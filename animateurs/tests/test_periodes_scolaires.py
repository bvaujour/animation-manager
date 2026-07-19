import datetime
import json
from unittest.mock import patch

from django.urls import reverse

from animateurs.models import Centre, Evenement, PeriodeScolaire
from animateurs.services.calendrier_scolaire import (
    SemaineVacances,
    decouper_en_semaines,
)
from animateurs.tests.base import ConnexionTestCase


class DecoupageCalendrierScolaireTests(ConnexionTestCase):
    def test_toussaint_est_decoupee_du_lundi_au_vendredi(self):
        semaines = decouper_en_semaines(
            "Vacances de la Toussaint",
            datetime.date(2026, 10, 17),
            datetime.date(2026, 11, 2),
        )

        self.assertEqual(len(semaines), 2)
        self.assertEqual(semaines[0].nom, "Toussaint — Semaine 1")
        self.assertEqual(semaines[0].debut, datetime.date(2026, 10, 19))
        self.assertEqual(semaines[0].fin, datetime.date(2026, 10, 23))
        self.assertEqual(semaines[1].debut, datetime.date(2026, 10, 26))
        self.assertEqual(semaines[1].fin, datetime.date(2026, 10, 30))

    def test_un_pont_ne_devient_pas_une_fausse_semaine(self):
        semaines = decouper_en_semaines(
            "Pont de l'Ascension",
            datetime.date(2027, 5, 5),
            datetime.date(2027, 5, 10),
        )
        self.assertEqual(semaines, [])


class PeriodesScolairesApiTests(ConnexionTestCase):
    def setUp(self):
        self.semaines = [
            SemaineVacances(
                nom="Toussaint — Semaine 1",
                debut=datetime.date(2026, 10, 19),
                fin=datetime.date(2026, 10, 23),
                description_source="Vacances de la Toussaint",
                numero=1,
            ),
            SemaineVacances(
                nom="Toussaint — Semaine 2",
                debut=datetime.date(2026, 10, 26),
                fin=datetime.date(2026, 10, 30),
                description_source="Vacances de la Toussaint",
                numero=2,
            ),
        ]

    @patch("animateurs.views.recuperer_semaines")
    def test_previsualisation_ne_cree_aucune_donnee(self, recuperer):
        recuperer.return_value = self.semaines
        response = self.client.post(
            reverse("api_periodes_scolaires_previsualiser"),
            data=json.dumps({"annee_scolaire": "2026-2027", "zone": "A"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["nombre"], 2)
        self.assertEqual(PeriodeScolaire.objects.count(), 0)

    @patch("animateurs.views.recuperer_semaines")
    def test_import_est_idempotent(self, recuperer):
        recuperer.return_value = self.semaines
        url = reverse("api_periodes_scolaires_importer")
        payload = json.dumps({"annee_scolaire": "2026-2027", "zone": "A"})

        first = self.client.post(url, data=payload, content_type="application/json")
        second = self.client.post(url, data=payload, content_type="application/json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["cree"], 2)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["cree"], 0)
        self.assertEqual(PeriodeScolaire.objects.count(), 2)

    def test_liste_peut_etre_filtree_par_annee(self):
        PeriodeScolaire.objects.create(
            nom="Toussaint — Semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 10, 19),
            fin=datetime.date(2026, 10, 23),
        )
        PeriodeScolaire.objects.create(
            nom="Toussaint — Semaine 1",
            annee_scolaire="2027-2028",
            zone="A",
            debut=datetime.date(2027, 10, 18),
            fin=datetime.date(2027, 10, 22),
        )

        response = self.client.get(
            reverse("api_periodes_scolaires") + "?annee_scolaire=2027-2028"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["annee_scolaire"], "2027-2028")

    @patch("animateurs.views.recuperer_semaines")
    def test_import_ne_modifie_pas_les_groupes_existants(self, recuperer):
        recuperer.return_value = self.semaines
        centre = Centre.objects.create(nom="La Pacaudière", code="PAC")
        Evenement.objects.create(
            centre=centre,
            nom="Maternelles",
            jours_ouverts=[0, 1, 2, 3, 4],
        )

        self.client.post(
            reverse("api_periodes_scolaires_importer"),
            data=json.dumps({"annee_scolaire": "2026-2027", "zone": "A"}),
            content_type="application/json",
        )

        evenement = Evenement.objects.get()
        self.assertEqual(evenement.periodes_scolaires.count(), 0)
