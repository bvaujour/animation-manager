"""Remplissage automatique du planning selon un ordre métier explicite.

Pour chaque journée, le moteur affecte successivement :
1. les personnes permettant de couvrir les statuts demandés ;
2. les personnes possédant les diplômes précis demandés ;
3. les postes restants selon l'affinité avec le groupe.

À chaque étape, les disponibilités, lieux interdits, préférences de lieu,
continuité sur la semaine et limites d'effectif restent prises en compte.
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
from .flottants import groupes_visibles
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
    """Maximise le nombre de postes remplis, puis le score des candidats."""

    groupes = [groupe for groupe in groupes if capacites.get(groupe.id, 0) > 0]
    if not animateurs or not groupes:
        return []

    source = 0
    premier_animateur = 1
    premier_groupe = premier_animateur + len(animateurs)
    puits = premier_groupe + len(groupes)
    graphe = [[] for _ in range(puits + 1)]
    index_animateur = {a.id: premier_animateur + index for index, a in enumerate(animateurs)}
    index_groupe = {g.id: premier_groupe + index for index, g in enumerate(groupes)}
    aretes_candidats = {}

    for animateur in animateurs:
        _ajouter_arete(graphe, source, index_animateur[animateur.id], 1, 0)
    for groupe in groupes:
        _ajouter_arete(graphe, index_groupe[groupe.id], puits, int(capacites[groupe.id]), 0)
    for animateur in animateurs:
        for groupe in groupes:
            valeur = score(animateur, groupe)
            if valeur is None:
                continue
            aretes_candidats[(animateur.id, groupe.id)] = _ajouter_arete(
                graphe, index_animateur[animateur.id], index_groupe[groupe.id], 1, -int(valeur)
            )

    while True:
        distances = [None] * len(graphe)
        precedent = [None] * len(graphe)
        dans_file = [False] * len(graphe)
        distances[source] = 0
        file = deque([source])
        dans_file[source] = True
        while file:
            sommet = file.popleft()
            dans_file[sommet] = False
            for index, arete in enumerate(graphe[sommet]):
                if arete.capacite <= 0:
                    continue
                nouvelle = distances[sommet] + arete.cout
                if distances[arete.destination] is None or nouvelle < distances[arete.destination]:
                    distances[arete.destination] = nouvelle
                    precedent[arete.destination] = (sommet, index)
                    if not dans_file[arete.destination]:
                        file.append(arete.destination)
                        dans_file[arete.destination] = True
        if distances[puits] is None:
            break
        sommet = puits
        while sommet != source:
            origine, index = precedent[sommet]
            arete = graphe[origine][index]
            arete.capacite -= 1
            graphe[sommet][arete.retour].capacite += 1
            sommet = origine

    par_animateur = {a.id: a for a in animateurs}
    par_groupe = {g.id: g for g in groupes}
    return [
        (par_animateur[animateur_id], par_groupe[groupe_id])
        for (animateur_id, groupe_id), arete in aretes_candidats.items()
        if arete.capacite == 0
    ]


def generer_planning_auto(payload):
    debut_date = parse_date((payload or {}).get("debut", ""))
    if not debut_date:
        return {"error": "Date de début invalide."}, 400

    lundi = debut_date - datetime.timedelta(days=debut_date.weekday())
    jours = [lundi + datetime.timedelta(days=index) for index in range(5)]
    debut_dt = parse_to_aware_datetime(lundi.isoformat())
    fin_dt = parse_to_aware_datetime((lundi + datetime.timedelta(days=5)).isoformat())

    groupes = list(
        groupes_visibles(Evenement.objects.all()).select_related("centre")
        .prefetch_related("dates_exclues", "periodes_scolaires", "besoins_qualifications__qualification")
        .order_by("centre__ordre", "centre__nom", "ordre", "nom", "id")
    )
    animateurs = list(
        Animateur.objects.prefetch_related("disponibilites", "preferences", "qualifications")
        .order_by("prenom", "nom", "id")
    )
    if not groupes:
        return {"error": "Aucun groupe n'est configuré."}, 400
    if not animateurs:
        return {"error": "Aucun animateur n'est configuré."}, 400

    fermetures = {g.id: {item.date for item in g.dates_exclues.all()} for g in groupes}
    groupes_par_jour = {
        jour: [g for g in groupes if g.effectif_cible > 0 and g.est_ouvert_le(jour, fermetures[g.id])]
        for jour in jours
    }
    if not any(groupes_par_jour.values()):
        return {"error": "Aucune place à remplir : vérifie les effectifs et les jours d'ouverture des groupes."}, 400

    statuts_ids = set(Qualification.objects.filter(est_statut=True).values_list("id", flat=True))
    noms = dict(Qualification.objects.values_list("id", "nom"))
    besoins_statuts = {}
    besoins_diplomes = {}
    for groupe in groupes:
        tous = {b.qualification_id: int(b.nombre_minimum) for b in groupe.besoins_qualifications.all() if b.nombre_minimum > 0}
        besoins_statuts[groupe.id] = {identifiant: minimum for identifiant, minimum in tous.items() if identifiant in statuts_ids}
        besoins_diplomes[groupe.id] = {identifiant: minimum for identifiant, minimum in tous.items() if identifiant not in statuts_ids}

    couvertures = couvertures_qualifications()
    qualifications_effectives = {}
    diplomes_possedes = {}
    for animateur in animateurs:
        diplomes = {q.id for q in animateur.qualifications.all() if not q.est_statut}
        diplomes_possedes[animateur.id] = diplomes
        qualifications_effectives[animateur.id] = {
            identifiant
            for diplome_id in diplomes
            for identifiant in couvertures.get(diplome_id, {diplome_id})
        }

    disponibilites = {a.id: list(a.disponibilites.all()) for a in animateurs}
    centres_interdits = {
        a.id: {p.centre_id for p in a.preferences.all() if p.est_interdit}
        for a in animateurs
    }
    centres_preferes = {
        a.id: {p.centre_id for p in a.preferences.all() if p.est_prefere and not p.est_interdit}
        for a in animateurs
    }

    synchroniser_affinites_groupes()
    affinites = {}
    historique_centres = defaultdict(int)
    for animateur_id, groupe_id, centre_id, jours_travailles in AffiniteGroupeAnimateur.objects.values_list(
        "animateur_id", "evenement_id", "evenement__centre_id", "jours_travailles"
    ):
        affinites[(animateur_id, groupe_id)] = int(jours_travailles)
        historique_centres[(animateur_id, centre_id)] += int(jours_travailles)

    rang_animateur = {a.id: index for index, a in enumerate(animateurs)}
    rang_groupe = {g.id: index for index, g in enumerate(groupes)}
    semaine_groupes = defaultdict(int)
    semaine_centres = defaultdict(int)
    groupes_veille = defaultdict(set)
    planning = []
    qualifications_manquantes_total = 0
    details_qualifications = []

    def disponible(animateur, jour):
        return any(plage.debut <= jour <= plage.fin for plage in disponibilites[animateur.id])

    def score_affinite_preferences(animateur, groupe):
        if groupe.centre_id in centres_interdits[animateur.id]:
            return None
        # L'affinité est le premier critère après statuts et diplômes.
        score = min(affinites.get((animateur.id, groupe.id), 0), 9_999) * 1_000_000_000
        if groupe.centre_id in centres_preferes[animateur.id]:
            score += 10_000_000
        if groupe.id in groupes_veille[animateur.id]:
            score += 1_000_000
        score += min(semaine_groupes[(animateur.id, groupe.id)], 4) * 100_000
        score += min(historique_centres[(animateur.id, groupe.centre_id)], 999) * 1_000
        score += min(semaine_centres[(animateur.id, groupe.centre_id)], 4) * 100
        score += len(animateurs) - rang_animateur[animateur.id]
        return score

    def manques(selection, besoins, groupe_id):
        resultat = {}
        for qualification_id, minimum in besoins[groupe_id].items():
            couverts = sum(qualification_id in qualifications_effectives[a.id] for a in selection)
            if couverts < minimum:
                resultat[qualification_id] = minimum - couverts
        return resultat

    for jour in jours:
        groupes_jour = groupes_par_jour[jour]
        disponibles_jour = [a for a in animateurs if disponible(a, jour)]
        utilises = set()
        selections = {g.id: [] for g in groupes_jour}

        def ajouter(animateur, groupe, *, utilises=utilises, selections=selections):
            utilises.add(animateur.id)
            selections[groupe.id].append(animateur)

        def affecter_besoins(
            besoins,
            est_phase_statut,
            *,
            groupes_jour=groupes_jour,
            selections=selections,
            disponibles_jour=disponibles_jour,
            utilises=utilises,
        ):
            while True:
                meilleur = None
                for groupe in groupes_jour:
                    selection = selections[groupe.id]
                    if len(selection) >= groupe.effectif_cible:
                        continue
                    attendus = manques(selection, besoins, groupe.id)
                    if not attendus:
                        continue
                    for animateur in disponibles_jour:
                        if animateur.id in utilises:
                            continue
                        score = score_affinite_preferences(animateur, groupe)
                        if score is None:
                            continue
                        couverts = {qid for qid in attendus if qid in qualifications_effectives[animateur.id]}
                        if not couverts:
                            continue
                        # Pour couvrir un statut, on préserve si possible les
                        # diplômes rares qui seront demandés à l'étape suivante.
                        diplomes_reserves = 0
                        if est_phase_statut:
                            diplomes_reserves = sum(
                                minimum
                                for autre in groupes_jour
                                for qid, minimum in manques(selections[autre.id], besoins_diplomes, autre.id).items()
                                if qid in diplomes_possedes[animateur.id]
                            )
                        valeur = (
                            len(couverts),
                            -diplomes_reserves,
                            score,
                            -rang_groupe[groupe.id],
                            -rang_animateur[animateur.id],
                        )
                        if meilleur is None or valeur > meilleur[0]:
                            meilleur = (valeur, animateur, groupe)
                if meilleur is None:
                    return
                _, animateur, groupe = meilleur
                ajouter(animateur, groupe)

        # Ordre demandé : statuts, diplômes précis, puis affinité.
        affecter_besoins(besoins_statuts, True)
        affecter_besoins(besoins_diplomes, False)

        def capacite_generique(groupe, *, selections=selections):
            restantes = max(0, groupe.effectif_cible - len(selections[groupe.id]))
            manques_restants = {
                **manques(selections[groupe.id], besoins_statuts, groupe.id),
                **manques(selections[groupe.id], besoins_diplomes, groupe.id),
            }
            return max(0, restantes - max(manques_restants.values(), default=0))

        restants = [a for a in disponibles_jour if a.id not in utilises]
        groupes_vides = [g for g in groupes_jour if not selections[g.id] and capacite_generique(g) > 0]
        for animateur, groupe in _meilleure_affectation(
            restants, groupes_vides, {g.id: 1 for g in groupes_vides}, score_affinite_preferences
        ):
            ajouter(animateur, groupe)

        restants = [a for a in disponibles_jour if a.id not in utilises]
        for animateur, groupe in _meilleure_affectation(
            restants, groupes_jour, {g.id: capacite_generique(g) for g in groupes_jour}, score_affinite_preferences
        ):
            ajouter(animateur, groupe)

        groupes_du_jour = defaultdict(set)
        for groupe in groupes_jour:
            selection = selections[groupe.id]
            for animateur in selection:
                planning.append((jour, animateur, groupe))
                semaine_groupes[(animateur.id, groupe.id)] += 1
                semaine_centres[(animateur.id, groupe.centre_id)] += 1
                groupes_du_jour[animateur.id].add(groupe.id)
            tous_manques = {
                **manques(selection, besoins_statuts, groupe.id),
                **manques(selection, besoins_diplomes, groupe.id),
            }
            if tous_manques:
                qualifications_manquantes_total += sum(tous_manques.values())
                libelles = ", ".join(f"{nombre} × {noms.get(qid, 'besoin')}" for qid, nombre in tous_manques.items())
                details_qualifications.append(
                    f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom} : {libelles} manquant(s)"
                )
        groupes_veille = groupes_du_jour

    with transaction.atomic():
        supprimees, _ = Affectation.objects.filter(debut__lt=fin_dt, fin__gt=debut_dt).delete()
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
    synchroniser_affinites_groupes()

    total_places = sum(g.effectif_cible for groupes_jour in groupes_par_jour.values() for g in groupes_jour)
    remplis = defaultdict(int)
    for jour, _, groupe in planning:
        remplis[(jour, groupe.id)] += 1
    details_non_remplis = []
    groupes_complets = groupes_partiels = groupes_vides = 0
    for jour in jours:
        for groupe in groupes_par_jour[jour]:
            nombre = remplis[(jour, groupe.id)]
            manque = groupe.effectif_cible - nombre
            if manque <= 0:
                groupes_complets += 1
            elif nombre:
                groupes_partiels += 1
                details_non_remplis.append(f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom} : {manque} place(s) vide(s)")
            else:
                groupes_vides += 1
                details_non_remplis.append(f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom} : {manque} place(s) vide(s)")

    creees = len(a_creer)
    non_remplies = total_places - creees
    message = (
        f"{creees}/{total_places} place(s) remplie(s), {groupes_complets} groupe(s)-jour complet(s), "
        f"{groupes_partiels} partiel(s) et {groupes_vides} vide(s). {supprimees} ancienne(s) affectation(s) remplacée(s)."
    )
    if qualifications_manquantes_total:
        message += f" {qualifications_manquantes_total} besoin(s) de statut ou diplôme reste(nt) non couvert(s)."
    if non_remplies:
        message += " Les places restantes manquent de salariés disponibles, autorisés ou adaptés aux besoins."

    return {
        "ok": True,
        "created": creees,
        "deleted": supprimees,
        "total_places": total_places,
        "unfilled": non_remplies,
        "animateurs_utilises": len({a.animateur_id for a in a_creer}),
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
