import datetime
import json

from django.urls import reverse

from animateurs.models import (
    AccueilCentre,
    Centre,
    Groupe,
    ModalitePeriscolaire,
    OuvertureCentrePeriode,
    PeriodeCalendrier,
    PeriodeScolaire,
    TypeAccueil,
)
from animateurs.services.accueils import accueil_centre
from animateurs.tests.base import ConnexionTestCase
from animateurs.views_catalogue import (
    RecuperationOuverturesHistoriquesRequise,
    _ouvertures_assistant,
)


class AccueilsMultiplesPeriscolairesTests(ConnexionTestCase):
    def setUp(self):
        self.periscolaire, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.PERISCOLAIRE,
            defaults={"nom": "Périscolaire", "ordre": 20, "actif": True},
        )
        self.vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES,
            defaults={"nom": "Vacances", "ordre": 10, "actif": True},
        )
        self.centre = Centre.objects.create(nom="Saint-Forgeux test", code="SFT", couleur="#654321")
        self.centre.types_accueil.add(self.periscolaire, self.vacances)

    def test_deux_accueils_periscolaires_peuvent_coexister(self):
        semaine = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Semaine",
            date_debut=datetime.date(2026, 9, 1),
            pedt_applicable=True,
        )
        mercredi = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Mercredi",
            date_debut=datetime.date(2026, 9, 1),
            pedt_applicable=False,
        )

        self.assertNotEqual(semaine.pk, mercredi.pk)
        self.assertEqual(self.centre.accueils.filter(type_accueil=self.periscolaire).count(), 2)
        self.assertEqual(mercredi.nom_affichage, "Périscolaire — Mercredi")
        self.assertEqual(mercredi.libelle_analytique, "SFT — Périscolaire · Mercredi")

    def test_assistant_demande_confirmation_avant_de_recuperer_une_ouverture_historique(self):
        mercredi = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Mercredi",
            date_debut=datetime.date(2026, 9, 1),
        )
        modalite = ModalitePeriscolaire.objects.create(
            code="mercredi_historique_test",
            nom="Mercredi journée entière test",
            heure_debut=datetime.time(7, 30),
            heure_fin=datetime.time(18, 0),
            jour_entier=True,
            actif=True,
            ordre=10,
        )
        periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.SCOLAIRE,
            nom="Rentrée → Toussaint historique",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 1),
            fin=datetime.date(2026, 10, 16),
        )
        ancienne = OuvertureCentrePeriode.objects.create(
            centre=self.centre,
            accueil_centre=None,
            periode_calendrier=periode,
            modalite_periscolaire=modalite,
            jour_semaine=2,
            heure_debut=datetime.time(8, 0),
            heure_fin=datetime.time(17, 30),
        )
        configuration = {
            "periode_calendrier_ids": [periode.pk],
            "ouvertures": [
                {
                    "modalite_id": modalite.pk,
                    "jour_semaine": 2,
                    "heure_debut": "07:30",
                    "heure_fin": "18:00",
                }
            ],
        }

        with self.assertRaises(RecuperationOuverturesHistoriquesRequise):
            _ouvertures_assistant(mercredi, configuration)

        ancienne.refresh_from_db()
        self.assertIsNone(ancienne.accueil_centre_id)
        self.assertEqual(ancienne.heure_debut, datetime.time(8, 0))

        _ouvertures_assistant(
            mercredi,
            {**configuration, "recuperer_ouvertures_historiques": True},
        )

        ancienne.refresh_from_db()
        self.assertEqual(ancienne.accueil_centre, mercredi)
        self.assertEqual(ancienne.heure_debut, datetime.time(7, 30))
        self.assertEqual(ancienne.heure_fin, datetime.time(18, 0))
        self.assertEqual(
            OuvertureCentrePeriode.objects.filter(
                centre=self.centre,
                periode_calendrier=periode,
                modalite_periscolaire=modalite,
                jour_semaine=2,
            ).count(),
            1,
        )

    def test_api_demande_confirmation_puis_recupere_une_ouverture_historique(self):
        mercredi = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Mercredi API",
            date_debut=datetime.date(2026, 9, 1),
        )
        modalite = ModalitePeriscolaire.objects.create(
            code="mercredi_historique_api",
            nom="Mercredi historique API",
            heure_debut=datetime.time(7, 30),
            heure_fin=datetime.time(18, 0),
            jour_entier=True,
            actif=True,
            ordre=11,
        )
        periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.SCOLAIRE,
            nom="Rentrée API",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 1),
            fin=datetime.date(2026, 10, 16),
        )
        ancienne = OuvertureCentrePeriode.objects.create(
            centre=self.centre,
            accueil_centre=None,
            periode_calendrier=periode,
            modalite_periscolaire=modalite,
            jour_semaine=2,
            heure_debut=datetime.time(8, 0),
            heure_fin=datetime.time(17, 30),
        )
        payload = {
            "periode_calendrier_id": periode.pk,
            "accueil_id": mercredi.pk,
            "ouvertures": [
                {
                    "modalite_id": modalite.pk,
                    "jour_semaine": 2,
                    "heure_debut": "07:30",
                    "heure_fin": "18:00",
                }
            ],
        }
        url = reverse("api_ouvertures_periscolaires_centre", args=[self.centre.pk])

        demande = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(demande.status_code, 409)
        self.assertEqual(demande.json()["code"], "ouvertures_historiques_a_recuperer")
        self.assertEqual(demande.json()["accueil_nom"], "Périscolaire — Mercredi API")
        self.assertEqual(demande.json()["ouvertures"][0]["id"], ancienne.pk)
        ancienne.refresh_from_db()
        self.assertIsNone(ancienne.accueil_centre_id)

        confirmation = self.client.post(
            url,
            data=json.dumps({**payload, "recuperer_ouvertures_historiques": True}),
            content_type="application/json",
        )

        self.assertEqual(confirmation.status_code, 200)
        ancienne.refresh_from_db()
        self.assertEqual(ancienne.accueil_centre_id, mercredi.pk)
        self.assertEqual(ancienne.heure_debut, datetime.time(7, 30))
        self.assertEqual(ancienne.heure_fin, datetime.time(18, 0))

    def test_assistant_http_demande_confirmation_et_ne_cree_rien_avant_le_choix(self):
        modalite = ModalitePeriscolaire.objects.create(
            code="mercredi_historique_assistant_http",
            nom="Mercredi historique assistant HTTP",
            heure_debut=datetime.time(7, 30),
            heure_fin=datetime.time(18, 0),
            jour_entier=True,
            actif=True,
            ordre=12,
        )
        reference = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.SCOLAIRE,
            nom="Rentrée assistant HTTP",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 1),
            fin=datetime.date(2026, 10, 16),
        )
        reference.types_accueil.add(self.periscolaire)
        semaine = PeriodeScolaire.objects.create(
            nom="Rentrée assistant HTTP — semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 1),
            fin=datetime.date(2026, 9, 4),
            periode_calendrier=reference,
            type_accueil=self.periscolaire,
        )
        semaine.types_accueil.add(self.periscolaire)
        groupe = Groupe.objects.create(
            nom="Maternelle assistant HTTP",
            cle_unique="maternelle-assistant-http",
            enfants_par_animateur_defaut=8,
        )
        ancienne = OuvertureCentrePeriode.objects.create(
            centre=self.centre,
            accueil_centre=None,
            periode_calendrier=reference,
            modalite_periscolaire=modalite,
            jour_semaine=2,
            heure_debut=datetime.time(8, 0),
            heure_fin=datetime.time(17, 30),
        )
        fonctionnement = {
            "periode_calendrier_ids": [reference.pk],
            "ouvertures": [
                {
                    "modalite_id": modalite.pk,
                    "jour_semaine": 2,
                    "heure_debut": "07:30",
                    "heure_fin": "18:00",
                }
            ],
        }
        payload = {
            "centre_id": self.centre.pk,
            "accueils": [
                {
                    "type_accueil": TypeAccueil.PERISCOLAIRE,
                    "libelle": "Mercredi assistant HTTP",
                    "date_debut": "2026-09-01",
                    "pedt_applicable": True,
                    "groupes": [{"id": groupe.pk, "besoins_encadrement": []}],
                    "fonctionnement": fonctionnement,
                }
            ],
        }
        url = reverse("api_assistant_lieu_accueils")

        demande = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(demande.status_code, 409)
        self.assertEqual(demande.json()["code"], "ouvertures_historiques_a_recuperer")
        self.assertFalse(
            AccueilCentre.objects.filter(
                centre=self.centre,
                type_accueil=self.periscolaire,
                libelle="Mercredi assistant HTTP",
            ).exists()
        )
        ancienne.refresh_from_db()
        self.assertIsNone(ancienne.accueil_centre_id)

        payload["accueils"][0]["fonctionnement"] = {
            **fonctionnement,
            "recuperer_ouvertures_historiques": True,
        }
        confirmation = self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(confirmation.status_code, 200)
        accueil = AccueilCentre.objects.get(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Mercredi assistant HTTP",
        )
        ancienne.refresh_from_db()
        self.assertEqual(ancienne.accueil_centre_id, accueil.pk)
        self.assertEqual(ancienne.heure_debut, datetime.time(7, 30))
        self.assertTrue(accueil.groupes.filter(groupe=groupe).exists())

    def test_un_vrai_conflit_entre_deux_accueils_periscolaires_reste_bloque(self):
        semaine = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Semaine conflit",
            date_debut=datetime.date(2026, 9, 1),
        )
        mercredi = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Mercredi conflit",
            date_debut=datetime.date(2026, 9, 1),
        )
        modalite = ModalitePeriscolaire.objects.create(
            code="mercredi_conflit_api",
            nom="Mercredi conflit API",
            actif=True,
            ordre=12,
        )
        periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.SCOLAIRE,
            nom="Rentrée conflit",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 1),
            fin=datetime.date(2026, 10, 16),
        )
        OuvertureCentrePeriode.objects.create(
            centre=self.centre,
            accueil_centre=semaine,
            periode_calendrier=periode,
            modalite_periscolaire=modalite,
            jour_semaine=2,
        )
        url = reverse("api_ouvertures_periscolaires_centre", args=[self.centre.pk])
        payload = {
            "periode_calendrier_id": periode.pk,
            "accueil_id": mercredi.pk,
            "recuperer_ouvertures_historiques": True,
            "ouvertures": [{"modalite_id": modalite.pk, "jour_semaine": 2}],
        }

        response = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Périscolaire — Semaine conflit", response.json()["error"])
        self.assertEqual(
            OuvertureCentrePeriode.objects.filter(
                centre=self.centre, periode_calendrier=periode, modalite_periscolaire=modalite, jour_semaine=2
            ).count(),
            1,
        )

    def test_api_exige_un_nom_pour_un_deuxieme_periscolaire(self):
        AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            date_debut=datetime.date(2026, 9, 1),
        )
        response = self.client.post(
            reverse("api_accueils_centre", args=[self.centre.pk]),
            data=json.dumps({
                "type_accueil": TypeAccueil.PERISCOLAIRE,
                "date_debut": "2027-09-01",
                "libelle": "",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("nom complémentaire", response.json()["error"])

    def test_ouverture_identifie_le_bon_accueil_periscolaire(self):
        semaine = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Semaine",
            date_debut=datetime.date(2026, 9, 1),
        )
        mercredi = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Mercredi",
            date_debut=datetime.date(2026, 9, 1),
        )
        modalite = ModalitePeriscolaire.objects.create(
            code="mercredi_test",
            nom="Mercredi test",
            heure_debut=datetime.time(7, 30),
            heure_fin=datetime.time(18, 0),
            jour_entier=True,
            actif=True,
            ordre=10,
        )
        periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.SCOLAIRE,
            nom="Rentrée → Toussaint",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 1),
            fin=datetime.date(2026, 10, 16),
        )
        OuvertureCentrePeriode.objects.create(
            centre=self.centre,
            accueil_centre=mercredi,
            periode_calendrier=periode,
            modalite_periscolaire=modalite,
            jour_semaine=2,
            heure_debut=datetime.time(7, 30),
            heure_fin=datetime.time(18, 0),
        )

        resolu = accueil_centre(
            self.centre,
            self.periscolaire,
            jour=datetime.date(2026, 9, 2),
            modalite=modalite,
        )
        self.assertEqual(resolu, mercredi)
        self.assertNotEqual(resolu, semaine)


class ModalitesPeriscolairesApiTests(ConnexionTestCase):
    def test_creation_et_edition_d_un_temps_periscolaire(self):
        creation = self.client.post(
            reverse("api_modalites_periscolaires"),
            data=json.dumps({
                "nom": "Atelier du soir",
                "heure_debut": "16:45",
                "heure_fin": "18:15",
                "jour_entier": False,
            }),
            content_type="application/json",
        )
        self.assertEqual(creation.status_code, 201)
        contenu = creation.json()
        self.assertEqual(contenu["nom"], "Atelier du soir")
        self.assertTrue(contenu["code"])

        edition = self.client.patch(
            reverse("api_modalite_periscolaire_detail", args=[contenu["id"]]),
            data=json.dumps({"nom": "Étude surveillée", "actif": False}),
            content_type="application/json",
        )
        self.assertEqual(edition.status_code, 200)
        self.assertEqual(edition.json()["nom"], "Étude surveillée")
        self.assertFalse(edition.json()["actif"])
