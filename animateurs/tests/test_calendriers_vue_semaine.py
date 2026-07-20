from pathlib import Path

from django.conf import settings
from django.urls import reverse

from animateurs.tests.base import ConnexionTestCase


class CalendriersVueSemaineTests(ConnexionTestCase):
    def test_planning_ne_propose_plus_la_vue_mois(self):
        response = self.client.get(reverse("planning"))
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode("utf-8")
        self.assertNotIn("Semaine affichée", contenu)
        self.assertIn("Aujourd’hui", contenu)
        self.assertNotIn(">Mois<", contenu)
        self.assertNotIn("planning-view-switcher", contenu)

    def test_accueil_direction_propose_un_mini_calendrier_de_pilotage(self):
        response = self.client.get(reverse("accueil"))
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode("utf-8")
        self.assertIn('id="dashboard-calendar"', contenu)
        self.assertIn('id="dashboard-month-prev"', contenu)
        self.assertIn('id="dashboard-month-next"', contenu)
        self.assertNotIn("home-view-month", contenu)

    def test_javascript_ne_contient_plus_de_vue_mensuelle(self):
        base_dir = Path(settings.BASE_DIR)
        for fichier in (base_dir / "static/js/planning.js", base_dir / "static/js/accueil.js"):
            contenu = fichier.read_text(encoding="utf-8")
            self.assertNotIn("dayGridMonth", contenu)
