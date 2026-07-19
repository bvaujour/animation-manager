import datetime
import json

from django.core.exceptions import FieldDoesNotExist

from animateurs.models import Centre, Evenement, PeriodeScolaire
from animateurs.tests.base import ConnexionTestCase


class GroupesPeriodesTests(ConnexionTestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="La Pacaudière", code="PAC")
        self.s1 = PeriodeScolaire.objects.create(
            nom="Été — Semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )
        self.s2 = PeriodeScolaire.objects.create(
            nom="Été — Semaine 2",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 7, 13),
            fin=datetime.date(2026, 7, 17),
        )

    def creer_groupe(self, **extra):
        payload = {
            "nom": "Maternelles",
            "periode_ids": [self.s1.id, self.s2.id],
            "effectif_cible": 3,
            "jours_ouverts": [0, 1, 2, 3, 4, 5],
            "ferme_jours_feries": True,
        }
        payload.update(extra)
        return self.client.post(
            f"/api/centres/{self.centre.id}/groupes/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_creation_sans_periode_est_autorisee(self):
        response = self.creer_groupe(periode_ids=[])
        self.assertEqual(response.status_code, 201)
        groupe = Evenement.objects.get()
        self.assertFalse(groupe.periodes_scolaires.exists())
        with self.assertRaises(FieldDoesNotExist):
            Evenement._meta.get_field("debut")
        with self.assertRaises(FieldDoesNotExist):
            Evenement._meta.get_field("fin")
        self.assertFalse(groupe.est_ouvert_le(datetime.date(2026, 7, 6)))


    def test_groupe_permanent_est_ouvert_sans_periode(self):
        response = self.creer_groupe(permanent=True, periode_ids=[self.s1.id])
        self.assertEqual(response.status_code, 201)
        groupe = Evenement.objects.get()
        self.assertTrue(groupe.permanent)
        self.assertEqual(
            set(groupe.periodes_scolaires.values_list("id", flat=True)),
            {self.s1.id, self.s2.id},
        )
        self.assertTrue(groupe.est_ouvert_le(datetime.date(2026, 9, 7)))
        self.assertFalse(groupe.est_ouvert_le(datetime.date(2026, 9, 13)))
        self.assertTrue(response.json()["permanent"])

    def test_repasser_un_groupe_en_non_permanent_le_ferme_sans_semaine(self):
        self.creer_groupe(permanent=True)
        groupe = Evenement.objects.get()
        response = self.client.patch(
            f"/api/groupes/{groupe.id}/",
            data=json.dumps({"permanent": False, "periode_ids": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        groupe.refresh_from_db()
        self.assertFalse(groupe.permanent)
        self.assertFalse(groupe.est_ouvert_le(datetime.date(2026, 9, 7)))

    def test_creation_utilise_uniquement_les_periodes_selectionnees(self):
        response = self.creer_groupe(periode_ids=[self.s2.id])
        self.assertEqual(response.status_code, 201)
        groupe = Evenement.objects.get()
        self.assertEqual(list(groupe.periodes_scolaires.all()), [self.s2])

    def test_lundi_a_samedi_ouverts_et_dimanche_ferme_par_defaut(self):
        response = self.creer_groupe(periode_ids=[self.s1.id])
        self.assertEqual(response.status_code, 201)
        groupe = Evenement.objects.get()
        self.assertEqual(groupe.jours_ouverts, [0, 1, 2, 3, 4, 5])
        self.assertTrue(groupe.est_ouvert_le(datetime.date(2026, 7, 6)))
        # La période importée s'arrête le vendredi, mais le samedi qui suit
        # est inclus car il fait partie des jours ouverts du groupe.
        self.assertTrue(groupe.est_ouvert_le(datetime.date(2026, 7, 11)))
        self.assertFalse(groupe.est_ouvert_le(datetime.date(2026, 7, 12)))

    def test_selection_personnalisee_des_jours(self):
        response = self.creer_groupe(
            periode_ids=[self.s1.id],
            jours_ouverts=[0, 2, 4],
            ferme_jours_feries=False,
        )
        self.assertEqual(response.status_code, 201)
        groupe = Evenement.objects.get()
        self.assertTrue(groupe.est_ouvert_le(datetime.date(2026, 7, 6)))  # lundi
        self.assertFalse(groupe.est_ouvert_le(datetime.date(2026, 7, 7)))  # mardi
        self.assertTrue(groupe.est_ouvert_le(datetime.date(2026, 7, 8)))  # mercredi

    def test_jour_ferie_est_propre_au_groupe(self):
        self.creer_groupe()
        groupe = Evenement.objects.get()
        self.assertFalse(groupe.est_ouvert_le(datetime.date(2026, 7, 14)))
        groupe.ferme_jours_feries = False
        groupe.save(update_fields=["ferme_jours_feries"])
        self.assertTrue(groupe.est_ouvert_le(datetime.date(2026, 7, 14)))

    def test_api_expose_periodes_et_jours_sans_anciens_booleens(self):
        response = self.creer_groupe()
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["periode_ids"], [self.s1.id, self.s2.id])
        self.assertEqual(data["jours_ouverts"], [0, 1, 2, 3, 4, 5])
        self.assertTrue(data["ferme_jours_feries"])
        self.assertNotIn("active", data)
        self.assertNotIn("ferme_weekends", data)

    def test_anciens_champs_booleens_nexistent_plus(self):
        with self.assertRaises(FieldDoesNotExist):
            Evenement._meta.get_field("active")
        with self.assertRaises(FieldDoesNotExist):
            Evenement._meta.get_field("ferme_weekends")
