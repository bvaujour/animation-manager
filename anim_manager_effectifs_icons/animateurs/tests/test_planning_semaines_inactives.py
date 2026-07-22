from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class PlanningSemainesInactivesTests(SimpleTestCase):
    def test_un_groupe_permanent_n_est_pas_force_visible_hors_semaine_active(self):
        script = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text(encoding="utf-8")

        self.assertNotIn("if (groupe?.permanent) return true;", script)
        self.assertNotIn("if (!groupe.permanent && !periodes.some", script)
        self.assertIn(
            "if (!periodes.some((periode) => dateStr >= periode.debut",
            script,
        )

    def test_une_semaine_totalement_fermee_est_masquee(self):
        script = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text(encoding="utf-8")

        self.assertIn("function groupeOuvertSurPlage", script)
        self.assertIn("if (evenementOuvertCeJour(groupe, jour)) return true;", script)
        self.assertIn("card.hidden = !groupe || !groupeOuvertSurPlage(groupe, debut, fin);", script)
        self.assertNotIn("card.hidden = !groupe || !groupeChevauchePlage", script)
        self.assertIn("bloc.hidden = false;", script)
        self.assertNotIn("bloc.hidden = aucunGroupeVisible;", script)
        self.assertIn('compteur.textContent = visibles.length', script)
        self.assertIn(': "Aucun groupe";', script)
        self.assertIn("if (etatVide) etatVide.hidden = !aucunGroupeVisible;", script)

    def test_hidden_reste_prioritaire_sur_les_regles_de_mise_en_page(self):
        css = (Path(settings.BASE_DIR) / "static/css/calendars.css").read_text(encoding="utf-8")
        planning_css = (Path(settings.BASE_DIR) / "static/css/planning.css").read_text(encoding="utf-8")

        self.assertIn(".calendar-site-card[hidden]", css)
        self.assertIn(".calendar-group-card[hidden]", css)
        self.assertIn("display:none !important", css)
        self.assertIn(".evenement-calendar-card[hidden]", planning_css)
