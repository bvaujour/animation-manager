from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from animateurs.models import Animateur


class PortailAnimateurEtape1Tests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="amartin", password="secret")
        Animateur.objects.create(prenom="Alice", nom="Martin", utilisateur=user)
        self.client.force_login(user)

    def test_les_cinq_espaces_sont_accessibles(self):
        espaces = {
            "accueil": "Accueil",
            "plannings_animateur": "Plannings",
            "infos_animateur": "Infos",
            "demandes_materiel": "Matériel",
            "mon_profil": "Mon profil",
        }
        for route, libelle in espaces.items():
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, libelle)

    def test_la_navigation_ne_contient_que_les_cinq_espaces_principaux(self):
        response = self.client.get(reverse("accueil"))
        for libelle in ("Accueil", "Plannings", "Infos", "Matériel", "Profil"):
            self.assertContains(response, libelle)
        self.assertNotContains(response, "Mercredis")
        self.assertNotContains(response, "Séjours")

    def test_accueil_conserve_la_semaine_selectionnee_dans_les_liens(self):
        response = self.client.get(reverse("accueil"), {"semaine": "2026-08-24"})
        self.assertContains(response, "semaine=2026-08-24")
        self.assertNotContains(response, "aujourd'hui")

    def test_pages_secondaires_sorties_et_documents_accessibles(self):
        for route, titre in (("sorties_animateur", "Sorties"), ("documents_animateur", "Documents")):
            with self.subTest(route=route):
                response = self.client.get(reverse(route), {"semaine": "2026-08-24"})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, titre)
                self.assertContains(response, "Retour à l'accueil")

    def test_infos_ne_contient_plus_sorties_documents_ou_reunions(self):
        response = self.client.get(reverse("infos_animateur"))
        self.assertContains(response, "Aucune information pour cette période.")
        self.assertNotContains(response, "Sorties de la semaine")
        self.assertNotContains(response, "Documents")
        self.assertNotContains(response, "Réunions")
