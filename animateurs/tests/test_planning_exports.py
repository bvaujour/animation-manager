from datetime import date, datetime, timezone as dt_timezone
from io import BytesIO
import zipfile

from django.test import TestCase
from django.urls import reverse

from animateurs.models import Affectation, Animateur, Centre, Evenement
from animateurs.services.planning_exports import _planning_matrix


class PlanningExportTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="Pacaudière",
            code="PAC",
            couleur="#E03C00",
        )
        self.maternelles = self.centre.evenements.get()
        self.maternelles.nom = "Maternelles"
        self.maternelles.effectif_cible = 2
        self.maternelles.save(update_fields=["nom", "effectif_cible"])
        self.elementaires = Evenement.objects.create(
            centre=self.centre,
            nom="Élémentaires",
            effectif_cible=2,
            ordre=1,
            active=True,
        )
        self.matin = Evenement.objects.create(
            centre=self.centre,
            nom="Accueil matin",
            effectif_cible=1,
            ordre=2,
            active=True,
            heure_debut="07:30",
            heure_fin="09:00",
        )

        self.julie = Animateur.objects.create(
            prenom="Julie",
            nom="Durand",
            couleur="#2563EB",
        )
        self.gael = Animateur.objects.create(
            prenom="Gaël",
            nom="Martin",
            couleur="#7C3AED",
        )
        Affectation.objects.create(
            animateur=self.julie,
            centre=self.centre,
            evenement=self.maternelles,
            debut=datetime(2026, 7, 6, tzinfo=dt_timezone.utc),
            fin=datetime(2026, 7, 7, tzinfo=dt_timezone.utc),
        )
        Affectation.objects.create(
            animateur=self.gael,
            centre=self.centre,
            evenement=self.elementaires,
            debut=datetime(2026, 7, 6, tzinfo=dt_timezone.utc),
            fin=datetime(2026, 7, 7, tzinfo=dt_timezone.utc),
        )

    def test_page_administration(self):
        response = self.client.get(reverse("administration"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planning calendrier par événement")

    def test_matrice_separe_les_evenements_du_meme_centre(self):
        dates, evenements, noms_par_case, _ = _planning_matrix(
            date(2026, 7, 6),
            date(2026, 7, 6),
        )
        self.assertEqual(dates, [date(2026, 7, 6)])
        self.assertEqual(
            [evenement.nom for evenement in evenements],
            ["Maternelles", "Élémentaires", "Accueil matin"],
        )
        self.assertEqual(
            noms_par_case[(self.maternelles.id, date(2026, 7, 6))],
            ["Julie Durand"],
        )
        self.assertEqual(
            noms_par_case[(self.elementaires.id, date(2026, 7, 6))],
            ["Gaël Martin"],
        )
        self.assertNotIn(
            "Gaël Martin",
            noms_par_case[(self.maternelles.id, date(2026, 7, 6))],
        )

    def test_export_excel_calendrier_par_evenement(self):
        response = self.client.get(reverse("export_planning_excel"), {
            "debut": "2026-07-06",
            "fin": "2026-07-11",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
            sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            self.assertIn("Pacaudière", strings)
            self.assertIn("Maternelles", strings)
            self.assertIn("Élémentaires", strings)
            self.assertIn("Accueil matin", strings)
            self.assertIn("07:30 - 09:00", strings)
            self.assertIn("Julie Durand", strings)
            self.assertIn("Gaël Martin", strings)
            self.assertIn("Lundi", strings)
            # Le centre est fusionné verticalement sur les trois événements.
            self.assertIn('ref="A3:A5"', sheet_xml)

    def test_export_pdf_calendrier_par_evenement(self):
        response = self.client.get(reverse("export_planning_pdf"), {
            "debut": "2026-07-06",
            "fin": "2026-07-11",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 1500)

    def test_evenement_inactive_conservee_si_affectee_sur_la_periode(self):
        self.elementaires.active = False
        self.elementaires.save(update_fields=["active"])
        _, evenements, _, _ = _planning_matrix(
            date(2026, 7, 6),
            date(2026, 7, 6),
        )
        self.assertIn(self.elementaires.id, [evenement.id for evenement in evenements])

    def test_evenement_inactive_vide_non_exportee(self):
        evenement_vide = Evenement.objects.create(
            centre=self.centre,
            nom="Ancienne événement",
            effectif_cible=1,
            ordre=3,
            active=False,
        )
        _, evenements, _, _ = _planning_matrix(
            date(2026, 7, 6),
            date(2026, 7, 6),
        )
        self.assertNotIn(evenement_vide.id, [evenement.id for evenement in evenements])

    def test_dimanche_masque(self):
        response = self.client.get(reverse("export_planning_excel"), {
            "debut": "2026-07-06",
            "fin": "2026-07-12",
        })
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
            self.assertNotIn("Dimanche", strings)
