"""Service de génération automatique du planning.

Ce module contient le solveur de remplissage automatique. Il est volontairement
séparé des vues Django pour éviter que `views.py` devienne illisible et pour
pouvoir tester/améliorer l'algorithme sans toucher aux endpoints HTTP.
"""

import datetime
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from animateurs.models import Affectation, Animateur, Centre, Qualification


def parse_to_aware_datetime(value):
    """Convertit une date ou datetime ISO en datetime aware."""

    dt = parse_datetime(value)

    if dt is None:
        date_seule = parse_date(value)
        if date_seule is None:
            raise ValueError(f"Date invalide : {value!r}")
        dt = datetime.datetime.combine(date_seule, datetime.time.min)

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)

    return dt


def generer_planning_auto(payload):
    """Génère automatiquement une semaine de planning.

    Paramètre:
        payload (dict): contenu JSON reçu depuis `/api/planning/auto/`.

    Retour:
        tuple(dict, int): données JSON à renvoyer et code HTTP.
    """
    """Remplit automatiquement la semaine affichée (lundi -> samedi) avec
    un solveur par backtracking borné.

    Pourquoi ce choix : l'ancien algorithme choisissait le meilleur candidat
    immédiat, mais pouvait bloquer une meilleure combinaison plus tard. Ici,
    on teste plusieurs combinaisons, on garde la meilleure solution trouvée,
    et on s'arrête proprement si le problème devient trop gros.

    Objectifs, par ordre de priorité :
      1. remplir le plus de places possible ;
      2. utiliser le plus d'animateurs différents possible ;
      3. équilibrer le nombre de jours travaillés ;
      4. favoriser les centres indiqués sur la fiche animateur ;
      5. respecter les exigences de qualifications demandées dans la modal.

    Contraintes strictes :
      - un animateur ne peut pas être placé deux fois le même jour ;
      - un animateur doit être disponible sur le jour concerné ;
      - si une place demande une qualification, l'animateur doit l'avoir.

    Important : les centres affectables de la fiche animateur ne sont PAS
    bloquants. Ils servent uniquement de bonus dans le score.
    """

    data = payload or {}

    debut_date = parse_date(data.get("debut", ""))
    if not debut_date:
        return {"error": "Date de début invalide."}, 400

    # Semaine affichée : lundi -> samedi. Dimanche exclu.
    lundi = debut_date - datetime.timedelta(days=debut_date.weekday())
    jours = [lundi + datetime.timedelta(days=i) for i in range(6)]
    dimanche = lundi + datetime.timedelta(days=6)

    debut_dt = parse_to_aware_datetime(lundi.isoformat())
    fin_dt = parse_to_aware_datetime(dimanche.isoformat())

    centres = list(Centre.objects.all().order_by("nom"))
    animateurs = list(
        Animateur.objects
        .prefetch_related("disponibilites", "preferences", "qualifications")
        .order_by("prenom", "nom")
    )

    if not centres:
        return {"error": "Aucun centre n'est configuré."}, 400
    if not animateurs:
        return {"error": "Aucun animateur n'est configuré."}, 400

    # ------------------------------------------------------------------
    # Lecture des besoins de la modal auto
    # ------------------------------------------------------------------
    besoins_recus = data.get("centres")
    effectifs_anciens = data.get("effectifs") or {}

    def besoin_pour(centre):
        """Renvoie (effectif_total, {qualification_id: nb_min}) pour un centre."""

        if isinstance(besoins_recus, dict):
            brut = besoins_recus.get(str(centre.id))
            if brut is None:
                brut = besoins_recus.get(centre.id)
            if isinstance(brut, dict):
                try:
                    effectif = int(brut.get("effectif", centre.effectif_cible))
                except (TypeError, ValueError):
                    effectif = centre.effectif_cible

                qualifs = {}
                for qid, nb in (brut.get("qualifs") or {}).items():
                    try:
                        qid_int, nb_int = int(qid), int(nb)
                    except (TypeError, ValueError):
                        continue
                    if nb_int > 0:
                        qualifs[qid_int] = nb_int

                return max(0, effectif), qualifs

        brut = effectifs_anciens.get(str(centre.id))
        if brut is None:
            brut = effectifs_anciens.get(centre.id, centre.effectif_cible)
        try:
            effectif = int(brut)
        except (TypeError, ValueError):
            effectif = centre.effectif_cible

        return max(0, effectif), {}

    # ------------------------------------------------------------------
    # Pré-calculs en mémoire : qualifications, disponibilités, centres
    # ------------------------------------------------------------------
    qualifs_animateur = {
        animateur.id: {qualification.id for qualification in animateur.qualifications.all()}
        for animateur in animateurs
    }

    centres_reperes = {
        animateur.id: {pref.centre_id for pref in animateur.preferences.all()}
        for animateur in animateurs
    }

    def a_la_qualif(animateur, qualif_id):
        return qualif_id in qualifs_animateur.get(animateur.id, set())

    def centre_est_repere(animateur, centre):
        return centre.id in centres_reperes.get(animateur.id, set())

    def disponible(animateur, jour):
        plages = list(animateur.disponibilites.all())
        if not plages:
            return True
        return any(plage.debut <= jour <= plage.fin for plage in plages)

    jours_dispo = {
        animateur.id: sum(1 for jour in jours if disponible(animateur, jour))
        for animateur in animateurs
    }

    nb_titulaires = {}
    for ids in qualifs_animateur.values():
        for qid in ids:
            nb_titulaires[qid] = nb_titulaires.get(qid, 0) + 1

    # ------------------------------------------------------------------
    # Création des places à remplir
    # ------------------------------------------------------------------
    slots = []
    for jour in jours:
        for centre in centres:
            effectif, qualifs_min = besoin_pour(centre)
            if effectif <= 0:
                continue

            # Les exigences les plus rares passent d'abord.
            exigences = sorted(
                qualifs_min.items(),
                key=lambda item: (nb_titulaires.get(item[0], 0), item[0]),
            )

            qualifs_slots = []
            for qid, nb in exigences:
                qualifs_slots.extend([qid] * nb)
            qualifs_slots = qualifs_slots[:effectif]

            for qid in qualifs_slots:
                slots.append({"jour": jour, "centre": centre, "qualif": qid})
            for _ in range(effectif - len(qualifs_slots)):
                slots.append({"jour": jour, "centre": centre, "qualif": None})

    if not slots:
        return {"error": "Aucune place à remplir : vérifie les effectifs des centres."}, 400

    # Candidats théoriques par slot, avant prise en compte des conflits du jour.
    base_candidates = []
    for slot in slots:
        candidats = []
        for animateur in animateurs:
            if jours_dispo[animateur.id] == 0:
                continue
            if not disponible(animateur, slot["jour"]):
                continue
            if slot["qualif"] is not None and not a_la_qualif(animateur, slot["qualif"]):
                continue
            candidats.append(animateur)
        base_candidates.append(candidats)

    # On traite d'abord les places les plus contraintes : peu de candidats,
    # puis qualification rare, puis jour/centre.
    ordre_slots = sorted(
        range(len(slots)),
        key=lambda i: (
            len(base_candidates[i]),
            0 if slots[i]["qualif"] is not None else 1,
            nb_titulaires.get(slots[i]["qualif"], 9999) if slots[i]["qualif"] is not None else 9999,
            slots[i]["jour"].isoformat(),
            slots[i]["centre"].nom,
        ),
    )

    # ------------------------------------------------------------------
    # Solveur backtracking borné
    # ------------------------------------------------------------------
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=2.5)
    assignment = [None] * len(slots)       # slot_index -> Animateur ou None
    best_assignment = [None] * len(slots)

    occupe_ce_jour = {jour: set() for jour in jours}
    jours_travailles = {a.id: 0 for a in animateurs}

    best_score = None
    appels = 0
    interrompu = False

    def score_solution(filled_count):
        used = sum(1 for nb in jours_travailles.values() if nb > 0)
        counts = [nb for nb in jours_travailles.values() if nb > 0]
        max_load = max(counts) if counts else 0
        min_load = min(counts) if counts else 0
        spread = max_load - min_load
        pref_bonus = 0
        qualif_bonus = 0

        for index, animateur in enumerate(assignment):
            if animateur is None:
                continue
            slot = slots[index]
            if centre_est_repere(animateur, slot["centre"]):
                pref_bonus += 1
            if slot["qualif"] is not None:
                qualif_bonus += 1

        # Tuple lexicographique : Python compare de gauche à droite.
        return (
            filled_count,     # priorité 1 : remplir un maximum
            used,             # priorité 2 : utiliser un maximum d'animateurs
            -max_load,        # priorité 3 : éviter de surcharger une personne
            -spread,          # priorité 4 : équilibrer les charges
            pref_bonus,       # priorité 5 : respecter les centres repères
            qualif_bonus,     # sécurité : garder les qualifs remplies
        )

    def memoriser_si_meilleur(filled_count):
        nonlocal best_score, best_assignment
        score = score_solution(filled_count)
        if best_score is None or score > best_score:
            best_score = score
            best_assignment = assignment.copy()

    def candidats_pour(slot_index):
        slot = slots[slot_index]
        candidats = [
            a for a in base_candidates[slot_index]
            if a.id not in occupe_ce_jour[slot["jour"]]
        ]

        # On essaie d'abord les animateurs les moins chargés, puis ceux pour
        # qui le centre est dans les repères, puis les moins disponibles.
        candidats.sort(key=lambda a: (
            jours_travailles[a.id],
            0 if centre_est_repere(a, slot["centre"]) else 1,
            jours_dispo[a.id],
            a.prenom,
            a.nom,
        ))
        return candidats

    def backtrack(position, filled_count):
        nonlocal appels, interrompu
        appels += 1

        if datetime.datetime.now() > deadline:
            interrompu = True
            memoriser_si_meilleur(filled_count)
            return

        # Borne simple : même en remplissant tout le reste, on ne peut pas
        # dépasser la meilleure solution déjà trouvée en nombre de places.
        restant = len(ordre_slots) - position
        if best_score is not None and filled_count + restant < best_score[0]:
            return

        if position >= len(ordre_slots):
            memoriser_si_meilleur(filled_count)
            return

        slot_index = ordre_slots[position]
        slot = slots[slot_index]
        candidats = candidats_pour(slot_index)

        # On tente tous les candidats possibles.
        for animateur in candidats:
            assignment[slot_index] = animateur
            occupe_ce_jour[slot["jour"]].add(animateur.id)
            jours_travailles[animateur.id] += 1

            backtrack(position + 1, filled_count + 1)

            jours_travailles[animateur.id] -= 1
            occupe_ce_jour[slot["jour"]].remove(animateur.id)
            assignment[slot_index] = None

            if interrompu:
                # On remonte rapidement : la meilleure solution partielle est
                # déjà mémorisée.
                return

        # Possibilité de laisser une place vide si aucune combinaison complète
        # n'est possible. C'est ce qui permet de renvoyer la meilleure solution
        # partielle au lieu d'échouer complètement.
        backtrack(position + 1, filled_count)

    backtrack(0, 0)

    if best_score is None:
        best_score = (0, 0, 0, 0, 0, 0)
        best_assignment = [None] * len(slots)

    with transaction.atomic():
        # On repart d'une semaine propre uniquement après avoir trouvé une
        # solution, même partielle. Si le solveur plantait avant, on ne vide
        # donc pas la semaine existante.
        supprimees, _ = Affectation.objects.filter(
            debut__lt=fin_dt,
            fin__gt=debut_dt,
        ).delete()

        a_creer = []
        for slot, animateur in zip(slots, best_assignment):
            if animateur is None:
                continue
            jour = slot["jour"]
            a_creer.append(Affectation(
                animateur=animateur,
                centre=slot["centre"],
                debut=parse_to_aware_datetime(jour.isoformat()),
                fin=parse_to_aware_datetime((jour + datetime.timedelta(days=1)).isoformat()),
            ))

        Affectation.objects.bulk_create(a_creer)

    total_places = len(slots)
    creees = len(a_creer)
    non_remplies = total_places - creees
    animateurs_utilises = best_score[1]

    # Diagnostics simples pour comprendre les trous éventuels.
    details_non_remplis = []
    for slot, animateur in zip(slots, best_assignment):
        if animateur is not None:
            continue
        texte = f"{slot['jour'].strftime('%d/%m')} - {slot['centre'].code}"
        if slot["qualif"] is not None:
            try:
                q = Qualification.objects.get(pk=slot["qualif"])
                texte += f" ({q.nom})"
            except Qualification.DoesNotExist:
                texte += " (qualification demandée)"
        details_non_remplis.append(texte)

    message = (
        f"{creees}/{total_places} place(s) remplie(s), "
        f"{supprimees} ancienne(s) remplacée(s). "
        f"{animateurs_utilises}/{len(animateurs)} animateur(s) utilisé(s)."
    )
    if non_remplies:
        message += " Certaines places restent vides faute de combinaison possible."
    if interrompu:
        message += " Recherche interrompue après délai : meilleure solution trouvée conservée."

    return {
        "ok": True,
        "created": creees,
        "deleted": supprimees,
        "total_places": total_places,
        "unfilled": non_remplies,
        "animateurs_utilises": animateurs_utilises,
        "interrompu": interrompu,
        "appels": appels,
        "details_non_remplis": details_non_remplis[:20],
        "message": message,
    }, 200
