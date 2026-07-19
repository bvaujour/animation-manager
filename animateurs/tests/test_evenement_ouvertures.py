import datetime
import json
from pathlib import Path

from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    DateExclueEvenement,
    Disponibilite,
    Evenement,
    PeriodeScolaire,
    PreferenceCentre,
)
from animateurs.services.planning_solver import generer_planning_auto
from animateurs.tests.base import ConnexionTestCase


class OuverturesGroupeTests(ConnexionTestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="La Pacaudière", code="PAC")
        self.periode = PeriodeScolaire.objects.create(
            nom="Été — Semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )
        self.groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Maternelles",
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.groupe.periodes_scolaires.add(self.periode)
        self.animateur = Animateur.objects.create(prenom="Alice", nom="Martin")
        PreferenceCentre.objects.create(
            animateur=self.animateur, centre=self.centre, est_prefere=True
        )
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=self.periode.debut,
            fin=self.periode.fin,
        )

    def _aware(self, date):
        return timezone.make_aware(datetime.datetime.combine(date, datetime.time.min))

    def test_api_groupe_expose_jours_et_dates_exclues(self):
        DateExclueEvenement.objects.create(
            evenement=self.groupe, date=datetime.date(2026, 7, 8)
        )
        response = self.client.get(f"/api/centres/{self.centre.id}/groupes/")
        self.assertEqual(response.status_code, 200)
        data = response.json()[0]
        self.assertEqual(data["jours_ouverts"], [0, 1, 2, 3, 4])
        self.assertEqual(data["dates_exclues"], ["2026-07-08"])

    def test_affectation_refuse_une_date_exclue(self):
        DateExclueEvenement.objects.create(
            evenement=self.groupe, date=datetime.date(2026, 7, 8)
        )
        response = self.client.post(
            "/api/affectations/",
            data=json.dumps({
                "animateur_id": self.animateur.id,
                "evenement_id": self.groupe.id,
                "centre_id": self.centre.id,
                "debut": "2026-07-08",
                "fin": "2026-07-09",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("fermé", response.json()["error"])

    def test_remplissage_auto_ignore_une_date_exclue(self):
        DateExclueEvenement.objects.create(
            evenement=self.groupe, date=datetime.date(2026, 7, 8)
        )
        data, status = generer_planning_auto({"debut": "2026-07-06"})
        self.assertEqual(status, 200)
        self.assertEqual(data["total_places"], 4)
        self.assertEqual(data["created"], 4)
        self.assertFalse(
            Affectation.objects.filter(debut__date=datetime.date(2026, 7, 8)).exists()
        )

class InterfaceOuverturesGroupeTests(ConnexionTestCase):
    def test_gestion_contient_jours_et_periodes_facultatives(self):
        contenu = Path("static/js/gestion.js").read_text(encoding="utf-8")
        self.assertIn("Jours ouverts", contenu)
        self.assertIn("sans période", contenu)
        self.assertIn("Fermé les jours fériés", contenu)
        self.assertNotIn("Groupe d’accueil actif", contenu)
