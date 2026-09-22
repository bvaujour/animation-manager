"""Lecture commune des actions attendues dans le portail animateur.

Les actions restent portées par leurs objets métier. Ce module les expose sous
un contrat volontairement simple afin d'accueillir plus tard d'autres
fournisseurs (par exemple une demande de modification de disponibilités).
"""

from __future__ import annotations

import datetime

from django.utils import timezone

from animateurs.models import Affectation, DestinatairePublicationAffectation, ResponsabiliteOperationnelle


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
        .select_related("centre", "evenement__groupe", "type_accueil")
        .order_by("debut", "fin", "id")
    )
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
            "role": role,
        })
    return resultat


def actions_actives_animateur(animateur):
    """Actions ouvertes de l'animateur, prêtes à être rendues par le portail."""
    destinataires = (
        DestinatairePublicationAffectation.objects.filter(
            animateur=animateur, confirme_le__isnull=True, retire_le__isnull=True, publication__publie=True
        )
        .select_related("publication__periode_calendrier")
        .order_by("publication__periode_calendrier__debut", "pk")
    )
    return [
        {
            "type": "affectation_a_confirmer",
            "id": destinataire.pk,
            "titre": f"Affectation {destinataire.publication.periode_calendrier.nom} à confirmer",
            "periode": destinataire.publication.periode_calendrier,
            "destinataire": destinataire,
        }
        for destinataire in destinataires
    ]


def nombre_actions_actives(animateur):
    return len(actions_actives_animateur(animateur))


def suivi_actions_affectations(periode):
    """État des actions d'affectation pour le tableau direction."""
    publication = getattr(periode, "publication_affectations", None)
    if publication is None:
        return {"publication": None, "destinataires": [], "total": 0, "confirmes": 0, "en_attente": 0, "sans_acces": 0}
    destinataires = list(publication.destinataires.select_related("animateur__utilisateur").all())
    actifs = [item for item in destinataires if item.retire_le is None]
    confirmes = sum(item.confirme_le is not None for item in actifs)
    sans_acces = sum(not item.animateur.utilisateur_id or not item.animateur.utilisateur.is_active for item in actifs)
    return {
        "publication": publication,
        "destinataires": destinataires,
        "total": len(actifs),
        "confirmes": confirmes,
        "en_attente": len(actifs) - confirmes,
        "sans_acces": sans_acces,
    }
