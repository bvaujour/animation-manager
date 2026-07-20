"""Données de pilotage pour la page d'accueil de la direction.

Le tableau de bord ne crée aucune donnée parallèle : il agrège les groupes,
les effectifs enfants et les affectations déjà utilisés par le Planning.
"""

from __future__ import annotations

import calendar
import datetime
import math
from collections import defaultdict

from django.db.models import Prefetch
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    EffectifEnfantsJour,
    Evenement,
)
from animateurs.services.qualifications import classes_equivalence_qualifications


ETAT_OK = "ok"
ETAT_INFO = "info"
ETAT_VIGILANCE = "vigilance"
ETAT_DANGER = "danger"
ETAT_VIDE = "vide"


def _debut_mois(jour: datetime.date) -> datetime.date:
    return jour.replace(day=1)


def _mois_suivant(jour: datetime.date) -> datetime.date:
    if jour.month == 12:
        return jour.replace(year=jour.year + 1, month=1, day=1)
    return jour.replace(month=jour.month + 1, day=1)


def _dt_locale(jour: datetime.date) -> datetime.datetime:
    return timezone.make_aware(
        datetime.datetime.combine(jour, datetime.time.min),
        timezone.get_current_timezone(),
    )


def _jours(debut: datetime.date, fin_exclusive: datetime.date):
    jour = debut
    while jour < fin_exclusive:
        yield jour
        jour += datetime.timedelta(days=1)


def _niveau_global(etats):
    etats = set(etats)
    if ETAT_DANGER in etats:
        return ETAT_DANGER
    if ETAT_VIGILANCE in etats:
        return ETAT_VIGILANCE
    if ETAT_INFO in etats:
        return ETAT_INFO
    if ETAT_OK in etats:
        return ETAT_OK
    return ETAT_VIDE


def _libelle_couverture(affectes: int, necessaires: int, effectifs_manquants: int) -> str:
    manque = max(necessaires - affectes, 0)
    if manque:
        return f"Manque {manque} anim."
    if effectifs_manquants:
        return "Effectifs à compléter"
    if affectes > necessaires:
        return "Équipe renforcée"
    return "Tout est OK"


def generer_tableau_de_bord(date_reference: datetime.date, centre_id: int | None = None):
    """Construit toutes les données utiles au tableau de bord.

    Les besoins d'encadrement sont calculés comme dans l'onglet Effectifs :
    ``ceil(nombre d'enfants / ratio)`` lorsqu'un effectif a été saisi. En
    l'absence de saisie, le besoin configuré sur le groupe sert uniquement de
    repère provisoire et une vigilance « effectif non renseigné » est émise.
    """

    centres_tous = list(Centre.objects.order_by("ordre", "nom"))
    centres = [centre for centre in centres_tous if centre_id is None or centre.id == centre_id]
    ids_centres = {centre.id for centre in centres}

    debut_mois = _debut_mois(date_reference)
    fin_mois = _mois_suivant(date_reference)
    debut_semaine = date_reference - datetime.timedelta(days=date_reference.weekday())
    fin_semaine = debut_semaine + datetime.timedelta(days=7)
    debut_semaine_precedente = debut_semaine - datetime.timedelta(days=7)
    # La marge à venir permet de trouver les prochains jours ouverts, même
    # entre deux semaines de vacances.
    fin_recherche = max(fin_mois, date_reference + datetime.timedelta(days=43), fin_semaine)
    debut_recherche = min(debut_mois, debut_semaine_precedente)

    fermetures_prefetch = Prefetch("dates_exclues")
    groupes = list(
        Evenement.objects.filter(centre_id__in=ids_centres)
        .select_related("centre")
        .prefetch_related(
            "periodes_scolaires",
            fermetures_prefetch,
            "besoins_qualifications__qualification",
        )
        .order_by("centre__ordre", "centre__nom", "ordre", "nom")
    )
    groupes_par_id = {groupe.id: groupe for groupe in groupes}
    fermetures_par_groupe = {
        groupe.id: {fermeture.date for fermeture in groupe.dates_exclues.all()}
        for groupe in groupes
    }

    effectifs = EffectifEnfantsJour.objects.filter(
        evenement_id__in=groupes_par_id,
        date__gte=debut_recherche,
        date__lt=fin_recherche,
    ).select_related("evenement")
    effectifs_par_cle = {(ligne.evenement_id, ligne.date): ligne for ligne in effectifs}

    affectations = list(
        Affectation.objects.filter(
            evenement_id__in=groupes_par_id,
            debut__lt=_dt_locale(fin_recherche),
            fin__gt=_dt_locale(debut_recherche),
        )
        .select_related("animateur", "centre", "evenement")
        .prefetch_related("animateur__qualifications")
        .order_by("debut", "animateur__prenom", "animateur__nom")
    )

    affectes_par_cle = defaultdict(set)
    animateurs_par_id: dict[int, Animateur] = {}
    for affectation in affectations:
        animateur = affectation.animateur
        animateurs_par_id[animateur.id] = animateur
        debut_affectation = max(timezone.localtime(affectation.debut).date(), debut_recherche)
        fin_affectation = min(timezone.localtime(affectation.fin).date(), fin_recherche)
        for jour in _jours(debut_affectation, fin_affectation):
            affectes_par_cle[(affectation.evenement_id, jour)].add(animateur.id)

    equivalences = classes_equivalence_qualifications()
    qualifications_effectives = {}
    for animateur in animateurs_par_id.values():
        ids = set()
        for qualification in animateur.qualifications.all():
            ids.update(equivalences.get(qualification.id, {qualification.id}))
        qualifications_effectives[animateur.id] = ids

    groupes_ouverts_cache = {}
    groupe_metriques_cache = {}
    jour_cache = {}

    def groupes_ouverts(jour):
        if jour not in groupes_ouverts_cache:
            groupes_ouverts_cache[jour] = [
                groupe
                for groupe in groupes
                if groupe.est_ouvert_le(jour, fermetures_par_groupe[groupe.id])
            ]
        return groupes_ouverts_cache[jour]

    def metriques_groupe(groupe, jour):
        cle = (groupe.id, jour)
        if cle in groupe_metriques_cache:
            return groupe_metriques_cache[cle]

        ligne = effectifs_par_cle.get(cle)
        effectif_saisi = ligne is not None
        enfants = ligne.nombre if ligne else 0
        ratio = (
            ligne.ratio_encadrement_effectif
            if ligne
            else max(1, groupe.enfants_par_animateur_defaut)
        )
        if effectif_saisi:
            necessaires = math.ceil(enfants / ratio) if enfants else 0
        else:
            necessaires = max(0, groupe.effectif_cible)

        ids_affectes = set(affectes_par_cle.get(cle, set()))
        affectes = len(ids_affectes)
        manque = max(necessaires - affectes, 0)

        qualifications_manquantes = []
        for besoin in groupe.besoins_qualifications.all():
            couverts = sum(
                1
                for animateur_id in ids_affectes
                if besoin.qualification_id in qualifications_effectives.get(animateur_id, set())
            )
            if couverts < besoin.nombre_minimum:
                qualifications_manquantes.append({
                    "qualification": besoin.qualification.nom,
                    "minimum": besoin.nombre_minimum,
                    "affectes": couverts,
                    "manque": besoin.nombre_minimum - couverts,
                })

        if manque or qualifications_manquantes:
            etat = ETAT_DANGER
        elif not effectif_saisi:
            etat = ETAT_VIGILANCE
        elif affectes > necessaires:
            etat = ETAT_INFO
        else:
            etat = ETAT_OK

        resultat = {
            "id": groupe.id,
            "nom": groupe.nom,
            "centre_id": groupe.centre_id,
            "centre_nom": groupe.centre.nom,
            "date": jour.isoformat(),
            "enfants": enfants,
            "effectif_saisi": effectif_saisi,
            "ratio": ratio,
            "animateurs_affectes": affectes,
            "animateurs_necessaires": necessaires,
            "manque_animateurs": manque,
            "surplus_animateurs": max(affectes - necessaires, 0),
            "qualifications_manquantes": qualifications_manquantes,
            "etat": etat,
            "animateur_ids": ids_affectes,
        }
        groupe_metriques_cache[cle] = resultat
        return resultat

    def metriques_jour(jour):
        if jour in jour_cache:
            return jour_cache[jour]

        groupes_jour = [metriques_groupe(groupe, jour) for groupe in groupes_ouverts(jour)]
        centres_jour = []
        for centre in centres:
            groupes_centre = [groupe for groupe in groupes_jour if groupe["centre_id"] == centre.id]
            if not groupes_centre:
                continue
            ids_affectes = set().union(*(groupe["animateur_ids"] for groupe in groupes_centre))
            enfants = sum(groupe["enfants"] for groupe in groupes_centre)
            necessaires = sum(groupe["animateurs_necessaires"] for groupe in groupes_centre)
            affectes = len(ids_affectes)
            effectifs_manquants = sum(1 for groupe in groupes_centre if not groupe["effectif_saisi"])
            manque = sum(groupe["manque_animateurs"] for groupe in groupes_centre)
            qualifications_manquantes = sum(
                len(groupe["qualifications_manquantes"]) for groupe in groupes_centre
            )
            etat = _niveau_global(groupe["etat"] for groupe in groupes_centre)
            centres_jour.append({
                "id": centre.id,
                "nom": centre.nom,
                "code": centre.code,
                "couleur": centre.couleur,
                "date": jour.isoformat(),
                "enfants": enfants,
                "animateurs_affectes": affectes,
                "animateurs_necessaires": necessaires,
                "manque_animateurs": manque,
                "effectifs_non_renseignes": effectifs_manquants,
                "qualifications_manquantes": qualifications_manquantes,
                "groupes_ouverts": len(groupes_centre),
                "etat": etat,
                "etat_libelle": _libelle_couverture(affectes, necessaires, effectifs_manquants),
                "groupes": groupes_centre,
                "animateur_ids": ids_affectes,
            })

        ids_affectes_jour = set().union(*(centre["animateur_ids"] for centre in centres_jour)) if centres_jour else set()
        resultat = {
            "date": jour.isoformat(),
            "enfants": sum(centre["enfants"] for centre in centres_jour),
            "animateurs_affectes": len(ids_affectes_jour),
            "animateurs_necessaires": sum(centre["animateurs_necessaires"] for centre in centres_jour),
            "manque_animateurs": sum(centre["manque_animateurs"] for centre in centres_jour),
            "effectifs_non_renseignes": sum(centre["effectifs_non_renseignes"] for centre in centres_jour),
            "qualifications_manquantes": sum(centre["qualifications_manquantes"] for centre in centres_jour),
            "groupes_ouverts": len(groupes_jour),
            "centres": centres_jour,
            "groupes": groupes_jour,
            "etat": _niveau_global(centre["etat"] for centre in centres_jour),
            "animateur_ids": ids_affectes_jour,
        }
        jour_cache[jour] = resultat
        return resultat

    def resume_semaine(debut):
        jours_semaine = [metriques_jour(debut + datetime.timedelta(days=i)) for i in range(7)]
        return {
            "jours": jours_semaine,
            "enfants": sum(jour["enfants"] for jour in jours_semaine),
            "journees_animateurs": sum(jour["animateurs_affectes"] for jour in jours_semaine),
            "journees_necessaires": sum(jour["animateurs_necessaires"] for jour in jours_semaine),
            "manque_animateurs": sum(jour["manque_animateurs"] for jour in jours_semaine),
            "effectifs_non_renseignes": sum(jour["effectifs_non_renseignes"] for jour in jours_semaine),
            "groupes_ouverts": sum(jour["groupes_ouverts"] for jour in jours_semaine),
            "groupes_a_risque": sum(
                1 for jour in jours_semaine for groupe in jour["groupes"]
                if groupe["manque_animateurs"] or groupe["qualifications_manquantes"]
            ),
            "problemes_critiques": sum(
                1 for jour in jours_semaine for groupe in jour["groupes"]
                if groupe["qualifications_manquantes"]
                or (groupe["animateurs_necessaires"] > 0 and groupe["animateurs_affectes"] == 0)
                or groupe["manque_animateurs"] >= 2
            ),
        }

    semaine = resume_semaine(debut_semaine)
    semaine_precedente = resume_semaine(debut_semaine_precedente)
    semaine["variation_enfants"] = semaine["enfants"] - semaine_precedente["enfants"]
    semaine["variation_animateurs"] = semaine["journees_animateurs"] - semaine_precedente["journees_animateurs"]

    jour_selectionne = metriques_jour(date_reference)

    alertes = []
    for groupe in jour_selectionne["groupes"]:
        action = f"/planning/?date={jour_selectionne['date']}&mode=effectifs&centre={groupe['centre_id']}"
        if groupe["manque_animateurs"]:
            nombre = groupe["manque_animateurs"]
            alertes.append({
                "niveau": "danger",
                "titre": f"Il manque {nombre} animateur{'s' if nombre > 1 else ''}",
                "detail": f"{groupe['centre_nom']} — {groupe['nom']}",
                "action_url": action,
                "action_label": "Voir",
            })
        for qualification in groupe["qualifications_manquantes"]:
            alertes.append({
                "niveau": "danger",
                "titre": f"Qualification manquante : {qualification['qualification']}",
                "detail": f"{groupe['centre_nom']} — {groupe['nom']} ({qualification['affectes']}/{qualification['minimum']})",
                "action_url": f"/planning/?date={jour_selectionne['date']}&mode=affectations&centre={groupe['centre_id']}",
                "action_label": "Voir",
            })
        if not groupe["effectif_saisi"]:
            alertes.append({
                "niveau": "vigilance",
                "titre": "Effectif enfants non renseigné",
                "detail": f"{groupe['centre_nom']} — {groupe['nom']}",
                "action_url": action,
                "action_label": "Saisir",
            })

    prochains = []
    for jour in _jours(date_reference, fin_recherche):
        donnees_jour = metriques_jour(jour)
        for centre in donnees_jour["centres"]:
            prochains.append({
                "date": jour.isoformat(),
                "centre_id": centre["id"],
                "centre_nom": centre["nom"],
                "couleur": centre["couleur"],
                "groupes": centre["groupes_ouverts"],
                "enfants": centre["enfants"],
                "animateurs_affectes": centre["animateurs_affectes"],
                "animateurs_necessaires": centre["animateurs_necessaires"],
                "etat": centre["etat"],
                "etat_libelle": centre["etat_libelle"],
                "action_url": f"/planning/?date={jour.isoformat()}&mode=affectations&centre={centre['id']}",
            })
            if len(prochains) >= 5:
                break
        if len(prochains) >= 5:
            break

    calendrier = []
    for jour in _jours(debut_mois, fin_mois):
        donnees = metriques_jour(jour)
        calendrier.append({
            "date": jour.isoformat(),
            "jour": jour.day,
            "etat": donnees["etat"],
            "enfants": donnees["enfants"],
            "animateurs_affectes": donnees["animateurs_affectes"],
            "animateurs_necessaires": donnees["animateurs_necessaires"],
            "alertes": donnees["manque_animateurs"] + donnees["effectifs_non_renseignes"] + donnees["qualifications_manquantes"],
            "groupes_ouverts": donnees["groupes_ouverts"],
        })

    mois_libelle = calendar.month_name[date_reference.month]
    # calendar.month_name est en anglais dans certains environnements serveur ;
    # le front reformate la date en français, ce libellé sert de repli.
    return {
        "date_selectionnee": date_reference.isoformat(),
        "centre_selectionne": centre_id,
        "centres_filtres": [
            {"id": centre.id, "nom": centre.nom, "code": centre.code, "couleur": centre.couleur}
            for centre in centres_tous
        ],
        "periode": {
            "debut_semaine": debut_semaine.isoformat(),
            "fin_semaine": (fin_semaine - datetime.timedelta(days=1)).isoformat(),
            "mois": date_reference.month,
            "annee": date_reference.year,
            "libelle_repli": f"{mois_libelle} {date_reference.year}",
        },
        "indicateurs": {
            **{cle: valeur for cle, valeur in semaine.items() if cle != "jours"},
            "couverture_pourcentage": round(
                (semaine["journees_animateurs"] / semaine["journees_necessaires"] * 100)
                if semaine["journees_necessaires"]
                else 100
            ),
        },
        "jour": {
            **{cle: valeur for cle, valeur in jour_selectionne.items() if cle not in {"groupes", "animateur_ids"}},
            "centres": [
                {cle: valeur for cle, valeur in centre.items() if cle not in {"groupes", "animateur_ids"}}
                for centre in jour_selectionne["centres"]
            ],
        },
        "calendrier": calendrier,
        "semaine": [
            {cle: valeur for cle, valeur in jour.items() if cle not in {"centres", "groupes", "animateur_ids"}}
            for jour in semaine["jours"]
        ],
        "alertes": alertes[:8],
        "prochains_jours": prochains,
    }
