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
