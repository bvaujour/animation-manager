import zipfile
from datetime import date, datetime
from datetime import timezone as dt_timezone
from io import BytesIO

from django.urls import reverse

from animateurs.models import Affectation, Animateur, Centre, EffectifEnfantsJour, HoraireAffectationJour
from animateurs.services.planning_exports import (
    _dates_par_semaine,
    _planning_matrix,
    libelle_affectation,
)
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_groupe


class PlanningExportTests(ConnexionTestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="Pacaudière",
            code="PAC",
            couleur="#E03C00",
        )
        self.maternelles, _ = creer_groupe(self.centre, nom="Maternelles", effectif_cible=2, ordre=0)
        self.elementaires, _ = creer_groupe(self.centre, nom="Élémentaires", effectif_cible=2, ordre=1)
        self.groupe_sans_periode, _ = creer_groupe(
            self.centre,
            nom="Groupe à préparer",
            effectif_cible=1,
            ordre=2,
            avec_periode=False,
        )

        self.julie = Animateur.objects.create(
            prenom="Julie",
            nom="Durand",
        )
        self.gael = Animateur.objects.create(
            prenom="Gaël",
            nom="Martin",
        )
        self.affectation_julie = Affectation.objects.create(
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
        EffectifEnfantsJour.objects.create(
            evenement=self.maternelles,
            date=date(2026, 7, 6),
            nombre=18,
        )
        HoraireAffectationJour.objects.create(
            affectation=self.affectation_julie,
            date=date(2026, 7, 6),
            heure_arrivee=datetime.strptime("08:00", "%H:%M").time(),
            heure_depart=datetime.strptime("17:30", "%H:%M").time(),
        )

    def test_page_administration(self):
        response = self.client.get(reverse("administration"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planning calendrier par groupe")

    def test_matrice_separe_les_groupes_du_meme_centre(self):
        dates, groupes, noms_par_case, _ = _planning_matrix(
            date(2026, 7, 6),
            date(2026, 7, 6),
        )
        self.assertEqual(dates, [date(2026, 7, 6)])
        self.assertEqual(
            [groupe.nom for groupe in groupes],
            ["Maternelles", "Élémentaires"],
        )
        self.assertEqual(
            noms_par_case[(self.maternelles.id, date(2026, 7, 6))],
            ["Julie Durand · 08:00–17:30"],
        )
        self.assertEqual(
            noms_par_case[(self.elementaires.id, date(2026, 7, 6))],
            ["Gaël Martin"],
        )

    def test_libelle_affectation_contient_uniquement_le_nom(self):
        self.assertEqual(
            libelle_affectation(self.affectation_julie),
            "Julie Durand",
        )

    def test_pdf_regroupe_exactement_les_jours_ouverts_de_chaque_semaine(self):
        dates = [
            date(2026, 7, 6),
            date(2026, 7, 8),
            date(2026, 7, 10),
            date(2026, 7, 20),
            date(2026, 7, 21),
        ]

        self.assertEqual(
            _dates_par_semaine(dates),
            [dates[:3], dates[3:]],
        )

    def test_groupe_sans_periode_non_exporte_sil_est_vide(self):
        _, groupes, _, _ = _planning_matrix(
            date(2026, 7, 6),
            date(2026, 7, 6),
        )
        self.assertNotIn(self.groupe_sans_periode.id, [groupe.id for groupe in groupes])

    def test_groupe_sans_periode_conserve_sil_a_une_affectation_historique(self):
        Affectation.objects.create(
            animateur=self.julie,
            centre=self.centre,
            evenement=self.groupe_sans_periode,
            debut=datetime(2026, 7, 7, tzinfo=dt_timezone.utc),
            fin=datetime(2026, 7, 8, tzinfo=dt_timezone.utc),
        )
        _, groupes, _, _ = _planning_matrix(
            date(2026, 7, 7),
            date(2026, 7, 7),
        )
        self.assertIn(self.groupe_sans_periode.id, [groupe.id for groupe in groupes])

    def test_export_excel_calendrier_par_groupe(self):
        response = self.client.get(
            reverse("export_planning_excel"),
            {
                "debut": "2026-07-06",
                "fin": "2026-07-11",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
            self.assertIn("Pacaudière", strings)
            self.assertIn("Maternelles", strings)
            self.assertIn("Élémentaires", strings)
            self.assertIn("Julie Durand", strings)
            self.assertIn("08:00–17:30", strings)
            self.assertIn("18 enfants", strings)
            self.assertIn("Gaël Martin", strings)
            self.assertIn("Lundi", strings)

    def test_export_pdf_calendrier_par_groupe(self):
        response = self.client.get(
            reverse("export_planning_pdf"),
            {
                "debut": "2026-07-06",
                "fin": "2026-07-11",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 1500)

    def test_dimanche_ferme_nest_pas_exporte(self):
        response = self.client.get(
            reverse("export_planning_excel"),
            {
                "debut": "2026-07-06",
                "fin": "2026-07-12",
            },
        )
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
            self.assertNotIn("Dimanche", strings)
