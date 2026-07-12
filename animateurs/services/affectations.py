"""Création, validation et modification des affectations du planning."""

from django.db import transaction

from animateurs.models import Affectation
from .disponibilites import animateur_disponible


def animateur_en_conflit(animateur, debut, fin, exclude_id=None):
    qs = Affectation.objects.filter(
        animateur=animateur,
        debut__lt=fin,
        fin__gt=debut,
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def valider_affectation(animateur, debut, fin, exclude_id=None):
    if fin <= debut:
        return "La date de fin doit être après la date de début."
    if animateur_en_conflit(animateur, debut, fin, exclude_id=exclude_id):
        return "Cet animateur a déjà une affectation ce jour-là, dans un centre ou un autre."
    if not animateur_disponible(animateur, debut, fin):
        return "Cet animateur n'est pas disponible à cette date."
    return None


@transaction.atomic
def creer_affectation(*, animateur, centre, debut, fin):
    erreur = valider_affectation(animateur, debut, fin)
    if erreur:
        raise ValueError(erreur)
    return Affectation.objects.create(animateur=animateur, centre=centre, debut=debut, fin=fin)


@transaction.atomic
def modifier_affectation(affectation, *, debut=None, fin=None, centre=None):
    if debut is not None:
        affectation.debut = debut
    if fin is not None:
        affectation.fin = fin
    if centre is not None:
        affectation.centre = centre
    erreur = valider_affectation(
        affectation.animateur,
        affectation.debut,
        affectation.fin,
        exclude_id=affectation.id,
    )
    if erreur:
        raise ValueError(erreur)
    affectation.save(update_fields=["debut", "fin", "centre"])
    return affectation
