import datetime
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Disponibilite


class PlanningApiTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Julie", nom="API")
        self.centre = Centre.objects.create(nom="Centre", code="CTR", couleur="#123456")
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 11),
        )

    def test_creation_affectation_et_refus_doublon(self):
        debut = "2026-07-06"
        payload = {
            "animateur_id": self.animateur.id,
            "centre_id": self.centre.id,
            "debut": debut,
            "fin": "2026-07-07",
        }
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_refuse_creation_sans_disponibilite(self):
        self.animateur.disponibilites.all().delete()
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps({
                "animateur_id": self.animateur.id,
                "centre_id": self.centre.id,
                "debut": "2026-07-06",
                "fin": "2026-07-07",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Affectation.objects.exists())

    def test_creation_manuelle_autorisee_le_samedi(self):
        payload = {
            "animateur_id": self.animateur.id,
            "centre_id": self.centre.id,
            "debut": "2026-07-11",
            "fin": "2026-07-12",
        }

        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Affectation.objects.filter(
                animateur=self.animateur,
                debut__date=datetime.date(2026, 7, 11),
            ).exists()
        )

    def test_vidage_semaine_preserve_le_samedi(self):
        lundi = timezone.make_aware(datetime.datetime(2026, 7, 6))
        samedi = timezone.make_aware(datetime.datetime(2026, 7, 11))
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            debut=lundi,
            fin=lundi + datetime.timedelta(days=1),
        )
        autre = Animateur.objects.create(prenom="Sam", nom="EDI")
        affectation_samedi = Affectation.objects.create(
            animateur=autre,
            centre=self.centre,
            debut=samedi,
            fin=samedi + datetime.timedelta(days=1),
        )

        response = self.client.delete(
            reverse("api_planning_plage") + "?debut=2026-07-06&fin=2026-07-11"
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Affectation.objects.filter(debut__date=datetime.date(2026, 7, 6)).exists())
        self.assertTrue(Affectation.objects.filter(pk=affectation_samedi.pk).exists())

