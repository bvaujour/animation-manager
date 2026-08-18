"""Validation commune des périodes de documents."""


import re
import unicodedata
import uuid
from pathlib import PurePath


def normaliser_nom_document(nom_original):
    """Construit un nom ASCII sûr et unique pour le stockage."""
    nom_base = PurePath(str(nom_original or "").replace("\\", "/")).name
    chemin = PurePath(nom_base)

    def segment_securise(valeur):
        sans_accents = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-zA-Z0-9]+", "-", sans_accents).strip("-").lower()

    extension = segment_securise(chemin.suffix.lstrip("."))
    radical = segment_securise(chemin.stem) or "document"
    radical = radical[:70].rstrip("-") or "document"
    identifiant = uuid.uuid4().hex[:8]
    return f"{radical}-{identifiant}{f'.{extension}' if extension else ''}"


def valider_periode_document(*, permanent, periode_debut, periode_fin):
    if permanent:
        return None, None, None
    if not periode_debut or not periode_fin:
        return periode_debut, periode_fin, "Renseigne une date de début et une date de fin, ou choisis Permanent."
    if periode_fin < periode_debut:
        return periode_debut, periode_fin, "La date de fin doit être postérieure ou égale à la date de début."
    return periode_debut, periode_fin, None
