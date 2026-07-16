import datetime
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Disponibilite, Evenement


class EvenementGestionApiTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="Centre événements",
            code="EQP",
            couleur="#123456",
            effectif_cible=2,
        )
        self.evenement_principale = self.centre.evenements.get()

    def test_liste_evenements_du_centre(self):
        response = self.client.get(reverse("api_evenements", args=[self.centre.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["nom"], "Événement principale")
        self.assertEqual(data[0]["effectif_cible"], 2)

    def test_creation_evenement_et_synchronisation_effectif_centre(self):
        response = self.client.post(
            reverse("api_evenements", args=[self.centre.id]),
            data=json.dumps({
                "nom": "Maternelles",
                "effectif_cible": 3,
                "active": True,
                "heure_debut": "08:00",
                "heure_fin": "18:00",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        self.centre.refresh_from_db()
        self.assertEqual(self.centre.effectif_cible, 5)
        evenement = Evenement.objects.get(nom="Maternelles")
        self.assertEqual(evenement.heure_debut, datetime.time(8, 0))
        self.assertEqual(evenement.heure_fin, datetime.time(18, 0))

    def test_modification_evenement(self):
        evenement = Evenement.objects.create(
            centre=self.centre,
            nom="Élémentaires",
            effectif_cible=2,
            ordre=1,
        )
        response = self.client.patch(
            reverse("api_evenement_detail", args=[evenement.id]),
            data=json.dumps({
                "nom": "CM2",
                "effectif_cible": 4,
                "active": True,
                "heure_debut": None,
                "heure_fin": None,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        evenement.refresh_from_db()
        self.assertEqual(evenement.nom, "CM2")
        self.assertEqual(evenement.effectif_cible, 4)
        self.centre.refresh_from_db()
        self.assertEqual(self.centre.effectif_cible, 6)

    def test_refuse_horaires_incomplets(self):
        response = self.client.post(
            reverse("api_evenements", args=[self.centre.id]),
            data=json.dumps({
                "nom": "Matin",
                "effectif_cible": 1,
                "heure_debut": "07:30",
                "heure_fin": None,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("ensemble", response.json()["error"])

    def test_refuse_nom_duplique_dans_un_centre(self):
        response = self.client.post(
            reverse("api_evenements", args=[self.centre.id]),
            data=json.dumps({"nom": "Événement principale", "effectif_cible": 1}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, (400, 409))

    def test_refuse_suppression_derniere_evenement(self):
        response = self.client.delete(
            reverse("api_evenement_detail", args=[self.evenement_principale.id])
        )
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Evenement.objects.filter(pk=self.evenement_principale.id).exists())

    def test_suppression_evenement_sans_affectation(self):
        autre = Evenement.objects.create(
            centre=self.centre,
            nom="Autre",
            effectif_cible=1,
            ordre=1,
        )
        response = self.client.delete(reverse("api_evenement_detail", args=[autre.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Evenement.objects.filter(pk=autre.id).exists())

    def test_refuse_suppression_evenement_avec_affectation(self):
        autre = Evenement.objects.create(
            centre=self.centre,
            nom="Maternelles",
            effectif_cible=1,
            ordre=1,
        )
        animateur = Animateur.objects.create(prenom="Julie", nom="Test")
        Disponibilite.objects.create(
            animateur=animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 6),
        )
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        Affectation.objects.create(
            animateur=animateur,
            centre=self.centre,
            evenement=autre,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )
        response = self.client.delete(reverse("api_evenement_detail", args=[autre.id]))
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Evenement.objects.filter(pk=autre.id).exists())

    def test_reordonner_evenements(self):
        seconde = Evenement.objects.create(
            centre=self.centre,
            nom="Seconde",
            effectif_cible=1,
            ordre=1,
        )
        troisieme = Evenement.objects.create(
            centre=self.centre,
            nom="Troisième",
            effectif_cible=1,
            ordre=2,
        )
        response = self.client.post(
            reverse("api_evenements_reordonner", args=[self.centre.id]),
            data=json.dumps({
                "evenement_ids": [troisieme.id, self.evenement_principale.id, seconde.id]
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(
            list(self.centre.evenements.order_by("ordre").values_list("id", flat=True)),
            [troisieme.id, self.evenement_principale.id, seconde.id],
        )

    def test_refuse_desactivation_derniere_evenement_active(self):
        response = self.client.patch(
            reverse("api_evenement_detail", args=[self.evenement_principale.id]),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.evenement_principale.refresh_from_db()
        self.assertTrue(self.evenement_principale.active)


class GestionEvenementPageTests(TestCase):
    def test_page_gestion_annonce_les_evenements(self):
        response = self.client.get(reverse("gestion"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "centres, leurs événements")
