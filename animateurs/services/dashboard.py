"""Agrégats hebdomadaires utilisés par le tableau de bord de la direction.

Le tableau de bord s'appuie exclusivement sur les données du Planning : groupes
ouverts, effectifs enfants, besoins d'encadrement, qualifications et
affectations. Toutes les valeurs retournées concernent l'ensemble des centres
pour la semaine sélectionnée.
"""

from __future__ import annotations

import datetime
import math
from collections import defaultdict

from django.db.models import Prefetch
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, EffectifEnfantsJour, Evenement
from animateurs.services.flottants import groupes_visibles
from animateurs.services.qualifications import couvertures_qualifications

ETAT_OK = "ok"
ETAT_VIGILANCE = "vigilance"
ETAT_DANGER = "danger"
ETAT_VIDE = "vide"
JOURS_TABLEAU_DE_BORD = 5


def _categorie_age_groupe(groupe: Evenement) -> str | None:
    """Rattache les groupes usuels aux deux catégories du tableau de bord.

    Les groupes partagés portent généralement les noms « Maternelles » et
    « Élémentaires ». Les alias 3/5 ans et 6/10 ans sont aussi reconnus afin
    que l’agrégat reste juste avec les anciennes dénominations.
    """

    cle = groupe.groupe.cle_unique if groupe.groupe_id else groupe.cle_unique
    if "maternel" in cle or "3 5" in cle or "3 6" in cle:
        return "maternels"
    if "elementair" in cle or "6 10" in cle:
        return "elementaires"
    return None


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
    if ETAT_OK in etats:
        return ETAT_OK
    return ETAT_VIDE


def _libelle_centre_semaine(
    *,
    jours_ouverts: int,
    manque_animateurs: int,
    qualifications_manquantes: int,
    effectifs_non_renseignes: int,
    journees_animateurs: int,
    journees_necessaires: int,
) -> str:
    if not jours_ouverts:
        return "Aucune ouverture"
    if manque_animateurs:
        suffixe = "s" if manque_animateurs > 1 else ""
        return f"Manque {manque_animateurs} journée{suffixe} anim."
    if qualifications_manquantes:
        return "Qualifications à compléter"
    if effectifs_non_renseignes:
        return "Effectifs à compléter"
    if journees_animateurs > journees_necessaires:
        return "Équipe renforcée"
    return "Tout est OK"


def generer_tableau_de_bord(date_reference: datetime.date):
    """Construit les indicateurs de la semaine contenant ``date_reference``.

    La semaine affichée va du lundi au vendredi. Les besoins d'encadrement sont
    calculés comme dans l'onglet Effectifs : ``ceil(enfants / ratio)`` lorsqu'un
    effectif a été saisi. Sans saisie, le besoin configuré sur le groupe sert de
    repère provisoire et une vigilance est créée.
    """

    centres = list(Centre.objects.order_by("ordre", "nom"))
    ids_centres = {centre.id for centre in centres}

    debut_semaine = date_reference - datetime.timedelta(days=date_reference.weekday())
    fin_semaine_exclusive = debut_semaine + datetime.timedelta(days=JOURS_TABLEAU_DE_BORD)
    debut_semaine_precedente = debut_semaine - datetime.timedelta(days=7)
    debut_recherche = debut_semaine_precedente
    fin_recherche = fin_semaine_exclusive

    groupes = list(
        groupes_visibles(Evenement.objects.filter(centre_id__in=ids_centres))
        .select_related("centre", "groupe")
        .prefetch_related(
            "periodes_scolaires",
            Prefetch("dates_exclues"),
            "besoins_qualifications__qualification",
        )
        .order_by("centre__ordre", "centre__nom", "ordre", "nom")
    )
    groupes_par_id = {groupe.id: groupe for groupe in groupes}
    fermetures_par_groupe = {
        groupe.id: {fermeture.date for fermeture in groupe.dates_exclues.all()} for groupe in groupes
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
        .prefetch_related("animateur__qualifications", "horaires_journaliers")
        .order_by("debut", "animateur__prenom", "animateur__nom")
    )

    affectes_par_cle = defaultdict(set)
    horaires_par_cle = defaultdict(set)
    animateurs_par_id: dict[int, Animateur] = {}
    for affectation in affectations:
        animateur = affectation.animateur
        animateurs_par_id[animateur.id] = animateur
        debut_affectation = max(timezone.localtime(affectation.debut).date(), debut_recherche)
        fin_affectation = min(timezone.localtime(affectation.fin).date(), fin_recherche)
        for jour in _jours(debut_affectation, fin_affectation):
            affectes_par_cle[(affectation.evenement_id, jour)].add(animateur.id)
        for horaire in affectation.horaires_journaliers.all():
            horaires_par_cle[(affectation.evenement_id, horaire.date)].add(animateur.id)

    couvertures = couvertures_qualifications()
    qualifications_effectives = {}
    for animateur in animateurs_par_id.values():
        ids = set()
        for qualification in animateur.qualifications.all():
            ids.update(couvertures.get(qualification.id, {qualification.id}))
        qualifications_effectives[animateur.id] = ids

    groupes_ouverts_cache = {}
    groupe_metriques_cache = {}
    jour_cache = {}

    def groupes_ouverts(jour):
        if jour not in groupes_ouverts_cache:
            groupes_ouverts_cache[jour] = [
                groupe for groupe in groupes if groupe.est_ouvert_le(jour, fermetures_par_groupe[groupe.id])
            ]
        return groupes_ouverts_cache[jour]

    def metriques_groupe(groupe, jour):
        cle = (groupe.id, jour)
        if cle in groupe_metriques_cache:
            return groupe_metriques_cache[cle]

        ligne = effectifs_par_cle.get(cle)
        effectif_saisi = ligne is not None
        enfants = ligne.nombre if ligne else 0
        ratio = ligne.ratio_encadrement_effectif if ligne else max(1, groupe.enfants_par_animateur_defaut)
        necessaires = (
            (math.ceil(enfants / ratio) if effectif_saisi and enfants else 0)
            if effectif_saisi
            else max(0, groupe.effectif_cible)
        )

        ids_affectes = set(affectes_par_cle.get(cle, set()))
        horaires_saisis = bool(ids_affectes) and ids_affectes <= horaires_par_cle.get(cle, set())
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
                qualifications_manquantes.append(
                    {
                        "qualification": besoin.qualification.nom,
                        "minimum": besoin.nombre_minimum,
                        "affectes": couverts,
                        "manque": besoin.nombre_minimum - couverts,
                    }
                )

        ecart_partiel = manque or qualifications_manquantes or affectes > necessaires or not horaires_saisis
        completement_non_fait = (
            (necessaires > 0 and affectes == 0)
            or any(
                qualification["minimum"] > 0 and qualification["affectes"] == 0
                for qualification in qualifications_manquantes
            )
            or not effectif_saisi
        )
        etat = ETAT_DANGER if completement_non_fait else ETAT_VIGILANCE if ecart_partiel else ETAT_OK

        resultat = {
            "id": groupe.id,
            "nom": groupe.nom,
            "centre_id": groupe.centre_id,
            "centre_nom": groupe.centre.nom,
            "date": jour.isoformat(),
            "enfants": enfants,
            "categorie_age": _categorie_age_groupe(groupe),
            "effectif_saisi": effectif_saisi,
            "horaires_saisis": horaires_saisis,
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
            qualifications_manquantes = sum(len(groupe["qualifications_manquantes"]) for groupe in groupes_centre)
            centres_jour.append(
                {
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
                    "etat": _niveau_global(groupe["etat"] for groupe in groupes_centre),
                    "groupes": groupes_centre,
                    "animateur_ids": ids_affectes,
                }
            )

        ids_affectes_jour = (
            set().union(*(centre["animateur_ids"] for centre in centres_jour)) if centres_jour else set()
        )
        resultat = {
            "date": jour.isoformat(),
            "enfants": sum(centre["enfants"] for centre in centres_jour),
            "enfants_maternels": sum(
                groupe["enfants"] for groupe in groupes_jour if groupe["categorie_age"] == "maternels"
            ),
            "enfants_elementaires": sum(
                groupe["enfants"] for groupe in groupes_jour if groupe["categorie_age"] == "elementaires"
            ),
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
        jours_semaine = [
            metriques_jour(debut + datetime.timedelta(days=index)) for index in range(JOURS_TABLEAU_DE_BORD)
        ]
        groupes_semaine = [groupe for jour in jours_semaine for groupe in jour["groupes"]]

        def est_critique(groupe):
            return bool(
                groupe["qualifications_manquantes"]
                or (groupe["animateurs_necessaires"] > 0 and groupe["animateurs_affectes"] == 0)
                or groupe["manque_animateurs"] >= 2
            )

        return {
            "jours": jours_semaine,
            "enfants": sum(jour["enfants"] for jour in jours_semaine),
            "journees_animateurs": sum(jour["animateurs_affectes"] for jour in jours_semaine),
            "journees_necessaires": sum(jour["animateurs_necessaires"] for jour in jours_semaine),
            "manque_animateurs": sum(jour["manque_animateurs"] for jour in jours_semaine),
            "effectifs_non_renseignes": sum(jour["effectifs_non_renseignes"] for jour in jours_semaine),
            "groupes_ouverts": sum(jour["groupes_ouverts"] for jour in jours_semaine),
            "groupes_a_risque": sum(
                1
                for jour in jours_semaine
                for groupe in jour["groupes"]
                if groupe["manque_animateurs"] or groupe["qualifications_manquantes"]
            ),
            "problemes_critiques": sum(1 for groupe in groupes_semaine if est_critique(groupe)),
            "problemes_moderes": sum(
                1 for groupe in groupes_semaine if groupe["etat"] == ETAT_VIGILANCE and not est_critique(groupe)
            ),
        }

    semaine = resume_semaine(debut_semaine)
    semaine_precedente = resume_semaine(debut_semaine_precedente)
    semaine["variation_enfants"] = semaine["enfants"] - semaine_precedente["enfants"]
    semaine["variation_animateurs"] = semaine["journees_animateurs"] - semaine_precedente["journees_animateurs"]

    centres_semaine = []
    for centre in centres:
        jours_centre = []
        ids_groupes = set()
        etats = []
        for jour in semaine["jours"]:
            donnees_centre = next(
                (item for item in jour["centres"] if item["id"] == centre.id),
                None,
            )
            if donnees_centre is None:
                continue
            jours_centre.append(donnees_centre)
            etats.append(donnees_centre["etat"])
            ids_groupes.update(groupe["id"] for groupe in donnees_centre["groupes"])

        jours_ouverts = len(jours_centre)
        enfants = sum(item["enfants"] for item in jours_centre)
        journees_groupes = sum(1 for item in jours_centre for groupe in item["groupes"] if groupe["effectif_saisi"])
        moyenne_enfants_groupe_jour = round(enfants / journees_groupes, 1) if journees_groupes else 0
        journees_animateurs = sum(item["animateurs_affectes"] for item in jours_centre)
        journees_necessaires = sum(item["animateurs_necessaires"] for item in jours_centre)
        manque_animateurs = sum(item["manque_animateurs"] for item in jours_centre)
        effectifs_non_renseignes = sum(item["effectifs_non_renseignes"] for item in jours_centre)
        qualifications_manquantes = sum(item["qualifications_manquantes"] for item in jours_centre)
        centres_semaine.append(
            {
                "id": centre.id,
                "nom": centre.nom,
                "code": centre.code,
                "couleur": centre.couleur,
                "jours_ouverts": jours_ouverts,
                "groupes": len(ids_groupes),
                "enfants": enfants,
                "moyenne_enfants_groupe_jour": moyenne_enfants_groupe_jour,
                "journees_animateurs": journees_animateurs,
                "journees_necessaires": journees_necessaires,
                "manque_animateurs": manque_animateurs,
                "effectifs_non_renseignes": effectifs_non_renseignes,
                "qualifications_manquantes": qualifications_manquantes,
                "etat": _niveau_global(etats),
                "etat_libelle": _libelle_centre_semaine(
                    jours_ouverts=jours_ouverts,
                    manque_animateurs=manque_animateurs,
                    qualifications_manquantes=qualifications_manquantes,
                    effectifs_non_renseignes=effectifs_non_renseignes,
                    journees_animateurs=journees_animateurs,
                    journees_necessaires=journees_necessaires,
                ),
            }
        )

    alertes = []
    for jour in semaine["jours"]:
        for groupe in jour["groupes"]:
            date = jour["date"]
            action_affectations = f"/planning/?date={date}&mode=affectations&centre={groupe['centre_id']}"
            action_effectifs = f"/planning/?date={date}&mode=effectifs&centre={groupe['centre_id']}"
            if groupe["manque_animateurs"]:
                nombre = groupe["manque_animateurs"]
                alertes.append(
                    {
                        "date": date,
                        "niveau": "danger",
                        "titre": f"Il manque {nombre} animateur{'s' if nombre > 1 else ''}",
                        "detail": f"{groupe['centre_nom']} — {groupe['nom']}",
                        "action_url": action_affectations,
                        "action_label": "Voir",
                    }
                )
            for qualification in groupe["qualifications_manquantes"]:
                alertes.append(
                    {
                        "date": date,
                        "niveau": "danger",
                        "titre": (f"Qualification manquante : {qualification['qualification']}"),
                        "detail": (
                            f"{groupe['centre_nom']} — {groupe['nom']} "
                            f"({qualification['affectes']}/{qualification['minimum']})"
                        ),
                        "action_url": action_affectations,
                        "action_label": "Voir",
                    }
                )
            if not groupe["effectif_saisi"]:
                alertes.append(
                    {
                        "date": date,
                        "niveau": "vigilance",
                        "titre": "Effectif enfants non renseigné",
                        "detail": f"{groupe['centre_nom']} — {groupe['nom']}",
                        "action_url": action_effectifs,
                        "action_label": "Saisir",
                    }
                )
            if not groupe["horaires_saisis"]:
                alertes.append(
                    {
                        "date": date,
                        "niveau": "vigilance",
                        "titre": "Horaires non renseignés",
                        "detail": f"{groupe['centre_nom']} — {groupe['nom']}",
                        "action_url": (f"/planning/?date={date}&mode=affectations&centre={groupe['centre_id']}"),
                        "action_label": "Saisir",
                    }
                )

    alertes.sort(
        key=lambda alerte: (
            alerte["date"],
            0 if alerte["niveau"] == "danger" else 1,
            alerte["detail"],
        )
    )

    return {
        "date_selectionnee": debut_semaine.isoformat(),
        "periode": {
            "debut_semaine": debut_semaine.isoformat(),
            "fin_semaine": (fin_semaine_exclusive - datetime.timedelta(days=1)).isoformat(),
        },
        "indicateurs": {
            **{cle: valeur for cle, valeur in semaine.items() if cle != "jours"},
            "couverture_pourcentage": round(
                (semaine["journees_animateurs"] / semaine["journees_necessaires"] * 100)
                if semaine["journees_necessaires"]
                else 100
            ),
        },
        "centres_semaine": centres_semaine,
        "semaine": [
            {cle: valeur for cle, valeur in jour.items() if cle not in {"centres", "groupes", "animateur_ids"}}
            for jour in semaine["jours"]
        ],
        "alertes": alertes,
    }
