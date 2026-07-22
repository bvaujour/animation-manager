"""Validation commune des périodes de documents."""


def valider_periode_document(*, permanent, periode_debut, periode_fin):
    if permanent:
        return None, None, None
    if not periode_debut or not periode_fin:
        return periode_debut, periode_fin, "Renseigne une date de début et une date de fin, ou choisis Permanent."
    if periode_fin < periode_debut:
        return periode_debut, periode_fin, "La date de fin doit être postérieure ou égale à la date de début."
    return periode_debut, periode_fin, None
