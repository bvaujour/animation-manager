"""Règles transversales des responsabilités opérationnelles du Planning."""

from __future__ import annotations

from django.db.models import Q

from animateurs.models import Affectation, FonctionOperationnelle, ResponsabiliteOperationnelle
from animateurs.services.parametres import get_parametres_structure
from animateurs.services.statuts import ids_qualifications_pour_date


CHAMPS_REGLES = {
    FonctionOperationnelle.DIRECTEUR: "directeur_general",
    FonctionOperationnelle.DIRECTEUR_ADJOINT: "directeur_adjoint",
    FonctionOperationnelle.REFERENT_SITE: "referent_site",
}


def regle_eligibilite_fonction(fonction, *, structure=None):
    """Retourne la règle paramétrée associée au référentiel de fonctions."""
    prefixe = CHAMPS_REGLES.get(fonction.code)
    if not prefixe:
        return {"majorite_requise": False, "qualification_requise": None}
    structure = structure or get_parametres_structure()
    return {
        "majorite_requise": getattr(structure, f"{prefixe}_majorite_requise"),
        "qualification_requise": getattr(structure, f"{prefixe}_qualification_requise"),
    }


def motif_ineligibilite_responsabilite(animateur, fonction, date_reference, *, structure=None):
    """Validation unique utilisée par les deux formulaires et par l'API."""
    regle = regle_eligibilite_fonction(fonction, structure=structure)
    manques = []
    if regle["majorite_requise"]:
        naissance = animateur.date_naissance
        majeur = naissance is not None and (
            date_reference.year - naissance.year
            - ((date_reference.month, date_reference.day) < (naissance.month, naissance.day))
        ) >= 18
        if not majeur:
            manques.append("majorité")
    qualification = regle["qualification_requise"]
    if qualification and qualification.id not in ids_qualifications_pour_date(animateur, date_reference):
        manques.append(qualification.nom)
    if not manques:
        return ""
    if len(manques) == 2:
        return f"{manques[1]} et majorité requis"
    return f"{manques[0]} requise" if manques[0] == "majorité" else f"{manques[0]} requis"


def responsabilites_standalone_sur_plage(*, animateur=None, debut, fin, bloquantes=None):
    """Responsabilités autonomes qui chevauchent l'intervalle demandé."""

    queryset = ResponsabiliteOperationnelle.objects.filter(
        fournit_temps_travail=True, debut__lt=fin, fin__gt=debut
    )
    if animateur is not None:
        queryset = queryset.filter(animateur=animateur)
    if bloquantes is not None:
        queryset = queryset.filter(bloque_affectation_animation=bloquantes)
    return queryset


def conflit_responsabilite_bloquante(*, animateur, debut, fin):
    return responsabilites_standalone_sur_plage(
        animateur=animateur, debut=debut, fin=fin, bloquantes=True
    ).select_related("fonction").order_by("debut", "id").first()


def responsabilite_correspond_au_contexte(responsabilite, *, centre_id, accueil_centre_ids=()):
    """Résout le périmètre sans inventer de rattachement multi-site."""

    if responsabilite.perimetre == ResponsabiliteOperationnelle.PERIMETRE_SITE:
        return responsabilite.centre_id == centre_id
    if responsabilite.perimetre == ResponsabiliteOperationnelle.PERIMETRE_ACCUEIL:
        return responsabilite.accueil_centre_id in set(accueil_centre_ids)
    if responsabilite.perimetre == ResponsabiliteOperationnelle.PERIMETRE_GROUPE:
        return responsabilite.evenement_id is not None and responsabilite.evenement.centre_id == centre_id
    return False


def filtre_contexte_responsabilites(*, centre_id=None, accueil_centre_ids=(), evenement_ids=()):
    filtre = Q()
    if centre_id:
        filtre |= Q(perimetre=ResponsabiliteOperationnelle.PERIMETRE_SITE, centre_id=centre_id)
    if accueil_centre_ids:
        filtre |= Q(
            perimetre=ResponsabiliteOperationnelle.PERIMETRE_ACCUEIL,
            accueil_centre_id__in=accueil_centre_ids,
        )
    if evenement_ids:
        filtre |= Q(
            perimetre=ResponsabiliteOperationnelle.PERIMETRE_GROUPE,
            evenement_id__in=evenement_ids,
        )
    return filtre


def membres_encadrement_uniques(personnes_affectees, responsabilites):
    """Une personne superposée à une affectation ne devient jamais deux adultes."""

    personnes = list(personnes_affectees)
    personnes.extend(
        item.animateur for item in responsabilites if item.compte_dans_encadrement
    )
    return list({personne.id: personne for personne in personnes}.values())


def membres_quotas_uniques(personnes_affectees, responsabilites):
    """Les quotas ne retiennent que les responsabilités explicitement autorisées."""

    personnes = list(personnes_affectees)
    personnes.extend(
        item.animateur
        for item in responsabilites
        if item.compte_dans_encadrement and item.compte_dans_quotas_qualification
    )
    return list({personne.id: personne for personne in personnes}.values())


def responsabilite_correspond_affectation(responsabilite, affectation):
    """Le PK d'origine accélère le cas courant, le contexte survit aux recréations du solveur."""

    if responsabilite.fournit_temps_travail:
        return False
    if responsabilite.affectation_source_id == affectation.id:
        return (
            responsabilite.animateur_id == affectation.animateur_id
            and responsabilite.evenement_id == affectation.evenement_id
            and responsabilite.debut < affectation.fin
            and responsabilite.fin > affectation.debut
        )
    return (
        responsabilite.animateur_id == affectation.animateur_id
        and responsabilite.evenement_id == affectation.evenement_id
        and responsabilite.debut < affectation.fin
        and responsabilite.fin > affectation.debut
    )


def affectation_active_responsabilite(responsabilite):
    """Retourne la présence actuelle ou ``None`` si la responsabilité liée est dormante."""

    if responsabilite.fournit_temps_travail:
        return None
    candidats = Affectation.objects.filter(
        animateur_id=responsabilite.animateur_id,
        evenement_id=responsabilite.evenement_id,
        debut__lt=responsabilite.fin,
        fin__gt=responsabilite.debut,
    )
    if responsabilite.affectation_source_id:
        origine = candidats.filter(pk=responsabilite.affectation_source_id).first()
        if origine is not None:
            return origine
    return candidats.order_by("debut", "id").first()
