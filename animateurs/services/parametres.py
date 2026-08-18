"""Accès unique aux paramètres de la structure courante."""

from animateurs.models import ParametresStructure
from animateurs.services.contrats import assurer_types_contrats_systeme, situation_contractuelle_pour_date
from animateurs.services.statuts import statut_actuel, statut_pour_date


CLE_STRUCTURE_COURANTE = "principale"


def get_parametres_structure():
    """Retourne une configuration persistée avec ses valeurs par défaut."""
    parametres, _ = ParametresStructure.objects.get_or_create(cle=CLE_STRUCTURE_COURANTE)
    assurer_types_contrats_systeme(parametres)
    return parametres


def taux_cee_pour_date(statut, date, structure=None):
    """Retourne le dernier taux du statut entré en vigueur à ``date``."""
    structure = structure or get_parametres_structure()
    bareme = (
        structure.baremes_cee.filter(statut=statut, date_effet__lte=date)
        .order_by("-date_effet", "-id")
        .first()
    )
    return bareme.montant_journalier if bareme else None


def prime_est_eligible(type_prime, animateur=None, contrat=None, statut=None, date=None):
    """Évalue l'éligibilité sans coupler le référentiel au moteur de Paie."""
    if not type_prime.active:
        return False
    if contrat is None and animateur is not None and date is not None:
        contrat = situation_contractuelle_pour_date(animateur, date).type_contrat
    type_contrat = getattr(contrat, "type_contrat", contrat)
    codes_prefetch = getattr(type_prime, "_types_contrats_eligibles_codes", None)
    if codes_prefetch is None:
        codes_relation = set(type_prime.types_contrats_eligibles.values_list("code", flat=True))
    else:
        codes_relation = set(codes_prefetch)
    codes_eligibles = codes_relation or set(type_prime.contrats_eligibles or [])
    if type_contrat not in codes_eligibles:
        return False
    if type_prime.tous_statuts:
        return True
    if statut is None and animateur is not None:
        statut = statut_pour_date(animateur, date) if date is not None else statut_actuel(animateur)
    statut_id = getattr(statut, "pk", statut)
    ids_prefetch = getattr(type_prime, "_statuts_eligibles_ids", None)
    if ids_prefetch is not None:
        return bool(statut_id and statut_id in ids_prefetch)
    return bool(statut_id and type_prime.statuts_eligibles.filter(pk=statut_id).exists())
