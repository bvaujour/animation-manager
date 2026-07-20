import datetime

from django.test import TestCase
from django.utils import timezone

from animateurs.models import Affectation, AffiniteGroupeAnimateur, Animateur, Centre
from animateurs.services.affinites import synchroniser_affinites_groupes
from animateurs.tests.factories import creer_groupe


class AffiniteGroupeAnimateurTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="Centre affinité",
            code="AFF",
            couleur="#123456",
        )
        self.groupe, _ = creer_groupe(self.centre, nom="Maternelles")
        self.animateur = Animateur.objects.create(prenom="Alice", nom="Affinité")

    def creer_affectation(self, debut, duree=1):
        debut_dt = timezone.make_aware(datetime.datetime.combine(debut, datetime.time.min))
        return Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut_dt,
            fin=debut_dt + datetime.timedelta(days=duree),
        )

    def test_une_journee_terminee_ajoute_un_point(self):
        hier = timezone.localdate() - datetime.timedelta(days=1)

        self.creer_affectation(hier)

        affinite = AffiniteGroupeAnimateur.objects.get(
            animateur=self.animateur,
            evenement=self.groupe,
        )
        self.assertEqual(affinite.jours_travailles, 1)
        self.assertEqual(affinite.score, 1)
        self.assertEqual(affinite.dernier_jour_travaille, hier)

    def test_une_affectation_future_n_augmente_pas_le_score(self):
        demain = timezone.localdate() + datetime.timedelta(days=1)

        self.creer_affectation(demain)

        self.assertFalse(
            AffiniteGroupeAnimateur.objects.filter(
                animateur=self.animateur,
                evenement=self.groupe,
            ).exists()
        )

    def test_une_affectation_de_plusieurs_jours_ajoute_un_point_par_jour(self):
        debut = timezone.localdate() - datetime.timedelta(days=3)

        self.creer_affectation(debut, duree=3)

        affinite = AffiniteGroupeAnimateur.objects.get(
            animateur=self.animateur,
            evenement=self.groupe,
        )
        self.assertEqual(affinite.jours_travailles, 3)

    def test_supprimer_une_journee_recalcule_le_score(self):
        avant_hier = timezone.localdate() - datetime.timedelta(days=2)
        hier = timezone.localdate() - datetime.timedelta(days=1)
        self.creer_affectation(avant_hier)
        affectation_hier = self.creer_affectation(hier)
        self.assertEqual(
            AffiniteGroupeAnimateur.objects.get(
                animateur=self.animateur,
                evenement=self.groupe,
            ).jours_travailles,
            2,
        )

        affectation_hier.delete()

        affinite = AffiniteGroupeAnimateur.objects.get(
            animateur=self.animateur,
            evenement=self.groupe,
        )
        self.assertEqual(affinite.jours_travailles, 1)
        self.assertEqual(affinite.dernier_jour_travaille, avant_hier)

    def test_la_synchronisation_repare_un_score_incorrect(self):
        hier = timezone.localdate() - datetime.timedelta(days=1)
        self.creer_affectation(hier)
        AffiniteGroupeAnimateur.objects.filter(
            animateur=self.animateur,
            evenement=self.groupe,
        ).update(jours_travailles=99)

        synchroniser_affinites_groupes()

        affinite = AffiniteGroupeAnimateur.objects.get(
            animateur=self.animateur,
            evenement=self.groupe,
        )
        self.assertEqual(affinite.jours_travailles, 1)
