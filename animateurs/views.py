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
# Pages
# ---------------------------------------------------------------------------

def accueil(request):
    return render(request, "accueil.html")


def planning(request):
    return render(request, "planning.html")


def test(request):
    return render(request, "test.html")


def gestion(request):
    return render(request, "gestion.html")


def documents(request):

    docs = Document.objects.all()

    documents_data = []

    for doc in docs:
        documents_data.append({
            "titre": doc.titre,
            "url": doc.fichier.url,
        })

    return render(
        request,
        "documents.html",
        {
            "documents": documents_data
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_to_aware_datetime(value):
    """Accepte une date ('2026-07-06') ou un datetime ISO et renvoie
    toujours un datetime timezone-aware."""

    dt = parse_datetime(value)

    if dt is None:
        date_seule = parse_date(value)

        if date_seule is None:
            raise ValueError(f"Date invalide : {value!r}")

        dt = datetime.datetime.combine(date_seule, datetime.time.min)

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)

    return dt


def _affectation_to_event(affectation):
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
    """Renvoie la liste des jours (date) couverts par un intervalle
    [debut, fin) exprimé en datetimes."""

    jour = debut.date()
    dernier_jour = fin.date()

    jours = []

    while jour < dernier_jour:
        jours.append(jour)
        jour += datetime.timedelta(days=1)

    return jours or [debut.date()]


def _animateur_disponible(animateur, debut, fin):
    """Un animateur sans aucune plage de disponibilité renseignée est
    considéré comme disponible en permanence (pas de contrainte tant que
    l'information n'a pas été saisie)."""

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
    chevauchent le même jour, que ce soit dans le même centre ou non."""

    conflits = Affectation.objects.filter(
        animateur=animateur,
        debut__lt=fin,
        fin__gt=debut,
    )

    if exclude_id is not None:
        conflits = conflits.exclude(pk=exclude_id)

    return conflits.exists()


def _valider_affectation(animateur, debut, fin, exclude_id=None):
    """Renvoie un message d'erreur si l'affectation n'est pas valide,
    ou None si tout est ok."""

    if _animateur_en_conflit(animateur, debut, fin, exclude_id=exclude_id):
        return "Cet animateur a déjà une affectation ce jour-là, dans un centre ou un autre."

    if not _animateur_disponible(animateur, debut, fin):
        return "Cet animateur n'est pas disponible à cette date."

    return None


# ---------------------------------------------------------------------------
# API - lecture
# ---------------------------------------------------------------------------

def _animateur_to_dict(animateur):
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
    if request.method == "GET":
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
        animateur.qualifications.set(
            Qualification.objects.filter(pk__in=qualification_ids)
        )

    return JsonResponse(_animateur_to_dict(animateur), status=201)


@require_http_methods(["DELETE"])
def api_animateur_detail(request, animateur_id):
    try:
        animateur = Animateur.objects.get(pk=animateur_id)
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Animateur introuvable."}, status=404)

    animateur.delete()
    return JsonResponse({"ok": True})


def api_disponibilites(request, animateur_id):
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


def api_planning(request):
    centre_id = request.GET.get("centre_id")

    affectations = Affectation.objects.select_related("animateur", "centre")

    if centre_id:
        affectations = affectations.filter(centre_id=centre_id)

    events = [_affectation_to_event(a) for a in affectations]

    return JsonResponse(events, safe=False)


# ---------------------------------------------------------------------------
# API - écriture (drag & drop dans le planning)
# ---------------------------------------------------------------------------

@require_POST
def api_affectation_create(request):
    try:
        payload = json.loads(request.body)

        animateur = Animateur.objects.get(pk=payload["animateur_id"])
        centre = Centre.objects.get(pk=payload["centre_id"])

        debut = _parse_to_aware_datetime(payload["debut"])
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
    try:
        affectation = Affectation.objects.get(pk=affectation_id)
    except Affectation.DoesNotExist:
        return JsonResponse({"error": "Affectation introuvable."}, status=404)

    if request.method == "DELETE":
        affectation.delete()
        return JsonResponse({"ok": True})

    # PATCH : déplacement / redimensionnement dans le calendrier
    try:
        payload = json.loads(request.body)

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


# ---------------------------------------------------------------------------
# API - gestion (centres / qualifications / animateurs)
# ---------------------------------------------------------------------------

def _centre_to_dict(centre):
    return {
        "id": centre.id,
        "nom": centre.nom,
        "code": centre.code,
        "couleur": centre.couleur,
    }


@require_http_methods(["GET", "POST"])
def api_centres(request):
    if request.method == "GET":
        centres = Centre.objects.all()
        return JsonResponse([_centre_to_dict(c) for c in centres], safe=False)

    try:
        payload = json.loads(request.body)

        nom = payload["nom"].strip()
        code = payload["code"].strip()
        couleur = payload.get("couleur", "#e03c00").strip() or "#e03c00"

        if not nom or not code:
            return JsonResponse({"error": "Le nom et le code sont obligatoires."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        centre = Centre.objects.create(nom=nom, code=code, couleur=couleur)
    except IntegrityError:
        return JsonResponse({"error": f"Le code « {code} » est déjà utilisé par un autre centre."}, status=409)

    return JsonResponse(_centre_to_dict(centre), status=201)


@require_http_methods(["DELETE"])
def api_centre_detail(request, centre_id):
    try:
        centre = Centre.objects.get(pk=centre_id)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Centre introuvable."}, status=404)

    centre.delete()
    return JsonResponse({"ok": True})


def _qualification_to_dict(qualification):
    return {"id": qualification.id, "nom": qualification.nom}


@require_http_methods(["GET", "POST"])
def api_qualifications(request):
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
    try:
        qualification = Qualification.objects.get(pk=qualification_id)
    except Qualification.DoesNotExist:
        return JsonResponse({"error": "Qualification introuvable."}, status=404)

    qualification.delete()
    return JsonResponse({"ok": True})
