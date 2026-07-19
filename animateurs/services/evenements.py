"""Gestion des groupes journaliers rattachés à un lieu."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from animateurs.models import (
    Affectation,
    BesoinQualification,
    Centre,
    Evenement,
    PeriodeScolaire,
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


def _periodes(ids):
    """Retourne les périodes demandées. Une sélection vide est autorisée."""
    try:
        ids = sorted({int(value) for value in (ids or [])})
    except (TypeError, ValueError):
        raise ValidationError("La sélection des périodes est invalide.") from None
    if not ids:
        return []
    periodes = list(PeriodeScolaire.objects.filter(pk__in=ids).order_by("debut"))
    if len(periodes) != len(ids):
        raise ValidationError("Une ou plusieurs périodes sélectionnées sont introuvables.")
    return periodes


def _jours_ouverts(valeurs):
    try:
        jours = sorted({int(value) for value in (valeurs or [])})
    except (TypeError, ValueError):
        raise ValidationError("La sélection des jours d’ouverture est invalide.") from None
    if not jours or any(jour < 0 or jour > 6 for jour in jours):
        raise ValidationError("Choisis au moins un jour d’ouverture valide.")
    return jours


def _enregistrer_besoins(groupe, besoins):
    BesoinQualification.objects.filter(evenement=groupe).delete()
    for qualification_id, nombre in (besoins or {}).items():
        try:
            nombre = int(nombre)
            qualification_id = int(qualification_id)
        except (TypeError, ValueError):
            continue
        if nombre > 0 and Qualification.objects.filter(pk=qualification_id).exists():
            BesoinQualification.objects.create(
                evenement=groupe,
                qualification_id=qualification_id,
                nombre_minimum=nombre,
            )


def _jours_affectation(affectation):
    import datetime
    jour = timezone.localtime(affectation.debut).date()
    dernier = (affectation.fin - datetime.timedelta(microseconds=1)).date()
    while jour <= dernier:
        yield jour
        jour += datetime.timedelta(days=1)


def _affectations_sur_jours_fermes(groupe):
    affectations_fermees = []
    dates_fermees = []
    dates_exclues = set(groupe.dates_exclues.values_list("date", flat=True))
    for affectation in groupe.affectations.all():
        fermes = [
            jour for jour in _jours_affectation(affectation)
            if not groupe.est_ouvert_le(jour, dates_exclues)
        ]
        if fermes:
            affectations_fermees.append(affectation)
            dates_fermees.extend(fermes)
    return affectations_fermees, dates_fermees


def synchroniser_effectif_centre(centre):
    total = centre.evenements.aggregate(total=Sum("effectif_cible"))["total"] or 0
    Centre.objects.filter(pk=centre.pk).update(effectif_cible=max(1, total))
    centre.effectif_cible = max(1, total)
    return total


def prochain_ordre(centre):
    maximum = centre.evenements.aggregate(maximum=Max("ordre"))["maximum"]
    return (maximum if maximum is not None else -1) + 1


@transaction.atomic
def creer_evenement(*, centre, nom, periode_ids=None, effectif_cible=1,
                    enfants_par_animateur_defaut=8,
                    qualifications=None, jours_ouverts=None,
                    ferme_jours_feries=True, permanent=False, **_):
    nom = (nom or "").strip()
    if not nom:
        raise ValidationError("Le nom du groupe est obligatoire.")
    permanent = bool(permanent)
    # Un groupe permanent est rattaché à toutes les périodes existantes.
    # Cela évite qu’il soit interprété comme un groupe « sans période » par
    # les écrans et exports qui travaillent avec une sélection de semaines.
    periodes = list(PeriodeScolaire.objects.all().order_by("debut")) if permanent else _periodes(periode_ids)
    effectif_cible = int(effectif_cible)
    enfants_par_animateur_defaut = int(enfants_par_animateur_defaut)
    if effectif_cible < 1:
        raise ValidationError("Le nombre de personnes doit être d’au moins 1.")
    if enfants_par_animateur_defaut < 1 or enfants_par_animateur_defaut > 999:
        raise ValidationError("Le ratio d’encadrement doit être compris entre 1 et 999.")

    groupe = Evenement(
        centre=centre,
        nom=nom,
        permanent=permanent,
        effectif_cible=effectif_cible,
        enfants_par_animateur_defaut=enfants_par_animateur_defaut,
        jours_ouverts=_jours_ouverts(jours_ouverts if jours_ouverts is not None else [0, 1, 2, 3, 4, 5]),
        ferme_jours_feries=bool(ferme_jours_feries),
        ordre=prochain_ordre(centre),
    )
    groupe.full_clean()
    groupe.save()
    groupe.periodes_scolaires.set(periodes)
    _enregistrer_besoins(groupe, qualifications)
    synchroniser_effectif_centre(centre)
    return groupe


@transaction.atomic
def modifier_evenement(groupe, *, nom=None, periode_ids=None,
                       periodes_fournies=False, effectif_cible=None,
                       enfants_par_animateur_defaut=None,
                       qualifications=None, qualifications_fournies=False,
                       jours_ouverts=None, ferme_jours_feries=None, permanent=None,
                       supprimer_affectations_dates_fermees=False, **_):
    if nom is not None:
        groupe.nom = str(nom).strip()
    if effectif_cible is not None:
        groupe.effectif_cible = int(effectif_cible)
    if enfants_par_animateur_defaut is not None:
        groupe.enfants_par_animateur_defaut = int(enfants_par_animateur_defaut)
    if jours_ouverts is not None:
        groupe.jours_ouverts = _jours_ouverts(jours_ouverts)
    if ferme_jours_feries is not None:
        groupe.ferme_jours_feries = bool(ferme_jours_feries)
    if permanent is not None:
        groupe.permanent = bool(permanent)

    if groupe.permanent:
        # Permanent signifie toutes les périodes, et non aucune période.
        periodes = list(PeriodeScolaire.objects.all().order_by("debut"))
        periodes_fournies = True
    else:
        periodes = _periodes(periode_ids) if periodes_fournies else list(groupe.periodes_scolaires.all())
    groupe.full_clean()
    groupe.save()
    if periodes_fournies:
        groupe.periodes_scolaires.set(periodes)

    affectations_fermees, dates_fermees = _affectations_sur_jours_fermes(groupe)
    if affectations_fermees and not supprimer_affectations_dates_fermees:
        raise FermetureAvecAffectationsError(affectations_fermees, dates_fermees)

    if qualifications_fournies:
        _enregistrer_besoins(groupe, qualifications)
    if affectations_fermees:
        Affectation.objects.filter(pk__in=[a.pk for a in affectations_fermees]).delete()
    synchroniser_effectif_centre(groupe.centre)
    return groupe


def supprimer_evenement(groupe):
    if groupe.affectations.exists():
        raise ValidationError("Ce groupe contient des affectations et ne peut pas être supprimé.")
    centre = groupe.centre
    groupe.delete()
    synchroniser_effectif_centre(centre)


def reordonner_evenements(centre, evenement_ids):
    """Réordonne les groupes visibles sans perdre ceux qui n'ont pas de période.

    Le planning n'affiche volontairement que les groupes rattachés à au moins
    une période. Lors d'un glisser-déposer, le navigateur peut donc envoyer un
    sous-ensemble des groupes du lieu. Les groupes absents sont conservés à la
    suite, dans leur ordre relatif actuel.
    """
    groupes = list(centre.evenements.order_by("ordre", "nom", "id"))
    existants = {groupe.id: groupe for groupe in groupes}
    try:
        ids = [int(identifiant) for identifiant in evenement_ids]
    except (TypeError, ValueError):
        raise ValidationError("La liste des groupes est invalide.") from None
    if len(ids) != len(set(ids)) or not set(ids).issubset(existants):
        raise ValidationError("La liste des groupes est invalide.")

    ids_complets = ids + [groupe.id for groupe in groupes if groupe.id not in set(ids)]
    for ordre, identifiant in enumerate(ids_complets):
        Evenement.objects.filter(pk=identifiant).update(ordre=ordre)
