import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from animateurs.models import Animateur, ParametresStructure
from animateurs.services.parametres import get_parametres_structure
from animateurs.services.recapitulatif import _montant
from animateurs.tests.base import ConnexionTestCase


class ParametresStructureTests(TestCase):
    def test_service_cree_et_reutilise_les_valeurs_par_defaut(self):
        premier = get_parametres_structure()
        second = get_parametres_structure()
        self.assertEqual(premier.pk, second.pk)
        self.assertEqual(premier.cle, "principale")
        self.assertEqual(premier.taux_indemnite_cp_cee, Decimal("10.00"))
        self.assertEqual(premier.prime_journaliere_maximale, Decimal("7.00"))
        self.assertEqual(ParametresStructure.objects.count(), 1)


class ParametresApiTests(ConnexionTestCase):
    def setUp(self):
        self.page_url = reverse("parametres")
        self.api_url = reverse("api_parametres")

    def _payload(self, **changes):
        payload = {
            "nom_structure": "AJS",
            "adresse": "1 rue des Écoles",
            "code_postal": "42300",
            "ville": "Roanne",
            "telephone": "04 00 00 00 00",
            "email": "contact@example.org",
            "taux_indemnite_cp_cee": "10.00",
            "prime_journaliere_maximale": "7.00",
        }
        payload.update(changes)
        return payload

    def test_superuser_accede_a_la_page_et_a_l_api(self):
        page = self.client.get(self.page_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Paramètres")
        self.assertContains(page, "Planning &amp; RH", html=False)
        self.assertEqual(self.client.get(self.api_url).status_code, 200)

    def test_modification_structure_et_taux_persiste_apres_relecture(self):
        response = self.client.put(
            self.api_url,
            data=json.dumps(self._payload(nom_structure="Association Jeunesse", taux_indemnite_cp_cee="12.50")),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["nom_structure"], "Association Jeunesse")
        self.assertEqual(response.json()["taux_indemnite_cp_cee"], "12.50")
        relu = self.client.get(self.api_url).json()
        self.assertEqual(relu["nom_structure"], "Association Jeunesse")
        self.assertEqual(relu["taux_indemnite_cp_cee"], "12.50")

    def test_validation_refuse_un_pourcentage_negatif_ou_deraisonnable(self):
        for taux in ("-0.01", "100.01", "invalide"):
            with self.subTest(taux=taux):
                response = self.client.put(
                    self.api_url,
                    data=json.dumps(self._payload(taux_indemnite_cp_cee=taux)),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)

    def test_enregistrement_reaffiche_la_reponse_fraiche_du_serveur(self):
        script = Path(settings.BASE_DIR, "static/js/parametres.js").read_text(encoding="utf-8")
        self.assertIn("const saved = await apiFetch", script)
        self.assertIn("afficher(saved)", script)
        self.assertNotIn("fetch(", script)

    def test_changer_le_taux_cp_ne_modifie_pas_la_paie_actuelle(self):
        animateur = Animateur.objects.create(prenom="Julie", nom="Paie", paie_jour=Decimal("50.00"))
        avant = _montant(2, animateur.paie_jour)
        self.client.put(
            self.api_url,
            data=json.dumps(self._payload(taux_indemnite_cp_cee="25.00")),
            content_type="application/json",
        )
        animateur.refresh_from_db()
        self.assertEqual(_montant(2, animateur.paie_jour), avant)
        self.assertEqual(avant, "100.00")

    def test_gestion_reste_une_page_distincte(self):
        response = self.client.get(reverse("gestion"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Périodes scolaires")
        self.assertNotContains(response, "Taux indemnité congés payés CEE")


class ParametresPermissionsTests(TestCase):
    def setUp(self):
        self.page_url = reverse("parametres")
        self.api_url = reverse("api_parametres")

    def test_direction_non_superuser_est_refusee(self):
        user = get_user_model().objects.create_user(username="direction", password="secret", is_staff=True)
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get(self.page_url).status_code, 403)
        self.assertEqual(client.get(self.api_url).status_code, 403)
        self.assertEqual(client.put(self.api_url, data="{}", content_type="application/json").status_code, 403)

    def test_animateur_est_refuse_et_ne_voit_pas_la_navigation(self):
        user = get_user_model().objects.create_user(username="animateur-parametres", password="secret")
        Animateur.objects.create(prenom="Ambre", nom="Portail", utilisateur=user)
        client = Client()
        client.force_login(user)
        self.assertRedirects(client.get(self.page_url), reverse("accueil"))
        self.assertEqual(client.get(self.api_url).status_code, 403)
        accueil = client.get(reverse("accueil"))
        self.assertNotContains(accueil, 'aria-label="Paramètres"')

    def test_anonyme_ne_peut_ni_lire_ni_modifier(self):
        client = Client()
        self.assertEqual(client.get(self.api_url).status_code, 401)
        self.assertEqual(client.put(self.api_url, data="{}", content_type="application/json").status_code, 401)
