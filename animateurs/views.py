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

from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_http_methods, require_POST

from .models import Affectation, Animateur, Centre, Disponibilite, Document, Qualification


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
    }


@require_http_methods(["GET", "POST"])
def api_animateurs(request):
    """GET : liste tous les animateurs.
    POST : crée un animateur ({"prenom", "nom", "qualifications": [ids]})."""

    if request.method == "GET":
        # prefetch_related évite le classique problème "N+1 requêtes" :
        # sans ça, chaque animateur referait une requête pour ses
        # qualifications et une pour ses préférences de centre.
        animateurs = Animateur.objects.prefetch_related(
            "qualifications",
            "preferences__centre",
        ).all()

        return JsonResponse([_animateur_to_dict(a) for a in animateurs], safe=False)

    try:
        payload = json.loads(request.body)

        prenom = payload["prenom"].strip()
        nom = payload["nom"].strip()
        qualification_ids = payload.get("qualifications", [])

        if not prenom or not nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    animateur = Animateur.objects.create(prenom=prenom, nom=nom)

    if qualification_ids:
        # .set() sur un ManyToMany remplace toute la liste en une requête.
        animateur.qualifications.set(
            Qualification.objects.filter(pk__in=qualification_ids)
        )

    return JsonResponse(_animateur_to_dict(animateur), status=201)


@require_http_methods(["DELETE"])
def api_animateur_detail(request, animateur_id):
    """Supprime un animateur. Grâce à on_delete=CASCADE sur les modèles
    PreferenceCentre / Disponibilite / Affectation, tout ce qui lui est
    lié est supprimé automatiquement avec lui."""

    try:
        animateur = Animateur.objects.get(pk=animateur_id)
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Animateur introuvable."}, status=404)

    animateur.delete()
    return JsonResponse({"ok": True})


def api_disponibilites(request, animateur_id):
    """Renvoie les plages de disponibilité (debut/fin) d'un animateur,
    utilisé par planning.js pour les afficher en surbrillance sur les
    calendriers quand on clique sur l'animateur."""

    try:
        animateur = Animateur.objects.get(pk=animateur_id)
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Animateur introuvable."}, status=404)

    plages = [
        {
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
    """Placement automatique : remplit les créneaux encore vides (jusqu'à
    l'effectif souhaité, par centre et par jour ouvré) sur la période
    donnée, en respectant les règles habituelles (disponibilité, pas de
    doublon).

    Payload attendu :
        {
            "debut": "2026-07-06", "fin": "2026-07-10",
            "effectifs": {"3": 2, "5": 1}   // optionnel, id de centre -> nb souhaité
        }
    (bornes incluses, on ignore automatiquement samedi/dimanche même si
    elles sont comprises dans l'intervalle). Si "effectifs" est absent ou
    ne mentionne pas un centre donné, on utilise Centre.effectif_cible
    (réglable une fois pour toutes dans la page Gestion), ce qui permet
    de relancer le placement sans avoir à ressaisir les effectifs à
    chaque fois.

    Algorithme (glouton, jour par jour puis centre par centre) :
      1. Pour chaque jour ouvré, on regarde qui est déjà pris ce jour-là.
      2. Pour chaque centre, on calcule combien d'animateurs lui
         manquent encore ce jour-là (effectif souhaité moins ceux déjà
         affectés, manuellement ou par un appel précédent).
      3. Pour chaque place manquante, on cherche les animateurs
         disponibles et pas déjà pris ce jour-là (dans CE centre ni dans
         un autre). Parmi les candidats, on choisit en priorité celui
         qui a le moins d'affectations posées durant CET appel (pour
         répartir la charge entre plusieurs animateurs plutôt que de
         toujours choisir le même), puis celui qui préfère le plus ce
         centre (ordre de préférence le plus bas), puis n'importe lequel.
      4. Si personne n'est disponible pour une place, elle reste vide et
         remonte dans la liste "non_couverts" pour que l'utilisateur le
         sache.
    """

    try:
        payload = json.loads(request.body)
        date_debut = parse_date(payload["debut"])
        date_fin = parse_date(payload["fin"])
        effectifs_demandes = payload.get("effectifs") or {}

        if date_debut is None or date_fin is None:
            raise ValueError("dates invalides")

        # Les clés JSON sont toujours des chaînes ; on les repasse en int
        # pour pouvoir comparer avec centre.id.
        effectifs_demandes = {int(k): int(v) for k, v in effectifs_demandes.items()}

    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    jours = _jours_ouvres(date_debut, date_fin)
    centres = list(Centre.objects.all())

    # prefetch_related pour ne pas refaire une requête "disponibilites"
    # et "preferences" par animateur et par jour dans la boucle ci-dessous.
    animateurs = list(
        Animateur.objects.prefetch_related("disponibilites", "preferences")
    )

    # Compteur de charge posée pendant CET appel (sert à répartir le
    # travail plutôt que de toujours choisir le même animateur en tête).
    charge = {animateur.id: 0 for animateur in animateurs}

    creees = []
    non_couverts = []

    for jour in jours:
        debut_jour = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
        fin_jour = debut_jour + datetime.timedelta(days=1)

        # Qui est déjà occupé ce jour-là, tous centres confondus (une
        # seule requête par jour, plutôt qu'une par centre).
        deja_pris_ids = set(
            Affectation.objects.filter(
                debut__lt=fin_jour,
                fin__gt=debut_jour,
            ).values_list("animateur_id", flat=True)
        )

        for centre in centres:
            effectif_vise = effectifs_demandes.get(centre.id, centre.effectif_cible)

            deja_presents = Affectation.objects.filter(
                centre=centre,
                debut__lt=fin_jour,
                fin__gt=debut_jour,
            ).count()

            places_a_pourvoir = effectif_vise - deja_presents

            for _ in range(places_a_pourvoir):
                candidats = []

                for animateur in animateurs:
                    if animateur.id in deja_pris_ids:
                        continue

                    # .all() sur une relation prefetch_related utilise le
                    # cache déjà chargé, pas de nouvelle requête ici.
                    disponibilites = list(animateur.disponibilites.all())
                    if disponibilites and not any(d.debut <= jour <= d.fin for d in disponibilites):
                        continue

                    # Ordre de préférence de l'animateur pour ce centre
                    # (1 = préféré). 999 si le centre n'est pas dans ses
                    # préférences, pour qu'il passe après ceux qui l'ont choisi.
                    ordre_preference = next(
                        (p.ordre for p in animateur.preferences.all() if p.centre_id == centre.id),
                        999,
                    )

                    candidats.append((charge[animateur.id], ordre_preference, animateur))

                if not candidats:
                    non_couverts.append({"centre": centre.nom, "date": jour.isoformat()})
                    continue

                # Tri : d'abord le moins chargé pendant cet appel, puis celui
                # qui préfère le plus ce centre.
                candidats.sort(key=lambda c: (c[0], c[1]))
                _, _, choisi = candidats[0]

                affectation = Affectation.objects.create(
                    animateur=choisi,
                    centre=centre,
                    debut=debut_jour,
                    fin=fin_jour,
                )

                creees.append(_affectation_to_event(affectation))
                charge[choisi.id] += 1
                deja_pris_ids.add(choisi.id)

    return JsonResponse({"creees": creees, "non_couverts": non_couverts})


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


@require_http_methods(["DELETE"])
def api_qualification_detail(request, qualification_id):
    """Supprime une qualification (elle est simplement retirée de la liste
    des animateurs qui l'avaient, grâce au comportement par défaut de
    Django sur les relations ManyToMany)."""

    try:
        qualification = Qualification.objects.get(pk=qualification_id)
    except Qualification.DoesNotExist:
        return JsonResponse({"error": "Qualification introuvable."}, status=404)

    qualification.delete()
    return JsonResponse({"ok": True})


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
