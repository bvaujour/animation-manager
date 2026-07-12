"""Sérialisation JSON centralisée des modèles de l'application."""


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
