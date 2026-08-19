"""Données du tableau de bord personnel des animateurs.

La page reste volontairement en lecture seule : elle rassemble les informations
qui existent déjà dans Animation Manager sans créer de doublon métier. Le
planning, les effectifs, les sorties, les réunions, les disponibilités, les
documents et les informations publiées par la direction restent pilotés par
leurs modules d’origine.
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from django.db.models import Prefetch, Q
from django.utils import timezone

from animateurs.models import (
    ActiviteTravailComplementaire,
    Affectation,
    Animateur,
    Disponibilite,
    Document,
    InformationAnimateur,
    PublicationPlanning,
    EffectifEnfantsJour,
    HoraireAffectationJour,
    ParticipationTravailComplementaire,
    Sortie,
)

JOURS_FR = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi")
JOURS_SEMAINE_FR = JOURS_FR + ("Samedi", "Dimanche")
MOIS_FR = (
    "",
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def debut_semaine(date_reference: datetime.date) -> datetime.date:
    """Ramène une date au lundi de sa semaine."""

    return date_reference - datetime.timedelta(days=date_reference.weekday())


def _borne_jour(jour: datetime.date) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))


def _jours_couverts(
    affectation: Affectation,
    debut: datetime.date,
    fin_inclusive: datetime.date,
):
    debut_local = timezone.localtime(affectation.debut).date()
    fin_locale_exclusive = timezone.localtime(affectation.fin).date()
    jour = max(debut_local, debut)
    fin = min(fin_locale_exclusive, fin_inclusive + datetime.timedelta(days=1))
    while jour < fin:
        yield jour
        jour += datetime.timedelta(days=1)


def _format_heure(heure: datetime.time | None) -> str:
    if not heure:
        return ""
    valeur = heure.strftime("%Hh%M").replace("h00", "h")
    return valeur[1:] if valeur.startswith("0") else valeur


def _format_plage(heure_arrivee: datetime.time | None, heure_depart: datetime.time | None) -> str:
    if not heure_arrivee or not heure_depart:
        return "Horaires à confirmer"
    return f"{_format_heure(heure_arrivee)} – {_format_heure(heure_depart)}"


def _libelle_date(jour: datetime.date) -> str:
    return f"{jour.day} {MOIS_FR[jour.month]}"


def _est_sejour(affectation: Affectation) -> bool:
    """Détermine si une affectation correspond à un séjour.

    Le modèle ne possède pas encore de catégorie dédiée : on conserve donc la
    même règle métier que le calendrier personnel du tableau de bord, en regardant les libellés du
    lieu, de l'événement et du groupe.
    """

    libelles = [
        getattr(affectation.centre, "nom", ""),
        getattr(affectation.evenement, "nom", ""),
        getattr(getattr(affectation.evenement, "groupe", None), "nom", ""),
    ]
    texte = " ".join(libelles).casefold()
    return "séjour" in texte or "sejour" in texte


def _libelle_semaine(lundi: datetime.date, vendredi: datetime.date) -> str:
    if lundi.month == vendredi.month:
        return f"Semaine du {lundi.day} au {vendredi.day} {MOIS_FR[vendredi.month]} {vendredi.year}"
    return (
        f"Semaine du {lundi.day} {MOIS_FR[lundi.month]} "
        f"au {vendredi.day} {MOIS_FR[vendredi.month]} {vendredi.year}"
    )


def _documents_semaine(lundi: datetime.date, vendredi: datetime.date):
    """Documents publiés utiles à la semaine, avec un libellé court pour le tableau de bord."""

    documents = list(
        Document.objects.filter(
            Q(permanent=True)
            | Q(periodes__debut__lte=vendredi, periodes__fin__gte=lundi)
            | Q(periode_debut__lte=vendredi, periode_fin__gte=lundi),
            publie=True,
        )
        .distinct()
        .prefetch_related("periodes")
        .order_by("-permanent", "titre")[:8]
    )
    for document in documents:
        if document.permanent:
            document.libelle_dashboard = "Permanent"
            continue
        periodes = list(document.periodes.all())
        if len(periodes) == 1:
            libelle = periodes[0].libelle_avec_annee
            libelle = libelle.replace(" — Semaine ", " · S")
            document.libelle_dashboard = libelle
        elif len(periodes) > 1:
            document.libelle_dashboard = f"{len(periodes)} semaines"
        else:
            document.libelle_dashboard = document.libelle_periode
    return documents



def _informations_semaine(animateur: Animateur, lundi: datetime.date, vendredi: datetime.date):
    """Informations publiées par la direction et destinées à l'animateur."""

    return list(
        InformationAnimateur.objects.filter(
            publie=True,
            date_debut__lte=vendredi,
            date_fin__gte=lundi,
        )
        .filter(Q(tous_animateurs=True) | Q(animateurs=animateur))
        .select_related("auteur")
        .distinct()
        .order_by("importance", "-date_debut", "-date_creation")
    )

def _sorties_concernees(
    animateur: Animateur,
    lundi: datetime.date,
    vendredi: datetime.date,
    evenements_par_jour: dict[datetime.date, set[int]],
):
    ids_evenements = {identifiant for ids in evenements_par_jour.values() for identifiant in ids}
    if not ids_evenements:
        responsabilites = Q(responsabilites__animateur=animateur) | Q(
            renforts__affectation__animateur=animateur
        )
        filtre_concerne = responsabilites
    else:
        filtre_concerne = (
            Q(participations__evenement_id__in=ids_evenements)
            | Q(responsabilites__animateur=animateur)
            | Q(renforts__affectation__animateur=animateur)
        )

    sorties = list(
        Sortie.objects.filter(date__range=(lundi, vendredi))
        .filter(filtre_concerne)
        .prefetch_related(
            "participations__evenement__centre",
            "responsabilites__animateur",
            "responsabilites__centre",
            "responsabilites__evenement",
            "renforts__affectation",
        )
        .distinct()
        .order_by("date", "nom")
    )

    resultat = []
    for sortie in sorties:
        ids_groupes_sortie = {item.evenement_id for item in sortie.participations.all()}
        responsable = next(
            (item for item in sortie.responsabilites.all() if item.animateur_id == animateur.id),
            None,
        )
        concerne_par_groupe = bool(ids_groupes_sortie & evenements_par_jour.get(sortie.date, set()))
        if not concerne_par_groupe and responsable is None:
            # Le renfort est déjà garanti par le filtre SQL, mais on conserve ce
            # test simple pour ne pas afficher une sortie liée à un groupe d'un
            # autre jour de la semaine.
            est_renfort = any(
                renfort.affectation.animateur_id == animateur.id
                for renfort in sortie.renforts.all()
            )
            if not est_renfort:
                continue

        heure_depart = sortie.heure_depart_site or sortie.heure_depart
        heure_retour = sortie.heure_arrivee_retour or sortie.heure_retour
        horaire = ""
        if heure_depart and heure_retour:
            horaire = f"{_format_heure(heure_depart)} – {_format_heure(heure_retour)}"
        elif heure_depart:
            horaire = f"Départ {_format_heure(heure_depart)}"
        elif heure_retour:
            horaire = f"Retour {_format_heure(heure_retour)}"

        responsabilite = ""
        if responsable:
            if responsable.type == responsable.TYPE_DIRECTION:
                responsabilite = "Direction de la sortie"
            elif responsable.type == responsable.TYPE_LIEU and responsable.centre_id:
                responsabilite = f"Responsable de {responsable.centre.nom}"
            elif responsable.type == responsable.TYPE_GROUPE and responsable.evenement_id:
                responsabilite = f"Responsable du groupe {responsable.evenement.nom}"

        resultat.append(
            {
                "id": sortie.id,
                "nom": sortie.nom,
                "date": sortie.date,
                "date_libelle": f"{JOURS_FR[sortie.date.weekday()]} {_libelle_date(sortie.date)}",
                "destination": sortie.destination or sortie.destination_commune,
                "horaire": horaire,
                "responsabilite": responsabilite,
                "depart": _format_heure(heure_depart),
                "retour": _format_heure(heure_retour),
            }
        )
    return resultat


def _contexte_jour(
    animateur: Animateur,
    jour: datetime.date,
    affectation: Affectation | None = None,
):
    """Résumé compact utilisé dans le bandeau « Aujourd'hui »."""

    debut = _borne_jour(jour)
    fin = debut + datetime.timedelta(days=1)
    if affectation is None:
        affectation = (
            Affectation.objects.filter(animateur=animateur, debut__lt=fin, fin__gt=debut)
            .select_related("centre", "evenement")
            .prefetch_related("horaires_journaliers")
            .first()
        )
    if affectation is None:
        return {
            "date": jour,
            "date_libelle": f"{JOURS_SEMAINE_FR[jour.weekday()]} {_libelle_date(jour)}",
            "travaille": False,
            "centre": "Aucune affectation",
            "groupe": "Repos",
            "enfants": None,
            "animateurs": None,
        }

    effectif = EffectifEnfantsJour.objects.filter(evenement=affectation.evenement, date=jour).first()
    equipe = (
        Affectation.objects.filter(evenement=affectation.evenement, debut__lt=fin, fin__gt=debut)
        .values("animateur_id")
        .distinct()
        .count()
    )
    return {
        "date": jour,
        "date_libelle": f"{JOURS_SEMAINE_FR[jour.weekday()]} {_libelle_date(jour)}",
        "travaille": True,
        "centre": affectation.centre.nom,
        "groupe": affectation.evenement.nom,
        "enfants": effectif.nombre if effectif else None,
        "animateurs": equipe,
    }


def generer_tableau_de_bord_animateur(
    animateur: Animateur,
    date_reference: datetime.date | None = None,
):
    """Construit le tableau de bord personnel d'un animateur."""

    aujourd_hui = timezone.localdate()
    date_reference = date_reference or aujourd_hui
    lundi = debut_semaine(date_reference)
    vendredi = lundi + datetime.timedelta(days=4)
    debut_dt = _borne_jour(lundi)
    fin_dt = _borne_jour(vendredi + datetime.timedelta(days=1))
    planning_publie = PublicationPlanning.objects.filter(semaine_debut=lundi, publie=True).exists()

    horaires_prefetch = Prefetch(
        "horaires_journaliers",
        queryset=HoraireAffectationJour.objects.filter(date__range=(lundi, vendredi)).order_by("date"),
    )
    affectations = []
    if planning_publie:
        affectations = list(
            Affectation.objects.filter(animateur=animateur, debut__lt=fin_dt, fin__gt=debut_dt)
            .select_related("centre", "evenement", "evenement__groupe")
            .prefetch_related(horaires_prefetch)
            .order_by("debut", "id")
        )

    affectation_par_jour: dict[datetime.date, Affectation] = {}
    evenements_par_jour: dict[datetime.date, set[int]] = defaultdict(set)
    for affectation in affectations:
        for jour in _jours_couverts(affectation, lundi, vendredi):
            affectation_par_jour.setdefault(jour, affectation)
            evenements_par_jour[jour].add(affectation.evenement_id)

    ids_evenements = {item.evenement_id for item in affectations}
    effectifs = {
        (item.evenement_id, item.date): item
        for item in EffectifEnfantsJour.objects.filter(
            evenement_id__in=ids_evenements,
            date__range=(lundi, vendredi),
        )
    }

    equipe_par_jour: dict[tuple[int, datetime.date], list[Animateur]] = defaultdict(list)
    if ids_evenements:
        affectations_equipe = list(
            Affectation.objects.filter(
                evenement_id__in=ids_evenements,
                debut__lt=fin_dt,
                fin__gt=debut_dt,
            )
            .select_related("animateur", "evenement")
            .order_by("animateur__prenom", "animateur__nom", "id")
        )
        ids_deja_ajoutes: dict[tuple[int, datetime.date], set[int]] = defaultdict(set)
        for affectation in affectations_equipe:
            for jour in _jours_couverts(affectation, lundi, vendredi):
                cle = (affectation.evenement_id, jour)
                if affectation.animateur_id in ids_deja_ajoutes[cle]:
                    continue
                ids_deja_ajoutes[cle].add(affectation.animateur_id)
                equipe_par_jour[cle].append(affectation.animateur)

    sorties = _sorties_concernees(animateur, lundi, vendredi, evenements_par_jour)
    sorties_par_jour = defaultdict(list)
    for sortie in sorties:
        sorties_par_jour[sortie["date"]].append(sortie)

    disponibilites = list(
        Disponibilite.objects.filter(animateur=animateur, debut__lte=vendredi, fin__gte=lundi).order_by("debut")
    )

    def est_disponible(jour: datetime.date) -> bool:
        return any(item.debut <= jour <= item.fin for item in disponibilites)

    jours = []
    for index in range(5):
        jour = lundi + datetime.timedelta(days=index)
        affectation = affectation_par_jour.get(jour)
        if affectation is None:
            jours.append(
                {
                    "date": jour,
                    "jour": JOURS_FR[index],
                    "date_libelle": _libelle_date(jour),
                    "est_aujourdhui": jour == aujourd_hui,
                    "travaille": False,
                    "disponible": est_disponible(jour),
                    "sorties": sorties_par_jour[jour],
                }
            )
            continue

        horaire = next((item for item in affectation.horaires_journaliers.all() if item.date == jour), None)
        equipe = equipe_par_jour[(affectation.evenement_id, jour)]
        collegues = [item for item in equipe if item.id != animateur.id]
        effectif = effectifs.get((affectation.evenement_id, jour))
        sorties_jour = sorties_par_jour[jour]
        responsabilite = next(
            (item["responsabilite"] for item in sorties_jour if item["responsabilite"]),
            "",
        )
        jours.append(
            {
                "date": jour,
                "jour": JOURS_FR[index],
                "date_libelle": _libelle_date(jour),
                "est_aujourdhui": jour == aujourd_hui,
                "travaille": True,
                "disponible": est_disponible(jour),
                "centre": affectation.centre.nom,
                "centre_code": affectation.centre.code,
                "centre_couleur": affectation.centre.couleur,
                "groupe": affectation.evenement.nom,
                "est_sejour": _est_sejour(affectation),
                "type_affectation": "Séjour" if _est_sejour(affectation) else "Affectation",
                "horaire": _format_plage(
                    horaire.heure_arrivee if horaire else None,
                    horaire.heure_depart if horaire else None,
                ),
                "horaires_renseignes": horaire is not None,
                "enfants": effectif.nombre if effectif else None,
                "effectif_renseigne": effectif is not None,
                "animateurs": len(equipe),
                "animateurs_prenoms": [item.prenom for item in equipe],
                "animateurs_libelle": ", ".join(item.prenom for item in equipe),
                "collegues": [item.prenom for item in collegues],
                "collegues_libelle": ", ".join(item.prenom for item in collegues),
                "sorties": sorties_jour,
                "sortie": sorties_jour[0] if sorties_jour else None,
                "responsabilite": responsabilite,
            }
        )

    reunions = list(
        ParticipationTravailComplementaire.objects.filter(
            animateur=animateur,
            activite__type=ActiviteTravailComplementaire.TYPE_REUNION,
            activite__date__range=(lundi, vendredi),
        )
        .select_related("activite")
        .order_by("activite__date", "activite__intitule")
    )
    reunions_dashboard = [
        {
            "date": item.activite.date,
            "date_libelle": f"{JOURS_FR[item.activite.date.weekday()]} {_libelle_date(item.activite.date)}",
            "titre": item.activite.intitule,
            "remarque": item.activite.remarque or item.remarque,
        }
        for item in reunions
    ]

    informations = _informations_semaine(animateur, lundi, vendredi)
    contexte_aujourdhui = None
    if lundi <= aujourd_hui <= vendredi:
        contexte_aujourdhui = _contexte_jour(
            animateur,
            aujourd_hui,
            affectation_par_jour.get(aujourd_hui),
        )
    else:
        contexte_aujourdhui = _contexte_jour(animateur, aujourd_hui)

    return {
        "animateur": animateur,
        "planning_publie": planning_publie,
        "aujourdhui": contexte_aujourdhui,
        "semaine": {
            "debut": lundi,
            "fin": vendredi,
            "libelle": _libelle_semaine(lundi, vendredi),
            "precedente": lundi - datetime.timedelta(days=7),
            "suivante": lundi + datetime.timedelta(days=7),
            "courante": debut_semaine(aujourd_hui),
            "est_courante": lundi == debut_semaine(aujourd_hui),
        },
        "jours": jours,
        "infos_semaine": informations,
        "informations": informations,
        "sorties": sorties,
        "reunions": reunions_dashboard,
        "documents": _documents_semaine(lundi, vendredi),
        "disponibilites": {
            "jours_disponibles": sum(1 for item in jours if item["disponible"]),
            "jours_travailles": sum(1 for item in jours if item["travaille"]),
            "jours_libres": sum(1 for item in jours if item["disponible"] and not item["travaille"]),
            "detail": [item for item in jours if item["disponible"]],
        },
    }
