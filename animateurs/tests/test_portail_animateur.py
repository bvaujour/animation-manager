from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from animateurs.models import Animateur, InformationAnimateur


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


class InformationsPortailAnimateurTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.direction = User.objects.create_superuser(username="direction", password="secret", email="dir@example.com")
        self.user_alice = User.objects.create_user(username="alice", password="secret")
        self.alice = Animateur.objects.create(prenom="Alice", nom="Martin", utilisateur=self.user_alice)
        self.user_bob = User.objects.create_user(username="bob", password="secret")
        self.bob = Animateur.objects.create(prenom="Bob", nom="Durand", utilisateur=self.user_bob)

    def test_direction_peut_publier_une_information_importante(self):
        self.client.force_login(self.direction)
        response = self.client.post(
            reverse("gestion") + "?onglet=informations",
            {
                "module": "informations-animateurs",
                "action": "enregistrer",
                "titre": "Casquette obligatoire",
                "message": "Pensez à prendre une casquette vendredi.",
                "date_debut": "2026-08-17",
                "date_fin": "2026-08-21",
                "importance": "importante",
                "cible": "tous",
                "publie": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        info = InformationAnimateur.objects.get(titre="Casquette obligatoire")
        self.assertTrue(info.publie)
        self.assertTrue(info.tous_animateurs)
        self.assertEqual(info.importance, InformationAnimateur.IMPORTANCE_IMPORTANTE)
        self.assertContains(response, "L’information a été enregistrée.")

    def test_information_publiee_alimente_accueil_et_page_infos(self):
        InformationAnimateur.objects.create(
            titre="Consigne importante",
            message="Prendre une gourde.",
            date_debut="2026-08-17",
            date_fin="2026-08-21",
            importance=InformationAnimateur.IMPORTANCE_IMPORTANTE,
            publie=True,
            tous_animateurs=True,
            auteur=self.direction,
        )
        self.client.force_login(self.user_alice)
        accueil = self.client.get(reverse("accueil"), {"semaine": "2026-08-17"})
        self.assertEqual(accueil.status_code, 200)
        self.assertContains(accueil, "1 information importante")
        self.assertContains(accueil, "Important")
        infos = self.client.get(reverse("infos_animateur"), {"semaine": "2026-08-17"})
        self.assertContains(infos, "Consigne importante")
        self.assertContains(infos, "Prendre une gourde.")

    def test_information_ciblee_nest_visible_que_par_les_animateurs_selectionnes(self):
        info = InformationAnimateur.objects.create(
            titre="Info Alice",
            message="Uniquement pour Alice.",
            date_debut="2026-08-17",
            date_fin="2026-08-21",
            publie=True,
            tous_animateurs=False,
            auteur=self.direction,
        )
        info.animateurs.add(self.alice)

        self.client.force_login(self.user_alice)
        response = self.client.get(reverse("infos_animateur"), {"semaine": "2026-08-17"})
        self.assertContains(response, "Info Alice")

        self.client.force_login(self.user_bob)
        response = self.client.get(reverse("infos_animateur"), {"semaine": "2026-08-17"})
        self.assertNotContains(response, "Info Alice")
        self.assertContains(response, "Aucune information pour cette période.")

    def test_brouillon_ou_hors_periode_nest_pas_visible(self):
        InformationAnimateur.objects.create(
            titre="Brouillon",
            message="Invisible.",
            date_debut="2026-08-17",
            date_fin="2026-08-21",
            publie=False,
            tous_animateurs=True,
            auteur=self.direction,
        )
        InformationAnimateur.objects.create(
            titre="Septembre",
            message="Invisible en août.",
            date_debut="2026-09-01",
            date_fin="2026-09-30",
            publie=True,
            tous_animateurs=True,
            auteur=self.direction,
        )
        self.client.force_login(self.user_alice)
        response = self.client.get(reverse("infos_animateur"), {"semaine": "2026-08-17"})
        self.assertNotContains(response, "Brouillon")
        self.assertNotContains(response, "Septembre")
        self.assertContains(response, "Aucune information pour cette période.")
