from pathlib import Path

from django.conf import settings

from animateurs.tests.base import ConnexionTestCase


class InterfaceHarmonisationTests(ConnexionTestCase):
    def test_accueil_direction_et_planning_chargent_leurs_styles_adaptes(self):
        accueil = self.client.get("/")
        planning = self.client.get("/planning/")

        self.assertEqual(accueil.status_code, 200)
        self.assertEqual(planning.status_code, 200)
        self.assertContains(accueil, "css/dashboard.css")
        self.assertContains(accueil, 'id="dashboard-root"')
        self.assertContains(planning, "css/calendars.css")
        self.assertContains(planning, 'class="planning-view-week calendar-sites"')

    def test_calendriers_partages_respectent_hidden_sans_imposer_le_layout_du_planning(self):
        css = (Path(settings.BASE_DIR) / "static/css/calendars.css").read_text()
        planning_css = (Path(settings.BASE_DIR) / "static/css/planning.css").read_text()

        css_compact = css.replace(" ", "")
        self.assertIn(".calendar-site-card[hidden]", css)
        self.assertIn("display:none!important", css_compact)
        self.assertNotIn("page-planning", css)
        self.assertIn(".planning-centres-row", planning_css)
        self.assertIn("repeat(var(--planning-row-count), minmax(0, 1fr))", planning_css)

    def test_le_selecteur_de_semaines_est_partage_par_toutes_les_pages(self):
        pages_principales = [
            "templates/accueil.html",
            "templates/planning.html",
            "templates/gestion.html",
            "templates/administration.html",
            "templates/recapitulatif.html",
            "templates/employes.html",
            "templates/documents_partages.html",
            "templates/mes_disponibilites.html",
        ]
        for fichier in pages_principales:
            contenu = (Path(settings.BASE_DIR) / fichier).read_text()
            self.assertIn("partials/_page_header.html", contenu, fichier)

        entete = (Path(settings.BASE_DIR) / "templates/partials/_page_header.html").read_text()
        self.assertIn("partials/_week_navigation.html", entete)
        self.assertIn("app-page-header--week-only", entete)
        self.assertIn("app-page-title", entete)
        self.assertNotIn("app-page-title-sr", entete)
        self.assertNotIn("app-page-header__title", entete)

        for fichier in ("templates/gestion.html", "templates/partials/_emails_admin.html"):
            contenu = (Path(settings.BASE_DIR) / fichier).read_text()
            self.assertIn("partials/_week_picker.html", contenu, fichier)

        composant = (Path(settings.BASE_DIR) / "static/js/common/week-picker.js").read_text()
        self.assertIn("function groupPeriods", composant)
        self.assertIn("function vacationLabel", composant)
        self.assertIn("function weekLabel", composant)
        self.assertIn("description_source", composant)
        self.assertIn("function isCurrentPeriod", composant)
        self.assertIn("closestPeriod(this.periods, this.activeDate)", composant)
        self.assertIn("period?.debut", composant)
        self.assertIn("period?.fin", composant)

    def test_la_navigation_est_une_barre_d_icones_non_depliable(self):
        navigation = (Path(settings.BASE_DIR) / "templates/partials/_nav.html").read_text()
        script = (Path(settings.BASE_DIR) / "static/js/ui.js").read_text()

        self.assertIn('class="app-rail"', navigation)
        self.assertIn('class="app-rail-links"', navigation)
        self.assertNotIn("data-nav-open", navigation)
        self.assertNotIn("data-nav-collapse", navigation)
        self.assertNotIn("nav-overlay", navigation)
        self.assertNotIn("initNavigationLaterale", script)

    def test_les_onglets_de_page_sont_places_sous_l_entete(self):
        attentes = {
            "templates/planning.html": "planning-tabs app-page-tabs app-page-tabs-row",
            "templates/gestion.html": "gestion-main-tabs app-page-tabs app-page-tabs-row",
            "templates/administration.html": "admin-tabs app-page-tabs app-page-tabs-row",
            "templates/recapitulatif.html": "recap-tabs app-page-tabs app-page-tabs-row",
        }
        for fichier, classe_onglets in attentes.items():
            contenu = (Path(settings.BASE_DIR) / fichier).read_text()
            position_entete = contenu.index('partials/_page_header.html')
            position_onglets = contenu.index(classe_onglets)
            self.assertGreater(position_onglets, position_entete, fichier)

        entete = (Path(settings.BASE_DIR) / "templates/partials/_page_header.html").read_text()
        self.assertNotIn("app-page-tabs", entete)
        self.assertNotIn("planning-tabs", entete)

    def test_les_selecteurs_d_une_page_partagent_le_meme_appel_api(self):
        composant = (Path(settings.BASE_DIR) / "static/js/common/week-picker.js").read_text()
        self.assertIn("let sharedPeriodsRequest = null", composant)
        self.assertIn("function loadSharedPeriods", composant)
        self.assertIn("const periods = await loadSharedPeriods()", composant)
        self.assertIn("navigateGeneric", composant)

    def test_documents_et_emails_utilisent_exactement_le_meme_partial(self):
        documents = (Path(settings.BASE_DIR) / "templates/gestion.html").read_text()
        emails = (Path(settings.BASE_DIR) / "templates/partials/_emails_admin.html").read_text()

        for contenu in (documents, emails):
            self.assertIn("partials/_week_picker.html", contenu)
            self.assertIn('mode="multiple"', contenu)
            self.assertIn('placeholder="Choisir des semaines"', contenu)
            self.assertIn("clear_id=", contenu)

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

    def test_les_filtres_salaries_s_ouvrent_dans_une_modal_centree(self):
        partial = (Path(settings.BASE_DIR) / "templates/partials/_staff_filter.html").read_text()
        script = (Path(settings.BASE_DIR) / "static/js/common/staff-filter.js").read_text()
        css = (Path(settings.BASE_DIR) / "static/css/common-base.css").read_text()

        self.assertIn("<dialog", partial)
        self.assertIn("data-staff-filter-dialog", partial)
        self.assertIn("data-staff-filter-close", partial)
        self.assertNotIn("<details", partial)
        self.assertIn("dialog.showModal()", script)
        self.assertIn('event.target === dialog', script)
        self.assertIn("place-items:center", css.replace(" ", ""))
        self.assertIn(".compact-filter__dialog::backdrop", css)

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

    def test_planning_charge_les_effectifs_en_une_requete_par_semaine(self):
        planning = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text()
        donnees_partagees = (Path(settings.BASE_DIR) / "static/js/common/planning-data.js").read_text()

        self.assertIn("PlanningData.fetchWeekEffectifs", planning)
        self.assertIn("/api/effectifs-enfants/", donnees_partagees)
        self.assertIn("const effectifsCache = new Map()", donnees_partagees)
        self.assertNotIn("evenement.effectifs_enfants || []", planning)

    def test_import_excel_actualise_immediatement_les_effectifs_du_planning(self):
        planning = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text()

        self.assertIn('document.addEventListener("effectifs-enfants-importes", async (event) =>', planning)
        self.assertIn("PlanningData.invalidateWeekEffectifs();", planning)
        self.assertIn("event.detail?.periodes", planning)
        self.assertIn("PlanningData.fetchWeekEffectifs(periode.debut, periode.fin, { force: true })", planning)
        self.assertIn("await Promise.all(calendars.map((calendar) => chargerEffectifsEnfants(calendar)))", planning)

    def test_effectifs_et_taux_sont_modifiables_directement_dans_les_cartes(self):
        planning = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text()
        css = (Path(settings.BASE_DIR) / "static/css/planning.css").read_text()

        self.assertIn("function ouvrirEditionEffectifInline", planning)
        self.assertIn('data-effectif-inline="nombre"', planning)
        self.assertIn('data-effectif-inline="ratio"', planning)
        self.assertIn("ratios_encadrement", planning)
        self.assertIn(".planning-inline-editor", css)

    def test_clic_effectif_ne_declenche_pas_la_selection_du_jour(self):
        planning = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text()

        self.assertIn('selectable: estModeAffectations()', planning)
        self.assertIn('calendar.setOption("selectable", modeAffectationsActif)', planning)
        self.assertIn('if (!modeAffectationsActif) calendar.unselect()', planning)
        self.assertIn('["pointerdown", "mousedown", "touchstart"]', planning)

    def test_selecteur_centres_souvre_vers_la_droite_du_menu_general(self):
        css = (Path(settings.BASE_DIR) / "static/css/planning.css").read_text().replace(" ", "")

        debut = css.index(".planning-centres-dropdown-menu{")
        regle = css[debut:css.index("}", debut)]
        self.assertIn("left:0", regle)
        self.assertIn("right:auto", regle)

    def test_semaine_selectionnee_est_persistante_et_partagee(self):
        selecteur = (Path(settings.BASE_DIR) / "static/js/common/week-picker.js").read_text()
        planning = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text()
        accueil = (Path(settings.BASE_DIR) / "static/js/accueil.js").read_text()
        dashboard = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text()
        recapitulatif = (Path(settings.BASE_DIR) / "static/js/recapitulatif.js").read_text()

        self.assertIn("animation-manager-selected-week-date-v1", selecteur)
        self.assertIn("getPersistedDate", selecteur)
        self.assertIn("setPersistedDate", selecteur)
        for contenu in (planning, accueil, dashboard, recapitulatif):
            self.assertIn("WeekPicker.getPersistedDate", contenu)

    def test_planning_recharge_les_statuts_animateurs_pour_la_semaine(self):
        contenu = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text()

        self.assertIn('format: "planning"', contenu)
        self.assertIn("debut: plage.debut", contenu)
        self.assertIn("fin: plage.fin", contenu)
        self.assertIn("rafraichirAnimateursSemaine", contenu)

    def test_planning_propose_les_horaires_sur_chaque_affectation(self):
        template = (Path(settings.BASE_DIR) / "templates/planning.html").read_text()
        script = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text()
        css = (Path(settings.BASE_DIR) / "static/css/planning.css").read_text()

        self.assertNotIn('data-planning-mode="horaires"', template)
        self.assertNotIn('id="planning-horaires-panel"', template)
        self.assertIn("function ouvrirSaisieHorairesAffectation(info, calendar)", script)
        self.assertIn("function normaliserHeureSaisie(valeur)", script)
        self.assertIn("correspondance[2] || 0", script)
        self.assertIn("JSON.stringify({ horaires })", script)
        self.assertIn("modal-horaires-affectation", template)
        self.assertIn("horaires-affectation-row", script)
        self.assertIn("modal-horaires-groupe", template)
        self.assertIn("btn-horaires-groupe", script)
        self.assertIn("horaires-affectations/", script)
        self.assertIn(".horaires-affectation-row", css)
        self.assertNotIn("body.page-planning.planning-mode-horaires", css)

    def test_tableau_de_bord_conserve_le_libelle_commun_du_selecteur_de_semaine(self):
        script = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text()

        self.assertIn("updateLabel: true", script)
        self.assertNotIn('getElementById("dashboard-visible-period")', script)

    def test_tableau_de_bord_regroupe_les_alertes_et_affiche_les_nouvelles_metriques(self):
        template = (Path(settings.BASE_DIR) / "templates/accueil.html").read_text()
        script = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text()

        self.assertIn('id="kpi-moderes"', template)
        self.assertIn("moyenne_enfants_groupe_jour", script)
        self.assertIn("alertesRegroupees", script)
        self.assertIn("dashboard-alert-count", script)

    def test_ordre_des_blocs_du_tableau_de_bord_est_persistant(self):
        template = (Path(settings.BASE_DIR) / "templates/accueil.html").read_text()
        script = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text()
        css = (Path(settings.BASE_DIR) / "static/css/dashboard.css").read_text()

        self.assertIn('data-dashboard-block="centres"', template)
        self.assertIn('data-dashboard-block="couverture"', template)
        self.assertIn("function activerTriPersistant", script)
        self.assertIn("animation-manager-dashboard-blocs", script)
        self.assertIn("localStorage.setItem", script)
        self.assertIn(".dashboard-drag-handle", css)

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

    def test_la_couche_commune_est_chargee_apres_les_styles_de_page(self):
        base = (Path(settings.BASE_DIR) / "templates/base.html").read_text()

        self.assertIn("css/common-ui.css", base)
        self.assertGreater(base.index("css/common-ui.css"), base.index("block extra_head"))

    def test_les_pages_principales_utilisent_le_shell_et_les_cartes_communes(self):
        attentes = {
            "templates/accueil.html": ["page-shell", "ui-card"],
            "templates/administration.html": ["page-shell", "ui-card"],
            "templates/documents_partages.html": ["page-shell", "partials/_page_header.html", "ui-grid"],
            "templates/employes.html": [
                "page-shell",
                "employees-workspace",
                "employees-sidebar",
                "employee-editor",
                "ui-card",
            ],
            "templates/gestion.html": ["page-shell", "ui-card"],
            "templates/mes_disponibilites.html": ["page-shell", "partials/_page_header.html", "ui-card"],
            "templates/recapitulatif.html": ["page-shell", "partials/_page_header.html", "ui-card"],
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
        css = (Path(settings.BASE_DIR) / "static/css/common-ui.css").read_text()

        self.assertIn("--page-gutter", css)
        self.assertIn("--card-padding", css)
        self.assertIn("--control-height", css)
        self.assertIn(".page-shell", css)
        self.assertIn(".ui-card", css)
