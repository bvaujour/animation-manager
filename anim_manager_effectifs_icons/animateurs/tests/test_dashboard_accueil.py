import datetime
from pathlib import Path

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, EffectifEnfantsJour, Evenement, HoraireAffectationJour
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

    def test_detail_semaine_affiche_les_totaux_par_age_sans_nombre_de_groupes(self):
        script = (Path(settings.BASE_DIR) / "static/js/dashboard.js").read_text(encoding="utf-8")

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
