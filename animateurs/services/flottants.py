"""Animateurs flottants sans colonne dédiée dans ``Affectation``.

Une affectation flottante reste une affectation Django classique. Elle est
identifiée uniquement par son rattachement à un groupe technique invisible,
créé une fois par lieu. Aucun booléen ``est_flottant`` n'est stocké dans la
table des affectations.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from animateurs.models import Evenement, Groupe, normaliser_cle_unique

NOM_GROUPE_FLOTTANTS = "__animateurs_flottants__"
CLE_GROUPE_FLOTTANTS = normaliser_cle_unique(NOM_GROUPE_FLOTTANTS)
TYPE_AFFECTATION_GROUPE = "groupe"
TYPE_AFFECTATION_FLOTTANT = "flottant"
# ``PositiveSmallIntegerField`` est un ``smallint`` signé sous PostgreSQL.
# Garder le groupe technique en dernière position sans dépasser sa borne.
ORDRE_GROUPE_FLOTTANTS = 32767


def est_groupe_flottants(evenement) -> bool:
    """Indique si une instance de groupe représente la case flottante."""
    if evenement is None:
        return False
    groupe = getattr(evenement, "groupe", None)
    cle = getattr(groupe, "cle_unique", "") or getattr(evenement, "cle_unique", "")
    return cle == CLE_GROUPE_FLOTTANTS


def est_affectation_flottante(affectation) -> bool:
    return bool(affectation and est_groupe_flottants(getattr(affectation, "evenement", None)))


def type_affectation(affectation) -> str:
    return TYPE_AFFECTATION_FLOTTANT if est_affectation_flottante(affectation) else TYPE_AFFECTATION_GROUPE


def groupes_visibles(queryset):
    """Exclut le groupe technique d'un queryset d'instances ``Evenement``."""
    return queryset.exclude(groupe__cle_unique=CLE_GROUPE_FLOTTANTS)


def groupes_partages_visibles(queryset):
    """Exclut le groupe technique d'un queryset de ``Groupe`` partagés."""
    return queryset.exclude(cle_unique=CLE_GROUPE_FLOTTANTS)


def _obtenir_groupe_technique() -> Groupe:
    groupe = Groupe.objects.filter(cle_unique=CLE_GROUPE_FLOTTANTS).first()
    if groupe is not None:
        return groupe

    try:
        with transaction.atomic():
            return Groupe.objects.create(
                nom=NOM_GROUPE_FLOTTANTS,
                enfants_par_animateur_defaut=1,
            )
    except IntegrityError:
        # Deux requêtes peuvent arriver presque simultanément lors d'un dépôt.
        groupe = Groupe.objects.filter(cle_unique=CLE_GROUPE_FLOTTANTS).first()
        if groupe is None:
            raise
        return groupe


def groupe_flottants_pour_centre(centre) -> Evenement:
    """Crée/récupère la destination technique invisible d'un lieu."""
    groupe = _obtenir_groupe_technique()
    evenement = Evenement.objects.filter(centre=centre, groupe=groupe).first()
    if evenement is not None:
        return evenement

    try:
        with transaction.atomic():
            return Evenement.objects.create(
                centre=centre,
                groupe=groupe,
                nom=NOM_GROUPE_FLOTTANTS,
                permanent=True,
                ferme_jours_feries=False,
                effectif_cible=1,
                enfants_par_animateur_defaut=1,
                jours_ouverts=[0, 1, 2, 3, 4, 5, 6],
                ordre=ORDRE_GROUPE_FLOTTANTS,
            )
    except IntegrityError:
        evenement = Evenement.objects.filter(centre=centre, groupe=groupe).first()
        if evenement is None:
            raise
        return evenement
