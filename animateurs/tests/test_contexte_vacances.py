import datetime

from django.urls import reverse

from animateurs.models import PeriodeScolaire, TypeAccueil
from animateurs.tests.base import ConnexionTestCase


class ContexteVacancesNonRegressionTests(ConnexionTestCase):
    """Le contexte complète le parcours Vacances sans changer ses API historiques."""

    def setUp(self):
        self.vacances = TypeAccueil.objects.get(code=TypeAccueil.VACANCES)
        self.periscolaire = TypeAccueil.objects.get(code=TypeAccueil.PERISCOLAIRE)
        self.hiver_1 = self._periode("Hiver — Semaine 1", datetime.date(2027, 2, 15), self.vacances)
        self.hiver_2 = self._periode("Hiver — Semaine 2", datetime.date(2027, 2, 22), self.vacances)
        self.printemps = self._periode("Printemps — Semaine 1", datetime.date(2027, 4, 12), self.vacances)
        self.scolaire = self._periode("Période scolaire 3", datetime.date(2027, 3, 1), self.periscolaire)

    @staticmethod
    def _periode(nom, debut, type_accueil):
        return PeriodeScolaire.objects.create(
            nom=nom,
            annee_scolaire="2026-2027",
            zone="A",
            debut=debut,
            fin=debut + datetime.timedelta(days=4),
            type_accueil=type_accueil,
        )

    def test_api_historique_des_periodes_reste_non_filtree(self):
        self.client.get(
            reverse("accueil"),
            {"type_accueil": "vacances", "periode_accueil": "hiver-2027"},
        )

        response = self.client.get(reverse("api_periodes_scolaires"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()}, {
            self.hiver_1.pk, self.hiver_2.pk, self.printemps.pk, self.scolaire.pk,
        })

    def test_selecteurs_partages_recoivent_uniquement_la_periode_vacances_active(self):
        self.client.get(
            reverse("accueil"),
            {"type_accueil": "vacances", "periode_accueil": "hiver-2027"},
        )

        response = self.client.get(reverse("api_periodes_scolaires"), {"contexte_travail": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()}, {self.hiver_1.pk, self.hiver_2.pk})

    def test_contexte_vacances_est_conserve_sur_une_autre_page_sans_parametres(self):
        self.client.get(
            reverse("accueil"),
            {"type_accueil": "vacances", "periode_accueil": "hiver-2027"},
        )

        response = self.client.get(reverse("planning"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["type_accueil_selectionne"], "vacances")
        self.assertEqual(response.context["periode_accueil_selectionnee"], "hiver-2027")
        self.assertEqual(
            set(response.context["periode_accueil_active"]["semaine_ids"]),
            {self.hiver_1.pk, self.hiver_2.pk},
        )

    def test_vue_generale_conserve_toutes_les_semaines_dans_les_selecteurs(self):
        response = self.client.get(reverse("api_periodes_scolaires"), {"contexte_travail": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 4)

    def test_tableau_de_bord_affiche_la_vue_de_la_periode_vacances_active(self):
        response = self.client.get(
            reverse("accueil"),
            {"type_accueil": "vacances", "periode_accueil": "hiver-2027"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="dashboard-period-overview"')
        self.assertContains(response, "Vue de la période — Hiver 2027")
        self.assertContains(response, "Détail de la semaine sélectionnée")
        self.assertContains(response, 'data-periode-accueil-debut="2027-02-15"')
        self.assertContains(response, 'data-periode-accueil-fin="2027-02-26"')

    def test_tableau_de_bord_historique_reste_inchange_sans_periode_complete(self):
        response = self.client.get(reverse("accueil"), {"type_accueil": "vacances"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="dashboard-period-overview"')
        self.assertContains(response, 'class="dashboard-kpis"')
        self.assertContains(response, 'class="dashboard-main-grid"')

    def test_changer_de_semaine_ne_modifie_pas_la_periode_complete_en_session(self):
        self.client.get(
            reverse("accueil"),
            {"type_accueil": "vacances", "periode_accueil": "hiver-2027"},
        )

        detail = self.client.get(reverse("api_tableau_de_bord"), {"semaine": self.hiver_2.debut.isoformat()})

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["periode"]["debut_semaine"], "2027-02-22")
        self.assertEqual(self.client.session["periode_accueil"], "hiver-2027")
        self.assertEqual(set(self.client.session["semaines_contexte_travail"]), {self.hiver_1.pk, self.hiver_2.pk})
