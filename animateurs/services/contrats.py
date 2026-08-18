"""Point d'accès central aux contrats applicables à une date."""

from django.db import models
from django.utils import timezone


def contrat_pour_date(animateur, date):
    """Retourne l'unique contrat couvrant ``date``, ou ``None``."""
    return (
        animateur.contrats.filter(date_debut__lte=date)
        .filter(models.Q(date_fin__isnull=True) | models.Q(date_fin__gte=date))
        .order_by("-date_debut", "-id")
        .first()
    )


def contrat_actuel(animateur):
    return contrat_pour_date(animateur, timezone.localdate())
