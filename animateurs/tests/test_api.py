import datetime
import json
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Disponibilite,
    PreferenceCentre,
    Qualification,
)
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_groupe


class PlanningApiTests(ConnexionTestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Julie", nom="API")
        self.centre = Centre.objects.create(nom="Centre", code="CTR", couleur="#123456")
        self.groupe, _ = creer_groupe(
            self.centre,
            nom="Groupe principal",
            jours_ouverts=[0, 1, 2, 3, 4, 5],
        )
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
            "evenement_id": self.groupe.id,
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
                "evenement_id": self.groupe.id,
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
            "evenement_id": self.groupe.id,
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
            evenement=self.groupe,
            debut=lundi,
            fin=lundi + datetime.timedelta(days=1),
        )
        autre = Animateur.objects.create(prenom="Sam", nom="EDI")
        affectation_samedi = Affectation.objects.create(
            animateur=autre,
            centre=self.centre,
            evenement=self.groupe,
            debut=samedi,
            fin=samedi + datetime.timedelta(days=1),
        )

        response = self.client.delete(
            reverse("api_planning_plage") + "?debut=2026-07-06&fin=2026-07-11"
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Affectation.objects.filter(debut__date=datetime.date(2026, 7, 6)).exists())
        self.assertTrue(Affectation.objects.filter(pk=affectation_samedi.pk).exists())



class QualificationApiTests(ConnexionTestCase):
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


class QualificationDefaultTests(ConnexionTestCase):
    def test_nouvelle_qualification_non_selectionnable_par_defaut(self):
        response = self.client.post(
            reverse("api_qualifications"),
            data=json.dumps({"nom": "SB"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["selectionnable_remplissage_auto"])


class AnimateurCentresHierarchisesApiTests(ConnexionTestCase):
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

class AnimateurDetailApiTests(ConnexionTestCase):
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

    def test_creation_et_modification_informations_administratives(self):
        response = self.client.post(
            reverse("api_animateurs"),
            data=json.dumps({
                "prenom": "Lina",
                "nom": "Admin",
                "adresse": "12 rue des Écoles\n42370 Saint-Haon",
                "numero_securite_sociale": "2 06 07 42 123 456 78",
                "paie_jour": "65,50",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["adresse"], "12 rue des Écoles\n42370 Saint-Haon")
        self.assertEqual(data["numero_securite_sociale"], "2 06 07 42 123 456 78")
        self.assertEqual(data["paie_jour"], "65.50")

        response = self.client.patch(
            reverse("api_animateur_detail", args=[data["id"]]),
            data=json.dumps({"paie_jour": "70.00", "adresse": "Nouvelle adresse"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["paie_jour"], "70.00")
        self.assertEqual(response.json()["adresse"], "Nouvelle adresse")

    def test_refuse_paie_jour_negative(self):
        response = self.client.patch(
            reverse("api_animateur_detail", args=[self.animateur.id]),
            data=json.dumps({"paie_jour": "-1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class GestionEtDisponibiliteApiTests(ConnexionTestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Alice", nom="Martin")
        self.disponibilite = Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 8, 3),
            fin=datetime.date(2026, 8, 7),
        )

    def test_employees_are_separate_from_management(self):
        response = self.client.get("/gestion/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lieux et groupes")
        self.assertNotContains(response, "Ajouter un salarié")
        self.assertNotContains(response, 'data-tab="salaries"')

        response = self.client.get("/employes/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salariés")
        self.assertContains(response, "Ajouter un salarié")
        self.assertContains(response, "employees-workspace")
        self.assertContains(response, "employee-editor")

    def test_old_employee_pages_redirect_to_master_detail_view(self):
        detail = self.client.get(f"/employes/{self.animateur.id}/")
        creation = self.client.get("/employes/nouveau/")

        self.assertRedirects(
            detail,
            f"/employes/?salarie={self.animateur.id}",
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            creation,
            "/employes/?nouveau=1",
            fetch_redirect_response=False,
        )

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


class PlanningPageLayoutTests(ConnexionTestCase):
    def test_planning_page_uses_fixed_viewport_layout(self):
        response = self.client.get("/planning/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="app-body page-planning"')
        self.assertContains(response, 'id="animateurs-panel"')
        self.assertContains(response, 'id="planning-period-nav"')
        self.assertContains(response, 'id="calendars-container"')


    def test_planning_page_exposes_scroll_layout(self):
        response = self.client.get("/planning/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="app-body page-planning"', html=False)
        self.assertContains(response, 'id="calendars-container"', html=False)
        self.assertContains(response, 'id="planning-actions"', html=False)


class AnimateursListPerformanceTests(ConnexionTestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="Centre principal",
            code="CP",
            couleur="#123456",
        )
        self.qualification = Qualification.objects.create(nom="BAFA")

    def creer_animateurs(self, nombre):
        for index in range(nombre):
            animateur = Animateur.objects.create(
                prenom=f"Prénom {index:02d}",
                nom="Test",
            )
            animateur.qualifications.add(self.qualification)
            PreferenceCentre.objects.create(
                animateur=animateur,
                centre=self.centre,
                est_prefere=True,
            )
            Disponibilite.objects.create(
                animateur=animateur,
                debut=datetime.date(2027, 7, 1),
                fin=datetime.date(2027, 7, 31),
            )

    def test_liste_utilise_un_nombre_fixe_de_requetes(self):
        self.creer_animateurs(25)

        with CaptureQueriesContext(connection) as contexte:
            response = self.client.get(reverse("api_animateurs"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 25)
        # Le but est de garantir l'absence de N+1 : le nombre de requêtes doit
        # rester constant quel que soit le nombre d'animateurs. Sur les 9, deux
        # sont le coût fixe de l'authentification (session + utilisateur) apporté
        # par ConnexionTestCase ; les autres chargent les relations, dont la
        # nouvelle table d'affinités animateur-groupe.
        self.assertLessEqual(
            len(contexte),
            9,
            f"La liste a effectué {len(contexte)} requêtes au lieu d'un nombre fixe.",
        )

    def test_consulter_la_liste_ne_modifie_pas_les_disponibilites(self):
        animateur = Animateur.objects.create(prenom="Aline", nom="Historique")
        disponibilite = Disponibilite.objects.create(
            animateur=animateur,
            debut=datetime.date(2020, 1, 1),
            fin=datetime.date(2020, 1, 5),
        )

        response = self.client.get(reverse("api_animateurs"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Disponibilite.objects.filter(pk=disponibilite.pk).exists())

    def test_liste_est_classee_par_prenom_puis_nom(self):
        Animateur.objects.create(prenom="Zoé", nom="Alpha")
        Animateur.objects.create(prenom="Alice", nom="Zulu")
        Animateur.objects.create(prenom="Alice", nom="Beta")

        response = self.client.get(reverse("api_animateurs"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(item["prenom"], item["nom"]) for item in response.json()],
            [("Alice", "Beta"), ("Alice", "Zulu"), ("Zoé", "Alpha")],
        )

class AnimateursApiOptionsTests(ConnexionTestCase):
    @mock.patch("animateurs.views.synchroniser_affinites_groupes")
    def test_liste_avec_affectations_reste_en_lecture_seule(self, synchroniser):
        Animateur.objects.create(prenom="Aline", nom="Lecture seule")

        response = self.client.get(
            reverse("api_animateurs"),
            {"include_affectations": "1"},
        )

        self.assertEqual(response.status_code, 200)
        synchroniser.assert_not_called()

    def test_liste_avec_prefetch_des_affectations(self):
        Animateur.objects.create(prenom="Ambre", nom="Test")

        response = self.client.get(
            reverse("api_animateurs"),
            {"include_affectations": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_liste_expose_le_nombre_de_jours_travailles_par_groupe(self):
        animateur = Animateur.objects.create(prenom="Ambre", nom="Historique")
        centre = Centre.objects.create(nom="Centre historique", code="HIS", couleur="#123456")
        groupe, _ = creer_groupe(centre, nom="Maternelles historique")
        debut = timezone.make_aware(datetime.datetime(2026, 7, 13))
        Affectation.objects.create(
            animateur=animateur,
            centre=centre,
            evenement=groupe,
            debut=debut,
            fin=debut + datetime.timedelta(days=2),
        )

        response = self.client.get(
            reverse("api_animateurs"),
            {"include_affectations": "1"},
        )

        self.assertEqual(response.status_code, 200)
        donnees = response.json()[0]
        historique = donnees["historique_groupes"]
        affinites = donnees["affinites_groupes"]
        self.assertEqual(len(historique), 1)
        self.assertEqual(historique[0]["groupe_nom"], "Maternelles historique")
        self.assertEqual(historique[0]["jours_travailles"], 2)
        self.assertEqual(affinites[0]["score_affinite"], 2)
