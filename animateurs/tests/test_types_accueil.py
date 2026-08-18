from importlib import import_module

from django.apps import apps
from django.urls import reverse

from animateurs.models import Animateur, Centre, Document, PeriodeScolaire, Sejour, TypeAccueil
from animateurs.services.types_accueil import filtrer_relation_type, filtrer_relations_types
from animateurs.tests.base import ConnexionTestCase


class SocleTypeAccueilNonRegressionTests(ConnexionTestCase):
    """Verrouille les points d'entrée et créations historiques avant évolution."""

    def test_routes_principales_conservent_leurs_noms_et_repondent(self):
        for nom in ("accueil", "planning", "gestion", "recapitulatif"):
            with self.subTest(nom=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)
        self.assertRedirects(
            self.client.get(reverse("temps_travail")),
            "/recapitulatif/?onglet=temps-travail",
            fetch_redirect_response=False,
        )

    def test_objets_historiques_restent_creables_sans_type_explicite(self):
        animateur = Animateur.objects.create(prenom="Test", nom="Historique")
        centre = Centre.objects.create(nom="Lieu historique", code="LH")
        periode = PeriodeScolaire.objects.create(
            nom="Été — Semaine historique",
            annee_scolaire="2026-2027",
            zone="A",
            debut="2026-07-06",
            fin="2026-07-10",
        )
        document = Document.objects.create(titre="Document historique", fichier="documents/historique.pdf")

        self.assertIsNotNone(animateur.pk)
        self.assertIsNotNone(centre.pk)
        self.assertIsNotNone(periode.pk)
        self.assertIsNotNone(document.pk)


class SocleTypeAccueilTests(ConnexionTestCase):
    def test_referentiel_conserve_alias_mercredis_et_affiche_trois_types_principaux(self):
        self.assertEqual(
            list(TypeAccueil.objects.values_list("code", "nom")),
            [
                ("vacances", "Vacances"),
                ("mercredis", "Mercredis"),
                ("periscolaire", "Périscolaire"),
                ("sejours", "Séjours"),
            ],
        )
        self.assertEqual(
            list(TypeAccueil.objects.filter(actif=True).values_list("code", flat=True)),
            ["vacances", "periscolaire", "sejours"],
        )

    def test_selecteur_propose_vue_generale_types_et_periodes_filtrees(self):
        vacances = TypeAccueil.objects.get(code="vacances")
        mercredis = TypeAccueil.objects.get(code="mercredis")
        PeriodeScolaire.objects.create(
            nom="Été — Semaine 1", annee_scolaire="2026-2027", zone="A",
            debut="2026-07-06", fin="2026-07-10", type_accueil=vacances,
        )
        PeriodeScolaire.objects.create(
            nom="Été — Semaine 2", annee_scolaire="2026-2027", zone="A",
            debut="2026-07-13", fin="2026-07-17", type_accueil=vacances,
        )
        PeriodeScolaire.objects.create(
            nom="Mercredis septembre", annee_scolaire="2026-2027", zone="A",
            debut="2026-09-02", fin="2026-09-30", type_accueil=mercredis,
        )

        response = self.client.get(reverse("accueil"), {"type_accueil": "vacances"})

        self.assertContains(response, "Vue générale")
        self.assertContains(response, "Vacances")
        self.assertNotContains(response, '<option value="mercredis">', html=False)
        self.assertContains(response, "Été 2026")
        self.assertNotContains(response, "Été 2026 — Semaine 1")
        self.assertNotContains(response, "Mercredis septembre")
        self.assertEqual(self.client.session["type_accueil"], "vacances")
        html = response.content.decode()
        self.assertEqual(html.count('id="app-type-accueil"'), 1)
        self.assertLess(html.index("Tableau de bord"), html.index('id="app-type-accueil"'))
        self.assertLess(html.index('id="app-type-accueil"'), html.index('id="app-periode-accueil"'))
        self.assertLess(html.index('id="app-periode-accueil"'), html.index('id="dashboard-period-nav"'))

        periode_complete = response.context["periodes_accueil"][0]
        response = self.client.get(reverse("accueil"), {
            "type_accueil": "vacances",
            "periode_accueil": periode_complete["id"],
        })
        self.assertContains(response, 'data-periode-accueil-debut="2026-07-06"')
        self.assertContains(response, 'data-periode-accueil-fin="2026-07-17"')

    def test_filtres_reutilisables_conservent_une_vue_generale(self):
        vacances = TypeAccueil.objects.get(code="vacances")
        mercredis = TypeAccueil.objects.get(code="mercredis")
        generale = Document.objects.create(titre="Général", fichier="documents/general.pdf")
        cible = Document.objects.create(titre="Vacances", fichier="documents/vacances.pdf")
        cible.types_accueil.add(vacances)
        autre = Document.objects.create(titre="Mercredis", fichier="documents/mercredis.pdf")
        autre.types_accueil.add(mercredis)

        self.assertEqual(filtrer_relations_types(Document.objects.all(), "").count(), 3)
        self.assertEqual(
            set(filtrer_relations_types(Document.objects.all(), "vacances").values_list("pk", flat=True)),
            {generale.pk, cible.pk},
        )

        periode_generale = PeriodeScolaire.objects.create(
            nom="Générale", annee_scolaire="2027-2028", zone="A", debut="2027-01-01", fin="2027-01-02"
        )
        periode_cible = PeriodeScolaire.objects.create(
            nom="Vacances", annee_scolaire="2027-2028", zone="A", debut="2027-02-01", fin="2027-02-02", type_accueil=vacances
        )
        self.assertEqual(
            set(filtrer_relation_type(PeriodeScolaire.objects.all(), "vacances").values_list("pk", flat=True)),
            {periode_generale.pk, periode_cible.pk},
        )

    def test_sejour_reference_un_lieu_legacy_sans_le_transformer(self):
        lieu = Centre.objects.create(nom="Ancien lieu séjour", code="ALS")
        sejour = Sejour.objects.create(nom="Séjour test", source_lieu_legacy=lieu)

        lieu.refresh_from_db()
        self.assertEqual(sejour.source_lieu_legacy, lieu)
        self.assertEqual(lieu.nom, "Ancien lieu séjour")

    def test_initialisation_des_types_est_reversible(self):
        migration = import_module("animateurs.migrations.0084_socle_types_accueil")
        document = Document.objects.create(titre="Ciblé", fichier="documents/cible.pdf")
        document.types_accueil.add(TypeAccueil.objects.get(code="vacances"))

        migration.retirer_initialisation(apps, None)
        self.assertFalse(TypeAccueil.objects.exists())
        self.assertFalse(document.types_accueil.exists())

        migration.initialiser_types_accueil(apps, None)
        self.assertEqual(TypeAccueil.objects.count(), 4)
