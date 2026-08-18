"""API de gestion des contrats depuis la fiche salarié."""

import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from .models import Animateur, Contrat, HistoriqueRemunerationContrat, TypeContrat
from .services.parametres import get_parametres_structure
from .services.serializers import contrat_to_dict


@require_http_methods(["GET"])
def api_types_contrats_actifs(request):
    """Référentiel en lecture pour le formulaire direction de la fiche salarié."""
    structure = get_parametres_structure()
    return JsonResponse([
        {
            "id": item.id, "code": item.code, "nom": item.nom,
            "mode_remuneration": item.mode_remuneration,
            "mode_remuneration_libelle": item.get_mode_remuneration_display(),
        }
        for item in structure.types_contrats.filter(actif=True)
    ], safe=False)


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
        code = payload.get("type_contrat", "")
        try:
            contrat.type_contrat_ref = TypeContrat.objects.get(
                structure=get_parametres_structure(), code=code, actif=True
            )
        except TypeContrat.DoesNotExist as exc:
            raise ValidationError("Le type de contrat est invalide ou inactif.") from exc
        contrat.type_contrat = contrat.type_contrat_ref.code
    if "date_debut" in payload:
        brut = payload.get("date_debut") or ""
        contrat.date_debut = parse_date(brut) if brut else None
        if brut and contrat.date_debut is None:
            raise ValidationError("La date de début doit être valide.")
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
    for champ, libelle in (
        ("heures_hebdomadaires", "Les heures hebdomadaires"),
        ("heures_mensuelles_reference", "Les heures mensuelles"),
        ("heures_annuelles_reference", "Les heures annuelles"),
    ):
        if champ in payload:
            setattr(contrat, champ, _decimal_facultatif(payload.get(champ), libelle))
    if "mode_temps_travail" in payload:
        contrat.mode_temps_travail = payload.get("mode_temps_travail", "")
    if "mode_remuneration" in payload:
        contrat.mode_remuneration = payload.get("mode_remuneration", "")
    if "annee_execution_initiale" in payload:
        valeur = payload.get("annee_execution_initiale")
        contrat.annee_execution_initiale = int(valeur) if valeur not in (None, "") else None
    if "date_effet_annee_execution" in payload:
        brut = payload.get("date_effet_annee_execution") or ""
        contrat.date_effet_annee_execution = parse_date(brut) if brut else None
        if brut and contrat.date_effet_annee_execution is None:
            raise ValidationError("La date d'effet de l'année d'exécution est invalide.")


def _historiser_salaire(contrat, payload, ancien_montant=None):
    montant = contrat.salaire_mensuel_reference
    if montant is None or montant == ancien_montant:
        return
    date_effet = parse_date(payload.get("date_effet_remuneration") or contrat.date_debut.isoformat())
    if not date_effet:
        raise ValidationError("La date d'effet de la rémunération est invalide.")
    HistoriqueRemunerationContrat.objects.update_or_create(
        contrat=contrat, date_effet=date_effet,
        defaults={"montant_mensuel": montant, "origine": HistoriqueRemunerationContrat.ORIGINE_MANUELLE},
    )


@require_http_methods(["GET", "POST"])
def api_contrats(request, animateur_id):
    animateur = get_object_or_404(Animateur, pk=animateur_id)
    if request.method == "GET":
        return JsonResponse([
            contrat_to_dict(item) for item in animateur.contrats.select_related("type_contrat_ref")
        ], safe=False)

    try:
        payload = json.loads(request.body)
        contrat = Contrat(animateur=animateur)
        _appliquer_payload(contrat, payload)
        contrat.save()
        _historiser_salaire(contrat, payload)
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
        ancien_montant = contrat.salaire_mensuel_reference
        _appliquer_payload(contrat, payload)
        contrat.save()
        _historiser_salaire(contrat, payload, ancien_montant)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        message = "Requête invalide." if not isinstance(exc, ValidationError) else _erreur_validation(exc)
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(contrat_to_dict(contrat))
