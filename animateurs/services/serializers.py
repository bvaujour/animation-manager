"""Sérialisation JSON centralisée des modèles de l'application."""

from django.utils import timezone

from animateurs.models import jours_feries_france
from animateurs.services.flottants import est_groupe_flottants, type_affectation
from animateurs.services.status_colors import (
    couleur_pour_statut,
    couleur_texte_pour_fond,
    statut_payload,
)


def affectation_to_event(affectation):
    qualifications = list(affectation.animateur.qualifications.all())
    statut = statut_payload(qualifications)
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
    if flottant:
        titre = f"↔ {titre}"
    if len(horaires) == 1:
        plage = next(iter(horaires.values()))
        titre += f" · {plage['heure_arrivee']}–{plage['heure_depart']}"
    debut_local = timezone.localtime(affectation.debut).date()
    fin_locale = timezone.localtime(affectation.fin).date()
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
            "centre_id": affectation.centre_id,
            # Noms modernes et alias historiques pour ne pas casser un ancien cache JS.
            "groupe_id": affectation.evenement_id,
            "groupe_nom": affectation.evenement.nom,
            "evenement_id": affectation.evenement_id,
            "evenement_nom": affectation.evenement.nom,
            "horaires": horaires,
            "type_affectation": type_affectation_valeur,
        },
    }


def animateur_to_dict(animateur):
    qualifications = list(animateur.qualifications.all())
    statut = statut_payload(qualifications)
    preferences = list(animateur.preferences.all())
    disponibilites_source = (
        animateur._filtre_disponibilites
        if hasattr(animateur, "_filtre_disponibilites")
        else animateur.disponibilites.all()
    )
    disponibilites = list(disponibilites_source)
    affectations = list(getattr(animateur, "_filtre_affectations", []))
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

    def centre_dict(pref):
        return {
            "id": pref.centre_id,
            "nom": pref.centre.nom,
            "code": pref.centre.code,
            "couleur": pref.centre.couleur,
        }

    centres_preferes = [centre_dict(pref) for pref in prefere_relations]
    centres_interdits = [centre_dict(pref) for pref in interdites_relations]
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
        "prenom": animateur.prenom,
        "nom": animateur.nom,
        "telephone": animateur.telephone,
        "email": animateur.email,
        "date_naissance": animateur.date_naissance.isoformat() if animateur.date_naissance else None,
        "adresse": animateur.adresse,
        "numero_securite_sociale": animateur.numero_securite_sociale,
        "paie_jour": str(animateur.paie_jour) if animateur.paie_jour is not None else None,
        "age": animateur.age,
        # Couleur historique conservée en base, mais les interfaces utilisent
        # désormais exclusivement la couleur automatique du statut.
        "couleur": statut["couleur_statut"],
        **statut,
        # Les catégories sont ajoutées aux identifiants effectifs pour que les
        # filtres puissent trouver tous les diplômes d'une même famille.
        "qualification_ids": sorted({identifiant for q in qualifications for identifiant in (q.id, q.statut_id) if identifiant}),
        "qualifications": [q.nom for q in qualifications],
        "qualification_icones": [
            {"id": q.id, "nom": q.nom, "icone": q.icone}
            for q in qualifications
            if not q.est_statut and q.icone
        ],
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
        },
    }


def animateur_planning_to_dict(animateur):
    """Version compacte de l'animateur pour la barre latérale du Planning.

    La fiche complète contient des données administratives et l'historique des
    affinités, inutiles pour afficher les badges. Cette sérialisation réduit donc
    le volume JSON et permet de ne charger que les disponibilités/affectations de
    la semaine demandée.
    """

    qualifications = list(animateur.qualifications.all())
    statut = statut_payload(qualifications)
    preferences = list(animateur.preferences.all())
    disponibilites_source = (
        animateur._filtre_disponibilites
        if hasattr(animateur, "_filtre_disponibilites")
        else animateur.disponibilites.all()
    )
    disponibilites = list(disponibilites_source)
    affectations = list(getattr(animateur, "_filtre_affectations", []))

    prefere_relations = [pref for pref in preferences if pref.est_prefere and not pref.est_interdit]
    interdites_relations = [pref for pref in preferences if pref.est_interdit]

    def centre_dict(pref):
        return {
            "id": pref.centre_id,
            "nom": pref.centre.nom,
            "code": pref.centre.code,
            "couleur": pref.centre.couleur,
        }

    centres_preferes = [centre_dict(pref) for pref in prefere_relations]
    centres_interdits = [centre_dict(pref) for pref in interdites_relations]
    centre_prefere = centres_preferes[0] if centres_preferes else None

    return {
        "id": animateur.id,
        "prenom": animateur.prenom,
        "nom": animateur.nom,
        "telephone": animateur.telephone,
        "email": animateur.email,
        "couleur": statut["couleur_statut"],
        **statut,
        "qualification_ids": sorted(
            {identifiant for q in qualifications for identifiant in (q.id, q.statut_id) if identifiant}
        ),
        "qualifications": [q.nom for q in qualifications],
        "qualification_icones": [
            {"id": q.id, "nom": q.nom, "icone": q.icone}
            for q in qualifications
            if not q.est_statut and q.icone
        ],
        "centre_prefere": centre_prefere,
        "centres_preferes": centres_preferes,
        "centres_interdits": centres_interdits,
        "centres_autorises": centres_preferes,
        "disponibilites": [
            {"debut": dispo.debut.isoformat(), "fin": dispo.fin.isoformat()} for dispo in disponibilites
        ],
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


def centre_to_dict(centre):
    return {
        "id": centre.id,
        "nom": centre.nom,
        "code": centre.code,
        "couleur": centre.couleur,
        "effectif_cible": centre.effectif_cible,
        "ordre": centre.ordre,
    }


def evenement_to_dict(evenement, *, include_effectifs=True):
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
    return {
        "id": evenement.id,
        "groupe_id": evenement.groupe_id,
        "centre_id": evenement.centre_id,
        "nom": evenement.nom,
        "permanent": evenement.permanent,
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
        "effectif_cible": evenement.effectif_cible,
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
            }
            for effectif in effectifs_enfants
        ],
        "jours_ouverts": [int(numero) for numero in (evenement.jours_ouverts or [])],
        "dates_exclues": [fermeture.date.isoformat() for fermeture in evenement.dates_exclues.all()],
        "ordre": evenement.ordre,
        "qualifications_requises": {str(b.qualification_id): b.nombre_minimum for b in besoins},
        "qualifications_libelle": [f"{b.nombre_minimum} × {b.qualification.nom}" for b in besoins],
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
    return {
        "id": document.id,
        "titre": document.titre,
        "url": document.fichier.url,
        "date_ajout": document.date_ajout.isoformat(),
        "permanent": document.permanent,
        "periode_debut": document.periode_debut.isoformat() if document.periode_debut else None,
        "periode_fin": document.periode_fin.isoformat() if document.periode_fin else None,
        "libelle_periode": document.libelle_periode,
        "periode_ids": [periode.id for periode in periodes],
        "periodes": [
            {
                "id": periode.id,
                "nom": periode.nom,
                "libelle": periode.libelle_avec_annee,
                "debut": periode.debut.isoformat(),
                "fin": periode.fin.isoformat(),
                "annee_scolaire": periode.annee_scolaire,
                "vacances": periode.vacances,
            }
            for periode in periodes
        ],
    }
