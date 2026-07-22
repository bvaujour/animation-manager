"""Création, validation et modification des affectations du planning."""

import datetime

from django.db import transaction

from animateurs.models import Affectation, Animateur, Centre, Evenement

from .disponibilites import animateur_disponible
from .flottants import (
    TYPE_AFFECTATION_FLOTTANT,
    TYPE_AFFECTATION_GROUPE,
    est_groupe_flottants,
    groupe_flottants_pour_centre,
    groupes_visibles,
)


def _valider_ouverture_evenement(evenement, debut, fin):
    dates_exclues = set(evenement.dates_exclues.values_list("date", flat=True))
    jour = debut.date()
    dernier = (fin - datetime.timedelta(microseconds=1)).date()
    while jour <= dernier:
        if not evenement.est_ouvert_le(jour, dates_exclues):
            raise ValueError(f"Le groupe est fermé le {jour.strftime('%d/%m/%Y')}.")
        jour += datetime.timedelta(days=1)


def evenement_par_defaut_pour_centre(centre: Centre) -> Evenement:
    """Renvoie le premier groupe réel du lieu, jamais le groupe technique."""
    groupe = groupes_visibles(centre.evenements.all()).order_by("ordre", "id").first()
    if groupe is None:
        raise ValueError("Crée d’abord un groupe dans ce lieu.")
    return groupe


def evenements_se_chevauchent(_evenement_a=None, _evenement_b=None):
    return True


def _conflits_affectation(animateur, debut, fin, exclude_id=None):
    qs = (
        Affectation.objects.select_related("evenement__groupe", "centre")
        .filter(animateur=animateur, debut__lt=fin, fin__gt=debut)
        .order_by("debut", "id")
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return list(qs)


def animateur_en_conflit(animateur, debut, fin, evenement=None, exclude_id=None):
    return bool(_conflits_affectation(animateur, debut, fin, exclude_id=exclude_id))


def valider_affectation(animateur, debut, fin, evenement=None, exclude_id=None):
    if fin <= debut:
        return "La date de fin doit être après la date de début."
    if animateur_en_conflit(animateur, debut, fin, evenement=evenement, exclude_id=exclude_id):
        return "Cet animateur a déjà une affectation ce jour-là."
    if not animateur_disponible(animateur, debut, fin):
        return "Cet animateur n'est pas disponible à cette date."
    return None


@transaction.atomic
def creer_affectation(*, animateur, centre, debut, fin, evenement=None):
    evenement = evenement or evenement_par_defaut_pour_centre(centre)
    _valider_ouverture_evenement(evenement, debut, fin)
    erreur = valider_affectation(animateur, debut, fin, evenement=evenement)
    if erreur:
        raise ValueError(erreur)
    if evenement.centre_id != centre.id:
        raise ValueError("Le groupe sélectionné n’appartient pas à ce lieu.")

    return Affectation.objects.create(
        animateur=animateur,
        centre=centre,
        evenement=evenement,
        debut=debut,
        fin=fin,
    )


def _isoler_plage_en_flottant(affectation, evenement_flottant, debut, fin):
    """Transforme seulement la plage demandée d'une affectation plus longue."""
    ancien_debut = affectation.debut
    ancienne_fin = affectation.fin
    ancien_evenement = affectation.evenement
    ancien_centre = affectation.centre
    horaires = list(affectation.horaires_journaliers.all())

    def creer_segment(segment_debut, segment_fin, predicat_horaire):
        if segment_fin <= segment_debut:
            return None
        segment = Affectation.objects.create(
            animateur=affectation.animateur,
            centre=ancien_centre,
            evenement=ancien_evenement,
            debut=segment_debut,
            fin=segment_fin,
        )
        for horaire in horaires:
            if predicat_horaire(horaire.date):
                segment.horaires_journaliers.create(
                    date=horaire.date,
                    heure_arrivee=horaire.heure_arrivee,
                    heure_depart=horaire.heure_depart,
                )
        return segment

    creer_segment(ancien_debut, debut, lambda jour: jour < debut.date())
    creer_segment(fin, ancienne_fin, lambda jour: jour >= fin.date())

    affectation.debut = debut
    affectation.fin = fin
    affectation.centre = evenement_flottant.centre
    affectation.evenement = evenement_flottant
    affectation.save(update_fields=["debut", "fin", "centre", "evenement"])
    affectation.horaires_journaliers.exclude(
        date__gte=debut.date(),
        date__lt=fin.date(),
    ).delete()
    return affectation


@transaction.atomic
def creer_ou_deplacer_affectation_flottante(*, animateur, centre, debut, fin):
    """Crée une affectation flottante sans champ SQL supplémentaire.

    L'opération est idempotente : une seconde requête identique renvoie la
    même affectation au lieu de produire un conflit 409. Si l'animateur possède
    déjà une affectation d'une seule journée dans le même lieu, cette ligne est
    déplacée vers la case flottante ; aucune affectation en double n'est créée.
    """
    if fin <= debut:
        raise ValueError("La date de fin doit être après la date de début.")

    # Le verrou du lieu garantit aussi l'unicité de la case si deux directions
    # tentent d'y déposer deux animateurs différents au même instant.
    centre = Centre.objects.select_for_update().get(pk=centre.pk)
    # Sérialise deux dépôts simultanés du même animateur.
    animateur = Animateur.objects.select_for_update().get(pk=animateur.pk)
    evenement_flottant = groupe_flottants_pour_centre(centre)
    _valider_ouverture_evenement(evenement_flottant, debut, fin)

    # Une case flottante représente une unique place par lieu et par jour.
    # Le contrôle serveur reste indispensable : deux navigateurs pourraient
    # tenter de remplir la même case presque simultanément.
    flottant_en_place = (
        Affectation.objects.filter(
            centre=centre,
            evenement=evenement_flottant,
            debut__lt=fin,
            fin__gt=debut,
        )
        .exclude(animateur=animateur)
        .select_related("animateur")
        .first()
    )
    if flottant_en_place is not None:
        raise ValueError(
            f"{flottant_en_place.animateur.prenom} est déjà animateur flottant "
            "dans ce lieu ce jour-là."
        )

    conflits = _conflits_affectation(animateur, debut, fin)
    if conflits:
        # Double clic/double événement de drag : succès idempotent.
        for existante in conflits:
            if (
                est_groupe_flottants(existante.evenement)
                and existante.centre_id == centre.id
                and existante.debut <= debut
                and existante.fin >= fin
            ):
                return existante, False

        # Un dépôt explicite dans la case flottante transforme l'affectation
        # du même lieu. Si elle couvre plusieurs jours, seule la journée visée
        # est isolée ; les autres jours restent dans leur groupe d'origine.
        if len(conflits) == 1:
            existante = conflits[0]
            if (
                existante.centre_id == centre.id
                and existante.debut <= debut
                and existante.fin >= fin
            ):
                return _isoler_plage_en_flottant(
                    existante, evenement_flottant, debut, fin
                ), False

        autre = conflits[0]
        if autre.centre_id != centre.id:
            raise ValueError(
                f"Cet animateur est déjà affecté à {autre.centre.nom} ce jour-là."
            )
        raise ValueError(
            "Cet animateur possède déjà une affectation qui couvre cette date. "
            "Supprime ou raccourcis cette affectation avant de le placer en flottant."
        )

    if not animateur_disponible(animateur, debut, fin):
        raise ValueError("Cet animateur n'est pas disponible à cette date.")

    return (
        Affectation.objects.create(
            animateur=animateur,
            centre=centre,
            evenement=evenement_flottant,
            debut=debut,
            fin=fin,
        ),
        True,
    )


@transaction.atomic
def modifier_affectation(
    affectation,
    *,
    debut=None,
    fin=None,
    centre=None,
    evenement=None,
    type_affectation=None,
):
    if debut is not None:
        affectation.debut = debut
    if fin is not None:
        affectation.fin = fin

    if type_affectation not in (None, TYPE_AFFECTATION_GROUPE, TYPE_AFFECTATION_FLOTTANT):
        raise ValueError("Type d’affectation invalide.")

    if type_affectation == TYPE_AFFECTATION_FLOTTANT:
        centre_cible = centre or (evenement.centre if evenement is not None else affectation.centre)
        affectation.centre = centre_cible
        affectation.evenement = groupe_flottants_pour_centre(centre_cible)
    elif type_affectation == TYPE_AFFECTATION_GROUPE and est_groupe_flottants(affectation.evenement):
        if evenement is None:
            evenement = evenement_par_defaut_pour_centre(centre or affectation.centre)
        affectation.evenement = evenement
        affectation.centre = evenement.centre
    elif evenement is not None:
        affectation.evenement = evenement
        affectation.centre = evenement.centre
    elif centre is not None:
        affectation.centre = centre
        affectation.evenement = evenement_par_defaut_pour_centre(centre)

    _valider_ouverture_evenement(affectation.evenement, affectation.debut, affectation.fin)
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
    affectation.horaires_journaliers.exclude(
        date__gte=affectation.debut.date(),
        date__lt=affectation.fin.date(),
    ).delete()
    return affectation
