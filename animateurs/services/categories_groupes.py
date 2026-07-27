"""Catégories d'âge partagées par les agrégats issus du Planning."""


def categorie_age_groupe(groupe):
    """Identifie la catégorie depuis le groupe partagé normalisé.

    Aucun champ de catégorie n'existe actuellement. La clé normalisée du
    groupe partagé est plus stable que le libellé propre à chaque lieu et
    reprend la règle historique du tableau de bord.
    """

    cle = groupe.groupe.cle_unique if groupe.groupe_id else groupe.cle_unique
    if "maternel" in cle or "3 5" in cle or "3 6" in cle:
        return "maternelle"
    if "elementair" in cle or "6 10" in cle or "6 11" in cle:
        return "elementaire"
    return "autre"
