import datetime

from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Affectation,
    ActiviteTravailComplementaire,
    Animateur,
    Centre,
    ParticipationTravailComplementaire,
)
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_groupe, creer_periode


class TempsTravailComplementaireTests(ConnexionTestCase):
    def setUp(self):
        self.semaine_1 = creer_periode(debut=datetime.date(2026, 7, 6), nom="Été — Semaine 1")
        self.semaine_2 = creer_periode(debut=datetime.date(2026, 7, 13), nom="Été — Semaine 2")
        self.centre = Centre.objects.create(nom="Pacaudière", code="PAC", couleur="#123456")
        self.groupe, _ = creer_groupe(self.centre, nom="Maternelles")
        self.groupe.periodes_scolaires.add(self.semaine_1, self.semaine_2)
        self.julie = Animateur.objects.create(prenom="Julie", nom="Martin", paie_jour="60.00")
        self.gael = Animateur.objects.create(prenom="Gaël", nom="Dupont", paie_jour="70.00")
        self.sans_planning = Animateur.objects.create(prenom="Libre", nom="Personne", paie_jour="50.00")
        self._affecter(self.julie, datetime.date(2026, 7, 6))
        self._affecter(self.gael, datetime.date(2026, 7, 13))

    def _affecter(self, animateur, jour):
        debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
        return Affectation.objects.create(
            animateur=animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

    def _selection(self):
        return f"{self.semaine_1.id},{self.semaine_2.id}"

    def test_liste_uniquement_les_animateurs_affectes_dans_la_selection(self):
        response = self.client.get(reverse("api_temps_travail"), {"periode_ids": self._selection()})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["animateurs"]],
            [self.gael.id, self.julie.id],
        )
        self.assertNotIn(self.sans_planning.id, [item["id"] for item in response.json()["animateurs"]])

    def test_creation_reunion_selectionne_tous_les_animateurs_par_defaut(self):
        response = self.client.post(
            reverse("api_reunions"),
            data={
                "periode_ids": [self.semaine_1.id, self.semaine_2.id],
                "intitule": "Réunion de préparation",
                "date": "2026-07-06",
                "remarque": "Salle commune",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        reunion = ActiviteTravailComplementaire.objects.get(type="reunion")
        self.assertEqual(
            set(reunion.participations.values_list("animateur_id", flat=True)),
            {self.julie.id, self.gael.id},
        )
        julie = next(item for item in response.json()["reunions"][0]["participants"] if item["animateur_id"] == self.julie.id)
        self.assertTrue(julie["deja_affecte"])

    def test_reunion_hors_dates_reste_rattachee_a_la_periode_et_a_la_paie(self):
        response = self.client.post(
            reverse("api_reunions"),
            data={
                "periode_ids": [self.semaine_1.id, self.semaine_2.id],
                "intitule": "Réunion en amont",
                "date": "2026-06-20",
                "participant_ids": [self.julie.id],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        reunion = ActiviteTravailComplementaire.objects.get(type="reunion")
        self.assertEqual(reunion.date, datetime.date(2026, 6, 20))
        self.assertEqual(set(reunion.periodes.values_list("id", flat=True)), {self.semaine_1.id, self.semaine_2.id})

        recap = self.client.get(
            reverse("api_recapitulatif") + f"?periode_ids={self._selection()}"
        ).json()
        julie = next(item for item in recap["animateurs"] if item["id"] == self.julie.id)
        self.assertEqual(julie["jours_affectation"], 1)
        self.assertEqual(julie["jours_reunion"], 1)
        self.assertEqual(julie["jours_travailles"], 2)
        self.assertEqual(julie["paie_totale"], "120.00")

    def test_controle_conflit_utilise_la_date_reelle_hors_periode(self):
        self._affecter(self.julie, datetime.date(2026, 6, 20))

        response = self.client.get(reverse("api_conflits_reunion"), {
            "periode_ids": self._selection(),
            "date": "2026-06-20",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["hors_periode"])
        self.assertEqual(response.json()["animateur_ids"], [self.julie.id])

    def test_modification_et_suppression_reunion_met_a_jour_les_participants(self):
        reunion = ActiviteTravailComplementaire.objects.create(
            type="reunion", intitule="Ancienne réunion", date=datetime.date(2026, 7, 7)
        )
        reunion.periodes.set([self.semaine_1, self.semaine_2])
        ParticipationTravailComplementaire.objects.create(activite=reunion, animateur=self.gael)

        response = self.client.patch(
            reverse("api_reunion_detail", args=[reunion.id]),
            data={
                "periode_ids": [self.semaine_1.id, self.semaine_2.id],
                "intitule": "Réunion corrigée",
                "date": "2026-07-06",
                "participant_ids": [self.julie.id],
                "double_comptage_ids": [self.julie.id],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        participation = reunion.participations.get()
        self.assertEqual(participation.animateur_id, self.julie.id)
        self.assertTrue(participation.autoriser_double_comptage)
        self.assertEqual(self.client.delete(reverse("api_reunion_detail", args=[reunion.id])).status_code, 200)
        self.assertFalse(ActiviteTravailComplementaire.objects.filter(pk=reunion.id).exists())

    def test_enregistre_les_journees_de_preparation_uniquement_pour_les_eligibles(self):
        response = self.client.put(
            reverse("api_preparation_travail"),
            data={
                "periode_ids": [self.semaine_1.id, self.semaine_2.id],
                "attributions": [
                    {"animateur_id": self.julie.id, "nombre_jours": "2", "remarque": "Préparation séjour"},
                    {"animateur_id": self.gael.id, "nombre_jours": "1", "remarque": "Activités"},
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["preparation"][str(self.julie.id)]["nombre_jours"], "2.00")

        invalide = self.client.put(
            reverse("api_preparation_travail"),
            data={
                "periode_ids": [self.semaine_1.id, self.semaine_2.id],
                "attributions": [{"animateur_id": self.sans_planning.id, "nombre_jours": "1"}],
            },
            content_type="application/json",
        )
        self.assertEqual(invalide.status_code, 400)

    def test_recapitulatif_evite_le_doublon_puis_accepte_le_double_comptage(self):
        reunion = ActiviteTravailComplementaire.objects.create(
            type="reunion", intitule="Réunion", date=datetime.date(2026, 7, 6)
        )
        reunion.periodes.set([self.semaine_1, self.semaine_2])
        participation = ParticipationTravailComplementaire.objects.create(
            activite=reunion,
            animateur=self.julie,
        )

        url = reverse("api_recapitulatif") + f"?periode_ids={self._selection()}"
        julie = next(item for item in self.client.get(url).json()["animateurs"] if item["id"] == self.julie.id)
        self.assertEqual(julie["jours_affectation"], 1)
        self.assertEqual(julie["jours_reunion"], 0)
        self.assertEqual(julie["jours_travailles"], 1)

        participation.autoriser_double_comptage = True
        participation.save(update_fields=["autoriser_double_comptage"])
        preparation = ActiviteTravailComplementaire.objects.create(
            type="preparation", intitule="Télétravail / préparation"
        )
        preparation.periodes.set([self.semaine_1, self.semaine_2])
        ParticipationTravailComplementaire.objects.create(
            activite=preparation,
            animateur=self.julie,
            nombre_jours="2.00",
        )

        julie = next(item for item in self.client.get(url).json()["animateurs"] if item["id"] == self.julie.id)
        self.assertEqual(julie["jours_reunion"], 1)
        self.assertEqual(julie["jours_preparation"], 2)
        self.assertEqual(julie["jours_travailles"], 4)
        self.assertEqual(julie["paie_totale"], "240.00")

        reunion.delete()
        julie = next(item for item in self.client.get(url).json()["animateurs"] if item["id"] == self.julie.id)
        self.assertEqual(julie["jours_reunion"], 0)
        self.assertEqual(julie["jours_travailles"], 3)
        self.assertEqual(julie["paie_totale"], "180.00")

    def test_remise_a_zero_supprime_les_journees_de_preparation(self):
        payload = {
            "periode_ids": [self.semaine_1.id, self.semaine_2.id],
            "attributions": [{"animateur_id": self.julie.id, "nombre_jours": "2"}],
        }
        self.client.put(reverse("api_preparation_travail"), data=payload, content_type="application/json")
        payload["attributions"][0]["nombre_jours"] = "0"

        response = self.client.put(
            reverse("api_preparation_travail"), data=payload, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(self.julie.id), response.json()["preparation"])

    def test_prime_estimee_inclut_reunion_et_preparation(self):
        reunion = ActiviteTravailComplementaire.objects.create(
            type="reunion", intitule="Réunion paie", date=datetime.date(2026, 6, 20)
        )
        reunion.periodes.set([self.semaine_1, self.semaine_2])
        ParticipationTravailComplementaire.objects.create(activite=reunion, animateur=self.julie)
        preparation = ActiviteTravailComplementaire.objects.create(
            type="preparation", intitule="Préparation paie"
        )
        preparation.periodes.set([self.semaine_1, self.semaine_2])
        ParticipationTravailComplementaire.objects.create(
            activite=preparation, animateur=self.julie, nombre_jours="2"
        )

        response = self.client.put(
            reverse("api_prime_journaliere"),
            data={
                "animateur_id": self.julie.id,
                "periode_ids": [self.semaine_1.id, self.semaine_2.id],
                "montant": "5",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_jour_avec_prime"], "65.00")
        self.assertEqual(response.json()["total_paie_estime"], "260.00")

    def test_page_planning_contient_le_nouvel_onglet(self):
        response = self.client.get(reverse("planning"))

        self.assertContains(response, "Temps de travail")
        self.assertContains(response, 'id="worktime-periods"')
        self.assertContains(response, 'data-week-picker-mode="multiple"')
        self.assertContains(response, 'id="worktime-preparation-form"')
        self.assertContains(response, 'placeholder="Rechercher un nom ou un prénom"')
        self.assertNotContains(response, 'id="worktime-save-preparation"')
