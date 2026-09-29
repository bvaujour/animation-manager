"""Lecture commune des actions attendues dans le portail animateur.

Les actions restent portées par leurs objets métier. Ce module les expose sous
un contrat volontairement simple afin d'accueillir plus tard d'autres
fournisseurs (par exemple une demande de modification de disponibilités).
"""

from __future__ import annotations

import datetime
import json
from collections import Counter, defaultdict

from django.utils import timezone

from animateurs.models import (
    Affectation, DestinatairePublicationAffectation, HoraireAffectationJour,
    ResponsabiliteOperationnelle,
)


def _normaliser_detail_affectation(detail):
    """Rend comparables les instantanés créés avant les nouveaux champs."""
    normalise = dict(detail)
    for cle in (
        "type_accueil_code", "modalite_periscolaire", "modalite_periscolaire_code",
    ):
        normalise.setdefault(cle, "")
    normalise["horaires"] = sorted(
        normalise.get("horaires", []),
        key=lambda horaire: json.dumps(horaire, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
    )
    return normalise


def _signature_affectation(detail):
    return json.dumps(_normaliser_detail_affectation(detail), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def instantanes_affectations_equivalents(ancien, nouveau):
    """Compare le contenu métier, sans dépendre des clés ajoutées ni de l'ordre."""
    return Counter(_signature_affectation(detail) for detail in ancien) == Counter(
        _signature_affectation(detail) for detail in nouveau
    )


def details_affectations_avec_statut(destinataire):
    """Retourne le détail publié, en distinguant les lignes déjà validées.

    La comparaison porte sur le contenu figé complet, avec un compteur pour
    gérer aussi deux lignes identiques sans attribuer deux fois une validation.
    Les destinataires antérieurs aux instantanés restent consultables grâce à
    une reconstruction de lecture seule ; elle n'est jamais enregistrée.
    """
    instantane = destinataire.instantane_affectations
    if not destinataire.instantane_affectations_est_fige:
        instantane = instantane_affectations(
            destinataire.publication.periode_calendrier, destinataire.animateur
        )
    confirmes = destinataire.instantane_affectations_confirmees
    if not confirmes and destinataire.confirme_le is not None:
        # Compatibilité avec les confirmations réalisées avant ce suivi fin,
        # y compris les lignes sans instantané historique.
        confirmes = instantane
    restants = Counter(_signature_affectation(detail) for detail in confirmes)
    resultat = []
    for detail in instantane:
        signature = _signature_affectation(detail)
        est_confirmee = restants[signature] > 0
        if est_confirmee:
            restants[signature] -= 1
        resultat.append({**detail, "statut_confirmation": "confirmee" if est_confirmee else "a_confirmer"})
    return resultat


def affectations_restent_a_confirmer(destinataire):
    # Une ancienne publication ne contient pas forcément de détail. Son
    # destinataire peut confirmer l'information reçue seulement si son détail
    # reste reconstructible, sans prétendre reconstituer un instantané.
    if not destinataire.instantane_affectations_est_fige:
        return destinataire.confirme_le is None and bool(details_affectations_avec_statut(destinataire))
    return any(detail["statut_confirmation"] == "a_confirmer" for detail in details_affectations_avec_statut(destinataire))


def detail_legacy_indisponible(destinataire):
    """Indique une ancienne publication non confirmée sans détail lisible."""
    return (
        not destinataire.instantane_affectations_est_fige
        and destinataire.confirme_le is None
        and not details_affectations_avec_statut(destinataire)
    )


def _jours_couverts(debut, fin):
    """Retourne les jours civils d'un intervalle dont la borne de fin est exclusive."""
    jour = timezone.localtime(debut).date()
    fin_locale = timezone.localtime(fin).date()
    jours = []
    while jour < fin_locale:
        jours.append(jour.isoformat())
        jour += datetime.timedelta(days=1)
    return jours


def instantane_affectations(periode, animateur):
    """Construit le minimum immuable présenté lors d'une publication."""
    debut = timezone.make_aware(datetime.datetime.combine(periode.debut, datetime.time.min))
    fin = timezone.make_aware(datetime.datetime.combine(periode.fin + datetime.timedelta(days=1), datetime.time.min))
    affectations = (
        Affectation.objects.filter(animateur=animateur, debut__lt=fin, fin__gt=debut)
        .select_related("centre", "evenement__groupe", "type_accueil", "modalite_periscolaire")
        .order_by("debut", "fin", "id")
    )
    affectations = list(affectations)
    horaires_par_affectation = defaultdict(list)
    for horaire in HoraireAffectationJour.objects.filter(
        affectation__in=affectations, date__gte=periode.debut, date__lte=periode.fin
    ).order_by("affectation_id", "date"):
        horaires_par_affectation[horaire.affectation_id].append({
            "date": horaire.date.isoformat(),
            "heure_arrivee": horaire.heure_arrivee.isoformat(),
            "heure_depart": horaire.heure_depart.isoformat(),
        })
    responsabilites = list(
        ResponsabiliteOperationnelle.objects.filter(
            animateur=animateur, debut__lt=fin, fin__gt=debut
        ).select_related("fonction").order_by("debut", "id")
    )
    resultat = []
    for affectation in affectations:
        role = next(
            (
                responsabilite.fonction.nom
                for responsabilite in responsabilites
                if responsabilite.debut < affectation.fin and responsabilite.fin > affectation.debut
            ),
            "",
        )
        groupe = affectation.evenement.groupe
        resultat.append({
            "jours": _jours_couverts(affectation.debut, affectation.fin),
            "date_debut": timezone.localtime(affectation.debut).date().isoformat(),
            "date_fin": (timezone.localtime(affectation.fin).date() - datetime.timedelta(days=1)).isoformat(),
            "centre": affectation.centre.nom,
            "centre_code": affectation.centre.code,
            "groupe": affectation.evenement.nom,
            "tranche_age": groupe.get_categorie_age_reglementaire_display(),
            "type_accueil": affectation.type_accueil.nom if affectation.type_accueil_id else "",
            "type_accueil_code": affectation.type_accueil.code if affectation.type_accueil_id else "",
            "modalite_periscolaire": affectation.modalite_periscolaire.nom if affectation.modalite_periscolaire_id else "",
            "modalite_periscolaire_code": affectation.modalite_periscolaire.code if affectation.modalite_periscolaire_id else "",
            "role": role,
            "horaires": horaires_par_affectation[affectation.pk],
        })
    # Le JSON publié doit être indépendant de l'ordre technique de création.
    return sorted(resultat, key=_signature_affectation)


def actions_actives_animateur(animateur):
    """Actions ouvertes de l'animateur, prêtes à être rendues par le portail."""
    destinataires = (
        DestinatairePublicationAffectation.objects.filter(
            animateur=animateur, publication__publie=True
        )
        .select_related("publication__periode_calendrier")
        .order_by("publication__periode_calendrier__debut", "pk")
    )
    actions = []
    for destinataire in destinataires:
        if (
            destinataire.annulation_notifiee_le is not None
            and destinataire.annulation_prise_en_compte_le is None
        ):
            actions.append({
                "type": "annulation_affectation_a_prendre_en_compte",
                "id": destinataire.pk,
                "titre": f"Votre affectation pour {destinataire.publication.periode_calendrier.nom} a été annulée",
                "periode": destinataire.publication.periode_calendrier,
                "destinataire": destinataire,
                "date_action": destinataire.annulation_notifiee_le,
                "libelle_date": "Annulée le",
            })
        elif destinataire.retire_le is None and affectations_restent_a_confirmer(destinataire):
            est_modifiee = destinataire.instantane_modifie_le is not None
            actions.append({
                "type": "affectation_modifiee_a_reconfirmer" if est_modifiee else "nouvelle_affectation_a_confirmer",
                "id": destinataire.pk,
                "titre": "Affectation modifiée à reconfirmer" if est_modifiee else "Nouvelle affectation à confirmer",
                "periode": destinataire.publication.periode_calendrier,
                "destinataire": destinataire,
                "date_action": destinataire.instantane_modifie_le if est_modifiee else destinataire.publication.publie_le,
                "libelle_date": "Mise à jour le" if est_modifiee else "Publiée le",
            })
    priorites = {
        "annulation_affectation_a_prendre_en_compte": 0,
        "affectation_modifiee_a_reconfirmer": 1,
        "nouvelle_affectation_a_confirmer": 2,
    }
    return sorted(
        actions,
        key=lambda action: (priorites[action["type"]], action["periode"].debut, action["id"]),
    )


def nombre_actions_actives(animateur):
    return len(actions_actives_animateur(animateur))


def suivi_actions_affectations(periode):
    """État des actions d'affectation pour le tableau direction."""
    publication = getattr(periode, "publication_affectations", None)
    if publication is None:
        return {"publication": None, "destinataires": [], "total": 0, "confirmes": 0, "en_attente": 0, "sans_acces": 0}
    destinataires = list(
        publication.destinataires.select_related("animateur__utilisateur").prefetch_related("signalements").all()
    )
    for destinataire in destinataires:
        # Attribut d'affichage éphémère : aucune donnée legacy n'est modifiée.
        destinataire.detail_indisponible = detail_legacy_indisponible(destinataire)
        destinataire.annulation_en_attente = (
            destinataire.annulation_notifiee_le is not None
            and destinataire.annulation_prise_en_compte_le is None
        )
    actifs = [item for item in destinataires if item.retire_le is None]
    indisponibles = sum(item.detail_indisponible for item in actifs)
    confirmes = sum(
        not item.detail_indisponible and not affectations_restent_a_confirmer(item)
        for item in actifs
    )
    sans_acces = sum(not item.animateur.utilisateur_id or not item.animateur.utilisateur.is_active for item in actifs)
    annulations_en_attente = sum(item.annulation_en_attente for item in destinataires)
    annulations_prises_en_compte = sum(
        item.annulation_notifiee_le is not None and item.annulation_prise_en_compte_le is not None
        for item in destinataires
    )
    return {
        "publication": publication,
        "destinataires": destinataires,
        "total": len(actifs),
        "confirmes": confirmes,
        "en_attente": len(actifs) - confirmes - indisponibles,
        "indisponibles": indisponibles,
        "sans_acces": sans_acces,
        "annulations_en_attente": annulations_en_attente,
        "annulations_prises_en_compte": annulations_prises_en_compte,
    }
