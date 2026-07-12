import datetime

from django.test import TestCase

from animateurs.models import Animateur, Disponibilite
from animateurs.services.disponibilites import fusionner_et_nettoyer_disponibilites


class DisponibiliteServiceTests(TestCase):
    def test_fusionne_les_plages_qui_se_touchent(self):
        animateur = Animateur.objects.create(prenom="Ambre", nom="Test")
        aujourd_hui = datetime.date(2026, 7, 1)
        Disponibilite.objects.create(animateur=animateur, debut=aujourd_hui, fin=datetime.date(2026, 7, 3))
        Disponibilite.objects.create(animateur=animateur, debut=datetime.date(2026, 7, 4), fin=datetime.date(2026, 7, 6))
        fusionner_et_nettoyer_disponibilites(animateur, aujourd_hui=aujourd_hui)
        plages = list(animateur.disponibilites.values_list("debut", "fin"))
        self.assertEqual(plages, [(datetime.date(2026, 7, 1), datetime.date(2026, 7, 6))])

    def test_supprime_les_plages_passees(self):
        animateur = Animateur.objects.create(prenom="Gaël", nom="Test")
        Disponibilite.objects.create(
            animateur=animateur,
            debut=datetime.date(2026, 6, 1),
            fin=datetime.date(2026, 6, 2),
        )
        fusionner_et_nettoyer_disponibilites(animateur, aujourd_hui=datetime.date(2026, 7, 1))
        self.assertFalse(animateur.disponibilites.exists())
