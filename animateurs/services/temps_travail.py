"""Sélection des périodes et salariés concernés par le temps complémentaire."""

import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch
from django.utils import timezone

from animateurs.models import (
    Affectation, ActiviteTravailComplementaire, ParticipationTravailComplementaire,
    PeriodeScolaire,
)


class SelectionTempsTravailInvalide(ValueError):
    pass


def activites_temps_travail_pour_periodes(periodes, *, accepter_selection_englobante=False):
    """Charge les activités du même contexte de périodes que Temps de travail.

    Une plage libre de Paie ne transporte pas les identifiants sélectionnés par
    l'écran Temps de travail. Dans ce cas seulement, une activité enregistrée
    sur une sélection englobante est retenue (par exemple juillet + août pour
    un récapitulatif limité à juillet). La sélection englobante la plus proche
    évite de reprendre une saisie créée pour une seule semaine.
    """

    ids = {periode.id for periode in periodes}
    if not ids:
        return []
    participations = ParticipationTravailComplementaire.objects.select_related(
        "animateur"
    ).order_by("animateur__prenom", "animateur__nom", "animateur_id")
    candidates = list(
        ActiviteTravailComplementaire.objects.filter(periodes__in=periodes)
        .prefetch_related(
            Prefetch("periodes", to_attr="periodes_chargees"),
            Prefetch("participations", queryset=participations, to_attr="participations_chargees"),
        )
        .distinct()
    )
    signatures = {
        activite.id: frozenset(item.id for item in activite.periodes_chargees)
        for activite in candidates
    }
    resultat = []
    for type_activite in {
        ActiviteTravailComplementaire.TYPE_REUNION,
        ActiviteTravailComplementaire.TYPE_PREPARATION,
    }:
        candidates_type = [item for item in candidates if item.type == type_activite]
        exactes = [item for item in candidates_type if signatures[item.id] == ids]
        if exactes or not accepter_selection_englobante:
            resultat.extend(exactes)
            continue
        englobantes = [item for item in candidates_type if ids < signatures[item.id]]
        if englobantes:
            taille_minimale = min(len(signatures[item.id]) for item in englobantes)
            resultat.extend(
                item for item in englobantes if len(signatures[item.id]) == taille_minimale
            )
    return resultat


def comptabiliser_jours_complementaires(animateur_ids, dates_affectees, activites):
    """Source commune des réunions et préparations incluses dans la Paie."""

    resultat = defaultdict(lambda: {
        "reunion": Decimal("0"),
        "preparation": Decimal("0"),
        "dates_reunions": set(),
    })
    animateur_ids = set(animateur_ids)
    for activite in activites:
        for participation in activite.participations_chargees:
            animateur_id = participation.animateur_id
            if animateur_id not in animateur_ids:
                continue
            if activite.type == ActiviteTravailComplementaire.TYPE_REUNION:
                if (
                    activite.date in dates_affectees.get(animateur_id, set())
                    and not participation.autoriser_double_comptage
                ):
                    continue
                resultat[animateur_id]["reunion"] += participation.nombre_jours
                if activite.date:
                    resultat[animateur_id]["dates_reunions"].add(activite.date)
            elif activite.type == ActiviteTravailComplementaire.TYPE_PREPARATION:
                resultat[animateur_id]["preparation"] += participation.nombre_jours
    return resultat


def selectionner_periodes(identifiants):
    """Retourne les semaines, leurs dates exactes et les bornes de requête."""

    try:
        ids = {int(valeur) for valeur in identifiants}
    except (TypeError, ValueError):
        raise SelectionTempsTravailInvalide("La sélection de périodes est invalide.")
    if not ids:
        raise SelectionTempsTravailInvalide("Sélectionne au moins une période.")
    periodes = list(PeriodeScolaire.objects.filter(pk__in=ids).order_by("debut", "ordre", "id"))
    if len(periodes) != len(ids):
        raise SelectionTempsTravailInvalide("Une période sélectionnée est introuvable.")
    jours = {
        periode.debut + datetime.timedelta(days=decalage)
        for periode in periodes
        for decalage in range((periode.fin - periode.debut).days + 1)
    }
    debut = timezone.make_aware(datetime.datetime.combine(min(jours), datetime.time.min))
    fin = timezone.make_aware(
        datetime.datetime.combine(max(jours) + datetime.timedelta(days=1), datetime.time.min)
    )
    return periodes, jours, debut, fin


def animateurs_affectes_sur_jours(jours, debut, fin):
    """Retourne les animateurs ayant une vraie affectation sur les dates choisies."""

    dates_par_animateur = {}
    animateurs = {}
    affectations = (
        Affectation.objects.select_related("animateur")
        .filter(debut__lt=fin, fin__gt=debut)
        .order_by("animateur__prenom", "animateur__nom", "debut")
    )
    for affectation in affectations:
        premier = max(timezone.localtime(affectation.debut).date(), min(jours))
        dernier_exclusif = min(timezone.localtime(affectation.fin).date(), max(jours) + datetime.timedelta(days=1))
        jour = premier
        while jour < dernier_exclusif:
            if jour in jours:
                animateurs[affectation.animateur_id] = affectation.animateur
                dates_par_animateur.setdefault(affectation.animateur_id, set()).add(jour)
            jour += datetime.timedelta(days=1)
    resultat = []
    for animateur in sorted(animateurs.values(), key=lambda item: (item.prenom.casefold(), item.nom.casefold())):
        resultat.append({
            "id": animateur.id,
            "prenom": animateur.prenom,
            "nom": animateur.nom,
            "dates_affectees": [jour.isoformat() for jour in sorted(dates_par_animateur[animateur.id])],
        })
    return resultat


def ids_animateurs_affectes_a_date(animateur_ids, date):
    """Recherche les conflits sur la date réelle, hors période comprise."""

    if not animateur_ids or date is None:
        return set()
    debut = timezone.make_aware(datetime.datetime.combine(date, datetime.time.min))
    fin = debut + datetime.timedelta(days=1)
    return set(
        Affectation.objects.filter(
            animateur_id__in=animateur_ids,
            debut__lt=fin,
            fin__gt=debut,
        ).values_list("animateur_id", flat=True)
    )
