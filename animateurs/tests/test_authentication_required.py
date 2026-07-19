from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from animateurs.models import Animateur


@override_settings(TESTING=False)
class AuthenticationRequiredTests(TestCase):
    def test_accueil_redirige_un_visiteur_vers_la_connexion(self):
        response = self.client.get(reverse("accueil"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(f'{reverse("login")}?next='))

    def test_page_connexion_reste_publique(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)

    def test_compte_salarie_connecte_peut_ouvrir_accueil(self):
        user = get_user_model().objects.create_user(username="animateur", password="secret-test")
        Animateur.objects.create(prenom="Alice", nom="Martin", utilisateur=user)
        self.client.force_login(user)
        response = self.client.get(reverse("accueil"))
        self.assertEqual(response.status_code, 200)

    def test_compte_salarie_peut_charger_les_semaines_de_l_accueil(self):
        user = get_user_model().objects.create_user(username="animateur-semaines", password="secret-test")
        Animateur.objects.create(prenom="Alice", nom="Semaines", utilisateur=user)
        self.client.force_login(user)

        response = self.client.get(reverse("api_periodes_scolaires"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_compte_ordinaire_sans_salarie_est_refuse(self):
        user = get_user_model().objects.create_user(username="orphelin", password="secret-test")
        self.client.force_login(user)
        response = self.client.get(reverse("accueil"))
        self.assertEqual(response.status_code, 403)

    def test_compte_maitre_sans_salarie_accede_a_toute_application(self):
        user = get_user_model().objects.create_superuser(
            username="maitre",
            email="maitre@example.com",
            password="secret-test",
        )
        self.assertFalse(hasattr(user, "profil_animateur"))
        self.client.force_login(user)

        # « emails » n'est plus une page : c'est une redirection de compatibilité
        # vers /administration/#emails. On teste donc « administration » directement.
        for route in ("accueil", "planning", "employes", "gestion", "recapitulatif", "administration"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)

    def test_compte_maitre_nest_pas_force_de_changer_un_mot_de_passe_provisoire(self):
        user = get_user_model().objects.create_superuser(
            username="secours",
            email="secours@example.com",
            password="secret-test",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accueil"))
        self.assertEqual(response.status_code, 200)
