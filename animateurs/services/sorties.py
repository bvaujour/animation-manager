import datetime
import math
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    EffectifEnfantsJour,
    Sortie,
    SortieEtapeTransport,
)
from animateurs.services.categories_groupes import categorie_age_groupe
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
        affectations_groupe = [
            item for item in affectations
            if item.evenement_id == evenement.id and not est_groupe_flottants(item.evenement)
        ]
        animateurs_groupe = [item.animateur for item in affectations_groupe]
        animateurs_utilises.update({item.id: item for item in animateurs_groupe})
        restant = max(0, nombre - len(animateurs_groupe) * ratio)
        ratio_reel = nombre / len(animateurs_groupe) if animateurs_groupe else None
        ligne = {
            "evenement_id": evenement.id,
            "centre_id": evenement.centre_id,
            "centre": evenement.centre.nom,
            "centre_code": evenement.centre.code,
            "groupe": evenement.nom,
            "categorie_age": categorie_age_groupe(evenement),
            "effectif": nombre,
            "effectif_renseigne": ligne_effectif is not None,
            "ratio": ratio,
            "ratio_libelle": f"1/{ratio}",
            "ratio_defaut": evenement.enfants_par_animateur_defaut,
            "ratio_exceptionnel": (
                ligne_effectif.ratio_encadrement_exceptionnel if ligne_effectif else None
            ),
            "ratio_reel": round(ratio_reel, 2) if ratio_reel is not None else None,
            "animateurs_requis": math.ceil(nombre / ratio) if nombre else 0,
            "animateurs": [
                _animateur_dict(item.animateur)
                for item in affectations_groupe
            ],
            "activite_horaire": str(activites.get(evenement.id, "") or ""),
            "non_couverts": restant,
            "marge_couverture": len(animateurs_groupe) * ratio - nombre,
            "flottants_mobilises": [],
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
                if couverts:
                    item["ligne"]["marge_couverture"] += couverts
                    item["ligne"]["flottants_mobilises"].append(_animateur_dict(animateur))
                capacite -= couverts
                if capacite <= 0:
                    break

    for reliquats in reliquats_par_centre.values():
        for item in reliquats:
            item["ligne"]["non_couverts"] = item["restant"]
            if item["restant"]:
                item["ligne"]["couverture"] = "insuffisant"
            elif item["ligne"]["marge_couverture"] == 0:
                item["ligne"]["couverture"] = "equilibre"
            else:
                item["ligne"]["couverture"] = "conforme"

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

    totaux_categories = {}
    for categorie in ("maternelle", "elementaire", "autre"):
        lignes_categorie = [item for item in lignes if item["categorie_age"] == categorie]
        ids_animateurs = {
            animateur["id"]
            for ligne in lignes_categorie
            for animateur in ligne["animateurs"]
        }
        totaux_categories[categorie] = {
            "enfants": sum(item["effectif"] for item in lignes_categorie),
            "animateurs": len(ids_animateurs),
        }

    return {
        "totaux": {
            "groupes": len(lignes),
            "enfants": sum(item["effectif"] for item in lignes),
            "animateurs": len(animateurs_utilises),
            "non_couverts": non_couverts,
            "categories": totaux_categories,
            "lieux": [
                {"id": centre.id, "nom": centre.nom, "code": centre.code}
                for centre in sorted(centres.values(), key=lambda item: (item.ordre, item.nom))
            ],
        },
        "groupes": lignes,
        "flottants_par_centre": flottants_par_centre,
        "animateurs_concernes": [
            _animateur_dict(item)
            for item in sorted(animateurs_utilises.values(), key=lambda animateur: (animateur.nom, animateur.prenom))
        ],
        "vigilances": vigilances,
    }


def centres_concernes_transport(sortie: Sortie):
    """Centres uniques réellement rattachés aux groupes de la sortie."""

    ids_centres = sortie.participations.values_list("evenement__centre_id", flat=True)
    return list(
        Centre.objects.filter(pk__in=ids_centres)
        .order_by("ordre", "nom", "id")
        .distinct()
    )


@transaction.atomic
def synchroniser_circuits_transport(sortie: Sortie):
    """Conserve l'ordre valide, retire les orphelins et ajoute les nouveaux lieux."""

    centres = centres_concernes_transport(sortie)
    ids_valides = {centre.id for centre in centres}
    existantes = list(sortie.etapes_transport.select_related("centre").order_by("sens", "ordre", "id"))
    par_sens = {
        sens: [item.centre_id for item in existantes if item.sens == sens and item.centre_id in ids_valides]
        for sens in (SortieEtapeTransport.SENS_ALLER, SortieEtapeTransport.SENS_RETOUR)
    }
    ids_ordonnes = [centre.id for centre in centres]
    if not par_sens[SortieEtapeTransport.SENS_ALLER]:
        par_sens[SortieEtapeTransport.SENS_ALLER] = ids_ordonnes.copy()
    if not par_sens[SortieEtapeTransport.SENS_RETOUR]:
        par_sens[SortieEtapeTransport.SENS_RETOUR] = list(reversed(ids_ordonnes))

    for sens in par_sens:
        presents = set(par_sens[sens])
        par_sens[sens].extend(centre_id for centre_id in ids_ordonnes if centre_id not in presents)

    ordre_actuel = {
        sens: [item.centre_id for item in existantes if item.sens == sens]
        for sens in par_sens
    }
    if ordre_actuel == par_sens:
        return

    invalider_estimations_transport(sortie)
    sortie.etapes_transport.all().delete()
    SortieEtapeTransport.objects.bulk_create(
        [
            SortieEtapeTransport(sortie=sortie, centre_id=centre_id, sens=sens, ordre=ordre)
            for sens, centres_ids in par_sens.items()
            for ordre, centre_id in enumerate(centres_ids)
        ]
    )


@transaction.atomic
def remplacer_circuits_transport(sortie: Sortie, circuit_aller, circuit_retour):
    """Valide puis remplace atomiquement les deux ordres de circuit."""

    ids_valides = {centre.id for centre in centres_concernes_transport(sortie)}
    circuits = {
        SortieEtapeTransport.SENS_ALLER: circuit_aller,
        SortieEtapeTransport.SENS_RETOUR: circuit_retour,
    }
    normalises = {}
    for sens, valeurs in circuits.items():
        if not isinstance(valeurs, list):
            raise ValueError("L’ordre du circuit est invalide.")
        try:
            ids = [int(value) for value in valeurs]
        except (TypeError, ValueError) as exc:
            raise ValueError("L’ordre du circuit est invalide.") from exc
        if len(ids) != len(set(ids)):
            raise ValueError("Un lieu ne peut apparaître qu’une fois dans un circuit.")
        if set(ids) != ids_valides:
            raise ValueError("Chaque circuit doit contenir exactement les lieux de la sortie.")
        normalises[sens] = ids

    ordre_actuel = {
        sens: list(
            sortie.etapes_transport.filter(sens=sens)
            .order_by("ordre", "id")
            .values_list("centre_id", flat=True)
        )
        for sens in normalises
    }
    if ordre_actuel == normalises:
        return
    invalider_estimations_transport(sortie)
    sortie.etapes_transport.all().delete()
    SortieEtapeTransport.objects.bulk_create(
        [
            SortieEtapeTransport(sortie=sortie, centre_id=centre_id, sens=sens, ordre=ordre)
            for sens, ids in normalises.items()
            for ordre, centre_id in enumerate(ids)
        ]
    )


def invalider_estimations_transport(sortie):
    """Efface seulement les horaires calculés, jamais un ajustement manuel."""

    champs = []
    if sortie.source_heure_arrivee == Sortie.SOURCE_HORAIRE_AUTOMATIQUE:
        sortie.heure_arrivee = None
        sortie.source_heure_arrivee = ""
        champs.extend(["heure_arrivee", "source_heure_arrivee"])
    if sortie.source_heure_arrivee_retour == Sortie.SOURCE_HORAIRE_AUTOMATIQUE:
        sortie.heure_arrivee_retour = None
        sortie.source_heure_arrivee_retour = ""
        champs.extend(["heure_arrivee_retour", "source_heure_arrivee_retour"])
    if champs:
        sortie.save(update_fields=champs)


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


def _renfort_dict(renfort):
    affectation = renfort.affectation
    return {
        "id": renfort.id,
        "animateur": _animateur_dict(affectation.animateur),
        "centre": {"id": affectation.centre_id, "nom": affectation.centre.nom},
        "groupe": {"id": affectation.evenement_id, "nom": affectation.evenement.nom},
    }


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
    renforts = list(
        sortie.renforts.select_related(
            "affectation__animateur", "affectation__centre", "affectation__evenement"
        ).prefetch_related("affectation__animateur__qualifications")
    )
    etapes_transport = list(
        sortie.etapes_transport.select_related("centre").order_by("sens", "ordre", "id")
    )

    vigilances = []
    if not sortie.nom:
        vigilances.append("Nom de la sortie manquant")
    if not sortie.date:
        vigilances.append("Date de la sortie manquante")
    if not sortie.destination:
        vigilances.append("Destination manquante")
    vigilances.extend(participants["vigilances"])
    if not sortie.heure_depart or not sortie.heure_retour:
        vigilances.append("Horaire de départ ou de retour manquant")

    controles_completion = [
        {
            "code": "identite",
            "libelle": "Nom, date et destination",
            "ok": bool(sortie.nom and sortie.date and sortie.destination),
        },
        {
            "code": "groupes_effectifs",
            "libelle": "Groupes et effectifs renseignés",
            "ok": bool(participants["groupes"])
            and all(item["effectif_renseigne"] for item in participants["groupes"]),
        },
        {
            "code": "animateurs",
            "libelle": "Animateurs affectés",
            "ok": bool(participants["groupes"] and participants["animateurs_concernes"]),
        },
        {
            "code": "encadrement",
            "libelle": "Encadrement conforme",
            "ok": bool(participants["groupes"])
            and participants["totaux"]["non_couverts"] == 0,
        },
        {
            "code": "horaires",
            "libelle": "Horaires de départ et retour",
            "ok": bool(sortie.heure_depart and sortie.heure_retour),
        },
    ]

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
        "destination_details": {
            "nom": sortie.destination,
            "adresse": sortie.destination_adresse,
            "code_postal": sortie.destination_code_postal,
            "commune": sortie.destination_commune,
            "code_insee": sortie.destination_code_insee,
            "latitude": float(sortie.destination_latitude) if sortie.destination_latitude is not None else None,
            "longitude": float(sortie.destination_longitude) if sortie.destination_longitude is not None else None,
            "precision": sortie.destination_precision,
            "peut_estimer": bool(sortie.destination_code_postal),
        },
        "meteo_lieu": {
            "libelle": sortie.destination,
            "adresse": " ".join(filter(None, (sortie.destination_adresse, sortie.destination_code_postal, sortie.destination_commune))),
            "latitude": float(sortie.destination_latitude) if sortie.destination_latitude is not None else None,
            "longitude": float(sortie.destination_longitude) if sortie.destination_longitude is not None else None,
            "precision": sortie.destination_precision,
        },
        "statut": "prete" if not vigilances else "a_completer",
        "controles_completion": controles_completion,
        "totaux": {
            "enfants": participants["totaux"]["enfants"],
            "animateurs": len(animateurs_adultes),
            "animateurs_repartition": participants["totaux"]["animateurs"],
            "non_couverts": participants["totaux"]["non_couverts"],
            "categories": participants["totaux"]["categories"],
            "lieux": participants["totaux"]["lieux"],
        },
        "groupes": participants["groupes"],
        "flottants_par_centre": participants["flottants_par_centre"],
        "animateurs_concernes": list(animateurs_adultes.values()),
        "responsabilites": [_responsabilite_dict(item) for item in responsabilites],
        "renforts": [_renfort_dict(item) for item in renforts],
        "transport": {
            "mode_transport": sortie.mode_transport,
            "nombre_vehicules": sortie.nombre_vehicules,
            "heure_depart": sortie.heure_depart.isoformat(timespec="minutes") if sortie.heure_depart else "",
            "heure_arrivee": sortie.heure_arrivee.isoformat(timespec="minutes") if sortie.heure_arrivee else "",
            "source_heure_arrivee": sortie.source_heure_arrivee,
            "heure_retour": sortie.heure_retour.isoformat(timespec="minutes") if sortie.heure_retour else "",
            "heure_arrivee_retour": (
                sortie.heure_arrivee_retour.isoformat(timespec="minutes")
                if sortie.heure_arrivee_retour else ""
            ),
            "source_heure_arrivee_retour": sortie.source_heure_arrivee_retour,
            "temps_arret_par_site": sortie.temps_arret_par_site,
            "trajet_ramassage": sortie.trajet_ramassage,
            "consignes_transport": sortie.consignes_transport,
            "circuits": {
                sens: [
                    {
                        "centre_id": item.centre_id,
                        "nom": item.centre.nom,
                        "code": item.centre.code,
                        "adresse": item.centre.adresse,
                        "code_postal": item.centre.code_postal,
                        "commune": item.centre.commune,
                        "latitude": float(item.centre.latitude) if item.centre.latitude is not None else None,
                        "longitude": float(item.centre.longitude) if item.centre.longitude is not None else None,
                        "precision": item.centre.precision_localisation,
                        "localisation_disponible": item.centre.latitude is not None and item.centre.longitude is not None,
                    }
                    for item in etapes_transport if item.sens == sens
                ]
                for sens in (SortieEtapeTransport.SENS_ALLER, SortieEtapeTransport.SENS_RETOUR)
            },
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
