import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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


class RecapitulatifDashboardTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="La Pacaudière",
            code="PAC",
            couleur="#123456",
        )
        self.bafa = Qualification.objects.create(nom="BAFA")
        self.periode = creer_periode(debut=datetime.date(2026, 7, 6), nom="Semaine récap")
        self.evenement = Evenement.objects.create(
            centre=self.centre,
            nom="Maternelles",
            debut=self.periode.debut,
            fin=self.periode.fin,
            effectif_cible=2,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.evenement.periodes_scolaires.add(self.periode)
        BesoinQualification.objects.create(
            evenement=self.evenement,
            qualification=self.bafa,
            nombre_minimum=1,
        )

        self.julie = Animateur.objects.create(prenom="Julie", nom="BAFA")
        self.julie.qualifications.add(self.bafa)
        PreferenceCentre.objects.create(
            animateur=self.julie,
            centre=self.centre,
            est_prefere=True,
        )
        Disponibilite.objects.create(
            animateur=self.julie,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 7),
        )

        self.sam = Animateur.objects.create(prenom="Sam", nom="Disponible")
        PreferenceCentre.objects.create(
            animateur=self.sam,
            centre=self.centre,
            est_prefere=True,
        )
        Disponibilite.objects.create(
            animateur=self.sam,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 7),
        )

        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        Affectation.objects.create(
            animateur=self.julie,
            centre=self.centre,
            evenement=self.evenement,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

    def test_api_expose_couverture_alertes_et_disponibilites(self):
        response = self.client.get(
            reverse("api_recapitulatif") + "?debut=2026-07-06&fin=2026-07-08"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["synthese"]["postes_requis"], 4)
        self.assertEqual(data["synthese"]["postes_couverts"], 1)
        self.assertEqual(data["synthese"]["postes_manquants"], 3)
        self.assertEqual(data["synthese"]["qualifications_manquantes"], 1)
        self.assertEqual(data["synthese"]["disponibles_sans_affectation"], 1)

        types_alertes = {alerte["type"] for alerte in data["alertes"]}
        self.assertIn("personnel", types_alertes)
        self.assertIn("qualification", types_alertes)
        self.assertIn("ressources_disponibles", types_alertes)

        evenement = data["evenements"][0]
        self.assertEqual(evenement["jours_prevus"], 2)
        self.assertEqual(evenement["jours_complets"], 0)
        self.assertEqual(evenement["postes_manquants"], 3)

        sam = next(item for item in data["animateurs"] if item["id"] == self.sam.id)
        self.assertEqual(sam["jours_disponibles"], 2)
        self.assertEqual(sam["jours_libres"], 2)

    def test_evenement_complet_ne_genere_pas_alerte_de_manque(self):
        for animateur in (self.sam,):
            debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
            Affectation.objects.create(
                animateur=animateur,
                centre=self.centre,
                evenement=self.evenement,
                debut=debut,
                fin=debut + datetime.timedelta(days=1),
            )

        for animateur in (self.julie, self.sam):
            debut = timezone.make_aware(datetime.datetime(2026, 7, 7))
            Affectation.objects.create(
                animateur=animateur,
                centre=self.centre,
                evenement=self.evenement,
                debut=debut,
                fin=debut + datetime.timedelta(days=1),
            )

        response = self.client.get(
            reverse("api_recapitulatif") + "?debut=2026-07-06&fin=2026-07-08"
        )
        data = response.json()

        self.assertEqual(data["synthese"]["postes_manquants"], 0)
        self.assertEqual(data["synthese"]["qualifications_manquantes"], 0)
        self.assertEqual(data["evenements"][0]["jours_complets"], 2)
        self.assertNotIn("personnel", {alerte["type"] for alerte in data["alertes"]})
        self.assertNotIn("qualification", {alerte["type"] for alerte in data["alertes"]})
    def test_api_accepte_plusieurs_periodes_discontinues(self):
        seconde_periode = creer_periode(
            debut=datetime.date(2026, 7, 20),
            nom="Deuxième semaine récap",
        )
        self.evenement.periodes_scolaires.add(seconde_periode)
        self.evenement.fin = seconde_periode.fin
        self.evenement.save(update_fields=["fin"])

        response = self.client.get(
            reverse("api_recapitulatif")
            + f"?periode_ids={self.periode.id},{seconde_periode.id}"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["periode"]["ids"], [self.periode.id, seconde_periode.id])
        evenement = next(item for item in data["evenements"] if item["id"] == self.evenement.id)
        self.assertEqual(evenement["jours_prevus"], 10)
        self.assertEqual(data["synthese"]["postes_requis"], 20)

    def test_api_refuse_une_selection_de_periode_inconnue(self):
        response = self.client.get(reverse("api_recapitulatif") + "?periode_ids=999999")
        self.assertEqual(response.status_code, 400)

