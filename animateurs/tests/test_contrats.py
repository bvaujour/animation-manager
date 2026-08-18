import datetime
import json
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from animateurs.models import Animateur, Contrat
from animateurs.services.contrats import contrat_actuel, contrat_pour_date
from animateurs.tests.base import ConnexionTestCase


class ContratModeleTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Julie", nom="Contrats")

    def test_cree_les_trois_types_avec_la_remuneration_adaptee(self):
        cee = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31),
            taux_journalier_reference=Decimal("50.00"),
        )
        cdd = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CDD,
            date_debut=datetime.date(2026, 8, 1), date_fin=datetime.date(2027, 7, 31),
            salaire_mensuel_reference=Decimal("1850.00"),
        )
        apprentissage = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_APPRENTISSAGE,
            date_debut=datetime.date(2027, 8, 1), salaire_mensuel_reference=Decimal("1200.00"),
        )
        self.assertEqual((cee.salaire_mensuel_reference, cdd.taux_journalier_reference, apprentissage.taux_journalier_reference), (None, None, None))
        self.assertEqual(self.animateur.contrats.count(), 3)

    def test_date_fin_anterieure_refusee(self):
        with self.assertRaisesMessage(ValidationError, "antérieure"):
            Contrat.objects.create(
                animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
                date_debut=datetime.date(2026, 8, 2), date_fin=datetime.date(2026, 8, 1),
                taux_journalier_reference=Decimal("50"),
            )

    def test_remuneration_obligatoire_et_champ_incompatible_refuses(self):
        cas = (
            {"type_contrat": Contrat.TYPE_CEE},
            {"type_contrat": Contrat.TYPE_CDD},
            {"type_contrat": Contrat.TYPE_APPRENTISSAGE},
            {"type_contrat": Contrat.TYPE_CEE, "taux_journalier_reference": 50, "salaire_mensuel_reference": 1800},
            {"type_contrat": Contrat.TYPE_CDD, "salaire_mensuel_reference": 1800, "taux_journalier_reference": 50},
        )
        for index, champs in enumerate(cas):
            with self.subTest(index=index), self.assertRaises(ValidationError):
                Contrat.objects.create(animateur=self.animateur, date_debut=datetime.date(2030 + index, 1, 1), **champs)

    @mock.patch("animateurs.models.timezone.localdate", return_value=datetime.date(2026, 8, 18))
    def test_statuts_sont_calcules_depuis_les_dates(self, _localdate):
        passe = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31), taux_journalier_reference=50,
        )
        actuel = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CDD,
            date_debut=datetime.date(2026, 8, 1), date_fin=datetime.date(2026, 8, 31), salaire_mensuel_reference=1800,
        )
        futur = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_APPRENTISSAGE,
            date_debut=datetime.date(2026, 9, 1), salaire_mensuel_reference=1200,
        )
        self.assertEqual((passe.statut, actuel.statut, futur.statut), ("termine", "en_cours", "a_venir"))

    def test_contrat_pour_date_et_historique_successif(self):
        premier = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31), taux_journalier_reference=50,
        )
        second = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CDD,
            date_debut=datetime.date(2026, 8, 1), date_fin=datetime.date(2027, 8, 1), salaire_mensuel_reference=1800,
        )
        self.assertEqual(contrat_pour_date(self.animateur, datetime.date(2026, 7, 15)), premier)
        self.assertEqual(contrat_pour_date(self.animateur, datetime.date(2026, 8, 15)), second)
        self.assertEqual(self.animateur.contrats.count(), 2)
        with mock.patch("animateurs.services.contrats.timezone.localdate", return_value=datetime.date(2026, 8, 18)):
            self.assertEqual(contrat_actuel(self.animateur), second)

    def test_chevauchement_et_contrat_ouvert_refusent_un_concurrent(self):
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31), taux_journalier_reference=50,
        )
        with self.assertRaisesMessage(ValidationError, "chevauche"):
            Contrat.objects.create(
                animateur=self.animateur, type_contrat=Contrat.TYPE_CDD,
                date_debut=datetime.date(2026, 7, 20), date_fin=datetime.date(2026, 8, 31), salaire_mensuel_reference=1800,
            )
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CDD,
            date_debut=datetime.date(2026, 8, 1), salaire_mensuel_reference=1800,
        )
        with self.assertRaisesMessage(ValidationError, "sans date de fin"):
            Contrat.objects.create(
                animateur=self.animateur, type_contrat=Contrat.TYPE_APPRENTISSAGE,
                date_debut=datetime.date(2027, 1, 1), salaire_mensuel_reference=1200,
            )


class ContratApiTests(ConnexionTestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Bruno", nom="API", paie_jour=Decimal("47.00"))
        self.url = reverse("api_contrats", args=[self.animateur.id])

    def test_creation_modification_liste_et_suppression(self):
        creation = self.client.post(self.url, data=json.dumps({
            "type_contrat": "cee", "date_debut": "2026-07-01", "date_fin": "2026-07-31",
            "taux_journalier_reference": "52.50", "salaire_mensuel_reference": None,
        }), content_type="application/json")
        self.assertEqual(creation.status_code, 201)
        contrat_id = creation.json()["id"]
        modification = self.client.patch(reverse("api_contrat_detail", args=[self.animateur.id, contrat_id]), data=json.dumps({
            "taux_journalier_reference": "55.00",
        }), content_type="application/json")
        self.assertEqual(modification.status_code, 200)
        self.assertEqual(modification.json()["taux_journalier_reference"], "55.00")
        self.assertEqual(len(self.client.get(self.url).json()), 1)
        suppression = self.client.delete(reverse("api_contrat_detail", args=[self.animateur.id, contrat_id]))
        self.assertEqual(suppression.status_code, 200)
        self.assertFalse(Contrat.objects.filter(pk=contrat_id).exists())
        self.animateur.refresh_from_db()
        self.assertEqual(self.animateur.paie_jour, Decimal("47.00"))

    def test_api_refuse_dates_remunerations_et_chevauchements_invalides(self):
        cas = (
            {"type_contrat": "cee", "date_debut": "2026-08-02", "date_fin": "2026-08-01"},
            {"type_contrat": "cee", "date_debut": "2026-08-01"},
            {"type_contrat": "cdd", "date_debut": "2026-08-01"},
            {"type_contrat": "apprentissage", "date_debut": "2026-08-01"},
        )
        for payload in cas:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(self.url, data=json.dumps(payload), content_type="application/json").status_code, 400)

        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31), taux_journalier_reference=50,
        )
        conflit = self.client.post(self.url, data=json.dumps({
            "type_contrat": "cdd", "date_debut": "2026-07-20", "date_fin": "2026-08-31", "salaire_mensuel_reference": 1800,
        }), content_type="application/json")
        self.assertEqual(conflit.status_code, 400)
        self.assertIn("chevauche", conflit.json()["error"])

    def test_animateur_sans_contrat_reste_serialisable_et_interface_est_conditionnelle(self):
        detail = self.client.get(reverse("api_animateur_detail", args=[self.animateur.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["contrats"], [])
        script = Path(settings.BASE_DIR, "static/js/animateurs.js").read_text(encoding="utf-8")
        self.assertIn("Contrat non renseigné", script)
        self.assertIn("data-contract-daily", script)
        self.assertIn("data-contract-monthly", script)
        self.assertIn("confirm(`Supprimer le contrat", script)

    def test_animateur_simple_ne_peut_pas_gerer_ses_contrats(self):
        user = get_user_model().objects.create_user(username="animateur-contrat", password="secret")
        self.animateur.utilisateur = user
        self.animateur.save()
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, data="{}", content_type="application/json").status_code, 403)

    def test_direction_peut_acceder_aux_contrats(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
