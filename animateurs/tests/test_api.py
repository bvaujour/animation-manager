import datetime
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Disponibilite


class PlanningApiTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Julie", nom="API")
        self.centre = Centre.objects.create(nom="Centre", code="CTR", couleur="#123456")
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 11),
        )

    def test_creation_affectation_et_refus_doublon(self):
        debut = "2026-07-06"
        payload = {
            "animateur_id": self.animateur.id,
            "centre_id": self.centre.id,
            "debut": debut,
            "fin": "2026-07-07",
        }
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_refuse_creation_sans_disponibilite(self):
        self.animateur.disponibilites.all().delete()
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps({
                "animateur_id": self.animateur.id,
                "centre_id": self.centre.id,
                "debut": "2026-07-06",
                "fin": "2026-07-07",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Affectation.objects.exists())

    def test_creation_manuelle_autorisee_le_samedi(self):
        payload = {
            "animateur_id": self.animateur.id,
            "centre_id": self.centre.id,
            "debut": "2026-07-11",
            "fin": "2026-07-12",
        }

        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Affectation.objects.filter(
                animateur=self.animateur,
                debut__date=datetime.date(2026, 7, 11),
            ).exists()
        )

    def test_vidage_semaine_preserve_le_samedi(self):
        lundi = timezone.make_aware(datetime.datetime(2026, 7, 6))
        samedi = timezone.make_aware(datetime.datetime(2026, 7, 11))
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            debut=lundi,
            fin=lundi + datetime.timedelta(days=1),
        )
        autre = Animateur.objects.create(prenom="Sam", nom="EDI")
        affectation_samedi = Affectation.objects.create(
            animateur=autre,
            centre=self.centre,
            debut=samedi,
            fin=samedi + datetime.timedelta(days=1),
        )

        response = self.client.delete(
            reverse("api_planning_plage") + "?debut=2026-07-06&fin=2026-07-11"
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Affectation.objects.filter(debut__date=datetime.date(2026, 7, 6)).exists())
        self.assertTrue(Affectation.objects.filter(pk=affectation_samedi.pk).exists())



class QualificationApiTests(TestCase):
    def test_creation_et_modification_visibilite_auto(self):
        response = self.client.post(
            reverse("api_qualifications"),
            data=json.dumps({
                "nom": "BAFA",
                "selectionnable_remplissage_auto": False,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertFalse(data["selectionnable_remplissage_auto"])

        qualification_id = data["id"]
        response = self.client.patch(
            reverse("api_qualification_detail", args=[qualification_id]),
            data=json.dumps({
                "nom": "BAFA confirmé",
                "selectionnable_remplissage_auto": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["nom"], "BAFA confirmé")
        self.assertTrue(data["selectionnable_remplissage_auto"])

    def test_liste_expose_visibilite_auto(self):
        from animateurs.models import Qualification

        Qualification.objects.create(
            nom="PSC1",
            selectionnable_remplissage_auto=False,
        )
        response = self.client.get(reverse("api_qualifications"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["selectionnable_remplissage_auto"], False)


class QualificationDefaultTests(TestCase):
    def test_nouvelle_qualification_non_selectionnable_par_defaut(self):
        response = self.client.post(
            reverse("api_qualifications"),
            data=json.dumps({"nom": "SB"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["selectionnable_remplissage_auto"])


class AnimateurCentresHierarchisesApiTests(TestCase):
    def test_creation_avec_centre_prefere_et_secondaires(self):
        from animateurs.models import Centre

        prefere = Centre.objects.create(nom="Préféré", code="PREF", couleur="#112233")
        secondaire = Centre.objects.create(nom="Secondaire", code="SEC", couleur="#445566")

        response = self.client.post(
            reverse("api_animateurs"),
            data=json.dumps({
                "prenom": "Julie",
                "nom": "Test",
                "centre_prefere": prefere.id,
                "centres_secondaires": [secondaire.id],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["centre_prefere"]["id"], prefere.id)
        self.assertEqual([c["id"] for c in data["centres_secondaires"]], [secondaire.id])
        self.assertEqual([c["id"] for c in data["centres_autorises"]], [prefere.id, secondaire.id])

class AnimateurDetailApiTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Alice", nom="Couleur")

    def test_modification_couleur_valide(self):
        response = self.client.patch(
            reverse("api_animateur_detail", args=[self.animateur.id]),
            data=json.dumps({"couleur": "#123ABC"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.animateur.refresh_from_db()
        self.assertEqual(self.animateur.couleur, "#123ABC")

    def test_refuse_couleur_invalide(self):
        response = self.client.patch(
            reverse("api_animateur_detail", args=[self.animateur.id]),
            data=json.dumps({"couleur": "rouge"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class EvenementPageAndDisponibiliteApiTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Alice", nom="Martin")
        self.disponibilite = Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 8, 3),
            fin=datetime.date(2026, 8, 7),
        )

    def test_old_evenement_page_redirects_to_gestion_salaries(self):
        response = self.client.get("/evenement/")
        self.assertRedirects(response, "/gestion/?onglet=salaries", fetch_redirect_response=False)

    def test_old_equipe_page_redirects_to_gestion_salaries(self):
        response = self.client.get("/equipe/")
        self.assertRedirects(response, "/gestion/?onglet=salaries", fetch_redirect_response=False)

    def test_gestion_page_contains_employee_management(self):
        response = self.client.get("/gestion/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salariés")
        self.assertContains(response, "Lieux et événements")
        self.assertContains(response, "Ajouter un salarié")

    def test_update_disponibilite(self):
        response = self.client.patch(
            f"/api/animateurs/{self.animateur.id}/disponibilites/{self.disponibilite.id}/",
            data=json.dumps({"debut": "2026-08-04", "fin": "2026-08-08"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.disponibilite.refresh_from_db()
        self.assertEqual(self.disponibilite.debut, datetime.date(2026, 8, 4))
        self.assertEqual(self.disponibilite.fin, datetime.date(2026, 8, 8))

    def test_delete_disponibilite(self):
        response = self.client.delete(
            f"/api/animateurs/{self.animateur.id}/disponibilites/{self.disponibilite.id}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Disponibilite.objects.filter(pk=self.disponibilite.id).exists())


class PlanningPageLayoutTests(TestCase):
    def test_planning_page_uses_fixed_viewport_layout(self):
        response = self.client.get("/planning/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="page-planning"')
        self.assertContains(response, 'id="animateurs-panel"')
        self.assertContains(response, 'id="planning-period-nav"')
        self.assertContains(response, 'id="calendars-container"')


    def test_planning_page_exposes_scroll_layout(self):
        response = self.client.get("/planning/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="page-planning"', html=False)
        self.assertContains(response, 'id="calendars-container"', html=False)
        self.assertContains(response, 'id="planning-actions"', html=False)
