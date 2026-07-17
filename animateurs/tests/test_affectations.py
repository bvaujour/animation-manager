import datetime

from django.test import TestCase
from django.utils import timezone

from animateurs.models import Animateur, Centre, Disponibilite
from animateurs.tests.factories import creer_groupe
from animateurs.services.affectations import creer_affectation, modifier_affectation


class AffectationServiceTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Julie", nom="Test")
        self.centre_a = Centre.objects.create(nom="Centre A", code="A", couleur="#123456")
        self.centre_b = Centre.objects.create(nom="Centre B", code="B", couleur="#654321")
        self.groupe_a, _ = creer_groupe(self.centre_a, nom="Groupe A")
        self.groupe_b, _ = creer_groupe(self.centre_b, nom="Groupe B")
        self.jour = timezone.make_aware(datetime.datetime(2026, 7, 6))
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 6),
        )

    def test_refuse_un_doublon_le_meme_jour(self):
        creer_affectation(
            animateur=self.animateur,
            centre=self.centre_a,
            debut=self.jour,
            fin=self.jour + datetime.timedelta(days=1),
        )
        with self.assertRaisesMessage(ValueError, "déjà une affectation"):
            creer_affectation(
                animateur=self.animateur,
                centre=self.centre_b,
                debut=self.jour,
                fin=self.jour + datetime.timedelta(days=1),
            )

    def test_refuse_un_jour_hors_disponibilite(self):
        self.animateur.disponibilites.all().delete()
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 7),
            fin=datetime.date(2026, 7, 7),
        )
        with self.assertRaisesMessage(ValueError, "n'est pas disponible"):
            creer_affectation(
                animateur=self.animateur,
                centre=self.centre_a,
                debut=self.jour,
                fin=self.jour + datetime.timedelta(days=1),
            )


    def test_refuse_un_animateur_sans_disponibilite(self):
        self.animateur.disponibilites.all().delete()
        with self.assertRaisesMessage(ValueError, "n'est pas disponible"):
            creer_affectation(
                animateur=self.animateur,
                centre=self.centre_a,
                debut=self.jour,
                fin=self.jour + datetime.timedelta(days=1),
            )

    def test_deplacement_change_le_centre(self):
        affectation = creer_affectation(
            animateur=self.animateur,
            centre=self.centre_a,
            debut=self.jour,
            fin=self.jour + datetime.timedelta(days=1),
        )
        modifier_affectation(affectation, centre=self.centre_b)
        affectation.refresh_from_db()
        self.assertEqual(affectation.centre, self.centre_b)
