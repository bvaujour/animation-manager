import datetime

from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, EffectifEnfantsJour, Evenement
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_periode


class DashboardAccueilTests(ConnexionTestCase):
    def setUp(self):
        self.jour = datetime.date(2026, 7, 20)
        self.periode = creer_periode(debut=self.jour, nom="Été 2026 — Semaine 3")
        self.centre = Centre.objects.create(
            nom="La Pacaudière", code="LP", couleur="#4f7bc8"
        )
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
                fin=timezone.make_aware(datetime.datetime.combine(self.jour + datetime.timedelta(days=1), datetime.time.min)),
            )

    def test_page_direction_charge_le_tableau_de_bord(self):
        response = self.client.get(reverse("accueil"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="dashboard-root"')
        self.assertContains(response, "css/dashboard.css")
        self.assertContains(response, "js/dashboard.js")
        self.assertContains(response, "État des centres")
        self.assertContains(response, "Actions rapides")

    def test_api_calcule_enfants_encadrement_et_manque(self):
        response = self.client.get(
            reverse("api_tableau_de_bord"),
            {"date": self.jour.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["jour"]["enfants"], 18)
        self.assertEqual(data["jour"]["animateurs_affectes"], 2)
        self.assertEqual(data["jour"]["animateurs_necessaires"], 3)
        self.assertEqual(data["jour"]["manque_animateurs"], 1)
        self.assertEqual(data["jour"]["etat"], "danger")
        self.assertEqual(data["jour"]["centres"][0]["etat_libelle"], "Manque 1 anim.")
        self.assertTrue(any("manque 1 animateur" in alerte["titre"].lower() for alerte in data["alertes"]))
        self.assertEqual(data["indicateurs"]["enfants"], 18)

    def test_api_signale_un_effectif_non_renseigne(self):
        EffectifEnfantsJour.objects.filter(evenement=self.groupe, date=self.jour).delete()

        response = self.client.get(reverse("api_tableau_de_bord"), {"date": self.jour.isoformat()})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["jour"]["effectifs_non_renseignes"], 1)
        self.assertTrue(any(alerte["niveau"] == "vigilance" for alerte in data["alertes"]))

    def test_filtre_centre_ne_conserve_que_le_centre_demande(self):
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
            {"date": self.jour.isoformat(), "centre_id": self.centre.id},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["centre_selectionne"], self.centre.id)
        self.assertEqual(data["jour"]["enfants"], 18)
        self.assertEqual([centre["id"] for centre in data["jour"]["centres"]], [self.centre.id])
        self.assertEqual(len(data["centres_filtres"]), 2)

    def test_api_refuse_un_centre_inexistant(self):
        response = self.client.get(
            reverse("api_tableau_de_bord"),
            {"date": self.jour.isoformat(), "centre_id": 999999},
        )
        self.assertEqual(response.status_code, 404)
