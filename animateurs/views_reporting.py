"""API du récapitulatif et de la bibliothèque de documents."""

import datetime
import json

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Document, PeriodeScolaire
from .services.dates import parse_to_aware_datetime
from .services.documents import valider_periode_document
from .services.recapitulatif import generer_recapitulatif
from .services.serializers import document_to_dict

# ---------------------------------------------------------------------------
# API - Récapitulatif (statistiques pour la page de suivi)
# ---------------------------------------------------------------------------


def api_recapitulatif(request):
    """Tableau de bord du planning sur une ou plusieurs périodes enregistrées.

    Le paramètre ``periode_ids`` contient les identifiants séparés par des
    virgules. Les semaines peuvent être discontinues : seules leurs dates sont
    intégrées aux calculs. L'ancien couple ``debut``/``fin`` reste accepté pour
    compatibilité avec les appels existants.
    """

    periode_ids_bruts = request.GET.get("periode_ids", "").strip()
    periodes = []
    jours_selectionnes = None

    if periode_ids_bruts:
        try:
            periode_ids = [int(valeur) for valeur in periode_ids_bruts.split(",") if valeur.strip()]
        except ValueError:
            return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)

        if not periode_ids:
            return JsonResponse({"error": "Sélectionne au moins une période."}, status=400)

        periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
        if len(periodes) != len(set(periode_ids)):
            return JsonResponse({"error": "Une période sélectionnée est introuvable."}, status=400)

        jours_selectionnes = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in periodes
            for decalage in range((periode.fin - periode.debut).days + 1)
        }
        debut_date = min(jours_selectionnes)
        fin_date = max(jours_selectionnes) + datetime.timedelta(days=1)
        debut = timezone.make_aware(datetime.datetime.combine(debut_date, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(fin_date, datetime.time.min))
    else:
        debut_str = request.GET.get("debut")
        fin_str = request.GET.get("fin")
        aujourd_hui = timezone.localdate()

        if debut_str:
            debut = parse_to_aware_datetime(debut_str)
        else:
            premier_jour = aujourd_hui.replace(day=1)
            debut = timezone.make_aware(datetime.datetime.combine(premier_jour, datetime.time.min))

        if fin_str:
            fin = parse_to_aware_datetime(fin_str)
        else:
            if aujourd_hui.month == 12:
                mois_suivant = aujourd_hui.replace(year=aujourd_hui.year + 1, month=1, day=1)
            else:
                mois_suivant = aujourd_hui.replace(month=aujourd_hui.month + 1, day=1)
            fin = timezone.make_aware(datetime.datetime.combine(mois_suivant, datetime.time.min))

    if debut >= fin:
        return JsonResponse({"error": "La date de début doit être avant la date de fin."}, status=400)

    recap = generer_recapitulatif(debut, fin, jours_selectionnes=jours_selectionnes)

    return JsonResponse(
        {
            "periode": {
                "debut": debut.date().isoformat(),
                "fin": fin.date().isoformat(),
                "ids": [periode.id for periode in periodes],
                "libelles": [periode.libelle_avec_annee for periode in periodes],
            },
            "dates": recap["dates"],
            "centres": recap["centres"],
            "animateurs": recap["animateurs"],
            "total_jours": recap["total_jours"],
            "total_paie_connue": recap["total_paie_connue"],
            "tarifs_manquants": recap["tarifs_manquants"],
        }
    )


# ---------------------------------------------------------------------------
# API - Documents (liste, upload, suppression)
# ---------------------------------------------------------------------------
# Particularité par rapport aux autres endpoints de ce fichier : la
# création se fait via un formulaire multipart/form-data (request.POST +
# request.FILES), pas du JSON, puisqu'il y a un fichier à envoyer. Le
# fichier est stocké via le backend configuré dans STORAGES (voir
# settings.py : ici un bucket S3 Supabase), donc `document.fichier.url`
# renvoie directement l'URL publique du fichier, quel que soit le
# stockage utilisé.


@require_http_methods(["GET", "POST"])
def api_documents(request):
    """GET : liste des documents (les plus récents en premier).
    POST : ajoute un document multipart avec son titre, son fichier et
    soit le statut permanent, soit une période début/fin."""

    if request.method == "GET":
        documents_qs = Document.objects.prefetch_related("periodes").all().order_by("-date_ajout")
        return JsonResponse([document_to_dict(d) for d in documents_qs], safe=False)

    titre = request.POST.get("titre", "").strip()
    fichier = request.FILES.get("fichier")
    permanent = False
    periode_ids_bruts = request.POST.getlist("periode_ids") or request.POST.getlist("periode_ids[]")
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in periode_ids_bruts))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)
    periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
    if not periode_ids:
        return JsonResponse({"error": "Sélectionne au moins une semaine."}, status=400)
    if len(periodes) != len(periode_ids):
        return JsonResponse({"error": "Une semaine sélectionnée est introuvable."}, status=400)
    periode_debut = min(periode.debut for periode in periodes)
    periode_fin = max(periode.fin for periode in periodes)

    if not titre or not fichier:
        return JsonResponse({"error": "Le titre et le fichier sont obligatoires."}, status=400)

    periode_debut, periode_fin, erreur = valider_periode_document(
        permanent=permanent,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
    )
    if erreur:
        return JsonResponse({"error": erreur}, status=400)

    document = Document.objects.create(
        titre=titre,
        fichier=fichier,
        permanent=False,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
    )
    document.periodes.set(periodes)

    return JsonResponse(document_to_dict(document), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_document_detail(request, document_id):
    """Supprime un document, y compris le fichier physique/distant
    associé (sans quoi il resterait orphelin dans le stockage)."""

    try:
        document = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return JsonResponse({"error": "Document introuvable."}, status=404)

    if request.method == "DELETE":
        document.fichier.delete(save=False)
        document.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide."}, status=400)

    titre = str(payload.get("titre", document.titre)).strip()
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in payload.get("periode_ids", [])))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)
    periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))

    if not titre:
        return JsonResponse({"error": "Le titre est obligatoire."}, status=400)
    if not periode_ids:
        return JsonResponse({"error": "Sélectionne au moins une semaine."}, status=400)
    if len(periodes) != len(periode_ids):
        return JsonResponse({"error": "Une semaine sélectionnée est introuvable."}, status=400)

    document.titre = titre
    document.permanent = False
    document.periode_debut = min(periode.debut for periode in periodes)
    document.periode_fin = max(periode.fin for periode in periodes)
    document.save(update_fields=["titre", "permanent", "periode_debut", "periode_fin"])
    document.periodes.set(periodes)

    return JsonResponse(document_to_dict(document))
