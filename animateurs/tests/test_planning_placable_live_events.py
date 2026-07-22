from pathlib import Path

from django.test import SimpleTestCase


class PlanningPlacableServerSituationTests(SimpleTestCase):
    def test_liste_utilise_la_situation_hebdomadaire_calculee_par_le_serveur(self):
        script = (Path(__file__).resolve().parents[2] / "static/js/planning.js").read_text()

        self.assertIn("animateur.situation_semaine", script)
        self.assertIn('situation.encore_placable === true', script)
        self.assertIn('situation.disponible === true', script)
        self.assertIn('situation.affecte === true', script)
        self.assertNotIn("affecteCeJourCalendriers", script)
        self.assertNotIn("calendriersAffectationsCharges", script)
