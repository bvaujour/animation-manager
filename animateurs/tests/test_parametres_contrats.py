import datetime
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from animateurs.models import (
    Animateur,
    BaremeApprentissage,
    Contrat,
    ReferenceSMIC,
    TypeContrat,
    TypePrime,
)
from animateurs.services.contrats import assurer_types_contrats_systeme, contrat_pour_date, situation_contractuelle_pour_date
from animateurs.services.parametres import get_parametres_structure, prime_est_eligible
from animateurs.services.remunerations_contrats import (
    age_applicable_apprentissage,
    date_effet_changement_age,
    heures_mensuelles_contrat,
    remuneration_apprentissage_pour_date,
    remuneration_mensualisee_pour_date,
    smic_pour_date,
)


class ReferentielsContratsTests(TestCase):
    def setUp(self):
        self.structure = get_parametres_structure()
        self.animateur = Animateur.objects.create(prenom="Camille", nom="Contrats")

    def type(self, code):
        return self.structure.types_contrats.get(code=code)

    def test_les_quatre_types_systeme_sont_disponibles(self):
        assurer_types_contrats_systeme(self.structure)
        self.assertEqual(
            set(self.structure.types_contrats.filter(systeme=True).values_list("code", flat=True)),
            {"cee", "cdd", "apprentissage", "permanent"},
        )

    def test_type_personnalise_mensualise(self):
        type_cdi = TypeContrat.objects.create(
            structure=self.structure, nom="CDI", code="cdi",
            mode_remuneration=TypeContrat.MODE_MENSUALISE,
        )
        contrat = Contrat.objects.create(
            animateur=self.animateur, type_contrat_ref=type_cdi, type_contrat="cdi",
            date_debut=datetime.date(2026, 1, 1), salaire_mensuel_reference=Decimal("2000"),
        )
        self.assertEqual(contrat.mode_paie, TypeContrat.MODE_MENSUALISE)
        self.assertEqual(situation_contractuelle_pour_date(self.animateur, datetime.date(2026, 8, 1)).type_contrat, "cdi")

    def test_type_systeme_ne_peut_pas_etre_supprime(self):
        with self.assertRaises(ValidationError):
            self.type("cee").delete()

    def test_permanent_sans_salaire_est_valide(self):
        contrat = Contrat(
            animateur=self.animateur, type_contrat_ref=self.type("permanent"),
            type_contrat="permanent", date_debut=datetime.date(2025, 9, 1),
        )
        contrat.full_clean()
        self.assertEqual(contrat.mode_paie, TypeContrat.MODE_PAIE_HABITUELLE)

    def test_permanent_accepte_toutes_les_combinaisons_de_bornes(self):
        cas = (
            (None, None),
            (datetime.date(2025, 9, 1), None),
            (None, datetime.date(2026, 8, 31)),
            (datetime.date(2025, 9, 1), datetime.date(2026, 8, 31)),
        )
        for index, (debut, fin) in enumerate(cas):
            animateur = Animateur.objects.create(prenom=f"Permanent {index}", nom="Bornes")
            contrat = Contrat.objects.create(
                animateur=animateur, type_contrat_ref=self.type("permanent"),
                type_contrat="permanent", date_debut=debut, date_fin=fin,
            )
            self.assertEqual(contrat.statut, Contrat.STATUT_EN_COURS)

    def test_applicabilite_des_bornes_ouvertes(self):
        sans_bornes = Contrat.objects.create(
            animateur=self.animateur, type_contrat_ref=self.type("permanent"),
            type_contrat="permanent", date_debut=None, date_fin=None,
        )
        self.assertEqual(contrat_pour_date(self.animateur, datetime.date(1990, 1, 1)), sans_bornes)
        self.assertEqual(contrat_pour_date(self.animateur, datetime.date(2090, 1, 1)), sans_bornes)

        avec_debut = Animateur.objects.create(prenom="Avec", nom="Début")
        Contrat.objects.create(
            animateur=avec_debut, type_contrat_ref=self.type("permanent"), type_contrat="permanent",
            date_debut=datetime.date(2026, 8, 1), date_fin=None,
        )
        self.assertIsNone(contrat_pour_date(avec_debut, datetime.date(2026, 7, 31)))
        self.assertIsNotNone(contrat_pour_date(avec_debut, datetime.date(2026, 8, 1)))

        avec_fin = Animateur.objects.create(prenom="Avec", nom="Fin")
        Contrat.objects.create(
            animateur=avec_fin, type_contrat_ref=self.type("permanent"), type_contrat="permanent",
            date_debut=None, date_fin=datetime.date(2026, 8, 31),
        )
        self.assertIsNotNone(contrat_pour_date(avec_fin, datetime.date(2026, 8, 31)))
        self.assertIsNone(contrat_pour_date(avec_fin, datetime.date(2026, 9, 1)))

    def test_autres_modes_exigent_toujours_une_date_debut(self):
        cas = (
            ("cee", {"taux_journalier_reference": Decimal("50")}),
            ("cdd", {"salaire_mensuel_reference": Decimal("1800")}),
            ("apprentissage", {"salaire_mensuel_reference": Decimal("900")}),
        )
        for code, remuneration in cas:
            with self.subTest(code=code), self.assertRaisesMessage(ValidationError, "date de début"):
                Contrat.objects.create(animateur=self.animateur, type_contrat=code, date_debut=None, **remuneration)

    def test_permanent_sans_bornes_bloque_un_contrat_concurrent(self):
        Contrat.objects.create(
            animateur=self.animateur, type_contrat_ref=self.type("permanent"),
            type_contrat="permanent", date_debut=None, date_fin=None,
        )
        with self.assertRaisesMessage(ValidationError, "chevauche"):
            Contrat.objects.create(
                animateur=self.animateur, type_contrat="cdd",
                date_debut=datetime.date(2026, 9, 1), salaire_mensuel_reference=Decimal("1800"),
            )

    def test_prime_reconnait_un_permanent_sans_bornes(self):
        Contrat.objects.create(
            animateur=self.animateur, type_contrat_ref=self.type("permanent"),
            type_contrat="permanent", date_debut=None, date_fin=None,
        )
        prime = TypePrime.objects.create(
            structure=self.structure, nom="Prime permanent", active=False,
            montant_fixe=Decimal("10"), contrats_eligibles=["permanent"],
        )
        prime.types_contrats_eligibles.add(self.type("permanent"))
        prime.active = True
        prime.save()
        self.assertTrue(prime_est_eligible(
            prime, animateur=self.animateur, date=datetime.date(2026, 8, 18)
        ))

    def test_prime_eligible_a_un_type_personnalise(self):
        type_cdi = TypeContrat.objects.create(
            structure=self.structure, nom="CDI", code="cdi-prime",
            mode_remuneration=TypeContrat.MODE_MENSUALISE,
        )
        prime = TypePrime.objects.create(
            structure=self.structure, nom="Prime CDI", active=False,
            mode_calcul=TypePrime.MODE_MOIS, type_montant=TypePrime.MONTANT_FIXE,
            montant_fixe=Decimal("20"), contrats_eligibles=[type_cdi.code],
        )
        prime.types_contrats_eligibles.add(type_cdi)
        prime.active = True
        prime.save()
        self.assertTrue(prime_est_eligible(prime, contrat=type_cdi.code))
        self.assertFalse(prime_est_eligible(prime, contrat="cee"))


class ReferencesRemunerationTests(TestCase):
    def setUp(self):
        self.structure = get_parametres_structure()
        self.animateur = Animateur.objects.create(
            prenom="Alex", nom="Références", date_naissance=datetime.date(2008, 2, 18)
        )

    def test_smic_est_historise(self):
        ReferenceSMIC.objects.create(structure=self.structure, date_effet=datetime.date(2026, 1, 1), montant_horaire=Decimal("11.0000"))
        ReferenceSMIC.objects.create(structure=self.structure, date_effet=datetime.date(2026, 6, 1), montant_horaire=Decimal("12.0000"))
        self.assertEqual(smic_pour_date(datetime.date(2026, 5, 1), self.structure).montant_horaire, Decimal("11.0000"))
        self.assertEqual(smic_pour_date(datetime.date(2026, 7, 1), self.structure).montant_horaire, Decimal("12.0000"))

    def test_equivalent_mensuel_hebdomadaire(self):
        contrat = Contrat(mode_temps_travail=Contrat.TEMPS_HEBDOMADAIRE, heures_hebdomadaires=Decimal("30"))
        self.assertEqual(heures_mensuelles_contrat(contrat), Decimal("130.00"))

    def test_cdd_minimum_smic_automatique(self):
        ReferenceSMIC.objects.create(structure=self.structure, date_effet=datetime.date(2026, 1, 1), montant_horaire=Decimal("12"))
        contrat = Contrat(
            animateur=self.animateur, type_contrat="cdd", date_debut=datetime.date(2026, 1, 1),
            mode_temps_travail=Contrat.TEMPS_MENSUEL, heures_mensuelles_reference=Decimal("130"),
            mode_remuneration=Contrat.REMUNERATION_MINIMUM_SMIC,
        )
        reference = remuneration_mensualisee_pour_date(contrat, datetime.date(2026, 8, 1), self.structure)
        self.assertEqual(reference.montant_retenu, Decimal("1560.00"))

    def test_cdd_fixe_inferieur_au_minimum_est_signale_sans_etre_remplace(self):
        ReferenceSMIC.objects.create(structure=self.structure, date_effet=datetime.date(2026, 1, 1), montant_horaire=Decimal("12"))
        contrat = Contrat(
            animateur=self.animateur, type_contrat="cdd", date_debut=datetime.date(2026, 1, 1),
            salaire_mensuel_reference=Decimal("1500"), mode_temps_travail=Contrat.TEMPS_MENSUEL,
            heures_mensuelles_reference=Decimal("130"), mode_remuneration=Contrat.REMUNERATION_FIXE_CONTROLE,
        )
        reference = remuneration_mensualisee_pour_date(contrat, datetime.date(2026, 8, 1), self.structure)
        self.assertEqual(reference.montant_retenu, Decimal("1500"))
        self.assertEqual(reference.minimum_calcule, Decimal("1560.00"))
        self.assertTrue(reference.alertes)

    def test_annualise_sans_equivalent_ne_fabrique_pas_de_minimum(self):
        contrat = Contrat(
            animateur=self.animateur, type_contrat="cdd", date_debut=datetime.date(2026, 1, 1),
            salaire_mensuel_reference=Decimal("1900"), mode_temps_travail=Contrat.TEMPS_ANNUALISE,
            heures_annuelles_reference=Decimal("1400"), mode_remuneration=Contrat.REMUNERATION_FIXE_CONTROLE,
        )
        reference = remuneration_mensualisee_pour_date(contrat, datetime.date(2026, 8, 1), self.structure)
        self.assertEqual(reference.montant_retenu, Decimal("1900"))
        self.assertIsNone(reference.minimum_calcule)
        self.assertTrue(reference.alertes)

    def test_changement_age_prend_effet_le_mois_suivant(self):
        anniversaire = datetime.date(2027, 2, 18)
        self.assertEqual(date_effet_changement_age(anniversaire), datetime.date(2027, 3, 1))
        self.assertEqual(age_applicable_apprentissage(self.animateur.date_naissance, datetime.date(2027, 2, 28)), 18)
        self.assertEqual(age_applicable_apprentissage(self.animateur.date_naissance, datetime.date(2027, 3, 1)), 19)

    def test_apprentissage_grille_et_salaire_superieur(self):
        ReferenceSMIC.objects.create(
            structure=self.structure, date_effet=datetime.date(2026, 1, 1),
            montant_horaire=Decimal("10"), montant_mensuel_35h=Decimal("1500"),
        )
        BaremeApprentissage.objects.create(
            structure=self.structure, date_effet=datetime.date(2026, 1, 1),
            annee_execution=1, age_minimum=18, age_maximum=20, pourcentage_smic=Decimal("50"),
        )
        contrat = Contrat(
            animateur=self.animateur, type_contrat="apprentissage", date_debut=datetime.date(2026, 3, 1),
            salaire_mensuel_reference=Decimal("850"), mode_remuneration=Contrat.REMUNERATION_GRILLE_CONTROLE,
            annee_execution_initiale=1,
        )
        reference = remuneration_apprentissage_pour_date(contrat, datetime.date(2026, 8, 1), self.structure)
        self.assertEqual(reference.minimum_calcule, Decimal("750.00"))
        self.assertEqual(reference.montant_retenu, Decimal("850"))


class ParametresContratsApiTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="param-contracts", password="secret", email="param@example.test"
        )
        self.client.force_login(self.superuser)

    def test_api_superuser_expose_referentiels_et_cree_un_type(self):
        url = reverse("api_parametres_contrats")
        data = self.client.get(url).json()
        self.assertEqual({item["code"] for item in data["types"]}, {"cee", "cdd", "apprentissage", "permanent"})
        response = self.client.post(
            url,
            data=json.dumps({
                "ressource": "type", "nom": "CDI", "code": "cdi",
                "mode_remuneration": TypeContrat.MODE_MENSUALISE, "actif": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "cdi")

    def test_api_refuse_un_non_superuser(self):
        self.client.logout()
        user = get_user_model().objects.create_user(username="direction-simple", password="secret", is_staff=True)
        self.client.force_login(user)
        self.assertNotEqual(self.client.get(reverse("api_parametres_contrats")).status_code, 200)
