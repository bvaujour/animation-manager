"""Couleurs automatiques des salariés selon leur statut de qualification.

Les couleurs ne sont pas enregistrées par salarié : elles sont calculées de
manière stable depuis le statut. Cela garantit qu'un même statut conserve la
même couleur dans la liste du Planning, les affectations et les filtres.
"""

from __future__ import annotations

import unicodedata
import zlib

STATUS_FALLBACK_COLOR = "#64748B"
# Teintes volontairement espacées sur le cercle chromatique. Elles restent
# suffisamment soutenues pour produire des fonds pastel bien distincts après
# mélange avec du blanc dans l'interface.
STATUS_COLOR_PALETTE = (
    "#2878B5",  # bleu franc
    "#7A4DB3",  # violet
    "#27866B",  # vert émeraude
    "#C34F7A",  # rose
    "#C56A22",  # orange
    "#148A91",  # turquoise
)


def _normaliser(texte: str) -> str:
    valeur = unicodedata.normalize("NFKD", str(texte or ""))
    valeur = "".join(caractere for caractere in valeur if not unicodedata.combining(caractere))
    return " ".join(valeur.casefold().replace("-", " ").split())


def couleur_pour_statut(statut) -> str:
    """Retourne une couleur lisible et stable pour un objet Qualification statut."""

    if statut is None:
        return STATUS_FALLBACK_COLOR

    nom = _normaliser(getattr(statut, "nom", ""))
    if "non diplome" in nom or "sans diplome" in nom:
        return "#C94F4F"
    if "stagiaire" in nom:
        return "#C98216"
    if "direction" in nom or "directeur" in nom or "directrice" in nom:
        return "#7246B3"
    if "diplome" in nom:
        return "#27866B"

    cle = nom or str(getattr(statut, "pk", "") or "statut")
    index = zlib.crc32(cle.encode("utf-8")) % len(STATUS_COLOR_PALETTE)
    return STATUS_COLOR_PALETTE[index]



def couleur_pastel_pour_fond(couleur: str, proportion_couleur: float = 0.24) -> str:
    """Mélange une teinte de statut avec du blanc pour les fonds de cartes.

    La teinte de base reste commune à tous les écrans, tandis que ce fond pastel
    garantit une lecture confortable dans les petits calendriers.
    """

    try:
        rouge, vert, bleu = (int(couleur[index : index + 2], 16) for index in (1, 3, 5))
    except (TypeError, ValueError):
        rouge, vert, bleu = (100, 116, 139)
    p = max(0.0, min(1.0, float(proportion_couleur)))
    canaux = [round(255 - ((255 - canal) * p)) for canal in (rouge, vert, bleu)]
    return "#" + "".join(f"{canal:02X}" for canal in canaux)

def couleur_texte_pour_fond(couleur: str) -> str:
    """Choisit une couleur de texte contrastée pour une couleur hexadécimale."""

    try:
        rouge, vert, bleu = (int(couleur[index : index + 2], 16) for index in (1, 3, 5))
    except (TypeError, ValueError):
        return "#FFFFFF"
    luminance = (0.299 * rouge) + (0.587 * vert) + (0.114 * bleu)
    return "#1F2937" if luminance >= 164 else "#FFFFFF"


def statuts_des_qualifications(qualifications) -> list:
    """Déduit les statuts uniques validés par les diplômes d'un salarié."""

    statuts = {}
    for qualification in qualifications:
        statut = qualification if getattr(qualification, "est_statut", False) else getattr(qualification, "statut", None)
        if statut is not None:
            statuts[statut.pk] = statut
    return sorted(statuts.values(), key=lambda item: (str(item.nom).casefold(), item.pk))


def statut_principal_des_qualifications(qualifications):
    statuts = statuts_des_qualifications(qualifications)
    return statuts[0] if statuts else None


def statut_payload(qualifications) -> dict:
    """Construit les champs JSON communs utilisés par les interfaces salariés."""

    qualifications = list(qualifications)
    statuts = statuts_des_qualifications(qualifications)
    principal = statuts[0] if statuts else None
    couleur = couleur_pour_statut(principal)
    return {
        "diplome_ids": sorted(q.pk for q in qualifications if not getattr(q, "est_statut", False)),
        "statut_ids": [statut.pk for statut in statuts],
        "statut_principal": (
            {
                "id": principal.pk,
                "nom": principal.nom,
                "couleur": couleur,
            }
            if principal is not None
            else None
        ),
        "couleur_statut": couleur,
        "couleur_fond_statut": couleur_pastel_pour_fond(couleur),
        "couleur_texte_statut": "#243244",
    }
