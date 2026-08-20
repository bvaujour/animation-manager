from base64 import urlsafe_b64encode

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes

from animateurs.models import Animateur
from animateurs.services.comptes import creer_compte_animateur, nom_utilisateur_disponible, valider_mot_de_passe


class ComptesAnimateursTests(TestCase):
    def test_identifiant_utilise_initiale_et_nom_normalises(self):
        self.assertEqual(nom_utilisateur_disponible("Bruno", "Vaujour"), "bvaujour")
        self.assertEqual(nom_utilisateur_disponible("Élodie", "Le-Clerc"), "eleclerc")

    def test_identifiant_numerote_les_doublons(self):
        get_user_model().objects.create_user(username="bvaujour", password="abcde")
        self.assertEqual(nom_utilisateur_disponible("Bruno", "Vaujour"), "bvaujour2")

    def test_creation_compte_associe_l_utilisateur(self):
        animateur = Animateur.objects.create(prenom="Bruno", nom="Vaujour", email="bruno@example.com")

        identifiants = creer_compte_animateur(animateur)

        animateur.refresh_from_db()
        self.assertEqual(identifiants["username"], "bvaujour")
        self.assertEqual(animateur.utilisateur.username, "bvaujour")
        self.assertTrue(animateur.doit_changer_mot_de_passe)

    def test_lien_activation_permet_de_choisir_un_mot_de_passe_une_fois(self):
        animateur = Animateur.objects.create(prenom="Bruno", nom="Vaujour")
        creer_compte_animateur(animateur)
        utilisateur = animateur.utilisateur
        uid = urlsafe_b64encode(force_bytes(utilisateur.pk)).decode().rstrip("=")
        url = reverse("activation_compte", kwargs={"uidb64": uid, "token": default_token_generator.make_token(utilisateur)})

        response = self.client.post(url, {"new_password1": "NouveauMot!123", "new_password2": "NouveauMot!123"})

        self.assertEqual(response.status_code, 302)
        utilisateur.refresh_from_db()
        self.assertTrue(utilisateur.is_active)
        self.assertTrue(utilisateur.check_password("NouveauMot!123"))
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_seule_la_longueur_minimale_est_verifiee(self):
        self.assertTrue(valider_mot_de_passe("1234"))
        self.assertEqual(valider_mot_de_passe("12345"), "")


class ProfilAnimateurTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="amartin",
            email="ancienne@example.com",
            password="abcde",
        )
        self.animateur = Animateur.objects.create(
            prenom="Alice",
            nom="Martin",
            telephone="0102030405",
            email="ancienne@example.com",
            utilisateur=self.user,
        )
        self.client.force_login(self.user)

    def test_animateur_modifie_telephone_et_email(self):
        response = self.client.post(
            reverse("mon_profil"),
            {
                "action": "coordonnees",
                "telephone": "0612345678",
                "email": "nouvelle@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.animateur.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.animateur.telephone, "0612345678")
        self.assertEqual(self.animateur.email, "nouvelle@example.com")
        self.assertEqual(self.user.email, "nouvelle@example.com")

    def test_animateur_change_son_mot_de_passe_et_reste_connecte(self):
        response = self.client.post(
            reverse("mon_profil"),
            {
                "action": "mot_de_passe",
                "mot_de_passe": "12345",
                "confirmation": "12345",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("12345"))
        self.assertIn("_auth_user_id", self.client.session)
