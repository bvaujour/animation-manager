"""Inférences prudentes et sans écriture pour le rattachement progressif.

Une fonction retourne ``None`` dès que plusieurs types sont possibles ou que
les relations disponibles se contredisent. Ce module ne modifie jamais les
données : une validation humaine reste donc possible avant toute migration.
"""

from django.db.models import Q

from animateurs.models import (
    ActiviteTravailComplementaire,
    Affectation,
    BesoinQualification,
    Document,
    EffectifEnfantsJour,
    Evenement,
    ModeleEmail,
    PeriodeScolaire,
    PrimeJournalierePeriode,
    PublicationPlanning,
    Sortie,
    Centre,
)


def _type_unique(types):
    par_id = {type_accueil.pk: type_accueil for type_accueil in types if type_accueil is not None}
    return next(iter(par_id.values())) if len(par_id) == 1 else None


def _type_des_periodes(periodes):
    periodes = list(periodes)
    if not periodes or any(periode.type_accueil_id is None for periode in periodes):
        return None
    return _type_unique(periode.type_accueil for periode in periodes)


def inferer_type_evenement(evenement, jour=None):
    """Combine le type explicite du groupe d'accueil et celui de ses semaines."""
    types_evenement = list(evenement.types_accueil.all())
    type_evenement = _type_unique(types_evenement)
    if len({item.pk for item in types_evenement}) > 1:
        return None

    periodes = evenement.periodes_scolaires.select_related("type_accueil")
    if jour is not None:
        periodes = periodes.filter(debut__lte=jour, fin__gte=jour)
    type_periode = _type_des_periodes(periodes)

    if type_evenement and type_periode and type_evenement.pk != type_periode.pk:
        return None
    return type_evenement or type_periode


def inferer_type_effectif(effectif):
    return effectif.type_accueil or inferer_type_evenement(effectif.evenement, effectif.date)


def inferer_type_besoin(besoin):
    return besoin.type_accueil or inferer_type_evenement(besoin.evenement)


def inferer_type_affectation(affectation):
    jour = affectation.debut.date() if affectation.debut else None
    return affectation.type_accueil or inferer_type_evenement(affectation.evenement, jour)


def inferer_type_sortie(sortie):
    if sortie.type_accueil_id:
        return sortie.type_accueil
    types = []
    participations = sortie.participations.select_related("evenement").prefetch_related(
        "evenement__types_accueil", "evenement__periodes_scolaires__type_accueil"
    )
    for participation in participations:
        type_accueil = inferer_type_evenement(participation.evenement, sortie.date)
        if type_accueil is None:
            return None
        types.append(type_accueil)
    return _type_unique(types)


def inferer_type_document(document):
    types_explicites = list(document.types_accueil.all())
    if types_explicites:
        return _type_unique(types_explicites)
    return _type_des_periodes(document.periodes.select_related("type_accueil"))


def inferer_type_activite_travail(activite):
    if activite.type_accueil_id:
        return activite.type_accueil
    return _type_des_periodes(activite.periodes.select_related("type_accueil"))


def inferer_type_prime(prime):
    return prime.periode.type_accueil


def inferer_type_publication(publication):
    if publication.type_accueil_id:
        return publication.type_accueil
    periodes = PeriodeScolaire.objects.select_related("type_accueil").filter(
        debut__lte=publication.semaine_debut,
        fin__gte=publication.semaine_debut,
    )
    return _type_des_periodes(periodes)


def inferer_type_modele_email(modele):
    return _type_unique(modele.types_accueil.all())


_INFERENCES = {
    Evenement: inferer_type_evenement,
    EffectifEnfantsJour: inferer_type_effectif,
    BesoinQualification: inferer_type_besoin,
    Affectation: inferer_type_affectation,
    Sortie: inferer_type_sortie,
    Document: inferer_type_document,
    ActiviteTravailComplementaire: inferer_type_activite_travail,
    PrimeJournalierePeriode: inferer_type_prime,
    PublicationPlanning: inferer_type_publication,
    ModeleEmail: inferer_type_modele_email,
}


def inferer_type_objet(objet):
    """Point d'entrée commun pour les futures vues filtrées."""
    fonction = _INFERENCES.get(type(objet))
    return fonction(objet) if fonction else None


def filtrer_objets_par_type_herite(objets, code_type, *, inclure_generaux=True):
    """Filtre en mémoire sans recopier le type hérité sur les objets liés.

    Cette première version privilégie la sûreté : les objets indéterminés
    restent visibles quand le fonctionnement historique est demandé.
    """
    if not code_type:
        return list(objets)
    resultat = []
    for objet in objets:
        type_accueil = inferer_type_objet(objet)
        if type_accueil is None:
            if inclure_generaux:
                resultat.append(objet)
        elif type_accueil.code == code_type:
            resultat.append(objet)
    return resultat


def lieux_sejours_a_examiner():
    """Inventaire en lecture seule des lieux pouvant nécessiter une décision humaine."""
    return Centre.objects.filter(
        Q(nom__icontains="séjour") | Q(nom__icontains="sejour") | Q(nom__icontains="camp")
    ).order_by("nom")
