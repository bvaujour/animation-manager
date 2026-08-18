"""Historique daté des statuts et compatibilité avec les qualifications."""

from dataclasses import dataclass

from django.db.models import Prefetch
from django.utils import timezone

from animateurs.models import HistoriqueStatutAnimateur, Qualification
from animateurs.services.status_colors import statut_principal_des_qualifications


ATTR_HISTORIQUE_PREFETCH = "_historique_statuts_dates"


@dataclass(frozen=True)
class SituationStatut:
    statut: Qualification | None
    source: str
    fiable: bool
    date_effet: object = None


def situation_statut_pour_date(animateur, date):
    """Retourne le statut et la fiabilité de sa source pour une date."""
    historique_prefetch = getattr(animateur, ATTR_HISTORIQUE_PREFETCH, None)
    if historique_prefetch is None:
        entree = (
            animateur.historique_statuts.select_related("statut")
            .filter(date_effet__lte=date)
            .order_by("-date_effet", "-id")
            .first()
        )
    else:
        entree = next((item for item in historique_prefetch if item.date_effet <= date), None)
    if entree:
        return SituationStatut(
            statut=entree.statut,
            source=entree.origine,
            fiable=not entree.date_effet_incertaine,
            date_effet=entree.date_effet,
        )
    statut = statut_principal_des_qualifications(animateur.qualifications.all())
    return SituationStatut(statut=statut, source="fallback_actuel", fiable=False)


def statut_pour_date(animateur, date):
    return situation_statut_pour_date(animateur, date).statut


def statut_actuel(animateur):
    return statut_pour_date(animateur, timezone.localdate())


def prefetch_historiques_statuts(queryset, *, date_fin=None):
    """Précharge les changements datés pour résoudre plusieurs jours sans N+1."""

    historique = HistoriqueStatutAnimateur.objects.select_related("statut").order_by(
        "-date_effet", "-id"
    )
    if date_fin is not None:
        historique = historique.filter(date_effet__lte=date_fin)
    return queryset.prefetch_related(
        Prefetch("historique_statuts", queryset=historique, to_attr=ATTR_HISTORIQUE_PREFETCH)
    )


def qualifications_ordinaires(animateur):
    """Conserve les diplômes/certificats, sans le statut matérialisé de compatibilité."""

    return [qualification for qualification in animateur.qualifications.all() if not qualification.est_statut]


def ids_qualifications_pour_date(animateur, date, *, qualifications=None):
    """Fusionne les qualifications ordinaires avec l'unique statut applicable à la date."""

    qualifications = list(qualifications if qualifications is not None else animateur.qualifications.all())
    ids = {qualification.id for qualification in qualifications if not qualification.est_statut}
    statut = statut_pour_date(animateur, date)
    if statut is not None:
        ids.add(statut.id)
    return ids


def synchroniser_statut_actuel(animateur):
    """Répercute uniquement le statut applicable aujourd'hui vers le M2M existant."""
    entree = (
        animateur.historique_statuts.select_related("statut")
        .filter(date_effet__lte=timezone.localdate())
        .order_by("-date_effet", "-id")
        .first()
    )
    if not entree:
        return None
    statuts_directs = Qualification.objects.filter(est_statut=True, animateur=animateur)
    animateur.qualifications.remove(*statuts_directs)
    animateur.qualifications.add(entree.statut)
    return entree.statut
