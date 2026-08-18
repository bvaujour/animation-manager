"""Page et API des paramètres réservées aux superusers."""

import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from .models import BaremeCEE, Contrat, Qualification, TypePrime
from .services.parametres import get_parametres_structure


def _payload(parametres):
    return {
        "nom_structure": parametres.nom_structure,
        "adresse": parametres.adresse,
        "code_postal": parametres.code_postal,
        "ville": parametres.ville,
        "telephone": parametres.telephone,
        "email": parametres.email,
        "taux_indemnite_cp_cee": str(parametres.taux_indemnite_cp_cee),
        "prime_journaliere_maximale": str(parametres.prime_journaliere_maximale),
        "adapter_taux_cee_changement_statut": parametres.adapter_taux_cee_changement_statut,
        "modifie_le": parametres.modifie_le.isoformat(),
    }


def parametres(request):
    return render(request, "parametres.html", {"active_page": "parametres"})


def _decimal(payload, champ, libelle):
    try:
        return Decimal(str(payload.get(champ, "")).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{libelle} est invalide.") from exc


def _erreur_validation(exc):
    return next(iter(exc.message_dict.values()))[0] if hasattr(exc, "message_dict") else exc.messages[0]


@require_http_methods(["GET", "PUT"])
def api_parametres(request):
    parametres_structure = get_parametres_structure()
    if request.method == "GET":
        return JsonResponse(_payload(parametres_structure))

    try:
        donnees = json.loads(request.body)
        for champ in ("nom_structure", "adresse", "code_postal", "ville", "telephone", "email"):
            setattr(parametres_structure, champ, str(donnees.get(champ, "")).strip())
        parametres_structure.taux_indemnite_cp_cee = _decimal(
            donnees, "taux_indemnite_cp_cee", "Le taux d’indemnité de congés payés CEE"
        )
        if "prime_journaliere_maximale" in donnees:
            parametres_structure.prime_journaliere_maximale = _decimal(
                donnees, "prime_journaliere_maximale", "La prime journalière maximale"
            )
        if "adapter_taux_cee_changement_statut" in donnees:
            parametres_structure.adapter_taux_cee_changement_statut = bool(
                donnees["adapter_taux_cee_changement_statut"]
            )
        parametres_structure.save()
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            message = _erreur_validation(exc)
        else:
            message = "Requête invalide."
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(_payload(parametres_structure))


def _bareme_payload(bareme):
    return {
        "id": bareme.id,
        "statut_id": bareme.statut_id,
        "statut_nom": bareme.statut.nom,
        "montant_journalier": str(bareme.montant_journalier),
        "date_effet": bareme.date_effet.isoformat(),
    }


def _prime_payload(prime):
    statuts = list(prime.statuts_eligibles.all())
    return {
        "id": prime.id,
        "nom": prime.nom,
        "description": prime.description,
        "active": prime.active,
        "mode_calcul": prime.mode_calcul,
        "mode_calcul_libelle": prime.get_mode_calcul_display(),
        "type_montant": prime.type_montant,
        "type_montant_libelle": prime.get_type_montant_display(),
        "montant_fixe": str(prime.montant_fixe) if prime.montant_fixe is not None else None,
        "montant_maximum": str(prime.montant_maximum) if prime.montant_maximum is not None else None,
        "contrats_eligibles": prime.contrats_eligibles,
        "contrats_eligibles_libelles": [dict(Contrat.TYPE_CHOICES)[item] for item in prime.contrats_eligibles],
        "tous_statuts": prime.tous_statuts,
        "statut_ids": [statut.id for statut in statuts],
        "statuts": [{"id": statut.id, "nom": statut.nom} for statut in statuts],
    }


@require_http_methods(["GET"])
def api_parametres_paie(request):
    structure = get_parametres_structure()
    statuts = list(Qualification.objects.filter(est_statut=True).order_by("nom", "id"))
    baremes = BaremeCEE.objects.filter(structure=structure).select_related("statut")
    primes = TypePrime.objects.filter(structure=structure).prefetch_related("statuts_eligibles")
    return JsonResponse({
        "adapter_taux_cee_changement_statut": structure.adapter_taux_cee_changement_statut,
        "statuts": [{"id": item.id, "nom": item.nom} for item in statuts],
        "baremes": [_bareme_payload(item) for item in baremes],
        "types_contrats": [{"value": valeur, "label": libelle} for valeur, libelle in Contrat.TYPE_CHOICES],
        "modes_calcul": [{"value": valeur, "label": libelle} for valeur, libelle in TypePrime.MODE_CHOICES],
        "types_montant": [{"value": valeur, "label": libelle} for valeur, libelle in TypePrime.TYPE_MONTANT_CHOICES],
        "primes": [_prime_payload(item) for item in primes],
    })


@require_http_methods(["POST"])
def api_baremes_cee(request):
    try:
        donnees = json.loads(request.body)
        statut = Qualification.objects.get(pk=int(donnees.get("statut_id")), est_statut=True)
        date_effet = parse_date(donnees.get("date_effet") or "")
        if date_effet is None:
            raise ValidationError("La date d’effet est obligatoire et doit être valide.")
        montant = _decimal(donnees, "montant_journalier", "Le taux journalier CEE")
        bareme, _ = BaremeCEE.objects.update_or_create(
            structure=get_parametres_structure(),
            statut=statut,
            date_effet=date_effet,
            defaults={"montant_journalier": montant},
        )
    except (json.JSONDecodeError, TypeError, ValueError, Qualification.DoesNotExist, ValidationError) as exc:
        message = _erreur_validation(exc) if isinstance(exc, ValidationError) else "Le statut transmis est invalide."
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(_bareme_payload(bareme), status=201)


def _appliquer_prime(prime, donnees):
    prime.nom = str(donnees.get("nom", "")).strip()
    prime.description = str(donnees.get("description", "")).strip()
    prime.active = bool(donnees.get("active", False))
    prime.mode_calcul = donnees.get("mode_calcul", "")
    prime.type_montant = donnees.get("type_montant", "")
    prime.montant_fixe = _decimal(donnees, "montant_fixe", "Le montant fixe") if donnees.get("montant_fixe") not in (None, "") else None
    prime.montant_maximum = _decimal(donnees, "montant_maximum", "Le plafond") if donnees.get("montant_maximum") not in (None, "") else None
    prime.contrats_eligibles = donnees.get("contrats_eligibles") or []
    prime.tous_statuts = bool(donnees.get("tous_statuts", False))
    statut_ids = list(dict.fromkeys(int(item) for item in (donnees.get("statut_ids") or [])))
    statuts = list(Qualification.objects.filter(pk__in=statut_ids, est_statut=True))
    if len(statuts) != len(statut_ids):
        raise ValidationError("Un statut éligible est invalide.")
    if prime.active and not prime.tous_statuts and not statuts:
        raise ValidationError("Choisis au moins un statut éligible ou active Tous les statuts.")
    prime.save()
    prime.statuts_eligibles.set([] if prime.tous_statuts else statuts)


@require_http_methods(["POST"])
def api_types_primes(request):
    try:
        donnees = json.loads(request.body)
        with transaction.atomic():
            prime = TypePrime(structure=get_parametres_structure())
            _appliquer_prime(prime, donnees)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        message = _erreur_validation(exc) if isinstance(exc, ValidationError) else "Requête invalide."
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(_prime_payload(prime), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_type_prime_detail(request, prime_id):
    try:
        prime = TypePrime.objects.prefetch_related("statuts_eligibles").get(
            pk=prime_id, structure=get_parametres_structure()
        )
    except TypePrime.DoesNotExist:
        return JsonResponse({"error": "Prime introuvable."}, status=404)
    if request.method == "DELETE":
        prime.delete()
        return JsonResponse({"ok": True})
    try:
        donnees = json.loads(request.body)
        with transaction.atomic():
            _appliquer_prime(prime, donnees)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        message = _erreur_validation(exc) if isinstance(exc, ValidationError) else "Requête invalide."
        return JsonResponse({"error": message}, status=400)
    return JsonResponse(_prime_payload(prime))
