import datetime

from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, DateExclueEvenement, Disponibilite
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_groupe


class SituationSemainePlanningTests(ConnexionTestCase):
    lundi = datetime.date(2026, 7, 20)
    samedi = datetime.date(2026, 7, 25)
    lundi_suivant = datetime.date(2026, 7, 27)

    def setUp(self):
        self.centre = Centre.objects.create(nom="Centre visible", code="VIS", couleur="#123456")
        self.groupe, _ = creer_groupe(
            self.centre,
            nom="Maternelles",
            debut=self.lundi,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.animateur = Animateur.objects.create(prenom="Lina", nom="Test")
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=self.lundi,
            fin=self.lundi + datetime.timedelta(days=4),
        )

    def _dt(self, jour):
        return timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))

    def _affecter(self, debut, fin, groupe=None):
        groupe = groupe or self.groupe
        return Affectation.objects.create(
            animateur=self.animateur,
            centre=groupe.centre,
            evenement=groupe,
            debut=self._dt(debut),
            fin=self._dt(fin),
        )

    def _situation(self):
        response = self.client.get(
            reverse("api_animateurs"),
            {
                "include_affectations": "1",
                "format": "planning",
                "debut": self.lundi.isoformat(),
                "fin": self.lundi_suivant.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()[0]["situation_semaine"]

    def test_affecte_sur_tous_les_jours_ouverts_nest_plus_placable(self):
        self._affecter(self.lundi, self.samedi)

        situation = self._situation()

        self.assertFalse(situation["encore_placable"])
        self.assertEqual(situation["nombre_jours_disponibles"], 5)
        self.assertEqual(situation["nombre_jours_affectes"], 5)
        self.assertEqual(situation["jours_restants"], [])

    def test_reste_visible_si_un_seul_jour_possible_reste(self):
        self._affecter(self.lundi, self.lundi + datetime.timedelta(days=4))

        situation = self._situation()

        self.assertTrue(situation["encore_placable"])
        self.assertEqual(situation["jours_restants"], ["2026-07-24"])

    def test_disparait_quand_tous_ses_jours_disponibles_sont_affectes(self):
        self.animateur.disponibilites.all().delete()
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=self.lundi,
            fin=self.lundi + datetime.timedelta(days=2),
        )
        self._affecter(self.lundi, self.lundi + datetime.timedelta(days=3))

        situation = self._situation()

        self.assertFalse(situation["encore_placable"])
        self.assertEqual(situation["nombre_jours_disponibles"], 3)
        self.assertEqual(situation["nombre_jours_affectes"], 3)

    def test_un_jour_ferme_ne_compte_pas_comme_jour_restant(self):
        self.groupe.jours_ouverts = [0, 1, 2, 3]
        self.groupe.save(update_fields=["jours_ouverts"])
        self._affecter(self.lundi, self.lundi + datetime.timedelta(days=4))

        situation = self._situation()

        self.assertFalse(situation["encore_placable"])
        self.assertEqual(situation["jours_ouverts"], [
            "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23"
        ])
        self.assertNotIn("2026-07-24", situation["jours_restants"])

    def test_une_date_exclue_ne_compte_pas_comme_jour_restant(self):
        DateExclueEvenement.objects.create(
            evenement=self.groupe,
            date=self.lundi + datetime.timedelta(days=2),
            motif="Fermeture",
        )
        self._affecter(self.lundi, self.lundi + datetime.timedelta(days=2))
        self._affecter(self.lundi + datetime.timedelta(days=3), self.samedi)

        situation = self._situation()

        self.assertFalse(situation["encore_placable"])
        self.assertNotIn("2026-07-22", situation["jours_ouverts"])

    def test_les_affectations_dun_centre_masque_restent_comptees(self):
        centre_masque = Centre.objects.create(nom="Centre masqué", code="MSQ", couleur="#654321")
        groupe_masque, _ = creer_groupe(
            centre_masque,
            nom="Élémentaires",
            debut=self.lundi,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self._affecter(self.lundi, self.samedi, groupe=groupe_masque)

        situation = self._situation()

        self.assertFalse(situation["encore_placable"])
        self.assertEqual(situation["nombre_jours_affectes"], 5)

    def test_les_dates_fullcalendar_sont_des_dates_locales_sans_decalage_utc(self):
        self._affecter(self.lundi, self.samedi)

        response = self.client.get(
            reverse("api_planning"),
            {"start": self.lundi.isoformat(), "end": self.lundi_suivant.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        event = response.json()[0]
        self.assertEqual(event["start"], "2026-07-20")
        self.assertEqual(event["end"], "2026-07-25")
