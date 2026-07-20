"""Remplissage automatique déterministe du planning.

Contraintes strictes :
- l'effectif quotidien vient de ``effectif_cible`` ;
- un salarié doit être disponible et ne peut travailler que dans un groupe par jour ;
- un lieu explicitement interdit n'est jamais proposé ;
- les minima de qualifications configurés dans chaque groupe sont respectés ;
- lorsqu'une qualification manque, le nombre minimal de postes nécessaires pour
  la couvrir reste vacant au lieu d'être occupé par une personne non qualifiée.

Priorités de départage :
- couvrir les qualifications les plus rares ;
- couvrir le maximum de groupes avant de compléter les équipes ;
- favoriser le lieu préféré ;
- conserver la même équipe pendant la semaine ;
- favoriser l'expérience passée dans le groupe puis dans le lieu.

Une même personne peut couvrir plusieurs exigences d'un groupe lorsqu'elle
possède plusieurs qualifications. Une exigence « 2 BAFA » demande toutefois
bien deux personnes couvrant le BAFA.
"""

from __future__ import annotations

import datetime
from collections import defaultdict, deque
from dataclasses import dataclass

from django.db import transaction
from django.utils.dateparse import parse_date

from animateurs.models import (
    Affectation,
    AffiniteGroupeAnimateur,
    Animateur,
    Evenement,
    Qualification,
)

from .affinites import synchroniser_affinites_groupes
from .dates import parse_to_aware_datetime
from .qualifications import couvertures_qualifications


@dataclass
class _Arete:
    destination: int
    retour: int
    capacite: int
    cout: int


def _ajouter_arete(graphe, source, destination, capacite, cout):
    aller = _Arete(destination, len(graphe[destination]), capacite, cout)
    retour = _Arete(source, len(graphe[source]), 0, -cout)
    graphe[source].append(aller)
    graphe[destination].append(retour)
    return aller


def _meilleure_affectation(animateurs, groupes, capacites, score):
    """Maximise d'abord le nombre d'affectations, puis leur score."""

    groupes = [groupe for groupe in groupes if capacites.get(groupe.id, 0) > 0]
    if not animateurs or not groupes:
        return []

    source = 0
    premier_animateur = 1
    premier_groupe = premier_animateur + len(animateurs)
    puits = premier_groupe + len(groupes)
    graphe = [[] for _ in range(puits + 1)]

    index_animateur = {
        animateur.id: premier_animateur + index
        for index, animateur in enumerate(animateurs)
    }
    index_groupe = {
        groupe.id: premier_groupe + index
        for index, groupe in enumerate(groupes)
    }
    aretes_candidats = {}

    for animateur in animateurs:
        _ajouter_arete(graphe, source, index_animateur[animateur.id], 1, 0)

    for groupe in groupes:
        _ajouter_arete(
            graphe,
            index_groupe[groupe.id],
            puits,
            int(capacites[groupe.id]),
            0,
        )

    for animateur in animateurs:
        for groupe in groupes:
            valeur = score(animateur, groupe)
            if valeur is None:
                continue
            aretes_candidats[(animateur.id, groupe.id)] = _ajouter_arete(
                graphe,
                index_animateur[animateur.id],
                index_groupe[groupe.id],
                1,
                -int(valeur),
            )

    # SPFA : les graphes manipulés ici restent petits et les coûts de
    # préférence peuvent être négatifs.
    while True:
        infini = 10**30
        distances = [infini] * len(graphe)
        precedent_noeud = [-1] * len(graphe)
        precedente_arete = [-1] * len(graphe)
        dans_file = [False] * len(graphe)
        distances[source] = 0
        file = deque([source])
        dans_file[source] = True

        while file:
            noeud = file.popleft()
            dans_file[noeud] = False
            for index, arete in enumerate(graphe[noeud]):
                if arete.capacite <= 0:
                    continue
                nouvelle_distance = distances[noeud] + arete.cout
                if nouvelle_distance >= distances[arete.destination]:
                    continue
                distances[arete.destination] = nouvelle_distance
                precedent_noeud[arete.destination] = noeud
                precedente_arete[arete.destination] = index
                if not dans_file[arete.destination]:
                    file.append(arete.destination)
                    dans_file[arete.destination] = True

        if distances[puits] == infini:
            break

        noeud = puits
        while noeud != source:
            precedent = precedent_noeud[noeud]
            index = precedente_arete[noeud]
            arete = graphe[precedent][index]
            arete.capacite -= 1
            graphe[noeud][arete.retour].capacite += 1
            noeud = precedent

    groupes_par_id = {groupe.id: groupe for groupe in groupes}
    animateurs_par_id = {animateur.id: animateur for animateur in animateurs}
    return [
        (animateurs_par_id[animateur_id], groupes_par_id[groupe_id])
        for (animateur_id, groupe_id), arete in aretes_candidats.items()
        if arete.capacite == 0
    ]


def generer_planning_auto(payload):
    """Remplit tous les groupes ouverts du lundi au vendredi."""

    debut_date = parse_date((payload or {}).get("debut", ""))
    if not debut_date:
        return {"error": "Date de début invalide."}, 400

    lundi = debut_date - datetime.timedelta(days=debut_date.weekday())
    jours = [lundi + datetime.timedelta(days=index) for index in range(5)]
    samedi = lundi + datetime.timedelta(days=5)
    debut_dt = parse_to_aware_datetime(lundi.isoformat())
    fin_dt = parse_to_aware_datetime(samedi.isoformat())

    groupes_configures = list(
        Evenement.objects.select_related("centre")
        .prefetch_related(
            "dates_exclues",
            "periodes_scolaires",
            "besoins_qualifications__qualification",
        )
        .order_by("centre__ordre", "centre__nom", "ordre", "nom", "id")
    )
    animateurs = list(
        Animateur.objects.prefetch_related(
            "disponibilites",
            "preferences",
            "qualifications",
        ).order_by("prenom", "nom", "id")
    )

    if not groupes_configures:
        return {"error": "Aucun groupe n'est configuré."}, 400
    if not animateurs:
        return {"error": "Aucun animateur n'est configuré."}, 400

    dates_exclues = {
        groupe.id: {fermeture.date for fermeture in groupe.dates_exclues.all()}
        for groupe in groupes_configures
    }
    groupes_par_jour = {
        jour: [
            groupe
            for groupe in groupes_configures
            if groupe.effectif_cible > 0
            and groupe.est_ouvert_le(jour, dates_exclues[groupe.id])
        ]
        for jour in jours
    }
    if not any(groupes_par_jour.values()):
        return {
            "error": "Aucune place à remplir : vérifie les effectifs et les jours d'ouverture des groupes."
        }, 400

    besoins_qualifications = {
        groupe.id: {
            besoin.qualification_id: int(besoin.nombre_minimum)
            for besoin in groupe.besoins_qualifications.all()
            if besoin.nombre_minimum > 0
        }
        for groupe in groupes_configures
    }
    noms_qualifications = dict(Qualification.objects.values_list("id", "nom"))
    couvertures = couvertures_qualifications()
    qualifications_animateurs = {}
    for animateur in animateurs:
        effectives = set()
        for qualification in animateur.qualifications.all():
            effectives.update(couvertures.get(qualification.id, {qualification.id}))
        qualifications_animateurs[animateur.id] = effectives

    disponibilites = {
        animateur.id: list(animateur.disponibilites.all())
        for animateur in animateurs
    }
    centres_interdits = {
        animateur.id: {
            preference.centre_id
            for preference in animateur.preferences.all()
            if preference.est_interdit
        }
        for animateur in animateurs
    }
    centres_preferes = {
        animateur.id: {
            preference.centre_id
            for preference in animateur.preferences.all()
            if preference.est_prefere and not preference.est_interdit
        }
        for animateur in animateurs
    }

    # La table d'affinité est la source persistante du nombre de jours
    # réellement travaillés dans chaque groupe. Elle est resynchronisée avant
    # chaque calcul afin que le passage d'une journée au statut « terminée »
    # soit pris en compte même sans modification manuelle du planning.
    synchroniser_affinites_groupes()
    affinites_groupes = {}
    historique_centres = defaultdict(int)
    for animateur_id, groupe_id, centre_id, jours_travailles in (
        AffiniteGroupeAnimateur.objects.values_list(
            "animateur_id",
            "evenement_id",
            "evenement__centre_id",
            "jours_travailles",
        )
    ):
        affinites_groupes[(animateur_id, groupe_id)] = int(jours_travailles)
        historique_centres[(animateur_id, centre_id)] += int(jours_travailles)

    semaine_groupes = defaultdict(int)
    semaine_centres = defaultdict(int)
    groupes_veille = defaultdict(set)
    rang_animateur = {animateur.id: index for index, animateur in enumerate(animateurs)}
    rang_groupe = {groupe.id: index for index, groupe in enumerate(groupes_configures)}

    def disponible(animateur, jour):
        plages = disponibilites[animateur.id]
        return bool(plages) and any(plage.debut <= jour <= plage.fin for plage in plages)

    def autorise(animateur, groupe):
        return groupe.centre_id not in centres_interdits.get(animateur.id, set())

    def score_candidat(animateur, groupe):
        if not autorise(animateur, groupe):
            return None

        score = 0
        if groupe.centre_id in centres_preferes.get(animateur.id, set()):
            score += 10_000_000
        if groupe.id in groupes_veille.get(animateur.id, set()):
            score += 3_000_000
        score += min(semaine_groupes[(animateur.id, groupe.id)], 4) * 500_000
        score += min(affinites_groupes.get((animateur.id, groupe.id), 0), 9_999) * 10_000
        score += min(semaine_centres[(animateur.id, groupe.centre_id)], 4) * 100
        score += min(historique_centres.get((animateur.id, groupe.centre_id), 0), 99)
        score += len(animateurs) - rang_animateur[animateur.id]
        return score

    def manques_qualifications(groupe, selection):
        manques = {}
        for qualification_id, minimum in besoins_qualifications[groupe.id].items():
            couverts = sum(
                1
                for animateur in selection
                if qualification_id in qualifications_animateurs[animateur.id]
            )
            if couverts < minimum:
                manques[qualification_id] = minimum - couverts
        return manques

    planning = []
    qualifications_manquantes_total = 0
    details_qualifications = []

    for jour in jours:
        groupes_jour = groupes_par_jour[jour]
        disponibles_jour = [animateur for animateur in animateurs if disponible(animateur, jour)]
        utilises = set()
        selection_par_groupe = {groupe.id: [] for groupe in groupes_jour}

        def ajouter(
            animateur,
            groupe,
            utilises_jour=utilises,
            selections_jour=selection_par_groupe,
        ):
            utilises_jour.add(animateur.id)
            selections_jour[groupe.id].append(animateur)

        # Passage 1 : affecter les personnes qualifiées avant tout poste
        # générique. Les besoins les plus rares obtiennent le poids le plus
        # fort ; un groupe encore vide est également prioritaire.
        while True:
            meilleur = None
            for groupe in groupes_jour:
                selection = selection_par_groupe[groupe.id]
                if len(selection) >= groupe.effectif_cible:
                    continue
                manques = manques_qualifications(groupe, selection)
                if not manques:
                    continue

                candidats = [
                    animateur
                    for animateur in disponibles_jour
                    if animateur.id not in utilises and autorise(animateur, groupe)
                ]
                for animateur in candidats:
                    couvertes = {
                        qualification_id
                        for qualification_id in manques
                        if qualification_id in qualifications_animateurs[animateur.id]
                    }
                    if not couvertes:
                        continue

                    rarete = 0
                    for qualification_id in couvertes:
                        nombre_candidats = sum(
                            1
                            for candidat in candidats
                            if qualification_id in qualifications_animateurs[candidat.id]
                        )
                        rarete += 1_000_000 // max(1, nombre_candidats)

                    valeur = (
                        1 if not selection else 0,
                        rarete,
                        len(couvertes),
                        score_candidat(animateur, groupe),
                        -rang_groupe[groupe.id],
                        -rang_animateur[animateur.id],
                    )
                    if meilleur is None or valeur > meilleur[0]:
                        meilleur = (valeur, animateur, groupe)

            if meilleur is None:
                break
            _, animateur, groupe = meilleur
            ajouter(animateur, groupe)

        def capacite_generique(groupe, selections_jour=selection_par_groupe):
            selection = selections_jour[groupe.id]
            places_restantes = max(0, groupe.effectif_cible - len(selection))
            manques = manques_qualifications(groupe, selection)
            # Une personne multiqualifiée peut couvrir plusieurs exigences à
            # la fois. Le nombre minimal de places à réserver est donc le plus
            # grand minimum encore manquant, et non la somme des manques.
            places_reservees = max(manques.values(), default=0)
            return max(0, places_restantes - places_reservees)

        # Passage 2 : donner une présence aux groupes encore vides lorsque des
        # postes non qualifiés sont réellement disponibles.
        restants = [animateur for animateur in disponibles_jour if animateur.id not in utilises]
        groupes_a_couvrir = [
            groupe
            for groupe in groupes_jour
            if not selection_par_groupe[groupe.id] and capacite_generique(groupe) > 0
        ]
        couverture = _meilleure_affectation(
            restants,
            groupes_a_couvrir,
            {groupe.id: 1 for groupe in groupes_a_couvrir},
            score_candidat,
        )
        for animateur, groupe in couverture:
            ajouter(animateur, groupe)

        # Passage 3 : compléter les autres postes, sans consommer les places
        # réservées aux qualifications encore manquantes.
        restants = [animateur for animateur in disponibles_jour if animateur.id not in utilises]
        capacites = {groupe.id: capacite_generique(groupe) for groupe in groupes_jour}
        complements = _meilleure_affectation(
            restants,
            groupes_jour,
            capacites,
            score_candidat,
        )
        for animateur, groupe in complements:
            ajouter(animateur, groupe)

        groupes_du_jour_par_animateur = defaultdict(set)
        for groupe in groupes_jour:
            selection = selection_par_groupe[groupe.id]
            for animateur in selection:
                planning.append((jour, animateur, groupe))
                semaine_groupes[(animateur.id, groupe.id)] += 1
                semaine_centres[(animateur.id, groupe.centre_id)] += 1
                groupes_du_jour_par_animateur[animateur.id].add(groupe.id)

            manques = manques_qualifications(groupe, selection)
            if manques:
                qualifications_manquantes_total += sum(manques.values())
                libelles = ", ".join(
                    f"{nombre} × {noms_qualifications.get(qualification_id, 'qualification')}"
                    for qualification_id, nombre in manques.items()
                )
                details_qualifications.append(
                    f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom} : {libelles} manquant(s)"
                )

        groupes_veille = groupes_du_jour_par_animateur

    with transaction.atomic():
        supprimees, _ = Affectation.objects.filter(
            debut__lt=fin_dt,
            fin__gt=debut_dt,
        ).delete()
        a_creer = [
            Affectation(
                animateur=animateur,
                centre=groupe.centre,
                evenement=groupe,
                debut=parse_to_aware_datetime(jour.isoformat()),
                fin=parse_to_aware_datetime((jour + datetime.timedelta(days=1)).isoformat()),
            )
            for jour, animateur, groupe in planning
        ]
        Affectation.objects.bulk_create(a_creer)

    # ``bulk_create`` ne déclenche pas les signaux Django. Une synchronisation
    # explicite garantit donc que la génération d'une semaine déjà passée met
    # elle aussi immédiatement à jour les scores d'affinité.
    synchroniser_affinites_groupes()

    total_places = sum(
        groupe.effectif_cible
        for groupes_jour in groupes_par_jour.values()
        for groupe in groupes_jour
    )
    remplis_par_cle = defaultdict(int)
    for jour, _, groupe in planning:
        remplis_par_cle[(jour, groupe.id)] += 1

    details_non_remplis = []
    groupes_complets = 0
    groupes_partiels = 0
    groupes_vides = 0
    for jour in jours:
        for groupe in groupes_par_jour[jour]:
            remplis = remplis_par_cle[(jour, groupe.id)]
            manque = groupe.effectif_cible - remplis
            if manque <= 0:
                groupes_complets += 1
                continue
            if remplis:
                groupes_partiels += 1
            else:
                groupes_vides += 1
            details_non_remplis.append(
                f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom} : "
                f"{manque} place(s) vide(s)"
            )

    creees = len(a_creer)
    non_remplies = total_places - creees
    animateurs_utilises = len({affectation.animateur_id for affectation in a_creer})
    message = (
        f"{creees}/{total_places} place(s) remplie(s), "
        f"{groupes_complets} groupe(s)-jour complet(s), "
        f"{groupes_partiels} partiel(s) et {groupes_vides} vide(s). "
        f"{supprimees} ancienne(s) affectation(s) remplacée(s)."
    )
    if qualifications_manquantes_total:
        message += (
            f" {qualifications_manquantes_total} exigence(s) de qualification "
            "reste(nt) non couverte(s)."
        )
    if non_remplies:
        message += (
            " Les places restantes correspondent à un manque de salariés disponibles, "
            "autorisés ou suffisamment qualifiés."
        )

    return {
        "ok": True,
        "created": creees,
        "deleted": supprimees,
        "total_places": total_places,
        "unfilled": non_remplies,
        "animateurs_utilises": animateurs_utilises,
        "groupes_complets": groupes_complets,
        "groupes_partiels": groupes_partiels,
        "groupes_vides": groupes_vides,
        "qualifications_manquantes": qualifications_manquantes_total,
        "interrompu": False,
        "appels": 0,
        "details_non_remplis": details_non_remplis[:50],
        "details_qualifications": details_qualifications[:50],
        "message": message,
    }, 200
