from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from animateurs.models import Animateur


class PlanningRefactorStructureTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(settings.BASE_DIR)
        self.planning_css = (self.root / "static/css/planning.css").read_text(encoding="utf-8")
        self.common_css = (self.root / "static/css/common-ui.css").read_text(encoding="utf-8")
        self.planning_js = (self.root / "static/js/planning.js").read_text(encoding="utf-8")
        self.administration_js = (self.root / "static/js/administration.js").read_text(encoding="utf-8")
        self.planning_template = (self.root / "templates/planning.html").read_text(encoding="utf-8")
        self.base_template = (self.root / "templates/base.html").read_text(encoding="utf-8")

    def test_planning_possede_une_seule_structure_deux_colonnes(self):
        self.assertIn(
            "grid-template-columns: var(--planning-sidebar-width) minmax(0, 1fr)",
            self.planning_css,
        )
        self.assertNotIn("planning-sidebar-resizer", self.planning_css)
        self.assertNotIn("#planning-toolbar", self.planning_css)
        self.assertNotIn("#planning-view-switcher", self.planning_css)
        self.assertNotIn("#calendars-scroll-top", self.planning_css)

    def test_styles_du_planning_ne_fuitent_plus_dans_common_ui(self):
        for marqueur in ("page-planning", "planning-workspace", "#animateurs-panel", "#calendars-section"):
            self.assertNotIn(marqueur, self.common_css)

    def test_css_responsive_reste_limite_et_lisible(self):
        self.assertLessEqual(self.planning_css.count("@media"), 2)
        self.assertIn("overflow-x: hidden", self.planning_css)
        self.assertIn("repeat(var(--planning-row-count), minmax(0, 1fr))", self.planning_css)

    def test_feuille_planning_est_chargee_apres_common_ui(self):
        self.assertIn("{% block page_styles %}{% endblock %}", self.base_template)
        self.assertIn("{% block page_styles %}", self.planning_template)
        self.assertNotIn("css/gestion.css", self.planning_template)
        self.assertLess(
            self.base_template.index("css/common-ui.css"),
            self.base_template.index("{% block page_styles %}"),
        )

    def test_javascript_ne_reference_plus_les_anciens_elements(self):
        self.assertNotIn("aideModePlanning", self.planning_js)
        self.assertNotIn("compteurAnimateursVisibles", self.planning_js)
        self.assertNotIn("animateur.couleur ||", self.planning_js)

    def test_suppression_flottante_rafraichit_sa_ligne_hors_fullcalendar(self):
        debut = self.planning_js.index('boutonSupprimerAffectation?.addEventListener("click"')
        fin = self.planning_js.index("function ouvrirSaisieHorairesGroupe", debut)
        gestion_suppression = self.planning_js[debut:fin]
        self.assertIn("etaitFlottante", gestion_suppression)
        self.assertIn("rafraichirLigneAnimateursFlottants(centre, ligne)", gestion_suppression)

    def test_ligne_flottante_possede_un_libelle_discret(self):
        self.assertIn('class="planning-floating-label"', self.planning_js)
        self.assertIn(".planning-floating-label", self.planning_css)

    def test_entete_groupe_accepte_affectation_de_toute_la_semaine(self):
        self.assertIn("async function affecterAnimateurSurSemaine", self.planning_js)
        self.assertIn('enteteGroupe.addEventListener("click"', self.planning_js)
        self.assertIn('enteteGroupe.dataset.weekAssignmentTarget = "true"', self.planning_js)
        self.assertIn(".evenement-calendar-header.is-week-drag-over", self.planning_css)

    def test_import_excel_est_reserve_au_mode_effectifs(self):
        self.assertIn('id="btn-effectifs-excel"', self.planning_template)
        self.assertIn('type="button" hidden', self.planning_template)
        self.assertIn("boutonImportEffectifsExcel.hidden = !estModeEffectifs()", self.planning_js)

    def test_export_planning_redirige_vers_administration_avec_la_periode(self):
        self.assertIn('id="btn-planning-export"', self.planning_template)
        self.assertNotIn('id="btn-planning-pdf"', self.planning_template)
        self.assertNotIn('id="btn-planning-excel"', self.planning_template)
        self.assertLess(
            self.planning_template.index('id="btn-planning-export"'),
            self.planning_template.index('id="btn-auto-semaine"'),
        )
        self.assertIn('url.searchParams.set("onglet", "export")', self.planning_js)
        self.assertIn('url.searchParams.set("periode_id", String(periode.id))', self.planning_js)
        self.assertIn('get("periode_id")', self.administration_js)
        self.assertIn("checkbox.checked = true", self.administration_js)

    def test_entete_groupe_explique_les_affectations_jour_et_semaine(self):
        self.assertIn('class="planning-assignment-hint"', self.planning_js)
        self.assertIn("cliquez sur une case pour 1 jour, ici pour toute la semaine", self.planning_js)
        self.assertIn(".planning-assignment-hint", self.planning_css)

    def test_objectif_et_horaires_sont_alignes_avec_le_titre_du_groupe(self):
        debut_titre = self.planning_js.index('class="evenement-calendar-title calendar-group-title"')
        fin_titre = self.planning_js.index('<div class="evenement-calendar-meta', debut_titre)
        contenu_titre = self.planning_js[debut_titre:fin_titre]
        self.assertIn('class="planning-objectif-groupe"', contenu_titre)
        self.assertIn('class="planning-group-hours-actions"', contenu_titre)

    def test_temps_travail_possede_son_propre_defilement_vertical(self):
        regle = self.planning_css[self.planning_css.index(".worktime-panel{"):]
        regle = regle[:regle.index("}")]
        self.assertIn("overflow-y:auto", regle)
        self.assertIn("height:calc(100dvh - 132px)", regle)

    def test_couleur_personnelle_animateur_supprimee_du_modele(self):
        self.assertNotIn("couleur", {champ.name for champ in Animateur._meta.get_fields()})
