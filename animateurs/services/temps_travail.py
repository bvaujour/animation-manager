"""Sélection des périodes et salariés concernés par le temps complémentaire."""

import datetime

from django.utils import timezone

from animateurs.models import Affectation, PeriodeScolaire


class SelectionTempsTravailInvalide(ValueError):
    pass


def selectionner_periodes(identifiants):
    """Retourne les semaines, leurs dates exactes et les bornes de requête."""

    try:
        ids = {int(valeur) for valeur in identifiants}
    except (TypeError, ValueError):
        raise SelectionTempsTravailInvalide("La sélection de périodes est invalide.")
    if not ids:
        raise SelectionTempsTravailInvalide("Sélectionne au moins une période.")
    periodes = list(PeriodeScolaire.objects.filter(pk__in=ids).order_by("debut", "ordre", "id"))
    if len(periodes) != len(ids):
        raise SelectionTempsTravailInvalide("Une période sélectionnée est introuvable.")
    jours = {
        periode.debut + datetime.timedelta(days=decalage)
        for periode in periodes
        for decalage in range((periode.fin - periode.debut).days + 1)
    }
    debut = timezone.make_aware(datetime.datetime.combine(min(jours), datetime.time.min))
    fin = timezone.make_aware(
        datetime.datetime.combine(max(jours) + datetime.timedelta(days=1), datetime.time.min)
    )
    return periodes, jours, debut, fin


def animateurs_affectes_sur_jours(jours, debut, fin):
    """Retourne les animateurs ayant une vraie affectation sur les dates choisies."""

    dates_par_animateur = {}
    animateurs = {}
    affectations = (
        Affectation.objects.select_related("animateur")
        .filter(debut__lt=fin, fin__gt=debut)
        .order_by("animateur__prenom", "animateur__nom", "debut")
    )
    for affectation in affectations:
        premier = max(timezone.localtime(affectation.debut).date(), min(jours))
        dernier_exclusif = min(timezone.localtime(affectation.fin).date(), max(jours) + datetime.timedelta(days=1))
        jour = premier
        while jour < dernier_exclusif:
            if jour in jours:
                animateurs[affectation.animateur_id] = affectation.animateur
                dates_par_animateur.setdefault(affectation.animateur_id, set()).add(jour)
            jour += datetime.timedelta(days=1)
    resultat = []
    for animateur in sorted(animateurs.values(), key=lambda item: (item.prenom.casefold(), item.nom.casefold())):
        resultat.append({
            "id": animateur.id,
            "prenom": animateur.prenom,
            "nom": animateur.nom,
            "dates_affectees": [jour.isoformat() for jour in sorted(dates_par_animateur[animateur.id])],
        })
    return resultat


def ids_animateurs_affectes_a_date(animateur_ids, date):
    """Recherche les conflits sur la date réelle, hors période comprise."""

    if not animateur_ids or date is None:
        return set()
    debut = timezone.make_aware(datetime.datetime.combine(date, datetime.time.min))
    fin = debut + datetime.timedelta(days=1)
    return set(
        Affectation.objects.filter(
            animateur_id__in=animateur_ids,
            debut__lt=fin,
            fin__gt=debut,
        ).values_list("animateur_id", flat=True)
    )
