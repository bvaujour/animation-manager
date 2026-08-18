import datetime
import importlib
import json
from decimal import Decimal
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Animateur,
    BaremeCEE,
    Formation,
    HistoriqueStatutAnimateur,
    ParticipationFormation,
    Qualification,
)
from animateurs.services.parametres import get_parametres_structure, taux_cee_pour_date
from animateurs.services.statuts import situation_statut_pour_date, statut_actuel, statut_pour_date
from animateurs.tests.base import ConnexionTestCase
from animateurs.views_formations import _attribuer_qualifications_presentes


class HistoriqueStatutServiceTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Bruno", nom="Historique")
        self.non_diplome = Qualification.objects.create(nom="Non diplômé", est_statut=True)
        self.stagiaire = Qualification.objects.create(nom="Stagiaire BAFA", est_statut=True)
        self.diplome = Qualification.objects.create(nom="Diplômé BAFA", est_statut=True)

    def test_plusieurs_changements_et_dates_inclusives(self):
        for statut, date_effet in (
            (self.non_diplome, datetime.date(2026, 7, 1)),
            (self.stagiaire, datetime.date(2026, 7, 10)),
            (self.diplome, datetime.date(2026, 7, 20)),
        ):
            HistoriqueStatutAnimateur.objects.create(
                animateur=self.animateur, statut=statut, date_effet=date_effet
            )
        attentes = {
            datetime.date(2026, 7, 5): self.non_diplome,
            datetime.date(2026, 7, 10): self.stagiaire,
            datetime.date(2026, 7, 19): self.stagiaire,
            datetime.date(2026, 7, 20): self.diplome,
            datetime.date(2026, 7, 31): self.diplome,
        }
        for date, attendu in attentes.items():
            with self.subTest(date=date):
                self.assertEqual(statut_pour_date(self.animateur, date), attendu)
        self.assertEqual(self.animateur.historique_statuts.count(), 3)

    def test_deux_statuts_a_la_meme_date_sont_refuses(self):
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=self.stagiaire, date_effet=datetime.date(2026, 7, 10)
        )
        with self.assertRaises(ValidationError):
            HistoriqueStatutAnimateur.objects.create(
                animateur=self.animateur, statut=self.diplome, date_effet=datetime.date(2026, 7, 10)
            )

    def test_fallback_actuel_est_explicitement_non_fiable(self):
        self.animateur.qualifications.add(self.stagiaire)
        situation = situation_statut_pour_date(self.animateur, datetime.date(2020, 1, 1))
        self.assertEqual(situation.statut, self.stagiaire)
        self.assertEqual(situation.source, "fallback_actuel")
        self.assertFalse(situation.fiable)

    def test_changement_futur_ne_modifie_pas_prematurement_le_statut_actuel(self):
        aujourd_hui = timezone.localdate()
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=self.stagiaire, date_effet=aujourd_hui - datetime.timedelta(days=10)
        )
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=self.diplome, date_effet=aujourd_hui + datetime.timedelta(days=8)
        )
        self.animateur.refresh_from_db()
        self.assertEqual(statut_actuel(self.animateur), self.stagiaire)
        self.assertTrue(self.animateur.qualifications.filter(pk=self.stagiaire.pk).exists())
        self.assertFalse(self.animateur.qualifications.filter(pk=self.diplome.pk).exists())
        self.assertEqual(statut_pour_date(self.animateur, aujourd_hui + datetime.timedelta(days=8)), self.diplome)

    def test_synchronisation_conserve_les_qualifications_ordinaires(self):
        psc1 = Qualification.objects.create(nom="PSC1")
        self.animateur.qualifications.add(psc1, self.non_diplome)
        entree = HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=self.stagiaire, date_effet=timezone.localdate()
        )
        self.assertTrue(self.animateur.qualifications.filter(pk=psc1.pk).exists())
        self.assertTrue(self.animateur.qualifications.filter(pk=self.stagiaire.pk).exists())
        self.assertFalse(self.animateur.qualifications.filter(pk=self.non_diplome.pk).exists())
        entree.statut = self.diplome
        entree.save()
        self.assertTrue(self.animateur.qualifications.filter(pk=psc1.pk).exists())
        entree.delete()
        self.assertTrue(self.animateur.qualifications.filter(pk=psc1.pk).exists())

    def test_compatibilite_avec_le_bareme_cee_historique(self):
        date = datetime.date(2026, 7, 15)
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=self.stagiaire, date_effet=datetime.date(2026, 7, 10)
        )
        BaremeCEE.objects.create(
            structure=get_parametres_structure(), statut=self.stagiaire,
            date_effet=datetime.date(2026, 1, 1), montant_journalier=Decimal("48.50"),
        )
        statut = statut_pour_date(self.animateur, date)
        self.assertEqual(taux_cee_pour_date(statut, date), Decimal("48.50"))


class HistoriqueStatutApiTests(ConnexionTestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Julie", nom="API statut")
        self.stagiaire = Qualification.objects.create(nom="Stagiaire", est_statut=True)
        self.diplome = Qualification.objects.create(nom="Diplômé", est_statut=True)
        self.url = reverse("api_historique_statuts", args=[self.animateur.id])

    def test_creation_modification_lecture_et_suppression(self):
        creation = self.client.post(self.url, data=json.dumps({
            "statut_id": self.stagiaire.id, "date_effet": "2026-07-01", "commentaire": "Début",
        }), content_type="application/json")
        self.assertEqual(creation.status_code, 201)
        entree_id = creation.json()["id"]
        detail_url = reverse("api_historique_statut_detail", args=[self.animateur.id, entree_id])
        modification = self.client.patch(detail_url, data=json.dumps({
            "statut_id": self.diplome.id, "date_effet": "2026-07-02", "commentaire": "Correction",
        }), content_type="application/json")
        self.assertEqual(modification.status_code, 200)
        self.assertEqual(modification.json()["statut_id"], self.diplome.id)
        self.assertEqual(len(self.client.get(self.url).json()), 1)
        self.assertEqual(self.client.delete(detail_url).status_code, 200)
        self.assertFalse(HistoriqueStatutAnimateur.objects.filter(pk=entree_id).exists())

    def test_statut_non_statutaire_et_date_dupliquee_refuses(self):
        psc1 = Qualification.objects.create(nom="PSC1")
        invalide = self.client.post(self.url, data=json.dumps({
            "statut_id": psc1.id, "date_effet": "2026-07-01",
        }), content_type="application/json")
        self.assertEqual(invalide.status_code, 400)
        self.client.post(self.url, data=json.dumps({
            "statut_id": self.stagiaire.id, "date_effet": "2026-07-01",
        }), content_type="application/json")
        doublon = self.client.post(self.url, data=json.dumps({
            "statut_id": self.diplome.id, "date_effet": "2026-07-01",
        }), content_type="application/json")
        self.assertEqual(doublon.status_code, 400)

    def test_animateur_simple_ne_peut_pas_modifier_l_historique(self):
        user = get_user_model().objects.create_user(username="statut-simple", password="secret")
        self.animateur.utilisateur = user
        self.animateur.save()
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, data="{}", content_type="application/json").status_code, 403)


class HistoriqueStatutFormationTests(ConnexionTestCase):
    def setUp(self):
        self.present = Animateur.objects.create(prenom="Barbara", nom="Présente")
        self.absent = Animateur.objects.create(prenom="Jeanne", nom="Absente")
        self.statut = Qualification.objects.create(nom="Diplômé formation", est_statut=True)
        self.date_fin = timezone.localdate() - datetime.timedelta(days=1)
        self.formation = Formation.objects.create(
            intitule="BAFA", date_debut=self.date_fin - datetime.timedelta(days=2),
            date_fin=self.date_fin, qualification=self.statut,
        )
        ParticipationFormation.objects.create(formation=self.formation, animateur=self.present)
        ParticipationFormation.objects.create(formation=self.formation, animateur=self.absent)

    def _cloturer(self):
        return self.client.post(reverse("api_formation_cloture", args=[self.formation.id]), data=json.dumps({
            "presences": [
                {"animateur_id": self.present.id, "presence": "present"},
                {"animateur_id": self.absent.id, "presence": "absent"},
            ]
        }), content_type="application/json")

    def test_present_recoit_historique_a_la_date_de_fin_absent_non(self):
        self.assertEqual(self._cloturer().status_code, 200)
        entree = HistoriqueStatutAnimateur.objects.get(animateur=self.present)
        self.assertEqual(entree.statut, self.statut)
        self.assertEqual(entree.date_effet, self.date_fin)
        self.assertEqual(entree.origine, "formation")
        self.assertFalse(HistoriqueStatutAnimateur.objects.filter(animateur=self.absent).exists())

    def test_qualification_non_statutaire_ne_cree_pas_historique(self):
        self.formation.qualification = Qualification.objects.create(nom="PSC1 formation")
        self.formation.save()
        self.assertEqual(self._cloturer().status_code, 200)
        self.assertFalse(HistoriqueStatutAnimateur.objects.exists())
        self.assertTrue(self.present.qualifications.filter(nom="PSC1 formation").exists())

    def test_retraitement_idempotent_et_suppression_formation_conserve_historique(self):
        self.assertEqual(self._cloturer().status_code, 200)
        _attribuer_qualifications_presentes(self.formation, None)
        self.assertEqual(HistoriqueStatutAnimateur.objects.filter(animateur=self.present).count(), 1)
        self.formation.delete()
        self.assertEqual(HistoriqueStatutAnimateur.objects.filter(animateur=self.present).count(), 1)


class MigrationHistoriqueStatutsTests(TestCase):
    def test_reprise_est_marquee_comme_technique_et_incertaine(self):
        animateur = Animateur.objects.create(prenom="Ancien", nom="Statut")
        statut = Qualification.objects.create(nom="Statut repris", est_statut=True)
        animateur.qualifications.add(statut)
        migration = importlib.import_module("animateurs.migrations.0096_historiquestatutanimateur")
        migration.reprendre_statuts_actuels(apps, None)
        entree = HistoriqueStatutAnimateur.objects.get(animateur=animateur)
        self.assertEqual(entree.origine, "reprise")
        self.assertTrue(entree.date_effet_incertaine)
        self.assertIn("date réelle", entree.commentaire)
