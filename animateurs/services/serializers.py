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
        "centres_autorises": [
            {
                "id": pref.centre_id,
                "nom": pref.centre.nom,
                "code": pref.centre.code,
                "couleur": pref.centre.couleur,
            }
            for pref in preferences
        ],
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
    return {"id": qualification.id, "nom": qualification.nom}


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
