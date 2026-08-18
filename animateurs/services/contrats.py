"""Point d'accès central aux contrats applicables à une date."""

from dataclasses import dataclass

from django.db import models
from django.utils import timezone

from animateurs.models import Contrat, ParametresStructure, TypeContrat


TYPES_SYSTEME = (
    (Contrat.TYPE_CEE, "CEE", TypeContrat.MODE_CEE, 10),
    (Contrat.TYPE_CDD, "CDD", TypeContrat.MODE_MENSUALISE, 20),
    (Contrat.TYPE_APPRENTISSAGE, "Apprentissage", TypeContrat.MODE_APPRENTISSAGE, 30),
    (Contrat.TYPE_PERMANENT, "Permanent", TypeContrat.MODE_PAIE_HABITUELLE, 40),
)


@dataclass(frozen=True)
class SituationContractuelle:
    type_contrat: str
    contrat: object = None
    explicite: bool = False
    type_definition: object = None
    mode_remuneration: str = TypeContrat.MODE_CEE

    @property
    def libelle(self):
        return self.type_definition.nom if self.type_definition else dict(Contrat.TYPE_CHOICES).get(
            self.type_contrat, self.type_contrat
        )


def assurer_types_contrats_systeme(structure=None):
    """Crée les types stables pour une structure nouvelle, sans écraser ses libellés."""
    structure = structure or ParametresStructure.objects.get_or_create(cle="principale")[0]
    resultats = {}
    for code, nom, mode, ordre in TYPES_SYSTEME:
        item, _ = TypeContrat.objects.get_or_create(
            structure=structure,
            code=code,
            defaults={
                "nom": nom, "mode_remuneration": mode, "ordre": ordre,
                "actif": True, "systeme": True,
            },
        )
        resultats[code] = item
    return resultats


def contrat_pour_date(animateur, date):
    """Retourne l'unique contrat couvrant ``date``, ou ``None``."""
    contrats_prefetch = getattr(animateur, "_contrats_paie", None)
    if contrats_prefetch is not None:
        return next(
            (
                contrat for contrat in contrats_prefetch
                if contrat_est_applicable(contrat, date)
            ),
            None,
        )
    return (
        animateur.contrats.select_related("type_contrat_ref")
        .filter(models.Q(date_debut__isnull=True) | models.Q(date_debut__lte=date))
        .filter(models.Q(date_fin__isnull=True) | models.Q(date_fin__gte=date))
        .order_by("-date_debut", "-id")
        .first()
    )


def contrat_est_applicable(contrat, date):
    """Teste un intervalle contractuel dont chaque borne peut être ouverte."""
    return (
        (contrat.date_debut is None or contrat.date_debut <= date)
        and (contrat.date_fin is None or contrat.date_fin >= date)
    )


def contrat_actuel(animateur):
    return contrat_pour_date(animateur, timezone.localdate())


def situation_contractuelle_pour_date(animateur, date):
    """Centralise la règle Paie : sans contrat explicite, le CEE est implicite."""

    contrat = contrat_pour_date(animateur, date)
    definition = contrat.type_contrat_ref if contrat and contrat.type_contrat_ref_id else None
    code = definition.code if definition else (contrat.type_contrat if contrat else Contrat.TYPE_CEE)
    return SituationContractuelle(
        type_contrat=code,
        contrat=contrat,
        explicite=contrat is not None,
        type_definition=definition,
        mode_remuneration=definition.mode_remuneration if definition else (
            contrat.mode_paie if contrat else TypeContrat.MODE_CEE
        ),
    )


def type_contrat_pour_date(animateur, date):
    return situation_contractuelle_pour_date(animateur, date).type_contrat
