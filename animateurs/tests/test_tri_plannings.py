import json

from django.urls import reverse

from animateurs.models import Centre, Evenement
from animateurs.tests.base import ConnexionTestCase


class OrdreAffichagePlanningApiTests(ConnexionTestCase):
    def setUp(self):
        self.centre_a = Centre.objects.create(
            nom="Alpha",
            code="ALP",
            couleur="#111111",
            ordre=0,
        )
        self.centre_b = Centre.objects.create(
            nom="Bravo",
            code="BRA",
            couleur="#222222",
            ordre=1,
        )
        self.centre_c = Centre.objects.create(
            nom="Charlie",
            code="CHA",
            couleur="#333333",
            ordre=2,
        )
        self.evenement_a = Evenement.objects.create(
            centre=self.centre_a,
            nom="Groupe principal",
            effectif_cible=1,
            ordre=0,
        )

    def test_api_centres_respecte_ordre_enregistre(self):
        response = self.client.get(reverse("api_centres"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [centre["id"] for centre in response.json()],
            [self.centre_a.id, self.centre_b.id, self.centre_c.id],
        )
        self.assertEqual([centre["ordre"] for centre in response.json()], [0, 1, 2])

    def test_reordonner_centres(self):
        nouvel_ordre = [self.centre_c.id, self.centre_a.id, self.centre_b.id]
        response = self.client.post(
            reverse("api_centres_reordonner"),
            data=json.dumps({"centre_ids": nouvel_ordre}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.json())

        self.assertEqual(
            list(Centre.objects.values_list("id", flat=True)),
            nouvel_ordre,
        )
        self.centre_c.refresh_from_db()
        self.centre_a.refresh_from_db()
        self.centre_b.refresh_from_db()
        self.assertEqual(
            [self.centre_c.ordre, self.centre_a.ordre, self.centre_b.ordre],
            [0, 1, 2],
        )

    def test_refuse_liste_centres_incomplete(self):
        response = self.client.post(
            reverse("api_centres_reordonner"),
            data=json.dumps({"centre_ids": [self.centre_a.id, self.centre_b.id]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("incomplète", response.json()["error"])

    def test_refuse_identifiant_centre_duplique(self):
        response = self.client.post(
            reverse("api_centres_reordonner"),
            data=json.dumps({
                "centre_ids": [self.centre_a.id, self.centre_a.id, self.centre_c.id]
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_nouveau_centre_cree_par_api_est_ajoute_a_la_fin(self):
        response = self.client.post(
            reverse("api_centres"),
            data=json.dumps({
                "nom": "Delta",
                "code": "DEL",
                "couleur": "#444444",
                "effectif_cible": 1,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        nouveau = Centre.objects.get(pk=response.json()["id"])
        self.assertEqual(nouveau.ordre, 3)
        self.assertEqual(list(Centre.objects.values_list("id", flat=True))[-1], nouveau.id)

    def test_ordre_evenements_modifie_depuis_planning_reutilise_api_existante(self):
        evenement_a = self.evenement_a
        evenement_a.nom = "Maternelles"
        evenement_a.save(update_fields=["nom"])
        evenement_b = Evenement.objects.create(
            centre=self.centre_a,
            nom="Élémentaires",
            effectif_cible=1,
            ordre=1,
        )
        evenement_c = Evenement.objects.create(
            centre=self.centre_a,
            nom="CM2",
            effectif_cible=1,
            ordre=2,
        )

        nouvel_ordre = [evenement_c.id, evenement_a.id, evenement_b.id]
        response = self.client.post(
            reverse("api_groupes_reordonner", args=[self.centre_a.id]),
            data=json.dumps({"evenement_ids": nouvel_ordre}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(
            list(self.centre_a.evenements.values_list("id", flat=True)),
            nouvel_ordre,
        )

    def test_page_planning_propose_la_disposition_libre_des_centres(self):
        response = self.client.get(reverse("planning"))
        self.assertContains(response, 'id="planning-centres-toolbar"')
        self.assertContains(response, 'id="planning-add-centre-menu"')
        self.assertContains(response, 'id="calendars-container"')
        self.assertNotContains(response, 'id="planning-layout-one-row"')
        self.assertNotContains(response, 'id="planning-layout-stacked"')
        self.assertNotContains(response, "planning-sort-hint")
        self.assertNotContains(response, "Sortable.min.js")
