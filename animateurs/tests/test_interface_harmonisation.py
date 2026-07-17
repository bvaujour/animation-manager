from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class InterfaceHarmonisationTests(SimpleTestCase):
    def test_accueil_et_planning_chargent_le_style_calendrier_partage(self):
        accueil = self.client.get("/")
        planning = self.client.get("/planning/")

        self.assertEqual(accueil.status_code, 200)
        self.assertEqual(planning.status_code, 200)
        self.assertContains(accueil, "css/calendars.css")
        self.assertContains(planning, "css/calendars.css")
        self.assertContains(accueil, 'class="home-calendars calendar-sites"')
        self.assertContains(planning, 'class="planning-view-week calendar-sites"')

    def test_planning_force_une_colonne_de_calendriers_et_respecte_hidden(self):
        css = (Path(settings.BASE_DIR) / "static/css/calendars.css").read_text()

        self.assertIn("flex-direction: column !important", css)
        self.assertIn(".calendar-site-card[hidden]", css)
        self.assertIn("display: none !important", css)

    def test_les_interfaces_de_periodes_sont_rangees_par_annee(self):
        fichiers = [
            "static/js/gestion.js",
            "static/js/animateurs.js",
            "static/js/recapitulatif.js",
        ]
        for fichier in fichiers:
            contenu = (Path(settings.BASE_DIR) / fichier).read_text()
            self.assertIn("grouperPeriodesParAnnee", contenu, fichier)
            self.assertIn("period-year-accordion", contenu, fichier)

    def test_helpers_communs_des_annees_scolaires_sont_presents(self):
        contenu = (Path(settings.BASE_DIR) / "static/js/ui.js").read_text()

        self.assertIn("function anneeScolaireCourante", contenu)
        self.assertIn("function grouperPeriodesParAnnee", contenu)
        self.assertIn("function anneePeriodesADeplier", contenu)
