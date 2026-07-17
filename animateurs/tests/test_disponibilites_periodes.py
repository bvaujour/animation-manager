import datetime
import json

from django.test import TestCase

from animateurs.models import Animateur, Disponibilite, PeriodeScolaire


class DisponibilitesParPeriodesApiTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Lina", nom="Test")
        PeriodeScolaire.objects.create(
            nom="Été — Semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
            ordre=1,
        )

    def test_get_expose_les_jours_de_la_periode(self):
        response = self.client.get(f"/api/animateurs/{self.animateur.id}/disponibilites/")
        self.assertEqual(response.status_code, 200)
        periode = response.json()["periodes"][0]
        self.assertEqual(len(periode["jours"]), 5)
        self.assertFalse(periode["selectionnee"])

    def test_put_enregistre_uniquement_les_jours_coches(self):
        response = self.client.put(
            f"/api/animateurs/{self.animateur.id}/disponibilites/",
            data=json.dumps({
                "jours_disponibles": [
                    "2026-07-06", "2026-07-07", "2026-07-09", "2026-07-10"
                ]
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        plages = list(
            Disponibilite.objects.filter(animateur=self.animateur)
            .values_list("debut", "fin")
        )
        self.assertEqual(plages, [
            (datetime.date(2026, 7, 6), datetime.date(2026, 7, 7)),
            (datetime.date(2026, 7, 9), datetime.date(2026, 7, 10)),
        ])
        jours = response.json()["periodes"][0]["jours"]
        indisponibles = [jour["date"] for jour in jours if not jour["disponible"]]
        self.assertEqual(indisponibles, ["2026-07-08"])

    def test_put_refuse_un_jour_hors_bibliotheque(self):
        response = self.client.put(
            f"/api/animateurs/{self.animateur.id}/disponibilites/",
            data=json.dumps({"jours_disponibles": ["2026-08-01"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
