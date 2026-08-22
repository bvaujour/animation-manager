import datetime
import json

from django.urls import reverse

from animateurs.models import Centre, Evenement, Groupe
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_periode


class GroupesSejourValiditeTests(ConnexionTestCase):
    def test_api_permet_de_categoriser_un_groupe_de_sejour_avec_ses_dates(self):
        response = self.client.post(
            reverse("api_groupes_partages"),
            data=json.dumps(
                {
                    "nom": "Ardèche CM 2027",
                    "type_groupe": "sejour",
                    "date_debut_validite": "2027-07-05",
                    "date_fin_validite": "2027-07-09",
                    "categorie_age_reglementaire": "six_plus",
                    "enfants_par_animateur_defaut": 12,
                    "type_accueil_codes": ["vacances"],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["type_groupe"], "sejour")
        self.assertEqual(data["date_debut_validite"], "2027-07-05")
        self.assertEqual(data["date_fin_validite"], "2027-07-09")
        self.assertEqual(data["statut_validite"], "a_venir")

    def test_un_groupe_de_sejour_exige_une_periode_complete(self):
        response = self.client.post(
            reverse("api_groupes_partages"),
            data=json.dumps(
                {
                    "nom": "Séjour sans fin",
                    "type_groupe": "sejour",
                    "date_debut_validite": "2027-07-05",
                    "date_fin_validite": "",
                    "categorie_age_reglementaire": "six_plus",
                    "enfants_par_animateur_defaut": 12,
                    "type_accueil_codes": ["vacances"],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("date de fin", response.json()["error"].lower())

    def test_validite_du_groupe_borne_le_planning_sans_supprimer_l_historique(self):
        centre = Centre.objects.create(nom="Séjours", code="SEJ", couleur="#123456")
        definition = Groupe.objects.create(
            nom="Cublize 2026",
            type_groupe=Groupe.TYPE_SEJOUR,
            date_debut_validite=datetime.date(2026, 7, 8),
            date_fin_validite=datetime.date(2026, 7, 10),
            categorie_age_reglementaire=Groupe.AGE_6_PLUS,
            enfants_par_animateur_defaut=12,
        )
        periode = creer_periode(debut=datetime.date(2026, 7, 6), nom="Semaine séjour")
        evenement = Evenement.objects.create(
            centre=centre,
            groupe=definition,
            nom=definition.nom,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        evenement.periodes_scolaires.add(periode)

        self.assertFalse(evenement.est_ouvert_le(datetime.date(2026, 7, 7)))
        self.assertTrue(evenement.est_ouvert_le(datetime.date(2026, 7, 8)))
        self.assertTrue(evenement.est_ouvert_le(datetime.date(2026, 7, 10)))
        self.assertFalse(evenement.est_ouvert_le(datetime.date(2026, 7, 11)))
        self.assertTrue(Groupe.objects.filter(pk=definition.pk).exists())
