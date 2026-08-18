"""API du récapitulatif et de la bibliothèque de documents."""

import datetime
import json
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access import est_direction
from .models import Affectation, Animateur, Centre, Document, PeriodeScolaire, PrimeJournalierePeriode
from .services.dates import parse_to_aware_datetime

logger = logging.getLogger(__name__)
from .services.documents import normaliser_nom_document, valider_periode_document
from .services.recapitulatif import generer_recapitulatif, generer_recapitulatif_excel, generer_recapitulatif_paie_pdf
from .services.serializers import document_to_dict

# ---------------------------------------------------------------------------
# API - Récapitulatif (statistiques pour la page de suivi)
# ---------------------------------------------------------------------------


def _selection_recapitulatif(request):
    """Valide et transforme la sélection commune à l'écran et au PDF."""
    periode_ids_bruts = request.GET.get("periode_ids", "").strip()
    mois_str = request.GET.get("mois", "").strip()
    date_debut_str = request.GET.get("date_debut", "").strip()
    date_fin_str = request.GET.get("date_fin", "").strip()
    periodes = []
    jours_selectionnes = None

    if periode_ids_bruts:
        try:
            periode_ids = [int(valeur) for valeur in periode_ids_bruts.split(",") if valeur.strip()]
        except ValueError:
            return None, None, None, None, "La sélection de périodes est invalide."

        if not periode_ids:
            return None, None, None, None, "Sélectionne au moins une période."

        periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
        if len(periodes) != len(set(periode_ids)):
            return None, None, None, None, "Une période sélectionnée est introuvable."

        jours_selectionnes = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in periodes
            for decalage in range((periode.fin - periode.debut).days + 1)
        }
        debut_date = min(jours_selectionnes)
        fin_date = max(jours_selectionnes) + datetime.timedelta(days=1)
        debut = timezone.make_aware(datetime.datetime.combine(debut_date, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(fin_date, datetime.time.min))
    elif mois_str:
        try:
            debut_date = datetime.date.fromisoformat(f"{mois_str}-01")
        except ValueError:
            return None, None, None, None, "Le mois sélectionné est invalide."
        mois_suivant = (
            debut_date.replace(year=debut_date.year + 1, month=1)
            if debut_date.month == 12
            else debut_date.replace(month=debut_date.month + 1)
        )
        dernier_jour = mois_suivant - datetime.timedelta(days=1)
        debut = timezone.make_aware(datetime.datetime.combine(debut_date, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(mois_suivant, datetime.time.min))
        periodes = list(
            PeriodeScolaire.objects.filter(debut__lte=dernier_jour, fin__gte=debut_date)
            .order_by("debut", "ordre", "nom")
        )
    elif date_debut_str or date_fin_str:
        if not date_debut_str or not date_fin_str:
            return None, None, None, None, "Les dates de début et de fin sont obligatoires."
        try:
            debut_date = datetime.date.fromisoformat(date_debut_str)
            dernier_jour = datetime.date.fromisoformat(date_fin_str)
        except ValueError:
            return None, None, None, None, "La période personnalisée est invalide."
        if dernier_jour < debut_date:
            return None, None, None, None, "La date de fin ne peut pas être antérieure à la date de début."
        fin_date = dernier_jour + datetime.timedelta(days=1)
        debut = timezone.make_aware(datetime.datetime.combine(debut_date, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(fin_date, datetime.time.min))
        periodes = list(
            PeriodeScolaire.objects.filter(debut__lte=dernier_jour, fin__gte=debut_date)
            .order_by("debut", "ordre", "nom")
        )
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

    if not debut or not fin:
        return None, None, None, None, "La période est invalide."
    if debut >= fin:
        return None, None, None, None, "La date de début doit être avant la date de fin."
    return debut, fin, jours_selectionnes, periodes, None


def _ajouter_preparation_paie(recap, periodes):
    """Enrichit le calcul commun avec les primes propres à chaque semaine."""

    periode_ids = [periode.id for periode in periodes]
    animateur_ids = [ligne["id"] for ligne in recap["animateurs"]]
    primes = {
        (prime.animateur_id, prime.periode_id): prime.montant
        for prime in PrimeJournalierePeriode.objects.filter(
            animateur_id__in=animateur_ids,
            periode_id__in=periode_ids,
        )
    }
    for ligne in recap["animateurs"]:
        montants = [primes.get((ligne["id"], periode_id), Decimal("0.00")) for periode_id in periode_ids]
        valeurs = set(montants)
        prime_variable = len(valeurs) > 1
        prime = montants[0] if montants and not prime_variable else None
        base = Decimal(ligne["paie_jour"]) if ligne["paie_jour"] is not None else None
        total_jour = base + prime if base is not None and prime is not None else None
        jours_affectation = {item["date"] for item in ligne["jours"]}
        dates_reunions = ligne.get("dates_reunions_comptabilisees", [])
        jours_par_periode = []
        for periode, montant_periode in zip(periodes, montants):
            jours = sum(
                1 for jour in jours_affectation
                if periode.debut.isoformat() <= jour <= periode.fin.isoformat()
            )
            jours += sum(
                1 for jour in dates_reunions
                if periode.debut.isoformat() <= jour <= periode.fin.isoformat()
            )
            jours_par_periode.append(Decimal(jours))
        # Une préparation sans date ne peut être rattachée sans ambiguïté
        # que lorsque la sélection contient une seule semaine. Elle n'est
        # surtout jamais divisée artificiellement entre plusieurs semaines.
        if len(periodes) == 1:
            jours_par_periode[0] += Decimal(str(ligne["jours_preparation"]))
        details = []
        total_prime = Decimal("0.00")
        for periode, montant_periode, jours in zip(periodes, montants, jours_par_periode):
            prime_semaine = (jours * montant_periode).quantize(Decimal("0.01"))
            total_prime += prime_semaine
            details.append({
                "periode_id": periode.id,
                "libelle": periode.libelle_avec_annee,
                "jours": int(jours) if jours == jours.to_integral_value() else float(jours),
                "prime_jour": str(montant_periode.quantize(Decimal("0.01"))),
                "montant_prime": str(prime_semaine),
            })
        paie_base = Decimal(ligne["paie_totale"]) if ligne["paie_totale"] is not None else None
        total_estime = paie_base + total_prime if paie_base is not None else None
        ligne["prime_jour"] = str(prime.quantize(Decimal("0.01"))) if prime is not None else None
        ligne["prime_jour_variable"] = prime_variable
        ligne["total_jour_avec_prime"] = str(total_jour.quantize(Decimal("0.01"))) if total_jour is not None else None
        ligne["total_paie_estime"] = str(total_estime.quantize(Decimal("0.01"))) if total_estime is not None else None
        ligne["paie_base"] = ligne["paie_totale"]
        ligne["montant_primes"] = str(total_prime.quantize(Decimal("0.01")))
        ligne["primes_detail"] = details
        ligne["prime_modifiable"] = bool(periode_ids and base is not None)

    recap["total_primes"] = str(sum(
        (Decimal(ligne["montant_primes"]) for ligne in recap["animateurs"]), Decimal("0.00")
    ).quantize(Decimal("0.01")))
    recap["total_paie_avec_primes"] = str(sum(
        (Decimal(ligne["total_paie_estime"]) for ligne in recap["animateurs"] if ligne["total_paie_estime"] is not None),
        Decimal("0.00"),
    ).quantize(Decimal("0.01")))


def api_recapitulatif(request):
    """Tableau de bord du planning sur une ou plusieurs périodes enregistrées."""

    debut, fin, jours_selectionnes, periodes, erreur = _selection_recapitulatif(request)
    if erreur:
        return JsonResponse({"error": erreur}, status=400)

    recap = generer_recapitulatif(
        debut,
        fin,
        jours_selectionnes=jours_selectionnes,
        periode_ids=[periode.id for periode in periodes] if jours_selectionnes is not None else None,
    )
    _ajouter_preparation_paie(recap, periodes)

    return JsonResponse(
        {
            "periode": {
                "debut": debut.date().isoformat(),
                "fin": (fin.date() - datetime.timedelta(days=1)).isoformat(),
                "ids": [periode.id for periode in periodes],
                "libelles": [periode.libelle_avec_annee for periode in periodes],
            },
            "dates": recap["dates"],
            "centres": recap["centres"],
            "animateurs": recap["animateurs"],
            "total_jours": recap["total_jours"],
            "total_paie_connue": recap["total_paie_connue"],
            "total_primes": recap["total_primes"],
            "total_paie_avec_primes": recap["total_paie_avec_primes"],
            "tarifs_manquants": recap["tarifs_manquants"],
        }
    )


@require_http_methods(["PUT", "DELETE"])
def api_prime_journaliere(request):
    """Valide en une transaction plusieurs primes sur plusieurs semaines."""

    try:
        payload = json.loads(request.body or "{}")
        periode_ids = list(dict.fromkeys(int(item) for item in payload.get("periode_ids", [])))
    except (AttributeError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError):
        return JsonResponse({"error": "La prime doit être un montant numérique valide."}, status=400)
    if not periode_ids:
        return JsonResponse({"error": "Sélectionne au moins une période."}, status=400)

    periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
    if len(periodes) != len(periode_ids):
        return JsonResponse({"error": "Une période sélectionnée est introuvable."}, status=400)

    if request.method == "DELETE":
        try:
            animateur_id = int(payload.get("animateur_id"))
        except (TypeError, ValueError):
            return JsonResponse({"error": "L'animateur transmis est invalide."}, status=400)
        if not Animateur.objects.filter(pk=animateur_id).exists():
            return JsonResponse({"error": "L'animateur transmis est introuvable."}, status=400)
        jours_selectionnes = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in periodes for decalage in range((periode.fin - periode.debut).days + 1)
        }
        debut = timezone.make_aware(datetime.datetime.combine(min(jours_selectionnes), datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(max(jours_selectionnes) + datetime.timedelta(days=1), datetime.time.min))
        with transaction.atomic():
            deleted_count, _ = PrimeJournalierePeriode.objects.filter(
                animateur_id=animateur_id, periode_id__in=periode_ids
            ).delete()
        recap = generer_recapitulatif(debut, fin, jours_selectionnes=jours_selectionnes, periode_ids=periode_ids)
        _ajouter_preparation_paie(recap, periodes)
        ligne = next((item for item in recap["animateurs"] if item["id"] == animateur_id), None)
        return JsonResponse({
            "success": True, "deleted_count": deleted_count,
            "animateur_id": animateur_id, "periode_ids": periode_ids,
            "animateur": ligne,
            "total_primes": recap["total_primes"],
            "total_paie_avec_primes": recap["total_paie_avec_primes"],
        })

    primes_payload = payload.get("primes")
    if primes_payload is None:  # compatibilité avec l'ancien client unitaire
        primes_payload = [{"animateur_id": payload.get("animateur_id"), "montant": payload.get("montant")}]
    if not isinstance(primes_payload, list) or not primes_payload:
        return JsonResponse({"error": "Aucune prime modifiée n'a été transmise."}, status=400)
    primes_validees = []
    try:
        for item in primes_payload:
            animateur_id = int(item.get("animateur_id"))
            montant = Decimal(str(item.get("montant")))
            if not montant.is_finite() or montant != montant.to_integral_value():
                return JsonResponse({"error": "La prime doit être indiquée en euros entiers."}, status=400)
            if montant < 0 or montant > 7:
                raise ValueError
            primes_validees.append((animateur_id, montant))
    except (AttributeError, TypeError, ValueError, InvalidOperation):
        return JsonResponse({"error": "Chaque prime doit être comprise entre 0 € et 7 €."}, status=400)
    animateur_ids = [item[0] for item in primes_validees]
    if len(set(animateur_ids)) != len(animateur_ids) or Animateur.objects.filter(pk__in=animateur_ids).count() != len(animateur_ids):
        return JsonResponse({"error": "Un animateur transmis est invalide ou présent deux fois."}, status=400)

    jours_selectionnes = {
        periode.debut + datetime.timedelta(days=decalage)
        for periode in periodes
        for decalage in range((periode.fin - periode.debut).days + 1)
    }
    debut = timezone.make_aware(datetime.datetime.combine(min(jours_selectionnes), datetime.time.min))
    fin = timezone.make_aware(
        datetime.datetime.combine(max(jours_selectionnes) + datetime.timedelta(days=1), datetime.time.min)
    )
    recap = generer_recapitulatif(
        debut,
        fin,
        jours_selectionnes=jours_selectionnes,
        periode_ids=periode_ids,
    )
    lignes = {item["id"]: item for item in recap["animateurs"]}
    if any(animateur_id not in lignes for animateur_id in animateur_ids):
        return JsonResponse({"error": "Un animateur n'a aucun jour travaillé sur cette sélection."}, status=400)
    if any(lignes[animateur_id]["paie_jour"] is None for animateur_id in animateur_ids):
        return JsonResponse({"error": "Renseigne d'abord tous les tarifs journaliers concernés."}, status=400)

    with transaction.atomic():
        for animateur_id, montant in primes_validees:
            for periode in periodes:
                if montant == 0:
                    PrimeJournalierePeriode.objects.filter(animateur_id=animateur_id, periode=periode).delete()
                else:
                    PrimeJournalierePeriode.objects.update_or_create(
                        animateur_id=animateur_id, periode=periode, defaults={"montant": montant}
                    )

    _ajouter_preparation_paie(recap, periodes)
    resultat = {
        "semaines_modifiees": len(periodes),
        "animateurs_modifies": len(primes_validees),
        "animateurs": [lignes[animateur_id] for animateur_id in animateur_ids],
    }
    if len(primes_validees) == 1:  # réponse historique conservée
        ligne = lignes[animateur_ids[0]]
        resultat.update({
            "animateur_id": animateur_ids[0],
            "prime_jour": ligne["prime_jour"],
            "total_jour_avec_prime": ligne["total_jour_avec_prime"],
            "total_paie_estime": ligne["total_paie_estime"],
        })
    return JsonResponse(resultat)


def export_recapitulatif_paie_pdf(request):
    """Télécharge les totaux de paie correspondant aux semaines sélectionnées."""

    debut, fin, jours_selectionnes, periodes, erreur = _selection_recapitulatif(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    recap = generer_recapitulatif(
        debut,
        fin,
        jours_selectionnes=jours_selectionnes,
        periode_ids=[periode.id for periode in periodes] if jours_selectionnes is not None else None,
    )
    _ajouter_preparation_paie(recap, periodes)
    dernier_jour = fin.date() - datetime.timedelta(days=1)
    contenu = generer_recapitulatif_paie_pdf(recap, debut.date(), dernier_jour)
    response = HttpResponse(contenu, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="recapitulatif_paie_{debut:%Y%m%d}_{dernier_jour:%Y%m%d}.pdf"'
    )
    return response


def export_recapitulatif_excel(request):
    """Télécharge le récapitulatif sélectionné sous forme de classeur Excel."""

    debut, fin, jours_selectionnes, periodes, erreur = _selection_recapitulatif(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    recap = generer_recapitulatif(
        debut, fin, jours_selectionnes=jours_selectionnes,
        periode_ids=[periode.id for periode in periodes] if jours_selectionnes is not None else None,
    )
    _ajouter_preparation_paie(recap, periodes)
    dernier_jour = fin.date() - datetime.timedelta(days=1)
    contenu = generer_recapitulatif_excel(recap, debut.date(), dernier_jour)
    response = HttpResponse(
        contenu,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="recapitulatif_{debut:%Y%m%d}_{dernier_jour:%Y%m%d}.xlsx"'
    )
    return response


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
        documents_qs = Document.objects.prefetch_related("periodes", "centres").all().order_by("-date_ajout")
        if not est_direction(request.user):
            animateur = getattr(request.user, "profil_animateur", None)
            if animateur is None:
                documents_qs = documents_qs.none()
            else:
                affectations = Affectation.objects.filter(animateur=animateur)
                documents_visibles = []
                for document in documents_qs.filter(publie=True):
                    affectations_document = affectations
                    if not document.permanent:
                        debut = timezone.make_aware(datetime.datetime.combine(document.periode_debut, datetime.time.min))
                        fin = timezone.make_aware(datetime.datetime.combine(document.periode_fin + datetime.timedelta(days=1), datetime.time.min))
                        affectations_document = affectations_document.filter(debut__lt=fin, fin__gt=debut)
                    if not document.tous_centres:
                        affectations_document = affectations_document.filter(centre_id__in=document.centres.all())
                    if (document.tous_centres and document.permanent) or affectations_document.exists():
                        documents_visibles.append(document)
                return JsonResponse([document_to_dict(d) for d in documents_visibles], safe=False)
        return JsonResponse([document_to_dict(d) for d in documents_qs], safe=False)

    titre = request.POST.get("titre", "").strip()
    fichier = request.FILES.get("fichier")
    permanent = str(request.POST.get("permanent", "")).lower() in {"1", "true", "on", "yes"}
    periode_ids_bruts = request.POST.getlist("periode_ids") or request.POST.getlist("periode_ids[]")
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in periode_ids_bruts))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)

    periodes = []
    periode_debut = None
    periode_fin = None
    if not permanent:
        periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
        if not periode_ids:
            return JsonResponse({"error": "Sélectionne au moins une semaine ou choisis Document permanent."}, status=400)
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

    publie = str(request.POST.get("publie", "true")).lower() in {"1", "true", "on", "yes"}
    tous_centres = str(request.POST.get("tous_centres", "true")).lower() in {"1", "true", "on", "yes"}
    centre_ids_bruts = request.POST.getlist("centre_ids") or request.POST.getlist("centre_ids[]")
    try:
        centre_ids = list(dict.fromkeys(int(value) for value in centre_ids_bruts))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de centres est invalide."}, status=400)
    centres = list(Centre.objects.filter(pk__in=centre_ids)) if not tous_centres else []
    if not tous_centres and (not centre_ids or len(centres) != len(centre_ids)):
        return JsonResponse({"error": "Sélectionne au moins un centre valide."}, status=400)
    nom_original = fichier.name
    nom_normalise = normaliser_nom_document(nom_original)
    fichier.name = nom_normalise
    stockage = Document._meta.get_field("fichier").storage
    backend_stockage = f"{stockage.__class__.__module__}.{stockage.__class__.__qualname__}"
    try:
        with transaction.atomic():
            document = Document.objects.create(
                titre=titre,
                publie=publie,
                fichier=fichier,
                permanent=permanent,
                periode_debut=periode_debut,
                periode_fin=periode_fin,
                tous_centres=tous_centres,
            )
            if periodes:
                document.periodes.set(periodes)
            document.centres.set(centres)
    except Exception as exc:
        logger.exception(
            "Échec du stockage d'un document : nom_original=%r nom_normalise=%r "
            "taille=%r type_mime=%r backend_stockage=%s exception_type=%s exception_detail=%r",
            nom_original,
            nom_normalise,
            getattr(fichier, "size", None),
            getattr(fichier, "content_type", None),
            backend_stockage,
            type(exc).__name__,
            str(exc),
        )
        return JsonResponse(
            {
                "error": "Le fichier n'a pas pu être enregistré. Réessaie plus tard."
            },
            status=503,
        )

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
    publie = bool(payload.get("publie", document.publie))
    permanent = bool(payload.get("permanent", document.permanent))
    tous_centres = bool(payload.get("tous_centres", document.tous_centres))
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in payload.get("periode_ids", [])))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)
    try:
        centre_ids = list(dict.fromkeys(int(value) for value in payload.get("centre_ids", [])))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de centres est invalide."}, status=400)
    centres = list(Centre.objects.filter(pk__in=centre_ids)) if not tous_centres else []
    if not tous_centres and (not centre_ids or len(centres) != len(centre_ids)):
        return JsonResponse({"error": "Sélectionne au moins un centre valide."}, status=400)

    if not titre:
        return JsonResponse({"error": "Le titre est obligatoire."}, status=400)

    periodes = []
    periode_debut = None
    periode_fin = None
    if not permanent:
        periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
        if not periode_ids:
            return JsonResponse({"error": "Sélectionne au moins une semaine ou choisis Document permanent."}, status=400)
        if len(periodes) != len(periode_ids):
            return JsonResponse({"error": "Une semaine sélectionnée est introuvable."}, status=400)
        periode_debut = min(periode.debut for periode in periodes)
        periode_fin = max(periode.fin for periode in periodes)

    document.titre = titre
    document.publie = publie
    document.permanent = permanent
    document.periode_debut = periode_debut
    document.periode_fin = periode_fin
    document.tous_centres = tous_centres
    document.save(update_fields=["titre", "publie", "permanent", "periode_debut", "periode_fin", "tous_centres"])
    document.periodes.set(periodes)
    document.centres.set(centres)

    return JsonResponse(document_to_dict(document))
