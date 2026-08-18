"""API de l'historique daté des statuts depuis la fiche salarié."""

import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from .models import Animateur, HistoriqueStatutAnimateur, Qualification
from .services.serializers import historique_statut_to_dict
from .services.statuts import synchroniser_statut_actuel


def _message_validation(exc):
    return next(iter(exc.message_dict.values()))[0] if hasattr(exc, "message_dict") else exc.messages[0]


def _appliquer(entree, donnees):
    try:
        entree.statut = Qualification.objects.get(pk=int(donnees.get("statut_id")), est_statut=True)
    except (Qualification.DoesNotExist, TypeError, ValueError) as exc:
        raise ValidationError("Le statut sélectionné est invalide.") from exc
    date_effet = parse_date(str(donnees.get("date_effet") or ""))
    if date_effet is None:
        raise ValidationError("La date d’effet est obligatoire et doit être valide.")
    entree.date_effet = date_effet
    entree.commentaire = str(donnees.get("commentaire", entree.commentaire) or "").strip()
    if not entree.pk:
        entree.origine = HistoriqueStatutAnimateur.ORIGINE_MANUELLE
        entree.date_effet_incertaine = False
    entree.save()


@require_http_methods(["GET", "POST"])
def api_historique_statuts(request, animateur_id):
    animateur = get_object_or_404(Animateur, pk=animateur_id)
    if request.method == "GET":
        synchroniser_statut_actuel(animateur)
        entrees = animateur.historique_statuts.select_related("statut")
        return JsonResponse([historique_statut_to_dict(item) for item in entrees], safe=False)
    try:
        donnees = json.loads(request.body)
        with transaction.atomic():
            entree = HistoriqueStatutAnimateur(animateur=animateur)
            _appliquer(entree, donnees)
    except (json.JSONDecodeError, TypeError, ValidationError, IntegrityError) as exc:
        message = _message_validation(exc) if isinstance(exc, ValidationError) else "Un statut existe déjà à cette date."
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(historique_statut_to_dict(entree), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_historique_statut_detail(request, animateur_id, historique_id):
    entree = get_object_or_404(
        HistoriqueStatutAnimateur.objects.select_related("statut"),
        pk=historique_id,
        animateur_id=animateur_id,
    )
    if request.method == "DELETE":
        entree.delete()
        return JsonResponse({"ok": True})
    try:
        donnees = json.loads(request.body)
        with transaction.atomic():
            _appliquer(entree, donnees)
    except (json.JSONDecodeError, TypeError, ValidationError, IntegrityError) as exc:
        message = _message_validation(exc) if isinstance(exc, ValidationError) else "Un statut existe déjà à cette date."
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(historique_statut_to_dict(entree))
