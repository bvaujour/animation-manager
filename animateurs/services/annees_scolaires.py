"""Transitions explicites et socle de verrouillage des années scolaires."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from animateurs.models import AnneeScolaire


def annee_est_cloturee(libelle):
    return AnneeScolaire.objects.filter(libelle=libelle, statut=AnneeScolaire.Statut.CLOTUREE).exists()


def changer_etat_annee(pk, *, reouvrir=False):
    try:
        with transaction.atomic():
            annee = AnneeScolaire.objects.select_for_update().get(pk=pk)
            attendu = AnneeScolaire.Statut.CLOTUREE if reouvrir else AnneeScolaire.Statut.ACTIVE
            if annee.statut != attendu:
                raise ValidationError("Seule une année clôturée peut être réouverte." if reouvrir else "Seule une année active peut être clôturée.")
            if reouvrir and AnneeScolaire.objects.filter(statut=AnneeScolaire.Statut.ACTIVE).exists():
                raise ValidationError("Une autre année scolaire est déjà active. Réouverture impossible.")
            annee.statut = AnneeScolaire.Statut.ACTIVE if reouvrir else AnneeScolaire.Statut.CLOTUREE
            annee.date_cloture = None if reouvrir else timezone.now()
            annee.save(update_fields=["statut", "date_cloture", "date_modification"])
            return annee
    except IntegrityError:
        # La contrainte unique protège aussi deux activations concurrentes.
        if not reouvrir:
            raise
        raise ValidationError("Une autre année scolaire est déjà active. Réouverture impossible.") from None
