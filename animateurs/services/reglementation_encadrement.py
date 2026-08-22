"""Calcul des besoins d'encadrement réglementaires ACM.

Le moteur distingue volontairement :
- le minimum réglementaire calculé à partir des enfants présents/référents ;
- le besoin opérationnel (minimum + renforts souhaités) ;
- la composition en qualifications, contrôlée uniquement sur le minimum requis.

Le groupe technique historique ``flottant`` est réutilisé côté Planning pour
matérialiser les postes « mixtes » qui absorbent les reliquats de plusieurs
catégories d'âge d'un même centre.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from django.db.models import Q

from animateurs.models import (
    BesoinEncadrement,
    EffectifEnfantsJour,
    Evenement,
    ModalitePeriscolaire,
    PeriodeCalendrier,
    TypeAccueil,
)
from animateurs.services.accueils import accueil_centre
from animateurs.services.affectations import _ouverture_periscolaire_pour_date
from animateurs.services.categories_groupes import categorie_reglementaire_groupe
from animateurs.services.parametres import get_parametres_structure
from animateurs.services.statuts import categorie_encadrement_du_statut


@dataclass(frozen=True)
class BesoinGroupeCalcule:
    evenement: Evenement
    mode_calcul: str
    enfants: int | None
    ratio: int | None
    postes_reglementaires_directs: int
    reliquat_enfants: int
    renforts_souhaites: int
    qualifications: tuple = ()
    configure: bool = True

    @property
    def postes_operationnels_directs(self):
        return self.postes_reglementaires_directs + self.renforts_souhaites


@dataclass
class BesoinCentreCalcule:
    centre_id: int
    groupes: dict[int, BesoinGroupeCalcule] = field(default_factory=dict)
    postes_mixtes: int = 0
    contributions_mixtes: list[dict] = field(default_factory=list)
    non_configures: list[int] = field(default_factory=list)

    @property
    def effectif_reglementaire_requis(self):
        return sum(item.postes_reglementaires_directs for item in self.groupes.values()) + self.postes_mixtes

    @property
    def renforts_souhaites(self):
        return sum(item.renforts_souhaites for item in self.groupes.values())

    @property
    def effectif_operationnel_retenu(self):
        return self.effectif_reglementaire_requis + self.renforts_souhaites


def duree_accueil_heures(centre, jour, modalite: ModalitePeriscolaire | None):
    if modalite is None:
        return None
    ouvert, debut, fin = _ouverture_periscolaire_pour_date(centre, jour, modalite)
    if not ouvert or debut is None or fin is None:
        return None
    minutes = (fin.hour * 60 + fin.minute) - (debut.hour * 60 + debut.minute)
    return max(0, minutes) / 60


def ratio_reglementaire(*, type_accueil, categorie_age, centre=None, jour=None, modalite=None, structure=None):
    """Retourne le nombre d'enfants par animateur pour le contexte demandé."""

    structure = structure or get_parametres_structure()
    code = getattr(type_accueil, "code", type_accueil)
    if categorie_age not in {"moins_6", "six_plus"}:
        return None

    if code == TypeAccueil.VACANCES:
        return int(
            structure.ratio_vacances_moins_6
            if categorie_age == "moins_6"
            else structure.ratio_vacances_6_plus
        )

    if code != TypeAccueil.PERISCOLAIRE:
        return None

    duree = duree_accueil_heures(centre, jour, modalite) if centre is not None and jour is not None else None
    court = duree is not None and duree <= 5
    pedt_applicable = bool(structure.pedt_actif)
    if centre is not None:
        accueil_periscolaire = accueil_centre(
            centre,
            TypeAccueil.PERISCOLAIRE,
            jour=jour,
            modalite=modalite,
        )
        if accueil_periscolaire is not None:
            pedt_applicable = bool(accueil_periscolaire.pedt_applicable)
    if pedt_applicable:
        if court:
            return int(
                structure.ratio_periscolaire_pedt_court_moins_6
                if categorie_age == "moins_6"
                else structure.ratio_periscolaire_pedt_court_6_plus
            )
        return int(
            structure.ratio_periscolaire_pedt_long_moins_6
            if categorie_age == "moins_6"
            else structure.ratio_periscolaire_pedt_long_6_plus
        )
    if court:
        return int(
            structure.ratio_periscolaire_court_moins_6
            if categorie_age == "moins_6"
            else structure.ratio_periscolaire_court_6_plus
        )
    return int(
        structure.ratio_periscolaire_long_moins_6
        if categorie_age == "moins_6"
        else structure.ratio_periscolaire_long_6_plus
    )


def effectif_enfants_effectif(evenement, jour, *, type_accueil=None, modalite=None, reference=None):
    """Effectif réel s'il existe, sinon fréquentation de référence."""

    qs = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour)
    code = getattr(type_accueil, "code", None)
    if code == TypeAccueil.PERISCOLAIRE:
        qs = qs.filter(modalite_periscolaire=modalite)
    else:
        qs = qs.filter(modalite_periscolaire__isnull=True)
    if type_accueil is not None:
        qs = qs.filter(Q(type_accueil=type_accueil) | Q(type_accueil__isnull=True))
    ligne = qs.order_by("-type_accueil_id", "-id").first()
    if ligne is not None:
        return int(ligne.nombre), ligne
    if reference is None:
        return None, None
    return int(reference), None


def contraintes_qualification(effectif_requis, structure=None):
    """Bornes de qualification appliquées au seul effectif minimum requis."""

    structure = structure or get_parametres_structure()
    requis = max(0, int(effectif_requis or 0))
    minimum_diplomes = math.ceil(requis * int(structure.pourcentage_qualifies_minimum) / 100)
    maximum_non_diplomes = math.floor(requis * int(structure.pourcentage_non_qualifies_maximum) / 100)
    if requis in (3, 4):
        maximum_non_diplomes = max(maximum_non_diplomes, 1)
    return {
        "effectif_requis": requis,
        "minimum_diplomes": minimum_diplomes,
        "maximum_non_diplomes": maximum_non_diplomes,
    }


def categorie_legale_statut(statut, structure=None):
    """Compatibilité : réutilise directement le statut existant de l'animateur.

    ``structure`` est conservé dans la signature afin de ne casser aucun appel
    existant, mais aucun classement parallèle n'est plus stocké dans les
    paramètres de structure.
    """

    return categorie_encadrement_du_statut(statut)


def calculer_besoins_centres(
    groupes,
    jour,
    *,
    type_accueil,
    modalite=None,
    periode_calendrier: PeriodeCalendrier | None = None,
    besoins_effectifs=None,
):
    """Calcule postes directs et postes mixtes centre par centre.

    Pour les règles automatiques, on remplit d'abord les groupes complets de
    chaque catégorie. Les reliquats sont ensuite mutualisés dans le centre au
    taux le plus restrictif, comme le faisait déjà l'« animateur flottant ».
    """

    from animateurs.services.besoins_encadrement import besoin_encadrement_effectif

    structure = get_parametres_structure()
    resultats: dict[int, BesoinCentreCalcule] = {}
    reliquats_par_centre: dict[int, list[dict]] = {}

    for evenement in groupes:
        resultat = resultats.setdefault(evenement.centre_id, BesoinCentreCalcule(evenement.centre_id))
        besoin = (
            besoins_effectifs.get((evenement.id, jour))
            if besoins_effectifs is not None
            else besoin_encadrement_effectif(
                evenement,
                type_accueil=type_accueil,
                modalite=modalite,
                periode_calendrier=periode_calendrier,
            )
        )
        if besoin is None or not besoin.configure:
            resultat.non_configures.append(evenement.id)
            continue

        regle = besoin.regle
        mode = regle.mode_calcul if regle is not None else BesoinEncadrement.MODE_MANUEL
        renforts = int(getattr(regle, "renforts_souhaites", 0) or 0)
        if mode != BesoinEncadrement.MODE_REGLEMENTAIRE:
            item = BesoinGroupeCalcule(
                evenement=evenement,
                mode_calcul=mode,
                enfants=None,
                ratio=None,
                postes_reglementaires_directs=max(0, int(besoin.effectif_cible)),
                reliquat_enfants=0,
                renforts_souhaites=renforts,
                qualifications=besoin.qualifications,
            )
            resultat.groupes[evenement.id] = item
            continue

        reference = getattr(regle, "effectif_enfants_reference", None)
        enfants, ligne_effectif = effectif_enfants_effectif(
            evenement,
            jour,
            type_accueil=type_accueil,
            modalite=modalite,
            reference=reference,
        )
        categorie = categorie_reglementaire_groupe(evenement)
        ratio = ratio_reglementaire(
            type_accueil=type_accueil,
            categorie_age=categorie,
            centre=evenement.centre,
            jour=jour,
            modalite=modalite,
            structure=structure,
        )
        if ligne_effectif is not None and ligne_effectif.ratio_encadrement_exceptionnel:
            ratio = int(ligne_effectif.ratio_encadrement_exceptionnel)
        if enfants is None or ratio is None or ratio < 1:
            resultat.non_configures.append(evenement.id)
            continue

        directs, reliquat = divmod(max(0, int(enfants)), ratio)
        item = BesoinGroupeCalcule(
            evenement=evenement,
            mode_calcul=mode,
            enfants=max(0, int(enfants)),
            ratio=ratio,
            postes_reglementaires_directs=directs,
            reliquat_enfants=reliquat,
            renforts_souhaites=renforts,
            qualifications=besoin.qualifications,
        )
        resultat.groupes[evenement.id] = item
        if reliquat:
            reliquats_par_centre.setdefault(evenement.centre_id, []).append(
                {"evenement": evenement, "reste": reliquat, "ratio": ratio}
            )

    for centre_id, reliquats in reliquats_par_centre.items():
        resultat = resultats[centre_id]
        while any(item["reste"] > 0 for item in reliquats):
            actifs = [item for item in reliquats if item["reste"] > 0]
            if len(actifs) == 1:
                seul = actifs[0]
                ancien = resultat.groupes[seul["evenement"].id]
                resultat.groupes[seul["evenement"].id] = BesoinGroupeCalcule(
                    evenement=ancien.evenement,
                    mode_calcul=ancien.mode_calcul,
                    enfants=ancien.enfants,
                    ratio=ancien.ratio,
                    postes_reglementaires_directs=ancien.postes_reglementaires_directs + 1,
                    reliquat_enfants=0,
                    renforts_souhaites=ancien.renforts_souhaites,
                    qualifications=ancien.qualifications,
                )
                seul["reste"] = 0
                break

            capacite = min(item["ratio"] for item in actifs)
            contributeurs = []
            # Les groupes au taux le plus restrictif sont consommés d'abord.
            for item in sorted(actifs, key=lambda valeur: (valeur["ratio"], valeur["evenement"].id)):
                if capacite <= 0:
                    break
                pris = min(item["reste"], capacite)
                if pris:
                    contributeurs.append({"evenement_id": item["evenement"].id, "enfants": pris})
                    item["reste"] -= pris
                    capacite -= pris
            if len(contributeurs) >= 2:
                resultat.postes_mixtes += 1
                resultat.contributions_mixtes.append({"groupes": contributeurs})
            elif contributeurs:
                # Cas de sécurité : si un seul groupe consomme finalement le
                # poste, il reste affecté à ce groupe plutôt qu'au groupe mixte.
                evenement_id = contributeurs[0]["evenement_id"]
                ancien = resultat.groupes[evenement_id]
                resultat.groupes[evenement_id] = BesoinGroupeCalcule(
                    evenement=ancien.evenement,
                    mode_calcul=ancien.mode_calcul,
                    enfants=ancien.enfants,
                    ratio=ancien.ratio,
                    postes_reglementaires_directs=ancien.postes_reglementaires_directs + 1,
                    reliquat_enfants=0,
                    renforts_souhaites=ancien.renforts_souhaites,
                    qualifications=ancien.qualifications,
                )

    return resultats
