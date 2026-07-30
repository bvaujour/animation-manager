import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Affectation, ActiviteTravailComplementaire, Animateur, Centre, Evenement,
    ParticipationTravailComplementaire, PrimeJournalierePeriode,
)
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_periode
from animateurs.services.recapitulatif import lignes_recapitulatif_paie


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
        self.assertContains(response, 'id="btn-recap-excel"')
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
            montant="3",
        )

        data = self.client.get(
            reverse("api_recapitulatif") + f"?periode_ids={self.periode.id}"
        ).json()
        julie = next(item for item in data["animateurs"] if item["id"] == self.julie.id)

        self.assertEqual(julie["jours_travailles"], 1)
        self.assertEqual(julie["prime_jour"], "3.00")
        self.assertEqual(julie["total_jour_avec_prime"], "68.00")
        self.assertEqual(julie["total_paie_estime"], "68.00")

    def test_validation_groupee_applique_plusieurs_animateurs_et_semaines(self):
        seconde = creer_periode(debut=datetime.date(2026, 7, 13), nom="Été — Semaine 2")
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        self._affecter(self.sam, datetime.date(2026, 7, 13))
        self.sam.paie_jour = Decimal("55.00")
        self.sam.save(update_fields=["paie_jour"])

        response = self.client.put(reverse("api_prime_journaliere"), data={
            "periode_ids": [self.periode.id, seconde.id],
            "primes": [
                {"animateur_id": self.julie.id, "montant": "3"},
                {"animateur_id": self.sam.id, "montant": "2.00"},
            ],
        }, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["semaines_modifiees"], 2)
        self.assertEqual(PrimeJournalierePeriode.objects.filter(
            animateur__in=[self.julie, self.sam], periode__in=[self.periode, seconde]
        ).count(), 4)

    def test_zero_groupe_supprime_uniquement_les_semaines_selectionnees(self):
        seconde = creer_periode(debut=datetime.date(2026, 7, 13), nom="Été — Semaine 2")
        PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=self.periode, montant="2")
        PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=seconde, montant="4")
        self._affecter(self.julie, datetime.date(2026, 7, 6))

        response = self.client.put(reverse("api_prime_journaliere"), data={
            "periode_ids": [self.periode.id],
            "primes": [{"animateur_id": self.julie.id, "montant": "0.00"}],
        }, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PrimeJournalierePeriode.objects.filter(animateur=self.julie, periode=self.periode).exists())
        self.assertTrue(PrimeJournalierePeriode.objects.filter(animateur=self.julie, periode=seconde, montant=4).exists())

    def test_validation_groupee_invalide_ne_modifie_rien(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        response = self.client.put(reverse("api_prime_journaliere"), data={
            "periode_ids": [self.periode.id],
            "primes": [
                {"animateur_id": self.julie.id, "montant": "3.00"},
                {"animateur_id": 999999, "montant": "2.00"},
            ],
        }, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PrimeJournalierePeriode.objects.exists())

    def test_primes_differentes_sont_detaillees_et_ponderees_par_semaine(self):
        seconde = creer_periode(debut=datetime.date(2026, 7, 13), nom="Été — Semaine 2")
        self._affecter(self.julie, datetime.date(2026, 7, 6), duree=5)
        self._affecter(self.julie, datetime.date(2026, 7, 13), duree=4)
        PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=self.periode, montant="2")
        PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=seconde, montant="5")

        data = self.client.get(reverse("api_recapitulatif") + f"?periode_ids={self.periode.id},{seconde.id}").json()
        julie = next(item for item in data["animateurs"] if item["id"] == self.julie.id)
        self.assertTrue(julie["prime_jour_variable"])
        self.assertEqual([item["prime_jour"] for item in julie["primes_detail"]], ["2.00", "5.00"])
        self.assertEqual(julie["paie_base"], "585.00")
        self.assertEqual(julie["montant_primes"], "30.00")
        self.assertEqual(julie["total_paie_estime"], "615.00")

    def test_page_prime_utilise_une_validation_explicite(self):
        response = self.client.get(reverse("recapitulatif"))
        self.assertContains(response, 'id="save-payroll-primes"')
        self.assertContains(response, "Valider les primes")
        self.assertContains(response, 'id="cancel-payroll-primes"')

    def test_suppression_individuelle_est_limitee_aux_semaines_selectionnees(self):
        seconde = creer_periode(debut=datetime.date(2026, 7, 13), nom="Été — Semaine 2")
        troisieme = creer_periode(debut=datetime.date(2026, 7, 20), nom="Été — Semaine 3")
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        for periode, montant in ((self.periode, 2), (seconde, 4), (troisieme, 5)):
            PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=periode, montant=montant)
        PrimeJournalierePeriode.objects.create(animateur=self.sam, periode=self.periode, montant=6)

        response = self.client.delete(reverse("api_prime_journaliere"), data={
            "animateur_id": self.julie.id, "periode_ids": [self.periode.id, seconde.id]
        }, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_count"], 2)
        self.assertFalse(PrimeJournalierePeriode.objects.filter(animateur=self.julie, periode__in=[self.periode, seconde]).exists())
        self.assertTrue(PrimeJournalierePeriode.objects.filter(animateur=self.julie, periode=troisieme, montant=5).exists())
        self.assertTrue(PrimeJournalierePeriode.objects.filter(animateur=self.sam, periode=self.periode, montant=6).exists())
        self.assertEqual(response.json()["animateur"]["montant_primes"], "0.00")

    def test_suppression_individuelle_tolere_une_semaine_sans_prime(self):
        seconde = creer_periode(debut=datetime.date(2026, 7, 13), nom="Été — Semaine 2")
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=self.periode, montant=3)
        response = self.client.delete(reverse("api_prime_journaliere"), data={
            "animateur_id": self.julie.id, "periode_ids": [self.periode.id, seconde.id]
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_count"], 1)

    def test_api_accepte_un_entier_et_refuse_toute_prime_decimale(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        url = reverse("api_prime_journaliere")
        payload = lambda montant: {"periode_ids": [self.periode.id], "primes": [{"animateur_id": self.julie.id, "montant": montant}]}
        self.assertEqual(self.client.put(url, data=payload(3), content_type="application/json").status_code, 200)
        for montant in ("2.50", "3.10", 3.5):
            response = self.client.put(url, data=payload(montant), content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("euros entiers", response.json()["error"])
        self.assertEqual(PrimeJournalierePeriode.objects.get().montant, 3)

    def test_audit_primes_signale_sans_corriger_une_ancienne_decimale(self):
        prime = PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=self.periode, montant="2.50")
        sortie = StringIO()
        call_command("audit_primes", stdout=sortie)
        self.assertIn("2,50 €", sortie.getvalue())
        prime.refresh_from_db()
        self.assertEqual(prime.montant, Decimal("2.50"))

    def test_prime_entiere_est_proratisee_sur_une_fraction_de_jour(self):
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        preparation = ActiviteTravailComplementaire.objects.create(type="preparation", intitule="Demi-journée")
        preparation.periodes.add(self.periode)
        ParticipationTravailComplementaire.objects.create(
            activite=preparation, animateur=self.julie, nombre_jours="0.50"
        )
        PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=self.periode, montant=3)
        data = self.client.get(reverse("api_recapitulatif") + f"?periode_ids={self.periode.id}").json()
        julie = next(item for item in data["animateurs"] if item["id"] == self.julie.id)
        self.assertEqual(julie["prime_jour"], "3.00")
        self.assertEqual(julie["montant_primes"], "4.50")
        self.assertEqual(julie["total_paie_estime"], "102.00")

    def test_interface_formate_la_prime_journaliere_sans_centimes(self):
        javascript = (Path(settings.BASE_DIR) / "static/js/recapitulatif.js").read_text(encoding="utf-8")
        self.assertIn('step="1"', javascript)
        self.assertIn("function formatDailyPrime", javascript)
        self.assertIn('`${number}\u00a0€`', javascript)
        self.assertNotIn('step="0.01"', javascript)
        self.assertIn("data-cancel-prime", javascript)
        self.assertIn("data-delete-prime", javascript)

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

    def test_export_excel_recapitulatif(self):
        from openpyxl import load_workbook
        from io import BytesIO

        self._affecter(self.julie, datetime.date(2026, 7, 6), duree=2)
        response = self.client.get(
            reverse("export_recapitulatif_excel") + f"?periode_ids={self.periode.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("recapitulatif_20260706_20260710.xlsx", response["Content-Disposition"])
        classeur = load_workbook(BytesIO(response.content), data_only=True)
        self.assertEqual(classeur.sheetnames, ["Totaux paie", "Détail par centre"])
        self.assertEqual(classeur["Totaux paie"]["A3"].value, "Julie Martin")

    def test_tableau_pdf_agrege_exactement_les_totaux_ecran(self):
        seconde = creer_periode(debut=datetime.date(2026, 7, 13), nom="Été — Semaine 2")
        self._affecter(self.julie, datetime.date(2026, 7, 6), duree=5)
        self._affecter(self.julie, datetime.date(2026, 7, 13), duree=4)
        reunion = ActiviteTravailComplementaire.objects.create(
            type="reunion", intitule="Réunion", date=datetime.date(2026, 7, 7)
        )
        reunion.periodes.set([self.periode, seconde])
        ParticipationTravailComplementaire.objects.create(
            activite=reunion, animateur=self.julie, autoriser_double_comptage=True
        )
        PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=self.periode, montant=3)
        PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=seconde, montant=4)

        data = self.client.get(reverse("api_recapitulatif") + f"?periode_ids={self.periode.id},{seconde.id}").json()
        julie = next(item for item in data["animateurs"] if item["id"] == self.julie.id)
        lignes = lignes_recapitulatif_paie(data)

        self.assertEqual(len(lignes), 3)  # en-tête, un animateur, total général
        self.assertEqual(lignes[1], [
            "Julie Martin", "9", "1", "0", "10", "65,00 €",
            "650,00 €", "34,00 €", "684,00 €",
        ])
        self.assertEqual(julie["jours_travailles"], 10)
        self.assertEqual(julie["montant_primes"], "34.00")
        self.assertNotIn("0.125", " ".join(lignes[1]))
        self.assertFalse(any("Semaine" in cellule for ligne in lignes for cellule in ligne))

    def test_reunion_n_est_pas_divisee_sur_les_semaines_vides(self):
        periodes = [self.periode] + [
            creer_periode(debut=datetime.date(2026, 7, 13) + datetime.timedelta(days=7 * index), nom=f"Été — Semaine {index + 2}")
            for index in range(7)
        ]
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        reunion = ActiviteTravailComplementaire.objects.create(
            type="reunion", intitule="Réunion unique", date=datetime.date(2026, 7, 7)
        )
        reunion.periodes.set(periodes)
        ParticipationTravailComplementaire.objects.create(activite=reunion, animateur=self.julie)
        for periode in periodes:
            PrimeJournalierePeriode.objects.create(animateur=self.julie, periode=periode, montant=3)

        ids = ",".join(str(periode.id) for periode in periodes)
        julie = self.client.get(reverse("api_recapitulatif") + f"?periode_ids={ids}").json()["animateurs"][0]
        self.assertEqual(julie["jours_reunion"], 1)
        self.assertEqual(julie["montant_primes"], "6.00")
        self.assertEqual([item["jours"] for item in julie["primes_detail"]], [2, 0, 0, 0, 0, 0, 0, 0])

    def test_export_pdf_recapitulatif_refuse_une_periode_inconnue(self):
        response = self.client.get(reverse("export_recapitulatif_paie_pdf") + "?periode_ids=999999")

        self.assertEqual(response.status_code, 400)

    def test_api_refuse_une_selection_de_periode_inconnue(self):
        response = self.client.get(reverse("api_recapitulatif") + "?periode_ids=999999")
        self.assertEqual(response.status_code, 400)
