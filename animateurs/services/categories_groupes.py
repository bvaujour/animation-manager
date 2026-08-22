"""Catégories d'âge partagées par les agrégats issus du Planning."""


def categorie_age_groupe(groupe):
    """Retourne ``maternelle``, ``elementaire`` ou ``autre``.

    La catégorie explicite du groupe partagé est prioritaire. Le repli par nom
    est conservé pour les anciennes bases tant que la migration 0105 n'a pas
    encore été appliquée.
    """

    groupe_partage = groupe.groupe if getattr(groupe, "groupe_id", None) else groupe
    categorie = getattr(groupe_partage, "categorie_age_reglementaire", "")
    if categorie == "moins_6":
        return "maternelle"
    if categorie == "six_plus":
        return "elementaire"

    cle = getattr(groupe_partage, "cle_unique", "") or ""
    if "maternel" in cle or "3 5" in cle or "3 6" in cle:
        return "maternelle"
    if "elementair" in cle or "6 10" in cle or "6 11" in cle:
        return "elementaire"
    return "autre"


def categorie_reglementaire_groupe(groupe):
    """Retourne la catégorie réglementaire stable utilisée par le calcul."""

    groupe_partage = groupe.groupe if getattr(groupe, "groupe_id", None) else groupe
    categorie = getattr(groupe_partage, "categorie_age_reglementaire", "")
    if categorie in {"moins_6", "six_plus"}:
        return categorie
    historique = categorie_age_groupe(groupe)
    if historique == "maternelle":
        return "moins_6"
    if historique == "elementaire":
        return "six_plus"
    return "autre"
