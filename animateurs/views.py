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


def _jours_ouvres(date_debut, date_fin):
    """Renvoie la liste des jours ouvrés (lundi à vendredi, on ignore
    samedi et dimanche) entre deux dates incluses.

    Utilisé par le placement automatique. `date_debut`/`date_fin` sont ici
    des objets `date` (pas des datetimes) et les deux bornes sont incluses.
    """

    jours = []
    jour = date_debut

    while jour <= date_fin:
        # weekday() renvoie 0 pour lundi ... 4 pour vendredi, 5=samedi, 6=dimanche
        if jour.weekday() < 5:
            jours.append(jour)
        jour += datetime.timedelta(days=1)

    return jours


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


def _valider_affectation(animateur, debut, fin, exclude_id=None):
    """Point d'entrée unique pour valider une affectation avant de
    l'enregistrer (création ou modification). Renvoie un message d'erreur
    (str) si l'affectation n'est pas valide, ou None si tout est ok."""

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
    préférés (triés par ordre de préférence grâce au Meta.ordering de
    PreferenceCentre)."""

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
        "centres_preferes": [
            {
                "id": preference.centre_id,
                "nom": preference.centre.nom,
                "code": preference.centre.code,
                "couleur": preference.centre.couleur,
                "ordre": preference.ordre,
            }
            for preference in animateur.preferences.all()
        ],
        # Utile côté planning automatique : si la liste est vide, on garde
        # la règle métier existante "pas de contrainte renseignée".
        "disponibilites": [
            {
                "debut": disponibilite.debut.isoformat(),
                "fin": disponibilite.fin.isoformat(),
            }
            for disponibilite in animateur.disponibilites.all()
        ],
    }


def _normaliser_preferences(payload):
    """Valide et normalise les centres préférés envoyés par le front.

    Format attendu :
        "preferences": [
            {"centre_id": 1, "ordre": 1},
            {"centre_id": 2, "ordre": 2}
        ]

    Renvoie None si le champ n'est pas présent dans la requête (donc ne
    pas modifier les préférences en PATCH), ou une liste normalisée de
    dictionnaires si le champ est présent.
    """

    if "preferences" not in payload:
        return None, None

    preferences_raw = payload.get("preferences") or []

    if not isinstance(preferences_raw, list):
        return None, "Les centres préférés sont invalides."

    preferences = []
    centres_vus = set()
    ordres_vus = set()

    for item in preferences_raw:
        try:
            centre_id = int(item["centre_id"])
            ordre = int(item["ordre"])
        except (KeyError, TypeError, ValueError):
            return None, "Les centres préférés sont invalides."

        if ordre < 1:
            return None, "L'ordre d'un centre préféré doit être supérieur ou égal à 1."

        if centre_id in centres_vus:
            return None, "Un même centre ne peut pas apparaître deux fois dans les préférences."

        if ordre in ordres_vus:
            return None, "Deux centres préférés ne peuvent pas avoir le même ordre."

        centres_vus.add(centre_id)
        ordres_vus.add(ordre)
        preferences.append({"centre_id": centre_id, "ordre": ordre})

    centres_existants = set(Centre.objects.filter(pk__in=centres_vus).values_list("id", flat=True))
    if centres_vus != centres_existants:
        return None, "Un des centres préférés est introuvable."

    preferences.sort(key=lambda pref: pref["ordre"])
    return preferences, None


def _appliquer_preferences(animateur, preferences):
    """Remplace entièrement l'ordre des centres préférés d'un animateur."""

    if preferences is None:
        return

    animateur.preferences.all().delete()

    PreferenceCentre.objects.bulk_create([
        PreferenceCentre(
            animateur=animateur,
            centre_id=pref["centre_id"],
            ordre=pref["ordre"],
        )
        for pref in preferences
    ])


@require_http_methods(["GET", "POST"])
def api_animateurs(request):
    """GET : liste tous les animateurs.
    POST : crée un animateur ({"prenom", "nom", "telephone", "email", "date_naissance", "qualifications": [ids], "preferences": [{centre_id, ordre}]})."""

    if request.method == "GET":
        # prefetch_related évite le classique problème "N+1 requêtes" :
        # sans ça, chaque animateur referait une requête pour ses
        # qualifications et une pour ses préférences de centre.
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
        preferences, erreur_preferences = _normaliser_preferences(payload)
        if erreur_preferences:
            return JsonResponse({"error": erreur_preferences}, status=400)

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

        _appliquer_preferences(animateur, preferences)

    animateur = Animateur.objects.prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    return JsonResponse(_animateur_to_dict(animateur), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_animateur_detail(request, animateur_id):
    """GET : renvoie un animateur.
    PATCH : modifie un ou plusieurs champs de l'animateur, y compris ses qualifications et ses centres préférés.
    DELETE : supprime l'animateur et, par cascade, son planning/disponibilités/préférences."""

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
        preferences, erreur_preferences = _normaliser_preferences(payload)
        if erreur_preferences:
            return JsonResponse({"error": erreur_preferences}, status=400)

    except (TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    with transaction.atomic():
        animateur.save()

        if qualification_ids is not None:
            animateur.qualifications.set(
                Qualification.objects.filter(pk__in=qualification_ids)
            )

        _appliquer_preferences(animateur, preferences)

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
        # Si "fin" n'est pas fourni, on suppose une affectation d'un seul jour.
        fin_brute = payload.get("fin") or payload["debut"]
        fin = _parse_to_aware_datetime(fin_brute)

    except (Animateur.DoesNotExist, Centre.DoesNotExist):
        return JsonResponse({"error": "Animateur ou centre introuvable."}, status=404)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    erreur = _valider_affectation(animateur, debut, fin)

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

    # On ne descend jamais avant "maintenant" : le passé n'est jamais
    # touché par cette action groupée.
    debut = max(debut_demande, timezone.now())

    if debut >= fin:
        # Toute la plage demandée est déjà dans le passé : rien à faire.
        return JsonResponse({"supprimees": 0})

    # .delete() sur un queryset supprime tout en une seule requête SQL et
    # renvoie (nombre_total_supprime, détail_par_modèle).
    nb_supprimees, _detail = Affectation.objects.filter(
        debut__lt=fin,
        fin__gt=debut,
    ).delete()

    return JsonResponse({"supprimees": nb_supprimees})


@require_POST
def api_planning_auto(request):
    """Placement automatique en deux passes avec diagnostic.

    Principe :
      1. on supprime d'abord les affectations existantes sur la semaine ;
      2. on construit toutes les places à remplir (jour + centre, répétées
         selon l'effectif demandé pour le centre) ;
      3. passe 1 : on essaye d'utiliser au moins une fois chaque animateur
         autorisé/éligible, en commençant par les plus difficiles à placer ;
      4. passe 2 : on remplit toutes les places restantes en équilibrant la
         charge et en respectant au mieux les préférences de centre.

    Ce n'est pas une optimisation mathématique parfaite, mais c'est beaucoup
    plus robuste qu'un simple parcours centre par centre : l'algo regarde les
    contraintes globales avant de choisir une place.
    """

    try:
        payload = json.loads(request.body)
        date_debut = parse_date(payload["debut"])
        date_fin = parse_date(payload["fin"])
        effectifs_demandes = payload.get("effectifs") or {}
        animateurs_par_jour_brut = payload.get("animateurs_par_jour") or {}

        if date_debut is None or date_fin is None or date_debut > date_fin:
            raise ValueError("dates invalides")

        effectifs_demandes = {int(k): max(0, int(v)) for k, v in effectifs_demandes.items()}

        animateurs_par_jour = {}
        for date_str, ids in animateurs_par_jour_brut.items():
            jour = parse_date(date_str)
            if jour is None:
                raise ValueError("date de sélection invalide")
            animateurs_par_jour[jour] = {int(i) for i in ids}

    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    jours = _jours_ouvres(date_debut, date_fin)
    centres = list(Centre.objects.all())
    animateurs = list(Animateur.objects.prefetch_related("disponibilites", "preferences"))
    animateurs_par_id = {animateur.id: animateur for animateur in animateurs}

    if not jours or not centres or not animateurs:
        return JsonResponse({
            "creees": [],
            "supprimees": 0,
            "non_couverts": [],
            "animateurs_utilises": [],
            "animateurs_non_utilises": [],
            "diagnostics": ["Aucun jour ouvré, aucun centre ou aucun animateur."],
            "message": "Aucun placement possible.",
        })

    def jour_datetime(jour):
        debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
        fin = debut + datetime.timedelta(days=1)
        return debut, fin

    def est_autorise_par_modal(animateur, jour):
        # Si la modal n'a pas envoyé de liste pour ce jour, on ne rajoute
        # aucune contrainte côté modal.
        if jour not in animateurs_par_jour:
            return True
        return animateur.id in animateurs_par_jour[jour]

    def disponible_ce_jour(animateur, jour):
        disponibilites = list(animateur.disponibilites.all())
        if not disponibilites:
            return True
        return any(dispo.debut <= jour <= dispo.fin for dispo in disponibilites)

    def ordre_preference(animateur, centre):
        return next(
            (preference.ordre for preference in animateur.preferences.all() if preference.centre_id == centre.id),
            999,
        )

    def peut_prendre_slot(animateur, slot, pris_par_jour):
        jour = slot["jour"]
        if animateur.id in pris_par_jour[jour]:
            return False
        if not est_autorise_par_modal(animateur, jour):
            return False
        if not disponible_ce_jour(animateur, jour):
            return False
        return True

    def slots_possibles_pour_animateur(animateur, slots_restants, pris_par_jour):
        return [slot for slot in slots_restants if peut_prendre_slot(animateur, slot, pris_par_jour)]

    def candidats_pour_slot(slot, pris_par_jour):
        return [animateur for animateur in animateurs if peut_prendre_slot(animateur, slot, pris_par_jour)]

    # Toutes les places à remplir, une entrée = une affectation attendue.
    slots = []
    for jour in jours:
        for centre in centres:
            effectif_vise = effectifs_demandes.get(centre.id, centre.effectif_cible)
            for index in range(max(0, effectif_vise)):
                slots.append({
                    "jour": jour,
                    "centre": centre,
                    "rang": index + 1,
                })

    total_places = len(slots)

    # Les animateurs concernés sont ceux cochés au moins une fois dans la
    # modal. Si la modal n'a rien transmis, tout le monde est concerné.
    if animateurs_par_jour:
        concernes_ids = set().union(*animateurs_par_jour.values()) if animateurs_par_jour.values() else set()
    else:
        concernes_ids = set(animateurs_par_id.keys())

    diagnostics = []
    if len(concernes_ids) > total_places:
        diagnostics.append(
            f"Impossible d'utiliser tout le monde : {len(concernes_ids)} animateur(s) sélectionné(s) pour seulement {total_places} place(s)."
        )

    periode_debut = timezone.make_aware(datetime.datetime.combine(jours[0], datetime.time.min))
    periode_fin = timezone.make_aware(datetime.datetime.combine(jours[-1] + datetime.timedelta(days=1), datetime.time.min))

    creees = []
    non_couverts = []
    charge = {animateur.id: 0 for animateur in animateurs}
    pris_par_jour = {jour: set() for jour in jours}
    created_by_day = {jour: [] for jour in jours}

    def retirer_slot(slots_restants, slot):
        # On retire par identité d'objet : chaque slot est un dict unique,
        # même si plusieurs places concernent le même centre/jour.
        slots_restants.remove(slot)

    def choisir_slot_pour_animateur(animateur, slots_restants):
        possibles = slots_possibles_pour_animateur(animateur, slots_restants, pris_par_jour)
        if not possibles:
            return None

        def score_slot(slot):
            # Plus un slot a peu de candidats, plus il est urgent de le remplir.
            nb_candidats = len(candidats_pour_slot(slot, pris_par_jour))
            return (
                ordre_preference(animateur, slot["centre"]),
                nb_candidats,
                slot["jour"].isoformat(),
                slot["centre"].nom.lower(),
                slot["rang"],
            )

        return min(possibles, key=score_slot)

    def choisir_animateur_pour_slot(slot):
        candidats = candidats_pour_slot(slot, pris_par_jour)
        if not candidats:
            return None

        def score_animateur(animateur):
            # On favorise :
            # 1. les animateurs encore jamais utilisés ;
            # 2. les moins chargés ;
            # 3. ceux qui préfèrent ce centre ;
            # 4. ceux qui ont peu d'autres possibilités restantes ;
            # 5. ordre alphabétique stable.
            nb_possibilites = len(slots_possibles_pour_animateur(animateur, slots_restants, pris_par_jour))
            return (
                0 if charge[animateur.id] == 0 else 1,
                charge[animateur.id],
                ordre_preference(animateur, slot["centre"]),
                nb_possibilites,
                animateur.nom.lower(),
                animateur.prenom.lower(),
                animateur.id,
            )

        return min(candidats, key=score_animateur)

    def creer_affectation(animateur, slot):
        debut_jour, fin_jour = jour_datetime(slot["jour"])
        affectation = Affectation.objects.create(
            animateur=animateur,
            centre=slot["centre"],
            debut=debut_jour,
            fin=fin_jour,
        )
        creees.append(_affectation_to_event(affectation))
        created_by_day[slot["jour"]].append(affectation)
        charge[animateur.id] += 1
        pris_par_jour[slot["jour"]].add(animateur.id)
        retirer_slot(slots_restants, slot)

    with transaction.atomic():
        # Placement automatique = recalcul complet de la période.
        nb_supprimees, _detail_supprimees = Affectation.objects.filter(
            debut__lt=periode_fin,
            fin__gt=periode_debut,
        ).delete()

        slots_restants = list(slots)

        # ------------------------------------------------------------------
        # Passe 1 : utiliser au moins une fois un maximum d'animateurs.
        # On commence par les animateurs les plus difficiles à placer : ceux
        # qui ont le moins de slots possibles sur la semaine.
        # ------------------------------------------------------------------
        def animateurs_a_placer_tries():
            candidats = []
            for animateur in animateurs:
                if animateur.id not in concernes_ids:
                    continue
                if charge[animateur.id] > 0:
                    continue
                possibles = slots_possibles_pour_animateur(animateur, slots_restants, pris_par_jour)
                if possibles:
                    candidats.append((len(possibles), animateur.nom.lower(), animateur.prenom.lower(), animateur.id, animateur))
            candidats.sort(key=lambda item: item[:4])
            return [item[4] for item in candidats]

        while slots_restants:
            candidats_non_utilises = animateurs_a_placer_tries()
            if not candidats_non_utilises:
                break

            animateur = candidats_non_utilises[0]
            slot = choisir_slot_pour_animateur(animateur, slots_restants)
            if slot is None:
                break
            creer_affectation(animateur, slot)

            # Si on a déjà utilisé autant d'animateurs qu'il y a de places,
            # inutile de continuer la passe 1.
            if len([nb for nb in charge.values() if nb > 0]) >= total_places:
                break

        # ------------------------------------------------------------------
        # Passe 2 : remplir toutes les places restantes.
        # À chaque tour on remplit le slot le plus contraint (moins de
        # candidats disponibles), puis on choisit le meilleur animateur.
        # ------------------------------------------------------------------
        while slots_restants:
            slots_scores = []
            for slot in slots_restants:
                candidats = candidats_pour_slot(slot, pris_par_jour)
                slots_scores.append((len(candidats), slot["jour"].isoformat(), slot["centre"].nom.lower(), slot["rang"], slot, candidats))

            impossibles = [item for item in slots_scores if item[0] == 0]
            if impossibles:
                for _nb, _jour_key, _centre_key, _rang, slot, _candidats in impossibles:
                    non_couverts.append({
                        "centre": slot["centre"].nom,
                        "centre_id": slot["centre"].id,
                        "date": slot["jour"].isoformat(),
                        "motif": "Aucun animateur disponible ou autorisé pour ce jour.",
                    })
                    if slot in slots_restants:
                        retirer_slot(slots_restants, slot)
                continue

            _nb, _jour_key, _centre_key, _rang, slot, _candidats = min(slots_scores, key=lambda item: item[:4])
            choisi = choisir_animateur_pour_slot(slot)
            if choisi is None:
                non_couverts.append({
                    "centre": slot["centre"].nom,
                    "centre_id": slot["centre"].id,
                    "date": slot["jour"].isoformat(),
                    "motif": "Aucun animateur disponible ou autorisé pour ce jour.",
                })
                retirer_slot(slots_restants, slot)
                continue
            creer_affectation(choisi, slot)

    animateurs_utilises_ids = {animateur_id for animateur_id, nb in charge.items() if nb > 0}

    animateurs_non_utilises = []
    for animateur in animateurs:
        if animateur.id not in concernes_ids or animateur.id in animateurs_utilises_ids:
            continue
        possibles_initiaux = [
            slot for slot in slots
            if est_autorise_par_modal(animateur, slot["jour"]) and disponible_ce_jour(animateur, slot["jour"])
        ]
        motif = "Aucune place compatible restante."
        if not possibles_initiaux:
            motif = "Aucune disponibilité ou autorisation sur la semaine."
        animateurs_non_utilises.append({
            "id": animateur.id,
            "nom": f"{animateur.prenom} {animateur.nom}",
            "motif": motif,
        })

    if non_couverts:
        diagnostics.append(f"{len(non_couverts)} place(s) n'ont pas pu être couvertes faute de candidat compatible.")
    if animateurs_non_utilises:
        diagnostics.append(f"{len(animateurs_non_utilises)} animateur(s) sélectionné(s) n'ont pas pu être utilisés.")

    return JsonResponse({
        "creees": creees,
        "supprimees": nb_supprimees,
        "non_couverts": non_couverts,
        "animateurs_utilises": sorted(animateurs_utilises_ids),
        "animateurs_non_utilises": animateurs_non_utilises,
        "diagnostics": diagnostics,
        "resume_jours": [
            {
                "date": jour.isoformat(),
                "creees": len(created_by_day[jour]),
            }
            for jour in jours
        ],
    })


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
    DELETE : supprime le centre (et, par cascade, ses préférences/
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
    animateurs_sans_preference = [
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
            "animateurs_sans_preference": animateurs_sans_preference,
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
