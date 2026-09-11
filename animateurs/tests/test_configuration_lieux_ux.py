from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ConfigurationLieuxUxTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = Path(settings.BASE_DIR, "static/js/gestion.js").read_text(encoding="utf-8")
        cls.styles = Path(settings.BASE_DIR, "static/css/gestion.css").read_text(encoding="utf-8")
        cls.template = Path(settings.BASE_DIR, "templates/gestion.html").read_text(encoding="utf-8")

    def test_lieu_est_replie_et_dispose_d_un_bouton_d_ouverture(self):
        self.assertIn('class="lieu-accueils-block" hidden', self.script)
        self.assertIn('class="btn btn-ghost lieu-toggle" aria-expanded="false"', self.script)
        self.assertIn('function ouvrirLieuUnique(card)', self.script)

    def test_recherche_et_filtre_utilisent_les_accueils_charges(self):
        self.assertIn('id="lieux-search"', self.script)
        self.assertIn('id="lieux-filter"', self.script)
        self.assertIn('data.forEach((lieu) => (lieu.accueils || [])', self.script)
        self.assertIn('rechercheLieux.addEventListener("input", appliquerFiltresLieux)', self.script)

    def test_etat_du_lieu_et_de_l_accueil_est_conserve_localement(self):
        self.assertIn('sessionStorage.setItem(CLE_ETAT_LIEUX', self.script)
        self.assertIn('const cardOuverte = etat.lieuId', self.script)
        self.assertIn('const accueilBouton = etat.accueilId', self.script)
        self.assertIn('window.scrollTo({ top: positionScroll', self.script)

    def test_navigation_mobile_ne_conserve_qu_une_colonne(self):
        self.assertIn('@media(max-width:620px)', self.styles)
        self.assertIn('.lieux-navigation{grid-template-columns:1fr}', self.styles)
        self.assertIn('.gestion-page .lieu-card-header{grid-template-columns:auto minmax(0,1fr) auto}', self.styles)

    def test_carte_separe_ouvertures_jours_groupes_et_encadrement(self):
        for libelle in ("Périodes ouvertes", "Temps d’accueil", "Jours ouverts", "Groupes", "Encadrement"):
            self.assertIn(libelle, self.script)
        self.assertNotIn('<strong>Fonctionnement :</strong>', self.script)

    def test_entete_lieu_utilise_deux_lignes_distinctes(self):
        self.assertIn('class="lieu-compact-summary"', self.script)
        self.assertIn('class="lieu-address"', self.script)
        self.assertIn('.lieu-compact-summary,.lieu-address{display:block', self.styles)

    def test_drag_and_drop_persiste_l_ordre_complet_des_lieux(self):
        self.assertIn('class="lieu-drag-handle" draggable="true"', self.script)
        self.assertIn('poignee.addEventListener("dragstart"', self.script)
        self.assertIn('card.addEventListener("drop"', self.script)
        self.assertIn('apiFetch("/api/centres/reordonner/"', self.script)
        self.assertIn('body: JSON.stringify({ centre_ids })', self.script)

    def test_commandes_monter_descendre_et_tout_replier_sont_absentes(self):
        self.assertNotIn('lieu-move-up', self.script)
        self.assertNotIn('lieu-move-down', self.script)
        self.assertNotIn('lieux-collapse-all', self.script)

    def test_onglets_gestion_sont_montes_a_la_demande(self):
        self.assertIn("const initialises = new Set();", self.template)
        self.assertIn("const obsoletes = new Set();", self.template)
        self.assertIn("function monterOnglet(nom)", self.template)
        self.assertIn("if (!initialises.has(nom))", self.template)
        self.assertIn("rafraichirOngletObsolete(nom);", self.template)
        self.assertIn("else monterOnglet(root.querySelector(\".tab-btn.active\")?.dataset.tab);", self.template)
        self.assertIn("documents: () => DocumentsManagement.mount", self.template)

    def test_referentiels_gestion_partagent_une_promesse_et_s_invalident(self):
        self.assertIn("const references = new Map();", self.template)
        self.assertIn("references.set(key, request);", self.template)
        self.assertIn("if (references.get(key) === request) references.delete(key);", self.template)
        self.assertIn("GestionData.invalidate(\"qualifications\")", self.template)
        self.assertIn("GestionData.invalidate(\"centres\")", self.template)
        self.assertIn('obsoletes.add("groupes");', self.template)
        self.assertNotIn('instances.get("groupes")?.charger?.();', self.template)
