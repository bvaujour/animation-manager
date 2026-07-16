import datetime
import json

from django.test import TestCase
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    DateExclueEvenement,
    Disponibilite,
    Evenement,
    PreferenceCentre,
)
from animateurs.services.planning_solver import generer_planning_auto
from animateurs.services.recapitulatif import generer_recapitulatif


class OuverturesEvenementTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="La Pacaudière", code="PAC")
        self.evenement = Evenement.objects.create(
            centre=self.centre,
            nom="Maternelles",
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.animateur = Animateur.objects.create(prenom="Alice", nom="Martin")
        PreferenceCentre.objects.create(
            animateur=self.animateur, centre=self.centre, est_prefere=True
        )
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )

    def _aware(self, date):
        return timezone.make_aware(datetime.datetime.combine(date, datetime.time.min))

    def test_api_evenement_expose_jours_et_dates_exclues(self):
        DateExclueEvenement.objects.create(
            evenement=self.evenement, date=datetime.date(2026, 7, 8)
        )
        response = self.client.get(f"/api/centres/{self.centre.id}/evenements/")
        self.assertEqual(response.status_code, 200)
        data = response.json()[0]
        self.assertEqual(data["jours_ouverts"], [0, 1, 2, 3, 4])
        self.assertEqual(data["dates_exclues"], ["2026-07-08"])

    def test_affectation_refuse_une_date_exclue(self):
        DateExclueEvenement.objects.create(
            evenement=self.evenement, date=datetime.date(2026, 7, 8)
        )
        response = self.client.post(
            "/api/affectations/",
            data=json.dumps({
                "animateur_id": self.animateur.id,
                "evenement_id": self.evenement.id,
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
            evenement=self.evenement, date=datetime.date(2026, 7, 8)
        )
        data, status = generer_planning_auto({"debut": "2026-07-06"})
        self.assertEqual(status, 200)
        self.assertEqual(data["total_places"], 4)
        self.assertEqual(data["created"], 4)
        self.assertFalse(
            Affectation.objects.filter(debut__date=datetime.date(2026, 7, 8)).exists()
        )

    def test_fermeture_demande_confirmation_puis_supprime_affectation(self):
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=self.evenement,
            debut=self._aware(datetime.date(2026, 7, 8)),
            fin=self._aware(datetime.date(2026, 7, 9)),
        )
        payload = {
            "jours_ouverts": [0, 1, 2, 3, 4],
            "dates_exclues": ["2026-07-08"],
        }
        response = self.client.patch(
            f"/api/evenements/{self.evenement.id}/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "affectations_dates_fermees")
        self.assertEqual(Affectation.objects.count(), 1)

        payload["supprimer_affectations_dates_fermees"] = True
        response = self.client.patch(
            f"/api/evenements/{self.evenement.id}/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Affectation.objects.count(), 0)
        self.assertTrue(
            DateExclueEvenement.objects.filter(
                evenement=self.evenement, date=datetime.date(2026, 7, 8)
            ).exists()
        )

    def test_recapitulatif_ne_compte_pas_le_jour_ferme(self):
        DateExclueEvenement.objects.create(
            evenement=self.evenement, date=datetime.date(2026, 7, 8)
        )
        recap = generer_recapitulatif(
            self._aware(datetime.date(2026, 7, 6)),
            self._aware(datetime.date(2026, 7, 11)),
        )
        ligne = next(item for item in recap["evenements"] if item["id"] == self.evenement.id)
        self.assertEqual(ligne["jours_prevus"], 4)
        self.assertEqual(ligne["postes_requis"], 4)


class InterfaceOuverturesEvenementTests(TestCase):
    def test_gestion_contient_calendrier_et_raccourcis(self):
        contenu = open("static/js/gestion.js", encoding="utf-8").read()
        self.assertIn("Jours habituels d’ouverture", contenu)
        self.assertIn("Jours fériés", contenu)
        self.assertIn("event-exclusion-calendar", contenu)
