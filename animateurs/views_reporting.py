"""API du récapitulatif et de la bibliothèque de documents."""

import datetime
import json
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access import est_direction
from .models import (
    Affectation, Animateur, AttributionPrime, Centre, Contrat, Document,
    HistoriqueStatutAnimateur, PeriodeScolaire, PrimeJournalierePeriode, TypePrime,
)
from .services.dates import parse_to_aware_datetime

logger = logging.getLogger(__name__)
from .services.documents import normaliser_nom_document, valider_periode_document
from .services.recapitulatif import generer_recapitulatif, generer_recapitulatif_excel, generer_recapitulatif_paie_pdf
from .services.preparation_paie import enrichir_recapitulatif_paie
from .services.primes import (
    attributions_primes_se_chevauchent,
    creer_attribution_prime,
    nombre_jours_attribution_prime,
)
from .services.contrats import situation_contractuelle_pour_date
from .services.parametres import prime_est_eligible
from .services.statuts import statut_pour_date
from .services.serializers import document_to_dict

# ---------------------------------------------------------------------------
# API - Récapitulatif (statistiques pour la page de suivi)
# ---------------------------------------------------------------------------


def _selection_recapitulatif(request):
    """Valide et transforme la sélection commune à l'écran et au PDF."""
    periode_ids_bruts = request.GET.get("periode_ids", "").strip()
    mois_str = request.GET.get("mois", "").strip()
    date_debut_str = request.GET.get("date_debut", "").strip()
    date_fin_str = request.GET.get("date_fin", "").strip()
    periodes = []
    jours_selectionnes = None

    if periode_ids_bruts:
        try:
            periode_ids = [int(valeur) for valeur in periode_ids_bruts.split(",") if valeur.strip()]
        except ValueError:
            return None, None, None, None, "La sélection de périodes est invalide."

        if not periode_ids:
            return None, None, None, None, "Sélectionne au moins une période."

        periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
        if len(periodes) != len(set(periode_ids)):
            return None, None, None, None, "Une période sélectionnée est introuvable."

        jours_selectionnes = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in periodes
            for decalage in range((periode.fin - periode.debut).days + 1)
        }
        debut_date = min(jours_selectionnes)
        fin_date = max(jours_selectionnes) + datetime.timedelta(days=1)
        debut = timezone.make_aware(datetime.datetime.combine(debut_date, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(fin_date, datetime.time.min))
    elif mois_str:
        try:
            debut_date = datetime.date.fromisoformat(f"{mois_str}-01")
        except ValueError:
            return None, None, None, None, "Le mois sélectionné est invalide."
        mois_suivant = (
            debut_date.replace(year=debut_date.year + 1, month=1)
            if debut_date.month == 12
            else debut_date.replace(month=debut_date.month + 1)
        )
        dernier_jour = mois_suivant - datetime.timedelta(days=1)
        debut = timezone.make_aware(datetime.datetime.combine(debut_date, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(mois_suivant, datetime.time.min))
        periodes = list(
            PeriodeScolaire.objects.filter(debut__lte=dernier_jour, fin__gte=debut_date)
            .order_by("debut", "ordre", "nom")
        )
    elif date_debut_str or date_fin_str:
        if not date_debut_str or not date_fin_str:
            return None, None, None, None, "Les dates de début et de fin sont obligatoires."
        try:
            debut_date = datetime.date.fromisoformat(date_debut_str)
            dernier_jour = datetime.date.fromisoformat(date_fin_str)
        except ValueError:
            return None, None, None, None, "La période personnalisée est invalide."
        if dernier_jour < debut_date:
            return None, None, None, None, "La date de fin ne peut pas être antérieure à la date de début."
        fin_date = dernier_jour + datetime.timedelta(days=1)
        debut = timezone.make_aware(datetime.datetime.combine(debut_date, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(fin_date, datetime.time.min))
        periodes = list(
            PeriodeScolaire.objects.filter(debut__lte=dernier_jour, fin__gte=debut_date)
            .order_by("debut", "ordre", "nom")
        )
    else:
        debut_str = request.GET.get("debut")
        fin_str = request.GET.get("fin")
        aujourd_hui = timezone.localdate()

        if debut_str:
            debut = parse_to_aware_datetime(debut_str)
        else:
            premier_jour = aujourd_hui.replace(day=1)
            debut = timezone.make_aware(datetime.datetime.combine(premier_jour, datetime.time.min))

        if fin_str:
            fin = parse_to_aware_datetime(fin_str)
        else:
            if aujourd_hui.month == 12:
                mois_suivant = aujourd_hui.replace(year=aujourd_hui.year + 1, month=1, day=1)
            else:
                mois_suivant = aujourd_hui.replace(month=aujourd_hui.month + 1, day=1)
            fin = timezone.make_aware(datetime.datetime.combine(mois_suivant, datetime.time.min))

    if not debut or not fin:
        return None, None, None, None, "La période est invalide."
    if debut >= fin:
        return None, None, None, None, "La date de début doit être avant la date de fin."
    return debut, fin, jours_selectionnes, periodes, None


def _ajouter_preparation_paie(recap, periodes, debut, fin):
    """Conserve l'ancien contrat d'API puis ajoute la nouvelle préparation datée."""

    periode_ids = [periode.id for periode in periodes]
    primes = {
        (item.animateur_id, item.periode_id): item.montant
        for item in PrimeJournalierePeriode.objects.filter(
            animateur_id__in=[ligne["id"] for ligne in recap["animateurs"]],
            periode_id__in=periode_ids,
        )
    }
    for ligne in recap["animateurs"]:
        montants = [primes.get((ligne["id"], periode.id), Decimal("0.00")) for periode in periodes]
        prime = montants[0] if montants and len(set(montants)) == 1 else None
        details = []
        total_prime = Decimal("0.00")
        dates_affectations = {datetime.date.fromisoformat(item["date"]) for item in ligne["jours"]}
        dates_reunions = {
            datetime.date.fromisoformat(item) for item in ligne.get("dates_reunions_comptabilisees", [])
        }
        for periode, montant in zip(periodes, montants):
            jours = Decimal(sum(periode.debut <= jour <= periode.fin for jour in dates_affectations))
            jours += Decimal(sum(periode.debut <= jour <= periode.fin for jour in dates_reunions))
            if len(periodes) == 1:
                jours += Decimal(str(ligne["jours_preparation"]))
            montant_periode = (jours * montant).quantize(Decimal("0.01"))
            total_prime += montant_periode
            details.append({
                "periode_id": periode.id, "libelle": periode.libelle_avec_annee,
                "jours": int(jours) if jours == jours.to_integral_value() else float(jours),
                "prime_jour": str(montant.quantize(Decimal("0.01"))),
                "montant_prime": str(montant_periode),
            })
        base = Decimal(ligne["paie_jour"]) if ligne["paie_jour"] is not None else None
        paie_base = Decimal(ligne["paie_totale"]) if ligne["paie_totale"] is not None else None
        ligne.update({
            "prime_jour": str(prime.quantize(Decimal("0.01"))) if prime is not None else None,
            "prime_jour_variable": len(set(montants)) > 1,
            "total_jour_avec_prime": str((base + prime).quantize(Decimal("0.01")))
            if base is not None and prime is not None else None,
            "paie_base": ligne["paie_totale"],
            "montant_primes": str(total_prime),
            "primes_detail": details,
            "prime_modifiable": bool(periode_ids and base is not None),
            "total_paie_estime": str((paie_base + total_prime).quantize(Decimal("0.01")))
            if paie_base is not None else None,
        })

    recap["total_primes"] = str(sum(
        (Decimal(item["montant_primes"]) for item in recap["animateurs"]), Decimal("0.00")
    ).quantize(Decimal("0.01")))
    recap["total_paie_avec_primes"] = str(sum(
        (Decimal(item["total_paie_estime"]) for item in recap["animateurs"] if item["total_paie_estime"] is not None),
        Decimal("0.00"),
    ).quantize(Decimal("0.01")))

    return enrichir_recapitulatif_paie(
        recap, debut.date(), fin.date() - datetime.timedelta(days=1), periodes
    )


def api_recapitulatif(request):
    """Tableau de bord du planning sur une ou plusieurs périodes enregistrées."""

    debut, fin, jours_selectionnes, periodes, erreur = _selection_recapitulatif(request)
    if erreur:
        return JsonResponse({"error": erreur}, status=400)

    recap = generer_recapitulatif(
        debut,
        fin,
        jours_selectionnes=jours_selectionnes,
        periode_ids=[periode.id for periode in periodes] if jours_selectionnes is not None else None,
    )
    _ajouter_preparation_paie(recap, periodes, debut, fin)

    return JsonResponse(
        {
            "periode": {
                "debut": debut.date().isoformat(),
                "fin": (fin.date() - datetime.timedelta(days=1)).isoformat(),
                "ids": [periode.id for periode in periodes],
                "libelles": [periode.libelle_avec_annee for periode in periodes],
            },
            "dates": recap["dates"],
            "centres": recap["centres"],
            "animateurs": recap["animateurs"],
            "total_jours": recap["total_jours"],
            "total_paie_connue": recap["total_paie_connue"],
            "total_primes": recap["total_primes"],
            "total_paie_avec_primes": recap["total_paie_avec_primes"],
            "tarifs_manquants": recap["tarifs_manquants"],
            "total_prepare": recap.get("total_prepare"),
            "total_primes_preparees": recap.get("total_primes_preparees"),
            "preparations_incompletes": recap.get("preparations_incompletes", 0),
        }
    )


@require_http_methods(["PUT", "DELETE"])
def api_prime_journaliere(request):
    """Valide en une transaction plusieurs primes sur plusieurs semaines."""

    try:
        payload = json.loads(request.body or "{}")
        periode_ids = list(dict.fromkeys(int(item) for item in payload.get("periode_ids", [])))
    except (AttributeError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError):
        return JsonResponse({"error": "La prime doit être un montant numérique valide."}, status=400)
    if not periode_ids:
        return JsonResponse({"error": "Sélectionne au moins une période."}, status=400)

    periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
    if len(periodes) != len(periode_ids):
        return JsonResponse({"error": "Une période sélectionnée est introuvable."}, status=400)

    if request.method == "DELETE":
        try:
            animateur_id = int(payload.get("animateur_id"))
        except (TypeError, ValueError):
            return JsonResponse({"error": "L'animateur transmis est invalide."}, status=400)
        if not Animateur.objects.filter(pk=animateur_id).exists():
            return JsonResponse({"error": "L'animateur transmis est introuvable."}, status=400)
        jours_selectionnes = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in periodes for decalage in range((periode.fin - periode.debut).days + 1)
        }
        debut = timezone.make_aware(datetime.datetime.combine(min(jours_selectionnes), datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(max(jours_selectionnes) + datetime.timedelta(days=1), datetime.time.min))
        with transaction.atomic():
            deleted_count, _ = PrimeJournalierePeriode.objects.filter(
                animateur_id=animateur_id, periode_id__in=periode_ids
            ).delete()
        recap = generer_recapitulatif(debut, fin, jours_selectionnes=jours_selectionnes, periode_ids=periode_ids)
        _ajouter_preparation_paie(recap, periodes, debut, fin)
        ligne = next((item for item in recap["animateurs"] if item["id"] == animateur_id), None)
        return JsonResponse({
            "success": True, "deleted_count": deleted_count,
            "animateur_id": animateur_id, "periode_ids": periode_ids,
            "animateur": ligne,
            "total_primes": recap["total_primes"],
            "total_paie_avec_primes": recap["total_paie_avec_primes"],
        })

    primes_payload = payload.get("primes")
    if primes_payload is None:  # compatibilité avec l'ancien client unitaire
        primes_payload = [{"animateur_id": payload.get("animateur_id"), "montant": payload.get("montant")}]
    if not isinstance(primes_payload, list) or not primes_payload:
        return JsonResponse({"error": "Aucune prime modifiée n'a été transmise."}, status=400)
    primes_validees = []
    try:
        for item in primes_payload:
            animateur_id = int(item.get("animateur_id"))
            montant = Decimal(str(item.get("montant")))
            if not montant.is_finite() or montant != montant.to_integral_value():
                return JsonResponse({"error": "La prime doit être indiquée en euros entiers."}, status=400)
            if montant < 0 or montant > 7:
                raise ValueError
            primes_validees.append((animateur_id, montant))
    except (AttributeError, TypeError, ValueError, InvalidOperation):
        return JsonResponse({"error": "Chaque prime doit être comprise entre 0 € et 7 €."}, status=400)
    animateur_ids = [item[0] for item in primes_validees]
    if len(set(animateur_ids)) != len(animateur_ids) or Animateur.objects.filter(pk__in=animateur_ids).count() != len(animateur_ids):
        return JsonResponse({"error": "Un animateur transmis est invalide ou présent deux fois."}, status=400)

    jours_selectionnes = {
        periode.debut + datetime.timedelta(days=decalage)
        for periode in periodes
        for decalage in range((periode.fin - periode.debut).days + 1)
    }
    debut = timezone.make_aware(datetime.datetime.combine(min(jours_selectionnes), datetime.time.min))
    fin = timezone.make_aware(
        datetime.datetime.combine(max(jours_selectionnes) + datetime.timedelta(days=1), datetime.time.min)
    )
    recap = generer_recapitulatif(
        debut,
        fin,
        jours_selectionnes=jours_selectionnes,
        periode_ids=periode_ids,
    )
    lignes = {item["id"]: item for item in recap["animateurs"]}
    if any(animateur_id not in lignes for animateur_id in animateur_ids):
        return JsonResponse({"error": "Un animateur n'a aucun jour travaillé sur cette sélection."}, status=400)
    if any(lignes[animateur_id]["paie_jour"] is None for animateur_id in animateur_ids):
        return JsonResponse({"error": "Renseigne d'abord tous les tarifs journaliers concernés."}, status=400)

    with transaction.atomic():
        for animateur_id, montant in primes_validees:
            for periode in periodes:
                if montant == 0:
                    PrimeJournalierePeriode.objects.filter(animateur_id=animateur_id, periode=periode).delete()
                else:
                    PrimeJournalierePeriode.objects.update_or_create(
                        animateur_id=animateur_id, periode=periode, defaults={"montant": montant}
                    )

    _ajouter_preparation_paie(recap, periodes, debut, fin)
    resultat = {
        "semaines_modifiees": len(periodes),
        "animateurs_modifies": len(primes_validees),
        "animateurs": [lignes[animateur_id] for animateur_id in animateur_ids],
    }
    if len(primes_validees) == 1:  # réponse historique conservée
        ligne = lignes[animateur_ids[0]]
        resultat.update({
            "animateur_id": animateur_ids[0],
            "prime_jour": ligne["prime_jour"],
            "total_jour_avec_prime": ligne["total_jour_avec_prime"],
            "total_paie_estime": ligne["total_paie_estime"],
        })
    return JsonResponse(resultat)


def _attribution_prime_dict(item):
    return {
        "id": item.id,
        "animateur_id": item.animateur_id,
        "animateur_nom": str(item.animateur),
        "type_prime_id": item.type_prime_id,
        "nom": item.type_prime.nom,
        "type_prime_nom": item.type_prime.nom,
        "mode_calcul": item.mode_calcul,
        "mode_libelle": dict(TypePrime.MODE_CHOICES).get(item.mode_calcul, item.mode_calcul),
        "date_debut": item.date_debut.isoformat(),
        "date_fin": item.date_fin.isoformat(),
        "montant_unitaire": str(item.montant_unitaire),
        "montant_total": str(item.montant_total),
        "nombre_jours": nombre_jours_attribution_prime(item),
        "commentaire": item.commentaire,
        "centre_id": item.centre_id,
    }


def _jours_travailles_pour_periode(debut, fin):
    recap = generer_recapitulatif(
        timezone.make_aware(datetime.datetime.combine(debut, datetime.time.min)),
        timezone.make_aware(datetime.datetime.combine(fin + datetime.timedelta(days=1), datetime.time.min)),
    )
    return {
        item["id"]: sorted(
            {datetime.date.fromisoformat(jour["date"]) for jour in item.get("jours", [])}
            | {datetime.date.fromisoformat(jour) for jour in item.get("dates_reunions_comptabilisees", [])}
        )
        for item in recap["animateurs"]
    }


def _niveaux_saisie_prime(prime):
    """Expose la granularité d'interface sans modifier le mode métier de la prime."""
    if prime.mode_calcul == TypePrime.MODE_JOUR:
        return ["mois", "semaine", "jour"]
    if prime.mode_calcul == TypePrime.MODE_SEMAINE:
        return ["mois", "semaine"]
    if prime.mode_calcul == TypePrime.MODE_MOIS:
        return ["mois"]
    return []


def _prime_context_payload(prime, jours_eligibles, *, semaines_eligibles=None, attributions=None):
    attributions = list(attributions or [])
    resume_attributions = _resume_attributions_prime(prime, attributions)
    jours_deja_attribues = [
        jour for jour in jours_eligibles
        if any(attributions_primes_se_chevauchent(
            prime.mode_calcul, jour, jour, item.date_debut, item.date_fin
        ) for item in attributions)
    ]
    deja = set(jours_deja_attribues)
    jours_disponibles = [jour for jour in jours_eligibles if jour not in deja]
    conflits = _nombre_conflits_attributions_prime(prime, attributions)
    payload = {
        "id": prime.id, "nom": prime.nom,
        "mode_calcul": prime.mode_calcul,
        "mode_libelle": prime.get_mode_calcul_display(),
        "type_montant": prime.type_montant,
        "montant_fixe": str(prime.montant_fixe) if prime.montant_fixe is not None else None,
        "montant_maximum": str(prime.montant_maximum) if prime.montant_maximum is not None else None,
        "jours_eligibles": [jour.isoformat() for jour in jours_eligibles],
        "jours_deja_attribues": [jour.isoformat() for jour in jours_deja_attribues],
        "jours_disponibles": [jour.isoformat() for jour in jours_disponibles],
        "segments_eligibles": _segments_depuis_dates(jours_eligibles),
        "segments_disponibles": _segments_depuis_dates(jours_disponibles),
        "entierement_attribue": bool(jours_eligibles and not jours_disponibles),
        "conflits_existants": conflits,
        "resume_attributions": resume_attributions,
        "attributions_couvertures": [{
            "id": item.id,
            "jours": [
                jour.isoformat() for jour in jours_eligibles
                if attributions_primes_se_chevauchent(
                    prime.mode_calcul, jour, jour, item.date_debut, item.date_fin
                )
            ],
        } for item in attributions],
        "niveaux_saisie": _niveaux_saisie_prime(prime),
    }
    if semaines_eligibles is not None:
        payload["semaines_toutes_eligibles"] = semaines_eligibles
        semaines_disponibles = []
        for semaine in semaines_eligibles:
            jours = [jour for jour in semaine["jours_eligibles"] if jour in {
                item.isoformat() for item in jours_disponibles
            }]
            if jours:
                semaines_disponibles.append({**semaine, "jours_eligibles": jours})
        payload["semaines_eligibles"] = semaines_disponibles
        multiplicateur = (
            len(semaines_disponibles)
            if prime.mode_calcul == TypePrime.MODE_SEMAINE
            else len(jours_disponibles)
        )
    else:
        multiplicateur = 1 if jours_disponibles else 0
    payload["multiplicateur_periode"] = multiplicateur
    payload["estimation_fixe_periode"] = (
        str((prime.montant_fixe * multiplicateur).quantize(Decimal("0.01")))
        if prime.montant_fixe is not None else None
    )
    return payload


def _resume_attributions_prime(prime, attributions):
    """Construit le résumé d'affichage sans requête ni recalcul Paie."""
    montants_unitaires = {item.montant_unitaire for item in attributions}
    if prime.mode_calcul == TypePrime.MODE_JOUR:
        quantite_attribuee = sum(nombre_jours_attribution_prime(item) for item in attributions)
    else:
        quantite_attribuee = len(attributions)
    return {
        "nombre_attributions": len(attributions),
        "quantite": quantite_attribuee,
        "montant_total": str(sum(
            (item.montant_total for item in attributions), Decimal("0.00")
        ).quantize(Decimal("0.01"))) if attributions else None,
        "montant_unitaire": str(next(iter(montants_unitaires)))
        if len(montants_unitaires) == 1 else None,
        "montants_variables": len(montants_unitaires) > 1,
    }


def _nombre_conflits_attributions_prime(prime, attributions):
    return sum(
        attributions_primes_se_chevauchent(
            prime.mode_calcul,
            premier.date_debut,
            premier.date_fin,
            second.date_debut,
            second.date_fin,
        )
        for index, premier in enumerate(attributions)
        for second in attributions[index + 1:]
    )


def _segments_depuis_dates(dates):
    segments = []
    for jour in dates:
        if segments and datetime.date.fromisoformat(segments[-1]["date_fin"]) + datetime.timedelta(days=1) == jour:
            segments[-1]["date_fin"] = jour.isoformat()
        else:
            segments.append({"date_debut": jour.isoformat(), "date_fin": jour.isoformat()})
    return segments


def _dates_iso_valides(valeurs):
    try:
        return sorted({datetime.date.fromisoformat(item) for item in valeurs})
    except (TypeError, ValueError):
        raise ValueError("Les jours sélectionnés sont invalides.") from None


def _synthese_attributions_prime(
    animateur, debut=None, fin=None, type_prime=None, jours_eligibles=None
):
    """Retour minimal après mutation : attributions et totaux, sans Planning/Paie."""
    queryset = AttributionPrime.objects.filter(animateur=animateur)
    if debut is not None and fin is not None:
        queryset = queryset.filter(date_debut__lte=fin, date_fin__gte=debut)
    montant_total = queryset.aggregate(total=Sum("montant_total"))["total"] or Decimal("0.00")
    if type_prime is not None:
        queryset = queryset.filter(type_prime=type_prime)
    attributions = list(queryset.select_related(
        "animateur", "type_prime", "centre"
    ).order_by("date_debut", "date_fin", "id"))
    resultat = {
        "animateur_id": animateur.id,
        "attributions": [_attribution_prime_dict(item) for item in attributions],
        "montant_total": str(montant_total.quantize(Decimal("0.01"))),
        "montant_total_type_prime": str(sum(
            (item.montant_total for item in attributions), Decimal("0.00")
        ).quantize(Decimal("0.01"))),
    }
    if type_prime is not None and debut is not None and fin is not None:
        # Le navigateur conserve les jours éligibles chargés au GET initial. La
        # mutation ne renvoie que les couvertures qui ont réellement changé.
        jours_periode = [
            debut + datetime.timedelta(days=index)
            for index in range((fin - debut).days + 1)
        ]
        resultat["contexte_prime"] = {
            "id": type_prime.id,
            "conflits_existants": _nombre_conflits_attributions_prime(type_prime, attributions),
            "resume_attributions": _resume_attributions_prime(type_prime, attributions),
            "attributions_couvertures": [{
                "id": item.id,
                "jours": [
                    jour.isoformat() for jour in jours_periode
                    if attributions_primes_se_chevauchent(
                        type_prime.mode_calcul, jour, jour, item.date_debut, item.date_fin
                    )
                ],
            } for item in attributions],
        }
        if jours_eligibles is not None:
            jours_eligibles = sorted(set(jours_eligibles))
            jours_deja = [
                jour for jour in jours_eligibles
                if any(attributions_primes_se_chevauchent(
                    type_prime.mode_calcul, jour, jour, item.date_debut, item.date_fin
                ) for item in attributions)
            ]
            deja = set(jours_deja)
            jours_disponibles = [jour for jour in jours_eligibles if jour not in deja]
            resultat["contexte_prime"].update({
                "jours_eligibles": [jour.isoformat() for jour in jours_eligibles],
                "jours_deja_attribues": [jour.isoformat() for jour in jours_deja],
                "jours_disponibles": [jour.isoformat() for jour in jours_disponibles],
                "segments_disponibles": _segments_depuis_dates(jours_disponibles),
                "entierement_attribue": bool(jours_eligibles and not jours_disponibles),
            })
    return resultat


def _periode_mutation_prime(data=None, request=None):
    data = data or {}
    debut_brut = data.get("periode_debut") or (request.GET.get("date_debut") if request else None)
    fin_brut = data.get("periode_fin") or (request.GET.get("date_fin") if request else None)
    try:
        return (
            datetime.date.fromisoformat(debut_brut) if debut_brut else None,
            datetime.date.fromisoformat(fin_brut) if fin_brut else None,
        )
    except (TypeError, ValueError):
        return None, None


def _eligibilites_primes(debut, fin, primes, jours_par_animateur):
    historiques = HistoriqueStatutAnimateur.objects.select_related("statut").filter(
        date_effet__lte=fin
    ).order_by("-date_effet", "-id")
    contrats = Contrat.objects.select_related("type_contrat_ref").filter(
        Q(date_debut__isnull=True) | Q(date_debut__lte=fin)
    ).filter(Q(date_fin__isnull=True) | Q(date_fin__gte=debut)).order_by("date_debut", "id")
    animateurs = Animateur.objects.prefetch_related(
        "qualifications",
        Prefetch("historique_statuts", queryset=historiques, to_attr="_historique_statuts_dates"),
        Prefetch("contrats", queryset=contrats, to_attr="_contrats_paie"),
    ).filter(id__in=jours_par_animateur).order_by("prenom", "nom", "id")
    attributions_par_cle = defaultdict(list)
    for attribution in AttributionPrime.objects.filter(
        animateur_id__in=jours_par_animateur,
        type_prime_id__in=[prime.id for prime in primes],
        date_debut__lte=fin,
        date_fin__gte=debut,
    ).only("id", "animateur_id", "type_prime_id", "date_debut", "date_fin", "mode_calcul"):
        attributions_par_cle[(attribution.animateur_id, attribution.type_prime_id)].append(attribution)
    resultat = []
    for animateur in animateurs:
        jours_travailles = jours_par_animateur.get(animateur.id, [])
        if not jours_travailles:
            continue
        semaines = {}
        primes_periode = []
        contextes_primes = []
        for prime in primes:
            attributions_prime = attributions_par_cle[(animateur.id, prime.id)]
            jours_eligibles = []
            for jour in jours_travailles:
                situation = situation_contractuelle_pour_date(animateur, jour)
                if prime_est_eligible(
                    prime, animateur=animateur, contrat=situation.type_contrat,
                    statut=statut_pour_date(animateur, jour), date=jour,
                ):
                    jours_eligibles.append(jour)
            if not jours_eligibles:
                continue
            if prime.mode_calcul in (TypePrime.MODE_MOIS, TypePrime.MODE_FORFAIT):
                contexte_prime = _prime_context_payload(
                    prime, jours_eligibles, attributions=attributions_prime
                )
                primes_periode.append(contexte_prime)
                contextes_primes.append(contexte_prime)
                continue
            par_semaine = {}
            for jour in jours_eligibles:
                lundi = jour - datetime.timedelta(days=jour.weekday())
                par_semaine.setdefault(lundi, []).append(jour)
            for lundi, jours_prime in par_semaine.items():
                borne_debut = max(debut, lundi)
                borne_fin = min(fin, lundi + datetime.timedelta(days=6))
                semaine = semaines.setdefault(lundi, {
                    "date_debut": borne_debut.isoformat(), "date_fin": borne_fin.isoformat(),
                    "jours_travailles": [jour.isoformat() for jour in jours_travailles if borne_debut <= jour <= borne_fin],
                    "primes_eligibles": [],
                })
                semaine["primes_eligibles"].append(_prime_context_payload(
                    prime, jours_prime, attributions=attributions_prime
                ))
            semaines_prime = []
            for lundi, jours_prime in sorted(par_semaine.items()):
                borne_debut = max(debut, lundi)
                borne_fin = min(fin, lundi + datetime.timedelta(days=6))
                semaines_prime.append({
                    "date_debut": borne_debut.isoformat(),
                    "date_fin": borne_fin.isoformat(),
                    "jours_travailles": [
                        jour.isoformat() for jour in jours_travailles
                        if borne_debut <= jour <= borne_fin
                    ],
                    "jours_eligibles": [jour.isoformat() for jour in jours_prime],
                })
            contextes_primes.append(_prime_context_payload(
                prime, jours_eligibles, semaines_eligibles=semaines_prime,
                attributions=attributions_prime,
            ))
        if semaines or primes_periode:
            resultat.append({
                "id": animateur.id,
                "semaines": [semaines[key] for key in sorted(semaines)],
                "primes_periode": primes_periode,
                "primes": contextes_primes,
            })
    return resultat


@require_http_methods(["GET", "POST"])
def api_attributions_primes(request):
    """Liste et crée les primes typées ; l'éligibilité est toujours revalidée au serveur."""

    if request.method == "GET":
        debut_brut = request.GET.get("date_debut")
        fin_brut = request.GET.get("date_fin")
        queryset = AttributionPrime.objects.select_related("animateur", "type_prime", "centre")
        if debut_brut and fin_brut:
            queryset = queryset.filter(date_debut__lte=fin_brut, date_fin__gte=debut_brut)
        primes = list(TypePrime.objects.filter(active=True).prefetch_related(
            "types_contrats_eligibles", "statuts_eligibles"
        ).order_by("nom"))
        for prime in primes:
            prime._types_contrats_eligibles_codes = {item.code for item in prime.types_contrats_eligibles.all()}
            prime._statuts_eligibles_ids = {item.id for item in prime.statuts_eligibles.all()}
        debut = datetime.date.fromisoformat(debut_brut) if debut_brut else None
        fin = datetime.date.fromisoformat(fin_brut) if fin_brut else None
        return JsonResponse({
            "types_primes": [
                {
                    "id": item.id, "nom": item.nom, "mode_calcul": item.mode_calcul,
                    "mode_libelle": item.get_mode_calcul_display(), "type_montant": item.type_montant,
                    "montant_fixe": str(item.montant_fixe) if item.montant_fixe is not None else None,
                    "montant_maximum": str(item.montant_maximum) if item.montant_maximum is not None else None,
                }
                for item in primes
            ],
            "attributions": [_attribution_prime_dict(item) for item in queryset],
            "animateurs": _eligibilites_primes(
                debut, fin, primes, _jours_travailles_pour_periode(debut, fin)
            ) if debut and fin else [],
        })
    try:
        data = json.loads(request.body or "{}")
        animateur = Animateur.objects.get(pk=int(data.get("animateur_id")))
        type_prime = TypePrime.objects.get(pk=int(data.get("type_prime_id")))
        jours_selectionnes = _dates_iso_valides(data.get("jours", [])) if "jours" in data else []
        jours_contexte = _dates_iso_valides(data.get("jours_eligibles", [])) if "jours_eligibles" in data else None
        if jours_selectionnes:
            if type_prime.mode_calcul not in (TypePrime.MODE_JOUR, TypePrime.MODE_SEMAINE):
                raise ValueError("La sélection de jours ne correspond pas au mode de cette prime.")
            jours_travailles = set(_jours_travailles_pour_periode(
                jours_selectionnes[0], jours_selectionnes[-1]
            ).get(animateur.id, []))
            if not set(jours_selectionnes).issubset(jours_travailles):
                raise ValueError("Une prime ne peut porter que sur des jours travaillés.")
            if type_prime.mode_calcul == TypePrime.MODE_SEMAINE:
                attribution = creer_attribution_prime(
                    animateur=animateur, type_prime=type_prime,
                    date_debut=jours_selectionnes[0], date_fin=jours_selectionnes[-1],
                    montant=data.get("montant"), centre=None,
                    commentaire=data.get("commentaire", ""), utilisateur=request.user,
                )
                resultat = _attribution_prime_dict(attribution)
                periode_debut, periode_fin = _periode_mutation_prime(data)
                periode_debut = periode_debut or jours_selectionnes[0]
                periode_fin = periode_fin or jours_selectionnes[-1]
                resultat["synthese"] = _synthese_attributions_prime(
                    animateur, periode_debut, periode_fin, type_prime, jours_contexte
                )
                return JsonResponse(resultat, status=201)
            with transaction.atomic():
                attributions = [
                    creer_attribution_prime(
                        animateur=animateur, type_prime=type_prime,
                        date_debut=datetime.date.fromisoformat(segment["date_debut"]),
                        date_fin=datetime.date.fromisoformat(segment["date_fin"]),
                        montant=data.get("montant"), centre=None,
                        commentaire=data.get("commentaire", ""), utilisateur=request.user,
                    )
                    for segment in _segments_depuis_dates(jours_selectionnes)
                ]
            periode_debut, periode_fin = _periode_mutation_prime(data)
            periode_debut = periode_debut or jours_selectionnes[0]
            periode_fin = periode_fin or jours_selectionnes[-1]
            return JsonResponse({
                "attributions": [_attribution_prime_dict(item) for item in attributions],
                "synthese": _synthese_attributions_prime(
                    animateur, periode_debut, periode_fin, type_prime, jours_contexte
                ),
            }, status=201)
        date_debut = datetime.date.fromisoformat(data.get("date_debut", ""))
        date_fin = datetime.date.fromisoformat(data.get("date_fin") or data.get("date_debut", ""))
        if type_prime.mode_calcul == TypePrime.MODE_SEMAINE and not _jours_travailles_pour_periode(
            date_debut, date_fin
        ).get(animateur.id, []):
            raise ValueError("Une prime hebdomadaire nécessite une semaine travaillée.")
        centre = Centre.objects.get(pk=int(data["centre_id"])) if data.get("centre_id") else None
        attribution = creer_attribution_prime(
            animateur=animateur, type_prime=type_prime, date_debut=date_debut, date_fin=date_fin,
            montant=data.get("montant"), centre=centre, commentaire=data.get("commentaire", ""),
            utilisateur=request.user,
        )
    except (ValueError, TypeError, json.JSONDecodeError, Animateur.DoesNotExist,
            TypePrime.DoesNotExist, Centre.DoesNotExist) as exc:
        return JsonResponse({"error": "Les données de la prime sont invalides."}, status=400)
    except Exception as exc:
        from django.core.exceptions import ValidationError
        if isinstance(exc, ValidationError):
            return JsonResponse({"error": exc.messages[0]}, status=400)
        raise
    resultat = _attribution_prime_dict(attribution)
    periode_debut, periode_fin = _periode_mutation_prime(data)
    periode_debut = periode_debut or attribution.date_debut
    periode_fin = periode_fin or attribution.date_fin
    resultat["synthese"] = _synthese_attributions_prime(
        animateur, periode_debut, periode_fin, type_prime, jours_contexte
    )
    return JsonResponse(resultat, status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_attribution_prime_detail(request, attribution_id):
    attribution = get_object_or_404(
        AttributionPrime.objects.select_related("animateur", "type_prime"), pk=attribution_id
    )
    if request.method == "DELETE":
        animateur = attribution.animateur
        try:
            data = json.loads(request.body or "{}")
            jours_contexte = _dates_iso_valides(data.get("jours_eligibles", [])) if "jours_eligibles" in data else None
        except (TypeError, ValueError, json.JSONDecodeError):
            jours_contexte = None
        attribution.delete()
        periode_debut, periode_fin = _periode_mutation_prime(request=request)
        return JsonResponse({
            "ok": True,
            "synthese": _synthese_attributions_prime(
                animateur, periode_debut, periode_fin, attribution.type_prime, jours_contexte
            ),
        })
    try:
        data = json.loads(request.body or "{}")
        jours_contexte = _dates_iso_valides(data.get("jours_eligibles", [])) if "jours_eligibles" in data else None
        type_prime = TypePrime.objects.get(pk=int(data.get("type_prime_id", attribution.type_prime_id)))
        animateur = Animateur.objects.get(pk=int(data.get("animateur_id", attribution.animateur_id)))
        if "jours" in data:
            jours = _dates_iso_valides(data.get("jours", []))
            if not jours or type_prime.mode_calcul != TypePrime.MODE_JOUR:
                raise ValueError
            jours_travailles = set(_jours_travailles_pour_periode(jours[0], jours[-1]).get(animateur.id, []))
            if not set(jours).issubset(jours_travailles):
                raise ValueError
            with transaction.atomic():
                nouvelles = [
                    creer_attribution_prime(
                        animateur=animateur, type_prime=type_prime,
                        date_debut=datetime.date.fromisoformat(segment["date_debut"]),
                        date_fin=datetime.date.fromisoformat(segment["date_fin"]),
                        montant=data.get("montant", attribution.montant_unitaire),
                        centre=attribution.centre, commentaire=data.get("commentaire", attribution.commentaire),
                        utilisateur=request.user, exclure_attribution_id=attribution.id,
                    ) for segment in _segments_depuis_dates(jours)
                ]
                attribution.delete()
            periode_debut, periode_fin = _periode_mutation_prime(data)
            return JsonResponse({
                "attributions": [_attribution_prime_dict(item) for item in nouvelles],
                "synthese": _synthese_attributions_prime(
                    animateur, periode_debut, periode_fin, type_prime, jours_contexte
                ),
            })
        with transaction.atomic():
            nouvelle = creer_attribution_prime(
                animateur=animateur,
                type_prime=type_prime,
                date_debut=datetime.date.fromisoformat(data.get("date_debut", attribution.date_debut.isoformat())),
                date_fin=datetime.date.fromisoformat(data.get("date_fin", attribution.date_fin.isoformat())),
                montant=data.get("montant", attribution.montant_unitaire),
                centre=attribution.centre,
                commentaire=data.get("commentaire", attribution.commentaire),
                utilisateur=request.user,
                exclure_attribution_id=attribution.id,
            )
            attribution.delete()
    except Exception as exc:
        from django.core.exceptions import ValidationError
        if isinstance(exc, ValidationError):
            return JsonResponse({"error": exc.messages[0]}, status=400)
        return JsonResponse({"error": "Les données de la prime sont invalides."}, status=400)
    resultat = _attribution_prime_dict(nouvelle)
    periode_debut, periode_fin = _periode_mutation_prime(data)
    resultat["synthese"] = _synthese_attributions_prime(
        animateur, periode_debut, periode_fin, type_prime, jours_contexte
    )
    return JsonResponse(resultat)


def export_recapitulatif_paie_pdf(request):
    """Télécharge les totaux de paie correspondant aux semaines sélectionnées."""

    debut, fin, jours_selectionnes, periodes, erreur = _selection_recapitulatif(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    recap = generer_recapitulatif(
        debut,
        fin,
        jours_selectionnes=jours_selectionnes,
        periode_ids=[periode.id for periode in periodes] if jours_selectionnes is not None else None,
    )
    _ajouter_preparation_paie(recap, periodes, debut, fin)
    dernier_jour = fin.date() - datetime.timedelta(days=1)
    contenu = generer_recapitulatif_paie_pdf(recap, debut.date(), dernier_jour)
    response = HttpResponse(contenu, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="recapitulatif_paie_{debut:%Y%m%d}_{dernier_jour:%Y%m%d}.pdf"'
    )
    return response


def export_recapitulatif_excel(request):
    """Télécharge le récapitulatif sélectionné sous forme de classeur Excel."""

    debut, fin, jours_selectionnes, periodes, erreur = _selection_recapitulatif(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    recap = generer_recapitulatif(
        debut, fin, jours_selectionnes=jours_selectionnes,
        periode_ids=[periode.id for periode in periodes] if jours_selectionnes is not None else None,
    )
    _ajouter_preparation_paie(recap, periodes, debut, fin)
    dernier_jour = fin.date() - datetime.timedelta(days=1)
    contenu = generer_recapitulatif_excel(recap, debut.date(), dernier_jour)
    response = HttpResponse(
        contenu,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="recapitulatif_{debut:%Y%m%d}_{dernier_jour:%Y%m%d}.xlsx"'
    )
    return response


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


@require_http_methods(["GET", "POST"])
def api_documents(request):
    """GET : liste des documents (les plus récents en premier).
    POST : ajoute un document multipart avec son titre, son fichier et
    soit le statut permanent, soit une période début/fin."""

    if request.method == "GET":
        documents_qs = Document.objects.prefetch_related("periodes", "centres").all().order_by("-date_ajout")
        if not est_direction(request.user):
            animateur = getattr(request.user, "profil_animateur", None)
            if animateur is None:
                documents_qs = documents_qs.none()
            else:
                affectations = Affectation.objects.filter(animateur=animateur)
                documents_visibles = []
                for document in documents_qs.filter(publie=True):
                    affectations_document = affectations
                    if not document.permanent:
                        debut = timezone.make_aware(datetime.datetime.combine(document.periode_debut, datetime.time.min))
                        fin = timezone.make_aware(datetime.datetime.combine(document.periode_fin + datetime.timedelta(days=1), datetime.time.min))
                        affectations_document = affectations_document.filter(debut__lt=fin, fin__gt=debut)
                    if not document.tous_centres:
                        affectations_document = affectations_document.filter(centre_id__in=document.centres.all())
                    if (document.tous_centres and document.permanent) or affectations_document.exists():
                        documents_visibles.append(document)
                return JsonResponse([document_to_dict(d) for d in documents_visibles], safe=False)
        return JsonResponse([document_to_dict(d) for d in documents_qs], safe=False)

    titre = request.POST.get("titre", "").strip()
    fichier = request.FILES.get("fichier")
    permanent = str(request.POST.get("permanent", "")).lower() in {"1", "true", "on", "yes"}
    periode_ids_bruts = request.POST.getlist("periode_ids") or request.POST.getlist("periode_ids[]")
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in periode_ids_bruts))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)

    periodes = []
    periode_debut = None
    periode_fin = None
    if not permanent:
        periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
        if not periode_ids:
            return JsonResponse({"error": "Sélectionne au moins une semaine ou choisis Document permanent."}, status=400)
        if len(periodes) != len(periode_ids):
            return JsonResponse({"error": "Une semaine sélectionnée est introuvable."}, status=400)
        periode_debut = min(periode.debut for periode in periodes)
        periode_fin = max(periode.fin for periode in periodes)

    if not titre or not fichier:
        return JsonResponse({"error": "Le titre et le fichier sont obligatoires."}, status=400)

    periode_debut, periode_fin, erreur = valider_periode_document(
        permanent=permanent,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
    )
    if erreur:
        return JsonResponse({"error": erreur}, status=400)

    publie = str(request.POST.get("publie", "true")).lower() in {"1", "true", "on", "yes"}
    tous_centres = str(request.POST.get("tous_centres", "true")).lower() in {"1", "true", "on", "yes"}
    centre_ids_bruts = request.POST.getlist("centre_ids") or request.POST.getlist("centre_ids[]")
    try:
        centre_ids = list(dict.fromkeys(int(value) for value in centre_ids_bruts))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de centres est invalide."}, status=400)
    centres = list(Centre.objects.filter(pk__in=centre_ids)) if not tous_centres else []
    if not tous_centres and (not centre_ids or len(centres) != len(centre_ids)):
        return JsonResponse({"error": "Sélectionne au moins un centre valide."}, status=400)
    nom_original = fichier.name
    nom_normalise = normaliser_nom_document(nom_original)
    fichier.name = nom_normalise
    stockage = Document._meta.get_field("fichier").storage
    backend_stockage = f"{stockage.__class__.__module__}.{stockage.__class__.__qualname__}"
    try:
        with transaction.atomic():
            document = Document.objects.create(
                titre=titre,
                publie=publie,
                fichier=fichier,
                permanent=permanent,
                periode_debut=periode_debut,
                periode_fin=periode_fin,
                tous_centres=tous_centres,
            )
            if periodes:
                document.periodes.set(periodes)
            document.centres.set(centres)
    except Exception as exc:
        logger.exception(
            "Échec du stockage d'un document : nom_original=%r nom_normalise=%r "
            "taille=%r type_mime=%r backend_stockage=%s exception_type=%s exception_detail=%r",
            nom_original,
            nom_normalise,
            getattr(fichier, "size", None),
            getattr(fichier, "content_type", None),
            backend_stockage,
            type(exc).__name__,
            str(exc),
        )
        return JsonResponse(
            {
                "error": "Le fichier n'a pas pu être enregistré. Réessaie plus tard."
            },
            status=503,
        )

    return JsonResponse(document_to_dict(document), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_document_detail(request, document_id):
    """Supprime un document, y compris le fichier physique/distant
    associé (sans quoi il resterait orphelin dans le stockage)."""

    try:
        document = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return JsonResponse({"error": "Document introuvable."}, status=404)

    if request.method == "DELETE":
        document.fichier.delete(save=False)
        document.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide."}, status=400)

    titre = str(payload.get("titre", document.titre)).strip()
    publie = bool(payload.get("publie", document.publie))
    permanent = bool(payload.get("permanent", document.permanent))
    tous_centres = bool(payload.get("tous_centres", document.tous_centres))
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in payload.get("periode_ids", [])))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)
    try:
        centre_ids = list(dict.fromkeys(int(value) for value in payload.get("centre_ids", [])))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de centres est invalide."}, status=400)
    centres = list(Centre.objects.filter(pk__in=centre_ids)) if not tous_centres else []
    if not tous_centres and (not centre_ids or len(centres) != len(centre_ids)):
        return JsonResponse({"error": "Sélectionne au moins un centre valide."}, status=400)

    if not titre:
        return JsonResponse({"error": "Le titre est obligatoire."}, status=400)

    periodes = []
    periode_debut = None
    periode_fin = None
    if not permanent:
        periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
        if not periode_ids:
            return JsonResponse({"error": "Sélectionne au moins une semaine ou choisis Document permanent."}, status=400)
        if len(periodes) != len(periode_ids):
            return JsonResponse({"error": "Une semaine sélectionnée est introuvable."}, status=400)
        periode_debut = min(periode.debut for periode in periodes)
        periode_fin = max(periode.fin for periode in periodes)

    document.titre = titre
    document.publie = publie
    document.permanent = permanent
    document.periode_debut = periode_debut
    document.periode_fin = periode_fin
    document.tous_centres = tous_centres
    document.save(update_fields=["titre", "publie", "permanent", "periode_debut", "periode_fin", "tous_centres"])
    document.periodes.set(periodes)
    document.centres.set(centres)

    return JsonResponse(document_to_dict(document))
