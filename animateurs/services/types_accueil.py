"""Filtres réutilisables pour faire évoluer les écrans sans les dupliquer."""

from django.db.models import Q
from django.utils.text import slugify


def regrouper_periodes_vacances(periodes):
    """Regroupe les semaines existantes en périodes complètes de vacances."""
    groupes = {}
    for periode in periodes:
        libelle = periode.categorie_vacances
        annee = periode.debut.year
        cle = f"{slugify(libelle)}-{annee}"
        groupe = groupes.setdefault(cle, {
            "id": cle,
            "libelle_selection": f"{libelle} {annee}",
            "debut": periode.debut,
            "fin": periode.fin,
            "semaine_ids": [],
        })
        groupe["debut"] = min(groupe["debut"], periode.debut)
        groupe["fin"] = max(groupe["fin"], periode.fin)
        groupe["semaine_ids"].append(periode.pk)
    return sorted(groupes.values(), key=lambda groupe: groupe["debut"], reverse=True)

def regrouper_periodes_scolaires(periodes):
    """Regroupe les semaines périscolaires par référence scolaire commune.

    Le sélecteur global manipule ainsi « Rentrée → Toussaint » plutôt qu'une
    modalité ou une semaine isolée. Les écrans métier continuent à recevoir
    les identifiants des semaines qui composent la référence.
    """

    groupes = {}
    sans_reference = []
    for periode in periodes:
        reference = getattr(periode, "periode_calendrier", None)
        if reference is None:
            sans_reference.append({
                "id": f"semaine-{periode.pk}",
                "libelle_selection": periode.libelle_avec_annee,
                "debut": periode.debut,
                "fin": periode.fin,
                "semaine_ids": [periode.pk],
                "periode_calendrier_id": None,
            })
            continue
        cle = f"scolaire-{reference.pk}"
        groupe = groupes.setdefault(cle, {
            "id": cle,
            "libelle_selection": f"{reference.nom} · {reference.annee_scolaire}",
            "debut": reference.debut,
            "fin": reference.fin,
            "semaine_ids": [],
            "periode_calendrier_id": reference.pk,
        })
        groupe["semaine_ids"].append(periode.pk)
    resultat = list(groupes.values()) + sans_reference
    return sorted(resultat, key=lambda groupe: groupe["debut"], reverse=True)


def filtrer_relation_type(queryset, code_type, *, champ="type_accueil", inclure_generaux=True):
    """Filtre une FK de type d'accueil ; une sélection vide est la vue générale."""
    if not code_type:
        return queryset
    condition = Q(**{f"{champ}__code": code_type})
    if inclure_generaux:
        condition |= Q(**{f"{champ}__isnull": True})
    return queryset.filter(condition)


def filtrer_relations_types(queryset, code_type, *, champ="types_accueil", inclure_generaux=True):
    """Équivalent pour une relation plusieurs-à-plusieurs."""
    if not code_type:
        return queryset
    condition = Q(**{f"{champ}__code": code_type})
    if inclure_generaux:
        condition |= Q(**{f"{champ}__isnull": True})
    return queryset.filter(condition).distinct()


def filtrer_semaines_contexte_travail(queryset, request):
    """Restreint la bibliothèque de semaines au contexte explicitement choisi.

    Sans contexte, le queryset est rendu intact : c'est le repli historique.
    La période complète de vacances reste une enveloppe de navigation ; les
    fonctionnalités continuent à recevoir les mêmes semaines qu'auparavant.
    """
    code_type = request.session.get("type_accueil", "")
    if not code_type:
        return queryset
    queryset = queryset.filter(type_accueil__code=code_type)
    semaine_ids = request.session.get("semaines_contexte_travail") or []
    if semaine_ids:
        queryset = queryset.filter(pk__in=semaine_ids)
    return queryset
