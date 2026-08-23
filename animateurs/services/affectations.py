"""Création, validation et modification des affectations du planning."""

import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Evenement,
    OuvertureCentrePeriode,
    PeriodeCalendrier,
    TypeAccueil,
)

from .accueils import accueil_actif_le, valider_contexte_accueil
from .disponibilites import indisponibilite_effective_sur_plage
from .flottants import (
    TYPE_AFFECTATION_FLOTTANT,
    TYPE_AFFECTATION_GROUPE,
    est_groupe_flottants,
    groupe_flottants_pour_centre,
    groupes_visibles,
)


def _ouverture_periscolaire_pour_date(centre, jour, modalite, accueil_centre=None):
    """Retourne ``(ouvert, début, fin)`` pour un créneau périscolaire.

    Dès qu'un centre possède une configuration pour la période scolaire
    concernée, elle devient la source de vérité : une modalité/journée absente
    signifie que le centre est fermé. Tant qu'aucune configuration n'existe,
    le repli sur les horaires indicatifs de la modalité préserve les données
    périscolaires déjà amorcées avant ce chantier.
    """

    if modalite is None:
        return False, None, None
    reference = (
        PeriodeCalendrier.objects.filter(
            categorie=PeriodeCalendrier.SCOLAIRE,
            debut__lte=jour,
            fin__gte=jour,
        )
        .order_by("-debut", "id")
        .first()
    )
    if reference is None:
        return True, modalite.heure_debut, modalite.heure_fin
    toutes = OuvertureCentrePeriode.objects.filter(
        centre=centre, periode_calendrier=reference, actif=True
    )
    if not toutes.exists():
        return True, modalite.heure_debut, modalite.heure_fin
    # Quand le groupe appartient à un accueil Périscolaire précis, ses
    # ouvertures deviennent la source de vérité. Une ouverture configurée pour
    # « Périscolaire — Mercredi » ne doit jamais ouvrir les groupes de
    # « Périscolaire — Semaine » dans le même lieu.
    if accueil_centre is not None:
        toutes = toutes.filter(accueil_centre=accueil_centre)
    ouverture = toutes.filter(
        modalite_periscolaire=modalite, jour_semaine=jour.weekday()
    ).first()
    if ouverture is None:
        return False, None, None
    return True, ouverture.heure_debut_effective, ouverture.heure_fin_effective


def _valider_ouverture_evenement(
    evenement, debut, fin, *, type_accueil=None, modalite_periscolaire=None
):
    try:
        type_accueil = valider_contexte_accueil(
            evenement, type_accueil, modalite_periscolaire
        )
    except ValidationError as exc:
        raise ValueError(exc.messages[0]) from exc
    dates_exclues = set(evenement.dates_exclues.values_list("date", flat=True))
    jour = debut.date()
    dernier = (fin - datetime.timedelta(microseconds=1)).date()
    while jour <= dernier:
        if type_accueil and not accueil_actif_le(evenement.centre, type_accueil, jour):
            raise ValueError(
                f"L’accueil {type_accueil.nom} de {evenement.centre.nom} n’existe pas le {jour.strftime('%d/%m/%Y')}."
            )
        if not evenement.est_ouvert_le(jour, dates_exclues):
            raise ValueError(f"Le groupe est fermé le {jour.strftime('%d/%m/%Y')}.")
        if type_accueil and type_accueil.code == TypeAccueil.PERISCOLAIRE:
            ouvert, _debut, _fin = _ouverture_periscolaire_pour_date(
                evenement.centre,
                jour,
                modalite_periscolaire,
                evenement.accueil_centre,
            )
            if not ouvert:
                nom = modalite_periscolaire.nom if modalite_periscolaire else "ce créneau"
                raise ValueError(
                    f"{evenement.centre.nom} est fermé pour « {nom} » le {jour.strftime('%d/%m/%Y')}."
                )
        jour += datetime.timedelta(days=1)


def _completer_horaires_periscolaires(affectation):
    """Crée les horaires du créneau uniquement lorsqu'ils manquent.

    Les horaires saisis manuellement restent prioritaires. Cette initialisation
    sert surtout après une création ou un déplacement vers une nouvelle date.
    """

    if (
        not affectation.type_accueil_id
        or affectation.type_accueil.code != TypeAccueil.PERISCOLAIRE
        or not affectation.modalite_periscolaire_id
    ):
        return
    jour = timezone.localtime(affectation.debut).date()
    dernier = timezone.localtime(
        affectation.fin - datetime.timedelta(microseconds=1)
    ).date()
    while jour <= dernier:
        ouvert, heure_debut, heure_fin = _ouverture_periscolaire_pour_date(
            affectation.centre,
            jour,
            affectation.modalite_periscolaire,
            affectation.evenement.accueil_centre,
        )
        if ouvert and heure_debut and heure_fin:
            affectation.horaires_journaliers.get_or_create(
                date=jour,
                defaults={"heure_arrivee": heure_debut, "heure_depart": heure_fin},
            )
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
        Affectation.objects.select_related(
            "evenement__groupe", "evenement__accueil_centre", "centre", "type_accueil", "modalite_periscolaire"
        )
        .filter(animateur=animateur, debut__lt=fin, fin__gt=debut)
        .order_by("debut", "id")
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return list(qs)


def _plages_se_chevauchent(debut_a, fin_a, debut_b, fin_b):
    if not all((debut_a, fin_a, debut_b, fin_b)):
        return True
    return debut_a < fin_b and debut_b < fin_a


def _conflit_periscolaire_effectif(
    existante, *, centre, debut, fin, type_accueil, modalite_periscolaire, accueil_centre=None
):
    """Un même salarié peut enchaîner plusieurs créneaux non chevauchants."""

    if not type_accueil or type_accueil.code != TypeAccueil.PERISCOLAIRE or modalite_periscolaire is None:
        return True
    if (
        existante.type_accueil_id is None
        or existante.type_accueil.code != TypeAccueil.PERISCOLAIRE
        or existante.modalite_periscolaire_id is None
    ):
        return True
    if existante.modalite_periscolaire_id == modalite_periscolaire.pk:
        return True

    premier = max(debut.date(), timezone.localtime(existante.debut).date())
    dernier = min(
        (fin - datetime.timedelta(microseconds=1)).date(),
        timezone.localtime(existante.fin - datetime.timedelta(microseconds=1)).date(),
    )
    jour = premier
    while jour <= dernier:
        ouvert_nouveau, debut_nouveau, fin_nouveau = _ouverture_periscolaire_pour_date(
            centre, jour, modalite_periscolaire, accueil_centre
        )
        ouvert_existant, debut_existant, fin_existant = _ouverture_periscolaire_pour_date(
            existante.centre,
            jour,
            existante.modalite_periscolaire,
            existante.evenement.accueil_centre,
        )
        if not ouvert_nouveau or not ouvert_existant:
            return True
        if _plages_se_chevauchent(debut_nouveau, fin_nouveau, debut_existant, fin_existant):
            return True
        jour += datetime.timedelta(days=1)
    return False


def animateur_en_conflit(
    animateur, debut, fin, evenement=None, exclude_id=None, *, type_accueil=None, modalite_periscolaire=None
):
    centre = evenement.centre if evenement is not None else None
    accueil_centre = evenement.accueil_centre if evenement is not None else None
    for existante in _conflits_affectation(animateur, debut, fin, exclude_id=exclude_id):
        if centre is None or _conflit_periscolaire_effectif(
            existante,
            centre=centre,
            debut=debut,
            fin=fin,
            type_accueil=type_accueil,
            modalite_periscolaire=modalite_periscolaire,
            accueil_centre=accueil_centre,
        ):
            return True
    return False


def _message_indisponibilite(animateur, indisponibilite):
    jour, resultat = indisponibilite
    if resultat.type_indisponibilite == "formation":
        formation = animateur.formations.get(pk=resultat.formation_id)
        return (
            f"{animateur.prenom} {animateur.nom} est en formation "
            f"« {formation.intitule} » le {jour.strftime('%d/%m/%Y')}."
        )
    return f"{animateur.prenom} {animateur.nom} n'est pas disponible le {jour.strftime('%d/%m/%Y')}."


def valider_affectation(
    animateur,
    debut,
    fin,
    evenement=None,
    exclude_id=None,
    *,
    autoriser_formation=False,
    type_accueil=None,
    modalite_periscolaire=None,
):
    if fin <= debut:
        return "La date de fin doit être après la date de début."
    try:
        valider_contexte_accueil(evenement, type_accueil, modalite_periscolaire)
    except ValidationError as exc:
        return exc.messages[0]
    if animateur_en_conflit(
        animateur, debut, fin, evenement=evenement, exclude_id=exclude_id,
        type_accueil=type_accueil, modalite_periscolaire=modalite_periscolaire,
    ):
        return "Cet animateur a déjà une affectation qui chevauche ce créneau."
    indisponibilite = indisponibilite_effective_sur_plage(animateur, debut, fin)
    if indisponibilite:
        if autoriser_formation and indisponibilite[1].type_indisponibilite == "formation":
            return None
        return _message_indisponibilite(animateur, indisponibilite)
    return None


@transaction.atomic
def creer_affectation(
    *, animateur, centre, debut, fin, evenement=None, autoriser_formation=False,
    type_accueil=None, modalite_periscolaire=None
):
    # Sérialise les créations concurrentes pour un même salarié. Ainsi, une
    # fiche Sorties restée ouverte ne peut pas créer un doublon si le Planning
    # a changé entre le chargement de la liste et la confirmation.
    animateur = Animateur.objects.select_for_update().get(pk=animateur.pk)
    evenement = evenement or evenement_par_defaut_pour_centre(centre)
    try:
        type_accueil = valider_contexte_accueil(
            evenement, type_accueil, modalite_periscolaire
        )
    except ValidationError as exc:
        raise ValueError(exc.messages[0]) from exc
    _valider_ouverture_evenement(
        evenement, debut, fin, type_accueil=type_accueil, modalite_periscolaire=modalite_periscolaire
    )
    erreur = valider_affectation(
        animateur, debut, fin, evenement=evenement, autoriser_formation=autoriser_formation,
        type_accueil=type_accueil, modalite_periscolaire=modalite_periscolaire,
    )
    if erreur:
        raise ValueError(erreur)
    if evenement.centre_id != centre.id:
        raise ValueError("Le groupe sélectionné n’appartient pas à ce lieu.")

    affectation = Affectation.objects.create(
        animateur=animateur,
        centre=centre,
        evenement=evenement,
        debut=debut,
        fin=fin,
        type_accueil=type_accueil,
        modalite_periscolaire=modalite_periscolaire,
    )
    _completer_horaires_periscolaires(affectation)
    return affectation


@transaction.atomic
def supprimer_jour_affectation(affectation, jour):
    """Retire un jour d'une affectation en conservant ses autres journées."""
    debut_jour = timezone.localtime(affectation.debut).date()
    fin_jour = timezone.localtime(affectation.fin - datetime.timedelta(microseconds=1)).date()
    if not debut_jour <= jour <= fin_jour:
        raise ValueError("Cette affectation ne couvre pas la date demandée.")

    debut_retrait = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
    fin_retrait = debut_retrait + datetime.timedelta(days=1)
    ancien_debut, ancienne_fin = affectation.debut, affectation.fin
    horaires = list(affectation.horaires_journaliers.all())

    def creer_segment(debut, fin, predicat):
        segment = Affectation.objects.create(
            animateur=affectation.animateur,
            centre=affectation.centre,
            evenement=affectation.evenement,
            debut=debut,
            fin=fin,
            type_accueil=affectation.type_accueil,
            modalite_periscolaire=affectation.modalite_periscolaire,
        )
        for horaire in horaires:
            if predicat(horaire.date):
                segment.horaires_journaliers.create(
                    date=horaire.date,
                    heure_arrivee=horaire.heure_arrivee,
                    heure_depart=horaire.heure_depart,
                )

    if ancien_debut < debut_retrait:
        creer_segment(ancien_debut, debut_retrait, lambda date: date < jour)
    if fin_retrait < ancienne_fin:
        creer_segment(fin_retrait, ancienne_fin, lambda date: date > jour)
    affectation.delete()


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
            type_accueil=affectation.type_accueil,
            modalite_periscolaire=affectation.modalite_periscolaire,
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
    affectation.save(update_fields=["debut", "fin", "centre", "evenement", "type_accueil", "modalite_periscolaire"])
    affectation.horaires_journaliers.exclude(
        date__gte=debut.date(),
        date__lt=fin.date(),
    ).delete()
    return affectation


@transaction.atomic
def creer_ou_deplacer_affectation_flottante(
    *, animateur, centre, debut, fin, autoriser_formation=False,
    type_accueil=None, modalite_periscolaire=None
):
    """Crée une affectation mixte sans champ SQL supplémentaire.

    L'opération est idempotente : une seconde requête identique renvoie la
    même affectation au lieu de produire un conflit 409. Si l'animateur possède
    déjà une affectation d'une seule journée dans le même lieu, cette ligne est
    déplacée vers la case mixte ; aucune affectation en double n'est créée.
    """
    if fin <= debut:
        raise ValueError("La date de fin doit être après la date de début.")

    # Le verrou du lieu garantit aussi l'unicité de la case si deux directions
    # tentent d'y déposer deux animateurs différents au même instant.
    centre = Centre.objects.select_for_update().get(pk=centre.pk)
    # Sérialise deux dépôts simultanés du même animateur.
    animateur = Animateur.objects.select_for_update().get(pk=animateur.pk)
    evenement_flottant = groupe_flottants_pour_centre(centre)
    _valider_ouverture_evenement(
        evenement_flottant, debut, fin, type_accueil=type_accueil, modalite_periscolaire=modalite_periscolaire
    )

    # Une case mixte représente une unique place par lieu et par jour.
    # Le contrôle serveur reste indispensable : deux navigateurs pourraient
    # tenter de remplir la même case presque simultanément.
    flottants_candidats = (
        Affectation.objects.filter(
            centre=centre,
            evenement=evenement_flottant,
            debut__lt=fin,
            fin__gt=debut,
        )
        .exclude(animateur=animateur)
        .select_related("animateur", "type_accueil", "modalite_periscolaire")
    )
    flottant_en_place = next((
        existante for existante in flottants_candidats
        if _conflit_periscolaire_effectif(
            existante,
            centre=centre,
            debut=debut,
            fin=fin,
            type_accueil=type_accueil,
            modalite_periscolaire=modalite_periscolaire,
        )
    ), None)
    if flottant_en_place is not None:
        raise ValueError(
            f"{flottant_en_place.animateur.prenom} est déjà animateur mixte "
            "dans ce lieu sur ce créneau."
        )

    conflits = [
        existante for existante in _conflits_affectation(animateur, debut, fin)
        if _conflit_periscolaire_effectif(
            existante,
            centre=centre,
            debut=debut,
            fin=fin,
            type_accueil=type_accueil,
            modalite_periscolaire=modalite_periscolaire,
        )
    ]
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

        # Un dépôt explicite dans la case mixte transforme l'affectation
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
            "Supprime ou raccourcis cette affectation avant de le placer comme animateur mixte."
        )

    indisponibilite = indisponibilite_effective_sur_plage(animateur, debut, fin)
    if indisponibilite:
        if autoriser_formation and indisponibilite[1].type_indisponibilite == "formation":
            indisponibilite = None
    if indisponibilite:
        raise ValueError(_message_indisponibilite(animateur, indisponibilite))

    affectation = Affectation.objects.create(
        animateur=animateur,
        centre=centre,
        evenement=evenement_flottant,
        debut=debut,
        fin=fin,
        type_accueil=type_accueil,
        modalite_periscolaire=modalite_periscolaire,
    )
    _completer_horaires_periscolaires(affectation)
    return affectation, True


@transaction.atomic
def modifier_affectation(
    affectation,
    *,
    debut=None,
    fin=None,
    centre=None,
    evenement=None,
    type_affectation=None,
    autoriser_formation=False,
    type_accueil=None,
    modalite_periscolaire=None,
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

    if type_accueil is not None:
        affectation.type_accueil = type_accueil
    try:
        affectation.type_accueil = valider_contexte_accueil(
            affectation.evenement, affectation.type_accueil, modalite_periscolaire
        )
    except ValidationError as exc:
        raise ValueError(exc.messages[0]) from exc
    if affectation.type_accueil is not None and affectation.type_accueil.code != TypeAccueil.PERISCOLAIRE:
        affectation.modalite_periscolaire = None
    elif modalite_periscolaire is not None:
        affectation.modalite_periscolaire = modalite_periscolaire

    _valider_ouverture_evenement(
        affectation.evenement, affectation.debut, affectation.fin,
        type_accueil=affectation.type_accueil,
        modalite_periscolaire=affectation.modalite_periscolaire,
    )
    erreur = valider_affectation(
        affectation.animateur,
        affectation.debut,
        affectation.fin,
        evenement=affectation.evenement,
        exclude_id=affectation.id,
        autoriser_formation=autoriser_formation,
        type_accueil=affectation.type_accueil,
        modalite_periscolaire=affectation.modalite_periscolaire,
    )
    if erreur:
        raise ValueError(erreur)

    affectation.save(
        update_fields=[
            "debut", "fin", "centre", "evenement",
            "type_accueil", "modalite_periscolaire",
        ]
    )
    affectation.horaires_journaliers.exclude(
        date__gte=affectation.debut.date(),
        date__lt=affectation.fin.date(),
    ).delete()
    _completer_horaires_periscolaires(affectation)
    return affectation
