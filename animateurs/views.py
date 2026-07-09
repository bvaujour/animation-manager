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

    # On ne bloque plus l'affectation sur les centres configurés dans
    # la fiche animateur : ces centres servent d'aide visuelle / indication,
    # mais Betty peut forcer une affectation sur n'importe quel centre.

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
            debut = _parse_to_aware_datetime(start)
            fin = _parse_to_aware_datetime(end)
            affectations = affectations.filter(debut__lt=fin, fin__gt=debut)
        except ValueError:
            return JsonResponse({"error": "Paramètres start/end invalides."}, status=400)

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

    if fin <= debut:
        return JsonResponse({"error": "La date de fin doit être après la date de début."}, status=400)

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

    if affectation.fin <= affectation.debut:
        return JsonResponse({"error": "La date de fin doit être après la date de début."}, status=400)

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
        debut = _parse_to_aware_datetime(debut_str)
    else:
        premier_jour = aujourd_hui.replace(day=1)
        debut = timezone.make_aware(datetime.datetime.combine(premier_jour, datetime.time.min))

    if fin_str:
        fin = _parse_to_aware_datetime(fin_str)
    else:
        if aujourd_hui.month == 12:
            mois_suivant = aujourd_hui.replace(year=aujourd_hui.year + 1, month=1, day=1)
        else:
            mois_suivant = aujourd_hui.replace(month=aujourd_hui.month + 1, day=1)
        fin = timezone.make_aware(datetime.datetime.combine(mois_suivant, datetime.time.min))

    if debut >= fin:
        return JsonResponse({"error": "La date de début doit être avant la date de fin."}, status=400)

    centres = list(Centre.objects.all().order_by("nom"))
    animateurs = list(Animateur.objects.all().order_by("prenom", "nom"))

    affectations = list(
        Affectation.objects
        .select_related("animateur", "centre")
        .filter(debut__lt=fin, fin__gt=debut)
    )

    # Structure de départ : tous les animateurs apparaissent, même à 0 jour.
    recap = {}
    for animateur in animateurs:
        recap[animateur.id] = {
            "id": animateur.id,
            "prenom": animateur.prenom,
            "nom": animateur.nom,
            "total": 0,
            "centres": {centre.id: 0 for centre in centres},
        }

    # On compte les jours réellement inclus dans la période demandée.
    # Exemple : affectation 30/07 -> 03/08, période août : on ne compte que
    # 01/08 et 02/08.
    for affectation in affectations:
        debut_effectif = max(affectation.debut, debut)
        fin_effective = min(affectation.fin, fin)
        nb_jours = max((fin_effective.date() - debut_effectif.date()).days, 1)

        ligne = recap.setdefault(affectation.animateur_id, {
            "id": affectation.animateur.id,
            "prenom": affectation.animateur.prenom,
            "nom": affectation.animateur.nom,
            "total": 0,
            "centres": {centre.id: 0 for centre in centres},
        })

        ligne["total"] += nb_jours
        ligne["centres"][affectation.centre_id] = ligne["centres"].get(affectation.centre_id, 0) + nb_jours

    animateurs_data = []
    for ligne in recap.values():
        animateurs_data.append({
            "id": ligne["id"],
            "prenom": ligne["prenom"],
            "nom": ligne["nom"],
            "total": ligne["total"],
            "centres": [
                {
                    "id": centre.id,
                    "jours": ligne["centres"].get(centre.id, 0),
                }
                for centre in centres
            ],
        })

    animateurs_data.sort(key=lambda item: (-item["total"], item["prenom"], item["nom"]))

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
