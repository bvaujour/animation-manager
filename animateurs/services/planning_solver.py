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
from django.db.models import Prefetch, Q
from django.utils.dateparse import parse_date

from animateurs.models import (
    Affectation,
    AffiniteGroupeAnimateur,
    Animateur,
    Evenement,
    Formation,
    ModalitePeriscolaire,
    PeriodeCalendrier,
    Qualification,
    TypeAccueil,
)

from .affinites import synchroniser_affinites_groupes
from .affectations import _completer_horaires_periscolaires, _conflit_periscolaire_effectif, _ouverture_periscolaire_pour_date
from .accueils import accueil_actif_le
from .besoins_encadrement import besoin_encadrement_effectif
from .flottants import groupe_flottants_pour_centre, groupes_visibles
from .dates import parse_to_aware_datetime
from .disponibilites import disponibilite_effective
from .parametres import get_parametres_structure
from .reglementation_encadrement import (
    calculer_besoins_centres,
    categorie_legale_statut,
    contraintes_qualification,
)
from .statuts import ids_qualifications_pour_date, prefetch_historiques_statuts, statut_pour_date


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
    payload = payload or {}
    debut_date = parse_date(payload.get("debut", ""))
    if not debut_date:
        return {"error": "Date de début invalide."}, 400

    # Les appels historiques sans contexte conservent strictement le
    # fonctionnement Vacances : tous les groupes visibles sont traités et les
    # affectations de la semaine sont remplacées. L'interface Direction envoie
    # désormais explicitement son type d'accueil pour isoler Vacances et
    # Périscolaire sans dupliquer le solveur.
    contexte_explicit = bool(str(payload.get("type_accueil") or "").strip())
    type_accueil = None
    modalite_periscolaire = None
    if contexte_explicit:
        code_type = str(payload.get("type_accueil") or "").strip()
        type_accueil = TypeAccueil.objects.filter(code=code_type, actif=True).first()
        if type_accueil is None or type_accueil.code not in (TypeAccueil.VACANCES, TypeAccueil.PERISCOLAIRE):
            return {"error": "Type d'accueil invalide pour le remplissage automatique."}, 400
        if type_accueil.code == TypeAccueil.PERISCOLAIRE:
            code_modalite = str(payload.get("modalite_periscolaire") or "").strip()
            if not code_modalite:
                return {"error": "Choisissez un créneau périscolaire avant le remplissage automatique."}, 400
            modalite_periscolaire = ModalitePeriscolaire.objects.filter(code=code_modalite, actif=True).first()
            if modalite_periscolaire is None:
                return {"error": "Créneau périscolaire invalide."}, 400

    periode_calendrier = None
    periode_id = payload.get("periode_calendrier_id")
    if periode_id not in (None, ""):
        try:
            periode_calendrier = PeriodeCalendrier.objects.get(pk=int(periode_id))
        except (TypeError, ValueError, PeriodeCalendrier.DoesNotExist):
            return {"error": "Période de travail invalide."}, 400

    lundi = debut_date - datetime.timedelta(days=debut_date.weekday())
    jours = [lundi + datetime.timedelta(days=index) for index in range(5)]
    debut_dt = parse_to_aware_datetime(lundi.isoformat())
    fin_dt = parse_to_aware_datetime((lundi + datetime.timedelta(days=5)).isoformat())

    groupes_qs = groupes_visibles(Evenement.objects.all()).select_related(
        "centre", "groupe", "accueil_centre", "accueil_centre__type_accueil"
    ).prefetch_related(
        "dates_exclues",
        "periodes_scolaires",
        "types_accueil",
        "besoins_encadrement__type_accueil",
        "besoins_encadrement__modalite_periscolaire",
        "besoins_encadrement__periode_calendrier",
        "besoins_qualifications__qualification",
    )
    if contexte_explicit:
        # Le solveur doit remplir exactement les groupes visibles dans le
        # contexte sélectionné, jamais une instance appartenant à un autre
        # type d'accueil. Les appels historiques sans contexte restent, eux,
        # entièrement rétrocompatibles.
        groupes_qs = groupes_qs.filter(
            Q(accueil_centre__type_accueil=type_accueil)
            | Q(accueil_centre__isnull=True, types_accueil=type_accueil)
        ).distinct()
    groupes = list(groupes_qs.order_by("centre__ordre", "centre__nom", "ordre", "nom", "id"))

    animateurs_queryset = Animateur.objects.prefetch_related(
        "disponibilites",
        "preferences",
        "qualifications",
        Prefetch(
            "formations",
            queryset=Formation.objects.filter(
                statut__in=(Formation.STATUT_PREVUE, Formation.STATUT_EN_COURS),
                date_debut__lte=jours[-1],
                date_fin__gte=jours[0],
            ),
            to_attr="formations_bloquantes",
        ),
    ).order_by("prenom", "nom", "id")
    animateurs = list(prefetch_historiques_statuts(animateurs_queryset, date_fin=jours[-1]))
    if not groupes:
        return {"error": "Aucun groupe n'est configuré pour ce contexte."}, 400
    if not animateurs:
        return {"error": "Aucun animateur n'est configuré."}, 400

    def periode_pour_jour(jour):
        if periode_calendrier is not None and periode_calendrier.debut <= jour <= periode_calendrier.fin:
            return periode_calendrier
        if type_accueil is None:
            return None
        categorie = (
            PeriodeCalendrier.SCOLAIRE
            if type_accueil.code == TypeAccueil.PERISCOLAIRE
            else PeriodeCalendrier.VACANCES
        )
        return (
            PeriodeCalendrier.objects.filter(categorie=categorie, debut__lte=jour, fin__gte=jour)
            .order_by("-debut", "id")
            .first()
        )

    periodes_par_jour = {jour: periode_pour_jour(jour) for jour in jours}
    fermetures = {g.id: {item.date for item in g.dates_exclues.all()} for g in groupes}

    # Le besoin est résolu groupe ET jour. En contexte explicite, le moteur
    # distingue désormais le minimum réglementaire, les renforts volontaires
    # et l'éventuel poste « mixte » qui mutualise les reliquats d'âge du lieu.
    besoins_effectifs = {}
    effectifs_cibles = {}
    cibles_reglementaires_directes = {}
    cibles_renforts = {}
    postes_mixtes = defaultdict(int)
    contributions_mixtes = {}
    besoins_centres_par_jour = {}
    groupes_par_jour = {}
    groupes_non_configures = []

    for jour in jours:
        ouverts_bruts = []
        for groupe in groupes:
            if contexte_explicit and not accueil_actif_le(groupe.centre, type_accueil, jour):
                continue
            if not groupe.est_ouvert_le(jour, fermetures[groupe.id]):
                continue
            if contexte_explicit and type_accueil.code == TypeAccueil.PERISCOLAIRE:
                ouvert, _heure_debut, _heure_fin = _ouverture_periscolaire_pour_date(
                    groupe.centre,
                    jour,
                    modalite_periscolaire,
                    groupe.accueil_centre,
                )
                if not ouvert:
                    continue
            besoin = besoin_encadrement_effectif(
                groupe,
                type_accueil=type_accueil,
                modalite=modalite_periscolaire,
                periode_calendrier=periodes_par_jour[jour],
            )
            besoins_effectifs[(groupe.id, jour)] = besoin
            ouverts_bruts.append(groupe)

        if contexte_explicit:
            calculs = calculer_besoins_centres(
                ouverts_bruts,
                jour,
                type_accueil=type_accueil,
                modalite=modalite_periscolaire,
                periode_calendrier=periodes_par_jour[jour],
                besoins_effectifs=besoins_effectifs,
            )
            besoins_centres_par_jour[jour] = calculs
            ouverts = []
            for resultat_centre in calculs.values():
                for groupe_id in resultat_centre.non_configures:
                    groupe = next((item for item in ouverts_bruts if item.id == groupe_id), None)
                    if groupe is not None:
                        groupes_non_configures.append(
                            f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom}"
                        )
                for groupe_id, calcule in resultat_centre.groupes.items():
                    cibles_reglementaires_directes[(groupe_id, jour)] = max(
                        0, int(calcule.postes_reglementaires_directs)
                    )
                    cibles_renforts[(groupe_id, jour)] = max(0, int(calcule.renforts_souhaites))
                    effectifs_cibles[(groupe_id, jour)] = max(
                        0, int(calcule.postes_operationnels_directs)
                    )
                    if effectifs_cibles[(groupe_id, jour)] > 0:
                        ouverts.append(calcule.evenement)
                postes_mixtes[(resultat_centre.centre_id, jour)] = max(
                    0, int(resultat_centre.postes_mixtes)
                )
                contributions_mixtes[(resultat_centre.centre_id, jour)] = list(
                    resultat_centre.contributions_mixtes
                )
            # Un lieu peut n'avoir que son poste mixte : conserver alors ses
            # groupes visibles pour le score d'affinité et l'affichage.
            centres_avec_mixte = {
                centre_id for (centre_id, date), nombre in postes_mixtes.items()
                if date == jour and nombre > 0
            }
            for groupe in ouverts_bruts:
                if groupe.centre_id in centres_avec_mixte and groupe not in ouverts:
                    ouverts.append(groupe)
        else:
            ouverts = []
            for groupe in ouverts_bruts:
                besoin = besoins_effectifs[(groupe.id, jour)]
                cible = max(0, int(besoin.effectif_cible))
                effectifs_cibles[(groupe.id, jour)] = cible
                cibles_reglementaires_directes[(groupe.id, jour)] = cible
                cibles_renforts[(groupe.id, jour)] = 0
                if cible > 0:
                    ouverts.append(groupe)
        groupes_par_jour[jour] = ouverts

    if groupes_non_configures:
        details = "; ".join(dict.fromkeys(groupes_non_configures[:8]))
        suffixe = "…" if len(groupes_non_configures) > 8 else ""
        return {
            "error": (
                "Les besoins d’encadrement ne sont pas complètement configurés pour ce contexte. "
                f"Complète-les dans Configuration → Centres : {details}{suffixe}"
            )
        }, 400

    if not any(groupes_par_jour.values()) and not any(postes_mixtes.values()):
        return {"error": "Aucune place à remplir : vérifie les besoins et les jours/créneaux d'ouverture des groupes."}, 400

    statuts_ids = set(Qualification.objects.filter(est_statut=True).values_list("id", flat=True))
    noms = dict(Qualification.objects.values_list("id", "nom"))
    besoins_statuts = {}
    besoins_diplomes = {}
    for jour in jours:
        for groupe in groupes_par_jour[jour]:
            tous = {
                b.qualification_id: int(b.nombre_minimum)
                for b in besoins_effectifs[(groupe.id, jour)].qualifications
                if b.nombre_minimum > 0
            }
            besoins_statuts[(groupe.id, jour)] = {
                identifiant: minimum for identifiant, minimum in tous.items() if identifiant in statuts_ids
            }
            besoins_diplomes[(groupe.id, jour)] = {
                identifiant: minimum for identifiant, minimum in tous.items() if identifiant not in statuts_ids
            }

    qualifications_effectives = {}
    diplomes_possedes = {}
    categories_legales = {}
    structure = get_parametres_structure()
    for animateur in animateurs:
        qualifications = list(animateur.qualifications.all())
        diplomes_possedes[animateur.id] = {q.id for q in qualifications if not q.est_statut}
        for jour in jours:
            qualifications_effectives[(animateur.id, jour)] = ids_qualifications_pour_date(
                animateur, jour, qualifications=qualifications
            )
            categories_legales[(animateur.id, jour)] = categorie_legale_statut(
                statut_pour_date(animateur, jour), structure=structure
            )

    disponibilites = {a.id: list(a.disponibilites.all()) for a in animateurs}
    centres_interdits = {
        a.id: {p.centre_id for p in a.preferences.all() if p.est_interdit}
        for a in animateurs
    }
    centres_preferes = {
        a.id: {p.centre_id for p in a.preferences.all() if p.est_prefere and not p.est_interdit}
        for a in animateurs
    }

    # En contexte explicite, seules les affectations du contexte courant seront
    # remplacées. Les autres restent donc des contraintes : une journée
    # Vacances bloque le Périscolaire et deux créneaux périscolaires ne peuvent
    # cohabiter que si leurs horaires ne se chevauchent pas.
    affectations_semaine = Affectation.objects.select_related(
        "centre", "type_accueil", "modalite_periscolaire"
    ).filter(debut__lt=fin_dt, fin__gt=debut_dt)
    if contexte_explicit:
        if type_accueil.code == TypeAccueil.PERISCOLAIRE:
            contexte_a_remplacer = Q(
                type_accueil=type_accueil,
                modalite_periscolaire=modalite_periscolaire,
            ) | Q(
                type_accueil__isnull=True,
                modalite_periscolaire=modalite_periscolaire,
            )
        else:
            contexte_a_remplacer = Q(type_accueil=type_accueil) | Q(
                type_accueil__isnull=True,
                modalite_periscolaire__isnull=True,
            )
        affectations_bloquantes = list(affectations_semaine.exclude(contexte_a_remplacer))
    else:
        contexte_a_remplacer = None
        affectations_bloquantes = []
    bloquantes_par_animateur = defaultdict(list)
    for affectation in affectations_bloquantes:
        bloquantes_par_animateur[affectation.animateur_id].append(affectation)

    def conflit_autre_contexte(animateur, groupe, jour):
        if not contexte_explicit:
            return False
        debut_jour = parse_to_aware_datetime(jour.isoformat())
        fin_jour = parse_to_aware_datetime((jour + datetime.timedelta(days=1)).isoformat())
        for existante in bloquantes_par_animateur.get(animateur.id, ()):
            if not (existante.debut < fin_jour and existante.fin > debut_jour):
                continue
            if type_accueil.code != TypeAccueil.PERISCOLAIRE:
                return True
            if _conflit_periscolaire_effectif(
                existante,
                centre=groupe.centre,
                debut=debut_jour,
                fin=fin_jour,
                type_accueil=type_accueil,
                modalite_periscolaire=modalite_periscolaire,
            ):
                return True
        return False

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
        return disponibilite_effective(
            animateur,
            jour,
            plages=disponibilites[animateur.id],
            formations=animateur.formations_bloquantes,
        ).disponible

    # ``jour_courant`` est mis à jour dans la boucle afin que le score puisse
    # vérifier les affectations conservées dans d'autres contextes.
    jour_courant = jours[0]

    def score_affinite_preferences(animateur, groupe):
        if groupe.centre_id in centres_interdits[animateur.id]:
            return None
        if conflit_autre_contexte(animateur, groupe, jour_courant):
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

    def manques(selection, besoins, groupe_id, jour):
        resultat = {}
        for qualification_id, minimum in besoins.get((groupe_id, jour), {}).items():
            couverts = sum(
                qualification_id in qualifications_effectives[(a.id, jour)] for a in selection
            )
            if couverts < minimum:
                resultat[qualification_id] = minimum - couverts
        return resultat

    details_reglementaires = []
    non_conformites_reglementaires = 0
    mixtes_planifies = 0
    mixtes_remplis = defaultdict(int)

    for jour in jours:
        jour_courant = jour
        groupes_jour = groupes_par_jour[jour]
        disponibles_jour = [a for a in animateurs if disponible(a, jour)]
        utilises = set()
        selections = {g.id: [] for g in groupes_jour}
        selections_mixtes = defaultdict(list)
        contributions_groupes_mixtes = defaultdict(list)

        contraintes_par_centre = {}
        if contexte_explicit:
            for centre_id, resultat in besoins_centres_par_jour.get(jour, {}).items():
                contraintes_par_centre[centre_id] = contraintes_qualification(
                    resultat.effectif_reglementaire_requis, structure=structure
                )

        def ajouter(animateur, groupe, *, utilises=utilises, selections=selections):
            utilises.add(animateur.id)
            selections[groupe.id].append(animateur)

        def selections_reglementaires_centre(centre_id):
            personnes = []
            for groupe in groupes_jour:
                if groupe.centre_id != centre_id:
                    continue
                limite = cibles_reglementaires_directes.get((groupe.id, jour), 0)
                personnes.extend(selections[groupe.id][:limite])
            personnes.extend(selections_mixtes.get(centre_id, ()))
            return personnes

        def stats_legaux_centre(centre_id):
            personnes = selections_reglementaires_centre(centre_id)
            categories = [categories_legales.get((animateur.id, jour), "inconnu") for animateur in personnes]
            return {
                "total": len(personnes),
                "diplomes": categories.count("diplome"),
                "stagiaires": categories.count("stagiaire"),
                "non_diplomes": categories.count("non_diplome"),
                "inconnus": categories.count("inconnu"),
            }

        def rang_legal_candidat(animateur, centre_id):
            """Priorise la conformité sans faire peser les quotas sur les renforts."""

            if not contexte_explicit:
                return 1
            contrainte = contraintes_par_centre.get(centre_id)
            if not contrainte or contrainte["effectif_requis"] <= 0:
                return 1
            stats = stats_legaux_centre(centre_id)
            categorie = categories_legales.get((animateur.id, jour), "inconnu")
            if categorie == "non_diplome" and stats["non_diplomes"] >= contrainte["maximum_non_diplomes"]:
                return None
            manque_diplomes = max(0, contrainte["minimum_diplomes"] - stats["diplomes"])
            if manque_diplomes:
                return {"diplome": 4, "stagiaire": 2, "inconnu": 1, "non_diplome": 0}.get(categorie, 1)
            return {"diplome": 3, "stagiaire": 3, "inconnu": 2, "non_diplome": 1}.get(categorie, 2)

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
                    # En contexte typé, les exigences spécifiques sont portées
                    # par le socle requis. Les renforts restent volontairement
                    # libres et ne modifient pas la conformité réglementaire.
                    limite = (
                        cibles_reglementaires_directes.get((groupe.id, jour), 0)
                        if contexte_explicit
                        else effectifs_cibles.get((groupe.id, jour), 0)
                    )
                    if len(selection) >= limite:
                        continue
                    attendus = manques(selection, besoins, groupe.id, jour)
                    if not attendus:
                        continue
                    for animateur in disponibles_jour:
                        if animateur.id in utilises:
                            continue
                        score = score_affinite_preferences(animateur, groupe)
                        if score is None:
                            continue
                        legal = rang_legal_candidat(animateur, groupe.centre_id)
                        if legal is None:
                            continue
                        couverts = {
                            qid for qid in attendus
                            if qid in qualifications_effectives[(animateur.id, jour)]
                        }
                        if not couverts:
                            continue
                        # Pour couvrir un statut, on préserve si possible les
                        # diplômes rares qui seront demandés à l'étape suivante.
                        diplomes_reserves = 0
                        if est_phase_statut:
                            diplomes_reserves = sum(
                                minimum
                                for autre in groupes_jour
                                for qid, minimum in manques(
                                    selections[autre.id], besoins_diplomes, autre.id, jour
                                ).items()
                                if qid in diplomes_possedes[animateur.id]
                            )
                        valeur = (
                            len(couverts),
                            legal,
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

        # Les besoins métier explicites restent prioritaires, comme auparavant.
        affecter_besoins(besoins_statuts, True)
        affecter_besoins(besoins_diplomes, False)

        if contexte_explicit:
            # Complète d'abord les postes réglementaires directs. Le statut
            # existant est un critère prioritaire ; les non diplômés sont écartés
            # lorsque leur plafond réglementaire est déjà atteint.
            while True:
                meilleur = None
                for groupe in groupes_jour:
                    cible_reglementaire = cibles_reglementaires_directes.get((groupe.id, jour), 0)
                    if len(selections[groupe.id]) >= cible_reglementaire:
                        continue
                    for animateur in disponibles_jour:
                        if animateur.id in utilises:
                            continue
                        score = score_affinite_preferences(animateur, groupe)
                        if score is None:
                            continue
                        legal = rang_legal_candidat(animateur, groupe.centre_id)
                        if legal is None:
                            continue
                        valeur = (
                            1 if not selections[groupe.id] else 0,
                            legal,
                            score,
                            -rang_groupe[groupe.id],
                            -rang_animateur[animateur.id],
                        )
                        if meilleur is None or valeur > meilleur[0]:
                            meilleur = (valeur, animateur, groupe)
                if meilleur is None:
                    break
                _, animateur, groupe = meilleur
                ajouter(animateur, groupe)

            # Les reliquats de plusieurs groupes d'âge utilisent le dispositif
            # technique historique « flottant », désormais présenté comme
            # animateur mixte. Il couvre au taux le plus restrictif du lieu.
            for centre_id, nombre_mixte in sorted(
                ((centre_id, nombre) for (centre_id, date), nombre in postes_mixtes.items() if date == jour),
                key=lambda item: item[0],
            ):
                if nombre_mixte <= 0:
                    continue
                groupes_centre = [groupe for groupe in groupes_jour if groupe.centre_id == centre_id]
                if not groupes_centre:
                    continue
                contributions = contributions_mixtes.get((centre_id, jour), [])
                qualifications_contributrices = set()
                for contribution in contributions:
                    for detail in contribution.get("groupes", []):
                        groupe_id = int(detail.get("evenement_id") or 0)
                        if groupe_id:
                            qualifications_contributrices.update(besoins_statuts.get((groupe_id, jour), {}))
                            qualifications_contributrices.update(besoins_diplomes.get((groupe_id, jour), {}))

                for index_mixte in range(nombre_mixte):
                    meilleur = None
                    for animateur in disponibles_jour:
                        if animateur.id in utilises:
                            continue
                        scores = [score_affinite_preferences(animateur, groupe) for groupe in groupes_centre]
                        scores = [score for score in scores if score is not None]
                        if not scores:
                            continue
                        legal = rang_legal_candidat(animateur, centre_id)
                        if legal is None:
                            continue
                        couverture_specifique = sum(
                            qid in qualifications_effectives[(animateur.id, jour)]
                            for qid in qualifications_contributrices
                        )
                        valeur = (
                            legal,
                            couverture_specifique,
                            max(scores),
                            -rang_animateur[animateur.id],
                        )
                        if meilleur is None or valeur > meilleur[0]:
                            meilleur = (valeur, animateur)
                    if meilleur is None:
                        break
                    _, animateur = meilleur
                    groupe_mixte = groupe_flottants_pour_centre(groupes_centre[0].centre)
                    utilises.add(animateur.id)
                    selections_mixtes[centre_id].append(animateur)
                    planning.append((jour, animateur, groupe_mixte))
                    semaine_groupes[(animateur.id, groupe_mixte.id)] += 1
                    semaine_centres[(animateur.id, centre_id)] += 1
                    mixtes_planifies += 1
                    mixtes_remplis[(centre_id, jour)] += 1
                    if index_mixte < len(contributions):
                        for detail in contributions[index_mixte].get("groupes", []):
                            groupe_id = int(detail.get("evenement_id") or 0)
                            if groupe_id:
                                contributions_groupes_mixtes[groupe_id].append(animateur)

            # Les renforts sont volontairement affectés après constitution du
            # socle réglementaire. Leur statut n'entre donc pas dans les quotas.
            restants = [a for a in disponibles_jour if a.id not in utilises]
            for animateur, groupe in _meilleure_affectation(
                restants,
                groupes_jour,
                {
                    g.id: max(0, effectifs_cibles.get((g.id, jour), 0) - len(selections[g.id]))
                    for g in groupes_jour
                },
                score_affinite_preferences,
            ):
                ajouter(animateur, groupe)
        else:
            # Compatibilité stricte du remplissage historique sans contexte.
            def capacite_generique(groupe, *, selections=selections):
                restantes = max(0, effectifs_cibles[(groupe.id, jour)] - len(selections[groupe.id]))
                manques_restants = {
                    **manques(selections[groupe.id], besoins_statuts, groupe.id, jour),
                    **manques(selections[groupe.id], besoins_diplomes, groupe.id, jour),
                }
                return max(0, restantes - max(manques_restants.values(), default=0))

            restants = [a for a in disponibles_jour if a.id not in utilises]
            groupes_vides_jour = [g for g in groupes_jour if not selections[g.id] and capacite_generique(g) > 0]
            for animateur, groupe in _meilleure_affectation(
                restants,
                groupes_vides_jour,
                {g.id: 1 for g in groupes_vides_jour},
                score_affinite_preferences,
            ):
                ajouter(animateur, groupe)

            restants = [a for a in disponibles_jour if a.id not in utilises]
            for animateur, groupe in _meilleure_affectation(
                restants,
                groupes_jour,
                {g.id: capacite_generique(g) for g in groupes_jour},
                score_affinite_preferences,
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
            selection_qualification = selection + contributions_groupes_mixtes.get(groupe.id, [])
            tous_manques = {
                **manques(selection_qualification, besoins_statuts, groupe.id, jour),
                **manques(selection_qualification, besoins_diplomes, groupe.id, jour),
            }
            if tous_manques:
                qualifications_manquantes_total += sum(tous_manques.values())
                libelles = ", ".join(
                    f"{nombre} × {noms.get(qid, 'besoin')}" for qid, nombre in tous_manques.items()
                )
                details_qualifications.append(
                    f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom} : {libelles} manquant(s)"
                )

        if contexte_explicit:
            centres_du_jour = {groupe.centre_id: groupe.centre for groupe in groupes_jour}
            for centre_id, centre in centres_du_jour.items():
                contrainte = contraintes_par_centre.get(centre_id)
                if not contrainte or contrainte["effectif_requis"] <= 0:
                    continue
                stats = stats_legaux_centre(centre_id)
                anomalies = []
                if stats["total"] < contrainte["effectif_requis"]:
                    anomalies.append(
                        f"{contrainte['effectif_requis'] - stats['total']} poste(s) réglementaire(s) non pourvu(s)"
                    )
                if stats["diplomes"] < contrainte["minimum_diplomes"]:
                    anomalies.append(
                        f"{contrainte['minimum_diplomes'] - stats['diplomes']} diplômé(s) manquant(s)"
                    )
                if stats["non_diplomes"] > contrainte["maximum_non_diplomes"]:
                    anomalies.append("trop de non diplômés dans le socle réglementaire")
                if stats["inconnus"]:
                    anomalies.append(
                        f"{stats['inconnus']} statut(s) non reconnu(s) comme Diplômé / Stagiaire / Non diplômé"
                    )
                if anomalies:
                    non_conformites_reglementaires += 1
                    details_reglementaires.append(
                        f"{jour.strftime('%d/%m')} - {centre.code} : " + ", ".join(anomalies)
                    )

        # Un animateur mixte prolonge la continuité du lieu ; pour l'affinité
        # de groupe du lendemain, on retient les groupes qu'il a réellement aidés.
        for groupe_id, animateurs_mixtes in contributions_groupes_mixtes.items():
            for animateur in animateurs_mixtes:
                groupes_du_jour[animateur.id].add(groupe_id)
        groupes_veille = groupes_du_jour
    with transaction.atomic():
        if contexte_explicit:
            supprimees, _ = affectations_semaine.filter(contexte_a_remplacer).delete()
        else:
            supprimees, _ = affectations_semaine.delete()
        a_creer = []
        for jour, animateur, groupe in planning:
            affectation = Affectation.objects.create(
                animateur=animateur,
                centre=groupe.centre,
                evenement=groupe,
                debut=parse_to_aware_datetime(jour.isoformat()),
                fin=parse_to_aware_datetime((jour + datetime.timedelta(days=1)).isoformat()),
                type_accueil=type_accueil if contexte_explicit else None,
                modalite_periscolaire=(
                    modalite_periscolaire
                    if contexte_explicit and type_accueil.code == TypeAccueil.PERISCOLAIRE
                    else None
                ),
            )
            if contexte_explicit and type_accueil.code == TypeAccueil.PERISCOLAIRE:
                _completer_horaires_periscolaires(affectation)
            a_creer.append(affectation)
    synchroniser_affinites_groupes()

    total_places_directes = sum(
        effectifs_cibles.get((g.id, jour), 0)
        for jour, groupes_jour in groupes_par_jour.items()
        for g in groupes_jour
    )
    total_places_mixtes = sum(postes_mixtes.values()) if contexte_explicit else 0
    total_places = total_places_directes + total_places_mixtes
    remplis = defaultdict(int)
    for jour, _, groupe in planning:
        remplis[(jour, groupe.id)] += 1
    details_non_remplis = []
    groupes_complets = groupes_partiels = groupes_vides = 0
    for jour in jours:
        for groupe in groupes_par_jour[jour]:
            cible = effectifs_cibles.get((groupe.id, jour), 0)
            if cible <= 0:
                continue
            nombre = remplis[(jour, groupe.id)]
            manque = cible - nombre
            if manque <= 0:
                groupes_complets += 1
            elif nombre:
                groupes_partiels += 1
                details_non_remplis.append(
                    f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom} : {manque} place(s) vide(s)"
                )
            else:
                groupes_vides += 1
                details_non_remplis.append(
                    f"{jour.strftime('%d/%m')} - {groupe.centre.code} / {groupe.nom} : {manque} place(s) vide(s)"
                )
        if contexte_explicit:
            centres = {groupe.centre_id: groupe.centre for groupe in groupes_par_jour[jour]}
            for centre_id, centre in centres.items():
                attendu = postes_mixtes.get((centre_id, jour), 0)
                manque_mixte = max(0, attendu - mixtes_remplis.get((centre_id, jour), 0))
                if manque_mixte:
                    details_non_remplis.append(
                        f"{jour.strftime('%d/%m')} - {centre.code} : {manque_mixte} poste(s) d’animateur mixte non pourvu(s)"
                    )

    creees = len(a_creer)
    non_remplies = total_places - creees
    contexte_message = ""
    if contexte_explicit and type_accueil.code == TypeAccueil.PERISCOLAIRE:
        contexte_message = f" pour « {modalite_periscolaire.nom} »"
    message = (
        f"{creees}/{total_places} place(s) remplie(s){contexte_message}, "
        f"{groupes_complets} groupe(s)-jour complet(s), {groupes_partiels} partiel(s) "
        f"et {groupes_vides} vide(s). {supprimees} ancienne(s) affectation(s) remplacée(s)."
    )
    if mixtes_planifies:
        message += f" {mixtes_planifies} poste(s) d’animateur mixte utilisé(s) pour mutualiser les reliquats d’enfants."
    if qualifications_manquantes_total:
        message += f" {qualifications_manquantes_total} besoin(s) de statut ou diplôme reste(nt) non couvert(s)."
    if non_conformites_reglementaires:
        message += f" {non_conformites_reglementaires} contrôle(s) réglementaire(s) restent à vérifier."
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
        "postes_mixtes": total_places_mixtes,
        "postes_mixtes_pourvus": mixtes_planifies,
        "non_conformites_reglementaires": non_conformites_reglementaires,
        "details_reglementaires": details_reglementaires[:50],
        "interrompu": False,
        "appels": 0,
        "details_non_remplis": details_non_remplis[:50],
        "details_qualifications": details_qualifications[:50],
        "message": message,
    }, 200
