"""Gestion des événements journaliers rattachés à un lieu."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils.dateparse import parse_date

from animateurs.models import (
    Affectation,
    BesoinQualification,
    Centre,
    DateExclueEvenement,
    Evenement,
    Qualification,
)




class FermetureAvecAffectationsError(ValidationError):
    """La nouvelle configuration ferme des jours déjà planifiés."""

    def __init__(self, affectations, dates):
        self.affectations = list(affectations)
        self.dates = sorted(set(dates))
        super().__init__(
            f"{len(self.affectations)} affectation(s) existent sur "
            f"{len(self.dates)} date(s) désormais fermée(s)."
        )


def _jours_ouverts(value):
    if value is None:
        return [0, 1, 2, 3, 4, 5]
    try:
        jours = sorted({int(numero) for numero in value})
    except (TypeError, ValueError):
        raise ValidationError("Les jours habituels d’ouverture sont invalides.")
    if not jours or any(numero < 0 or numero > 6 for numero in jours):
        raise ValidationError("Choisis au moins un jour habituel d’ouverture.")
    return jours


def _dates_exclues(value, debut, fin):
    dates = set()
    for valeur in value or []:
        date = _date(valeur, "date exclue")
        if date < debut or date > fin:
            raise ValidationError("Chaque date exclue doit appartenir à la période de l’événement.")
        dates.add(date)
    return dates


def _enregistrer_dates_exclues(evenement, dates):
    evenement.dates_exclues.exclude(date__in=dates).delete()
    existantes = set(evenement.dates_exclues.filter(date__in=dates).values_list("date", flat=True))
    DateExclueEvenement.objects.bulk_create([
        DateExclueEvenement(evenement=evenement, date=date)
        for date in sorted(dates - existantes)
    ])


def _jours_affectation(affectation):
    import datetime
    jour = affectation.debut.date()
    dernier = (affectation.fin - datetime.timedelta(microseconds=1)).date()
    while jour <= dernier:
        yield jour
        jour += datetime.timedelta(days=1)


def _affectations_sur_jours_fermes(evenement, dates_exclues):
    affectations = list(evenement.affectations.all())
    affectations_fermees = []
    dates_fermees = []
    for affectation in affectations:
        jours_ouverts = {int(numero) for numero in (evenement.jours_ouverts or [])}
        jours_fermes_affectation = [
            jour for jour in _jours_affectation(affectation)
            if (evenement.debut and jour < evenement.debut)
            or (evenement.fin and jour > evenement.fin)
            or jour.weekday() not in jours_ouverts
            or jour in dates_exclues
        ]
        if jours_fermes_affectation:
            affectations_fermees.append(affectation)
            dates_fermees.extend(jours_fermes_affectation)
    return affectations_fermees, dates_fermees


def synchroniser_effectif_centre(centre):
    total = centre.evenements.filter(active=True).aggregate(total=Sum("effectif_cible"))["total"] or 0
    Centre.objects.filter(pk=centre.pk).update(effectif_cible=max(1, total))
    centre.effectif_cible = max(1, total)
    return total


def prochain_ordre(centre):
    maximum = centre.evenements.aggregate(maximum=Max("ordre"))["maximum"]
    return (maximum if maximum is not None else -1) + 1


def _date(value, libelle):
    if hasattr(value, "year"):
        return value
    parsed = parse_date(str(value or ""))
    if not parsed:
        raise ValidationError(f"La {libelle} est obligatoire.")
    return parsed


def _enregistrer_besoins(evenement, besoins):
    BesoinQualification.objects.filter(evenement=evenement).delete()
    for qualification_id, nombre in (besoins or {}).items():
        try:
            nombre = int(nombre)
            qualification_id = int(qualification_id)
        except (TypeError, ValueError):
            continue
        if nombre > 0 and Qualification.objects.filter(pk=qualification_id).exists():
            BesoinQualification.objects.create(
                evenement=evenement, qualification_id=qualification_id, nombre_minimum=nombre
            )


@transaction.atomic
def creer_evenement(*, centre, nom, debut, fin, effectif_cible=1, active=True, qualifications=None, jours_ouverts=None, dates_exclues=None, **_):
    nom = (nom or "").strip()
    if not nom:
        raise ValidationError("Le nom de l’événement est obligatoire.")
    debut, fin = _date(debut, "date de début"), _date(fin, "date de fin")
    if fin < debut:
        raise ValidationError("La date de fin doit être après la date de début.")
    effectif_cible = int(effectif_cible)
    if effectif_cible < 1:
        raise ValidationError("Le nombre de personnes doit être d’au moins 1.")
    jours_ouverts = _jours_ouverts(jours_ouverts)
    dates_exclues = _dates_exclues(dates_exclues, debut, fin)
    evenement = Evenement.objects.create(
        centre=centre, nom=nom, debut=debut, fin=fin, effectif_cible=effectif_cible,
        jours_ouverts=jours_ouverts, active=bool(active), ordre=prochain_ordre(centre)
    )
    _enregistrer_besoins(evenement, qualifications)
    _enregistrer_dates_exclues(evenement, dates_exclues)
    synchroniser_effectif_centre(centre)
    return evenement


@transaction.atomic
def modifier_evenement(evenement, *, nom=None, debut=None, fin=None, effectif_cible=None,
                       active=None, qualifications=None, qualifications_fournies=False,
                       jours_ouverts=None, jours_ouverts_fournis=False,
                       dates_exclues=None, dates_exclues_fournies=False,
                       supprimer_affectations_dates_fermees=False, **_):
    if nom is not None:
        evenement.nom = str(nom).strip()
    if debut is not None:
        evenement.debut = _date(debut, "date de début")
    if fin is not None:
        evenement.fin = _date(fin, "date de fin")
    if effectif_cible is not None:
        evenement.effectif_cible = int(effectif_cible)
    if active is not None:
        evenement.active = bool(active)
    if jours_ouverts_fournis:
        evenement.jours_ouverts = _jours_ouverts(jours_ouverts)

    evenement.full_clean()
    nouvelles_dates_exclues = (
        _dates_exclues(dates_exclues, evenement.debut, evenement.fin)
        if dates_exclues_fournies
        else set(evenement.dates_exclues.values_list("date", flat=True))
    )

    affectations_fermees, dates_fermees = _affectations_sur_jours_fermes(
        evenement, nouvelles_dates_exclues
    )
    if affectations_fermees and not supprimer_affectations_dates_fermees:
        raise FermetureAvecAffectationsError(affectations_fermees, dates_fermees)

    evenement.save()
    if qualifications_fournies:
        _enregistrer_besoins(evenement, qualifications)
    if dates_exclues_fournies:
        _enregistrer_dates_exclues(evenement, nouvelles_dates_exclues)
    if affectations_fermees:
        Affectation.objects.filter(pk__in=[a.pk for a in affectations_fermees]).delete()
    synchroniser_effectif_centre(evenement.centre)
    return evenement


def supprimer_evenement(evenement):
    if evenement.affectations.exists():
        raise ValidationError("Cet événement contient des affectations et ne peut pas être supprimé.")
    centre = evenement.centre
    evenement.delete()
    synchroniser_effectif_centre(centre)


def reordonner_evenements(centre, evenement_ids):
    existants = {e.id: e for e in centre.evenements.all()}
    if set(evenement_ids) != set(existants):
        raise ValidationError("La liste d’événements est invalide.")
    for ordre, identifiant in enumerate(evenement_ids):
        Evenement.objects.filter(pk=identifiant).update(ordre=ordre)
