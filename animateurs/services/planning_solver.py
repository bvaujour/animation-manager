"""Solveur de remplissage automatique du planning par groupe.

Le solveur travaille sur des groupes ``jour + groupe``. Les qualifications
sont vérifiées sur l'ensemble des animateurs retenus dans le groupe : une même
personne peut donc couvrir simultanément plusieurs exigences (par exemple BAFA
et permis), tandis qu'une exigence ``2 BAFA`` nécessite bien deux titulaires.
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from django.db import transaction
from django.utils.dateparse import parse_date

from animateurs.models import Affectation, Animateur, Centre, Evenement, Qualification
from .dates import parse_to_aware_datetime


def _evenements_se_chevauchent(evenement_a, evenement_b):
    """La gestion est exclusivement à la journée : deux affectations le même jour sont toujours en conflit."""
    return True


def generer_planning_auto(payload):
    """Remplit la semaine affichée du lundi au vendredi, groupe par groupe.

    Priorités du score :
      1. remplir le plus de places ;
      2. remplir complètement le plus de groupes jour/groupe ;
      3. respecter le groupe préféré, puis le centre préféré ;
      4. conserver les mêmes personnes dans la même groupe sur la semaine ;
      5. limiter la rotation globale.

    Contraintes strictes : disponibilité, lieu autorisé,
    absence de double affectation le même jour et couverture complète des
    qualifications demandées pour chaque groupe non vide.
    """

    data = payload or {}
    debut_date = parse_date(data.get("debut", ""))
    if not debut_date:
        return {"error": "Date de début invalide."}, 400

    lundi = debut_date - datetime.timedelta(days=debut_date.weekday())
    jours = [lundi + datetime.timedelta(days=i) for i in range(5)]
    samedi = lundi + datetime.timedelta(days=5)
    debut_dt = parse_to_aware_datetime(lundi.isoformat())
    fin_dt = parse_to_aware_datetime(samedi.isoformat())

    centres = list(Centre.objects.all().order_by("nom"))
    groupes_configures = list(
        Evenement.objects.select_related("centre").prefetch_related("besoins_qualifications", "dates_exclues", "periodes_scolaires")
        .order_by("centre__nom", "ordre", "nom")
    )
    animateurs = list(
        Animateur.objects.select_related("evenement_preferee")
        .prefetch_related("disponibilites", "preferences", "qualifications")
        .order_by("prenom", "nom")
    )

    if not centres:
        return {"error": "Aucun centre n'est configuré."}, 400
    if not groupes_configures:
        return {"error": "Aucun groupe avec une période ouverte n’est configuré."}, 400
    if not animateurs:
        return {"error": "Aucun animateur n'est configuré."}, 400

    qualifs_existantes = set(Qualification.objects.values_list("id", flat=True))

    besoins = {}
    for evenement in groupes_configures:
        qualifs = {
            besoin.qualification_id: besoin.nombre_minimum
            for besoin in evenement.besoins_qualifications.all()
            if besoin.qualification_id in qualifs_existantes
        }
        besoins[evenement.id] = (evenement.effectif_cible, qualifs)

    dates_exclues_par_evenement = {
        evenement.id: {fermeture.date for fermeture in evenement.dates_exclues.all()}
        for evenement in groupes_configures
    }

    groupes = []
    for jour in jours:
        for evenement in groupes_configures:
            if not evenement.est_ouvert_le(
                jour, dates_exclues_par_evenement[evenement.id]
            ):
                continue
            effectif, qualifs = besoins[evenement.id]
            if effectif <= 0:
                continue
            groupes.append({
                "jour": jour,
                "evenement": evenement,
                "centre": evenement.centre,
                "effectif": effectif,
                "qualifs": qualifs,
            })

    if not groupes:
        return {"error": "Aucune place à remplir : vérifie les effectifs des groupes."}, 400

    qualifs_animateur = {
        animateur.id: {q.id for q in animateur.qualifications.all()}
        for animateur in animateurs
    }
    centres_autorises = {
        animateur.id: {pref.centre_id for pref in animateur.preferences.all()}
        for animateur in animateurs
    }
    centres_preferes = {
        animateur.id: next(
            (pref.centre_id for pref in animateur.preferences.all() if pref.est_prefere),
            None,
        )
        for animateur in animateurs
    }
    evenements_preferees = {
        animateur.id: animateur.evenement_preferee_id
        for animateur in animateurs
    }
    disponibilites = {
        animateur.id: list(animateur.disponibilites.all())
        for animateur in animateurs
    }

    def disponible(animateur, jour):
        plages = disponibilites[animateur.id]
        return bool(plages) and any(p.debut <= jour <= p.fin for p in plages)

    def centre_autorise(animateur, centre_id):
        return centre_id in centres_autorises.get(animateur.id, set())

    nb_titulaires = defaultdict(int)
    for ids in qualifs_animateur.values():
        for qid in ids:
            nb_titulaires[qid] += 1

    # Candidats théoriques par groupe. Le filtrage des conflits horaires est
    # effectué dynamiquement pendant la recherche.
    for groupe in groupes:
        groupe["candidats"] = [
            animateur for animateur in animateurs
            if disponible(animateur, groupe["jour"])
            and centre_autorise(animateur, groupe["centre"].id)
        ]

    # Jour après jour, et d'abord les groupes les plus contraintes du jour.
    groupes.sort(key=lambda groupe: (
        groupe["jour"],
        len(groupe["candidats"]),
        min((nb_titulaires[qid] for qid in groupe["qualifs"]), default=9999),
        groupe["centre"].nom,
        groupe["evenement"].ordre,
        groupe["evenement"].nom,
    ))

    deadline = datetime.datetime.now() + datetime.timedelta(seconds=3.5)
    interrompu = False
    appels = 0

    choix = [tuple() for _ in groupes]
    meilleur_choix = [tuple() for _ in groupes]
    meilleur_score = None

    # jour -> animateur_id -> groupes déjà attribuées ce jour
    occupation = {jour: defaultdict(list) for jour in jours}
    placements_par_animateur = defaultdict(int)
    placements_par_anim_evenement = defaultdict(int)
    placements_par_anim_centre = defaultdict(int)

    def conflit(animateur, groupe):
        return any(
            _evenements_se_chevauchent(groupe["evenement"], autre_evenement)
            for autre_evenement in occupation[groupe["jour"]].get(animateur.id, [])
        )

    def qualifications_couvertes(groupe, selection):
        for qid, minimum in groupe["qualifs"].items():
            nb = sum(1 for animateur in selection if qid in qualifs_animateur[animateur.id])
            if nb < minimum:
                return False
        return True

    def score_solution():
        remplissage = sum(len(selection) for selection in choix)
        groupes_complets = sum(
            1 for groupe, selection in zip(groupes, choix)
            if len(selection) == groupe["effectif"]
        )
        placements_evenement_preferee = 0
        placements_centre_prefere = 0
        continuite_evenement = 0
        continuite_centre = 0
        continuite_consecutive = 0
        jours_par_anim_evenement = defaultdict(set)

        for groupe, selection in zip(groupes, choix):
            for animateur in selection:
                if evenements_preferees.get(animateur.id) == groupe["evenement"].id:
                    placements_evenement_preferee += 1
                if centres_preferes.get(animateur.id) == groupe["centre"].id:
                    placements_centre_prefere += 1
                jours_par_anim_evenement[(animateur.id, groupe["evenement"].id)].add(groupe["jour"])

        for nb in placements_par_anim_evenement.values():
            continuite_evenement += max(0, nb - 1)
        for nb in placements_par_anim_centre.values():
            continuite_centre += max(0, nb - 1)
        for jours_set in jours_par_anim_evenement.values():
            for jour in jours_set:
                if jour - datetime.timedelta(days=1) in jours_set:
                    continuite_consecutive += 1

        utilises = sum(1 for nb in placements_par_animateur.values() if nb > 0)
        charges = [nb for nb in placements_par_animateur.values() if nb > 0]
        ecart = (max(charges) - min(charges)) if charges else 0

        return (
            remplissage,
            groupes_complets,
            placements_evenement_preferee,
            placements_centre_prefere,
            continuite_evenement,
            continuite_consecutive,
            continuite_centre,
            -utilises,
            -ecart,
        )

    def memoriser():
        nonlocal meilleur_score, meilleur_choix
        score = score_solution()
        if meilleur_score is None or score > meilleur_score:
            meilleur_score = score
            meilleur_choix = [tuple(selection) for selection in choix]

    def appliquer_selection(groupe, selection, sens):
        for animateur in selection:
            if sens > 0:
                occupation[groupe["jour"]][animateur.id].append(groupe["evenement"])
            else:
                occupation[groupe["jour"]][animateur.id].remove(groupe["evenement"])
                if not occupation[groupe["jour"]][animateur.id]:
                    del occupation[groupe["jour"]][animateur.id]
            placements_par_animateur[animateur.id] += sens
            placements_par_anim_evenement[(animateur.id, groupe["evenement"].id)] += sens
            placements_par_anim_centre[(animateur.id, groupe["centre"].id)] += sens

    def candidats_ordonnes(groupe):
        candidats = [a for a in groupe["candidats"] if not conflit(a, groupe)]
        jour_precedent = groupe["jour"] - datetime.timedelta(days=1)

        def travaille_veille_meme_evenement(animateur):
            for autre_groupe, selection in zip(groupes, choix):
                if autre_groupe["jour"] != jour_precedent:
                    continue
                if autre_groupe["evenement"].id != groupe["evenement"].id:
                    continue
                if any(a.id == animateur.id for a in selection):
                    return True
            return False

        def utilite_qualifs(animateur):
            return sum(
                1 for qid in groupe["qualifs"]
                if qid in qualifs_animateur[animateur.id]
            )

        candidats.sort(key=lambda animateur: (
            0 if evenements_preferees.get(animateur.id) == groupe["evenement"].id else 1,
            0 if centres_preferes.get(animateur.id) == groupe["centre"].id else 1,
            0 if travaille_veille_meme_evenement(animateur) else 1,
            0 if placements_par_anim_evenement[(animateur.id, groupe["evenement"].id)] > 0 else 1,
            -utilite_qualifs(animateur),
            -placements_par_anim_evenement[(animateur.id, groupe["evenement"].id)],
            -placements_par_anim_centre[(animateur.id, groupe["centre"].id)],
            -placements_par_animateur[animateur.id],
            animateur.prenom,
            animateur.nom,
        ))
        return candidats

    def options_groupe(groupe):
        """Génère des groupes candidates, complètes d'abord, sous limite."""

        candidats = candidats_ordonnes(groupe)
        effectif = groupe["effectif"]
        exigences = groupe["qualifs"]
        options = []
        vus = set()
        limite = 180

        def ajouter(selection):
            cle = tuple(sorted(a.id for a in selection))
            if cle in vus:
                return
            vus.add(cle)
            options.append(tuple(selection))

        def possible_avec_restant(selection, position, taille_cible):
            places_restantes = taille_cible - len(selection)
            if len(candidats) - position < places_restantes:
                return False
            for qid, minimum in exigences.items():
                deja = sum(1 for a in selection if qid in qualifs_animateur[a.id])
                potentiel = sum(
                    1 for a in candidats[position:]
                    if qid in qualifs_animateur[a.id]
                )
                if deja + min(places_restantes, potentiel) < minimum:
                    return False
            return True

        # Taille cible décroissante : une solution pleine est essayée avant une
        # solution partielle. Un groupe non vide n'est proposée que lorsque
        # toutes ses qualifications sont couvertes.
        for taille in range(min(effectif, len(candidats)), 0, -1):
            if len(options) >= limite:
                break

            def combiner(position, selection):
                nonlocal interrompu
                if len(options) >= limite or datetime.datetime.now() > deadline:
                    interrompu = datetime.datetime.now() > deadline
                    return
                if len(selection) == taille:
                    if qualifications_couvertes(groupe, selection):
                        ajouter(selection)
                    return
                if position >= len(candidats):
                    return
                if not possible_avec_restant(selection, position, taille):
                    return

                selection.append(candidats[position])
                combiner(position + 1, selection)
                selection.pop()
                combiner(position + 1, selection)

            combiner(0, [])

        # Laisser tout le groupe vide est toujours autorisé. Cela évite de
        # créer un groupe partielle qui ne respecterait pas les exigences.
        options.append(tuple())
        return options

    def rechercher(index):
        nonlocal appels, interrompu
        appels += 1
        if datetime.datetime.now() > deadline:
            interrompu = True
            memoriser()
            return
        if index >= len(groupes):
            memoriser()
            return

        # Borne supérieure simple sur le nombre de places encore atteignable.
        places_actuelles = sum(len(selection) for selection in choix[:index])
        places_restantes = sum(groupe["effectif"] for groupe in groupes[index:])
        if meilleur_score is not None and places_actuelles + places_restantes < meilleur_score[0]:
            return

        groupe = groupes[index]
        for selection in options_groupe(groupe):
            if interrompu and datetime.datetime.now() > deadline:
                memoriser()
                return
            # Les options ont été calculées avec l'occupation actuelle. Cette
            # vérification garde la fonction sûre si elle évolue plus tard.
            if any(conflit(a, groupe) for a in selection):
                continue
            choix[index] = selection
            appliquer_selection(groupe, selection, +1)
            rechercher(index + 1)
            appliquer_selection(groupe, selection, -1)
            choix[index] = tuple()
            if interrompu and datetime.datetime.now() > deadline:
                return

    rechercher(0)
    if meilleur_score is None:
        meilleur_choix = [tuple() for _ in groupes]
        meilleur_score = (0,) * 9

    with transaction.atomic():
        supprimees, _ = Affectation.objects.filter(
            debut__lt=fin_dt,
            fin__gt=debut_dt,
        ).delete()

        a_creer = []
        for groupe, selection in zip(groupes, meilleur_choix):
            jour = groupe["jour"]
            for animateur in selection:
                a_creer.append(Affectation(
                    animateur=animateur,
                    centre=groupe["centre"],
                    evenement=groupe["evenement"],
                    debut=parse_to_aware_datetime(jour.isoformat()),
                    fin=parse_to_aware_datetime((jour + datetime.timedelta(days=1)).isoformat()),
                ))
        Affectation.objects.bulk_create(a_creer)

    total_places = sum(groupe["effectif"] for groupe in groupes)
    creees = len(a_creer)
    non_remplies = total_places - creees
    animateurs_utilises = len({aff.animateur_id for aff in a_creer})

    noms_qualifs = dict(Qualification.objects.values_list("id", "nom"))
    details_non_remplis = []
    for groupe, selection in zip(groupes, meilleur_choix):
        manque = groupe["effectif"] - len(selection)
        if manque <= 0:
            continue
        texte = (
            f"{groupe['jour'].strftime('%d/%m')} - "
            f"{groupe['centre'].code} / {groupe['evenement'].nom} : {manque} place(s) vide(s)"
        )
        if not selection and groupe["qualifs"]:
            exigences = ", ".join(
                f"{nb} {noms_qualifs.get(qid, 'qualification')}"
                for qid, nb in groupe["qualifs"].items()
            )
            texte += f" (exigences : {exigences})"
        details_non_remplis.append(texte)

    message = (
        f"{creees}/{total_places} place(s) remplie(s) dans les groupes, "
        f"{supprimees} ancienne(s) affectation(s) remplacée(s). "
        f"{animateurs_utilises}/{len(animateurs)} animateur(s) utilisé(s)."
    )
    if non_remplies:
        message += " Certaines places restent vides faute de combinaison conforme."
    if interrompu:
        message += " Recherche limitée dans le temps : la meilleure solution trouvée a été conservée."

    return {
        "ok": True,
        "created": creees,
        "deleted": supprimees,
        "total_places": total_places,
        "unfilled": non_remplies,
        "animateurs_utilises": animateurs_utilises,
        "interrompu": interrompu,
        "appels": appels,
        "details_non_remplis": details_non_remplis[:30],
        "message": message,
    }, 200
