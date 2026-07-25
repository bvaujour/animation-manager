import datetime
import math
from collections import defaultdict

from django.utils import timezone

from animateurs.models import Affectation, Animateur, EffectifEnfantsJour, Sortie, SortieResponsabilite
from animateurs.services.flottants import est_groupe_flottants
from animateurs.services.status_colors import statut_payload


def _bornes_jour(jour):
    debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
    return debut, debut + datetime.timedelta(days=1)


def _animateur_dict(animateur, **complements):
    """Payload commun d'un salarié, avec la couleur de son statut."""

    statut = statut_payload(list(animateur.qualifications.all()))
    resultat = {
        "id": animateur.id,
        "nom": str(animateur),
        "telephone": animateur.telephone or "",
        "email": animateur.email or "",
        **statut,
    }
    resultat.update(complements)
    return resultat


def animateurs_eligibles_responsabilites(sortie: Sortie):
    """Retourne uniquement les salariés pouvant devenir responsables.

    Sont proposés :
    - les animateurs affectés le jour de la sortie à l'un des groupes
      participants ou, plus largement, dans l'un des lieux concernés ;
    - les animateurs disponibles ce jour-là et sans aucune affectation.

    Un animateur affecté ailleurs dans un lieu non concerné n'est donc jamais
    proposé, même s'il travaille le même jour.
    """

    participations = list(
        sortie.participations.select_related("evenement__centre").order_by(
            "evenement__centre__ordre", "evenement__ordre", "evenement__nom"
        )
    )
    ids_groupes = {item.evenement_id for item in participations}
    ids_centres = {item.evenement.centre_id for item in participations}
    debut, fin = _bornes_jour(sortie.date)

    affectations_jour = list(
        Affectation.objects.filter(debut__lt=fin, fin__gt=debut)
        .select_related("animateur", "centre", "evenement")
        .prefetch_related("animateur__qualifications")
        .order_by("animateur__nom", "animateur__prenom", "id")
    )
    ids_affectes_jour = {item.animateur_id for item in affectations_jour}
    affectations_concernees = defaultdict(list)
    animateurs_affectes = {}
    for affectation in affectations_jour:
        if affectation.evenement_id not in ids_groupes and affectation.centre_id not in ids_centres:
            continue
        animateurs_affectes[affectation.animateur_id] = affectation.animateur
        if est_groupe_flottants(affectation.evenement):
            libelle = f"Flottant — {affectation.centre.nom}"
        else:
            libelle = f"{affectation.centre.nom} — {affectation.evenement.nom}"
        if libelle not in affectations_concernees[affectation.animateur_id]:
            affectations_concernees[affectation.animateur_id].append(libelle)

    disponibles_libres = list(
        Animateur.objects.filter(
            disponibilites__debut__lte=sortie.date,
            disponibilites__fin__gte=sortie.date,
        )
        .exclude(pk__in=ids_affectes_jour)
        .prefetch_related("qualifications")
        .distinct()
        .order_by("nom", "prenom", "id")
    )

    resultat = []
    for animateur in sorted(
        animateurs_affectes.values(), key=lambda item: (item.nom.casefold(), item.prenom.casefold(), item.id)
    ):
        details = affectations_concernees[animateur.id]
        resultat.append(
            _animateur_dict(
                animateur,
                eligibilite="affecte",
                eligibilite_libelle="Affecté à la sortie",
                situation=" · ".join(details),
                affectations_concernees=details,
            )
        )
    for animateur in disponibles_libres:
        resultat.append(
            _animateur_dict(
                animateur,
                eligibilite="disponible",
                eligibilite_libelle="Disponible et non affecté",
                situation="Disponible — non affecté ce jour",
                affectations_concernees=[],
            )
        )
    return resultat


def calculer_participants_sortie(jour, evenements, activites=None):
    """Calcule les données issues du Planning pour une date et des groupes.

    Rien n'est copié dans ``Sortie`` : effectifs, taux, équipes fixes et
    flottants sont relus à chaque appel afin que la fiche reste toujours
    synchronisée avec le Planning.
    """

    activites = activites or {}
    evenements = sorted(
        list(evenements),
        key=lambda item: (item.centre.ordre, item.centre.nom, item.ordre, item.nom),
    )
    ids_evenements = {item.id for item in evenements}
    ids_centres = {item.centre_id for item in evenements}

    effectifs = {
        item.evenement_id: item
        for item in EffectifEnfantsJour.objects.filter(evenement_id__in=ids_evenements, date=jour).select_related(
            "evenement"
        )
    }

    debut, fin = _bornes_jour(jour)
    affectations = list(
        Affectation.objects.filter(centre_id__in=ids_centres, debut__lt=fin, fin__gt=debut)
        .select_related("animateur", "evenement", "evenement__groupe", "centre")
        .prefetch_related("animateur__qualifications")
        .order_by("animateur__nom", "animateur__prenom", "id")
    )

    fixes = defaultdict(dict)
    flottants = defaultdict(dict)
    centres = {item.centre_id: item.centre for item in evenements}
    for affectation in affectations:
        if est_groupe_flottants(affectation.evenement):
            flottants[affectation.centre_id][affectation.animateur_id] = affectation.animateur
        elif affectation.evenement_id in ids_evenements:
            fixes[affectation.evenement_id][affectation.animateur_id] = affectation.animateur

    lignes = []
    reliquats_par_centre = defaultdict(list)
    animateurs_utilises = {}

    for evenement in evenements:
        ligne_effectif = effectifs.get(evenement.id)
        nombre = ligne_effectif.nombre if ligne_effectif else 0
        ratio = (
            ligne_effectif.ratio_encadrement_effectif
            if ligne_effectif
            else evenement.enfants_par_animateur_defaut
        )
        ratio = max(1, int(ratio or 1))
        animateurs_groupe = list(fixes[evenement.id].values())
        animateurs_utilises.update({item.id: item for item in animateurs_groupe})
        restant = max(0, nombre - len(animateurs_groupe) * ratio)
        ligne = {
            "evenement_id": evenement.id,
            "centre_id": evenement.centre_id,
            "centre": evenement.centre.nom,
            "groupe": evenement.nom,
            "effectif": nombre,
            "effectif_renseigne": ligne_effectif is not None,
            "ratio": ratio,
            "ratio_libelle": f"1/{ratio}",
            "animateurs_requis": math.ceil(nombre / ratio) if nombre else 0,
            "animateurs": [_animateur_dict(item) for item in animateurs_groupe],
            "activite_horaire": str(activites.get(evenement.id, "") or ""),
            "non_couverts": restant,
        }
        lignes.append(ligne)
        reliquats_par_centre[evenement.centre_id].append({"ligne": ligne, "restant": restant})

    flottants_utilises = defaultdict(list)
    for centre_id, reliquats in reliquats_par_centre.items():
        for animateur in flottants[centre_id].values():
            restants = [item for item in reliquats if item["restant"] > 0]
            if not restants:
                break

            # Le flottant prend le taux le plus contraignant encore présent,
            # puis répartit sa capacité entre les reliquats du même lieu.
            capacite = min(item["ligne"]["ratio"] for item in restants)
            flottants_utilises[centre_id].append(animateur)
            animateurs_utilises[animateur.id] = animateur
            for item in sorted(
                restants,
                key=lambda value: (value["ligne"]["ratio"], value["ligne"]["evenement_id"]),
            ):
                couverts = min(capacite, item["restant"])
                item["restant"] -= couverts
                capacite -= couverts
                if capacite <= 0:
                    break

    for reliquats in reliquats_par_centre.values():
        for item in reliquats:
            item["ligne"]["non_couverts"] = item["restant"]
            item["ligne"]["couverture"] = "insuffisant" if item["restant"] else "conforme"

    non_couverts = sum(item["restant"] for values in reliquats_par_centre.values() for item in values)
    vigilances = []
    if not lignes:
        vigilances.append("Aucun groupe sélectionné")
    effectifs_manquants = sum(1 for item in lignes if not item["effectif_renseigne"])
    if effectifs_manquants:
        vigilances.append(
            f"Effectif non renseigné pour {effectifs_manquants} groupe"
            f"{'s' if effectifs_manquants > 1 else ''}"
        )
    if lignes and not animateurs_utilises:
        vigilances.append("Aucun animateur affecté")
    if non_couverts:
        pluriel = non_couverts > 1
        vigilances.append(
            f"Encadrement insuffisant : {non_couverts} enfant{'s' if pluriel else ''} "
            f"non couvert{'s' if pluriel else ''}"
        )

    flottants_par_centre = []
    for centre_id, animateurs in flottants_utilises.items():
        flottants_par_centre.append(
            {
                "centre_id": centre_id,
                "centre": centres[centre_id].nom,
                "animateurs": [_animateur_dict(item) for item in animateurs],
            }
        )
    flottants_par_centre.sort(key=lambda item: (centres[item["centre_id"]].ordre, item["centre"]))

    return {
        "totaux": {
            "groupes": len(lignes),
            "enfants": sum(item["effectif"] for item in lignes),
            "animateurs": len(animateurs_utilises),
            "non_couverts": non_couverts,
        },
        "groupes": lignes,
        "flottants_par_centre": flottants_par_centre,
        "animateurs_concernes": [
            _animateur_dict(item)
            for item in sorted(animateurs_utilises.values(), key=lambda animateur: (animateur.nom, animateur.prenom))
        ],
        "vigilances": vigilances,
    }


def _responsabilite_dict(responsabilite):
    resultat = {
        "id": responsabilite.id,
        "type": responsabilite.type,
        "type_libelle": responsabilite.get_type_display(),
        "animateur": _animateur_dict(responsabilite.animateur),
        "centre": None,
        "groupe": None,
        "affectation_creee": bool(responsabilite.affectation_creee_id),
    }
    if responsabilite.centre_id:
        resultat["centre"] = {
            "id": responsabilite.centre_id,
            "nom": responsabilite.centre.nom,
        }
    if responsabilite.evenement_id:
        resultat["groupe"] = {
            "id": responsabilite.evenement_id,
            "nom": responsabilite.evenement.nom,
            "centre_id": responsabilite.evenement.centre_id,
            "centre": responsabilite.evenement.centre.nom,
        }
    return resultat


def donnees_sortie(sortie: Sortie):
    participations = list(
        sortie.participations.select_related("evenement__centre", "evenement__groupe").order_by(
            "evenement__centre__ordre", "evenement__ordre", "evenement__nom"
        )
    )
    evenements = [item.evenement for item in participations]
    activites = {item.evenement_id: item.activite_horaire for item in participations}
    participants = calculer_participants_sortie(sortie.date, evenements, activites)
    responsabilites = list(
        sortie.responsabilites.select_related(
            "animateur", "centre", "evenement", "evenement__centre"
        ).prefetch_related("animateur__qualifications").order_by("ordre", "type", "centre__ordre", "evenement__ordre", "id")
    )

    vigilances = list(participants["vigilances"])
    if not any(item.type == SortieResponsabilite.TYPE_DIRECTION for item in responsabilites):
        vigilances.append("Aucun responsable de direction")
    if not sortie.heure_depart or not sortie.heure_retour:
        vigilances.append("Horaire de départ ou de retour manquant")

    # Les responsables ajoutés à la sortie comptent parmi les adultes, sans
    # double comptage lorsqu'ils sont déjà présents dans le Planning.
    animateurs_adultes = {
        item["id"]: item for item in participants["animateurs_concernes"]
    }
    for responsabilite in responsabilites:
        animateurs_adultes[responsabilite.animateur_id] = _animateur_dict(responsabilite.animateur)

    return {
        "id": sortie.id,
        "nom": sortie.nom,
        "date": sortie.date.isoformat(),
        "destination": sortie.destination,
        "meteo_lieu": {
            "libelle": sortie.meteo_lieu_libelle,
            "adresse": sortie.meteo_adresse,
            "latitude": float(sortie.meteo_latitude) if sortie.meteo_latitude is not None else None,
            "longitude": float(sortie.meteo_longitude) if sortie.meteo_longitude is not None else None,
            "code_departement": sortie.meteo_code_departement,
        },
        "statut": "prete" if not vigilances else "a_completer",
        "totaux": {
            "enfants": participants["totaux"]["enfants"],
            "animateurs": len(animateurs_adultes),
            "non_couverts": participants["totaux"]["non_couverts"],
        },
        "groupes": participants["groupes"],
        "flottants_par_centre": participants["flottants_par_centre"],
        "animateurs_concernes": list(animateurs_adultes.values()),
        "responsabilites": [_responsabilite_dict(item) for item in responsabilites],
        "transport": {
            "mode_transport": sortie.mode_transport,
            "nombre_vehicules": sortie.nombre_vehicules,
            "heure_depart": sortie.heure_depart.isoformat(timespec="minutes") if sortie.heure_depart else "",
            "heure_arrivee": sortie.heure_arrivee.isoformat(timespec="minutes") if sortie.heure_arrivee else "",
            "heure_depart_site": (
                sortie.heure_depart_site.isoformat(timespec="minutes") if sortie.heure_depart_site else ""
            ),
            "heure_retour": sortie.heure_retour.isoformat(timespec="minutes") if sortie.heure_retour else "",
            "trajet_ramassage": sortie.trajet_ramassage,
            "consignes_transport": sortie.consignes_transport,
        },
        "textes": {
            champ: getattr(sortie, champ)
            for champ in (
                "objectifs_pedagogiques",
                "consignes_encadrement",
                "organisation_maternels",
                "organisation_elementaires",
                "repas_gouter",
            )
        },
        "liens": [{"id": item.id, "libelle": item.libelle, "url": item.url} for item in sortie.liens.all()],
        "documents": [{"id": item.id, "titre": item.titre, "url": item.fichier.url} for item in sortie.documents.all()],
        "vigilances": vigilances,
    }
