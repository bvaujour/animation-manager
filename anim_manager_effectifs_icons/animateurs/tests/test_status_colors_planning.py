import datetime
from pathlib import Path

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Disponibilite, Qualification
from animateurs.services.status_colors import couleur_pastel_pour_fond, couleur_pour_statut
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_groupe


class CouleursStatutsPlanningTests(ConnexionTestCase):
    def setUp(self):
        self.statut = Qualification.objects.create(nom="Diplômé", est_statut=True)
        self.diplome = Qualification.objects.create(nom="BAFA", statut=self.statut, icone="diplome")
        self.animateur = Animateur.objects.create(
            prenom="Ambre",
            nom="Test",
        )
        self.animateur.qualifications.add(self.diplome)
        self.centre = Centre.objects.create(nom="Centre", code="CTR", couleur="#123456")
        self.groupe, _ = creer_groupe(self.centre, nom="Maternelles")
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

    def test_api_planning_animateurs_utilise_la_couleur_du_statut(self):
        response = self.client.get(
            reverse("api_animateurs"),
            {
                "include_affectations": "1",
                "format": "planning",
                "debut": "2026-07-06",
                "fin": "2026-07-13",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()[0]
        self.assertEqual(data["couleur"], couleur_pour_statut(self.statut))
        self.assertEqual(data["couleur_statut"], couleur_pour_statut(self.statut))
        self.assertEqual(data["statut_ids"], [self.statut.id])
        self.assertEqual(data["diplome_ids"], [self.diplome.id])
        self.assertEqual(data["statut_principal"]["nom"], "Diplômé")
        self.assertEqual(data["qualification_icones"], [{"id": self.diplome.id, "nom": "BAFA", "icone": "diplome"}])

    def test_affectation_fullcalendar_utilise_la_meme_couleur(self):
        response = self.client.get(
            reverse("api_planning"),
            {
                "centre_id": self.centre.id,
                "start": "2026-07-06",
                "end": "2026-07-13",
            },
        )

        self.assertEqual(response.status_code, 200)
        event = response.json()[0]
        self.assertEqual(event["backgroundColor"], couleur_pastel_pour_fond(couleur_pour_statut(self.statut)))
        self.assertEqual(event["borderColor"], couleur_pour_statut(self.statut))

    def test_api_qualifications_expose_la_couleur_du_statut(self):
        response = self.client.get(reverse("api_qualifications"))

        self.assertEqual(response.status_code, 200)
        par_id = {item["id"]: item for item in response.json()}
        self.assertEqual(par_id[self.statut.id]["couleur_statut"], couleur_pour_statut(self.statut))
        self.assertEqual(par_id[self.diplome.id]["couleur_statut"], couleur_pour_statut(self.statut))
        self.assertEqual(par_id[self.diplome.id]["icone"], "diplome")

    def test_interface_separe_statuts_et_diplomes_et_masque_les_affectes_par_defaut(self):
        template = (Path(settings.BASE_DIR) / "templates/planning.html").read_text(encoding="utf-8")
        partial = (Path(settings.BASE_DIR) / "templates/partials/_staff_filter.html").read_text(encoding="utf-8")
        script = (Path(settings.BASE_DIR) / "static/js/planning.js").read_text(encoding="utf-8")
        css = (Path(settings.BASE_DIR) / "static/css/planning.css").read_text(encoding="utf-8")
        gestion_script = (Path(settings.BASE_DIR) / "static/js/gestion.js").read_text(encoding="utf-8")
        employee_script = (Path(settings.BASE_DIR) / "static/js/animateurs.js").read_text(encoding="utf-8")

        self.assertIn('statuts_id="animateurs-filter-statuts"', template)
        self.assertIn('situation_id="animateurs-filter-situation"', template)
        self.assertNotIn("planning-staff-legend", template)
        self.assertIn("Encore plaçables", partial)
        self.assertIn('filtreSituationAnimateursValeur === "placable" && !encorePlacable', script)
        self.assertIn('filtreSituationAnimateursValeur === "disponible" && !disponible', script)
        self.assertIn('let filtreSituationAnimateursValeur = "placable";', script)
        self.assertIn('localStorage.removeItem("planning-filtre-situation")', script)
        self.assertIn('const situation = animateur.situation_semaine || {};', script)
        self.assertIn('situation.encore_placable === true', script)
        self.assertNotIn('affecte ? "A" : (disponible ? "D" : "—")', script)
        self.assertIn("qualification_icones", script)
        self.assertIn("qualif-icone", gestion_script)
        self.assertIn("grid-template-columns: var(--planning-sidebar-width) minmax(0, 1fr)", css)
        self.assertNotIn("planning-sidebar-resizer", css)
        self.assertNotIn("fiche-couleur-random", employee_script)
        self.assertNotIn('name="couleur" type="color"', employee_script)

    def test_api_permet_de_creer_et_modifier_une_icone_de_diplome(self):
        creation = self.client.post(
            reverse("api_qualifications"),
            data={
                "nom": "PSC1",
                "selectionnable_remplissage_auto": True,
                "est_statut": False,
                "statut_id": self.statut.id,
                "icone": "secours",
            },
            content_type="application/json",
        )
        self.assertEqual(creation.status_code, 201)
        qualification_id = creation.json()["id"]
        self.assertEqual(creation.json()["icone"], "secours")

        modification = self.client.patch(
            reverse("api_qualification_detail", args=[qualification_id]),
            data={"icone": "baignade"},
            content_type="application/json",
        )
        self.assertEqual(modification.status_code, 200)
        self.assertEqual(modification.json()["icone"], "baignade")
