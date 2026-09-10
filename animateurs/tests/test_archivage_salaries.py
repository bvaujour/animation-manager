import datetime
import json

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from animateurs.models import Animateur, AnneeScolaire, Contrat, Disponibilite
from animateurs.services.contrats import contrat_est_verrouille
from animateurs.tests.base import ConnexionTestCase


class ArchivageSalariesTests(ConnexionTestCase):
    def setUp(self):
        self.salarie = Animateur.objects.create(prenom="Alice", nom="Historique")
        self.url = f"/api/animateurs/{self.salarie.pk}/"
        self.annee = AnneeScolaire.objects.get(libelle="2025-2026")
        self.contrat = Contrat.objects.create(animateur=self.salarie, type_contrat="cee", date_debut=datetime.date(2025, 9, 15), date_fin=datetime.date(2026, 8, 31), taux_journalier_reference=50)
        self.contrat_url = self.url + f"contrats/{self.contrat.pk}/"

    def fermer(self):
        self.annee.statut = "CLOTUREE"
        self.annee.save()

    def test_inactivation_reactivation_et_historique(self):
        dispo = Disponibilite.objects.create(animateur=self.salarie, debut=datetime.date(2026, 7, 1), fin=datetime.date(2026, 7, 2))
        avant = Contrat.objects.values().get(pk=self.contrat.pk)
        self.assertTrue(self.salarie.actif)
        for actif in (False, True):
            response = self.client.patch(self.url, json.dumps({"actif": actif}), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["actif"], actif)
            self.assertEqual(Contrat.objects.values().get(pk=self.contrat.pk), avant)
            self.assertTrue(Disponibilite.objects.filter(pk=dispo.pk).exists())

    def test_inactif_consultable_et_filtre_actifs(self):
        self.salarie.actif = False
        self.salarie.save()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertIn(self.salarie.pk, [a["id"] for a in self.client.get("/api/animateurs/").json()])
        self.assertNotIn(self.salarie.pk, [a["id"] for a in self.client.get("/api/animateurs/?actif=1").json()])
        data = self.client.get("/api/animateurs/?format=planning").json()
        self.assertFalse(next(a for a in data if a["id"] == self.salarie.pk)["actif"])
        self.assertEqual(self.client.post(self.url + "contrats/", "{}", content_type="application/json").status_code, 400)

    def test_contrat_cloture_lecture_seule_et_cascade(self):
        self.fermer()
        self.assertTrue(contrat_est_verrouille(self.contrat))
        self.assertTrue(self.client.get(self.url + "contrats/").json()[0]["verrouille"])
        self.assertEqual(self.client.patch(self.contrat_url, json.dumps({"date_fin": "2027-08-31"}), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.delete(self.contrat_url).status_code, 403)
        self.assertEqual(self.client.delete(self.url).status_code, 403)
        self.assertTrue(Contrat.objects.filter(pk=self.contrat.pk).exists())
        self.contrat.refresh_from_db()
        self.assertEqual(self.contrat.date_fin, datetime.date(2026, 8, 31))

    def test_contrat_actif_modifiable(self):
        self.assertFalse(contrat_est_verrouille(self.contrat))
        response = self.client.patch(self.contrat_url, json.dumps({"taux_journalier_reference": "60"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_chevauchement_et_dates_incompletes_non_verrouilles(self):
        self.fermer()
        AnneeScolaire.objects.create(libelle="2026-2027", date_debut=datetime.date(2026, 9, 1), date_fin=datetime.date(2027, 8, 31), statut="ACTIVE")
        self.contrat.date_debut = datetime.date(2026, 7, 1)
        self.contrat.date_fin = datetime.date(2027, 6, 30)
        self.contrat.save()
        self.assertFalse(contrat_est_verrouille(self.contrat))
        self.assertEqual(self.client.patch(self.contrat_url, json.dumps({"taux_journalier_reference": "60"}), content_type="application/json").status_code, 200)
        self.contrat.date_fin = None
        self.assertFalse(contrat_est_verrouille(self.contrat))
        self.contrat.date_fin = datetime.date(2026, 8, 31)
        self.contrat.date_debut = None
        self.assertFalse(contrat_est_verrouille(self.contrat))

    def test_cloture_ne_desactive_pas_et_reouverture_deverrouille(self):
        self.fermer()
        self.salarie.refresh_from_db()
        self.assertTrue(self.salarie.actif)
        self.annee.statut = "ACTIVE"
        self.annee.save()
        self.assertFalse(contrat_est_verrouille(self.contrat))

    def test_permission_direction_requise(self):
        user = get_user_model().objects.create_user(username="sans-direction")
        self.client.force_login(user)
        self.assertEqual(self.client.patch(self.url, '{"actif": false}', content_type="application/json").status_code, 403)
        self.salarie.refresh_from_db()
        self.assertTrue(self.salarie.actif)


class MigrationActifTests(TransactionTestCase):
    def test_fiches_existantes_conservees_actives(self):
        avant = [("animateurs", "0114_initialiser_annee_scolaire")]
        apres = [("animateurs", "0115_animateur_actif")]
        executor = MigrationExecutor(connection)
        executor.migrate(avant)
        try:
            anciens = executor.loader.project_state(avant).apps
            salarie = anciens.get_model("animateurs", "Animateur").objects.create(prenom="Avant", nom="Migration", cle_unique="avant migration")
            identifiant = salarie.pk
        finally:
            MigrationExecutor(connection).migrate(apres)
        salarie = Animateur.objects.get(pk=identifiant)
        self.assertTrue(salarie.actif)
        self.assertEqual((salarie.prenom, salarie.nom), ("Avant", "Migration"))
