"""Résolution des diplômes et des statuts qu'ils valident."""

from animateurs.models import Qualification


def couvertures_qualifications():
    """Retourne, pour chaque diplôme, son propre ID et celui de son statut."""

    couvertures = {}
    for qualification_id, statut_id in Qualification.objects.values_list("id", "statut_id"):
        couverts = {qualification_id}
        if statut_id:
            couverts.add(statut_id)
        couvertures[qualification_id] = couverts
    return couvertures
