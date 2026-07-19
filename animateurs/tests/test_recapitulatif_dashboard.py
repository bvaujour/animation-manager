import datetime

from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Evenement
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_periode


class RecapitulatifDashboardTests(ConnexionTestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="La Pacaudière", code="PAC", couleur="#123456")
        self.periode = creer_periode(debut=datetime.date(2026, 7, 6), nom="Semaine récap")
        self.evenement = Evenement.objects.create(
            centre=self.centre,
            nom="Maternelles",
            effectif_cible=2,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.evenement.periodes_scolaires.add(self.periode)
        self.julie = Animateur.objects.create(prenom="Julie", nom="Martin", paie_jour="65.00")
        self.sam = Animateur.objects.create(prenom="Sam", nom="Dupont")

    def _affecter(self, animateur, jour, duree=1):
        debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
        return Affectation.objects.create(
            animateur=animateur,
            centre=self.centre,
            evenement=self.evenement,
            debut=debut,
            fin=debut + datetime.timedelta(days=duree),
        )

    def test_api_compte_les_jours_travailles_par_animateur(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6), duree=2)
        self._affecter(self.sam, datetime.date(2026, 7, 7))

        response = self.client.get(reverse("api_recapitulatif") + "?debut=2026-07-06&fin=2026-07-09")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_jours"], 3)
        self.assertNotIn("synthese", data)
        self.assertNotIn("alertes", data)
        self.assertNotIn("evenements", data)

        julie = next(item for item in data["animateurs"] if item["id"] == self.julie.id)
        sam = next(item for item in data["animateurs"] if item["id"] == self.sam.id)
        self.assertEqual(julie["jours_travailles"], 2)
        self.assertEqual(sam["jours_travailles"], 1)

    def test_une_date_ne_compte_quune_fois_par_animateur(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        autre_groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Élémentaires",
            effectif_cible=1,
        )
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        Affectation.objects.create(
            animateur=self.julie,
            centre=self.centre,
            evenement=autre_groupe,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

        data = self.client.get(reverse("api_recapitulatif") + "?debut=2026-07-06&fin=2026-07-07").json()
        self.assertEqual(data["animateurs"][0]["jours_travailles"], 1)
        self.assertEqual(data["total_jours"], 1)

    def test_api_accepte_plusieurs_periodes_discontinues(self):
        seconde_periode = creer_periode(debut=datetime.date(2026, 7, 20), nom="Deuxième semaine récap")
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        self._affecter(self.julie, datetime.date(2026, 7, 20))
        self._affecter(self.julie, datetime.date(2026, 7, 13))

        response = self.client.get(
            reverse("api_recapitulatif") + f"?periode_ids={self.periode.id},{seconde_periode.id}"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["periode"]["ids"], [self.periode.id, seconde_periode.id])
        self.assertEqual(data["animateurs"][0]["jours_travailles"], 2)


    def test_api_retourne_le_detail_des_lieux_par_jour(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6), duree=2)

        data = self.client.get(
            reverse("api_recapitulatif") + f"?periode_ids={self.periode.id}"
        ).json()

        self.assertEqual(data["dates"][0], "2026-07-06")
        self.assertEqual(data["centres"], [{
            "id": self.centre.id,
            "nom": "La Pacaudière",
            "code": "PAC",
            "couleur": "#123456",
        }])
        julie = next(item for item in data["animateurs"] if item["id"] == self.julie.id)
        self.assertEqual([jour["date"] for jour in julie["jours"]], ["2026-07-06", "2026-07-07"])
        self.assertEqual(julie["jours"][0]["lieux"][0]["code"], "PAC")
        self.assertEqual(julie["jours"][0]["lieux"][0]["couleur"], "#123456")
        self.assertEqual(julie["centres"][0]["jours_travailles"], 2)
        self.assertEqual(julie["centres"][0]["paie"], "130.00")
        self.assertEqual(julie["paie_totale"], "130.00")

    def test_page_recapitulatif_affiche_les_deux_onglets(self):
        response = self.client.get(reverse("recapitulatif"))

        self.assertContains(response, "Jours et paie par centre")
        self.assertContains(response, "Totaux par animateur")
        self.assertContains(response, 'data-recap-panel="centres"')

    def test_api_refuse_une_selection_de_periode_inconnue(self):
        response = self.client.get(reverse("api_recapitulatif") + "?periode_ids=999999")
        self.assertEqual(response.status_code, 400)
