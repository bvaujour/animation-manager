"""Sérialisation JSON centralisée des modèles de l'application."""

from animateurs.models import jours_feries_france


def affectation_to_event(affectation):
    return {
        "id": affectation.id,
        "title": f"{affectation.animateur.prenom} {affectation.animateur.nom[0]}.",
        "start": affectation.debut.isoformat(),
        "end": affectation.fin.isoformat(),
        "allDay": True,
        "backgroundColor": affectation.animateur.couleur,
        "borderColor": affectation.animateur.couleur,
        "textColor": "#ffffff",
        "extendedProps": {
            "animateur_id": affectation.animateur_id,
            "centre_id": affectation.centre_id,
            # Noms modernes et alias historiques pour ne pas casser un ancien cache JS.
            "groupe_id": affectation.evenement_id,
            "groupe_nom": affectation.evenement.nom,
            "evenement_id": affectation.evenement_id,
            "evenement_nom": affectation.evenement.nom,
        },
    }


def animateur_to_dict(animateur):
    qualifications = list(animateur.qualifications.all())
    preferences = list(animateur.preferences.all())
    disponibilites = list(animateur.disponibilites.all())

    pref_relation = next((pref for pref in preferences if pref.est_prefere), None)
    secondaires_relations = [pref for pref in preferences if not pref.est_prefere]

    def centre_dict(pref):
        return {
            "id": pref.centre_id,
            "nom": pref.centre.nom,
            "code": pref.centre.code,
            "couleur": pref.centre.couleur,
        }

    centre_prefere = centre_dict(pref_relation) if pref_relation else None
    centres_secondaires = [centre_dict(pref) for pref in secondaires_relations]
    centres_autorises = ([centre_prefere] if centre_prefere else []) + centres_secondaires

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
        "age": animateur.age,
        "couleur": animateur.couleur,
        "qualification_ids": [q.id for q in qualifications],
        "qualifications": [q.nom for q in qualifications],
        "centre_prefere": centre_prefere,
        "centres_secondaires": centres_secondaires,
        # Champ conservé pour compatibilité avec les écrans qui attendent encore
        # une liste globale. Le centre préféré est toujours placé en premier.
        "centres_autorises": centres_autorises,
        "evenement_preferee": evenement_preferee,
        "evenement_preferee_id": evenement_preferee["id"] if evenement_preferee else None,
        "disponibilites": [
            {"debut": dispo.debut.isoformat(), "fin": dispo.fin.isoformat()}
            for dispo in disponibilites
        ],
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



def evenement_to_dict(evenement):
    besoins = list(evenement.besoins_qualifications.select_related("qualification").all())
    nb_affectations = getattr(evenement, "nb_affectations", evenement.affectations.count())
    periodes = list(evenement.periodes_scolaires.all())
    return {
        "id": evenement.id,
        "centre_id": evenement.centre_id,
        "nom": evenement.nom,
        "debut": evenement.debut.isoformat() if evenement.debut else None,
        "fin": evenement.fin.isoformat() if evenement.fin else None,
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
        "dates_feriees_fermees": sorted({
            jour.isoformat()
            for periode in periodes
            for annee in range(periode.debut.year, evenement.fin_ouverture_periode(periode).year + 1)
            for jour in jours_feries_france(annee)
            if evenement.ferme_jours_feries and periode.debut <= jour <= evenement.fin_ouverture_periode(periode)
        }),
        "effectif_cible": evenement.effectif_cible,
        "jours_ouverts": [int(numero) for numero in (evenement.jours_ouverts or [])],
        "dates_exclues": [fermeture.date.isoformat() for fermeture in evenement.dates_exclues.all()],
        "ordre": evenement.ordre,
        "qualifications_requises": {
            str(b.qualification_id): b.nombre_minimum for b in besoins
        },
        "qualifications_libelle": [
            f"{b.nombre_minimum} × {b.qualification.nom}" for b in besoins
        ],
        "nb_affectations": nb_affectations,
        "peut_supprimer": nb_affectations == 0,
        "a_des_periodes": bool(periodes),
    }


def qualification_to_dict(qualification):
    return {
        "id": qualification.id,
        "nom": qualification.nom,
        "selectionnable_remplissage_auto": qualification.selectionnable_remplissage_auto,
    }


def document_to_dict(document):
    return {
        "id": document.id,
        "titre": document.titre,
        "url": document.fichier.url,
        "date_ajout": document.date_ajout.isoformat(),
        "permanent": document.permanent,
        "periode_debut": document.periode_debut.isoformat() if document.periode_debut else None,
        "periode_fin": document.periode_fin.isoformat() if document.periode_fin else None,
        "libelle_periode": document.libelle_periode,
    }
