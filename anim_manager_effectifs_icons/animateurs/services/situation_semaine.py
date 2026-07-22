"""Calcul fiable de la situation d'un animateur sur une semaine de Planning.

La barre latérale ne doit pas dépendre des calendriers rendus dans le navigateur :
un centre peut être masqué, les événements arrivent de manière asynchrone et les
dates des ``DateTimeField`` sont stockées en UTC. Ce module calcule donc une
source de vérité côté serveur à partir des jours réellement ouverts, des
disponibilités et des affectations de la plage demandée.
"""

import datetime

from django.utils import timezone

from animateurs.models import Evenement, jours_feries_france


def _date_locale(valeur):
    """Retourne la date métier locale d'un datetime Django."""
    if timezone.is_aware(valeur):
        valeur = timezone.localtime(valeur)
    return valeur.date()


def _jours_intervalle(debut, fin):
    """Dates de l'intervalle semi-ouvert [debut, fin)."""
    jour = debut
    while jour < fin:
        yield jour
        jour += datetime.timedelta(days=1)


def jours_ouverts_planning(debut, fin):
    """Union des jours où au moins un groupe est réellement ouvert.

    Les périodes et dates exclues sont lues dans une requête unique. Une
    ``prefetch_related`` classique en demanderait trois et alourdirait l'API
    Planning à chaque affectation.
    """
    jours = list(_jours_intervalle(debut, fin))
    if not jours:
        return []

    lignes = Evenement.objects.values(
        "id",
        "permanent",
        "jours_ouverts",
        "ferme_jours_feries",
        "periodes_scolaires__debut",
        "periodes_scolaires__fin",
        "dates_exclues__date",
    )
    groupes = {}
    for ligne in lignes:
        groupe = groupes.setdefault(
            ligne["id"],
            {
                "permanent": ligne["permanent"],
                "jours_ouverts": {int(numero) for numero in (ligne["jours_ouverts"] or [])},
                "ferme_jours_feries": ligne["ferme_jours_feries"],
                "periodes": set(),
                "dates_exclues": set(),
            },
        )
        periode_debut = ligne["periodes_scolaires__debut"]
        periode_fin = ligne["periodes_scolaires__fin"]
        if periode_debut and periode_fin:
            groupe["periodes"].add((periode_debut, periode_fin))
        if ligne["dates_exclues__date"]:
            groupe["dates_exclues"].add(ligne["dates_exclues__date"])

    feries_par_annee = {annee: jours_feries_france(annee) for annee in {jour.year for jour in jours}}
    ouverts = set()
    for groupe in groupes.values():
        extension = 2 if 6 in groupe["jours_ouverts"] else (1 if 5 in groupe["jours_ouverts"] else 0)
        for jour in jours:
            if jour.weekday() not in groupe["jours_ouverts"]:
                continue
            if jour in groupe["dates_exclues"]:
                continue
            if groupe["ferme_jours_feries"] and jour in feries_par_annee[jour.year]:
                continue
            if not groupe["permanent"]:
                if not groupe["periodes"]:
                    continue
                if not any(
                    periode_debut <= jour <= periode_fin + datetime.timedelta(days=extension)
                    for periode_debut, periode_fin in groupe["periodes"]
                ):
                    continue
            ouverts.add(jour)
    return sorted(ouverts)


def situation_animateur_semaine(animateur, jours_ouverts, debut, fin):
    """Construit la situation hebdomadaire d'un animateur.

    Un jour est encore possible uniquement s'il est :
    - réellement ouvert dans au moins un groupe ;
    - couvert par une disponibilité de l'animateur ;
    - non couvert par une affectation existante.
    """
    jours_ouverts = set(jours_ouverts)
    jours_plage = set(_jours_intervalle(debut, fin))

    disponibilites = list(
        animateur._filtre_disponibilites
        if hasattr(animateur, "_filtre_disponibilites")
        else animateur.disponibilites.all()
    )
    affectations = list(getattr(animateur, "_filtre_affectations", []))

    jours_disponibles = {
        jour
        for jour in jours_ouverts
        if any(disponibilite.debut <= jour <= disponibilite.fin for disponibilite in disponibilites)
    }

    jours_affectes = set()
    for affectation in affectations:
        debut_local = _date_locale(affectation.debut)
        fin_locale = _date_locale(affectation.fin)
        jours_affectes.update(_jours_intervalle(debut_local, fin_locale))
    jours_affectes &= jours_plage

    jours_restants = jours_disponibles - jours_affectes
    jours_affectes_ouverts = jours_ouverts & jours_affectes

    return {
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "jours_ouverts": [jour.isoformat() for jour in sorted(jours_ouverts)],
        "jours_disponibles": [jour.isoformat() for jour in sorted(jours_disponibles)],
        "jours_affectes": [jour.isoformat() for jour in sorted(jours_affectes_ouverts)],
        "jours_restants": [jour.isoformat() for jour in sorted(jours_restants)],
        "nombre_jours_ouverts": len(jours_ouverts),
        "nombre_jours_disponibles": len(jours_disponibles),
        "nombre_jours_affectes": len(jours_affectes_ouverts),
        "nombre_jours_restants": len(jours_restants),
        "encore_placable": bool(jours_restants),
        "disponible": bool(jours_disponibles),
        "affecte": bool(jours_affectes),
        "indisponible": not bool(jours_disponibles),
    }
