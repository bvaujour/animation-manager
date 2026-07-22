"""Outils de dates partagés par les services métier et les API."""

import datetime

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime


def parse_to_aware_datetime(value):
    """Convertit une date/datetime ISO en datetime aware."""
    dt = parse_datetime(value)
    if dt is None:
        date_seule = parse_date(value)
        if date_seule is None:
            raise ValueError(f"Date invalide : {value!r}")
        dt = datetime.datetime.combine(date_seule, datetime.time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def jours_couverts(debut, fin):
    """Liste les jours couverts par l'intervalle semi-ouvert [debut, fin)."""
    jour = debut.date()
    dernier_jour = fin.date()
    jours = []
    while jour < dernier_jour:
        jours.append(jour)
        jour += datetime.timedelta(days=1)
    return jours or [debut.date()]
