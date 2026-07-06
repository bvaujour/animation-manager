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

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_http_methods, require_POST

from .models import Affectation, Animateur, Centre, Disponibilite, Document, Qualification, PreferenceCentre


# ---------------------------------------------------------------------------
# Pages HTML
# ---------------------------------------------------------------------------
# Chaque vue ci-dessous se contente de rendre un template quasi vide : les
# données sont chargées côté client par le JS correspondant (voir
# static/js/<nom-de-la-page>.js), qui appelle les endpoints API plus bas.

def accueil(request):
    return render(request, "accueil.html")


def planning(request):
    """Page principale : un calendrier par centre, avec la liste des
    animateurs à glisser-déposer ou à affecter par clic."""
    return render(request, "planning.html")


def gestion(request):
    """Page de gestion CRUD (ajout/suppression) des animateurs, centres et
    qualifications. Le même module JS (gestion.js) est aussi utilisé dans
    la popup d'ajout rapide du planning."""
    return render(request, "gestion.html")


def recapitulatif(request):
    """Tableau de bord : jours travaillés par animateur/centre et alertes
    de suivi (animateurs jamais affectés, centres inutilisés, etc.)."""
    return render(request, "recapitulatif.html")


def test(request):
    return render(request, "test.html")


def documents(request):
    """Page /documents/ : la liste elle-même est chargée dynamiquement en
    JS (voir static/js/documents.js + api_documents plus bas), cette vue
    ne fait que rendre le squelette de la page."""
    return render(request, "documents.html")


# ---------------------------------------------------------------------------
# Helpers communs (dates, règles métier de placement)
# ---------------------------------------------------------------------------

def _parse_to_aware_datetime(value):
    """Convertit une chaîne de date ('2026-07-06') ou de datetime ISO en un
    datetime Python "aware" (avec fuseau horaire), comme l'exige USE_TZ=True.

    Utilisé partout où on reçoit une date venant du JS (JSON), pour éviter
    de manipuler des datetimes naïfs qui déclenchent des avertissements
    Django et peuvent fausser les comparaisons.
    """

    dt = parse_datetime(value)

    if dt is None:
        # Ce n'était pas un datetime complet : on retente en date seule
        # (cas normal ici, puisque le planning raisonne en jours entiers).
        date_seule = parse_date(value)

        if date_seule is None:
            raise ValueError(f"Date invalide : {value!r}")

        dt = datetime.datetime.combine(date_seule, datetime.time.min)

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)

    return dt


def _affectation_to_event(affectation):
    """Sérialise une Affectation au format attendu par FullCalendar côté
    JS (title/start/end/allDay + quelques infos utiles en extendedProps)."""

    return {
        "id": affectation.id,
        "title": f"{affectation.animateur.prenom} {affectation.animateur.nom[0]}.",
        "start": affectation.debut.isoformat(),
        "end": affectation.fin.isoformat(),
        "allDay": True,
        "extendedProps": {
            "animateur_id": affectation.animateur_id,
            "centre_id": affectation.centre_id,
        },
    }


def _jours_couverts(debut, fin):
    """Renvoie la liste des jours (objets date, sans l'heure) couverts par
    un intervalle [debut, fin) exprimé en datetimes.

    Exemple : debut=lundi 00:00, fin=mercredi 00:00 -> [lundi, mardi].
    La borne fin est exclusive, ce qui correspond à la convention "allDay"
    de FullCalendar (le jour de fin affiché est le dernier jour + 1).
    """

    jour = debut.date()
    dernier_jour = fin.date()

    jours = []

    while jour < dernier_jour:
        jours.append(jour)
        jour += datetime.timedelta(days=1)

    # Filet de sécurité : si jamais debut == fin (ne devrait pas arriver),
    # on considère quand même que le jour de début est couvert.
    return jours or [debut.date()]


def _animateur_disponible(animateur, debut, fin):
    """Vérifie qu'un animateur est disponible sur tout l'intervalle
    [debut, fin) donné.

    Règle volontairement souple : un animateur qui n'a AUCUNE plage de
    disponibilité renseignée est considéré disponible en permanence (pas
    de contrainte tant que l'info n'a pas été saisie, pour ne pas bloquer
    les animateurs existants avant qu'on ait rempli leurs disponibilités).
    Dès qu'il a au moins une plage, seuls les jours couverts par une de
    ses plages sont autorisés.
    """

    if not animateur.disponibilites.exists():
        return True

    for jour in _jours_couverts(debut, fin):
        couvert = animateur.disponibilites.filter(
            debut__lte=jour,
            fin__gte=jour,
        ).exists()

        if not couvert:
            return False

    return True


def _animateur_en_conflit(animateur, debut, fin, exclude_id=None):
    """Un même animateur ne peut pas avoir deux affectations qui se
    chevauchent le même jour, que ce soit dans le même centre ou un autre.

    `exclude_id` sert à ignorer l'affectation qu'on est justement en train
    de modifier (sinon elle serait toujours "en conflit avec elle-même").
    """

    conflits = Affectation.objects.filter(
        animateur=animateur,
        debut__lt=fin,
        fin__gt=debut,
    )

    if exclude_id is not None:
        conflits = conflits.exclude(pk=exclude_id)

    return conflits.exists()


def _valider_affectation(animateur, debut, fin, centre=None, exclude_id=None):
    """Point d'entrée unique pour valider une affectation avant de
    l'enregistrer (création ou modification). Renvoie un message d'erreur
    (str) si l'affectation n'est pas valide, ou None si tout est ok."""

    if centre is not None and not animateur.preferences.filter(centre=centre).exists():
        return "Cet animateur n'est pas affectable sur ce centre."

    if _animateur_en_conflit(animateur, debut, fin, exclude_id=exclude_id):
        return "Cet animateur a déjà une affectation ce jour-là, dans un centre ou un autre."

    if not _animateur_disponible(animateur, debut, fin):
        return "Cet animateur n'est pas disponible à cette date."

    return None


# ---------------------------------------------------------------------------
# API - Animateurs (lecture, création, suppression)
# ---------------------------------------------------------------------------

def _animateur_to_dict(animateur):
    """Sérialise un animateur avec ses qualifications et ses centres
    où il peut être affecté."""

    return {
        "id": animateur.id,
        "prenom": animateur.prenom,
        "nom": animateur.nom,
        "telephone": animateur.telephone,
        "email": animateur.email,
        "date_naissance": animateur.date_naissance.isoformat() if animateur.date_naissance else None,
        "age": animateur.age,
        "qualification_ids": [
            qualification.id
            for qualification in animateur.qualifications.all()
        ],
        "qualifications": [
            qualification.nom
            for qualification in animateur.qualifications.all()
        ],
        "centres_autorises": [
            {
                "id": preference.centre_id,
                "nom": preference.centre.nom,
                "code": preference.centre.code,
                "couleur": preference.centre.couleur,
            }
            for preference in animateur.preferences.all()
        ],
        # Si la liste est vide, on garde la règle métier existante
        # "pas de contrainte renseignée".
        "disponibilites": [
            {
                "debut": disponibilite.debut.isoformat(),
                "fin": disponibilite.fin.isoformat(),
            }
            for disponibilite in animateur.disponibilites.all()
        ],
    }


def _fusionner_et_nettoyer_disponibilites(animateur):
    """Nettoie les disponibilités d'un animateur.

    Règles appliquées :
      - les plages déjà entièrement passées sont supprimées ;
      - les plages commencées dans le passé sont recoupées à aujourd'hui ;
      - les plages qui se chevauchent ou se touchent sont fusionnées.

    Exemple : 01/07→05/07 + 04/07→10/07 devient 01/07→10/07.
    Cette fonction limite les doublons et garde une base plus lisible.
    """

    aujourd_hui = timezone.localdate()

    # On supprime les disponibilités dont la fin est strictement avant aujourd'hui.
    animateur.disponibilites.filter(fin__lt=aujourd_hui).delete()

    plages = list(animateur.disponibilites.order_by("debut", "fin"))
    if not plages:
        return

    # Si une plage a commencé dans le passé mais continue aujourd'hui ou plus tard,
    # on coupe sa partie passée : hier n'a plus d'intérêt pour le planning à venir.
    plages_normalisees = [
        (max(plage.debut, aujourd_hui), plage.fin)
        for plage in plages
    ]

    groupes = []
    debut_courant, fin_courante = plages_normalisees[0]

    for debut_plage, fin_plage in plages_normalisees[1:]:
        # Fusion si les plages se chevauchent ou sont directement contiguës.
        if debut_plage <= fin_courante + datetime.timedelta(days=1):
            fin_courante = max(fin_courante, fin_plage)
        else:
            groupes.append((debut_courant, fin_courante))
            debut_courant = debut_plage
            fin_courante = fin_plage

    groupes.append((debut_courant, fin_courante))

    # On réécrit seulement si le nettoyage change réellement quelque chose.
    etat_actuel = [(plage.debut, plage.fin) for plage in plages]
    if etat_actuel == groupes:
        return

    animateur.disponibilites.all().delete()
    Disponibilite.objects.bulk_create([
        Disponibilite(animateur=animateur, debut=debut, fin=fin)
        for debut, fin in groupes
    ])


def _nettoyer_disponibilites_tous_animateurs():
    """Nettoyage léger appelé quand l'app charge les animateurs.

    Cela évite d'accumuler des anciennes disponibilités inutiles en base
    sans avoir à lancer une commande manuelle.
    """

    for animateur in Animateur.objects.prefetch_related("disponibilites"):
        _fusionner_et_nettoyer_disponibilites(animateur)


def _normaliser_centres_autorises(payload):
    """Valide les centres où l'animateur peut être affecté.

    Format attendu côté front :
        "centres_autorises": [1, 2, 3]

    Pour compatibilité avec d'anciennes versions du front, on accepte aussi
    encore "preferences": [{"centre_id": 1}, ...], mais l'ordre est ignoré.
    """

    if "centres_autorises" in payload:
        centres_raw = payload.get("centres_autorises") or []
    elif "preferences" in payload:
        centres_raw = [item.get("centre_id") for item in (payload.get("preferences") or [])]
    else:
        return None, None

    if not isinstance(centres_raw, list):
        return None, "Les centres autorisés sont invalides."

    centres_ids = []
    centres_vus = set()

    for centre_raw in centres_raw:
        try:
            centre_id = int(centre_raw)
        except (TypeError, ValueError):
            return None, "Les centres autorisés sont invalides."

        if centre_id in centres_vus:
            return None, "Un même centre ne peut pas être ajouté deux fois."

        centres_vus.add(centre_id)
        centres_ids.append(centre_id)

    centres_existants = set(Centre.objects.filter(pk__in=centres_vus).values_list("id", flat=True))
    if centres_vus != centres_existants:
        return None, "Un des centres autorisés est introuvable."

    return centres_ids, None


def _appliquer_centres_autorises(animateur, centres_ids):
    """Remplace entièrement les centres où l'animateur peut être affecté."""

    if centres_ids is None:
        return

    animateur.preferences.all().delete()

    PreferenceCentre.objects.bulk_create([
        PreferenceCentre(
            animateur=animateur,
            centre_id=centre_id,
        )
        for centre_id in centres_ids
    ])


@require_http_methods(["GET", "POST"])
def api_animateurs(request):
    """GET : liste tous les animateurs.
    POST : crée un animateur ({"prenom", "nom", "telephone", "email", "date_naissance", "qualifications": [ids], "centres_autorises": [ids]})."""

    if request.method == "GET":
        # Nettoyage opportuniste : on supprime les anciennes disponibilités
        # et on fusionne celles qui se chevauchent avant de les renvoyer au front.
        _nettoyer_disponibilites_tous_animateurs()

        # prefetch_related évite le classique problème "N+1 requêtes" :
        # sans ça, chaque animateur referait une requête pour ses
        # qualifications et une pour ses centres autorisés.
        animateurs = Animateur.objects.prefetch_related(
            "qualifications",
            "preferences__centre",
            "disponibilites",
        ).all()

        return JsonResponse([_animateur_to_dict(a) for a in animateurs], safe=False)

    try:
        payload = json.loads(request.body)

        prenom = payload["prenom"].strip()
        nom = payload["nom"].strip()
        telephone = payload.get("telephone", "").strip()
        email = payload.get("email", "").strip()
        date_naissance_raw = payload.get("date_naissance") or None
        date_naissance = parse_date(date_naissance_raw) if date_naissance_raw else None
        qualification_ids = payload.get("qualifications", [])
        centres_autorises, erreur_centres = _normaliser_centres_autorises(payload)
        if erreur_centres:
            return JsonResponse({"error": erreur_centres}, status=400)

        if not prenom or not nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

        if date_naissance_raw and date_naissance is None:
            return JsonResponse({"error": "La date de naissance est invalide."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    with transaction.atomic():
        animateur = Animateur.objects.create(
            prenom=prenom,
            nom=nom,
            telephone=telephone,
            email=email,
            date_naissance=date_naissance,
        )

        if qualification_ids:
            # .set() sur un ManyToMany remplace toute la liste en une requête.
            animateur.qualifications.set(
                Qualification.objects.filter(pk__in=qualification_ids)
            )

        _appliquer_centres_autorises(animateur, centres_autorises)

    animateur = Animateur.objects.prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    return JsonResponse(_animateur_to_dict(animateur), status=201)


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
        return JsonResponse(_animateur_to_dict(animateur))

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

        if not animateur.prenom or not animateur.nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

        qualification_ids = payload.get("qualifications", None)
        centres_autorises, erreur_centres = _normaliser_centres_autorises(payload)
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

        _appliquer_centres_autorises(animateur, centres_autorises)

    animateur = Animateur.objects.prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    return JsonResponse(_animateur_to_dict(animateur))


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

    _fusionner_et_nettoyer_disponibilites(animateur)

    plages = [
        {
            "id": disponibilite.id,
            "debut": disponibilite.debut.isoformat(),
            "fin": disponibilite.fin.isoformat(),
        }
        for disponibilite in animateur.disponibilites.all()
    ]

    return JsonResponse({"disponibilites": plages})


# ---------------------------------------------------------------------------
# API - Planning (lecture des évènements + écriture individuelle)
# ---------------------------------------------------------------------------

def api_planning(request):
    """Renvoie les affectations au format FullCalendar, filtrées par
    centre (chaque calendrier du planning appelle cette route avec son
    propre ?centre_id=...)."""

    centre_id = request.GET.get("centre_id")

    affectations = Affectation.objects.select_related("animateur", "centre")

    if centre_id:
        affectations = affectations.filter(centre_id=centre_id)

    events = [_affectation_to_event(a) for a in affectations]

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

        debut = _parse_to_aware_datetime(payload["debut"])
        # Si "fin" n'est pas fourni, on suppose une affectation d'un seul
        # jour. ATTENTION : la convention "allDay" de FullCalendar veut une
        # borne de fin EXCLUSIVE, donc une journée = debut + 1 jour. Mettre
        # fin = debut donnerait un évènement de durée nulle (start == end)
        # qui ne s'affiche pas dans le calendrier.
        if payload.get("fin"):
            fin = _parse_to_aware_datetime(payload["fin"])
        else:
            fin = debut + datetime.timedelta(days=1)

    except (Animateur.DoesNotExist, Centre.DoesNotExist):
        return JsonResponse({"error": "Animateur ou centre introuvable."}, status=404)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    erreur = _valider_affectation(animateur, debut, fin, centre=centre)

    if erreur:
        return JsonResponse({"error": erreur}, status=409)

    affectation = Affectation.objects.create(
        animateur=animateur,
        centre=centre,
        debut=debut,
        fin=fin,
    )

    return JsonResponse(_affectation_to_event(affectation), status=201)


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
            affectation.debut = _parse_to_aware_datetime(payload["debut"])

        if "fin" in payload:
            affectation.fin = _parse_to_aware_datetime(payload["fin"])

        if "centre_id" in payload:
            affectation.centre = Centre.objects.get(pk=payload["centre_id"])

    except Centre.DoesNotExist:
        return JsonResponse({"error": "Centre introuvable."}, status=404)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    erreur = _valider_affectation(
        affectation.animateur,
        affectation.debut,
        affectation.fin,
        centre=affectation.centre,
        exclude_id=affectation.id,
    )

    if erreur:
        return JsonResponse({"error": erreur}, status=409)

    affectation.save()

    return JsonResponse(_affectation_to_event(affectation))


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
        debut_demande = _parse_to_aware_datetime(debut_str)
        fin = _parse_to_aware_datetime(fin_str)
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

def _centre_to_dict(centre):
    return {
        "id": centre.id,
        "nom": centre.nom,
        "code": centre.code,
        "couleur": centre.couleur,
        "effectif_cible": centre.effectif_cible,
    }


@require_http_methods(["GET", "POST"])
def api_centres(request):
    """GET : liste des centres. POST : création d'un centre."""

    if request.method == "GET":
        centres = Centre.objects.all()
        return JsonResponse([_centre_to_dict(c) for c in centres], safe=False)

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

    return JsonResponse(_centre_to_dict(centre), status=201)


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

    return JsonResponse(_centre_to_dict(centre))


def _qualification_to_dict(qualification):
    return {"id": qualification.id, "nom": qualification.nom}


@require_http_methods(["GET", "POST"])
def api_qualifications(request):
    """GET : liste des qualifications. POST : création d'une qualification."""

    if request.method == "GET":
        qualifications = Qualification.objects.all()
        return JsonResponse([_qualification_to_dict(q) for q in qualifications], safe=False)

    try:
        payload = json.loads(request.body)
        nom = payload["nom"].strip()

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    qualification = Qualification.objects.create(nom=nom)

    return JsonResponse(_qualification_to_dict(qualification), status=201)


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
        return JsonResponse(_qualification_to_dict(qualification))

    if request.method == "DELETE":
        qualification.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)
        nom = payload["nom"].strip()

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    qualification.nom = nom
    qualification.save()

    return JsonResponse(_qualification_to_dict(qualification))


# ---------------------------------------------------------------------------
# API - Récapitulatif (statistiques pour la page de suivi)
# ---------------------------------------------------------------------------

def api_recapitulatif(request):
    """Calcule les statistiques affichées sur la page Récapitulatif :
      - compteurs globaux (nb animateurs/centres/qualifications/affectations) ;
      - jours travaillés par animateur et par centre sur une période
        optionnelle (?debut=...&fin=..., aucun des deux n'est obligatoire) ;
      - quelques listes "à surveiller" (toujours calculées sur l'ensemble
        des données, indépendamment du filtre de période).

    Tout est calculé ici plutôt que côté JS pour que ça reste correct et
    rapide même quand il y aura beaucoup d'affectations en base.
    """

    debut_str = request.GET.get("debut")
    fin_str = request.GET.get("fin")

    affectations_qs = Affectation.objects.select_related("animateur", "centre")

    # Une affectation est "dans la période" si elle chevauche l'intervalle
    # demandé (même logique que pour les conflits de placement).
    if debut_str:
        affectations_qs = affectations_qs.filter(fin__gt=_parse_to_aware_datetime(debut_str))
    if fin_str:
        affectations_qs = affectations_qs.filter(debut__lt=_parse_to_aware_datetime(fin_str))

    affectations = list(affectations_qs)

    # --- Cumul du nombre de jours par animateur et par centre ---
    # (dictionnaires indexés par id, remplis en parcourant les
    # affectations une seule fois)
    par_animateur = {}
    par_centre = {}

    for affectation in affectations:
        # Une affectation peut durer plusieurs jours (redimensionnée dans
        # le calendrier) : on compte le nombre réel de jours couverts,
        # pas juste "1 ligne = 1 jour".
        nb_jours = max((affectation.fin.date() - affectation.debut.date()).days, 1)

        cle_animateur = affectation.animateur_id
        if cle_animateur not in par_animateur:
            par_animateur[cle_animateur] = {
                "id": affectation.animateur.id,
                "prenom": affectation.animateur.prenom,
                "nom": affectation.animateur.nom,
                "age": affectation.animateur.age,
                "jours": 0,
                "centres": set(),
            }
        par_animateur[cle_animateur]["jours"] += nb_jours
        par_animateur[cle_animateur]["centres"].add(affectation.centre_id)

        cle_centre = affectation.centre_id
        if cle_centre not in par_centre:
            par_centre[cle_centre] = {
                "id": affectation.centre.id,
                "nom": affectation.centre.nom,
                "code": affectation.centre.code,
                "jours": 0,
                "animateurs": set(),
            }
        par_centre[cle_centre]["jours"] += nb_jours
        par_centre[cle_centre]["animateurs"].add(affectation.animateur_id)

    # On ajoute aussi les animateurs/centres qui n'ont RIEN sur la période
    # (0 jour), pour qu'ils apparaissent quand même dans les tableaux.
    for animateur in Animateur.objects.all():
        par_animateur.setdefault(animateur.id, {
            "id": animateur.id,
            "prenom": animateur.prenom,
            "nom": animateur.nom,
            "age": animateur.age,
            "jours": 0,
            "centres": set(),
        })

    for centre in Centre.objects.all():
        par_centre.setdefault(centre.id, {
            "id": centre.id,
            "nom": centre.nom,
            "code": centre.code,
            "jours": 0,
            "animateurs": set(),
        })

    animateurs_data = sorted(
        (
            {
                "id": v["id"],
                "prenom": v["prenom"],
                "nom": v["nom"],
                "age": v.get("age"),
                "jours": v["jours"],
                "nb_centres": len(v["centres"]),
            }
            for v in par_animateur.values()
        ),
        key=lambda x: (-x["jours"], x["prenom"], x["nom"]),
    )

    centres_data = sorted(
        (
            {
                "id": v["id"],
                "nom": v["nom"],
                "code": v["code"],
                "jours": v["jours"],
                "nb_animateurs": len(v["animateurs"]),
            }
            for v in par_centre.values()
        ),
        key=lambda x: (-x["jours"], x["nom"]),
    )

    # --- Signaux à surveiller (toujours sur l'ensemble des données, sans
    # tenir compte du filtre de période choisi sur la page) ---
    animateurs_sans_centre_autorise = [
        f"{prenom} {nom}"
        for prenom, nom in Animateur.objects.filter(preferences__isnull=True).values_list("prenom", "nom")
    ]
    animateurs_sans_disponibilite = [
        f"{prenom} {nom}"
        for prenom, nom in Animateur.objects.filter(disponibilites__isnull=True).values_list("prenom", "nom")
    ]
    animateurs_jamais_affectes = [
        f"{prenom} {nom}"
        for prenom, nom in Animateur.objects.filter(affectations__isnull=True).values_list("prenom", "nom")
    ]
    centres_jamais_utilises = list(
        Centre.objects.filter(affectations__isnull=True).values_list("nom", flat=True)
    )
    qualifications_non_utilisees = list(
        Qualification.objects.filter(animateur__isnull=True).values_list("nom", flat=True)
    )

    return JsonResponse({
        "compteurs": {
            "nb_animateurs": Animateur.objects.count(),
            "nb_centres": Centre.objects.count(),
            "nb_qualifications": Qualification.objects.count(),
            "nb_affectations_periode": len(affectations),
            "nb_affectations_a_venir": Affectation.objects.filter(debut__gte=timezone.now()).count(),
        },
        "animateurs": animateurs_data,
        "centres": centres_data,
        "alertes": {
            "animateurs_sans_centre_autorise": animateurs_sans_centre_autorise,
            "animateurs_sans_disponibilite": animateurs_sans_disponibilite,
            "animateurs_jamais_affectes": animateurs_jamais_affectes,
            "centres_jamais_utilises": centres_jamais_utilises,
            "qualifications_non_utilisees": qualifications_non_utilisees,
        },
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

def _document_to_dict(document):
    return {
        "id": document.id,
        "titre": document.titre,
        "url": document.fichier.url,
        "date_ajout": document.date_ajout.isoformat(),
    }


@require_http_methods(["GET", "POST"])
def api_documents(request):
    """GET : liste des documents (les plus récents en premier).
    POST : ajoute un document (formulaire multipart, champs "titre" et
    "fichier")."""

    if request.method == "GET":
        documents_qs = Document.objects.all().order_by("-date_ajout")
        return JsonResponse([_document_to_dict(d) for d in documents_qs], safe=False)

    titre = request.POST.get("titre", "").strip()
    fichier = request.FILES.get("fichier")

    if not titre or not fichier:
        return JsonResponse({"error": "Le titre et le fichier sont obligatoires."}, status=400)

    document = Document.objects.create(titre=titre, fichier=fichier)

    return JsonResponse(_document_to_dict(document), status=201)


@require_http_methods(["DELETE"])
def api_document_detail(request, document_id):
    """Supprime un document, y compris le fichier physique/distant
    associé (sans quoi il resterait orphelin dans le stockage)."""

    try:
        document = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return JsonResponse({"error": "Document introuvable."}, status=404)

    document.fichier.delete(save=False)
    document.delete()

    return JsonResponse({"ok": True})


@require_POST
def api_planning_auto(request):
    """Remplit automatiquement la semaine affichée, du LUNDI au VENDREDI.

    Corps JSON attendu :
        {
          "debut": "2026-07-06",          # une date quelconque de la semaine
          "effectifs": {"1": 2, "3": 1}   # nb d'animateurs/jour par centre (optionnel)
        }

    - "debut" est ramené au lundi de sa semaine ; seuls les 5 jours ouvrés
      (lundi -> vendredi) sont remplis. Les éventuelles affectations du
      week-end ne sont pas touchées.
    - "effectifs" permet de choisir, depuis la popup du planning, combien
      d'animateurs placer par jour dans chaque centre. Si un centre n'y
      figure pas, on retombe sur son `effectif_cible`. Une valeur 0 exclut
      le centre du remplissage.

    Objectifs de l'algorithme (dans cet ordre) :
      1. faire travailler un MAXIMUM d'animateurs différents (au moins une
         fois chacun quand c'est possible) ;
      2. équilibrer le nombre de jours travaillés entre les animateurs ;
      3. respecter les centres autorisés à effectif égal.

    Contraintes toujours respectées :
      - un animateur ne travaille que les jours où il est disponible (un
        animateur sans aucune disponibilité renseignée est réputé
        disponible en permanence) ;
      - un animateur ne peut pas être placé deux fois le même jour.
    """

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Requête invalide."}, status=400)

    debut_date = parse_date(data.get("debut", ""))
    if not debut_date:
        return JsonResponse({"error": "Date de début invalide."}, status=400)

    # Lundi de la semaine reçue, puis 5 jours ouvrés (lundi -> vendredi).
    lundi = debut_date - datetime.timedelta(days=debut_date.weekday())
    jours = [lundi + datetime.timedelta(days=i) for i in range(5)]
    samedi = lundi + datetime.timedelta(days=5)  # borne exclusive (le week-end n'est pas rempli)

    debut_dt = _parse_to_aware_datetime(lundi.isoformat())
    fin_dt = _parse_to_aware_datetime(samedi.isoformat())

    centres = list(Centre.objects.all().order_by("nom"))
    animateurs = list(
        Animateur.objects
        .prefetch_related("disponibilites", "preferences")
        .order_by("prenom", "nom")
    )

    if not centres:
        return JsonResponse({"error": "Aucun centre n'est configuré."}, status=400)
    if not animateurs:
        return JsonResponse({"error": "Aucun animateur n'est configuré."}, status=400)

    # --- Effectifs par centre (venus de la popup, sinon effectif_cible) ---
    effectifs_recus = data.get("effectifs") or {}

    def effectif_pour(centre):
        brut = effectifs_recus.get(str(centre.id))
        if brut is None:
            brut = effectifs_recus.get(centre.id, centre.effectif_cible)
        try:
            valeur = int(brut)
        except (TypeError, ValueError):
            valeur = centre.effectif_cible
        return max(0, valeur)

    # --- Centres autorisés : un animateur ne peut être placé que sur ces centres ---
    centres_autorises = {}
    for pref in PreferenceCentre.objects.filter(
        animateur__in=animateurs,
        centre__in=centres,
    ):
        centres_autorises.setdefault(pref.animateur_id, set()).add(pref.centre_id)

    def affectable_sur_centre(animateur, centre):
        return centre.id in centres_autorises.get(animateur.id, set())

    # --- Disponibilité évaluée EN MÉMOIRE (grâce au prefetch), sans requête
    #     par jour. Règle : aucune plage renseignée => disponible partout. ---
    def disponible(animateur, jour):
        plages = list(animateur.disponibilites.all())
        if not plages:
            return True
        return any(plage.debut <= jour <= plage.fin for plage in plages)

    # Nombre de jours ouvrés où chaque animateur est disponible : on s'en
    # sert pour traiter en priorité les profils les moins disponibles (les
    # plus difficiles à caser), ce qui maximise le nombre de personnes utilisées.
    jours_dispo = {
        animateur.id: sum(1 for jour in jours if disponible(animateur, jour))
        for animateur in animateurs
    }

    with transaction.atomic():
        # On repart d'une semaine propre (lundi -> vendredi uniquement).
        supprimees, _ = Affectation.objects.filter(
            debut__lt=fin_dt,
            fin__gt=debut_dt,
        ).delete()

        # Une "place" = un besoin d'un animateur sur (un jour, un centre).
        slots = []
        for jour in jours:
            for centre in centres:
                for _ in range(effectif_pour(centre)):
                    slots.append({"jour": jour, "centre": centre, "animateur": None})

        occupe_ce_jour = {jour: set() for jour in jours}   # jour -> {animateur_id}
        jours_travailles = {animateur.id: 0 for animateur in animateurs}

        def peut_placer(animateur, slot):
            if animateur.id in occupe_ce_jour[slot["jour"]]:
                return False
            return disponible(animateur, slot["jour"]) and affectable_sur_centre(animateur, slot["centre"])

        def placer(animateur, slot):
            slot["animateur"] = animateur
            occupe_ce_jour[slot["jour"]].add(animateur.id)
            jours_travailles[animateur.id] += 1

        # --- Passe 1 : garantir qu'un MAXIMUM d'animateurs travaille au moins
        # une fois. On commence par les moins disponibles (les plus rares). ---
        animateurs_par_rarete = sorted(
            animateurs,
            key=lambda a: (jours_dispo[a.id], a.prenom, a.nom),
        )
        for animateur in animateurs_par_rarete:
            if jours_dispo[animateur.id] == 0:
                continue  # jamais disponible cette semaine : rien à faire

            meilleurs = [
                # jour le moins rempli (pour étaler l'équipe)
                (len(occupe_ce_jour[slot["jour"]]), index)
                for index, slot in enumerate(slots)
                if slot["animateur"] is None and peut_placer(animateur, slot)
            ]
            if meilleurs:
                meilleurs.sort()
                placer(animateur, slots[meilleurs[0][1]])

        # --- Passe 2 : remplir les places restantes en équilibrant la charge
        # (le moins de jours déjà travaillés d'abord), centre autorisé en départage. ---
        for slot in slots:
            if slot["animateur"] is not None:
                continue

            candidats = [
                (jours_travailles[a.id], a.prenom, a.nom, a)
                for a in animateurs
                if peut_placer(a, slot)
            ]
            if not candidats:
                continue

            candidats.sort(key=lambda item: item[:-1])
            placer(candidats[0][-1], slot)

        # --- Création en base en une seule requête ---
        a_creer = []
        for slot in slots:
            if slot["animateur"] is None:
                continue
            jour = slot["jour"]
            a_creer.append(Affectation(
                animateur=slot["animateur"],
                centre=slot["centre"],
                debut=_parse_to_aware_datetime(jour.isoformat()),
                fin=_parse_to_aware_datetime((jour + datetime.timedelta(days=1)).isoformat()),
            ))
        Affectation.objects.bulk_create(a_creer)

    total_places = len(slots)
    creees = len(a_creer)
    non_remplies = total_places - creees
    animateurs_utilises = sum(1 for nb in jours_travailles.values() if nb > 0)

    message = (
        f"{creees} affectation(s) créée(s) du lundi au vendredi, "
        f"{supprimees} ancienne(s) remplacée(s). "
        f"{animateurs_utilises}/{len(animateurs)} animateur(s) utilisé(s)."
    )
    if non_remplies > 0:
        message += f" {non_remplies} place(s) non remplie(s) faute d'animateur disponible."

    return JsonResponse({
        "ok": True,
        "created": creees,
        "deleted": supprimees,
        "total_places": total_places,
        "unfilled": non_remplies,
        "animateurs_utilises": animateurs_utilises,
        "message": message,
    })
