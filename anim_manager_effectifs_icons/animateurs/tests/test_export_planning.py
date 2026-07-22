import datetime
import io
import zipfile

from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, PeriodeScolaire, Qualification
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_groupe


class ExportPlanningExcelTests(ConnexionTestCase):
    def setUp(self):
        self.bafa = Qualification.objects.create(nom="BAFA")
        self.animateur = Animateur.objects.create(
            prenom="Julie",
            nom="Martin",
            telephone="0600000000",
            email="julie@example.fr",
        )
        self.animateur.qualifications.add(self.bafa)
        self.centre = Centre.objects.create(
            nom="La Pacaudière",
            code="PAC",
            couleur="#1F6F54",
        )
        self.groupe, _ = creer_groupe(self.centre, nom="Maternelles")
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

    def test_page_administration_disponible(self):
        response = self.client.get(reverse("administration"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planning calendrier par groupe")

    def test_export_xlsx_valide(self):
        response = self.client.get(
            reverse("export_planning_excel"),
            {"debut": "2026-07-01", "fin": "2026-07-31"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("planning_20260701_20260731.xlsx", response["Content-Disposition"])

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("xl/workbook.xml", archive.namelist())
            shared_strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
            self.assertIn("Julie Martin", shared_strings)
            self.assertIn("La Pacaudière", shared_strings)

    def test_export_refuse_periode_invalide(self):
        response = self.client.get(
            reverse("export_planning_excel"),
            {"debut": "2026-07-31", "fin": "2026-07-01"},
        )
        self.assertEqual(response.status_code, 400)

    def test_verification_export_signale_les_horaires_manquants(self):
        periode = self.groupe.periodes_scolaires.first()

        response = self.client.get(
            reverse("api_verification_export_planning"),
            {"periode_ids": periode.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["nombre"], 0)
        self.assertEqual(response.json()["manquants"][0]["groupe"], "Maternelles")

    def test_export_accepte_plusieurs_semaines_enregistrees(self):
        semaines = [
            PeriodeScolaire.objects.create(
                nom=f"Été 2026 — Semaine {numero}",
                annee_scolaire="2025-2026",
                zone="A",
                debut=debut,
                fin=debut + datetime.timedelta(days=4),
                ordre=numero,
            )
            for numero, debut in enumerate((datetime.date(2026, 7, 6), datetime.date(2026, 7, 20)), start=1)
        ]

        page = self.client.get(reverse("administration"))
        for semaine in semaines:
            self.assertContains(page, f'name="periode_ids" value="{semaine.id}"')

        response = self.client.get(
            reverse("export_planning_excel"),
            [("periode_ids", str(semaine.id)) for semaine in semaines],
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("planning_20260706_20260724.xlsx", response["Content-Disposition"])
