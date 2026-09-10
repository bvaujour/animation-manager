"""Portée des groupes et règles de rattachement aux sites."""
from django.core.exceptions import ValidationError


def multisite_actif():
    from animateurs.models import ParametresStructure
    valeur = ParametresStructure.objects.filter(cle="principale").values_list("multisite", flat=True).first()
    return True if valeur is None else valeur


def valider_rattachement(groupe, centre_id):
    if groupe.portee == groupe.LOCAL and groupe.centre_id != centre_id:
        raise ValidationError("Ce groupe local appartient à un autre centre.")
    if not multisite_actif() and groupe.instances.exclude(centre_id=centre_id).exists():
        raise ValidationError("Le mode mono-site interdit un rattachement à plusieurs centres.")


def trouver_ou_creer_groupe(nom, centre, *, portee=None, defaults=None):
    from animateurs.models import Groupe, normaliser_cle_unique
    # Compatibilité des anciens appels en multisite ; un groupe explicitement
    # local est toujours recherché dans son propre centre, jamais globalement.
    portee = portee or (Groupe.PARTAGE if multisite_actif() else Groupe.LOCAL)
    if portee not in (Groupe.LOCAL, Groupe.PARTAGE):
        raise ValidationError("Portée du groupe invalide.")
    return Groupe.objects.get_or_create(
        cle_unique=normaliser_cle_unique(nom), portee=portee,
        centre=centre if portee == Groupe.LOCAL else None,
        defaults={"nom": nom, **(defaults or {})},
    )
