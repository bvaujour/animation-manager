"""Références contractuelles datées, sans calcul de bulletin de salaire."""

import calendar
import datetime
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from animateurs.models import (
    BaremeApprentissage,
    Contrat,
    ReferenceSMIC,
)
from animateurs.services.parametres import get_parametres_structure


HEURES_MENSUELLES_35H = Decimal("151.67")


@dataclass(frozen=True)
class ReferenceRemuneration:
    montant_retenu: Decimal | None
    minimum_calcule: Decimal | None = None
    source: str = ""
    fiable: bool = True
    alertes: tuple = field(default_factory=tuple)
    smic: object = None
    bareme: object = None
    age: int | None = None
    annee_execution: int | None = None
    prochaine_evolution: dict | None = None


def smic_pour_date(date, structure=None):
    structure = structure or get_parametres_structure()
    prefetched = getattr(structure, "_references_smic_paie", None)
    if prefetched is not None:
        return next((item for item in prefetched if item.date_effet <= date), None)
    return structure.references_smic.filter(date_effet__lte=date).order_by("-date_effet", "-id").first()


def montant_smic_mensuel_35h(reference):
    if reference is None:
        return None
    if reference.montant_mensuel_35h is not None:
        return reference.montant_mensuel_35h
    return (reference.montant_horaire * HEURES_MENSUELLES_35H).quantize(Decimal("0.01"), ROUND_HALF_UP)


def heures_mensuelles_contrat(contrat):
    if contrat.heures_mensuelles_reference is not None:
        return contrat.heures_mensuelles_reference
    if contrat.mode_temps_travail == Contrat.TEMPS_HEBDOMADAIRE and contrat.heures_hebdomadaires is not None:
        return (contrat.heures_hebdomadaires * Decimal("52") / Decimal("12")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
    return None


def remuneration_mensualisee_pour_date(contrat, date, structure=None):
    """Retourne une référence ; ne prorate jamais une période partielle."""
    structure = structure or get_parametres_structure()
    salaire = contrat.salaire_mensuel_reference
    if contrat.mode_remuneration == Contrat.REMUNERATION_FIXE:
        return ReferenceRemuneration(salaire, source="salaire_contractuel", fiable=salaire is not None)

    heures = heures_mensuelles_contrat(contrat)
    if heures is None:
        return ReferenceRemuneration(
            salaire,
            source="salaire_contractuel" if salaire is not None else "",
            fiable=False,
            alertes=("Volume horaire non renseigné — contrôle SMIC indisponible",),
        )
    smic = smic_pour_date(date, structure)
    if smic is None:
        return ReferenceRemuneration(
            salaire,
            source="salaire_contractuel" if salaire is not None else "",
            fiable=False,
            alertes=(f"Référence SMIC manquante au {date:%d/%m/%Y}",),
        )
    minimum = (smic.montant_horaire * heures).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if contrat.mode_remuneration == Contrat.REMUNERATION_MINIMUM_SMIC:
        return ReferenceRemuneration(minimum, minimum, "minimum_smic", smic=smic)
    alertes = ()
    if salaire is not None and salaire < minimum:
        alertes = ("Salaire de référence inférieur au minimum calculé — à vérifier",)
    return ReferenceRemuneration(
        salaire, minimum, "salaire_contractuel", fiable=salaire is not None,
        alertes=alertes, smic=smic,
    )


def date_effet_changement_age(date_anniversaire):
    """Premier jour du mois suivant l'anniversaire qui change une tranche."""
    if date_anniversaire.month == 12:
        return datetime.date(date_anniversaire.year + 1, 1, 1)
    return datetime.date(date_anniversaire.year, date_anniversaire.month + 1, 1)


def age_applicable_apprentissage(date_naissance, date):
    age = date.year - date_naissance.year
    anniversaire = datetime.date(
        date.year,
        date_naissance.month,
        min(date_naissance.day, calendar.monthrange(date.year, date_naissance.month)[1]),
    )
    if date < date_effet_changement_age(anniversaire):
        age -= 1
    return age


def annee_execution_pour_date(contrat, date):
    if contrat.annee_execution_initiale not in (1, 2, 3):
        return None
    origine = contrat.date_effet_annee_execution or contrat.date_debut
    annees = date.year - origine.year - ((date.month, date.day) < (origine.month, origine.day))
    return min(3, contrat.annee_execution_initiale + max(0, annees))


def _bareme_apprentissage_pour_date(structure, date, annee_execution, age):
    prefetched = getattr(structure, "_baremes_apprentissage_paie", None)
    source = prefetched if prefetched is not None else structure.baremes_apprentissage.filter(
        date_effet__lte=date, actif=True
    )
    return next((item for item in source if (
        item.date_effet <= date
        and item.actif
        and item.annee_execution == annee_execution
        and item.age_minimum <= age
        and (item.age_maximum is None or item.age_maximum >= age)
    )), None)


def _salaire_contractuel_pour_date(contrat, date):
    historique = getattr(contrat, "_historique_remunerations_paie", None)
    if historique is None and contrat.pk:
        entree = contrat.historique_remunerations.filter(date_effet__lte=date).order_by(
            "-date_effet", "-id"
        ).first()
    elif historique is None:
        entree = None
    else:
        entree = next((item for item in historique if item.date_effet <= date), None)
    return entree.montant_mensuel if entree else contrat.salaire_mensuel_reference


def remuneration_apprentissage_pour_date(contrat, date, structure=None):
    structure = structure or get_parametres_structure()
    salaire = _salaire_contractuel_pour_date(contrat, date)
    if contrat.mode_remuneration == Contrat.REMUNERATION_FIXE:
        return ReferenceRemuneration(salaire, source="salaire_contractuel", fiable=salaire is not None)
    if not contrat.animateur.date_naissance:
        return ReferenceRemuneration(
            salaire, source="salaire_contractuel" if salaire is not None else "", fiable=False,
            alertes=("Date de naissance manquante — rémunération apprentissage impossible",),
        )
    annee = annee_execution_pour_date(contrat, date)
    if annee is None:
        return ReferenceRemuneration(
            salaire, source="salaire_contractuel" if salaire is not None else "", fiable=False,
            alertes=("Année d'exécution de l'apprentissage manquante",),
        )
    age = age_applicable_apprentissage(contrat.animateur.date_naissance, date)
    bareme = _bareme_apprentissage_pour_date(structure, date, annee, age)
    if bareme is None:
        return ReferenceRemuneration(
            salaire, source="salaire_contractuel" if salaire is not None else "", fiable=False,
            alertes=("Barème apprentissage manquant",), age=age, annee_execution=annee,
        )
    smic = smic_pour_date(date, structure)
    if smic is None:
        return ReferenceRemuneration(
            salaire, source="salaire_contractuel" if salaire is not None else "", fiable=False,
            alertes=(f"Référence SMIC manquante au {date:%d/%m/%Y}",),
            bareme=bareme, age=age, annee_execution=annee,
        )
    minimum = (
        montant_smic_mensuel_35h(smic) * bareme.pourcentage_smic / Decimal("100")
    ).quantize(Decimal("0.01"), ROUND_HALF_UP)
    retenu = minimum if contrat.mode_remuneration == Contrat.REMUNERATION_GRILLE_AUTO else salaire
    alertes = ()
    if contrat.mode_remuneration == Contrat.REMUNERATION_GRILLE_CONTROLE and salaire is not None and salaire < minimum:
        alertes = ("Salaire contractuel inférieur au minimum calculé — à vérifier",)
    return ReferenceRemuneration(
        retenu, minimum, "grille_apprentissage" if retenu == minimum else "salaire_contractuel",
        fiable=retenu is not None, alertes=alertes, smic=smic, bareme=bareme,
        age=age, annee_execution=annee,
    )
