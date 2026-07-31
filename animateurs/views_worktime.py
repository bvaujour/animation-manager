"""API des réunions et journées de télétravail/préparation."""

import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from .models import Affectation, ActiviteTravailComplementaire, ParticipationTravailComplementaire
from .services.temps_travail import (
    SelectionTempsTravailInvalide,
    animateurs_affectes_sur_jours,
    ids_animateurs_affectes_a_date,
    selectionner_periodes,
)


def _ids_periodes(request, payload=None):
    valeurs = (payload or {}).get("periode_ids")
    if valeurs is None:
        valeurs = [item for item in request.GET.get("periode_ids", "").split(",") if item]
    return valeurs


def _selection(request, payload=None):
    return selectionner_periodes(_ids_periodes(request, payload))


def _activites_selectionnees(periodes):
    """Charge en une fois les activités correspondant exactement à la sélection."""

    ids = {periode.id for periode in periodes}
    participations = ParticipationTravailComplementaire.objects.select_related("animateur").order_by(
        "animateur__prenom", "animateur__nom", "animateur_id"
    )
    candidates = (
        ActiviteTravailComplementaire.objects.filter(periodes__in=periodes)
        .prefetch_related(
            Prefetch("periodes", to_attr="periodes_chargees"),
            Prefetch("participations", queryset=participations, to_attr="participations_chargees"),
        )
        .distinct()
    )
    return [
        activite
        for activite in candidates
        if {item.id for item in activite.periodes_chargees} == ids
    ]


def _reunion_json(activite, ids_en_conflit):
    participants = []
    for participation in activite.participations_chargees:
        participants.append({
            "animateur_id": participation.animateur_id,
            "prenom": participation.animateur.prenom,
            "nom": participation.animateur.nom,
            "autoriser_double_comptage": participation.autoriser_double_comptage,
            "deja_affecte": participation.animateur_id in ids_en_conflit,
        })
    return {
        "id": activite.id,
        "intitule": activite.intitule,
        "date": activite.date.isoformat(),
        "remarque": activite.remarque,
        "periode_ids": [periode.id for periode in activite.periodes_chargees],
        "participants": participants,
    }


def _conflits_reunions(animateur_ids, dates_reunions):
    """Retourne les conflits de toutes les réunions avec une seule requête SQL."""

    dates = sorted({date for date in dates_reunions if date is not None})
    if not animateur_ids or not dates:
        return {date: set() for date in dates}

    import datetime
    from django.utils import timezone

    debut = timezone.make_aware(datetime.datetime.combine(dates[0], datetime.time.min))
    fin = timezone.make_aware(datetime.datetime.combine(dates[-1] + datetime.timedelta(days=1), datetime.time.min))
    affectations = Affectation.objects.filter(
        animateur_id__in=animateur_ids,
        debut__lt=fin,
        fin__gt=debut,
    ).values_list("animateur_id", "debut", "fin")

    conflits = {date: set() for date in dates}
    dates_set = set(dates)
    for animateur_id, debut_affectation, fin_affectation in affectations:
        premier = max(timezone.localtime(debut_affectation).date(), dates[0])
        dernier = min(timezone.localtime(fin_affectation).date(), dates[-1] + datetime.timedelta(days=1))
        jour = premier
        while jour < dernier:
            if jour in dates_set:
                conflits[jour].add(animateur_id)
            jour += datetime.timedelta(days=1)
    return conflits


def _nombre_json_local(nombre):
    valeur = Decimal(nombre)
    return int(valeur) if valeur == valeur.to_integral_value() else float(valeur)


def _donnees_temps_travail(request, periodes, jours, debut, fin):
    """Construit la page Temps de travail sans recalculer le récapitulatif complet."""

    animateurs = animateurs_affectes_sur_jours(jours, debut, fin)
    activites = _activites_selectionnees(periodes)
    ids_eligibles = {item["id"] for item in animateurs}
    dates_affectees = {
        item["id"]: set(item["dates_affectees"])
        for item in animateurs
    }

    reunions_activites = [
        item for item in activites
        if item.type == ActiviteTravailComplementaire.TYPE_REUNION
    ]
    conflits_par_date = _conflits_reunions(
        ids_eligibles,
        [item.date for item in reunions_activites],
    )
    reunions = [
        _reunion_json(activite, conflits_par_date.get(activite.date, set()))
        for activite in reunions_activites
    ]

    preparation = next(
        (item for item in activites if item.type == ActiviteTravailComplementaire.TYPE_PREPARATION),
        None,
    )
    attributions = {}
    if preparation:
        attributions = {
            item.animateur_id: {
                "nombre_jours": str(item.nombre_jours),
                "remarque": item.remarque,
            }
            for item in preparation.participations_chargees
        }

    complements = {
        animateur_id: {"reunion": Decimal("0"), "preparation": Decimal("0")}
        for animateur_id in ids_eligibles
    }
    for reunion in reunions_activites:
        date_iso = reunion.date.isoformat() if reunion.date else None
        for participation in reunion.participations_chargees:
            if participation.animateur_id not in ids_eligibles:
                continue
            deja_affecte = date_iso in dates_affectees.get(participation.animateur_id, set())
            if deja_affecte and not participation.autoriser_double_comptage:
                continue
            complements[participation.animateur_id]["reunion"] += participation.nombre_jours

    if preparation:
        for participation in preparation.participations_chargees:
            if participation.animateur_id in ids_eligibles:
                complements[participation.animateur_id]["preparation"] += participation.nombre_jours

    synthese = []
    for animateur in animateurs:
        complement = complements[animateur["id"]]
        jours_reunion = complement["reunion"]
        jours_preparation = complement["preparation"]
        jours_complementaires = jours_reunion + jours_preparation
        if not jours_complementaires:
            continue
        jours_affectation = Decimal(len(animateur["dates_affectees"]))
        synthese.append({
            "animateur_id": animateur["id"],
            "prenom": animateur["prenom"],
            "nom": animateur["nom"],
            "jours_reunion": _nombre_json_local(jours_reunion),
            "jours_preparation": _nombre_json_local(jours_preparation),
            "jours_complementaires": _nombre_json_local(jours_complementaires),
            "jours_total_recapitulatif": _nombre_json_local(jours_affectation + jours_complementaires),
        })

    total_jours_complementaires = sum(
        (Decimal(str(item["jours_complementaires"])) for item in synthese),
        Decimal("0"),
    )
    return {
        "periodes": [{
            "id": periode.id,
            "libelle": periode.libelle_avec_annee,
            "debut": periode.debut.isoformat(),
            "fin": periode.fin.isoformat(),
        } for periode in periodes],
        "animateurs": animateurs,
        "reunions": reunions,
        "preparation": attributions,
        "synthese": synthese,
        "total_jours_complementaires": _nombre_json_local(total_jours_complementaires),
    }


@require_http_methods(["GET"])
def api_temps_travail(request):
    try:
        selection = _selection(request)
    except SelectionTempsTravailInvalide as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_donnees_temps_travail(request, *selection))


@require_http_methods(["GET"])
def api_conflits_reunion(request):
    """Contrôle une date réelle sans imposer qu’elle appartienne à la période."""

    try:
        periodes, jours, debut, fin = _selection(request)
        date = parse_date(request.GET.get("date", ""))
        if date is None:
            raise ValueError("La date de réunion est invalide.")
        animateurs = animateurs_affectes_sur_jours(jours, debut, fin)
        ids_eligibles = {item["id"] for item in animateurs}
    except (SelectionTempsTravailInvalide, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({
        "animateur_ids": sorted(ids_animateurs_affectes_a_date(ids_eligibles, date)),
        "hors_periode": date not in jours,
        "periodes": [periode.libelle_avec_annee for periode in periodes],
    })


def _payload(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        raise ValueError("Les données transmises sont invalides.")


def _enregistrer_reunion(request, reunion=None):
    payload = _payload(request)
    periodes, jours, debut, fin = _selection(request, payload)
    intitule = str(payload.get("intitule", "")).strip()
    date = parse_date(str(payload.get("date", "")))
    remarque = str(payload.get("remarque", "")).strip()
    if not intitule:
        raise ValueError("L’intitulé de la réunion est obligatoire.")
    if date is None:
        raise ValueError("La date de réunion est invalide.")
    animateurs = animateurs_affectes_sur_jours(jours, debut, fin)
    ids_eligibles = {item["id"] for item in animateurs}
    ids_en_conflit = ids_animateurs_affectes_a_date(ids_eligibles, date)
    participants_bruts = payload.get("participant_ids")
    participant_ids = ids_eligibles if participants_bruts is None else {int(item) for item in participants_bruts}
    doubles = {int(item) for item in payload.get("double_comptage_ids", [])}
    if not participant_ids <= ids_eligibles:
        raise ValueError("Un participant n’est pas affecté pendant cette période.")
    if not doubles <= participant_ids or not doubles <= ids_en_conflit:
        raise ValueError("Le double comptage ne peut être confirmé qu’en présence d’une affectation à cette date.")

    with transaction.atomic():
        if reunion is None:
            reunion = ActiviteTravailComplementaire(type=ActiviteTravailComplementaire.TYPE_REUNION)
        reunion.intitule = intitule
        reunion.date = date
        reunion.remarque = remarque
        reunion.full_clean(exclude=("periodes",))
        reunion.save()
        reunion.periodes.set(periodes)
        reunion.participations.all().delete()
        ParticipationTravailComplementaire.objects.bulk_create([
            ParticipationTravailComplementaire(
                activite=reunion,
                animateur_id=animateur_id,
                nombre_jours=Decimal("1.00"),
                autoriser_double_comptage=animateur_id in doubles,
            )
            for animateur_id in participant_ids
        ])
    return reunion


@require_http_methods(["POST"])
def api_reunions(request):
    try:
        reunion = _enregistrer_reunion(request)
        periodes, jours, debut, fin = _selection(request, _payload(request))
    except (SelectionTempsTravailInvalide, ValueError, TypeError, ValidationError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        return JsonResponse({"error": message}, status=400)
    return JsonResponse({"id": reunion.id, **_donnees_temps_travail(request, periodes, jours, debut, fin)}, status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_reunion_detail(request, reunion_id):
    try:
        reunion = ActiviteTravailComplementaire.objects.get(
            pk=reunion_id,
            type=ActiviteTravailComplementaire.TYPE_REUNION,
        )
    except ActiviteTravailComplementaire.DoesNotExist:
        return JsonResponse({"error": "Réunion introuvable."}, status=404)
    if request.method == "DELETE":
        reunion.delete()
        return JsonResponse({"ok": True})
    try:
        _enregistrer_reunion(request, reunion)
    except (SelectionTempsTravailInvalide, ValueError, TypeError, ValidationError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        return JsonResponse({"error": message}, status=400)
    return JsonResponse({"ok": True})


@require_http_methods(["PUT"])
def api_preparation_travail(request):
    try:
        payload = _payload(request)
        periodes, jours, debut, fin = _selection(request, payload)
        animateurs = animateurs_affectes_sur_jours(jours, debut, fin)
        ids_eligibles = {item["id"] for item in animateurs}
        attributions = []
        for item in payload.get("attributions", []):
            animateur_id = int(item["animateur_id"])
            if animateur_id not in ids_eligibles:
                raise ValueError("Un animateur n’est pas affecté pendant cette période.")
            try:
                nombre = Decimal(str(item.get("nombre_jours", "0")).replace(",", "."))
            except InvalidOperation:
                raise ValueError("Le nombre de journées est invalide.")
            if nombre < 0 or nombre > 366:
                raise ValueError("Le nombre de journées doit être compris entre 0 et 366.")
            remarque = str(item.get("remarque", "")).strip()[:240]
            if nombre or remarque:
                attributions.append((animateur_id, nombre, remarque))
    except (KeyError, TypeError, SelectionTempsTravailInvalide, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    with transaction.atomic():
        activites = [
            item for item in _activites_selectionnees(periodes)
            if item.type == ActiviteTravailComplementaire.TYPE_PREPARATION
        ]
        activite = activites[0] if activites else ActiviteTravailComplementaire.objects.create(
            type=ActiviteTravailComplementaire.TYPE_PREPARATION,
            intitule="Télétravail / préparation",
        )
        activite.periodes.set(periodes)
        activite.participations.all().delete()
        ParticipationTravailComplementaire.objects.bulk_create([
            ParticipationTravailComplementaire(
                activite=activite,
                animateur_id=animateur_id,
                nombre_jours=nombre,
                remarque=remarque,
            )
            for animateur_id, nombre, remarque in attributions
        ])
    return JsonResponse(_donnees_temps_travail(request, periodes, jours, debut, fin))
