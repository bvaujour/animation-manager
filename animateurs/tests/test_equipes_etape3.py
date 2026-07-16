import datetime
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Disponibilite, Evenement
from animateurs.services.affectations import creer_affectation, modifier_affectation


class PlanningManuelParEvenementApiTests(TestCase):
    def setUp(self):
        self.centre_a = Centre.objects.create(
            nom="La Pacaudière",
            code="LP",
            couleur="#d97706",
            effectif_cible=2,
        )
        self.centre_b = Centre.objects.create(
            nom="Saint-Martin",
            code="SM",
            couleur="#2563eb",
            effectif_cible=1,
        )
        self.evenement_a1 = self.centre_a.evenements.get()
        self.evenement_a1.nom = "Maternelles"
        self.evenement_a1.save(update_fields=["nom"])
        self.evenement_a2 = Evenement.objects.create(
            centre=self.centre_a,
            nom="Élémentaires",
            effectif_cible=2,
            ordre=1,
        )
        self.evenement_b1 = self.centre_b.evenements.get()
        self.evenement_b1.nom = "CM2"
        self.evenement_b1.save(update_fields=["nom"])

        self.animateur = Animateur.objects.create(prenom="Julie", nom="Test")
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )

    def _creer(self, evenement, date="2026-07-06"):
        return self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps({
                "animateur_id": self.animateur.id,
                "centre_id": evenement.centre_id,
                "evenement_id": evenement.id,
                "debut": date,
                "fin": (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat(),
            }),
            content_type="application/json",
        )

    def test_creation_explicitement_dans_une_evenement(self):
        response = self._creer(self.evenement_a2)
        self.assertEqual(response.status_code, 201, response.json())

        affectation = Affectation.objects.get()
        self.assertEqual(affectation.evenement, self.evenement_a2)
        self.assertEqual(affectation.centre, self.centre_a)
        self.assertEqual(response.json()["extendedProps"]["evenement_id"], self.evenement_a2.id)
        self.assertEqual(response.json()["extendedProps"]["evenement_nom"], "Élémentaires")

    def test_refuse_creation_dans_une_evenement_inactive(self):
        self.evenement_a2.active = False
        self.evenement_a2.save(update_fields=["active"])
        response = self._creer(self.evenement_a2)
        self.assertEqual(response.status_code, 409)
        self.assertIn("inactive", response.json()["error"])

    def test_refuse_evenement_et_centre_incoherents(self):
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps({
                "animateur_id": self.animateur.id,
                "centre_id": self.centre_b.id,
                "evenement_id": self.evenement_a2.id,
                "debut": "2026-07-06",
                "fin": "2026-07-07",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Affectation.objects.exists())

    def test_filtre_planning_par_evenement(self):
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        autre_animateur = Animateur.objects.create(prenom="Ambre", nom="Autre")
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre_a,
            evenement=self.evenement_a1,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )
        Affectation.objects.create(
            animateur=autre_animateur,
            centre=self.centre_a,
            evenement=self.evenement_a2,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

        response = self.client.get(
            reverse("api_planning"),
            {"evenement_id": self.evenement_a2.id, "start": "2026-07-06", "end": "2026-07-07"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["extendedProps"]["evenement_id"], self.evenement_a2.id)

    def test_deplacement_vers_une_autre_evenement_du_meme_centre(self):
        response = self._creer(self.evenement_a1)
        affectation_id = response.json()["id"]

        response = self.client.patch(
            reverse("api_affectation_detail", args=[affectation_id]),
            data=json.dumps({
                "centre_id": self.centre_a.id,
                "evenement_id": self.evenement_a2.id,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        affectation = Affectation.objects.get(pk=affectation_id)
        self.assertEqual(affectation.evenement, self.evenement_a2)
        self.assertEqual(affectation.centre, self.centre_a)


    def test_matin_et_soir_non_chevauchants_acceptent_le_meme_animateur(self):
        matin = Evenement.objects.create(
            centre=self.centre_a,
            nom="Matin",
            effectif_cible=1,
            ordre=2,
            heure_debut=datetime.time(7, 30),
            heure_fin=datetime.time(12, 0),
        )
        soir = Evenement.objects.create(
            centre=self.centre_a,
            nom="Soir",
            effectif_cible=1,
            ordre=3,
            heure_debut=datetime.time(14, 0),
            heure_fin=datetime.time(18, 30),
        )

        premiere = self._creer(matin)
        seconde = self._creer(soir)

        self.assertEqual(premiere.status_code, 201, premiere.json())
        self.assertEqual(seconde.status_code, 201, seconde.json())
        self.assertEqual(Affectation.objects.filter(animateur=self.animateur).count(), 2)

    def test_deux_evenements_horaires_qui_se_chevauchent_sont_refusees(self):
        matin = Evenement.objects.create(
            centre=self.centre_a,
            nom="Matin bis",
            effectif_cible=1,
            ordre=2,
            heure_debut=datetime.time(8, 0),
            heure_fin=datetime.time(13, 0),
        )
        midi = Evenement.objects.create(
            centre=self.centre_a,
            nom="Midi",
            effectif_cible=1,
            ordre=3,
            heure_debut=datetime.time(12, 0),
            heure_fin=datetime.time(16, 0),
        )

        self.assertEqual(self._creer(matin).status_code, 201)
        response = self._creer(midi)
        self.assertEqual(response.status_code, 409)
        self.assertIn("chevauche", response.json()["error"])

    def test_evenement_journee_entre_en_conflit_avec_une_evenement_horaire(self):
        matin = Evenement.objects.create(
            centre=self.centre_a,
            nom="Petit matin",
            effectif_cible=1,
            ordre=2,
            heure_debut=datetime.time(7, 30),
            heure_fin=datetime.time(10, 0),
        )

        self.assertEqual(self._creer(matin).status_code, 201)
        response = self._creer(self.evenement_a2)
        self.assertEqual(response.status_code, 409)

    def test_deplacement_vers_une_evenement_d_un_autre_centre(self):
        response = self._creer(self.evenement_a1)
        affectation_id = response.json()["id"]

        response = self.client.patch(
            reverse("api_affectation_detail", args=[affectation_id]),
            data=json.dumps({
                "centre_id": self.centre_b.id,
                "evenement_id": self.evenement_b1.id,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        affectation = Affectation.objects.get(pk=affectation_id)
        self.assertEqual(affectation.evenement, self.evenement_b1)
        self.assertEqual(affectation.centre, self.centre_b)


class PlanningManuelParEvenementServiceTests(TestCase):
    def test_modifier_affectation_avec_evenement_met_a_jour_le_centre(self):
        centre_a = Centre.objects.create(nom="A", code="A3", couleur="#111111")
        centre_b = Centre.objects.create(nom="B", code="B3", couleur="#222222")
        evenement_b = centre_b.evenements.get()
        animateur = Animateur.objects.create(prenom="Gaël", nom="Test")
        Disponibilite.objects.create(
            animateur=animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 6),
        )
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        affectation = creer_affectation(
            animateur=animateur,
            centre=centre_a,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

        modifier_affectation(affectation, evenement=evenement_b)
        affectation.refresh_from_db()
        self.assertEqual(affectation.evenement, evenement_b)
        self.assertEqual(affectation.centre, centre_b)


class PlanningPageEvenementStructureTests(TestCase):
    def test_page_charge_le_script_de_planning_par_evenement(self):
        response = self.client.get(reverse("planning"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="calendars-container"')
        self.assertContains(response, "/static/js/planning.")
