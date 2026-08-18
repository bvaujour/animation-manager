"""Règles métier relatives aux disponibilités des animateurs."""

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from animateurs.models import Disponibilite, Formation

from .dates import jours_couverts


@dataclass(frozen=True)
class DisponibiliteEffective:
    disponible: bool
    motif: str = ""
    type_indisponibilite: str = ""
    formation_id: int | None = None


def disponibilite_effective(animateur, jour, *, plages=None, formations=None):
    """Retourne la disponibilité réelle et, si connu, son motif.

    Ce point d'entrée central sépare la disponibilité déclarée des
    indisponibilités métier. D'autres motifs RH pourront ainsi être ajoutés
    ici sans disséminer leur logique dans le Planning.
    """
    plages = list(animateur.disponibilites.all()) if plages is None else plages
    if not any(plage.debut <= jour <= plage.fin for plage in plages):
        return DisponibiliteEffective(False, "Disponibilité non déclarée", "declaration")

    formation = formation_bloquante(animateur, jour, formations=formations)
    if formation:
        return DisponibiliteEffective(
            False,
            f"Formation — {formation.intitule}",
            "formation",
            formation.id,
        )
    return DisponibiliteEffective(True)


def formation_bloquante(animateur, jour, *, formations=None):
    """Formation active couvrant le jour, utilisée aussi pour les conflits."""
    if formations is None:
        formations = animateur.formations.filter(
            statut__in=(Formation.STATUT_PREVUE, Formation.STATUT_EN_COURS),
            date_debut__lte=jour,
            date_fin__gte=jour,
        ).order_by("date_debut", "id")
    return next(
        (
            item for item in formations
            if item.statut in (Formation.STATUT_PREVUE, Formation.STATUT_EN_COURS)
            and item.date_debut <= jour <= item.date_fin
        ),
        None,
    )


def indisponibilite_effective_sur_plage(animateur, debut, fin):
    """Renvoie la première indisponibilité d'une plage, bornes datetime."""
    plages = list(animateur.disponibilites.all())
    formations = list(
        animateur.formations.filter(
            statut__in=(Formation.STATUT_PREVUE, Formation.STATUT_EN_COURS),
            date_debut__lte=(fin - datetime.timedelta(microseconds=1)).date(),
            date_fin__gte=debut.date(),
        ).order_by("date_debut", "id")
    )
    for jour in jours_couverts(debut, fin):
        resultat = disponibilite_effective(animateur, jour, plages=plages, formations=formations)
        if not resultat.disponible:
            return jour, resultat
    return None


def animateur_disponible(animateur, debut, fin):
    """Disponible uniquement si chaque jour est effectivement disponible.

    Aucune disponibilité renseignée signifie désormais « indisponible » ;
    l'absence d'information ne doit jamais créer une affectation implicite.
    """
    return indisponibilite_effective_sur_plage(animateur, debut, fin) is None


@transaction.atomic
def fusionner_et_nettoyer_disponibilites(animateur, aujourd_hui=None):
    """Supprime le passé, recoupe à aujourd'hui et fusionne les plages contiguës."""
    aujourd_hui = aujourd_hui or timezone.localdate()
    animateur.disponibilites.filter(fin__lt=aujourd_hui).delete()
    plages = list(animateur.disponibilites.order_by("debut", "fin"))
    if not plages:
        return []

    normalisees = [(max(p.debut, aujourd_hui), p.fin) for p in plages]
    groupes = []
    debut_courant, fin_courante = normalisees[0]
    for debut, fin in normalisees[1:]:
        if debut <= fin_courante + datetime.timedelta(days=1):
            fin_courante = max(fin_courante, fin)
        else:
            groupes.append((debut_courant, fin_courante))
            debut_courant, fin_courante = debut, fin
    groupes.append((debut_courant, fin_courante))

    actuel = [(p.debut, p.fin) for p in plages]
    if actuel != groupes:
        animateur.disponibilites.all().delete()
        Disponibilite.objects.bulk_create([
            Disponibilite(animateur=animateur, debut=debut, fin=fin)
            for debut, fin in groupes
        ])
    return groupes
