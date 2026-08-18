import datetime
import json
from unittest.mock import patch

from django.urls import reverse

from animateurs.models import Centre, Evenement, PeriodeCalendrier, PeriodeScolaire, Sejour, TypeAccueil
from animateurs.services.calendrier_scolaire import (
    SemaineVacances,
    decouper_en_semaines,
    calculer_periodes_scolaires,
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

    @patch("animateurs.views_catalogue.recuperer_semaines")
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

    @patch("animateurs.views_catalogue.recuperer_semaines")
    def test_import_est_idempotent(self, recuperer):
        recuperer.return_value = self.semaines
        url = reverse("api_periodes_scolaires_importer")
        payload = json.dumps({"annee_scolaire": "2026-2027", "zone": "A", "type_accueil": "vacances"})

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

    @patch("animateurs.views_catalogue.recuperer_semaines")
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
            data=json.dumps({"annee_scolaire": "2026-2027", "zone": "A", "type_accueil": "vacances"}),
            content_type="application/json",
        )

        evenement = Evenement.objects.get()
        self.assertEqual(evenement.periodes_scolaires.count(), 0)

    def test_creation_et_modification_exigent_un_type_accueil(self):
        url = reverse("api_periodes_scolaires")
        payload = {
            "nom": "Mercredi septembre",
            "annee_scolaire": "2027-2028",
            "zone": "A",
            "debut": "2027-09-01",
            "fin": "2027-09-01",
        }
        self.assertEqual(
            self.client.post(url, data=json.dumps(payload), content_type="application/json").status_code,
            400,
        )

        payload["type_accueil"] = "periscolaire"
        creation = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(creation.status_code, 201)
        periode = PeriodeScolaire.objects.get(pk=creation.json()["id"])
        self.assertEqual(periode.type_accueil.code, TypeAccueil.PERISCOLAIRE)

        payload["type_accueil"] = "periscolaire"
        payload["nom"] = "Périscolaire septembre"
        modification = self.client.patch(
            reverse("api_periode_scolaire_detail", args=(periode.pk,)),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(modification.status_code, 200)
        periode.refresh_from_db()
        self.assertEqual(periode.nom, "Périscolaire septembre")
        self.assertEqual(periode.type_accueil.code, TypeAccueil.PERISCOLAIRE)

    def test_espace_gestion_preslectionne_le_type_du_contexte(self):
        response = self.client.get(reverse("gestion"), {"onglet": "periodes", "type_accueil": "sejours"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-type-accueil-selectionne="sejours"')
        self.assertContains(response, "Périodes vacances")
        self.assertContains(response, "Périodes scolaires")

    @patch("animateurs.views_catalogue.recuperer_semaines")
    def test_import_selectif_regroupe_sans_doublon_et_force_vacances(self, recuperer):
        recuperer.return_value = self.semaines
        payload = {"annee_scolaire": "2026-2027", "zone": "A", "type_accueil": "vacances", "semaine_ids": ["2026-10-19"]}

        response = self.client.post(reverse("api_periodes_scolaires_importer"), data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(PeriodeScolaire.objects.count(), 1)
        semaine = PeriodeScolaire.objects.get()
        self.assertEqual(semaine.type_accueil.code, "vacances")
        self.assertIsNotNone(semaine.periode_calendrier)
        self.assertEqual(semaine.periode_calendrier.nom, "Toussaint")
        self.assertEqual(set(semaine.types_accueil.values_list("code", flat=True)), {"vacances"})

    def test_calcul_scolaire_conserve_les_semaines_partielles(self):
        vacances = [SemaineVacances("Toussaint — Semaine 1", datetime.date(2026, 10, 19), datetime.date(2026, 10, 23), "Toussaint", 1)]

        periodes = calculer_periodes_scolaires("2026-2027", vacances)

        self.assertTrue(periodes)
        jours = [jour for periode in periodes for semaine in periode["semaines"] for jour in semaine["jours_scolaires"]]
        self.assertNotIn("2026-10-19", jours)
        self.assertIn("2026-10-16", jours)

    @patch("animateurs.views_catalogue.recuperer_semaines")
    def test_reference_scolaire_est_partagee_sans_dupliquer_les_semaines(self, recuperer):
        recuperer.return_value = self.semaines
        url = reverse("api_calendrier_scolaire_enregistrer")
        base = {"annee_scolaire": "2026-2027", "zone": "A", "periode_ids": [0]}
        first = self.client.post(url, data=json.dumps({**base, "type_accueil": "mercredis"}), content_type="application/json")
        nombre = PeriodeScolaire.objects.count()
        second = self.client.post(url, data=json.dumps({**base, "type_accueil": "periscolaire", "modalite_periscolaire": "soir"}), content_type="application/json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PeriodeScolaire.objects.count(), nombre)
        reference = PeriodeCalendrier.objects.get(categorie=PeriodeCalendrier.SCOLAIRE)
        self.assertEqual(set(reference.types_accueil.values_list("code", flat=True)), {"periscolaire"})
        self.assertTrue(all(set(item.modalites_periscolaires.values_list("code", flat=True)) == {"mercredi_journee", "soir"} for item in reference.semaines.all()))

    def test_sejour_reste_distinct_du_lieu_et_peut_avoir_reference_et_equipe(self):
        reference = PeriodeCalendrier.objects.create(categorie="vacances", nom="Été", annee_scolaire="2027-2028", zone="A", debut="2028-07-10", fin="2028-07-21")
        response = self.client.post(reverse("api_sejours"), data=json.dumps({"nom": "Camp montagne", "destination": "Alpes", "date_debut": "2028-07-12", "date_fin": "2028-07-18", "periode_vacances_id": reference.pk, "equipe_ids": []}), content_type="application/json")

        self.assertEqual(response.status_code, 201)
        sejour = Sejour.objects.get()
        self.assertEqual(sejour.periode_vacances, reference)
        self.assertEqual(Centre.objects.count(), 0)
