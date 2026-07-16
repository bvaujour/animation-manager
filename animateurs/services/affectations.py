"""Création, validation et modification des affectations du planning."""

import datetime

from django.db import transaction

from animateurs.models import (
    Affectation,
    Centre,
    Evenement,
    EQUIPE_PRINCIPALE_NOM,
)
from .disponibilites import animateur_disponible




def _valider_ouverture_evenement(evenement, debut, fin):
    dates_exclues = set(evenement.dates_exclues.values_list("date", flat=True))
    jour = debut.date()
    dernier = (fin - datetime.timedelta(microseconds=1)).date()
    while jour <= dernier:
        if not evenement.est_ouvert_le(jour, dates_exclues):
            raise ValueError(
                f"L’événement est fermé le {jour.strftime('%d/%m/%Y')}."
            )
        jour += datetime.timedelta(days=1)


def evenement_par_defaut_pour_centre(centre: Centre) -> Evenement:
    """Renvoie l'événement utilisée par les écrans encore basés sur le centre.

    À l'étape 1, le front ne choisit pas encore explicitement une événement. On
    rattache donc les nouvelles affectations à la première événement active du
    centre, normalement l'« Événement principale » créée par la migration.
    """

    evenement = (
        centre.evenements.filter(active=True)
        .order_by("ordre", "id")
        .first()
    )
    if evenement is not None:
        return evenement

    return Evenement.objects.create(
        centre=centre,
        nom=EQUIPE_PRINCIPALE_NOM,
        effectif_cible=max(1, centre.effectif_cible),
        ordre=0,
        active=True,
    )


def evenements_se_chevauchent(evenement_a=None, evenement_b=None):
    return True


def animateur_en_conflit(animateur, debut, fin, evenement=None, exclude_id=None):
    qs = (
        Affectation.objects.select_related("evenement")
        .filter(
            animateur=animateur,
            debut__lt=fin,
            fin__gt=debut,
        )
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)

    return any(evenements_se_chevauchent(evenement, existante.evenement) for existante in qs)


def valider_affectation(animateur, debut, fin, evenement=None, exclude_id=None):
    if fin <= debut:
        return "La date de fin doit être après la date de début."
    if animateur_en_conflit(
        animateur,
        debut,
        fin,
        evenement=evenement,
        exclude_id=exclude_id,
    ):
        return "Cet animateur a déjà une affectation ce jour-là."
    if not animateur_disponible(animateur, debut, fin):
        return "Cet animateur n'est pas disponible à cette date."
    return None


@transaction.atomic
def creer_affectation(*, animateur, centre, debut, fin, evenement=None):
    evenement = evenement or evenement_par_defaut_pour_centre(centre)
    if not evenement.active:
        raise ValueError("Cet événement est inactif et ne peut pas recevoir de nouvelle affectation.")
    _valider_ouverture_evenement(evenement, debut, fin)
    erreur = valider_affectation(animateur, debut, fin, evenement=evenement)
    if erreur:
        raise ValueError(erreur)

    if evenement.centre_id != centre.id:
        raise ValueError("L'événement sélectionnée n'appartient pas à ce centre.")

    return Affectation.objects.create(
        animateur=animateur,
        centre=centre,
        evenement=evenement,
        debut=debut,
        fin=fin,
    )


@transaction.atomic
def modifier_affectation(affectation, *, debut=None, fin=None, centre=None, evenement=None):
    if debut is not None:
        affectation.debut = debut
    if fin is not None:
        affectation.fin = fin

    if evenement is not None:
        if not evenement.active:
            raise ValueError("Cette événement est inactive et ne peut pas recevoir d'affectation.")
        affectation.evenement = evenement
        affectation.centre = evenement.centre
    elif centre is not None:
        affectation.centre = centre
        affectation.evenement = evenement_par_defaut_pour_centre(centre)

    _valider_ouverture_evenement(
        affectation.evenement, affectation.debut, affectation.fin
    )

    erreur = valider_affectation(
        affectation.animateur,
        affectation.debut,
        affectation.fin,
        evenement=affectation.evenement,
        exclude_id=affectation.id,
    )
    if erreur:
        raise ValueError(erreur)

    affectation.save(update_fields=["debut", "fin", "centre", "evenement"])
    return affectation
