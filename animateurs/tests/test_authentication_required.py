from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Evenement, Groupe


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
        self.assertContains(response, "Mon tableau de bord")

    def test_compte_salarie_accede_aux_pages_de_son_tableau_de_bord(self):
        user = get_user_model().objects.create_user(username="espace-unique", password="secret-test")
        Animateur.objects.create(prenom="Alice", nom="Unique", utilisateur=user)
        self.client.force_login(user)

        for route in ("mon_planning", "mon_profil", "documents", "mes_disponibilites"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)

    def test_api_planning_salarie_retourne_toute_equipe_de_son_lieu(self):
        user = get_user_model().objects.create_user(username="planning-perso", password="secret-test")
        animateur = Animateur.objects.create(prenom="Alice", nom="Planning", utilisateur=user)
        autre = Animateur.objects.create(prenom="Bob", nom="Autre")
        centre = Centre.objects.create(nom="Centre test", code="CT")
        groupe = Groupe.objects.create(nom="Élémentaires")
        evenement = Evenement.objects.create(centre=centre, groupe=groupe, nom=groupe.nom)
        debut = timezone.now()
        for salarie in (animateur, autre):
            Affectation.objects.create(
                animateur=salarie, centre=centre, evenement=evenement,
                debut=debut, fin=debut + timedelta(days=1),
            )
        self.client.force_login(user)

        response = self.client.get(reverse("api_planning"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        self.assertEqual(
            {item["extendedProps"]["animateur_id"] for item in response.json()},
            {animateur.id, autre.id},
        )

    def test_deux_lieux_affectes_dans_la_semaine_sont_visibles(self):
        user = get_user_model().objects.create_user(username="deux-lieux", password="secret-test")
        animateur = Animateur.objects.create(prenom="Alice", nom="Mobile", utilisateur=user)
        debut = timezone.now()
        centres = []
        for index in range(2):
            centre = Centre.objects.create(nom=f"Centre {index}", code=f"C{index}")
            groupe = Groupe.objects.create(nom=f"Groupe {index}")
            evenement = Evenement.objects.create(centre=centre, groupe=groupe, nom=groupe.nom)
            Affectation.objects.create(
                animateur=animateur,
                centre=centre,
                evenement=evenement,
                debut=debut + timedelta(days=index),
                fin=debut + timedelta(days=index + 1),
            )
            centres.append(centre)
        self.client.force_login(user)
        fin = debut + timedelta(days=7)

        response = self.client.get(
            reverse("api_centres"),
            {"include_groupes": "1", "start": debut.isoformat(), "end": fin.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()}, {centre.id for centre in centres})

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
