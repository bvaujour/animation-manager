from pathlib import Path

from django.conf import settings

from animateurs.tests.base import ConnexionTestCase


class InterfaceHarmonisationTests(ConnexionTestCase):
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

    def test_le_selecteur_de_semaines_est_partage_par_toutes_les_pages(self):
        attentes = {
            "templates/accueil.html": "partials/_week_navigation.html",
            "templates/planning.html": "partials/_week_navigation.html",
            "templates/gestion.html": "partials/_week_picker.html",
            "templates/partials/_emails_admin.html": "partials/_week_picker.html",
            "templates/recapitulatif.html": "partials/_week_picker.html",
        }
        for fichier, partial in attentes.items():
            contenu = (Path(settings.BASE_DIR) / fichier).read_text()
            self.assertIn(partial, contenu, fichier)

        composant = (Path(settings.BASE_DIR) / "static/js/common/week-picker.js").read_text()
        self.assertIn("function groupPeriods", composant)
        self.assertIn("function vacationLabel", composant)
        self.assertIn("function weekLabel", composant)
        self.assertIn("description_source", composant)
        self.assertIn("function isCurrentPeriod", composant)
        self.assertIn("closestPeriod(this.periods, this.activeDate)", composant)
        self.assertIn("period?.debut", composant)
        self.assertIn("period?.fin", composant)

    def test_documents_et_emails_utilisent_exactement_le_meme_partial(self):
        documents = (Path(settings.BASE_DIR) / "templates/gestion.html").read_text()
        emails = (Path(settings.BASE_DIR) / "templates/partials/_emails_admin.html").read_text()

        for contenu in (documents, emails):
            self.assertIn('partials/_week_picker.html', contenu)
            self.assertIn('mode="multiple"', contenu)
            self.assertIn('placeholder="Choisir des semaines"', contenu)
            self.assertIn('clear_id=', contenu)

        edition_documents = (Path(settings.BASE_DIR) / "static/js/documents-management.js").read_text()
        self.assertIn("mainPickerRoot.cloneNode(true)", edition_documents)
        self.assertNotIn("function pickerMarkup", edition_documents)

    def test_les_filtres_salaries_utilisent_le_meme_partial(self):
        fichiers = [
            "templates/planning.html",
            "templates/employes.html",
            "templates/partials/_emails_admin.html",
        ]
        for fichier in fichiers:
            contenu = (Path(settings.BASE_DIR) / fichier).read_text()
            self.assertIn("partials/_staff_filter.html", contenu, fichier)

    def test_helpers_communs_des_annees_scolaires_sont_presents(self):
        contenu = (Path(settings.BASE_DIR) / "static/js/ui.js").read_text()

        self.assertIn("function anneeScolaireCourante", contenu)
        self.assertIn("function grouperPeriodesParAnnee", contenu)
        self.assertIn("function anneePeriodesADeplier", contenu)

    def test_api_fetch_preserve_les_envois_formdata(self):
        contenu = (Path(settings.BASE_DIR) / "static/js/ui.js").read_text()

        self.assertIn("const bodyIsFormData", contenu)
        self.assertIn("!bodyIsFormData", contenu)
        self.assertIn('headers.set("Content-Type", "application/json")', contenu)
        self.assertIn('config.cache = "no-store"', contenu)

    def test_planning_precharge_et_relit_les_effectifs_persistes(self):
        contenu = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text()
        template = (Path(settings.BASE_DIR) / "templates/planning.html").read_text()

        self.assertIn("evenement.effectifs_enfants || []", contenu)
        self.assertIn('{ cache: "no-store" }', contenu)
        self.assertIn("window.setTimeout(() => chargerEffectifsEnfants(calendar), 0)", contenu)
        self.assertIn("effectifs-persistants-4", template)

    def test_les_pages_utilisent_le_client_api_commun(self):
        fichiers = [
            "static/js/accueil.js",
            "static/js/animateurs.js",
            "static/js/documents-management.js",
            "static/js/documents-partages.js",
            "static/js/mes-disponibilites.js",
            "static/js/planning.js",
            "static/js/common/week-picker.js",
        ]
        for fichier in fichiers:
            contenu = (Path(settings.BASE_DIR) / fichier).read_text()
            self.assertNotIn("fetch(", contenu, fichier)

    def test_la_couche_de_composants_est_chargee_apres_les_styles_de_page(self):
        base = (Path(settings.BASE_DIR) / "templates/base.html").read_text()

        self.assertIn("css/components.css", base)
        self.assertGreater(base.index("css/components.css"), base.index("block extra_head"))

    def test_les_pages_principales_utilisent_le_shell_et_les_cartes_communes(self):
        attentes = {
            "templates/accueil.html": ["page-shell", "ui-card"],
            "templates/administration.html": ["page-shell", "ui-card"],
            "templates/documents_partages.html": ["page-shell", "page-header", "ui-grid"],
            "templates/employes.html": ["page-shell", "employees-workspace", "employees-sidebar", "employee-editor", "ui-card"],
            "templates/gestion.html": ["page-shell", "ui-card"],
            "templates/mes_disponibilites.html": ["page-shell", "page-header", "ui-card"],
            "templates/recapitulatif.html": ["page-shell", "page-header", "ui-card"],
        }
        for fichier, classes in attentes.items():
            contenu = (Path(settings.BASE_DIR) / fichier).read_text()
            for classe in classes:
                self.assertIn(classe, contenu, fichier)

    def test_l_ancienne_page_salarie_autonome_est_supprimee(self):
        template = Path(settings.BASE_DIR) / "templates/employe_detail.html"
        self.assertFalse(template.exists())

        contenu = (Path(settings.BASE_DIR) / "templates/employes.html").read_text()
        self.assertIn("employees-sidebar", contenu)
        self.assertIn("employee-editor", contenu)

    def test_le_script_email_definit_l_affichage_de_configuration(self):
        contenu = (Path(settings.BASE_DIR) / "static/js/emails.js").read_text()

        self.assertIn("function afficherConfiguration()", contenu)
        self.assertGreaterEqual(contenu.count("afficherConfiguration"), 2)

    def test_les_variables_de_densite_sont_centralisees(self):
        css = (Path(settings.BASE_DIR) / "static/css/components.css").read_text()

        self.assertIn("--page-gutter", css)
        self.assertIn("--card-padding", css)
        self.assertIn("--control-height", css)
        self.assertIn(".page-shell", css)
        self.assertIn(".ui-card", css)

