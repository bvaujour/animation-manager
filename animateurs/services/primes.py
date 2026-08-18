"""Validation centralisée des primes attribuées depuis la préparation de Paie."""

import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from animateurs.models import AttributionPrime, TypePrime
from animateurs.services.contrats import situation_contractuelle_pour_date
from animateurs.services.parametres import prime_est_eligible
from animateurs.services.statuts import statut_pour_date


def _jours(debut, fin):
    jour = debut
    while jour <= fin:
        yield jour
        jour += datetime.timedelta(days=1)


def nombre_jours_attribution_prime(attribution):
    """Retourne le multiplicateur journalier réellement figé dans l'attribution."""
    if attribution.mode_calcul != TypePrime.MODE_JOUR:
        return None
    if attribution.montant_unitaire:
        multiplicateur = attribution.montant_total / attribution.montant_unitaire
        if multiplicateur == multiplicateur.to_integral_value():
            return int(multiplicateur)
    # Un montant unitaire nul ne permet pas de retrouver le multiplicateur par
    # division. Les segments journaliers enregistrés sont alors contigus.
    return (attribution.date_fin - attribution.date_debut).days + 1


def _semaines_couvertes(debut, fin):
    return {jour - datetime.timedelta(days=jour.weekday()) for jour in _jours(debut, fin)}


def _mois_couverts(debut, fin):
    mois = set()
    courant = debut.replace(day=1)
    borne = fin.replace(day=1)
    while courant <= borne:
        mois.add((courant.year, courant.month))
        courant = (courant.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return mois


def attributions_primes_se_chevauchent(mode, debut_a, fin_a, debut_b, fin_b):
    """Compare deux occurrences selon la périodicité métier du TypePrime."""
    if mode == TypePrime.MODE_SEMAINE:
        return bool(_semaines_couvertes(debut_a, fin_a) & _semaines_couvertes(debut_b, fin_b))
    if mode == TypePrime.MODE_MOIS:
        return bool(_mois_couverts(debut_a, fin_a) & _mois_couverts(debut_b, fin_b))
    # Journalier et forfait : seules les dates réellement couvertes se croisent.
    return debut_a <= fin_b and debut_b <= fin_a


def creer_attribution_prime(*, animateur, type_prime, date_debut, date_fin, montant=None,
                            centre=None, commentaire="", utilisateur=None,
                            exclure_attribution_id=None):
    if date_fin < date_debut:
        raise ValidationError("La date de fin ne peut pas précéder la date de début.")
    if not type_prime.active:
        raise ValidationError("Cette prime est inactive.")
    type_prime._types_contrats_eligibles_codes = set(
        type_prime.types_contrats_eligibles.values_list("code", flat=True)
    )
    if not type_prime.tous_statuts:
        type_prime._statuts_eligibles_ids = set(
            type_prime.statuts_eligibles.values_list("id", flat=True)
        )

    dates_controle = list(_jours(date_debut, date_fin))
    for jour in dates_controle:
        situation = situation_contractuelle_pour_date(animateur, jour)
        if not prime_est_eligible(
            type_prime,
            animateur=animateur,
            contrat=situation.type_contrat,
            statut=statut_pour_date(animateur, jour),
            date=jour,
        ):
            raise ValidationError(
                f"{type_prime.nom} n'est pas éligible pour {animateur} le {jour:%d/%m/%Y}."
            )

    if type_prime.type_montant == TypePrime.MONTANT_FIXE:
        montant_unitaire = type_prime.montant_fixe
    else:
        try:
            montant_unitaire = Decimal(str(montant))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError("Le montant attribué est obligatoire.") from exc
        if montant_unitaire < 0 or montant_unitaire > type_prime.montant_maximum:
            raise ValidationError(
                f"Le montant doit être compris entre 0 et {type_prime.montant_maximum} €."
            )

    multiplicateur = len(dates_controle) if type_prime.mode_calcul == TypePrime.MODE_JOUR else 1
    montant_total = (montant_unitaire * multiplicateur).quantize(Decimal("0.01"))
    commentaire = commentaire.strip()
    # Le verrou rend l'opération idempotente même si le bouton est activé deux fois
    # avant la fin de la première requête.
    with transaction.atomic():
        type(animateur).objects.select_for_update().get(pk=animateur.pk)
        identiques = AttributionPrime.objects.filter(
            animateur=animateur,
            type_prime=type_prime,
            centre=centre,
            date_debut=date_debut,
            date_fin=date_fin,
            mode_calcul=type_prime.mode_calcul,
            montant_unitaire=montant_unitaire,
            montant_total=montant_total,
            commentaire=commentaire,
        )
        if exclure_attribution_id is not None:
            identiques = identiques.exclude(pk=exclure_attribution_id)
        existante = identiques.order_by("id").first()
        if existante is not None:
            return existante
        autres = AttributionPrime.objects.filter(
            animateur=animateur,
            type_prime=type_prime,
        )
        if exclure_attribution_id is not None:
            autres = autres.exclude(pk=exclure_attribution_id)
        if any(attributions_primes_se_chevauchent(
            type_prime.mode_calcul,
            date_debut,
            date_fin,
            item.date_debut,
            item.date_fin,
        ) for item in autres.only("date_debut", "date_fin")):
            raise ValidationError(
                "Cette prime est déjà attribuée sur tout ou partie des dates sélectionnées. "
                "Utilisez Modifier pour changer son montant."
            )
        return AttributionPrime.objects.create(
            animateur=animateur,
            type_prime=type_prime,
            centre=centre,
            date_debut=date_debut,
            date_fin=date_fin,
            mode_calcul=type_prime.mode_calcul,
            montant_unitaire=montant_unitaire,
            montant_total=montant_total,
            commentaire=commentaire,
            attribue_par=utilisateur,
        )
