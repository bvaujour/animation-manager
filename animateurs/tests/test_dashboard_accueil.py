import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, EffectifEnfantsJour, Evenement, HoraireAffectationJour, Sejour, Sortie, StatutPreparationSemaine
from animateurs.services.flottants import groupe_flottants_pour_centre
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_periode


class DashboardAccueilTests(ConnexionTestCase):
    def setUp(self):
        self.jour = datetime.date(2026, 7, 20)
        self.periode = creer_periode(debut=self.jour, nom="Été 2026 — Semaine 3")
        self.centre = Centre.objects.create(nom="La Pacaudière", code="LP", couleur="#4f7bc8")
        self.groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Maternelles",
            effectif_cible=2,
            enfants_par_animateur_defaut=8,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        self.groupe.periodes_scolaires.add(self.periode)
        EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=self.jour,
            nombre=18,
            enfants_par_animateur=8,
        )
        for prenom in ("Alice", "Bruno"):
            animateur = Animateur.objects.create(prenom=prenom, nom="Test")
            Affectation.objects.create(
                animateur=animateur,
                centre=self.centre,
                evenement=self.groupe,
                debut=timezone.make_aware(datetime.datetime.combine(self.jour, datetime.time.min)),
                fin=timezone.make_aware(
                    datetime.datetime.combine(self.jour + datetime.timedelta(days=1), datetime.time.min)
                ),
            )

    def test_page_direction_affiche_un_selecteur_de_semaine_sans_calendrier_ni_centre(self):
        response = self.client.get(reverse("accueil"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="dashboard-root"')
        self.assertContains(response, 'id="dashboard-period-nav"')
        self.assertNotContains(response, "Semaine concernée")
        self.assertContains(response, "État des centres")
        self.assertContains(response, "Actions rapides")
        self.assertNotContains(response, 'id="dashboard-calendar"')
        self.assertNotContains(response, 'id="dashboard-centre-select"')

    def test_api_calcule_les_indicateurs_de_toute_la_semaine(self):
        response = self.client.get(
            reverse("api_tableau_de_bord"),
            {"semaine": self.jour.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        lundi = data["semaine"][0]
        centre = data["centres_semaine"][0]

        self.assertEqual(data["periode"]["debut_semaine"], "2026-07-20")
        self.assertEqual(data["periode"]["fin_semaine"], "2026-07-24")
        self.assertEqual(len(data["semaine"]), 5)
        self.assertEqual(lundi["enfants"], 18)
        self.assertEqual(lundi["animateurs_affectes"], 2)
        self.assertEqual(lundi["animateurs_necessaires"], 3)
        self.assertEqual(lundi["manque_animateurs"], 1)
        self.assertEqual(lundi["etat"], "vigilance")
        self.assertEqual(data["indicateurs"]["enfants"], 18)
        self.assertEqual(centre["enfants"], 18)
        self.assertEqual(centre["moyenne_enfants_groupe_jour"], 18)
        self.assertEqual(centre["journees_animateurs"], 2)
        self.assertEqual(centre["journees_necessaires"], 11)
        self.assertEqual(data["indicateurs"]["problemes_moderes"], 1)
        self.assertEqual(centre["etat"], "danger")
        self.assertTrue(any("manque 1 animateur" in alerte["titre"].lower() for alerte in data["alertes"]))

    def test_api_compte_centres_ouverts_sejours_et_sorties_pour_chaque_semaine(self):
        Sejour.objects.create(
            nom="Séjour sur deux semaines",
            date_debut=datetime.date(2026, 7, 23),
            date_fin=datetime.date(2026, 7, 28),
        )
        Sejour.objects.create(
            nom="Séjour terminé",
            date_debut=datetime.date(2026, 7, 10),
            date_fin=datetime.date(2026, 7, 19),
        )
        Centre.objects.create(nom="Ancien lieu Séjour", code="ALS")
        Sortie.objects.create(nom="Piscine", date=datetime.date(2026, 7, 20), destination="Piscine")
        Sortie.objects.create(nom="Musée", date=datetime.date(2026, 7, 24), destination="Musée")
        Sortie.objects.create(nom="Forêt", date=datetime.date(2026, 7, 27), destination="Forêt")

        premiere = self.client.get(
            reverse("api_tableau_de_bord"), {"semaine": "2026-07-20"}
        ).json()
        suivante = self.client.get(
            reverse("api_tableau_de_bord"), {"semaine": "2026-07-27"}
        ).json()

        self.assertEqual(
            len([centre for centre in premiere["centres_semaine"] if centre["jours_ouverts"] > 0]),
            1,
        )
        self.assertEqual((premiere["nombre_sejours"], premiere["nombre_sorties"]), (1, 2))
        self.assertEqual((suivante["nombre_sejours"], suivante["nombre_sorties"]), (1, 1))

    def test_superutilisateur_force_puis_retablit_le_statut_sans_modifier_la_preparation(self):
        url = reverse("api_statut_preparation_semaine")
        avant = self.client.get(
            reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()}
        ).json()
        affectations_avant = Affectation.objects.count()
        effectifs_avant = list(EffectifEnfantsJour.objects.values_list("pk", "nombre"))

        force = self.client.post(
            url,
            data='{"semaine":"2026-07-20","forcer":true}',
            content_type="application/json",
        )

        self.assertEqual(force.status_code, 200)
        statut = StatutPreparationSemaine.objects.get(debut_semaine=self.jour)
        self.assertTrue(statut.est_force_prete)
        self.assertEqual(statut.modifie_par, self.compte_maitre)
        apres = self.client.get(
            reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()}
        ).json()
        self.assertTrue(apres["statut_preparation_manuel"]["est_force_prete"])
        self.assertEqual(apres["alertes"], avant["alertes"])
        self.assertEqual(apres["indicateurs"], avant["indicateurs"])
        self.assertEqual(Affectation.objects.count(), affectations_avant)
        self.assertEqual(list(EffectifEnfantsJour.objects.values_list("pk", "nombre")), effectifs_avant)

        self.client.logout()
        self.client.force_login(self.compte_maitre)
        persistant = self.client.get(
            reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()}
        ).json()
        self.assertTrue(persistant["statut_preparation_manuel"]["est_force_prete"])

        retour = self.client.post(
            url,
            data='{"semaine":"2026-07-20","forcer":false}',
            content_type="application/json",
        )
        self.assertEqual(retour.status_code, 200)
        statut.refresh_from_db()
        self.assertFalse(statut.est_force_prete)
        automatique = self.client.get(
            reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()}
        ).json()
        self.assertFalse(automatique["statut_preparation_manuel"]["est_force_prete"])

    def test_utilisateur_non_superuser_ne_peut_pas_forcer_le_statut(self):
        utilisateur = get_user_model().objects.create_user(
            username="sans-autorisation",
            password="secret-test",
        )
        self.client.force_login(utilisateur)

        response = self.client.post(
            reverse("api_statut_preparation_semaine"),
            data='{"semaine":"2026-07-20","forcer":true}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(StatutPreparationSemaine.objects.exists())

    def test_api_signale_tous_les_effectifs_non_renseignes_de_la_semaine(self):
        EffectifEnfantsJour.objects.filter(evenement=self.groupe, date=self.jour).delete()

        response = self.client.get(reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["indicateurs"]["effectifs_non_renseignes"], 5)
        self.assertEqual(data["centres_semaine"][0]["effectifs_non_renseignes"], 5)
        self.assertEqual(
            sum(1 for alerte in data["alertes"] if alerte["titre"] == "Effectif enfants non renseigné"),
            5,
        )

    def test_api_compte_un_animateur_flottant_dans_la_couverture_du_lieu(self):
        # Chaque groupe laisse un petit reliquat. Le flottant doit pouvoir les
        # couvrir ensemble, comme dans l'indicateur du planning.
        EffectifEnfantsJour.objects.filter(evenement=self.groupe, date=self.jour).update(nombre=18)
        autre_groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Élémentaires",
            effectif_cible=1,
            enfants_par_animateur_defaut=8,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        autre_groupe.periodes_scolaires.add(self.periode)
        EffectifEnfantsJour.objects.create(
            evenement=autre_groupe,
            date=self.jour,
            nombre=6,
            enfants_par_animateur=8,
        )
        flottant = Animateur.objects.create(prenom="Chloé", nom="Test")
        Affectation.objects.create(
            animateur=flottant,
            centre=self.centre,
            evenement=groupe_flottants_pour_centre(self.centre),
            debut=timezone.make_aware(datetime.datetime.combine(self.jour, datetime.time.min)),
            fin=timezone.make_aware(
                datetime.datetime.combine(self.jour + datetime.timedelta(days=1), datetime.time.min)
            ),
        )

        response = self.client.get(reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["semaine"][0]["animateurs_affectes"], 3)
        self.assertEqual(data["semaine"][0]["manque_animateurs"], 0)
        self.assertFalse(
            any(
                alerte["date"] == self.jour.isoformat() and "Il manque" in alerte["titre"]
                for alerte in data["alertes"]
            )
        )

    def test_api_alerte_sur_les_horaires_non_renseignes(self):
        response = self.client.get(reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()})

        alertes = [alerte for alerte in response.json()["alertes"] if alerte["titre"] == "Horaires non renseignés"]
        self.assertEqual(len(alertes), 5)
        self.assertIn("mode=affectations", alertes[0]["action_url"])

        for affectation in Affectation.objects.filter(evenement=self.groupe):
            HoraireAffectationJour.objects.create(
                affectation=affectation,
                date=self.jour,
                heure_arrivee="07:30",
                heure_depart="18:00",
            )
        response = self.client.get(reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()})
        alertes = [alerte for alerte in response.json()["alertes"] if alerte["titre"] == "Horaires non renseignés"]
        self.assertEqual(len(alertes), 4)

    def test_api_regroupe_toujours_tous_les_centres(self):
        autre = Centre.objects.create(nom="Saint-Forgeux", code="SF", couleur="#43a36f")
        autre_groupe = Evenement.objects.create(
            centre=autre,
            nom="Élémentaires",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        EffectifEnfantsJour.objects.create(
            evenement=autre_groupe,
            date=self.jour,
            nombre=40,
            enfants_par_animateur=8,
        )

        response = self.client.get(
            reverse("api_tableau_de_bord"),
            {
                "semaine": self.jour.isoformat(),
                "centre_id": self.centre.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["indicateurs"]["enfants"], 58)
        self.assertEqual(
            {centre["id"] for centre in data["centres_semaine"]},
            {self.centre.id, autre.id},
        )
        self.assertNotIn("centre_selectionne", data)
        self.assertNotIn("centres_filtres", data)

    def test_api_agrege_maternels_elementaires_et_animateurs_tous_lieux(self):
        autre_centre = Centre.objects.create(nom="Saint-Forgeux", code="SF", couleur="#43a36f")
        autre_maternelles = Evenement.objects.create(
            centre=autre_centre,
            nom="Maternelles",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        elementaires = Evenement.objects.create(
            centre=autre_centre,
            nom="Élémentaires",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        EffectifEnfantsJour.objects.create(
            evenement=autre_maternelles,
            date=self.jour,
            nombre=7,
            enfants_par_animateur=8,
        )
        EffectifEnfantsJour.objects.create(
            evenement=elementaires,
            date=self.jour,
            nombre=31,
            enfants_par_animateur=12,
        )

        alice = Animateur.objects.get(prenom="Alice")
        charlie = Animateur.objects.create(prenom="Charlie", nom="Test")
        for animateur in (alice, charlie):
            Affectation.objects.create(
                animateur=animateur,
                centre=autre_centre,
                evenement=elementaires,
                debut=timezone.make_aware(datetime.datetime.combine(self.jour, datetime.time.min)),
                fin=timezone.make_aware(
                    datetime.datetime.combine(self.jour + datetime.timedelta(days=1), datetime.time.min)
                ),
            )

        response = self.client.get(reverse("api_tableau_de_bord"), {"semaine": self.jour.isoformat()})

        self.assertEqual(response.status_code, 200)
        lundi = response.json()["semaine"][0]
        self.assertEqual(lundi["enfants_maternels"], 25)
        self.assertEqual(lundi["enfants_elementaires"], 31)
        self.assertEqual(lundi["animateurs_affectes"], 3)

    def test_detail_semaine_affiche_le_total_enfants_et_les_totaux_par_age(self):
        script = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text(encoding="utf-8")

        self.assertIn("<span>Total enfants</span><strong>${day.enfants}</strong>", script)
        self.assertIn("<span>Maternels</span>", script)
        self.assertIn("<span>Élémentaires</span>", script)
        self.assertIn("${day.animateurs_affectes}</strong>", script)
        self.assertNotIn("<span>Groupes</span><strong>${day.groupes_ouverts}</strong>", script)

    def test_une_date_au_milieu_de_la_semaine_est_ramenee_au_lundi(self):
        response = self.client.get(
            reverse("api_tableau_de_bord"),
            {"semaine": "2026-07-22"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["date_selectionnee"], "2026-07-20")
        self.assertEqual(
            [jour["date"] for jour in data["semaine"]],
            [
                "2026-07-20",
                "2026-07-21",
                "2026-07-22",
                "2026-07-23",
                "2026-07-24",
            ],
        )

    def test_vue_periode_reutilise_l_api_hebdomadaire_et_filtre_strictement_les_bornes(self):
        script = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text(encoding="utf-8")

        self.assertIn('String(period.debut || "") >= vacancesDebut', script)
        self.assertIn('String(period.fin || "") <= vacancesFin', script)
        self.assertIn("Promise.all(periods.map((period)", script)
        self.assertIn('new URLSearchParams({ semaine: period.debut })', script)
        self.assertIn('return apiFetch(`${apiUrl}?${query.toString()}`)', script)
        self.assertNotIn("api/periode-tableau-de-bord", script)

    def test_carte_periode_selectionne_la_semaine_et_conserve_la_persistance_historique(self):
        script = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text(encoding="utf-8")

        self.assertIn('data-dashboard-period-week="${escapeHtml(debut)}"', script)
        self.assertIn('selectedDate = card.dataset.dashboardPeriodWeek', script)
        self.assertIn('selectedDate = card.dataset.dashboardPeriodWeek;\n        updatePeriodSelection();', script)
        self.assertIn("WeekPicker.setPersistedDate(selectedDate)", script)
        self.assertIn("WeekPicker.setPersistedDate(selectedDate);\n            updatePeriodSelection();", script)
        self.assertIn("picker?.setActiveDate(data.periode.debut_semaine", script)
        self.assertIn("updateQuickActions(data)", script)
        self.assertIn('document.getElementById("action-effectifs").href = urlPlanning(debut, "effectifs")', script)
        self.assertIn('document.getElementById("action-affectations").href = urlPlanning(debut, "affectations")', script)

    def test_cartes_de_periode_sont_verticales_lisibles_et_adaptent_le_nombre_de_colonnes(self):
        script = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text(encoding="utf-8")
        css = (Path(settings.BASE_DIR) / "static/css/dashboard.css").read_text(encoding="utf-8")
        template = (Path(settings.BASE_DIR) / "templates/accueil.html").read_text(encoding="utf-8")
        rendu = script[script.index("function renderPeriodOverview"):script.index("async function loadPeriodOverview")]

        self.assertIn("dashboard-period-week-title", rendu)
        self.assertIn("dashboard-period-week-status", rendu)
        self.assertIn("Prête manuellement", script)
        self.assertIn("Marquer comme prête", script)
        self.assertIn("Revenir au statut automatique", script)
        self.assertIn("window.confirm", script)
        self.assertIn('${centres} centre${centres > 1 ? "s" : ""} ouvert', rendu)
        self.assertIn('${sejours} séjour${sejours > 1 ? "s" : ""}', rendu)
        self.assertIn('${sorties} sortie${sorties > 1 ? "s" : ""}', rendu)
        self.assertIn("dashboard-period-week-alerts", rendu)
        self.assertIn("Encadrement conforme", rendu)
        self.assertIn("Qualifications conformes", rendu)
        self.assertNotIn("dashboard-period-week-selected", rendu)
        self.assertNotIn("Effectifs enfants", rendu)
        self.assertNotIn("Effectifs à renseigner", rendu)
        self.assertNotIn("problèmes critiques", rendu)
        self.assertIn("grid-template-columns:repeat(auto-fit,200px)", css)
        self.assertIn("justify-content:start", css)
        self.assertIn("overflow:visible", css)
        self.assertIn('.dashboard-period-week[aria-pressed="true"]', css)
        self.assertIn("border:3px solid #123a78!important", css)
        self.assertIn("period-ready-4", template)
        self.assertIn("box-sizing:border-box", css)
        self.assertNotIn("overflow-x:auto", css)
        self.assertNotIn("min-height:168px", css)
