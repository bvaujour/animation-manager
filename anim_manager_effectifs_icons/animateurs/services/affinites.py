"""Synchronisation des affinités persistantes entre salariés et groupes."""

from __future__ import annotations

import datetime
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from animateurs.models import Affectation, AffiniteGroupeAnimateur

from .dates import parse_to_aware_datetime


def _jours_termines(affectation, date_reference):
    """Retourne les journées terminées d'une affectation avant la date donnée."""

    debut = timezone.localtime(affectation.debut).date()
    fin = min(timezone.localtime(affectation.fin).date(), date_reference)
    jour = debut
    while jour < fin:
        yield jour
        jour += datetime.timedelta(days=1)


def recalculer_affinite_groupe(animateur_id, evenement_id, date_reference=None):
    """Recalcule une seule affinité depuis l'historique réel des affectations."""

    if not animateur_id or not evenement_id:
        return None

    date_reference = date_reference or timezone.localdate()
    limite = parse_to_aware_datetime(date_reference.isoformat())
    affectations = Affectation.objects.filter(
        animateur_id=animateur_id,
        evenement_id=evenement_id,
        debut__lt=limite,
    ).only("debut", "fin")

    jours = set()
    for affectation in affectations.iterator():
        jours.update(_jours_termines(affectation, date_reference))

    if not jours:
        AffiniteGroupeAnimateur.objects.filter(
            animateur_id=animateur_id,
            evenement_id=evenement_id,
        ).delete()
        return None

    affinite, _ = AffiniteGroupeAnimateur.objects.update_or_create(
        animateur_id=animateur_id,
        evenement_id=evenement_id,
        defaults={
            "jours_travailles": len(jours),
            "dernier_jour_travaille": max(jours),
        },
    )
    return affinite


def synchroniser_affinites_groupes(date_reference=None, animateur_ids=None):
    """Synchronise toutes les affinités depuis les journées réellement passées.

    Les affectations futures ne donnent aucun point. Une journée n'est comptée
    qu'une fois par couple animateur-groupe, même si des données historiques se
    chevauchent accidentellement.
    """

    date_reference = date_reference or timezone.localdate()
    limite = parse_to_aware_datetime(date_reference.isoformat())
    affectations = Affectation.objects.filter(debut__lt=limite).only(
        "animateur_id",
        "evenement_id",
        "debut",
        "fin",
    )
    ids = None
    if animateur_ids is not None:
        ids = {int(value) for value in animateur_ids}
        affectations = affectations.filter(animateur_id__in=ids)

    jours_par_couple = defaultdict(set)
    for affectation in affectations.iterator():
        cle = (affectation.animateur_id, affectation.evenement_id)
        jours_par_couple[cle].update(_jours_termines(affectation, date_reference))

    existantes_qs = AffiniteGroupeAnimateur.objects.all()
    if ids is not None:
        existantes_qs = existantes_qs.filter(animateur_id__in=ids)
    existantes = {
        (affinite.animateur_id, affinite.evenement_id): affinite
        for affinite in existantes_qs
    }

    a_creer = []
    a_modifier = []
    for cle, jours in jours_par_couple.items():
        if not jours:
            continue
        nombre = len(jours)
        dernier = max(jours)
        affinite = existantes.pop(cle, None)
        if affinite is None:
            a_creer.append(
                AffiniteGroupeAnimateur(
                    animateur_id=cle[0],
                    evenement_id=cle[1],
                    jours_travailles=nombre,
                    dernier_jour_travaille=dernier,
                )
            )
            continue
        if (
            affinite.jours_travailles != nombre
            or affinite.dernier_jour_travaille != dernier
        ):
            affinite.jours_travailles = nombre
            affinite.dernier_jour_travaille = dernier
            affinite.modifie_le = timezone.now()
            a_modifier.append(affinite)

    with transaction.atomic():
        if existantes:
            AffiniteGroupeAnimateur.objects.filter(
                pk__in=[affinite.pk for affinite in existantes.values()]
            ).delete()
        if a_creer:
            AffiniteGroupeAnimateur.objects.bulk_create(a_creer)
        if a_modifier:
            AffiniteGroupeAnimateur.objects.bulk_update(
                a_modifier,
                ("jours_travailles", "dernier_jour_travaille", "modifie_le"),
            )

    return {
        "creees": len(a_creer),
        "modifiees": len(a_modifier),
        "supprimees": len(existantes),
        "total": len(jours_par_couple),
    }
