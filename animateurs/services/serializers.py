"""Sérialisation JSON centralisée des modèles de l'application."""

import datetime
import re

from django.utils import timezone

from animateurs.models import BesoinEncadrement, TypeAccueil, jours_feries_france
from animateurs.services.flottants import est_groupe_flottants, type_affectation
from animateurs.services.besoins_encadrement import besoin_encadrement_effectif, besoins_contextuels_payload
from animateurs.services.disponibilites import formation_bloquante
from animateurs.services.status_colors import (
    couleur_pour_statut,
    couleur_texte_pour_fond,
    statut_payload,
)
from animateurs.services.statuts import statut_actuel, statut_pour_date


def _centre_preference_to_dict(preference):
    """Sérialise un centre issu d'une relation de préférence animateur."""
    centre = preference.centre
    return {
        "id": preference.centre_id,
        "nom": centre.nom,
        "code": centre.code,
        "couleur": centre.couleur,
    }


def _formations_indisponibles_payload(formations):
    return [
        {
            "id": formation.id,
            "intitule": formation.intitule,
            "debut": formation.date_debut.isoformat(),
            "fin": formation.date_fin.isoformat(),
            "motif": f"Formation — {formation.intitule}",
        }
        for formation in formations
    ]


def _qualifications_payload(qualifications, *, statut_resolu=None, statut_date_resolu=False):
    """Retourne les champs communs aux sérialisations complète et Planning."""

    qualifications_ordinaires = [item for item in qualifications if not item.est_statut]
    qualification_ids = {
        qualification.id for qualification in qualifications_ordinaires
    }
    if statut_date_resolu and statut_resolu is not None:
        qualification_ids.add(statut_resolu.id)
    elif not statut_date_resolu:
        qualification_ids.update(
            identifiant
            for qualification in qualifications
            for identifiant in (qualification.id, qualification.statut_id)
            if identifiant
        )
    noms_qualifications = [qualification.nom for qualification in qualifications_ordinaires]
    if statut_date_resolu and statut_resolu is not None:
        noms_qualifications.append(statut_resolu.nom)
    elif not statut_date_resolu:
        noms_qualifications = [qualification.nom for qualification in qualifications]
    return {
        "qualification_ids": sorted(qualification_ids),
        "qualifications": noms_qualifications,
        "qualification_icones": [
            {"id": qualification.id, "nom": qualification.nom, "icone": qualification.icone}
            for qualification in qualifications
            if not qualification.est_statut and qualification.icone
        ],
    }


def contrat_to_dict(contrat, *, annees_cloturees=None):
    from .contrats import contrat_est_verrouille
    historique_remunerations = getattr(
        contrat,
        "_animateurs_payload_historique_remunerations",
        None,
    )
    if historique_remunerations is None:
        historique_remunerations = contrat.historique_remunerations.all()
    return {
        "id": contrat.id,
        "verrouille": contrat_est_verrouille(contrat, annees_cloturees=annees_cloturees),
        "animateur_id": contrat.animateur_id,
        "type_contrat": contrat.type_contrat,
        "type_contrat_ref_id": contrat.type_contrat_ref_id,
        "type_contrat_libelle": contrat.libelle_type,
        "mode_paie": contrat.mode_paie,
        "date_debut": contrat.date_debut.isoformat() if contrat.date_debut else None,
        "date_fin": contrat.date_fin.isoformat() if contrat.date_fin else None,
        "taux_journalier_reference": (
            str(contrat.taux_journalier_reference) if contrat.taux_journalier_reference is not None else None
        ),
        "salaire_mensuel_reference": (
            str(contrat.salaire_mensuel_reference) if contrat.salaire_mensuel_reference is not None else None
        ),
        "mode_temps_travail": contrat.mode_temps_travail,
        "heures_hebdomadaires": str(contrat.heures_hebdomadaires) if contrat.heures_hebdomadaires is not None else None,
        "heures_mensuelles_reference": str(contrat.heures_mensuelles_reference) if contrat.heures_mensuelles_reference is not None else None,
        "heures_annuelles_reference": str(contrat.heures_annuelles_reference) if contrat.heures_annuelles_reference is not None else None,
        "mode_remuneration": contrat.mode_remuneration,
        "annee_execution_initiale": contrat.annee_execution_initiale,
        "date_effet_annee_execution": (
            contrat.date_effet_annee_execution.isoformat() if contrat.date_effet_annee_execution else None
        ),
        "historique_remunerations": [
            {"id": item.id, "date_effet": item.date_effet.isoformat(), "montant_mensuel": str(item.montant_mensuel), "origine": item.origine}
            for item in historique_remunerations
        ],
        "statut": contrat.statut,
        "statut_libelle": contrat.libelle_statut,
        "cree_le": contrat.cree_le.isoformat(),
        "modifie_le": contrat.modifie_le.isoformat(),
    }


def historique_statut_to_dict(entree):
    return {
        "id": entree.id,
        "statut_id": entree.statut_id,
        "statut_nom": entree.statut.nom,
        "date_effet": entree.date_effet.isoformat(),
        "origine": entree.origine,
        "origine_libelle": entree.get_origine_display(),
        "date_effet_incertaine": entree.date_effet_incertaine,
        "commentaire": entree.commentaire,
    }


def affectation_to_event(affectation):
    qualifications = list(affectation.animateur.qualifications.all())
    horaires = {
        horaire.date.isoformat(): {
            "heure_arrivee": horaire.heure_arrivee.strftime("%H:%M"),
            "heure_depart": horaire.heure_depart.strftime("%H:%M"),
        }
        for horaire in affectation.horaires_journaliers.all()
    }
    titre = f"{affectation.animateur.prenom} {affectation.animateur.nom[0]}."
    flottant = est_groupe_flottants(affectation.evenement)
    type_affectation_valeur = type_affectation(affectation)
    responsabilites = getattr(affectation, "_responsabilites_planning", None)
    if responsabilites is None:
        from animateurs.models import ResponsabiliteOperationnelle
        responsabilites = list(ResponsabiliteOperationnelle.objects.filter(
            affectation_source_id=affectation.id
        ).select_related("fonction"))
    responsabilite = responsabilites[0] if responsabilites else None
    if flottant:
        titre = f"↔ {titre}"
    if len(horaires) == 1:
        plage = next(iter(horaires.values()))
        titre += f" · {plage['heure_arrivee']}–{plage['heure_depart']}"
    debut_local = timezone.localtime(affectation.debut).date()
    fin_locale = timezone.localtime(affectation.fin).date()
    statut_date = statut_pour_date(affectation.animateur, debut_local)
    statut = statut_payload(qualifications, statut_resolu=statut_date)
    formations = getattr(affectation.animateur, "_planning_formations", None)
    conflits_formation = []
    jour = debut_local
    while jour < fin_locale:
        formation = formation_bloquante(affectation.animateur, jour, formations=formations)
        if formation:
            conflits_formation.append({
                "formation_id": formation.id,
                "intitule": formation.intitule,
                "date": jour.isoformat(),
                "motif": f"Formation — {formation.intitule}",
            })
        jour += datetime.timedelta(days=1)
    if conflits_formation:
        titre += "  ⚠ FORMATION"
    return {
        "id": affectation.id,
        "title": titre,
        # Une affectation FullCalendar est une plage de journées entières :
        # envoyer des dates locales évite tout décalage UTC au changement de fuseau.
        "start": debut_local.isoformat(),
        "end": fin_locale.isoformat(),
        "allDay": True,
        "backgroundColor": statut["couleur_fond_statut"],
        "borderColor": statut["couleur_statut"],
        "textColor": statut["couleur_texte_statut"],
        "extendedProps": {
            "animateur_id": affectation.animateur_id,
            "animateur_nom": f"{affectation.animateur.prenom} {affectation.animateur.nom}",
            "conflits_formation": conflits_formation,
            "centre_id": affectation.centre_id,
            # Noms modernes et alias historiques pour ne pas casser un ancien cache JS.
            "groupe_id": affectation.evenement_id,
            "groupe_nom": affectation.evenement.nom,
            "evenement_id": affectation.evenement_id,
            "evenement_nom": affectation.evenement.nom,
            "horaires": horaires,
            "type_affectation": type_affectation_valeur,
            "type_accueil": affectation.type_accueil.code if affectation.type_accueil_id else None,
            "modalite_periscolaire": (
                affectation.modalite_periscolaire.code if affectation.modalite_periscolaire_id else None
            ),
            "modalite_periscolaire_nom": (
                affectation.modalite_periscolaire.nom if affectation.modalite_periscolaire_id else None
            ),
            "responsabilite": ({
                "id": responsabilite.id,
                "fonction_code": responsabilite.fonction.code,
                "fonction_nom": responsabilite.fonction.nom,
            } if responsabilite else None),
        },
    }


def animateur_to_dict(
    animateur,
    *,
    date_reference=None,
    activation_url=None,
    annees_cloturees=None,
):
    qualifications = list(animateur.qualifications.all())
    statut_date = statut_pour_date(animateur, date_reference) if date_reference else statut_actuel(animateur)
    statut = statut_payload(qualifications, statut_resolu=statut_date)
    preferences = list(animateur.preferences.all())
    disponibilites_source = (
        animateur._filtre_disponibilites
        if hasattr(animateur, "_filtre_disponibilites")
        else animateur.disponibilites.all()
    )
    disponibilites = list(disponibilites_source)
    affectations = list(getattr(animateur, "_filtre_affectations", []))
    formations = list(getattr(animateur, "_filtre_formations", []))
    contrats = list(animateur.contrats.all())
    historique_statuts = list(getattr(animateur, "_historique_statuts", []))
    affinites = list(animateur.affinites_groupes.all())

    affinites_groupes = [
        {
            "affinite_id": affinite.id,
            "groupe_id": affinite.evenement_id,
            "groupe_nom": affinite.evenement.nom,
            "centre_id": affinite.evenement.centre_id,
            "centre_nom": affinite.evenement.centre.nom,
            "jours_travailles": affinite.jours_travailles,
            "score_affinite": affinite.score,
            "dernier_jour": (affinite.dernier_jour_travaille.isoformat() if affinite.dernier_jour_travaille else None),
        }
        for affinite in affinites
        if affinite.jours_travailles > 0 and not est_groupe_flottants(affinite.evenement)
    ]
    affinites_groupes.sort(
        key=lambda entree: (
            -entree["score_affinite"],
            entree["centre_nom"],
            entree["groupe_nom"],
        )
    )

    prefere_relations = [pref for pref in preferences if pref.est_prefere and not pref.est_interdit]
    interdites_relations = [pref for pref in preferences if pref.est_interdit]

    centres_preferes = [_centre_preference_to_dict(pref) for pref in prefere_relations]
    centres_interdits = [_centre_preference_to_dict(pref) for pref in interdites_relations]
    centre_prefere = centres_preferes[0] if centres_preferes else None
    # Les champs singulier/secondaires sont conservés pour les anciennes
    # interfaces. La nouvelle interface utilise directement
    # ``centres_preferes`` et ``centres_interdits``.
    centres_secondaires = centres_preferes[1:]
    centres_autorises = centres_preferes

    evenement_preferee = None
    if animateur.evenement_preferee_id:
        evenement = animateur.evenement_preferee
        evenement_preferee = {
            "id": evenement.id,
            "nom": evenement.nom,
            "centre_id": evenement.centre_id,
            "centre_nom": evenement.centre.nom,
        }

    return {
        "id": animateur.id,
        "actif": animateur.actif,
        "prenom": animateur.prenom,
        "nom": animateur.nom,
        "telephone": animateur.telephone,
        "email": animateur.email,
        "date_naissance": animateur.date_naissance.isoformat() if animateur.date_naissance else None,
        "adresse": animateur.adresse,
        "numero_securite_sociale": animateur.numero_securite_sociale,
        "paie_jour": str(animateur.paie_jour) if animateur.paie_jour is not None else None,
        "contrats": [
            contrat_to_dict(contrat, annees_cloturees=annees_cloturees)
            for contrat in contrats
        ],
        "historique_statuts": [historique_statut_to_dict(entree) for entree in historique_statuts],
        "age": animateur.age,
        # Couleur historique conservée en base, mais les interfaces utilisent
        # désormais exclusivement la couleur automatique du statut.
        "couleur": statut["couleur_statut"],
        **statut,
        # Les catégories sont ajoutées aux identifiants effectifs pour que les
        # filtres puissent trouver tous les diplômes d'une même famille.
        **_qualifications_payload(
            qualifications, statut_resolu=statut_date, statut_date_resolu=True
        ),
        "centre_prefere": centre_prefere,
        "centres_secondaires": centres_secondaires,
        "centres_preferes": centres_preferes,
        "centres_interdits": centres_interdits,
        # Champ conservé pour compatibilité avec les écrans qui attendent encore
        # une liste globale. Le centre préféré est toujours placé en premier.
        "centres_autorises": centres_autorises,
        "evenement_preferee": evenement_preferee,
        "evenement_preferee_id": evenement_preferee["id"] if evenement_preferee else None,
        "disponibilites": [
            {"debut": dispo.debut.isoformat(), "fin": dispo.fin.isoformat()} for dispo in disponibilites
        ],
        "formations_indisponibles": _formations_indisponibles_payload(formations),
        "affectations": [
            {
                "debut": affectation.debut.isoformat(),
                "fin": affectation.fin.isoformat(),
                "centre_id": affectation.centre_id,
            }
            for affectation in affectations
        ],
        "affinites_groupes": affinites_groupes,
        # Alias temporaire pour les anciens caches JavaScript.
        "historique_groupes": affinites_groupes,
        "role": "animateur",
        "role_label": "Animateur",
        "access": {
            "exists": bool(animateur.utilisateur_id),
            "username": animateur.utilisateur.username if animateur.utilisateur_id else None,
            "active": animateur.utilisateur.is_active if animateur.utilisateur_id else False,
            "activation_pending": bool(
                animateur.utilisateur_id and not animateur.utilisateur.has_usable_password()
            ),
            "activation_url": activation_url,
            "last_login": (
                animateur.utilisateur.last_login.isoformat()
                if animateur.utilisateur_id and animateur.utilisateur.last_login else None
            ),
        },
    }


def animateur_planning_to_dict(animateur, *, date_reference=None, dates_reference=None):
    """Version compacte de l'animateur pour la barre latérale du Planning.

    La fiche complète contient des données administratives et l'historique des
    affinités, inutiles pour afficher les badges. Cette sérialisation réduit donc
    le volume JSON et permet de ne charger que les disponibilités/affectations de
    la semaine demandée.
    """

    qualifications = list(animateur.qualifications.all())
    date_reference = date_reference or timezone.localdate()
    statut_date = statut_pour_date(animateur, date_reference)
    statut = statut_payload(qualifications, statut_resolu=statut_date)
    statuts_par_date = {}
    for jour in dates_reference or []:
        statut_jour = statut_pour_date(animateur, jour)
        statuts_par_date[jour.isoformat()] = (
            {"id": statut_jour.id, "nom": statut_jour.nom} if statut_jour else None
        )
    preferences = list(animateur.preferences.all())
    disponibilites_source = (
        animateur._filtre_disponibilites
        if hasattr(animateur, "_filtre_disponibilites")
        else animateur.disponibilites.all()
    )
    disponibilites = list(disponibilites_source)
    affectations = list(getattr(animateur, "_filtre_affectations", []))
    formations = list(getattr(animateur, "_filtre_formations", []))

    prefere_relations = [pref for pref in preferences if pref.est_prefere and not pref.est_interdit]
    interdites_relations = [pref for pref in preferences if pref.est_interdit]

    centres_preferes = [_centre_preference_to_dict(pref) for pref in prefere_relations]
    centres_interdits = [_centre_preference_to_dict(pref) for pref in interdites_relations]
    centre_prefere = centres_preferes[0] if centres_preferes else None

    return {
        "id": animateur.id,
        "actif": animateur.actif,
        "prenom": animateur.prenom,
        "nom": animateur.nom,
        "telephone": animateur.telephone,
        "email": animateur.email,
        "couleur": statut["couleur_statut"],
        **statut,
        **_qualifications_payload(
            qualifications, statut_resolu=statut_date, statut_date_resolu=True
        ),
        "statuts_par_date": statuts_par_date,
        "centre_prefere": centre_prefere,
        "centres_preferes": centres_preferes,
        "centres_interdits": centres_interdits,
        "centres_autorises": centres_preferes,
        "disponibilites": [
            {"debut": dispo.debut.isoformat(), "fin": dispo.fin.isoformat()} for dispo in disponibilites
        ],
        "formations_indisponibles": _formations_indisponibles_payload(formations),
        "affectations": [
            {
                "debut": timezone.localtime(affectation.debut).date().isoformat(),
                "fin": timezone.localtime(affectation.fin).date().isoformat(),
                "centre_id": affectation.centre_id,
            }
            for affectation in affectations
        ],
        "situation_semaine": getattr(animateur, "_situation_semaine", None),
    }


def _jour_dans_ouverture(ouverture):
    """Retourne une date réelle de la période correspondant au jour ouvert."""

    debut = ouverture.periode_calendrier.debut
    decalage = (int(ouverture.jour_semaine) - debut.weekday()) % 7
    jour = debut + datetime.timedelta(days=decalage)
    return jour if jour <= ouverture.periode_calendrier.fin else None


def _periodes_vacances_resume(periodes):
    groupes = {}
    for periode in sorted(periodes, key=lambda item: (item.debut, item.id)):
        cle = (periode.categorie_vacances, periode.debut.year)
        numero = re.search(r"Semaine\s+(\d+)", periode.nom, flags=re.IGNORECASE)
        ligne = groupes.setdefault(cle, {"nom": f"{cle[0]} {cle[1]}", "semaines": []})
        if numero:
            ligne["semaines"].append(f"S{numero.group(1)}")
        elif periode.libelle_avec_annee not in ligne["semaines"]:
            ligne["semaines"].append(periode.libelle_avec_annee)
    return list(groupes.values())


def _ratio_reglementaire_accueil(accueil, evenement, *, modalite=None, ouverture=None, structure=None):
    """Délègue le taux affiché au même moteur que le calcul réglementaire."""

    from animateurs.services.categories_groupes import categorie_reglementaire_groupe
    from animateurs.services.reglementation_encadrement import ratio_reglementaire

    jour = _jour_dans_ouverture(ouverture) if ouverture is not None else None
    if accueil.type_accueil.code == TypeAccueil.PERISCOLAIRE and jour is None:
        return None
    duree_accueil = None
    if ouverture is not None:
        debut = ouverture.heure_debut_effective
        fin = ouverture.heure_fin_effective
        if debut is not None and fin is not None:
            duree_accueil = max(0, (fin.hour * 60 + fin.minute) - (debut.hour * 60 + debut.minute)) / 60
    return ratio_reglementaire(
        type_accueil=accueil.type_accueil,
        categorie_age=categorie_reglementaire_groupe(evenement),
        centre=accueil.centre,
        jour=jour,
        modalite=modalite,
        accueil_centre=accueil,
        structure=structure,
        duree_accueil=duree_accueil,
    )


def _resume_encadrement_groupes(accueil, groupes, ouvertures, *, structure=None):
    from animateurs.services.besoins_encadrement import regle_encadrement_effective

    resultats = []
    ouvertures_par_modalite = {}
    for ouverture in ouvertures:
        ouvertures_par_modalite.setdefault(ouverture.modalite_periscolaire_id, []).append(ouverture)

    for evenement in groupes:
        regles_prefetches = getattr(evenement, "_centres_payload_besoins_encadrement", None)
        if regles_prefetches is None:
            regles_prefetches = getattr(evenement, "_prefetched_objects_cache", {}).get(
                "besoins_encadrement"
            )
        regles = (
            [regle for regle in regles_prefetches if regle.type_accueil_id == accueil.type_accueil_id]
            if regles_prefetches is not None
            else list(evenement.besoins_encadrement.filter(type_accueil=accueil.type_accueil))
        )
        ligne = {"nom": evenement.nom, "resume": "À configurer", "details": [], "exigences": []}
        if not regles:
            resultats.append(ligne)
            continue

        modes = {regle.mode_calcul for regle in regles}
        valeurs_references = [regle.effectif_enfants_reference for regle in regles]
        references = {int(valeur) for valeur in valeurs_references if valeur is not None}
        reference = (
            next(iter(references))
            if len(references) == 1 and all(valeur is not None for valeur in valeurs_references)
            else None
        )
        suffixe_reference = f" · Effectif de référence : {reference} enfants" if reference is not None else ""

        def ajouter_references_contextuelles():
            if reference is not None:
                return
            for regle in regles:
                if regle.effectif_enfants_reference is None:
                    continue
                contexte = regle.modalite_periscolaire.nom if regle.modalite_periscolaire_id else "Par défaut"
                ligne["details"].append({
                    "contexte": contexte,
                    "texte": f"Effectif de référence : {regle.effectif_enfants_reference} enfants",
                })

        if modes == {BesoinEncadrement.MODE_MANUEL}:
            postes = {int(regle.effectif_cible) for regle in regles}
            if len(postes) == 1:
                nombre = next(iter(postes))
                ligne["resume"] = f"{nombre} poste{'s' if nombre > 1 else ''} requis{suffixe_reference}"
                ajouter_references_contextuelles()
            else:
                ligne["resume"] = "Postes définis selon les créneaux"
                for regle in regles:
                    contexte = regle.modalite_periscolaire.nom if regle.modalite_periscolaire_id else "Par défaut"
                    texte = f"{regle.effectif_cible} poste{'s' if regle.effectif_cible > 1 else ''} requis"
                    if regle.effectif_enfants_reference is not None:
                        texte += f" · Effectif de référence : {regle.effectif_enfants_reference} enfants"
                    ligne["details"].append({"contexte": contexte, "texte": texte})
        elif modes == {BesoinEncadrement.MODE_REGLEMENTAIRE}:
            taux_contextes = []
            if accueil.type_accueil.code == TypeAccueil.VACANCES:
                taux = _ratio_reglementaire_accueil(accueil, evenement, structure=structure)
                if taux:
                    taux_contextes.append(("", int(taux)))
            else:
                for modalite_id, lignes_ouverture in ouvertures_par_modalite.items():
                    modalite = lignes_ouverture[0].modalite_periscolaire
                    taux_par_ouverture = []
                    for ouverture in lignes_ouverture:
                        regle_effective = regle_encadrement_effective(
                            evenement,
                            type_accueil=accueil.type_accueil,
                            modalite=modalite,
                            periode_calendrier=ouverture.periode_calendrier,
                        )
                        if (
                            regle_effective is None
                            or regle_effective.mode_calcul != BesoinEncadrement.MODE_REGLEMENTAIRE
                        ):
                            continue
                        taux = _ratio_reglementaire_accueil(
                            accueil, evenement, modalite=modalite, ouverture=ouverture, structure=structure
                        )
                        if taux:
                            taux_par_ouverture.append((ouverture, int(taux)))
                    taux_vus = {taux for _ouverture, taux in taux_par_ouverture}
                    if len(taux_vus) == 1:
                        taux_contextes.append((modalite.nom, next(iter(taux_vus))))
                    else:
                        couples_vus = set()
                        for ouverture, taux in taux_par_ouverture:
                            cle = (ouverture.periode_calendrier_id, taux)
                            if cle in couples_vus:
                                continue
                            couples_vus.add(cle)
                            contexte = f"{modalite.nom} · {ouverture.periode_calendrier.nom}"
                            taux_contextes.append((contexte, taux))
            taux_distincts = {taux for _contexte, taux in taux_contextes}
            ligne["resume"] = "Calcul réglementaire"
            if len(taux_distincts) == 1:
                ligne["resume"] += f" · Taux appliqué : 1 / {next(iter(taux_distincts))}"
            elif len(taux_distincts) > 1:
                ligne["details"] = [
                    {"contexte": contexte, "texte": f"Taux appliqué : 1 / {taux}"}
                    for contexte, taux in taux_contextes
                ]
            ligne["resume"] += suffixe_reference
            ajouter_references_contextuelles()
        else:
            ligne["resume"] = "Selon les créneaux"
            for regle in regles:
                contexte = regle.modalite_periscolaire.nom if regle.modalite_periscolaire_id else "Par défaut"
                if regle.mode_calcul == BesoinEncadrement.MODE_MANUEL:
                    texte = f"{regle.effectif_cible} poste{'s' if regle.effectif_cible > 1 else ''} requis"
                else:
                    ouverture = next(iter(ouvertures_par_modalite.get(regle.modalite_periscolaire_id, [])), None)
                    taux = _ratio_reglementaire_accueil(
                        accueil, evenement,
                        modalite=regle.modalite_periscolaire if regle.modalite_periscolaire_id else None,
                        ouverture=ouverture, structure=structure,
                    )
                    texte = "Calcul réglementaire" + (f" · 1 / {taux}" if taux else "")
                if regle.effectif_enfants_reference is not None:
                    texte += f" · Effectif de référence : {regle.effectif_enfants_reference} enfants"
                ligne["details"].append({"contexte": contexte, "texte": texte})

        ligne["exigences"] = _exigences_contextuelles_moderne(evenement)
        resultats.append(ligne)
    return resultats


def _accueils_centre_payload(centre, *, structure=None):
    accueils_precharges = getattr(centre, "_centres_payload_accueils", None)
    if accueils_precharges is None:
        accueils_precharges = getattr(centre, "_prefetched_objects_cache", {}).get("accueils")
    accueils = list(accueils_precharges) if accueils_precharges is not None else list(
        centre.accueils.select_related("type_accueil").all()
    )
    resultats = []
    for accueil in accueils:
        groupes = list(getattr(
            accueil,
            "_centres_payload_groupes",
            accueil.groupes.select_related("groupe").prefetch_related(
                "periodes_scolaires", "besoins_encadrement", "types_accueil"
            ).order_by("ordre", "nom"),
        ))
        periodes = {}
        jours = set()
        modes = set()
        for groupe in groupes:
            jours.update(int(numero) for numero in (groupe.jours_ouverts or []))
            for periode in groupe.periodes_scolaires.all():
                periodes[periode.id] = periode
            for besoin in getattr(
                groupe, "_centres_payload_besoins_encadrement", groupe.besoins_encadrement.all()
            ):
                if besoin.type_accueil_id != accueil.type_accueil_id:
                    continue
                modes.add(besoin.mode_calcul)
        ouvertures = list(getattr(
            accueil,
            "_centres_payload_ouvertures",
            accueil.ouvertures_periodes.select_related("modalite_periscolaire", "periode_calendrier")
            .filter(actif=True)
            .order_by("periode_calendrier__debut", "modalite_periscolaire__ordre", "jour_semaine"),
        ))
        if accueil.type_accueil.code == TypeAccueil.PERISCOLAIRE:
            # Les jours du Périscolaire viennent des ouvertures réelles de
            # l'accueil, pas des anciens jours génériques portés par le groupe.
            jours = {int(ouverture.jour_semaine) for ouverture in ouvertures}
        modalites = []
        vus = set()
        for ouverture in ouvertures:
            cle = ouverture.modalite_periscolaire_id
            if cle in vus:
                continue
            vus.add(cle)
            modalites.append({
                "id": ouverture.modalite_periscolaire_id,
                "code": ouverture.modalite_periscolaire.code,
                "nom": ouverture.modalite_periscolaire.nom,
            })
        if not modes:
            encadrement = "À configurer"
        elif modes == {"reglementaire"}:
            encadrement = "Calcul réglementaire"
        elif modes == {"manuel"}:
            encadrement = "Postes définis manuellement"
        else:
            encadrement = "Selon les groupes / créneaux"
        resultats.append({
            "id": accueil.id,
            "type_accueil_id": accueil.type_accueil_id,
            "type_accueil_code": accueil.type_accueil.code,
            "type_accueil_nom": accueil.type_accueil.nom,
            "libelle": accueil.libelle,
            "nom_affichage": accueil.nom_affichage,
            "date_debut": accueil.date_debut.isoformat() if accueil.date_debut else "",
            "date_fin": accueil.date_fin.isoformat() if accueil.date_fin else "",
            "pedt_applicable": bool(accueil.pedt_applicable),
            "statut": accueil.statut,
            "libelle_analytique": accueil.libelle_analytique,
            "groupes": [{"id": groupe.id, "groupe_id": groupe.groupe_id, "nom": groupe.nom} for groupe in groupes],
            "groupes_noms": [groupe.nom for groupe in groupes],
            "nb_groupes": len(groupes),
            "jours_ouverts": sorted(jours),
            "periodes_noms": [periode.libelle_avec_annee for periode in periodes.values()],
            "periodes_ouvertes": _periodes_vacances_resume(periodes.values()),
            "modalites_periscolaires": modalites,
            "modalites_noms": [modalite["nom"] for modalite in modalites],
            "encadrement_resume": encadrement,
            "encadrement_groupes": _resume_encadrement_groupes(
                accueil, groupes, ouvertures, structure=structure
            ),
        })
    return resultats


def _resume_encadrement_moderne(evenement):
    """Résume l'encadrement sans consulter les champs historiques du groupe."""

    accueil = evenement.accueil_centre
    regles_prefetches = getattr(evenement, "_centres_payload_besoins_encadrement", None)
    if regles_prefetches is None:
        regles_prefetches = getattr(evenement, "_prefetched_objects_cache", {}).get(
            "besoins_encadrement"
        )
    regles = (
        [regle for regle in regles_prefetches if regle.type_accueil_id == accueil.type_accueil_id]
        if regles_prefetches is not None
        else list(
            evenement.besoins_encadrement.filter(type_accueil=accueil.type_accueil)
            .select_related("modalite_periscolaire", "periode_calendrier")
        )
    )
    if not regles:
        return "À configurer"

    modes = {regle.mode_calcul for regle in regles}
    if modes == {"reglementaire"}:
        resume = "Calcul réglementaire"
    elif modes == {"manuel"}:
        nombres = {int(regle.effectif_cible) for regle in regles}
        if len(nombres) == 1:
            nombre = nombres.pop()
            resume = f"{nombre} animateur{'s' if nombre > 1 else ''} requis"
        else:
            resume = "Postes définis selon les créneaux"
    else:
        resume = "Selon les créneaux"

    if accueil.type_accueil.code == "periscolaire" and accueil.pedt_applicable:
        resume += " · PEDT"
    return resume


def _exigences_contextuelles_moderne(evenement):
    """Retourne uniquement les exigences rattachées au type de l'accueil."""

    accueil = evenement.accueil_centre
    regles_prefetches = getattr(evenement, "_centres_payload_besoins_encadrement", None)
    if regles_prefetches is None:
        regles_prefetches = getattr(evenement, "_prefetched_objects_cache", {}).get(
            "besoins_encadrement"
        )
    regles = (
        [regle for regle in regles_prefetches if regle.type_accueil_id == accueil.type_accueil_id]
        if regles_prefetches is not None
        else list(
            evenement.besoins_encadrement.filter(type_accueil=accueil.type_accueil)
            .select_related("modalite_periscolaire", "periode_calendrier")
        )
    )
    contextes_valides = {
        (regle.modalite_periscolaire_id, regle.periode_calendrier_id): regle
        for regle in regles
    }
    besoins_prefetches = getattr(evenement, "_centres_payload_besoins_qualifications", None)
    if besoins_prefetches is None:
        besoins_prefetches = getattr(evenement, "_prefetched_objects_cache", {}).get(
            "besoins_qualifications"
        )
    besoins = (
        [besoin for besoin in besoins_prefetches if besoin.type_accueil_id == accueil.type_accueil_id]
        if besoins_prefetches is not None
        else evenement.besoins_qualifications.filter(
            type_accueil=accueil.type_accueil,
        ).select_related("qualification", "modalite_periscolaire", "periode_calendrier")
    )
    resultats = []
    for besoin in besoins:
        cle = (besoin.modalite_periscolaire_id, besoin.periode_calendrier_id)
        regle = contextes_valides.get(cle)
        if regle is None:
            continue
        contexte = []
        if besoin.modalite_periscolaire_id:
            contexte.append(besoin.modalite_periscolaire.nom)
        if besoin.periode_calendrier_id:
            contexte.append(besoin.periode_calendrier.nom)
        libelle = f"{besoin.nombre_minimum} × {besoin.qualification.nom}"
        if contexte:
            libelle += f" ({' · '.join(contexte)})"
        resultats.append(libelle)
    return resultats


def centre_to_dict(centre, *, structure=None):
    types = [type_accueil for type_accueil in centre.types_accueil.all() if type_accueil.actif]
    return {
        "id": centre.id,
        "nom": centre.nom,
        "code": centre.code,
        "adresse": centre.adresse,
        "code_postal": centre.code_postal,
        "commune": centre.commune,
        "code_insee": centre.code_insee,
        "latitude": float(centre.latitude) if centre.latitude is not None else None,
        "longitude": float(centre.longitude) if centre.longitude is not None else None,
        "precision_localisation": centre.precision_localisation,
        "couleur": centre.couleur,
        "effectif_cible": centre.effectif_cible,
        "type_accueil_codes": [type_accueil.code for type_accueil in types],
        "types_accueil": [{"code": type_accueil.code, "nom": type_accueil.nom} for type_accueil in types],
        "accueils": _accueils_centre_payload(centre, structure=structure),
        "ordre": centre.ordre,
    }


def evenement_to_dict(
    evenement,
    *,
    include_effectifs=True,
    type_accueil=None,
    modalite_periscolaire=None,
    periode_calendrier=None,
):
    besoins_prefetches = getattr(evenement, "_prefetched_objects_cache", {}).get("besoins_qualifications")
    besoins = (
        list(besoins_prefetches)
        if besoins_prefetches is not None
        else list(evenement.besoins_qualifications.select_related("qualification").all())
    )
    nb_affectations = (
        evenement.nb_affectations
        if hasattr(evenement, "nb_affectations")
        else evenement.affectations.count()
    )
    periodes = list(evenement.periodes_scolaires.all())
    effectifs_enfants = list(evenement.effectifs_enfants.all()) if include_effectifs else []
    moderne = bool(evenement.accueil_centre_id)
    besoin_effectif = besoin_encadrement_effectif(
        evenement,
        type_accueil=type_accueil,
        modalite=modalite_periscolaire,
        periode_calendrier=periode_calendrier,
    )
    besoins_effectifs = list(besoin_effectif.qualifications)
    besoins_generiques = [
        besoin for besoin in besoins
        if besoin.type_accueil_id is None
        and besoin.modalite_periscolaire_id is None
        and getattr(besoin, "periode_calendrier_id", None) is None
    ]
    codes_types_accueil = (
        [evenement.accueil_centre.type_accueil.code]
        if evenement.accueil_centre_id
        else [
            type_accueil.code
            for type_accueil in evenement.types_accueil.all()
            if type_accueil.actif
        ]
    )
    return {
        "id": evenement.id,
        "groupe_id": evenement.groupe_id,
        "accueil_centre_id": evenement.accueil_centre_id,
        "accueil_nom": evenement.accueil_centre.nom_affichage if evenement.accueil_centre_id else "",
        "type_accueil_code": (
            evenement.accueil_centre.type_accueil.code
            if evenement.accueil_centre_id
            else None
        ),
        "groupe_type": evenement.groupe.type_groupe if evenement.groupe_id else "structure",
        "groupe_date_debut_validite": (
            evenement.groupe.date_debut_validite.isoformat()
            if evenement.groupe_id and evenement.groupe.date_debut_validite else ""
        ),
        "groupe_date_fin_validite": (
            evenement.groupe.date_fin_validite.isoformat()
            if evenement.groupe_id and evenement.groupe.date_fin_validite else ""
        ),
        "centre_id": evenement.centre_id,
        "nom": evenement.nom,
        "permanent": evenement.permanent,
        # Pour une instance moderne, AccueilCentre est la source de vérité,
        # même si le M2M historique contient encore une valeur incohérente.
        "type_accueil_codes": codes_types_accueil,
        "modalite_periscolaire": (evenement.modalite_periscolaire.code if evenement.modalite_periscolaire_id else None),
        "modalite_periscolaire_nom": (evenement.modalite_periscolaire.nom if evenement.modalite_periscolaire_id else None),
        "periode_ids": [periode.id for periode in periodes],
        "periodes": [
            {
                "id": periode.id,
                "nom": periode.nom,
                "libelle": periode.libelle_avec_annee,
                "annee_scolaire": periode.annee_scolaire,
                "zone": periode.zone,
                "debut": periode.debut.isoformat(),
                "fin": periode.fin.isoformat(),
                "fin_ouverture": evenement.fin_ouverture_periode(periode).isoformat(),
            }
            for periode in periodes
        ],
        "ferme_jours_feries": evenement.ferme_jours_feries,
        "dates_feriees_fermees": sorted(
            {
                jour.isoformat()
                for periode in periodes
                for annee in range(periode.debut.year, evenement.fin_ouverture_periode(periode).year + 1)
                for jour in jours_feries_france(annee)
                if evenement.ferme_jours_feries and periode.debut <= jour <= evenement.fin_ouverture_periode(periode)
            }
        ),
        "effectif_cible": besoin_effectif.effectif_cible,
        "effectif_cible_base": evenement.effectif_cible,
        "encadrement_resume": _resume_encadrement_moderne(evenement) if moderne else "",
        "exigences_particulieres_libelle": (
            _exigences_contextuelles_moderne(evenement) if moderne else []
        ),
        "besoin_encadrement_personnalise": besoin_effectif.personnalise,
        "enfants_par_animateur_defaut": evenement.enfants_par_animateur_defaut,
        # Les écrans de gestion conservent la liste complète. Le chargement
        # groupé du Planning passe ``include_effectifs=False`` puis récupère
        # uniquement la semaine visible via l'endpoint dédié.
        "effectifs_enfants": [
            {
                "date": effectif.date.isoformat(),
                "nombre": effectif.nombre,
                "enfants_par_animateur": effectif.ratio_encadrement_effectif,
                "ratio_encadrement_exceptionnel": effectif.ratio_encadrement_exceptionnel,
                "heure_arrivee": effectif.heure_arrivee.strftime("%H:%M") if effectif.heure_arrivee else "",
                "heure_depart": effectif.heure_depart.strftime("%H:%M") if effectif.heure_depart else "",
                "type_accueil": effectif.type_accueil.code if effectif.type_accueil_id else None,
                "modalite_periscolaire": (
                    effectif.modalite_periscolaire.code if effectif.modalite_periscolaire_id else None
                ),
            }
            for effectif in effectifs_enfants
        ],
        "jours_ouverts": [int(numero) for numero in (evenement.jours_ouverts or [])],
        "dates_exclues": [fermeture.date.isoformat() for fermeture in evenement.dates_exclues.all()],
        "ordre": evenement.ordre,
        "qualifications_requises": {str(b.qualification_id): b.nombre_minimum for b in besoins_generiques},
        "qualifications_libelle": [f"{b.nombre_minimum} × {b.qualification.nom}" for b in besoins_effectifs],
        "qualifications_requises_effectives": {
            str(b.qualification_id): b.nombre_minimum for b in besoins_effectifs
        },
        "besoins_encadrement": besoins_contextuels_payload(evenement),
        "nb_affectations": nb_affectations,
        "peut_supprimer": nb_affectations == 0,
        "a_des_periodes": evenement.permanent or bool(periodes),
    }


def qualification_to_dict(qualification):
    statut_couleur = qualification if qualification.est_statut else qualification.statut
    couleur = couleur_pour_statut(statut_couleur)
    return {
        "id": qualification.id,
        "nom": qualification.nom,
        "selectionnable_remplissage_auto": qualification.selectionnable_remplissage_auto,
        "est_statut": qualification.est_statut,
        "statut_id": qualification.statut_id,
        "statut_nom": qualification.statut.nom if qualification.statut_id else "",
        "icone": qualification.icone,
        "couleur_statut": couleur,
        "couleur_texte_statut": couleur_texte_pour_fond(couleur),
    }


def document_to_dict(document):
    periodes = list(document.periodes.all())
    centres = list(document.centres.all())
    return {
        "id": document.id,
        "titre": document.titre,
        "url": document.fichier.url,
        "type_document": document.type_document,
        "type_document_libelle": document.get_type_document_display(),
        "date_ajout": document.date_ajout.isoformat(),
        "publie": document.publie,
        "permanent": document.permanent,
        "periode_debut": document.periode_debut.isoformat() if document.periode_debut else None,
        "periode_fin": document.periode_fin.isoformat() if document.periode_fin else None,
        "libelle_periode": document.libelle_periode,
        "periode_ids": [periode.id for periode in periodes],
        "tous_centres": document.tous_centres,
        "centre_ids": [centre.id for centre in centres],
        "centres": [{"id": centre.id, "nom": centre.nom, "code": centre.code} for centre in centres],
        "periodes": [
            {
                "id": periode.id,
                "nom": periode.nom,
                "libelle": periode.libelle_avec_annee,
                "debut": periode.debut.isoformat(),
                "fin": periode.fin.isoformat(),
                "annee_scolaire": periode.annee_scolaire,
                "vacances": periode.categorie_vacances,
            }
            for periode in periodes
        ],
    }
