import datetime
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Evenement, PrimeJournalierePeriode
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
        self.assertContains(response, 'id="periode-select"')
        self.assertContains(response, 'data-week-picker-mode="multiple"')
        self.assertContains(response, "Choisir des semaines ou une période")
        self.assertContains(response, 'id="btn-recap-pdf"')
        self.assertContains(response, "Préparation de la paie")
        self.assertContains(response, 'data-recap-panel="paie"')

    def test_prime_journaliere_est_limitee_et_propre_a_la_periode(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6), duree=2)
        tarif_initial = Decimal(str(self.julie.paie_jour))
        url = reverse("api_prime_journaliere")

        response = self.client.put(
            url,
            data={"animateur_id": self.julie.id, "periode_ids": [self.periode.id], "montant": "5.00"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_jour_avec_prime"], "70.00")
        self.assertEqual(response.json()["total_paie_estime"], "140.00")
        self.assertEqual(
            PrimeJournalierePeriode.objects.get(animateur=self.julie, periode=self.periode).montant,
            5,
        )
        self.julie.refresh_from_db()
        self.assertEqual(self.julie.paie_jour, tarif_initial)

        invalide = self.client.put(
            url,
            data={"animateur_id": self.julie.id, "periode_ids": [self.periode.id], "montant": "7.01"},
            content_type="application/json",
        )
        self.assertEqual(invalide.status_code, 400)

    def test_api_recapitulatif_expose_la_preparation_de_paie(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        PrimeJournalierePeriode.objects.create(
            animateur=self.julie,
            periode=self.periode,
            montant="3.50",
        )

        data = self.client.get(
            reverse("api_recapitulatif") + f"?periode_ids={self.periode.id}"
        ).json()
        julie = next(item for item in data["animateurs"] if item["id"] == self.julie.id)

        self.assertEqual(julie["jours_travailles"], 1)
        self.assertEqual(julie["prime_jour"], "3.50")
        self.assertEqual(julie["total_jour_avec_prime"], "68.50")
        self.assertEqual(julie["total_paie_estime"], "68.50")

    def test_prime_refusee_sans_jour_travaille_ou_tarif_journalier(self):
        url = reverse("api_prime_journaliere")
        sans_jour = self.client.put(
            url,
            data={"animateur_id": self.julie.id, "periode_ids": [self.periode.id], "montant": "2"},
            content_type="application/json",
        )
        self.assertEqual(sans_jour.status_code, 400)

        self._affecter(self.sam, datetime.date(2026, 7, 6))
        sans_tarif = self.client.put(
            url,
            data={"animateur_id": self.sam.id, "periode_ids": [self.periode.id], "montant": "2"},
            content_type="application/json",
        )
        self.assertEqual(sans_tarif.status_code, 400)

    def test_export_pdf_recapitulatif_paie(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6), duree=2)

        response = self.client.get(
            reverse("export_recapitulatif_paie_pdf") + f"?periode_ids={self.periode.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("recapitulatif_paie_20260706_20260710.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_export_pdf_recapitulatif_refuse_une_periode_inconnue(self):
        response = self.client.get(reverse("export_recapitulatif_paie_pdf") + "?periode_ids=999999")

        self.assertEqual(response.status_code, 400)

    def test_api_refuse_une_selection_de_periode_inconnue(self):
        response = self.client.get(reverse("api_recapitulatif") + "?periode_ids=999999")
        self.assertEqual(response.status_code, 400)
