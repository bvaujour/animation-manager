"""Indicateurs de pilotage du planning sur une période donnée.

Le récapitulatif combine deux lectures complémentaires :
- la charge réellement affectée à chaque salarié ;
- la couverture des besoins de chaque groupe, journée par journée.

Les besoins sont contrôlés sur tous les jours de la période. Chaque groupe décide ensuite quels jours de la semaine sont ouverts.
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from django.db.models import Q

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Evenement,
)


def _jours_entre(debut: datetime.date, fin_exclusive: datetime.date):
    """Itère sur les dates de ``debut`` inclus à ``fin_exclusive`` exclu."""

    jour = debut
    while jour < fin_exclusive:
        yield jour
        jour += datetime.timedelta(days=1)


def _jours_operationnels(debut: datetime.date, fin_exclusive: datetime.date):
    """Tous les jours possibles ; l’ouverture dépend ensuite de chaque groupe."""
    return list(_jours_entre(debut, fin_exclusive))


def _date_fr(jour: datetime.date) -> str:
    return jour.strftime("%d/%m/%Y")


def _liste_dates_courte(dates, limite=6):
    dates = sorted(set(dates))
    affichees = [_date_fr(jour) for jour in dates[:limite]]
    if len(dates) > limite:
        affichees.append(f"+ {len(dates) - limite} autre(s)")
    return ", ".join(affichees)


def _jour_dans_disponibilites(jour, disponibilites):
    return any(plage.debut <= jour <= plage.fin for plage in disponibilites)




def _evenement_ouvert_selon_configuration(evenement, jour, dates_exclues):
    return evenement.est_ouvert_le(jour, dates_exclues)


def generer_recapitulatif(debut, fin, jours_selectionnes=None):
    """Construit le tableau de charge, les indicateurs et les alertes.

    ``debut`` est inclus et ``fin`` est exclusif, conformément aux autres API
    du planning.
    """

    debut_date = debut.date()
    fin_date = fin.date()
    jours_operationnels = _jours_operationnels(debut_date, fin_date)
    if jours_selectionnes is not None:
        jours_selectionnes = set(jours_selectionnes)
        jours_operationnels = [jour for jour in jours_operationnels if jour in jours_selectionnes]
    jours_operationnels_set = set(jours_operationnels)

    centres = list(Centre.objects.all().order_by("ordre", "nom"))
    animateurs = list(
        Animateur.objects.prefetch_related(
            "qualifications",
            "disponibilites",
            "preferences",
        ).order_by("prenom", "nom")
    )

    evenements = list(
        Evenement.objects.select_related("centre")
        .prefetch_related("besoins_qualifications__qualification", "dates_exclues", "periodes_scolaires")
        .filter(
            Q(debut__isnull=True) | Q(debut__lt=fin_date),
            Q(fin__isnull=True) | Q(fin__gte=debut_date),
        )
        .order_by("centre__ordre", "centre__nom", "ordre", "nom")
    )

    affectations = list(
        Affectation.objects.select_related("animateur", "centre", "evenement")
        .filter(debut__lt=fin, fin__gt=debut)
        .order_by("debut", "animateur__prenom", "animateur__nom")
    )

    qualifications_par_animateur = {
        animateur.id: {qualification.id for qualification in animateur.qualifications.all()}
        for animateur in animateurs
    }
    disponibilites_par_animateur = {
        animateur.id: list(animateur.disponibilites.all())
        for animateur in animateurs
    }
    centres_autorises_par_animateur = {
        animateur.id: {preference.centre_id for preference in animateur.preferences.all()}
        for animateur in animateurs
    }

    jours_affectes_par_animateur = defaultdict(set)
    jours_affectes_par_animateur_centre = defaultdict(set)
    affectations_par_evenement_jour = defaultdict(list)
    affectations_par_animateur_jour = defaultdict(list)

    anomalies_jours_fermes = []

    for affectation in affectations:
        debut_effectif = max(affectation.debut.date(), debut_date)
        fin_effective = min(affectation.fin.date(), fin_date)

        for jour in _jours_entre(debut_effectif, fin_effective):
            if jour not in jours_operationnels_set:
                continue
            jours_affectes_par_animateur[affectation.animateur_id].add(jour)
            jours_affectes_par_animateur_centre[
                (affectation.animateur_id, affectation.centre_id)
            ].add(jour)
            affectations_par_animateur_jour[(affectation.animateur_id, jour)].append(affectation)

            if affectation.evenement_id:
                affectations_par_evenement_jour[(affectation.evenement_id, jour)].append(affectation)
                evenement = affectation.evenement
                dates_exclues = {fermeture.date for fermeture in evenement.dates_exclues.all()}
                if not _evenement_ouvert_selon_configuration(evenement, jour, dates_exclues):
                    anomalies_jours_fermes.append((affectation, jour))

    recap = {}
    for animateur in animateurs:
        jours_disponibles = {
            jour
            for jour in jours_operationnels
            if _jour_dans_disponibilites(
                jour, disponibilites_par_animateur.get(animateur.id, [])
            )
        }
        jours_affectes = jours_affectes_par_animateur.get(animateur.id, set())
        jours_affectes_operationnels = jours_affectes & jours_operationnels_set

        recap[animateur.id] = {
            "id": animateur.id,
            "prenom": animateur.prenom,
            "nom": animateur.nom,
            "total": len(jours_affectes),
            "jours_disponibles": len(jours_disponibles),
            "jours_libres": len(jours_disponibles - jours_affectes_operationnels),
            "centres": {
                centre.id: len(
                    jours_affectes_par_animateur_centre.get(
                        (animateur.id, centre.id), set()
                    )
                )
                for centre in centres
            },
        }

    lignes_animateurs = [
        {
            "id": ligne["id"],
            "prenom": ligne["prenom"],
            "nom": ligne["nom"],
            "total": ligne["total"],
            "jours_disponibles": ligne["jours_disponibles"],
            "jours_libres": ligne["jours_libres"],
            "centres": [
                {"id": centre.id, "jours": ligne["centres"][centre.id]}
                for centre in centres
            ],
        }
        for ligne in recap.values()
    ]
    lignes_animateurs.sort(
        key=lambda item: (-item["total"], item["prenom"].casefold(), item["nom"].casefold())
    )

    alertes = []
    lignes_evenements = []

    total_postes_requis = 0
    total_postes_couverts = 0
    total_postes_manquants = 0
    total_sureffectif = 0
    total_qualifications_manquantes = 0
    journees_sous_tension = set()

    for evenement in evenements:
        debut_evenement = max(debut_date, evenement.debut or debut_date)
        fin_evenement_exclusive = min(
            fin_date,
            (evenement.fin + datetime.timedelta(days=1)) if evenement.fin else fin_date,
        )
        dates_exclues_evenement = {
            fermeture.date for fermeture in evenement.dates_exclues.all()
        }
        jours_evenement = (
            [
                jour
                for jour in _jours_operationnels(debut_evenement, fin_evenement_exclusive)
                if jour in jours_operationnels_set
                and evenement.est_ouvert_le(jour, dates_exclues_evenement)
            ]
            if debut_evenement < fin_evenement_exclusive
            else []
        )

        besoins_qualifications = list(evenement.besoins_qualifications.all())
        manques_personnel = []
        sureffectifs = []
        manques_qualifications = defaultdict(list)
        jours_complets = 0
        postes_requis = len(jours_evenement) * evenement.effectif_cible
        postes_couverts = 0

        for jour in jours_evenement:
            affectations_jour = affectations_par_evenement_jour.get((evenement.id, jour), [])
            nb_affectes = len(affectations_jour)
            postes_couverts += min(nb_affectes, evenement.effectif_cible)
            manque = max(0, evenement.effectif_cible - nb_affectes)
            surplus = max(0, nb_affectes - evenement.effectif_cible)

            if manque:
                manques_personnel.append((jour, manque))
                journees_sous_tension.add((evenement.id, jour))
            if surplus:
                sureffectifs.append((jour, surplus))

            qualifs_ok = True
            for besoin in besoins_qualifications:
                nb_titulaires = sum(
                    1
                    for affectation in affectations_jour
                    if besoin.qualification_id
                    in qualifications_par_animateur.get(affectation.animateur_id, set())
                )
                manque_qualification = max(0, besoin.nombre_minimum - nb_titulaires)
                if manque_qualification:
                    qualifs_ok = False
                    manques_qualifications[besoin].append((jour, manque_qualification))
                    journees_sous_tension.add((evenement.id, jour))

            if manque == 0 and qualifs_ok:
                jours_complets += 1

        total_postes_requis += postes_requis
        total_postes_couverts += postes_couverts
        total_postes_manquants += sum(manque for _, manque in manques_personnel)
        total_sureffectif += sum(surplus for _, surplus in sureffectifs)
        total_qualifications_manquantes += sum(
            manque
            for valeurs in manques_qualifications.values()
            for _, manque in valeurs
        )

        if manques_personnel:
            nb_postes = sum(manque for _, manque in manques_personnel)
            alertes.append({
                "niveau": "danger",
                "type": "personnel",
                "titre": f"Personnel manquant — {evenement.nom}",
                "lieu": evenement.centre.nom,
                "message": (
                    f"{nb_postes} poste(s) non couvert(s) sur "
                    f"{len(manques_personnel)} journée(s)."
                ),
                "dates": _liste_dates_courte([jour for jour, _ in manques_personnel]),
            })

        for besoin, valeurs in manques_qualifications.items():
            manque_total = sum(manque for _, manque in valeurs)
            alertes.append({
                "niveau": "danger",
                "type": "qualification",
                "titre": f"Qualification manquante — {evenement.nom}",
                "lieu": evenement.centre.nom,
                "message": (
                    f"Il manque {manque_total} titulaire(s) « {besoin.qualification.nom} » "
                    f"au total sur {len(valeurs)} journée(s)."
                ),
                "dates": _liste_dates_courte([jour for jour, _ in valeurs]),
            })

        if sureffectifs:
            nb_surplus = sum(surplus for _, surplus in sureffectifs)
            alertes.append({
                "niveau": "warning",
                "type": "sureffectif",
                "titre": f"Sureffectif — {evenement.nom}",
                "lieu": evenement.centre.nom,
                "message": (
                    f"{nb_surplus} présence(s) au-delà du besoin sur "
                    f"{len(sureffectifs)} journée(s)."
                ),
                "dates": _liste_dates_courte([jour for jour, _ in sureffectifs]),
            })

        besoins_impossibles = [
            besoin
            for besoin in besoins_qualifications
            if besoin.nombre_minimum > evenement.effectif_cible
        ]
        for besoin in besoins_impossibles:
            alertes.append({
                "niveau": "warning",
                "type": "configuration",
                "titre": f"Besoin incohérent — {evenement.nom}",
                "lieu": evenement.centre.nom,
                "message": (
                    f"{besoin.nombre_minimum} personne(s) « {besoin.qualification.nom} » "
                    f"sont demandées pour un effectif total de {evenement.effectif_cible}."
                ),
                "dates": "À corriger dans Gestion",
            })

        qualifications_libelle = [
            {
                "nom": besoin.qualification.nom,
                "minimum": besoin.nombre_minimum,
            }
            for besoin in besoins_qualifications
        ]
        couverture = round((postes_couverts / postes_requis) * 100) if postes_requis else 0
        statut = "neutre"
        if jours_evenement:
            if manques_personnel or manques_qualifications:
                statut = "danger"
            elif sureffectifs:
                statut = "warning"
            else:
                statut = "ok"

        lignes_evenements.append({
            "id": evenement.id,
            "nom": evenement.nom,
            "lieu": evenement.centre.nom,
            "couleur": evenement.centre.couleur,
            "debut": evenement.debut.isoformat() if evenement.debut else None,
            "fin": evenement.fin.isoformat() if evenement.fin else None,
            "effectif_cible": evenement.effectif_cible,
            "jours_ouverts": [int(numero) for numero in (evenement.jours_ouverts or [])],
            "dates_exclues": [date.isoformat() for date in sorted(dates_exclues_evenement)],
            "jours_prevus": len(jours_evenement),
            "jours_complets": jours_complets,
            "jours_incomplets": len(jours_evenement) - jours_complets,
            "postes_requis": postes_requis,
            "postes_couverts": postes_couverts,
            "postes_manquants": sum(manque for _, manque in manques_personnel),
            "sureffectif": sum(surplus for _, surplus in sureffectifs),
            "qualifications_manquantes": sum(
                manque
                for valeurs in manques_qualifications.values()
                for _, manque in valeurs
            ),
            "qualifications": qualifications_libelle,
            "couverture": couverture,
            "statut": statut,
        })

    # Contrôles de cohérence des affectations existantes.
    doubles_par_animateur = defaultdict(list)
    indisponibles_par_animateur = defaultdict(list)
    lieux_non_autorises = defaultdict(list)

    animateurs_par_id = {animateur.id: animateur for animateur in animateurs}

    for (animateur_id, jour), affectations_jour in affectations_par_animateur_jour.items():
        animateur = animateurs_par_id.get(animateur_id)
        if not animateur:
            continue

        if len(affectations_jour) > 1:
            doubles_par_animateur[animateur].append(jour)

        if not _jour_dans_disponibilites(
            jour, disponibilites_par_animateur.get(animateur_id, [])
        ):
            indisponibles_par_animateur[animateur].append(jour)

        centres_jour = {
            affectation.centre_id
            for affectation in affectations_jour
            if affectation.centre_id
            not in centres_autorises_par_animateur.get(animateur_id, set())
        }
        for centre_id in centres_jour:
            lieux_non_autorises[(animateur, centre_id)].append(jour)

    for animateur, dates in doubles_par_animateur.items():
        alertes.append({
            "niveau": "danger",
            "type": "double_affectation",
            "titre": f"Double affectation — {animateur.prenom} {animateur.nom}",
            "lieu": "Conflit de planning",
            "message": f"Cette personne apparaît sur plusieurs groupes le même jour ({len(set(dates))} jour(s)).",
            "dates": _liste_dates_courte(dates),
        })

    for animateur, dates in indisponibles_par_animateur.items():
        alertes.append({
            "niveau": "warning",
            "type": "indisponibilite",
            "titre": f"Affectation hors disponibilité — {animateur.prenom} {animateur.nom}",
            "lieu": "Disponibilités",
            "message": f"{len(set(dates))} journée(s) affectée(s) ne sont pas couvertes par ses disponibilités.",
            "dates": _liste_dates_courte(dates),
        })

    centres_par_id = {centre.id: centre for centre in centres}
    for (animateur, centre_id), dates in lieux_non_autorises.items():
        centre = centres_par_id.get(centre_id)
        alertes.append({
            "niveau": "warning",
            "type": "lieu_non_autorise",
            "titre": f"Lieu non prévu — {animateur.prenom} {animateur.nom}",
            "lieu": centre.nom if centre else "Lieu inconnu",
            "message": "Cette personne est affectée sur un lieu absent de ses lieux autorisés.",
            "dates": _liste_dates_courte(dates),
        })

    for affectation, jour in anomalies_jours_fermes:
        alertes.append({
            "niveau": "warning",
            "type": "jour_ferme",
            "titre": f"Affectation sur un jour fermé — {affectation.evenement.nom}",
            "lieu": affectation.centre.nom,
            "message": (
                f"{affectation.animateur.prenom} {affectation.animateur.nom} est affecté(e) "
                "sur une date non ouverte pour ce groupe."
            ),
            "dates": _date_fr(jour),
        })


    animateurs_mobilises = sum(1 for ligne in lignes_animateurs if ligne["total"] > 0)
    disponibles_sans_affectation = [
        ligne
        for ligne in lignes_animateurs
        if ligne["jours_disponibles"] > 0 and ligne["total"] == 0
    ]

    if disponibles_sans_affectation:
        noms = ", ".join(
            f"{ligne['prenom']} {ligne['nom']}" for ligne in disponibles_sans_affectation[:8]
        )
        if len(disponibles_sans_affectation) > 8:
            noms += f" + {len(disponibles_sans_affectation) - 8} autre(s)"
        alertes.append({
            "niveau": "info",
            "type": "ressources_disponibles",
            "titre": "Salariés disponibles sans affectation",
            "lieu": "Ressources disponibles",
            "message": noms,
            "dates": f"{len(disponibles_sans_affectation)} personne(s)",
        })

    ordre_niveaux = {"danger": 0, "warning": 1, "info": 2}
    alertes.sort(
        key=lambda alerte: (
            ordre_niveaux.get(alerte["niveau"], 9),
            alerte["lieu"].casefold(),
            alerte["titre"].casefold(),
        )
    )

    couverture_globale = (
        round((total_postes_couverts / total_postes_requis) * 100)
        if total_postes_requis
        else 0
    )
    charges = [ligne["total"] for ligne in lignes_animateurs if ligne["total"] > 0]

    synthese = {
        "couverture": couverture_globale,
        "postes_requis": total_postes_requis,
        "postes_couverts": total_postes_couverts,
        "postes_manquants": total_postes_manquants,
        "qualifications_manquantes": total_qualifications_manquantes,
        "sureffectif": total_sureffectif,
        "journees_sous_tension": len(journees_sous_tension),
        "evenements_suivis": sum(1 for ligne in lignes_evenements if ligne["jours_prevus"] > 0),
        "animateurs_mobilises": animateurs_mobilises,
        "animateurs_total": len(animateurs),
        "disponibles_sans_affectation": len(disponibles_sans_affectation),
        "charge_min": min(charges) if charges else 0,
        "charge_max": max(charges) if charges else 0,
        "charge_moyenne": round(sum(charges) / len(charges), 1) if charges else 0,
    }

    return {
        "centres": centres,
        "animateurs": lignes_animateurs,
        "evenements": lignes_evenements,
        "alertes": alertes,
        "synthese": synthese,
    }
