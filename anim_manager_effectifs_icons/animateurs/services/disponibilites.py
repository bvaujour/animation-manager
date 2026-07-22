"""Règles métier relatives aux disponibilités des animateurs."""

import datetime

from django.db import transaction
from django.utils import timezone

from animateurs.models import Disponibilite

from .dates import jours_couverts


def animateur_disponible(animateur, debut, fin):
    """Disponible uniquement si une plage couvre chaque jour demandé.

    Aucune disponibilité renseignée signifie désormais « indisponible » ;
    l'absence d'information ne doit jamais créer une affectation implicite.
    """
    plages = list(animateur.disponibilites.all())
    if not plages:
        return False
    return all(any(p.debut <= jour <= p.fin for p in plages) for jour in jours_couverts(debut, fin))


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
