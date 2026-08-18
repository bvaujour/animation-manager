"""Page et API des paramètres réservées aux superusers."""

import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import BaremeApprentissage, BaremeCEE, Contrat, Qualification, ReferenceSMIC, TypeContrat, TypePrime
from .services.parametres import get_parametres_structure
from .services.remunerations_contrats import smic_pour_date
from .services.smic_provider import SMICProviderIndisponible, get_smic_provider


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
    types = list(prime.types_contrats_eligibles.all())
    codes = [item.code for item in types] or list(prime.contrats_eligibles or [])
    libelles = {item.code: item.nom for item in types}
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
        "contrats_eligibles": codes,
        "contrats_eligibles_libelles": [libelles.get(item, dict(Contrat.TYPE_CHOICES).get(item, item)) for item in codes],
        "tous_statuts": prime.tous_statuts,
        "statut_ids": [statut.id for statut in statuts],
        "statuts": [{"id": statut.id, "nom": statut.nom} for statut in statuts],
    }


@require_http_methods(["GET"])
def api_parametres_paie(request):
    structure = get_parametres_structure()
    statuts = list(Qualification.objects.filter(est_statut=True).order_by("nom", "id"))
    baremes = BaremeCEE.objects.filter(structure=structure).select_related("statut")
    primes = TypePrime.objects.filter(structure=structure).prefetch_related(
        "statuts_eligibles", "types_contrats_eligibles"
    )
    types_contrats = TypeContrat.objects.filter(structure=structure, actif=True)
    return JsonResponse({
        "adapter_taux_cee_changement_statut": structure.adapter_taux_cee_changement_statut,
        "statuts": [{"id": item.id, "nom": item.nom} for item in statuts],
        "baremes": [_bareme_payload(item) for item in baremes],
        "types_contrats": [{"value": item.code, "label": item.nom} for item in types_contrats],
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
    codes_contrats = list(dict.fromkeys(donnees.get("contrats_eligibles") or []))
    types_contrats = list(TypeContrat.objects.filter(
        structure=prime.structure, code__in=codes_contrats
    ))
    if len(types_contrats) != len(codes_contrats):
        raise ValidationError("Un type de contrat éligible est invalide.")
    prime.contrats_eligibles = codes_contrats
    prime.tous_statuts = bool(donnees.get("tous_statuts", False))
    statut_ids = list(dict.fromkeys(int(item) for item in (donnees.get("statut_ids") or [])))
    statuts = list(Qualification.objects.filter(pk__in=statut_ids, est_statut=True))
    if len(statuts) != len(statut_ids):
        raise ValidationError("Un statut éligible est invalide.")
    if prime.active and not prime.tous_statuts and not statuts:
        raise ValidationError("Choisis au moins un statut éligible ou active Tous les statuts.")
    prime.save()
    prime.types_contrats_eligibles.set(types_contrats)
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
        prime = TypePrime.objects.prefetch_related("statuts_eligibles", "types_contrats_eligibles").get(
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


def _type_contrat_payload(item):
    return {
        "id": item.id, "nom": item.nom, "code": item.code, "actif": item.actif,
        "ordre": item.ordre, "description": item.description,
        "mode_remuneration": item.mode_remuneration,
        "mode_remuneration_libelle": item.get_mode_remuneration_display(),
        "systeme": item.systeme,
    }


def _smic_payload(item):
    return {
        "id": item.id, "date_effet": item.date_effet.isoformat(),
        "montant_horaire": str(item.montant_horaire),
        "montant_mensuel_35h": str(item.montant_mensuel_35h) if item.montant_mensuel_35h is not None else None,
        "source": item.source, "identifiant_externe": item.identifiant_externe,
        "recupere_le": item.recupere_le.isoformat() if item.recupere_le else None,
        "commentaire": item.commentaire,
    }


def _apprentissage_payload(item):
    return {
        "id": item.id, "date_effet": item.date_effet.isoformat(),
        "annee_execution": item.annee_execution, "age_minimum": item.age_minimum,
        "age_maximum": item.age_maximum, "pourcentage_smic": str(item.pourcentage_smic),
        "actif": item.actif, "commentaire": item.commentaire,
    }


@require_http_methods(["GET", "POST"])
def api_parametres_contrats(request):
    structure = get_parametres_structure()
    if request.method == "GET":
        provider = get_smic_provider()
        smic_actuel = smic_pour_date(timezone.localdate(), structure)
        return JsonResponse({
            "types": [_type_contrat_payload(item) for item in structure.types_contrats.all()],
            "modes_paie": [{"value": value, "label": label} for value, label in TypeContrat.MODE_CHOICES],
            "references_smic": [_smic_payload(item) for item in structure.references_smic.all()],
            "smic_actuel_id": smic_actuel.id if smic_actuel else None,
            "baremes_apprentissage": [
                _apprentissage_payload(item) for item in structure.baremes_apprentissage.all()
            ],
            "provider_smic": {"disponible": provider.disponible, "libelle": provider.libelle},
        })
    try:
        data = json.loads(request.body)
        ressource = data.get("ressource")
        if ressource == "type":
            item = TypeContrat(
                structure=structure, nom=str(data.get("nom", "")).strip(),
                code=str(data.get("code", "")).strip(), actif=bool(data.get("actif", True)),
                ordre=int(data.get("ordre") or 0), description=str(data.get("description", "")).strip(),
                mode_remuneration=data.get("mode_remuneration", ""), systeme=False,
            )
            item.save()
            return JsonResponse(_type_contrat_payload(item), status=201)
        if ressource == "smic":
            date_effet = parse_date(data.get("date_effet") or "")
            if not date_effet:
                raise ValidationError("La date d'effet du SMIC est obligatoire.")
            item = ReferenceSMIC(
                structure=structure, date_effet=date_effet,
                montant_horaire=_decimal(data, "montant_horaire", "Le SMIC horaire"),
                montant_mensuel_35h=(
                    _decimal(data, "montant_mensuel_35h", "Le SMIC mensuel")
                    if data.get("montant_mensuel_35h") not in (None, "") else None
                ),
                source=str(data.get("source", "")).strip(), commentaire=str(data.get("commentaire", "")).strip(),
            )
            item.save()
            return JsonResponse(_smic_payload(item), status=201)
        if ressource == "apprentissage":
            date_effet = parse_date(data.get("date_effet") or "")
            if not date_effet:
                raise ValidationError("La date d'effet du barème est obligatoire.")
            item = BaremeApprentissage(
                structure=structure, date_effet=date_effet,
                annee_execution=int(data.get("annee_execution")), age_minimum=int(data.get("age_minimum")),
                age_maximum=int(data["age_maximum"]) if data.get("age_maximum") not in (None, "") else None,
                pourcentage_smic=_decimal(data, "pourcentage_smic", "Le pourcentage du SMIC"),
                actif=bool(data.get("actif", True)), commentaire=str(data.get("commentaire", "")).strip(),
            )
            item.save()
            return JsonResponse(_apprentissage_payload(item), status=201)
        if ressource == "synchroniser_smic":
            provider = get_smic_provider()
            provider.recuperer()
        raise ValidationError("L'opération demandée est invalide.")
    except SMICProviderIndisponible as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        return JsonResponse({"error": _erreur_validation(exc) if isinstance(exc, ValidationError) else "Requête invalide."}, status=400)


@require_http_methods(["PATCH", "DELETE"])
def api_parametre_contrat_detail(request, ressource, objet_id):
    structure = get_parametres_structure()
    modeles = {"type": TypeContrat, "smic": ReferenceSMIC, "apprentissage": BaremeApprentissage}
    modele = modeles.get(ressource)
    if not modele:
        return JsonResponse({"error": "Ressource invalide."}, status=404)
    try:
        item = modele.objects.get(pk=objet_id, structure=structure)
    except modele.DoesNotExist:
        return JsonResponse({"error": "Ressource introuvable."}, status=404)
    if request.method == "DELETE":
        try:
            if isinstance(item, TypeContrat) and (item.systeme or item.contrats.exists()):
                raise ValidationError("Ce type doit être désactivé afin de conserver l'historique.")
            if not isinstance(item, TypeContrat) and Contrat.objects.filter(
                mode_remuneration__in=(
                    Contrat.REMUNERATION_MINIMUM_SMIC,
                    Contrat.REMUNERATION_GRILLE_AUTO,
                    Contrat.REMUNERATION_GRILLE_CONTROLE,
                )
            ).exists():
                raise ValidationError("Cette référence peut être utilisée par un contrat et doit être conservée.")
            item.delete()
        except ValidationError as exc:
            return JsonResponse({"error": _erreur_validation(exc)}, status=400)
        return JsonResponse({"ok": True})
    try:
        data = json.loads(request.body)
        if isinstance(item, TypeContrat):
            item.nom = str(data.get("nom", item.nom)).strip()
            item.description = str(data.get("description", item.description)).strip()
            item.mode_remuneration = data.get("mode_remuneration", item.mode_remuneration)
            item.ordre = int(data.get("ordre", item.ordre))
            nouvel_actif = bool(data.get("actif", item.actif))
            if not nouvel_actif and item.contrats.filter(
                models.Q(date_debut__isnull=True) | models.Q(date_debut__lte=timezone.localdate())
            ).filter(models.Q(date_fin__isnull=True) | models.Q(date_fin__gte=timezone.localdate())).exists():
                raise ValidationError("Un contrat en cours utilise encore ce type.")
            item.actif = nouvel_actif
        elif isinstance(item, ReferenceSMIC):
            if "montant_horaire" in data:
                item.montant_horaire = _decimal(data, "montant_horaire", "Le SMIC horaire")
            item.source = str(data.get("source", item.source)).strip()
            item.commentaire = str(data.get("commentaire", item.commentaire)).strip()
        else:
            for champ in ("annee_execution", "age_minimum", "age_maximum"):
                if champ in data:
                    setattr(item, champ, int(data[champ]) if data[champ] not in (None, "") else None)
            if "pourcentage_smic" in data:
                item.pourcentage_smic = _decimal(data, "pourcentage_smic", "Le pourcentage du SMIC")
            item.actif = bool(data.get("actif", item.actif))
            item.commentaire = str(data.get("commentaire", item.commentaire)).strip()
        item.save()
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        return JsonResponse({"error": _erreur_validation(exc) if isinstance(exc, ValidationError) else "Requête invalide."}, status=400)
    payload = _type_contrat_payload(item) if isinstance(item, TypeContrat) else (
        _smic_payload(item) if isinstance(item, ReferenceSMIC) else _apprentissage_payload(item)
    )
    return JsonResponse(payload)
