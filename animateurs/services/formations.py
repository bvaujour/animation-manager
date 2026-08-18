"""Règles transversales des formations, sans dépendance à leur interface."""

import datetime

from django.utils import timezone

from animateurs.models import Affectation, Formation


def bornes_datetime_formation(formation):
    debut = timezone.make_aware(datetime.datetime.combine(formation.date_debut, datetime.time.min))
    fin = timezone.make_aware(
        datetime.datetime.combine(formation.date_fin + datetime.timedelta(days=1), datetime.time.min)
    )
    return debut, fin


def conflits_formation(formation):
    """Détaille les journées déjà affectées sans modifier le Planning."""
    debut, fin = bornes_datetime_formation(formation)
    conflits = []
    affectations = (
        Affectation.objects.filter(animateur__in=formation.animateurs.all(), debut__lt=fin, fin__gt=debut)
        .select_related("animateur", "centre", "evenement")
        .order_by("debut", "animateur__nom", "animateur__prenom")
    )
    for affectation in affectations:
        premier = max(formation.date_debut, timezone.localtime(affectation.debut).date())
        dernier = min(
            formation.date_fin,
            timezone.localtime(affectation.fin - datetime.timedelta(microseconds=1)).date(),
        )
        jour = premier
        while jour <= dernier:
            conflits.append({
                "affectation_id": affectation.id,
                "animateur_id": affectation.animateur_id,
                "animateur": f"{affectation.animateur.prenom} {affectation.animateur.nom}",
                "date": jour.isoformat(),
                "centre": affectation.centre.nom,
                "groupe": affectation.evenement.nom,
            })
            jour += datetime.timedelta(days=1)
    return conflits


def resume_formations_dashboard(aujourdhui=None, limite=4):
    aujourd_hui = aujourdhui or timezone.localdate()
    formations = list(
        Formation.objects.exclude(statut__in=(Formation.STATUT_ANNULEE, Formation.STATUT_TERMINEE))
        .prefetch_related("animateurs")
        .order_by("date_debut", "id")
    )
    formations = [
        item for item in formations
        if item.statut_calcule(aujourd_hui) in (
            Formation.STATUT_EN_COURS,
            Formation.STATUT_A_CLOTURER,
            Formation.STATUT_PREVUE,
        )
    ]
    ordre = {
        Formation.STATUT_EN_COURS: 0,
        Formation.STATUT_A_CLOTURER: 1,
        Formation.STATUT_PREVUE: 2,
    }
    formations.sort(key=lambda item: (ordre[item.statut_calcule(aujourd_hui)], item.date_debut, item.id))
    actives = [
        item for item in formations
        if item.statut_calcule(aujourd_hui) in (Formation.STATUT_EN_COURS, Formation.STATUT_PREVUE)
    ]
    conflits = {item["affectation_id"] for formation in actives for item in conflits_formation(formation)}
    return {
        "en_cours": sum(item.statut_calcule(aujourd_hui) == Formation.STATUT_EN_COURS for item in formations),
        "a_cloturer": sum(item.statut_calcule(aujourd_hui) == Formation.STATUT_A_CLOTURER for item in formations),
        "a_venir": sum(item.statut_calcule(aujourd_hui) == Formation.STATUT_PREVUE for item in formations),
        "conflits": len(conflits),
        "elements": [
            {
                "id": formation.id,
                "intitule": formation.intitule,
                "date_debut": formation.date_debut.isoformat(),
                "date_fin": formation.date_fin.isoformat(),
                "statut": formation.statut_calcule(aujourd_hui),
                "animateurs": [
                    {"prenom": item.prenom, "nom": item.nom}
                    for item in formation.animateurs.all()
                ],
            }
            for formation in formations[:limite]
        ],
    }
