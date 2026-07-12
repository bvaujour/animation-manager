"""
Vues de l'application "animateurs".

Ce fichier regroupe :
  - les pages HTML (rendues via render(), pas grand-chose dedans : le vrai
    contenu est chargé en JS via les endpoints API ci-dessous) ;
  - une API JSON "maison" (pas de Django REST Framework ici, on répond
    directement avec JsonResponse) utilisée par les fichiers JS dans
    static/js/ (planning.js, gestion.js, recapitulatif.js).

Convention utilisée partout : les endpoints qui modifient des données
renvoient soit l'objet créé/modifié en JSON, soit {"error": "..."} avec un
code HTTP adapté (400 = requête invalide, 404 = introuvable,
409 = conflit métier comme un doublon ou un code déjà pris).
"""

import datetime
import json
import re

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_POST

from .models import Affectation, Animateur, Centre, Disponibilite, Document, Qualification

from .services.affectations import creer_affectation, modifier_affectation
from .services.animateurs import appliquer_centres_hierarchises, normaliser_centres_hierarchises
from .services.dates import parse_to_aware_datetime
from .services.disponibilites import (
    fusionner_et_nettoyer_disponibilites,
    nettoyer_disponibilites_tous_animateurs,
)
from .services.documents import valider_periode_document
from .services.recapitulatif import generer_recapitulatif
from .services.serializers import (
    affectation_to_event,
    animateur_to_dict,
    centre_to_dict,
    document_to_dict,
    qualification_to_dict,
)


# ---------------------------------------------------------------------------
# Pages HTML
# ---------------------------------------------------------------------------
# Chaque vue ci-dessous se contente de rendre un template quasi vide : les
# données sont chargées côté client par le JS correspondant (voir
# static/js/<nom-de-la-page>.js), qui appelle les endpoints API plus bas.

def accueil(request):
    return render(request, "accueil.html", {"active_page": "accueil"})


def planning(request):
    """Page principale : un calendrier par centre, avec la liste des
    animateurs à glisser-déposer ou à affecter par clic."""
    return render(request, "planning.html", {"active_page": "planning"})


def equipe(request):
    """Page dédiée à la gestion complète des animateurs."""
    return render(request, "equipe.html", {"active_page": "equipe"})


def gestion(request):
    """Page de gestion des paramètres : centres et qualifications."""
    return render(request, "gestion.html", {"active_page": "gestion"})


def recapitulatif(request):
    """Tableau de bord : jours travaillés par animateur/centre et alertes
    de suivi (animateurs jamais affectés, centres inutilisés, etc.)."""
    return render(request, "recapitulatif.html", {"active_page": "recapitulatif"})


def documents(request):
    """Page /documents/ : la liste elle-même est chargée dynamiquement en
    JS (voir static/js/documents.js + api_documents plus bas), cette vue
    ne fait que rendre le squelette de la page."""
    return render(request, "documents.html", {"active_page": "documents"})


# ---------------------------------------------------------------------------
# API - Animateurs (lecture, création, suppression)
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
def api_animateurs(request):
    """GET : liste tous les animateurs.
    POST : crée un animateur avec ses coordonnées, qualifications, un centre préféré et des centres secondaires."""

    if request.method == "GET":
        # Nettoyage opportuniste : on supprime les anciennes disponibilités
        # et on fusionne celles qui se chevauchent avant de les renvoyer au front.
        nettoyer_disponibilites_tous_animateurs()

        # prefetch_related évite le classique problème "N+1 requêtes" :
        # sans ça, chaque animateur referait une requête pour ses
        # qualifications et une pour ses centres autorisés.
        animateurs = Animateur.objects.prefetch_related(
            "qualifications",
            "preferences__centre",
            "disponibilites",
        ).all()

        return JsonResponse([animateur_to_dict(a) for a in animateurs], safe=False)

    try:
        payload = json.loads(request.body)

        prenom = payload["prenom"].strip()
        nom = payload["nom"].strip()
        telephone = payload.get("telephone", "").strip()
        email = payload.get("email", "").strip()
        date_naissance_raw = payload.get("date_naissance") or None
        date_naissance = parse_date(date_naissance_raw) if date_naissance_raw else None
        couleur = (payload.get("couleur") or "").strip()
        qualification_ids = payload.get("qualifications", [])
        centre_prefere, centres_secondaires, erreur_centres = normaliser_centres_hierarchises(payload)
        if erreur_centres:
            return JsonResponse({"error": erreur_centres}, status=400)

        if not prenom or not nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

        if date_naissance_raw and date_naissance is None:
            return JsonResponse({"error": "La date de naissance est invalide."}, status=400)

        if couleur and not re.fullmatch(r"#[0-9A-Fa-f]{6}", couleur):
            return JsonResponse({"error": "La couleur doit être au format #RRGGBB."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    with transaction.atomic():
        animateur = Animateur.objects.create(
            prenom=prenom,
            nom=nom,
            telephone=telephone,
            email=email,
            date_naissance=date_naissance,
            couleur=couleur,
        )

        if qualification_ids:
            # .set() sur un ManyToMany remplace toute la liste en une requête.
            animateur.qualifications.set(
                Qualification.objects.filter(pk__in=qualification_ids)
            )

        appliquer_centres_hierarchises(animateur, centre_prefere, centres_secondaires)

    animateur = Animateur.objects.prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    return JsonResponse(animateur_to_dict(animateur), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_animateur_detail(request, animateur_id):
    """GET : renvoie un animateur.
    PATCH : modifie un ou plusieurs champs de l'animateur, y compris ses qualifications et ses centres autorisés.
    DELETE : supprime l'animateur et, par cascade, son planning/disponibilités/centres autorisés."""

    try:
        animateur = Animateur.objects.prefetch_related(
            "qualifications",
            "preferences__centre",
            "disponibilites",
        ).get(pk=animateur_id)
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Animateur introuvable."}, status=404)

    if request.method == "GET":
        return JsonResponse(animateur_to_dict(animateur))

    if request.method == "DELETE":
        animateur.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)

        if "prenom" in payload:
            animateur.prenom = payload["prenom"].strip()

        if "nom" in payload:
            animateur.nom = payload["nom"].strip()

        if "telephone" in payload:
            animateur.telephone = payload.get("telephone", "").strip()

        if "email" in payload:
            animateur.email = payload.get("email", "").strip()

        if "date_naissance" in payload:
            date_naissance_raw = payload.get("date_naissance") or None
            date_naissance = parse_date(date_naissance_raw) if date_naissance_raw else None
            if date_naissance_raw and date_naissance is None:
                return JsonResponse({"error": "La date de naissance est invalide."}, status=400)
            animateur.date_naissance = date_naissance

        if "couleur" in payload:
            couleur = (payload.get("couleur") or "").strip()
            if couleur and not re.fullmatch(r"#[0-9A-Fa-f]{6}", couleur):
                return JsonResponse({"error": "La couleur doit être au format #RRGGBB."}, status=400)
            animateur.couleur = couleur

        if not animateur.prenom or not animateur.nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

        qualification_ids = payload.get("qualifications", None)
        centre_prefere, centres_secondaires, erreur_centres = normaliser_centres_hierarchises(payload)
        if erreur_centres:
            return JsonResponse({"error": erreur_centres}, status=400)

    except (TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    with transaction.atomic():
        animateur.save()

        if qualification_ids is not None:
            animateur.qualifications.set(
                Qualification.objects.filter(pk__in=qualification_ids)
            )

        appliquer_centres_hierarchises(animateur, centre_prefere, centres_secondaires)

    animateur = Animateur.objects.prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    return JsonResponse(animateur_to_dict(animateur))


@require_http_methods(["GET", "POST"])
def api_disponibilites(request, animateur_id):
    """GET : renvoie les plages de disponibilité d'un animateur.
    POST : ajoute rapidement une nouvelle plage de disponibilité.

    Payload POST attendu : {"debut": "YYYY-MM-DD", "fin": "YYYY-MM-DD"}.
    Les bornes sont incluses côté métier.
    """

    try:
        animateur = Animateur.objects.get(pk=animateur_id)
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Animateur introuvable."}, status=404)

    if request.method == "POST":
        try:
            payload = json.loads(request.body)
            debut = parse_date(payload["debut"])
            fin = parse_date(payload.get("fin") or payload["debut"])

            if debut is None or fin is None:
                raise ValueError("date invalide")
            if fin < debut:
                return JsonResponse({"error": "La date de fin doit être après la date de début."}, status=400)

        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            return JsonResponse({"error": "Requête invalide."}, status=400)

        Disponibilite.objects.create(animateur=animateur, debut=debut, fin=fin)

    fusionner_et_nettoyer_disponibilites(animateur)

    plages = [
        {
            "id": disponibilite.id,
            "debut": disponibilite.debut.isoformat(),
            "fin": disponibilite.fin.isoformat(),
        }
        for disponibilite in animateur.disponibilites.all()
    ]

    return JsonResponse({"disponibilites": plages})


@require_http_methods(["PATCH", "DELETE"])
def api_disponibilite_detail(request, animateur_id, disponibilite_id):
    """Modifie ou supprime une plage de disponibilité précise."""

    try:
        animateur = Animateur.objects.get(pk=animateur_id)
        disponibilite = Disponibilite.objects.get(pk=disponibilite_id, animateur=animateur)
    except (Animateur.DoesNotExist, Disponibilite.DoesNotExist):
        return JsonResponse({"error": "Disponibilité introuvable."}, status=404)

    if request.method == "DELETE":
        disponibilite.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)
        debut = parse_date(payload.get("debut"))
        fin = parse_date(payload.get("fin") or payload.get("debut"))
        if debut is None or fin is None:
            raise ValueError("date invalide")
        if fin < debut:
            return JsonResponse({"error": "La date de fin doit être après la date de début."}, status=400)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    disponibilite.debut = debut
    disponibilite.fin = fin
    disponibilite.save(update_fields=["debut", "fin"])
    fusionner_et_nettoyer_disponibilites(animateur)

    plages = [
        {"id": dispo.id, "debut": dispo.debut.isoformat(), "fin": dispo.fin.isoformat()}
        for dispo in animateur.disponibilites.all()
    ]
    return JsonResponse({"disponibilites": plages})


# ---------------------------------------------------------------------------
# API - Planning (lecture des évènements + écriture individuelle)
# ---------------------------------------------------------------------------

def api_planning(request):
    """Renvoie les affectations au format FullCalendar.

    FullCalendar envoie automatiquement `start` et `end` dans la requête.
    On filtre donc côté serveur pour ne renvoyer que la période affichée :
    cela évite de recharger inutilement tout l'historique et réduit les
    risques d'affichage incohérent après un déplacement/suppression.
    """

    centre_id = request.GET.get("centre_id")
    start = request.GET.get("start")
    end = request.GET.get("end")

    affectations = Affectation.objects.select_related("animateur", "centre")

    if centre_id:
        affectations = affectations.filter(centre_id=centre_id)

    if start and end:
        try:
            debut = parse_to_aware_datetime(start)
            fin = parse_to_aware_datetime(end)
            affectations = affectations.filter(debut__lt=fin, fin__gt=debut)
        except ValueError:
            return JsonResponse({"error": "Paramètres start/end invalides."}, status=400)

    events = [affectation_to_event(a) for a in affectations]

    return JsonResponse(events, safe=False)


@require_POST
def api_affectation_create(request):
    """Crée une affectation (glisser-déposer ou clic sur un jour dans le
    planning). Passe par _valider_affectation() pour refuser les doublons
    et les jours hors disponibilité."""

    try:
        payload = json.loads(request.body)

        animateur = Animateur.objects.get(pk=payload["animateur_id"])
        centre = Centre.objects.get(pk=payload["centre_id"])

        debut = parse_to_aware_datetime(payload["debut"])
        # Si "fin" n'est pas fourni, on suppose une affectation d'un seul
        # jour. ATTENTION : la convention "allDay" de FullCalendar veut une
        # borne de fin EXCLUSIVE, donc une journée = debut + 1 jour. Mettre
        # fin = debut donnerait un évènement de durée nulle (start == end)
        # qui ne s'affiche pas dans le calendrier.
        if payload.get("fin"):
            fin = parse_to_aware_datetime(payload["fin"])
        else:
            fin = debut + datetime.timedelta(days=1)

    except (Animateur.DoesNotExist, Centre.DoesNotExist):
        return JsonResponse({"error": "Animateur ou centre introuvable."}, status=404)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        affectation = creer_affectation(
            animateur=animateur, centre=centre, debut=debut, fin=fin
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)

    return JsonResponse(affectation_to_event(affectation), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_affectation_detail(request, affectation_id):
    """PATCH : déplacement ou redimensionnement d'une affectation existante
    dans le calendrier (revalidée comme à la création).
    DELETE : suppression d'une affectation (clic sur l'évènement)."""

    try:
        affectation = Affectation.objects.get(pk=affectation_id)
    except Affectation.DoesNotExist:
        return JsonResponse({"error": "Affectation introuvable."}, status=404)

    if request.method == "DELETE":
        affectation.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)

        # On applique les champs fournis directement sur l'objet en
        # mémoire (sans sauvegarder tout de suite), pour pouvoir valider
        # l'état final avant de l'enregistrer réellement.
        if "debut" in payload:
            affectation.debut = parse_to_aware_datetime(payload["debut"])

        if "fin" in payload:
            affectation.fin = parse_to_aware_datetime(payload["fin"])

        if "centre_id" in payload:
            affectation.centre = Centre.objects.get(pk=payload["centre_id"])

    except Centre.DoesNotExist:
        return JsonResponse({"error": "Centre introuvable."}, status=404)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        affectation = modifier_affectation(
            affectation,
            debut=affectation.debut,
            fin=affectation.fin,
            centre=affectation.centre,
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)

    return JsonResponse(affectation_to_event(affectation))


@require_http_methods(["DELETE"])
def api_planning_plage(request):
    """Supprime en une fois toutes les affectations (tous centres
    confondus) qui chevauchent une plage de dates donnée en query params
    (?debut=...&fin=...). C'est le bouton "Vider la semaine" du planning.

    Sécurité importante : on ne supprime JAMAIS de jours déjà passés,
    même si `debut` est antérieur à aujourd'hui — la borne de début
    réellement utilisée est toujours au plus tôt "maintenant". Ça évite
    qu'un vidage de semaine efface accidentellement l'historique de ce
    qui a déjà été travaillé.

    On renvoie le nombre de lignes supprimées pour que le message de
    confirmation côté front soit précis.
    """

    debut_str = request.GET.get("debut")
    fin_str = request.GET.get("fin")

    try:
        debut_demande = parse_to_aware_datetime(debut_str)
        fin = parse_to_aware_datetime(fin_str)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Paramètres debut/fin invalides."}, status=400)

    # Pour le bouton "Vider la semaine", on vide vraiment toute la
    # semaine affichée, même si certains jours sont déjà passés.
    # Sinon l'interface peut garder des affectations visibles et donner
    # l'impression que le calendrier n'a pas été remis à zéro.
    debut = debut_demande

    if debut >= fin:
        return JsonResponse({"error": "La date de début doit être avant la date de fin."}, status=400)

    # .delete() sur un queryset supprime tout en une seule requête SQL et
    # renvoie (nombre_total_supprime, détail_par_modèle).
    nb_supprimees, _detail = Affectation.objects.filter(
        debut__lt=fin,
        fin__gt=debut,
    ).delete()

    return JsonResponse({"supprimees": nb_supprimees})


# ---------------------------------------------------------------------------
# API - Gestion (CRUD centres / qualifications)
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
def api_centres(request):
    """GET : liste des centres. POST : création d'un centre."""

    if request.method == "GET":
        centres = Centre.objects.all()
        return JsonResponse([centre_to_dict(c) for c in centres], safe=False)

    try:
        payload = json.loads(request.body)

        nom = payload["nom"].strip()
        code = payload["code"].strip()
        couleur = payload.get("couleur", "#e03c00").strip() or "#e03c00"
        effectif_cible = int(payload.get("effectif_cible", 1) or 1)

        if not nom or not code:
            return JsonResponse({"error": "Le nom et le code sont obligatoires."}, status=400)

        if effectif_cible < 1:
            return JsonResponse({"error": "L'effectif souhaité doit être d'au moins 1."}, status=400)

    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        centre = Centre.objects.create(nom=nom, code=code, couleur=couleur, effectif_cible=effectif_cible)
    except IntegrityError:
        # Le champ `code` est unique en base (contrainte du modèle) :
        # on transforme l'erreur SQL brute en message compréhensible.
        return JsonResponse({"error": f"Le code « {code} » est déjà utilisé par un autre centre."}, status=409)

    return JsonResponse(centre_to_dict(centre), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_centre_detail(request, centre_id):
    """PATCH : met à jour un ou plusieurs champs d'un centre (utilisé pour
    ajuster l'effectif souhaité sans avoir à le recréer).
    DELETE : supprime le centre (et, par cascade, ses centres autorisés/
    affectations liées)."""

    try:
        centre = Centre.objects.get(pk=centre_id)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Centre introuvable."}, status=404)

    if request.method == "DELETE":
        centre.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)

        if "nom" in payload:
            centre.nom = payload["nom"].strip()

        if "code" in payload:
            centre.code = payload["code"].strip()

        if "couleur" in payload:
            centre.couleur = payload["couleur"].strip()

        if "effectif_cible" in payload:
            effectif_cible = int(payload["effectif_cible"])
            if effectif_cible < 1:
                return JsonResponse({"error": "L'effectif souhaité doit être d'au moins 1."}, status=400)
            centre.effectif_cible = effectif_cible

    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        centre.save()
    except IntegrityError:
        return JsonResponse({"error": f"Le code « {centre.code} » est déjà utilisé par un autre centre."}, status=409)

    return JsonResponse(centre_to_dict(centre))


@require_http_methods(["GET", "POST"])
def api_qualifications(request):
    """GET : liste des qualifications. POST : création d'une qualification."""

    if request.method == "GET":
        qualifications = Qualification.objects.all()
        return JsonResponse([qualification_to_dict(q) for q in qualifications], safe=False)

    try:
        payload = json.loads(request.body)
        nom = payload["nom"].strip()
        selectionnable_auto = bool(payload.get("selectionnable_remplissage_auto", False))

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    qualification = Qualification.objects.create(
        nom=nom,
        selectionnable_remplissage_auto=selectionnable_auto,
    )

    return JsonResponse(qualification_to_dict(qualification), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_qualification_detail(request, qualification_id):
    """GET : renvoie une qualification. PATCH : modifie son nom.
    DELETE : supprime la qualification (elle est simplement retirée de la liste
    des animateurs qui l'avaient, grâce au comportement par défaut de
    Django sur les relations ManyToMany)."""

    try:
        qualification = Qualification.objects.get(pk=qualification_id)
    except Qualification.DoesNotExist:
        return JsonResponse({"error": "Qualification introuvable."}, status=404)

    if request.method == "GET":
        return JsonResponse(qualification_to_dict(qualification))

    if request.method == "DELETE":
        qualification.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)
        nom = payload.get("nom", qualification.nom).strip()
        selectionnable_auto = bool(
            payload.get(
                "selectionnable_remplissage_auto",
                qualification.selectionnable_remplissage_auto,
            )
        )

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    qualification.nom = nom
    qualification.selectionnable_remplissage_auto = selectionnable_auto
    qualification.save(update_fields=["nom", "selectionnable_remplissage_auto"])

    return JsonResponse(qualification_to_dict(qualification))


# ---------------------------------------------------------------------------
# API - Récapitulatif (statistiques pour la page de suivi)
# ---------------------------------------------------------------------------

def api_recapitulatif(request):
    """Récapitulatif simple sur une période donnée.

    Objectif de la page : renseigner une période et voir, pour chaque
    animateur, combien de jours il a travaillé au total et dans chaque centre.

    Convention de dates :
      - `debut` est inclus ;
      - `fin` est exclusif, comme FullCalendar.

    Si aucune période n'est fournie, on utilise par défaut le mois courant.
    """

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

    centres, animateurs_data = generer_recapitulatif(debut, fin)

    return JsonResponse({
        "periode": {
            "debut": debut.date().isoformat(),
            # On renvoie aussi la fin exclusive pour rester cohérent avec l'API.
            "fin": fin.date().isoformat(),
        },
        "centres": [
            {
                "id": centre.id,
                "nom": centre.nom,
                "code": centre.code,
                "couleur": centre.couleur,
            }
            for centre in centres
        ],
        "animateurs": animateurs_data,
    })

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
        documents_qs = Document.objects.all().order_by("-permanent", "-periode_debut", "-date_ajout")
        return JsonResponse([document_to_dict(d) for d in documents_qs], safe=False)

    titre = request.POST.get("titre", "").strip()
    fichier = request.FILES.get("fichier")
    permanent = request.POST.get("permanent", "false").lower() in {"1", "true", "on", "yes"}
    periode_debut = parse_date(request.POST.get("periode_debut", ""))
    periode_fin = parse_date(request.POST.get("periode_fin", ""))

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
        permanent=permanent,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
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
    permanent = bool(payload.get("permanent", document.permanent))
    periode_debut = parse_date(payload.get("periode_debut") or "")
    periode_fin = parse_date(payload.get("periode_fin") or "")

    if not titre:
        return JsonResponse({"error": "Le titre est obligatoire."}, status=400)

    periode_debut, periode_fin, erreur = valider_periode_document(
        permanent=permanent,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
    )
    if erreur:
        return JsonResponse({"error": erreur}, status=400)

    document.titre = titre
    document.permanent = permanent
    document.periode_debut = periode_debut
    document.periode_fin = periode_fin
    document.full_clean()
    document.save(update_fields=["titre", "permanent", "periode_debut", "periode_fin"])

    return JsonResponse(document_to_dict(document))


@require_POST
def api_planning_auto(request):
    """Endpoint HTTP du remplissage automatique.

    La logique métier est dans animateurs.services.planning_solver pour
    garder ce fichier concentré sur les entrées/sorties HTTP.
    """

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Requête invalide."}, status=400)

    from .services.planning_solver import generer_planning_auto

    data, status = generer_planning_auto(payload)
    return JsonResponse(data, status=status)
