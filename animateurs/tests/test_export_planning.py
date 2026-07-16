import datetime
import io
import zipfile

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Qualification


class ExportPlanningExcelTests(TestCase):
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
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

    def test_page_administration_disponible(self):
        response = self.client.get(reverse("administration"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Exporter le planning")

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
        self.assertIn("planning_2026-07-01_2026-07-31.xlsx", response["Content-Disposition"])

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("xl/workbook.xml", archive.namelist())
            shared_strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
            self.assertIn("Julie Martin", shared_strings)
            self.assertIn("La Pacaudière", shared_strings)
            self.assertIn("BAFA", shared_strings)

    def test_export_refuse_periode_invalide(self):
        response = self.client.get(
            reverse("export_planning_excel"),
            {"debut": "2026-07-31", "fin": "2026-07-01"},
        )
        self.assertEqual(response.status_code, 400)
