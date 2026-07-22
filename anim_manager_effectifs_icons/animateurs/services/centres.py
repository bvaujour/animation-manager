"""Règles métier liées aux centres."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from animateurs.models import Centre


def prochain_ordre_centre() -> int:
    maximum = Centre.objects.aggregate(maximum=Max("ordre"))["maximum"]
    return (maximum if maximum is not None else -1) + 1


def reordonner_centres(centre_ids: list[int]) -> None:
    centres = list(Centre.objects.all())
    ids_existants = {centre.id for centre in centres}

    if set(centre_ids) != ids_existants or len(centre_ids) != len(ids_existants):
        raise ValidationError("La liste de centres à réordonner est incomplète ou invalide.")

    centres_par_id = {centre.id: centre for centre in centres}
    with transaction.atomic():
        for ordre, centre_id in enumerate(centre_ids):
            centre = centres_par_id[centre_id]
            if centre.ordre != ordre:
                centre.ordre = ordre
                centre.save(update_fields=["ordre"])
