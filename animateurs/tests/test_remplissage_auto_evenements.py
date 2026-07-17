import datetime
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from animateurs.models import (
    Affectation,
    Animateur,
    BesoinQualification,
    Centre,
    Disponibilite,
    Evenement,
    PreferenceCentre,
    Qualification,
)
from animateurs.tests.factories import creer_periode
from animateurs.services.planning_solver import generer_planning_auto
from animateurs.services.serializers import evenement_to_dict


class ConfigurationEvenementRemplissageAutoTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="La Pacaudière",
            code="PAC",
            couleur="#123456",
        )
        self.periode = creer_periode(debut=datetime.date(2026, 7, 6), nom="Semaine auto")
        self.evenement = Evenement.objects.create(
            centre=self.centre,
            nom="Maternelles",
            debut=self.periode.debut,
            fin=self.periode.fin,
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.evenement.periodes_scolaires.add(self.periode)
        self.bafa = Qualification.objects.create(
            nom="BAFA",
            selectionnable_remplissage_auto=False,
        )
        BesoinQualification.objects.create(
            evenement=self.evenement,
            qualification=self.bafa,
            nombre_minimum=1,
        )
        self.animateur = Animateur.objects.create(prenom="Sam", nom="Sans BAFA")
        PreferenceCentre.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            est_prefere=True,
        )
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )

    def test_api_evenement_fournit_les_qualifications_enregistrees(self):
        data = evenement_to_dict(self.evenement)
        self.assertEqual(data["qualifications_requises"], {str(self.bafa.id): 1})

    def test_solveur_utilise_le_besoin_enregistre(self):
        data, status = generer_planning_auto({"debut": "2026-07-06"})
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertFalse(Affectation.objects.exists())

    def test_une_configuration_temporaire_envoyee_est_ignoree(self):
        data, status = generer_planning_auto({
            "debut": "2026-07-06",
            "evenements": {
                str(self.evenement.id): {
                    "effectif": 1,
                    "qualifs": {},
                }
            },
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertFalse(Affectation.objects.exists())

    def test_le_solveur_remplit_quand_le_salarie_respecte_le_besoin(self):
        self.animateur.qualifications.add(self.bafa)
        data, status = generer_planning_auto({"debut": "2026-07-06"})
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(Affectation.objects.count(), 5)


class PlanningJavascriptConfigurationTests(SimpleTestCase):
    def test_la_fenetre_est_en_lecture_seule(self):
        script = Path("static/js/planning.js").read_text(encoding="utf-8")
        self.assertIn("Ces besoins ne sont pas modifiables depuis le planning.", script)
        self.assertNotIn('class="auto-evenement-effectif"', script)
        self.assertNotIn('class="auto-evenement-qualif"', script)
        self.assertIn('body: JSON.stringify({ debut })', script)
