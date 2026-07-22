"""Synthèse des jours planifiés et de la paie par animateur et par lieu."""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from animateurs.models import Affectation
from animateurs.services.flottants import est_groupe_flottants


def _jours_entre(debut: datetime.date, fin_exclusive: datetime.date):
    """Itère de ``debut`` inclus à ``fin_exclusive`` exclu."""

    jour = debut
    while jour < fin_exclusive:
        yield jour
        jour += datetime.timedelta(days=1)


def _montant(jours: int, paie_jour):
    """Calcule un montant sérialisable, ou ``None`` si le tarif manque."""

    if paie_jour is None:
        return None
    return str((Decimal(jours) * paie_jour).quantize(Decimal("0.01")))


def generer_recapitulatif(debut, fin, jours_selectionnes=None):
    """Retourne les jours et la paie par animateur, ventilés par centre.

    ``debut`` est inclus et ``fin`` est exclusif. Une même date ne compte
    qu'une fois par animateur et par centre, même si plusieurs groupes du même
    centre lui sont affectés ce jour-là. Le total animateur compte également
    chaque date une seule fois.
    """

    debut_date = debut.date()
    fin_date = fin.date()
    jours_autorises = set(_jours_entre(debut_date, fin_date))
    if jours_selectionnes is not None:
        jours_autorises &= set(jours_selectionnes)

    affectations = (
        Affectation.objects.select_related("animateur", "centre", "evenement")
        .filter(debut__lt=fin, fin__gt=debut)
        .order_by("animateur__prenom", "animateur__nom", "debut")
    )

    jours_par_animateur = defaultdict(set)
    jours_par_animateur_centre = defaultdict(lambda: defaultdict(set))
    details_par_animateur = defaultdict(lambda: defaultdict(dict))
    animateurs = {}
    centres = {}

    for affectation in affectations:
        animateur = affectation.animateur
        centre = affectation.centre
        animateurs[animateur.id] = animateur
        centres[centre.id] = {
            "id": centre.id,
            "nom": centre.nom,
            "code": centre.code,
            "couleur": centre.couleur,
            "ordre": centre.ordre,
        }

        debut_affectation = max(timezone.localtime(affectation.debut).date(), debut_date)
        fin_affectation = min(timezone.localtime(affectation.fin).date(), fin_date)
        for jour in _jours_entre(debut_affectation, fin_affectation):
            if jour not in jours_autorises:
                continue
            jours_par_animateur[animateur.id].add(jour)
            jours_par_animateur_centre[animateur.id][centre.id].add(jour)
            details_par_animateur[animateur.id][jour][centre.id] = {
                "id": centre.id,
                "nom": centre.nom,
                "code": centre.code,
                "couleur": centre.couleur,
                "groupe": "Animateur flottant" if est_groupe_flottants(affectation.evenement) else affectation.evenement.nom,
            }

    centres_tries = sorted(
        centres.values(),
        key=lambda centre: (centre["ordre"], centre["nom"].casefold(), centre["code"]),
    )

    lignes = []
    for animateur in animateurs.values():
        jours_totaux = jours_par_animateur[animateur.id]
        if not jours_totaux:
            continue
        ventilation = []
        for centre in centres_tries:
            nombre_jours = len(jours_par_animateur_centre[animateur.id][centre["id"]])
            ventilation.append({
                "centre_id": centre["id"],
                "jours_travailles": nombre_jours,
                "paie": _montant(nombre_jours, animateur.paie_jour),
            })

        lignes.append({
            "id": animateur.id,
            "prenom": animateur.prenom,
            "nom": animateur.nom,
            "paie_jour": str(animateur.paie_jour) if animateur.paie_jour is not None else None,
            "jours_travailles": len(jours_totaux),
            "paie_totale": _montant(len(jours_totaux), animateur.paie_jour),
            "centres": ventilation,
            "jours": [
                {
                    "date": jour.isoformat(),
                    "lieux": list(details_par_animateur[animateur.id][jour].values()),
                }
                for jour in sorted(jours_totaux)
            ],
        })

    lignes.sort(key=lambda ligne: (ligne["prenom"].casefold(), ligne["nom"].casefold()))
    total_paie = sum(
        (Decimal(ligne["paie_totale"]) for ligne in lignes if ligne["paie_totale"] is not None),
        Decimal("0.00"),
    )

    return {
        "dates": [jour.isoformat() for jour in sorted(jours_autorises)],
        "centres": [{key: value for key, value in centre.items() if key != "ordre"} for centre in centres_tries],
        "animateurs": lignes,
        "total_jours": sum(ligne["jours_travailles"] for ligne in lignes),
        "total_paie_connue": str(total_paie.quantize(Decimal("0.01"))),
        "tarifs_manquants": sum(1 for ligne in lignes if ligne["paie_jour"] is None),
    }
