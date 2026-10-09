"""Workflow métier des campagnes et demandes de disponibilités.

Ce module ne sert volontairement pas le Planning : les propositions restent
isolées jusqu'à l'application transactionnelle d'une demande validée dans les
plages officielles ``Disponibilite``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from animateurs.models import (
    Animateur,
    CampagneDisponibilite,
    DemandeDisponibilite,
    Disponibilite,
    PeriodeScolaire,
    PropositionDisponibiliteDate,
)


@dataclass(frozen=True)
class ConflitDisponibiliteDemande:
    """Écart détecté entre l'instantané d'une proposition et l'officiel."""

    date: datetime.date
    etait_disponible: bool
    est_disponible_actuellement: bool


class ApplicationDemandeDisponibiliteEnConflit(Exception):
    """Empêche une validation qui écraserait une disponibilité plus récente."""

    def __init__(self, conflits):
        self.conflits = tuple(conflits)
        super().__init__("La disponibilité officielle a changé depuis la demande.")


class DemandeDisponibiliteIncomplete(Exception):
    """Une réponse contient encore une date que l'animateur n'a pas renseignée."""


class ApplicationDemandeDisponibiliteGranulariteNonSupportee(Exception):
    """Le planning officiel ne sait pas encore enregistrer une demi-journée."""

    def __init__(self, propositions):
        self.propositions = tuple(propositions)
        super().__init__("Une disponibilité matin ou après-midi ne peut pas encore devenir officielle.")


def campagne_origine_demande(demande):
    """Retrouve le contexte de campagne d'une chaîne de versions, sans l'altérer."""
    courante = demande
    deja_vues = set()
    while courante is not None and courante.pk not in deja_vues:
        deja_vues.add(courante.pk)
        if courante.campagne_id:
            return courante.campagne
        courante = courante.demande_precedente
    return None


def version_courante_demande(demande):
    """Suit une chaîne de versions sans supposer qu'elle est bien formée."""
    courante = demande
    deja_vues = set()
    while courante is not None and courante.pk not in deja_vues:
        deja_vues.add(courante.pk)
        suivante = courante.versions_suivantes.order_by("cree_le", "pk").first()
        if suivante is None:
            return courante
        courante = suivante
    return demande


def demande_modification_autonome_active(animateur, *, verrouiller=False):
    """Retourne l'unique chaîne autonome encore en cours pour un animateur.

    Une correction de campagne est volontairement exclue : sa racine porte une
    campagne, tandis qu'une demande spontanée commence hors campagne.
    """
    racines = DemandeDisponibilite.objects.filter(
        animateur=animateur,
        nature=DemandeDisponibilite.MODIFICATION,
        campagne__isnull=True,
        demande_precedente__isnull=True,
    ).order_by("cree_le", "pk")
    if verrouiller:
        racines = racines.select_for_update()
    for racine in racines:
        courante = version_courante_demande(racine)
        if courante.statut in {DemandeDisponibilite.BROUILLON, DemandeDisponibilite.ENVOYEE}:
            return courante
    return None


def jours_modification_autonome_autorises(*, aujourd_hui=None):
    """Jours ouvrés présents ou futurs issus du calendrier scolaire connu."""
    aujourd_hui = aujourd_hui or timezone.localdate()
    jours = set()
    for periode in PeriodeScolaire.objects.filter(fin__gte=aujourd_hui).order_by("debut", "ordre", "pk"):
        jour = max(periode.debut, aujourd_hui)
        while jour <= periode.fin:
            if jour.weekday() < 5:
                jours.add(jour)
            jour += datetime.timedelta(days=1)
    return jours


@transaction.atomic
def obtenir_ou_creer_brouillon_modification_autonome(animateur):
    """Sérialise la création afin que deux clics ne créent pas deux brouillons."""
    animateur = Animateur.objects.select_for_update().get(pk=animateur.pk)
    demande = demande_modification_autonome_active(animateur, verrouiller=True)
    if demande is not None:
        return demande, False
    return DemandeDisponibilite.objects.create(
        animateur=animateur,
        nature=DemandeDisponibilite.MODIFICATION,
        statut=DemandeDisponibilite.BROUILLON,
    ), True


@transaction.atomic
def enregistrer_modification_autonome(demande, souhaits):
    """Met à jour un brouillon autonome en ne gardant que le vrai différentiel.

    Le snapshot d'une ligne déjà créée reste immuable ; seuls les nouveaux
    écarts prennent l'état officiel observé au moment de leur apparition.
    """
    demande = DemandeDisponibilite.objects.select_for_update().get(pk=demande.pk)
    if (
        demande.nature != DemandeDisponibilite.MODIFICATION
        or demande.campagne_id
        or demande.demande_precedente_id
        or demande.statut != DemandeDisponibilite.BROUILLON
    ):
        raise ValidationError("Cette demande de modification ne peut pas être modifiée.")
    jours_autorises = jours_modification_autonome_autorises()
    if set(souhaits) - jours_autorises:
        raise ValidationError("Une date demandée est passée ou ne fait pas partie des périodes autorisées.")
    if any(valeur not in {PropositionDisponibiliteDate.JOURNEE, PropositionDisponibiliteDate.INDISPONIBLE} for valeur in souhaits.values()):
        raise ValidationError("Une demande autonome accepte uniquement des journées entières.")

    existantes = {proposition.date: proposition for proposition in demande.propositions.select_for_update()}
    dates = sorted(set(souhaits) | set(existantes))
    officielles = list(Disponibilite.objects.filter(
        animateur=demande.animateur,
        debut__lte=dates[-1] if dates else timezone.localdate(),
        fin__gte=dates[0] if dates else timezone.localdate(),
    )) if dates else []
    for jour in dates:
        est_disponible = _est_officiellement_disponible(officielles, jour)
        souhait = souhaits.get(jour, PropositionDisponibiliteDate.JOURNEE if est_disponible else PropositionDisponibiliteDate.INDISPONIBLE)
        proposition = existantes.get(jour)
        if proposition is not None:
            # La référence d'un brouillon existant est son snapshot, jamais
            # l'officiel relu aujourd'hui : sinon une modification concurrente
            # pourrait effacer le conflit à l'insu de l'animateur.
            choix_initial = (
                PropositionDisponibiliteDate.JOURNEE if proposition.etait_disponible
                else PropositionDisponibiliteDate.INDISPONIBLE
            )
            if souhait == choix_initial:
                proposition.delete()
            elif proposition.creneau != souhait:
                proposition.creneau = souhait
                proposition.save(update_fields=["creneau"])
            continue
        if (souhait == PropositionDisponibiliteDate.JOURNEE) == est_disponible:
            continue
        if proposition is None:
            PropositionDisponibiliteDate.objects.create(
                demande=demande,
                date=jour,
                creneau=souhait,
                etait_disponible=est_disponible,
            )
    return demande


def _est_officiellement_disponible(plages, jour):
    return any(plage.debut <= jour <= plage.fin for plage in plages)


def _creer_plage(animateur, debut, fin, types_accueil_ids):
    plage = Disponibilite.objects.create(animateur=animateur, debut=debut, fin=fin)
    if types_accueil_ids:
        plage.types_accueil.set(types_accueil_ids)
    return plage


def _fragments_sans_dates(plage, dates_a_retirer):
    """Découpe une plage seulement là où des jours doivent être retirés."""
    jours = sorted(jour for jour in dates_a_retirer if plage.debut <= jour <= plage.fin)
    if not jours:
        return [(plage.debut, plage.fin)]
    fragments = []
    debut = plage.debut
    for jour in jours:
        if debut < jour:
            fragments.append((debut, jour - datetime.timedelta(days=1)))
        debut = jour + datetime.timedelta(days=1)
    if debut <= plage.fin:
        fragments.append((debut, plage.fin))
    return fragments


def _fusionner_ajouts_generaux(animateur, jours_ajoutes):
    """Fusionne seulement la composante générale touchée par les nouveaux jours.

    Une disponibilité avec ``types_accueil`` n'est jamais assimilée à une
    disponibilité générale. Cette limite locale conserve les autres lignes et
    leurs métadonnées, y compris leurs identifiants, intactes.
    """
    if not jours_ajoutes:
        return
    dates_composante = set(jours_ajoutes)
    plages = list(
        Disponibilite.objects.select_for_update()
        .filter(animateur=animateur, types_accueil__isnull=True)
        .order_by("debut", "fin", "id")
    )
    selection = set()
    progression = True
    while progression:
        progression = False
        for plage in plages:
            if plage.pk in selection:
                continue
            if any(plage.debut <= jour + datetime.timedelta(days=1) and plage.fin >= jour - datetime.timedelta(days=1) for jour in dates_composante):
                selection.add(plage.pk)
                progression = True
                jour = plage.debut
                while jour <= plage.fin:
                    dates_composante.add(jour)
                    jour += datetime.timedelta(days=1)
    composante = [plage for plage in plages if plage.pk in selection]
    if not composante:
        return
    # Toutes ces plages sont jointives par construction : une unique plage est
    # la représentation minimale, sans toucher aux autres disponibilités.
    debut = min(plage.debut for plage in composante)
    fin = max(plage.fin for plage in composante)
    if len(composante) == 1 and composante[0].debut == debut and composante[0].fin == fin:
        return
    Disponibilite.objects.filter(pk__in=[plage.pk for plage in composante]).delete()
    _creer_plage(animateur, debut, fin, ())


@transaction.atomic
def ouvrir_campagne(campagne, animateurs=None):
    """Ouvre une campagne et crée une demande initiale par destinataire."""
    campagne = CampagneDisponibilite.objects.select_for_update().get(pk=campagne.pk)
    if campagne.statut != CampagneDisponibilite.BROUILLON:
        raise ValidationError("Seule une campagne brouillon peut être ouverte.")
    dates = list(campagne.dates.select_related("bloc").order_by("date", "ordre", "id"))
    if not dates:
        raise ValidationError("Une campagne doit contenir au moins une date.")

    animateurs = list(campagne.destinataires.all() if animateurs is None else animateurs)
    if not animateurs:
        raise ValidationError("Sélectionne au moins un animateur destinataire.")
    demandes = []
    for animateur in animateurs:
        demande = DemandeDisponibilite.objects.create(
            animateur=animateur,
            campagne=campagne,
            nature=DemandeDisponibilite.PREMIERE_SAISIE,
        )
        officielles = list(
            Disponibilite.objects.filter(
                animateur=animateur, debut__lte=dates[-1].date, fin__gte=dates[0].date
            )
        )
        PropositionDisponibiliteDate.objects.bulk_create([
            PropositionDisponibiliteDate(
                demande=demande,
                date_campagne=date_campagne,
                date=date_campagne.date,
                # Une date non renseignée n'est jamais assimilée à une
                # indisponibilité : elle rend seulement la réponse incomplète.
                creneau=PropositionDisponibiliteDate.NON_RENSEIGNE,
                etait_disponible=_est_officiellement_disponible(officielles, date_campagne.date),
            )
            for date_campagne in dates
        ])
        demandes.append(demande)
    campagne.statut = CampagneDisponibilite.OUVERTE
    campagne.ouverte_le = timezone.now()
    campagne.save(update_fields=["statut", "ouverte_le"])
    return demandes


@transaction.atomic
def cloturer_campagne(campagne):
    """Clôture définitivement une campagne ouverte sans toucher aux réponses."""
    campagne = CampagneDisponibilite.objects.select_for_update().get(pk=campagne.pk)
    if campagne.statut != CampagneDisponibilite.OUVERTE:
        raise ValidationError("Seule une campagne ouverte peut être clôturée.")
    campagne.statut = CampagneDisponibilite.CLOTUREE
    campagne.cloturee_le = timezone.now()
    campagne.save(update_fields=["statut", "cloturee_le"])
    return campagne


@transaction.atomic
def creer_demande_modification(
    animateur, propositions, *, commentaire_animateur="", demande_precedente=None,
    dates_campagne=None,
):
    """Crée un brouillon indépendant portant seulement sur les dates voulues.

    ``propositions`` est un mapping ``date -> creneau``. L'instantané
    officiel est pris ici, avant toute modification éventuelle du brouillon.
    """
    valeurs = dict(propositions)
    dates_campagne = dict(dates_campagne or {})
    if not valeurs:
        raise ValidationError("Une demande de modification doit contenir au moins une date.")
    if any(not isinstance(jour, datetime.date) for jour in valeurs):
        raise ValidationError("Les dates de disponibilité sont invalides.")
    if any(valeur not in dict(PropositionDisponibiliteDate.CRENEAUX) for valeur in valeurs.values()):
        raise ValidationError("Un créneau de disponibilité est invalide.")
    if any(jour not in valeurs or date_campagne.date != jour for jour, date_campagne in dates_campagne.items()):
        raise ValidationError("Les dates de campagne de la correction sont invalides.")
    demande = DemandeDisponibilite.objects.create(
        animateur=animateur,
        nature=DemandeDisponibilite.MODIFICATION,
        statut=DemandeDisponibilite.BROUILLON,
        commentaire_animateur=commentaire_animateur,
        demande_precedente=demande_precedente,
    )
    jours = sorted(valeurs)
    officielles = list(
        Disponibilite.objects.filter(animateur=animateur, debut__lte=jours[-1], fin__gte=jours[0])
    )
    PropositionDisponibiliteDate.objects.bulk_create([
        PropositionDisponibiliteDate(
            demande=demande, date_campagne=dates_campagne.get(jour), date=jour, creneau=valeurs[jour],
            etait_disponible=_est_officiellement_disponible(officielles, jour),
        )
        for jour in jours
    ])
    return demande


def _verifier_lignes_campagne(demande):
    attendues = set(demande.campagne.dates.values_list("date", flat=True))
    recues = set(demande.propositions.values_list("date", flat=True))
    if recues != attendues:
        raise ValidationError("La réponse doit porter exactement sur toutes les dates de la campagne.")


def _verifier_creneaux_explicites(demande):
    propositions = list(demande.propositions.select_related("date_campagne__bloc"))
    if any(proposition.creneau == PropositionDisponibiliteDate.NON_RENSEIGNE for proposition in propositions):
        raise DemandeDisponibiliteIncomplete("Toutes les dates doivent être renseignées avant l’envoi.")
    for proposition in propositions:
        bloc = proposition.date_campagne.bloc if proposition.date_campagne_id else None
        if (
            bloc is not None
            and bloc.mode_saisie == bloc.JOURNEE
            and proposition.creneau not in {PropositionDisponibiliteDate.INDISPONIBLE, PropositionDisponibiliteDate.JOURNEE}
        ):
            raise ValidationError("Un bloc à la journée ne peut pas contenir de demi-journée.")


@transaction.atomic
def envoyer_demande(demande):
    """Fige une demande envoyée, ou valide immédiatement une campagne sans contrôle."""
    demande = DemandeDisponibilite.objects.select_for_update().get(pk=demande.pk)
    if demande.nature == DemandeDisponibilite.PREMIERE_SAISIE:
        _verifier_lignes_campagne(demande)
    elif not demande.propositions.exists():
        raise ValidationError("Une demande de modification doit contenir au moins une date.")
    _verifier_creneaux_explicites(demande)
    demande.transition_vers(DemandeDisponibilite.ENVOYEE)
    demande.envoyee_le = timezone.now()
    demande.save(update_fields=["statut", "envoyee_le"])
    if not demande.validation_requise:
        try:
            return appliquer_demande_validee(demande, traite_par=None)
        except ApplicationDemandeDisponibiliteGranulariteNonSupportee:
            # Le sous-bloc atomique de l'application est annulé : aucune
            # journée officielle n'est créée ni retirée. La réponse, elle,
            # reste envoyée pour être traitée explicitement par la direction.
            return demande
    return demande


@transaction.atomic
def demander_correction(demande, *, traite_par, commentaire_direction=""):
    """Clôture la version envoyée en demandant une nouvelle version."""
    demande = DemandeDisponibilite.objects.select_for_update().get(pk=demande.pk)
    demande.transition_vers(DemandeDisponibilite.A_CORRIGER)
    demande.commentaire_direction = commentaire_direction
    demande.traitee_le = timezone.now()
    demande.traitee_par = traite_par
    demande.save(update_fields=["statut", "commentaire_direction", "traitee_le", "traitee_par"])
    return demande


@transaction.atomic
def refuser_demande(demande, *, traite_par, commentaire_direction=""):
    """Refuse une demande envoyée sans modifier les disponibilités officielles."""
    demande = DemandeDisponibilite.objects.select_for_update().get(pk=demande.pk)
    demande.transition_vers(DemandeDisponibilite.REFUSEE)
    demande.commentaire_direction = commentaire_direction
    demande.traitee_le = timezone.now()
    demande.traitee_par = traite_par
    demande.save(update_fields=["statut", "commentaire_direction", "traitee_le", "traitee_par"])
    return demande


def creer_version_correction(demande, propositions, *, commentaire_animateur="", dates_campagne=None):
    """Crée une nouvelle version plutôt que de rouvrir une réponse figée."""
    if demande.statut != DemandeDisponibilite.A_CORRIGER:
        raise ValidationError("Une nouvelle version est possible après une demande de correction.")
    return creer_demande_modification(
        demande.animateur,
        propositions,
        commentaire_animateur=commentaire_animateur,
        demande_precedente=demande,
        dates_campagne=dates_campagne,
    )


@transaction.atomic
def demander_correction_et_creer_version(demande, *, traite_par, commentaire_direction):
    """Fige l'originale puis prépare une version modifiable préremplie."""
    demande = DemandeDisponibilite.objects.select_for_update().get(pk=demande.pk)
    if demande.statut != DemandeDisponibilite.ENVOYEE:
        raise ValidationError("Seule une réponse envoyée peut faire l’objet d’une correction.")
    if not commentaire_direction.strip():
        raise ValidationError("Explique la correction attendue.")
    propositions = {
        proposition.date: proposition.creneau
        for proposition in demande.propositions.select_for_update().all()
    }
    dates_campagne = {
        proposition.date: proposition.date_campagne
        for proposition in demande.propositions.select_related("date_campagne").all()
        if proposition.date_campagne_id
    }
    originale = demander_correction(
        demande, traite_par=traite_par, commentaire_direction=commentaire_direction.strip()
    )
    return creer_version_correction(originale, propositions, dates_campagne=dates_campagne)


def analyser_application_demande(demande):
    """Expose l'impact de lecture sans remplacer les contrôles de validation."""
    propositions = list(demande.propositions.order_by("date", "id"))
    if not propositions:
        return {"conflits": (), "ajouts": 0, "retraits": 0, "inchangés": 0, "demi_journees": ()}
    dates = [proposition.date for proposition in propositions]
    officielles = list(Disponibilite.objects.filter(
        animateur=demande.animateur, debut__lte=max(dates), fin__gte=min(dates)
    ))
    conflits = tuple(
        ConflitDisponibiliteDemande(
            date=proposition.date,
            etait_disponible=proposition.etait_disponible,
            est_disponible_actuellement=_est_officiellement_disponible(officielles, proposition.date),
        )
        for proposition in propositions
        if proposition.etait_disponible != _est_officiellement_disponible(officielles, proposition.date)
    )
    ajouts = retraits = inchangés = 0
    for proposition in propositions:
        actuelle = _est_officiellement_disponible(officielles, proposition.date)
        if proposition.creneau == PropositionDisponibiliteDate.JOURNEE and not actuelle:
            ajouts += 1
        elif proposition.creneau == PropositionDisponibiliteDate.INDISPONIBLE and actuelle:
            retraits += 1
        else:
            inchangés += 1
    return {
        "conflits": conflits, "ajouts": ajouts, "retraits": retraits, "inchangés": inchangés,
        "demi_journees": tuple(p for p in propositions if p.creneau in {p.MATIN, p.APRES_MIDI}),
    }


@transaction.atomic
def appliquer_demande_validee(demande, *, traite_par, commentaire_direction=""):
    """Applique uniquement les jours d'une demande envoyée aux données officielles.

    Toute divergence avec l'instantané ``etait_disponible`` interrompt la
    transaction et expose les conflits au futur écran de validation.
    """
    demande = DemandeDisponibilite.objects.select_for_update().get(pk=demande.pk)
    if demande.statut != DemandeDisponibilite.ENVOYEE:
        raise ValidationError("Seule une demande envoyée peut être validée.")
    propositions = list(demande.propositions.select_for_update().order_by("date", "id"))
    if not propositions:
        raise ValidationError("La demande ne contient aucune proposition.")
    if any(p.creneau == PropositionDisponibiliteDate.NON_RENSEIGNE for p in propositions):
        raise DemandeDisponibiliteIncomplete("Une date non renseignée ne peut pas être appliquée.")
    demi_journees = [
        p for p in propositions
        if p.creneau in {PropositionDisponibiliteDate.MATIN, PropositionDisponibiliteDate.APRES_MIDI}
    ]
    if demi_journees:
        # La vérification précède toute mutation : une demande mixte reste
        # atomique et aucune demi-journée n'est élargie en journée entière.
        raise ApplicationDemandeDisponibiliteGranulariteNonSupportee(demi_journees)
    dates = [proposition.date for proposition in propositions]
    officielles = list(
        Disponibilite.objects.select_for_update().prefetch_related("types_accueil").filter(
            animateur=demande.animateur, debut__lte=max(dates), fin__gte=min(dates)
        )
    )
    conflits = [
        ConflitDisponibiliteDemande(
            date=proposition.date,
            etait_disponible=proposition.etait_disponible,
            est_disponible_actuellement=_est_officiellement_disponible(officielles, proposition.date),
        )
        for proposition in propositions
        if proposition.etait_disponible != _est_officiellement_disponible(officielles, proposition.date)
    ]
    if conflits:
        raise ApplicationDemandeDisponibiliteEnConflit(conflits)

    dates_a_retirer = {
        p.date for p in propositions if p.creneau == PropositionDisponibiliteDate.INDISPONIBLE
    }
    for plage in officielles:
        if not any(plage.debut <= jour <= plage.fin for jour in dates_a_retirer):
            continue
        types_accueil_ids = list(plage.types_accueil.values_list("id", flat=True))
        fragments = _fragments_sans_dates(plage, dates_a_retirer)
        plage.delete()
        for debut, fin in fragments:
            _creer_plage(demande.animateur, debut, fin, types_accueil_ids)

    # Les ajouts ne remplacent jamais une ligne existante ni ses métadonnées.
    jours_ajoutes = []
    officielles_apres_retraits = list(
        Disponibilite.objects.select_for_update().filter(
            animateur=demande.animateur, debut__lte=max(dates), fin__gte=min(dates)
        )
    )
    for proposition in propositions:
        if (
            proposition.creneau == PropositionDisponibiliteDate.JOURNEE
            and not _est_officiellement_disponible(officielles_apres_retraits, proposition.date)
        ):
            _creer_plage(demande.animateur, proposition.date, proposition.date, ())
            jours_ajoutes.append(proposition.date)
            officielles_apres_retraits.append(
                Disponibilite(animateur=demande.animateur, debut=proposition.date, fin=proposition.date)
            )
    _fusionner_ajouts_generaux(demande.animateur, jours_ajoutes)

    demande.transition_vers(DemandeDisponibilite.VALIDEE)
    demande.commentaire_direction = commentaire_direction
    demande.traitee_le = timezone.now()
    demande.traitee_par = traite_par
    demande.save(update_fields=["statut", "commentaire_direction", "traitee_le", "traitee_par"])
    return demande
