"""API de gestion des contrats depuis la fiche salarié."""

import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from .models import Animateur, Contrat
from .services.serializers import contrat_to_dict


def _erreur_validation(exc):
    if hasattr(exc, "message_dict"):
        return next(iter(exc.message_dict.values()))[0]
    return exc.messages[0]


def _decimal_facultatif(valeur, libelle):
    if valeur in (None, ""):
        return None
    try:
        return Decimal(str(valeur).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"{libelle} est invalide.") from exc


def _appliquer_payload(contrat, payload):
    if "type_contrat" in payload:
        contrat.type_contrat = payload.get("type_contrat", "")
    if "date_debut" in payload:
        contrat.date_debut = parse_date(payload.get("date_debut") or "")
        if contrat.date_debut is None:
            raise ValidationError("La date de début est obligatoire et doit être valide.")
    if "date_fin" in payload:
        brut = payload.get("date_fin") or ""
        contrat.date_fin = parse_date(brut) if brut else None
        if brut and contrat.date_fin is None:
            raise ValidationError("La date de fin est invalide.")
    if "taux_journalier_reference" in payload:
        contrat.taux_journalier_reference = _decimal_facultatif(
            payload.get("taux_journalier_reference"), "Le taux journalier de référence"
        )
    if "salaire_mensuel_reference" in payload:
        contrat.salaire_mensuel_reference = _decimal_facultatif(
            payload.get("salaire_mensuel_reference"), "Le salaire mensuel de référence"
        )


@require_http_methods(["GET", "POST"])
def api_contrats(request, animateur_id):
    animateur = get_object_or_404(Animateur, pk=animateur_id)
    if request.method == "GET":
        return JsonResponse([contrat_to_dict(item) for item in animateur.contrats.all()], safe=False)

    try:
        payload = json.loads(request.body)
        contrat = Contrat(animateur=animateur)
        _appliquer_payload(contrat, payload)
        contrat.save()
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        message = "Requête invalide." if not isinstance(exc, ValidationError) else _erreur_validation(exc)
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(contrat_to_dict(contrat), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_contrat_detail(request, animateur_id, contrat_id):
    contrat = get_object_or_404(Contrat, pk=contrat_id, animateur_id=animateur_id)
    if request.method == "DELETE":
        contrat.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)
        _appliquer_payload(contrat, payload)
        contrat.save()
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        message = "Requête invalide." if not isinstance(exc, ValidationError) else _erreur_validation(exc)
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(contrat_to_dict(contrat))
