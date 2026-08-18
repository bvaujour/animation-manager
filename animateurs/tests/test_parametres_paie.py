import datetime
import importlib
import json
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from animateurs.models import Animateur, BaremeCEE, Contrat, ParametresStructure, Qualification, TypePrime
from animateurs.services.parametres import get_parametres_structure, prime_est_eligible, taux_cee_pour_date
from animateurs.services.recapitulatif import _montant
from animateurs.tests.base import ConnexionTestCase


class BaremeCEETests(ConnexionTestCase):
    def setUp(self):
        self.structure = get_parametres_structure()
        self.stagiaire = Qualification.objects.create(nom="Stagiaire BAFA", est_statut=True)
        self.diplome = Qualification.objects.create(nom="Diplômé BAFA", est_statut=True)
        self.url = reverse("api_baremes_cee")

    def test_api_recupere_les_statuts_existants(self):
        response = self.client.get(reverse("api_parametres_paie"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["nom"] for item in response.json()["statuts"]}, {"Stagiaire BAFA", "Diplômé BAFA"})

    def test_creation_decimal_et_historique_selon_date(self):
        for date_effet, montant in (("2026-01-01", "48.25"), ("2027-01-01", "51.75")):
            response = self.client.post(self.url, data=json.dumps({
                "statut_id": self.stagiaire.id, "date_effet": date_effet, "montant_journalier": montant,
            }), content_type="application/json")
            self.assertEqual(response.status_code, 201)
        self.assertEqual(BaremeCEE.objects.filter(statut=self.stagiaire).count(), 2)
        self.assertEqual(taux_cee_pour_date(self.stagiaire, datetime.date(2026, 12, 31)), Decimal("48.25"))
        self.assertEqual(taux_cee_pour_date(self.stagiaire, datetime.date(2027, 1, 1)), Decimal("51.75"))

    def test_correction_actuelle_ne_change_pas_une_date_historique(self):
        BaremeCEE.objects.create(
            structure=self.structure, statut=self.diplome,
            date_effet=datetime.date(2025, 1, 1), montant_journalier=Decimal("50.00"),
        )
        BaremeCEE.objects.create(
            structure=self.structure, statut=self.diplome,
            date_effet=datetime.date(2026, 8, 1), montant_journalier=Decimal("55.00"),
        )
        self.assertEqual(taux_cee_pour_date(self.diplome, datetime.date(2025, 7, 1)), Decimal("50.00"))
        self.assertEqual(taux_cee_pour_date(self.diplome, datetime.date(2026, 8, 2)), Decimal("55.00"))

    def test_adaptation_automatique_est_oui_par_defaut_et_modifiable(self):
        self.assertTrue(self.structure.adapter_taux_cee_changement_statut)
        payload = self.client.get(reverse("api_parametres")).json()
        payload["adapter_taux_cee_changement_statut"] = False
        response = self.client.put(reverse("api_parametres"), data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["adapter_taux_cee_changement_statut"])

    def test_bareme_n_a_aucun_effet_sur_la_paie_actuelle(self):
        animateur = Animateur.objects.create(prenom="Julie", nom="Historique", paie_jour=Decimal("47.00"))
        BaremeCEE.objects.create(
            structure=self.structure, statut=self.stagiaire,
            date_effet=datetime.date(2026, 1, 1), montant_journalier=Decimal("99.00"),
        )
        self.assertEqual(_montant(2, animateur.paie_jour), "94.00")


class TypePrimeTests(ConnexionTestCase):
    def setUp(self):
        self.structure = get_parametres_structure()
        self.statut_a = Qualification.objects.create(nom="Non diplômé", est_statut=True)
        self.statut_b = Qualification.objects.create(nom="Diplômé", est_statut=True)
        self.url = reverse("api_types_primes")

    def payload(self, **changes):
        donnees = {
            "nom": "Prime séjour", "description": "Test", "active": True,
            "mode_calcul": "jour", "type_montant": "fixe", "montant_fixe": "10.00",
            "montant_maximum": None, "contrats_eligibles": ["cee"],
            "tous_statuts": True, "statut_ids": [],
        }
        donnees.update(changes)
        return donnees

    def test_creation_prime_fixe_et_modes_disponibles(self):
        response = self.client.post(self.url, data=json.dumps(self.payload()), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["montant_fixe"], "10.00")
        modes = self.client.get(reverse("api_parametres_paie")).json()["modes_calcul"]
        self.assertEqual({item["value"] for item in modes}, {"jour", "semaine", "mois", "forfait"})

    def test_creation_prime_variable_plafonnee(self):
        response = self.client.post(self.url, data=json.dumps(self.payload(
            nom="Prime variable", type_montant="variable_plafonne", montant_fixe=None,
            montant_maximum="7.00", contrats_eligibles=["cee", "cdd", "apprentissage"],
        )), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["montant_maximum"], "7.00")

    def test_validations_montants_et_contrats_actifs(self):
        cas = (
            self.payload(montant_fixe="-1"),
            self.payload(montant_fixe=None),
            self.payload(type_montant="variable_plafonne", montant_fixe=None, montant_maximum=None),
            self.payload(contrats_eligibles=[]),
            self.payload(tous_statuts=False, statut_ids=[]),
        )
        for donnees in cas:
            with self.subTest(donnees=donnees):
                self.assertEqual(self.client.post(self.url, data=json.dumps(donnees), content_type="application/json").status_code, 400)

    def test_prime_inactive_incomplete_est_autorisee(self):
        response = self.client.post(self.url, data=json.dumps(self.payload(
            nom="À configurer", active=False, montant_fixe=None, contrats_eligibles=[],
        )), content_type="application/json")
        self.assertEqual(response.status_code, 201)

    def test_eligibilite_cee_cdd_apprentissage_et_prime_inactive(self):
        for index, type_contrat in enumerate(("cee", "cdd", "apprentissage")):
            prime = TypePrime.objects.create(
                structure=self.structure, nom=f"Prime {index}", active=True,
                mode_calcul="jour", type_montant="fixe", montant_fixe=5,
                contrats_eligibles=[type_contrat], tous_statuts=True,
            )
            self.assertTrue(prime_est_eligible(prime, contrat=type_contrat))
            self.assertFalse(prime_est_eligible(prime, contrat=({"cee", "cdd", "apprentissage"} - {type_contrat}).pop()))
        inactive = TypePrime.objects.create(
            structure=self.structure, nom="Inactive", active=False,
            contrats_eligibles=["cee", "cdd", "apprentissage"], tous_statuts=True,
        )
        self.assertFalse(prime_est_eligible(inactive, contrat="cee"))

    def test_restriction_a_certains_statuts(self):
        response = self.client.post(self.url, data=json.dumps(self.payload(
            nom="Prime diplômé", tous_statuts=False, statut_ids=[self.statut_b.id],
        )), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        prime = TypePrime.objects.get(pk=response.json()["id"])
        self.assertFalse(prime_est_eligible(prime, contrat="cee", statut=self.statut_a))
        self.assertTrue(prime_est_eligible(prime, contrat="cee", statut=self.statut_b))
        animateur = Animateur.objects.create(prenom="Ambre", nom="Éligibilité")
        animateur.qualifications.add(self.statut_b)
        Contrat.objects.create(
            animateur=animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31),
            taux_journalier_reference=Decimal("50.00"),
        )
        self.assertTrue(prime_est_eligible(
            prime, animateur=animateur, statut=self.statut_b, date=datetime.date(2026, 7, 15)
        ))

    def test_modification_activation_desactivation_et_suppression(self):
        creation = self.client.post(self.url, data=json.dumps(self.payload()), content_type="application/json").json()
        detail_url = reverse("api_type_prime_detail", args=[creation["id"]])
        modification = self.client.patch(detail_url, data=json.dumps(self.payload(
            nom="Prime séjour modifiée", active=False,
        )), content_type="application/json")
        self.assertEqual(modification.status_code, 200)
        self.assertFalse(modification.json()["active"])
        self.assertEqual(modification.json()["nom"], "Prime séjour modifiée")
        reactivation = self.client.patch(detail_url, data=json.dumps(self.payload(
            nom="Prime séjour modifiée", active=True,
        )), content_type="application/json")
        self.assertEqual(reactivation.status_code, 200)
        self.assertTrue(reactivation.json()["active"])
        self.assertEqual(self.client.delete(detail_url).status_code, 200)
        self.assertFalse(TypePrime.objects.filter(pk=creation["id"]).exists())


class MigrationPrimesInitialesTests(TestCase):
    def test_primes_initiales_reprennent_le_plafond_historique(self):
        structure = ParametresStructure.objects.create(
            cle="test-migration", prime_journaliere_maximale=Decimal("6.50")
        )
        migration = importlib.import_module(
            "animateurs.migrations.0095_parametresstructure_adapter_taux_cee_changement_statut_and_more"
        )
        migration.creer_primes_initiales(apps, None)
        autonomie = TypePrime.objects.get(structure=structure, nom="Prime d’autonomie")
        self.assertTrue(autonomie.active)
        self.assertEqual(autonomie.mode_calcul, "jour")
        self.assertEqual(autonomie.type_montant, "variable_plafonne")
        self.assertEqual(autonomie.montant_maximum, Decimal("6.50"))
        self.assertEqual(autonomie.contrats_eligibles, ["cee", "cdd", "apprentissage"])
        self.assertTrue(autonomie.tous_statuts)
        adjointe = TypePrime.objects.get(structure=structure, nom="Prime de direction adjointe")
        self.assertFalse(adjointe.active)
        self.assertIsNone(adjointe.montant_fixe)
        self.assertEqual(get_parametres_structure().prime_journaliere_maximale, Decimal("7.00"))


class ParametresPaiePermissionsTests(TestCase):
    def test_api_referentiels_interdite_aux_non_superusers(self):
        user = get_user_model().objects.create_user(username="sans-parametres-paie", password="secret", is_staff=True)
        client = Client()
        client.force_login(user)
        urls = (
            reverse("api_parametres_paie"), reverse("api_baremes_cee"), reverse("api_types_primes")
        )
        self.assertEqual(client.get(urls[0]).status_code, 403)
        self.assertEqual(client.post(urls[1], data="{}", content_type="application/json").status_code, 403)
        self.assertEqual(client.post(urls[2], data="{}", content_type="application/json").status_code, 403)
