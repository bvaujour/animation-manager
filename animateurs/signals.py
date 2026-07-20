"""Maintient les affinités quand une affectation historique est modifiée."""

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from animateurs.models import Affectation
from animateurs.services.affinites import recalculer_affinite_groupe


@receiver(pre_save, sender=Affectation)
def memoriser_ancienne_affectation(sender, instance, **kwargs):
    if not instance.pk:
        instance._ancienne_affinite = None
        return
    instance._ancienne_affinite = sender.objects.filter(pk=instance.pk).values_list(
        "animateur_id",
        "evenement_id",
    ).first()


@receiver(post_save, sender=Affectation)
def actualiser_affinite_apres_enregistrement(sender, instance, raw=False, **kwargs):
    if raw:
        return
    ancienne = getattr(instance, "_ancienne_affinite", None)
    nouvelle = (instance.animateur_id, instance.evenement_id)
    if ancienne and ancienne != nouvelle:
        recalculer_affinite_groupe(*ancienne)
    recalculer_affinite_groupe(*nouvelle)


@receiver(post_delete, sender=Affectation)
def actualiser_affinite_apres_suppression(sender, instance, **kwargs):
    recalculer_affinite_groupe(instance.animateur_id, instance.evenement_id)
