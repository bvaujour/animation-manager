import datetime
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Affectation, Animateur, AttributionPrime, BaremeCEE, Centre, Contrat,
    Evenement, Formation, HistoriqueStatutAnimateur, ParticipationFormation,
    Qualification, TypePrime,
)
from animateurs.services.contrats import situation_contractuelle_pour_date, type_contrat_pour_date
from animateurs.services.parametres import get_parametres_structure
from animateurs.services.preparation_paie import enrichir_recapitulatif_paie
from animateurs.services.primes import creer_attribution_prime
from animateurs.services.recapitulatif import generer_recapitulatif
from animateurs.services.statuts import situation_statut_pour_date
from animateurs.tests.base import ConnexionTestCase


DEBUT = datetime.date(2026, 7, 1)
FIN = datetime.date(2026, 7, 31)


def _dt(jour):
    return timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))


class PreparationPaieTests(TestCase):
    def setUp(self):
        self.structure = get_parametres_structure()
        self.stagiaire = Qualification.objects.create(nom="Stagiaire Paie", est_statut=True)
        self.diplome = Qualification.objects.create(nom="Diplômé Paie", est_statut=True)
        self.animateur = Animateur.objects.create(
            prenom="Jeanne", nom="Paie", paie_jour=Decimal("999.00")
        )
        self.centre = Centre.objects.create(nom="Centre Paie", code="CP")
        self.autre_centre = Centre.objects.create(nom="Autre centre", code="AC")
        self.groupe = Evenement.objects.create(centre=self.centre, nom="Groupe Paie", permanent=True)
        self.autre_groupe = Evenement.objects.create(
            centre=self.autre_centre, nom="Autre groupe", permanent=True
        )

    def historique(self, statut, date=DEBUT, incertain=False):
        return HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=statut, date_effet=date,
            date_effet_incertaine=incertain,
        )

    def bareme(self, statut, montant, date=DEBUT):
        return BaremeCEE.objects.create(
            structure=self.structure, statut=statut, date_effet=date,
            montant_journalier=Decimal(montant),
        )

    def affecter(self, jour, groupe=None):
        groupe = groupe or self.groupe
        return Affectation.objects.create(
            animateur=self.animateur, centre=groupe.centre, evenement=groupe,
            debut=_dt(jour), fin=_dt(jour + datetime.timedelta(days=1)),
        )

    def preparer(self, debut=DEBUT, fin=FIN):
        recap = generer_recapitulatif(_dt(debut), _dt(fin + datetime.timedelta(days=1)))
        return enrichir_recapitulatif_paie(recap, debut, fin)["animateurs"][0]

    def test_cee_implicite_barreme_date_cp_et_paie_jour_ignoree(self):
        self.historique(self.stagiaire)
        self.historique(self.diplome, DEBUT + datetime.timedelta(days=1))
        self.bareme(self.stagiaire, "48.00")
        self.bareme(self.diplome, "52.00")
        self.affecter(DEBUT)
        self.affecter(DEBUT + datetime.timedelta(days=1))

        ligne = self.preparer()

        self.assertEqual(type_contrat_pour_date(self.animateur, DEBUT), Contrat.TYPE_CEE)
        self.assertFalse(situation_contractuelle_pour_date(self.animateur, DEBUT).explicite)
        self.assertFalse(Contrat.objects.exists())
        self.assertEqual(ligne["base_cee"], "100.00")
        self.assertEqual(ligne["indemnite_cp_cee"], "10.00")
        self.assertEqual(ligne["total_prepare"], "110.00")
        self.assertEqual(ligne["etat_preparation"], "pret")
        self.assertTrue(any(item["code"] == "contrat_implicite" for item in ligne["alertes_paie"]))
        self.assertTrue(all(not item["explicite"] for item in ligne["segments_contractuels"]))
        self.assertNotEqual(ligne["base_cee"], "1998.00")

    def test_statut_ou_bareme_manquant_rend_incomplet_sans_zero_arbitraire(self):
        self.affecter(DEBUT)
        ligne = self.preparer()
        self.assertEqual(ligne["etat_preparation"], "incomplet")
        self.assertIsNone(ligne["total_prepare"])
        self.assertTrue(any(item["code"] == "statut_manquant" for item in ligne["alertes_paie"]))

        self.historique(self.stagiaire)
        ligne = self.preparer()
        self.assertTrue(any(item["code"] == "bareme_manquant" for item in ligne["alertes_paie"]))

    def test_statut_incertain_calcule_mais_demande_verification(self):
        self.historique(self.stagiaire, incertain=True)
        self.bareme(self.stagiaire, "48.00")
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=DEBUT, date_fin=FIN, taux_journalier_reference=Decimal("60.00"),
        )
        self.affecter(DEBUT)
        ligne = self.preparer()
        self.assertEqual(ligne["base_cee"], "48.00")
        self.assertEqual(ligne["etat_preparation"], "a_verifier")

    def test_cee_explicite_adaptation_active_puis_taux_contractuel(self):
        self.historique(self.stagiaire)
        self.historique(self.diplome, DEBUT + datetime.timedelta(days=1))
        self.bareme(self.stagiaire, "48.00")
        self.bareme(self.diplome, "52.00")
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=DEBUT, date_fin=FIN, taux_journalier_reference=Decimal("60.00"),
        )
        self.affecter(DEBUT)
        self.affecter(DEBUT + datetime.timedelta(days=1))
        self.assertEqual(self.preparer()["base_cee"], "100.00")

        self.structure.adapter_taux_cee_changement_statut = False
        self.structure.save()
        self.assertEqual(self.preparer()["base_cee"], "120.00")

    def test_cee_explicite_sans_historique_utilise_le_taux_contractuel(self):
        debut = datetime.date(2026, 8, 24)
        fin = datetime.date(2026, 8, 31)
        self.animateur.prenom = "Malonn"
        self.animateur.nom = "MEMBRE"
        self.animateur.save(update_fields=["prenom", "nom"])
        self.animateur.qualifications.add(self.stagiaire)
        self.bareme(self.stagiaire, "55.00", debut)
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=debut, date_fin=fin,
            taux_journalier_reference=Decimal("52.00"),
        )
        for jour in range(24, 29):
            self.affecter(datetime.date(2026, 8, jour))

        situation = situation_statut_pour_date(self.animateur, debut)
        ligne = self.preparer(debut, fin)

        self.assertEqual(situation.source, "fallback_actuel")
        self.assertFalse(situation.fiable)
        self.assertEqual(ligne["base_cee"], "260.00")
        self.assertEqual(ligne["details_cee"], [{
            "statut": "Taux contractuel", "taux": "52.00", "jours": 5,
            "montant": "260.00",
        }])
        self.assertIsNone(ligne["segments_contractuels"][0]["statut"])
        self.assertEqual(ligne["segments_contractuels"][0]["contrat_date_debut"], "2026-08-24")
        self.assertEqual(ligne["segments_contractuels"][0]["contrat_date_fin"], "2026-08-31")

    def test_cee_explicite_avec_historique_date_conserve_le_bareme(self):
        self.historique(self.stagiaire)
        self.bareme(self.stagiaire, "55.00")
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=DEBUT, date_fin=FIN, taux_journalier_reference=Decimal("52.00"),
        )
        self.affecter(DEBUT)

        ligne = self.preparer()

        self.assertEqual(ligne["base_cee"], "55.00")
        self.assertEqual(ligne["details_cee"][0]["statut"], self.stagiaire.nom)

    def test_permanent_sans_salaire_reste_pret_et_hors_calcul(self):
        type_permanent = self.structure.types_contrats.get(code="permanent")
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_PERMANENT,
            type_contrat_ref=type_permanent, date_debut=None, date_fin=None,
        )
        self.affecter(DEBUT)

        ligne = self.preparer()

        self.assertEqual(ligne["etat_preparation"], "pret")
        self.assertTrue(ligne["paie_habituelle"])
        self.assertEqual(ligne["jours_travailles"], 1)
        self.assertIsNone(ligne["base_preparee"])
        self.assertIsNone(ligne["segments_contractuels"][0]["contrat_date_debut"])
        self.assertIsNone(ligne["segments_contractuels"][0]["contrat_date_fin"])
        self.assertFalse(any(item["code"] == "salaire_mensuel_manquant" for item in ligne["alertes_paie"]))

    def test_cdd_mois_complet_compte_une_base_unique_malgre_deux_centres(self):
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CDD,
            date_debut=DEBUT, date_fin=FIN, salaire_mensuel_reference=Decimal("1850.00"),
        )
        self.affecter(DEBUT)
        self.affecter(DEBUT + datetime.timedelta(days=1), self.autre_groupe)
        ligne = self.preparer()
        self.assertEqual(ligne["base_mensuelle_reference"], "1850.00")
        self.assertEqual(ligne["total_prepare"], "1850.00")
        self.assertEqual(ligne["base_cee"], "0.00")
        self.assertEqual(len(ligne["centres"]), 2)

    def test_cdd_partiel_et_apprentissage_ne_sont_jamais_prorates(self):
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_APPRENTISSAGE,
            date_debut=datetime.date(2026, 7, 15), date_fin=FIN,
            salaire_mensuel_reference=Decimal("900.00"),
        )
        self.affecter(datetime.date(2026, 7, 15))
        ligne = self.preparer(datetime.date(2026, 7, 15), FIN)
        self.assertEqual(ligne["salaire_mensuel_reference"], "900.00")
        self.assertIsNone(ligne["base_mensuelle_reference"])
        self.assertEqual(ligne["base_cee"], "0.00")
        self.assertEqual(ligne["etat_preparation"], "a_verifier")

    def test_salaire_mensuel_manquant_est_incomplet(self):
        contrat = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CDD,
            date_debut=DEBUT, date_fin=FIN, salaire_mensuel_reference=Decimal("1800.00"),
        )
        Contrat.objects.filter(pk=contrat.pk).update(salaire_mensuel_reference=None)
        self.affecter(DEBUT)
        ligne = self.preparer()
        self.assertEqual(ligne["etat_preparation"], "incomplet")
        self.assertTrue(any(item["code"] == "salaire_mensuel_manquant" for item in ligne["alertes_paie"]))

    def test_taux_contractuel_cee_manquant_est_signale_sans_modifier_le_calcul(self):
        self.structure.adapter_taux_cee_changement_statut = False
        self.structure.save(update_fields=["adapter_taux_cee_changement_statut"])
        contrat = Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=DEBUT, date_fin=FIN, taux_journalier_reference=Decimal("52.00"),
        )
        Contrat.objects.filter(pk=contrat.pk).update(taux_journalier_reference=None)
        self.affecter(DEBUT)

        ligne = self.preparer()

        self.assertEqual(ligne["etat_preparation"], "incomplet")
        self.assertIsNone(ligne["base_preparee"])
        self.assertTrue(any(
            item["code"] == "taux_contractuel_manquant" for item in ligne["alertes_paie"]
        ))

    def test_transition_cee_implicite_vers_cdd_est_segmentee_sans_retroactivite(self):
        self.historique(self.stagiaire)
        self.bareme(self.stagiaire, "50.00")
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CDD,
            date_debut=datetime.date(2026, 7, 16), date_fin=FIN,
            salaire_mensuel_reference=Decimal("1800.00"),
        )
        self.affecter(datetime.date(2026, 7, 15))
        self.affecter(datetime.date(2026, 7, 16))
        ligne = self.preparer()
        self.assertEqual(ligne["base_cee"], "50.00")
        self.assertEqual([item["type_contrat"] for item in ligne["segments_contractuels"]], ["cee", "cdd"])
        self.assertIsNone(ligne["base_mensuelle_reference"])

    def _contrats_barbara(self):
        self.animateur.prenom = "Barbara"
        self.animateur.nom = "LAPOILE"
        self.animateur.save(update_fields=["prenom", "nom"])
        self.structure.adapter_taux_cee_changement_statut = False
        self.structure.save(update_fields=["adapter_taux_cee_changement_statut"])
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_CEE,
            date_debut=datetime.date(2026, 8, 1), date_fin=datetime.date(2026, 8, 20),
            taux_journalier_reference=Decimal("52.00"),
        )
        Contrat.objects.create(
            animateur=self.animateur, type_contrat=Contrat.TYPE_APPRENTISSAGE,
            date_debut=datetime.date(2026, 8, 24), date_fin=datetime.date(2026, 8, 31),
            salaire_mensuel_reference=Decimal("802.82"),
        )

    def test_barbara_jours_cee_utilisent_le_taux_contractuel(self):
        self._contrats_barbara()
        for jour in range(3, 8):
            self.affecter(datetime.date(2026, 8, jour))

        ligne = self.preparer(datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))

        self.assertEqual(ligne["types_contrat"], [Contrat.TYPE_CEE])
        self.assertEqual(ligne["type_contrat_libelle"], "CEE")
        self.assertEqual(ligne["base_cee"], "260.00")
        self.assertEqual(ligne["base_preparee"], "260.00")
        self.assertIsNone(ligne["salaire_mensuel_reference"])

    def test_barbara_jours_apprentissage_exposent_la_reference_sans_faux_zero(self):
        self._contrats_barbara()
        for jour in range(24, 29):
            self.affecter(datetime.date(2026, 8, jour))

        ligne = self.preparer(datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))

        self.assertEqual(ligne["types_contrat"], [Contrat.TYPE_APPRENTISSAGE])
        self.assertEqual(ligne["type_contrat_libelle"], "Apprentissage / alternance")
        self.assertEqual(ligne["salaire_mensuel_reference"], "802.82")
        self.assertIsNone(ligne["base_preparee"])
        self.assertTrue(ligne["reference_mensuelle_a_ajuster"])
        self.assertEqual(ligne["etat_preparation"], "a_verifier")
        self.assertEqual(ligne["segments_contractuels"][0]["contrat_date_debut"], "2026-08-24")
        self.assertEqual(ligne["segments_contractuels"][0]["contrat_date_fin"], "2026-08-31")

    def test_barbara_jours_mixtes_conservent_base_cee_et_reference_apprentissage(self):
        self._contrats_barbara()
        for jour in (18, 19, 20, 24, 25):
            self.affecter(datetime.date(2026, 8, jour))

        ligne = self.preparer(datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))

        self.assertEqual(ligne["types_contrat"], [Contrat.TYPE_CEE, Contrat.TYPE_APPRENTISSAGE])
        self.assertEqual(ligne["base_cee"], "156.00")
        self.assertEqual(ligne["base_preparee"], "156.00")
        self.assertEqual(ligne["salaire_mensuel_reference"], "802.82")
        self.assertTrue(ligne["reference_mensuelle_a_ajuster"])
        self.assertEqual(
            [item["type_contrat"] for item in ligne["segments_contractuels"]],
            [Contrat.TYPE_CEE, Contrat.TYPE_APPRENTISSAGE],
        )

    def test_formations_present_absent_et_a_cloturer(self):
        self.historique(self.stagiaire)
        self.bareme(self.stagiaire, "50.00")
        self.affecter(FIN)
        terminee = Formation.objects.create(
            intitule="Formation suivie", date_debut=DEBUT, date_fin=DEBUT + datetime.timedelta(days=1),
            statut=Formation.STATUT_TERMINEE,
        )
        ParticipationFormation.objects.create(
            formation=terminee, animateur=self.animateur,
            presence=ParticipationFormation.PRESENCE_PRESENT,
        )
        a_cloturer = Formation.objects.create(
            intitule="Formation à valider", date_debut=DEBUT, date_fin=DEBUT,
        )
        ParticipationFormation.objects.create(
            formation=a_cloturer, animateur=self.animateur,
            presence=ParticipationFormation.PRESENCE_ABSENT,
        )
        ligne = self.preparer()
        self.assertEqual(ligne["jours_formation"], 2)
        self.assertTrue(any(item["code"] == "formation_a_cloturer" for item in ligne["alertes_paie"]))
        self.assertEqual(ligne["etat_preparation"], "a_verifier")


class AttributionPrimeTests(ConnexionTestCase):
    def setUp(self):
        self.structure = get_parametres_structure()
        TypePrime.objects.all().update(active=False)
        self.statut = Qualification.objects.create(nom="Statut primes paie", est_statut=True)
        self.animateur = Animateur.objects.create(prenom="Ambre", nom="Prime paie")
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=self.statut, date_effet=DEBUT
        )
        self.centre_prime = Centre.objects.create(nom="Centre éligibilité prime", code="CEP")
        self.groupe_prime = Evenement.objects.create(
            centre=self.centre_prime, nom="Groupe éligibilité prime", permanent=True
        )
        self.travailler(self.animateur, DEBUT)

    def travailler(self, animateur, jour):
        return Affectation.objects.create(
            animateur=animateur, centre=self.centre_prime, evenement=self.groupe_prime,
            debut=_dt(jour), fin=_dt(jour + datetime.timedelta(days=1)),
        )

    def type_prime(self, *, mode="jour", variable=False, contrats=None, active=True):
        prime = TypePrime.objects.create(
            structure=self.structure, nom=f"Prime {mode} {variable} {TypePrime.objects.count()}",
            active=active, mode_calcul=mode,
            type_montant=TypePrime.MONTANT_VARIABLE_PLAFONNE if variable else TypePrime.MONTANT_FIXE,
            montant_maximum=Decimal("7.00") if variable else None,
            montant_fixe=None if variable else Decimal("10.00"),
            contrats_eligibles=contrats or [Contrat.TYPE_CEE], tous_statuts=True,
        )
        return prime

    def test_fixe_variable_plafond_et_montant_historique(self):
        fixe = self.type_prime()
        attribution = creer_attribution_prime(
            animateur=self.animateur, type_prime=fixe, date_debut=DEBUT,
            date_fin=DEBUT + datetime.timedelta(days=1),
        )
        self.assertEqual(attribution.montant_total, Decimal("20.00"))
        fixe.montant_fixe = Decimal("20.00")
        fixe.save()
        attribution.refresh_from_db()
        self.assertEqual(attribution.montant_unitaire, Decimal("10.00"))

        variable = self.type_prime(variable=True)
        with self.assertRaisesMessage(Exception, "compris entre"):
            creer_attribution_prime(
                animateur=self.animateur, type_prime=variable, date_debut=DEBUT,
                date_fin=DEBUT, montant="8.00",
            )

    def test_budget_requetes_mutations_prime_ciblees(self):
        prime = self.type_prime(variable=True)
        payload = {
            "animateur_id": self.animateur.id, "type_prime_id": prime.id,
            "jours": [DEBUT.isoformat()], "montant": "5.00",
            "periode_debut": DEBUT.isoformat(), "periode_fin": FIN.isoformat(),
        }
        with CaptureQueriesContext(connection) as contexte:
            creation = self.client.post(reverse("api_attributions_primes"), data=json.dumps(payload), content_type="application/json")
        self.assertLessEqual(len(contexte), 25)
        detail = reverse("api_attribution_prime_detail", args=[creation.json()["attributions"][0]["id"]])
        with CaptureQueriesContext(connection) as contexte:
            modification = self.client.patch(detail, data=json.dumps({**payload, "montant": "4.00"}), content_type="application/json")
        self.assertLessEqual(len(contexte), 27)
        detail = reverse("api_attribution_prime_detail", args=[modification.json()["attributions"][0]["id"]])
        with CaptureQueriesContext(connection) as contexte:
            self.client.delete(detail + f"?date_debut={DEBUT.isoformat()}&date_fin={FIN.isoformat()}")
        self.assertLessEqual(len(contexte), 8)

    def test_deux_types_primes_se_cumulent_sur_les_memes_dates(self):
        prime_a = self.type_prime()
        prime_b = self.type_prime()
        attribution_a = creer_attribution_prime(
            animateur=self.animateur, type_prime=prime_a,
            date_debut=DEBUT, date_fin=DEBUT,
        )
        attribution_b = creer_attribution_prime(
            animateur=self.animateur, type_prime=prime_b,
            date_debut=DEBUT, date_fin=DEBUT,
        )
        self.assertNotEqual(attribution_a.type_prime_id, attribution_b.type_prime_id)
        self.assertEqual(
            set(AttributionPrime.objects.filter(animateur=self.animateur).values_list(
                "type_prime_id", flat=True
            )),
            {prime_a.id, prime_b.id},
        )

    def test_meme_prime_refuse_un_montant_different_sur_les_memes_jours(self):
        jours = [datetime.date(2026, 7, 6) + datetime.timedelta(days=index) for index in range(5)]
        for jour in jours:
            self.travailler(self.animateur, jour)
        prime = self.type_prime(variable=True)
        payload = {
            "animateur_id": self.animateur.id,
            "type_prime_id": prime.id,
            "jours": [jour.isoformat() for jour in jours],
            "periode_debut": DEBUT.isoformat(),
            "periode_fin": FIN.isoformat(),
            "jours_eligibles": [DEBUT.isoformat(), *[jour.isoformat() for jour in jours]],
        }
        premiere = self.client.post(
            reverse("api_attributions_primes"),
            data=json.dumps({**payload, "montant": "5.00"}),
            content_type="application/json",
        )
        self.assertEqual(premiere.status_code, 201)
        contexte = premiere.json()["synthese"]["contexte_prime"]
        self.assertEqual(len(contexte["jours_eligibles"]), 6)
        self.assertEqual(len(contexte["jours_deja_attribues"]), 5)
        self.assertEqual(contexte["jours_disponibles"], [DEBUT.isoformat()])

        seconde = self.client.post(
            reverse("api_attributions_primes"),
            data=json.dumps({**payload, "montant": "3.00"}),
            content_type="application/json",
        )
        self.assertEqual(seconde.status_code, 400)
        self.assertIn("Utilisez Modifier", seconde.json()["error"])
        attribution = AttributionPrime.objects.get(animateur=self.animateur, type_prime=prime)
        self.assertEqual(attribution.montant_total, Decimal("25.00"))

    def test_meme_prime_refuse_un_chevauchement_partiel(self):
        prime = self.type_prime(variable=True)
        creer_attribution_prime(
            animateur=self.animateur, type_prime=prime,
            date_debut=datetime.date(2026, 7, 6), date_fin=datetime.date(2026, 7, 10),
            montant="5.00",
        )
        with self.assertRaisesMessage(Exception, "déjà attribuée"):
            creer_attribution_prime(
                animateur=self.animateur, type_prime=prime,
                date_debut=datetime.date(2026, 7, 8), date_fin=datetime.date(2026, 7, 15),
                montant="3.00",
            )

    def test_contexte_soustrait_cinq_jours_deja_attribues_sur_dix(self):
        jours = [
            datetime.date(2026, 7, jour)
            for jour in (6, 7, 8, 9, 10, 13, 14, 15, 16, 17)
        ]
        animateur = Animateur.objects.create(prenom="Ange", nom="Disponibilité prime")
        HistoriqueStatutAnimateur.objects.create(
            animateur=animateur, statut=self.statut, date_effet=jours[0]
        )
        for jour in jours:
            self.travailler(animateur, jour)
        prime = self.type_prime(variable=True)
        creer_attribution_prime(
            animateur=animateur, type_prime=prime,
            date_debut=jours[0], date_fin=jours[4], montant="5.00",
        )

        ligne = next(
            item for item in self.eligibilites_api()["animateurs"]
            if item["id"] == animateur.id
        )
        contexte = next(item for item in ligne["primes"] if item["id"] == prime.id)
        self.assertEqual(len(contexte["jours_eligibles"]), 10)
        self.assertEqual(contexte["jours_deja_attribues"], [jour.isoformat() for jour in jours[:5]])
        self.assertEqual(contexte["jours_disponibles"], [jour.isoformat() for jour in jours[5:]])
        self.assertEqual(contexte["resume_attributions"]["quantite"], 5)
        self.assertEqual(contexte["resume_attributions"]["montant_total"], "25.00")
        self.assertEqual(len(contexte["semaines_eligibles"]), 1)
        self.assertEqual(contexte["semaines_eligibles"][0]["jours_eligibles"], [
            jour.isoformat() for jour in jours[5:]
        ])

    def test_resume_prime_journaliere_signale_plusieurs_montants_sans_moyenne(self):
        jours = [datetime.date(2026, 7, 6) + datetime.timedelta(days=index) for index in range(5)]
        jours += [datetime.date(2026, 7, 13) + datetime.timedelta(days=index) for index in range(5)]
        animateur = Animateur.objects.create(prenom="Ange", nom="Résumé variable")
        HistoriqueStatutAnimateur.objects.create(
            animateur=animateur, statut=self.statut, date_effet=jours[0]
        )
        for jour in jours:
            self.travailler(animateur, jour)
        prime = self.type_prime(variable=True)
        creer_attribution_prime(
            animateur=animateur, type_prime=prime,
            date_debut=jours[0], date_fin=jours[4], montant="5.00",
        )
        creer_attribution_prime(
            animateur=animateur, type_prime=prime,
            date_debut=jours[5], date_fin=jours[9], montant="3.00",
        )

        ligne = next(item for item in self.eligibilites_api()["animateurs"] if item["id"] == animateur.id)
        resume = next(item for item in ligne["primes"] if item["id"] == prime.id)["resume_attributions"]
        self.assertEqual(resume["quantite"], 10)
        self.assertEqual(resume["montant_total"], "40.00")
        self.assertIsNone(resume["montant_unitaire"])
        self.assertTrue(resume["montants_variables"])

    def test_modifier_le_montant_exclut_attribution_courante(self):
        prime = self.type_prime(variable=True)
        attribution = creer_attribution_prime(
            animateur=self.animateur, type_prime=prime,
            date_debut=DEBUT, date_fin=DEBUT, montant="5.00",
        )
        response = self.client.patch(
            reverse("api_attribution_prime_detail", args=[attribution.id]),
            data=json.dumps({
                "montant": "3.00", "periode_debut": DEBUT.isoformat(),
                "periode_fin": FIN.isoformat(),
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        finale = AttributionPrime.objects.get(animateur=self.animateur, type_prime=prime)
        self.assertEqual(finale.montant_total, Decimal("3.00"))

    def test_meme_prime_hebdomadaire_et_mensuelle_refusent_meme_occurrence(self):
        for mode in (TypePrime.MODE_SEMAINE, TypePrime.MODE_MOIS):
            prime = self.type_prime(mode=mode, variable=True)
            creer_attribution_prime(
                animateur=self.animateur, type_prime=prime,
                date_debut=datetime.date(2026, 7, 6), date_fin=datetime.date(2026, 7, 10),
                montant="5.00",
            )
            with self.assertRaisesMessage(Exception, "déjà attribuée"):
                creer_attribution_prime(
                    animateur=self.animateur, type_prime=prime,
                    date_debut=datetime.date(2026, 7, 8), date_fin=datetime.date(2026, 7, 8),
                    montant="3.00",
                )

    def test_prime_hors_assiette_cp_et_visible_sans_affectation_supplementaire(self):
        BaremeCEE.objects.create(
            structure=self.structure, statut=self.statut, date_effet=DEBUT,
            montant_journalier=Decimal("50.00"),
        )
        centre = Centre.objects.create(nom="Centre prime", code="PR")
        groupe = Evenement.objects.create(centre=centre, nom="Groupe prime", permanent=True)
        Affectation.objects.create(
            animateur=self.animateur, centre=centre, evenement=groupe,
            debut=_dt(DEBUT), fin=_dt(DEBUT + datetime.timedelta(days=1)),
        )
        prime = self.type_prime(mode="forfait")
        creer_attribution_prime(
            animateur=self.animateur, type_prime=prime, date_debut=DEBUT, date_fin=DEBUT
        )
        recap = generer_recapitulatif(_dt(DEBUT), _dt(DEBUT + datetime.timedelta(days=1)))
        ligne = enrichir_recapitulatif_paie(recap, DEBUT, DEBUT)["animateurs"][0]
        self.assertEqual(ligne["base_cee"], "50.00")
        self.assertEqual(ligne["indemnite_cp_cee"], "5.00")
        self.assertEqual(ligne["montant_primes_preparees"], "10.00")
        self.assertEqual(ligne["total_prepare"], "65.00")

    def test_modes_jour_semaine_mois_forfait(self):
        for mode in ("jour", "semaine", "mois", "forfait"):
            prime = self.type_prime(mode=mode)
            item = creer_attribution_prime(
                animateur=self.animateur, type_prime=prime, date_debut=DEBUT,
                date_fin=DEBUT + datetime.timedelta(days=2),
            )
            attendu = Decimal("30.00") if mode == "jour" else Decimal("10.00")
            self.assertEqual(item.montant_total, attendu)

    def test_cee_implicite_eligible_et_cdd_refuse(self):
        cee = self.type_prime()
        cdd = self.type_prime(contrats=[Contrat.TYPE_CDD])
        self.assertIsNotNone(creer_attribution_prime(
            animateur=self.animateur, type_prime=cee, date_debut=DEBUT, date_fin=DEBUT
        ))
        with self.assertRaisesMessage(Exception, "n'est pas éligible"):
            creer_attribution_prime(
                animateur=self.animateur, type_prime=cdd, date_debut=DEBUT, date_fin=DEBUT
            )

    def test_cdd_apprentissage_statut_restreint_et_prime_inactive(self):
        for index, type_contrat in enumerate((Contrat.TYPE_CDD, Contrat.TYPE_APPRENTISSAGE)):
            animateur = Animateur.objects.create(prenom=f"Mensuel{index}", nom="Prime")
            HistoriqueStatutAnimateur.objects.create(
                animateur=animateur, statut=self.statut, date_effet=DEBUT
            )
            Contrat.objects.create(
                animateur=animateur, type_contrat=type_contrat, date_debut=DEBUT,
                date_fin=FIN, salaire_mensuel_reference=Decimal("1000.00"),
            )
            prime = self.type_prime(contrats=[type_contrat])
            self.assertIsNotNone(creer_attribution_prime(
                animateur=animateur, type_prime=prime, date_debut=DEBUT, date_fin=DEBUT
            ))
        inactive = self.type_prime(active=False)
        with self.assertRaisesMessage(Exception, "inactive"):
            creer_attribution_prime(
                animateur=self.animateur, type_prime=inactive, date_debut=DEBUT, date_fin=DEBUT
            )

    def test_api_creation_modification_suppression_et_permissions(self):
        prime = self.type_prime(variable=True)
        creation = self.client.post(reverse("api_attributions_primes"), data=json.dumps({
            "animateur_id": self.animateur.id, "type_prime_id": prime.id,
            "date_debut": DEBUT.isoformat(), "date_fin": DEBUT.isoformat(), "montant": "5.00",
            "periode_debut": DEBUT.isoformat(), "periode_fin": FIN.isoformat(),
        }), content_type="application/json")
        self.assertEqual(creation.status_code, 201)
        self.assertEqual(creation.json()["synthese"]["montant_total"], "5.00")
        self.assertEqual(creation.json()["synthese"]["animateur_id"], self.animateur.id)
        detail = reverse("api_attribution_prime_detail", args=[creation.json()["id"]])
        modification = self.client.patch(detail, data=json.dumps({
            "montant": "6.00", "periode_debut": DEBUT.isoformat(),
            "periode_fin": FIN.isoformat(),
        }), content_type="application/json")
        self.assertEqual(modification.status_code, 200)
        self.assertEqual(modification.json()["montant_unitaire"], "6.00")
        self.assertEqual(modification.json()["synthese"]["montant_total"], "6.00")
        suppression = self.client.delete(
            reverse("api_attribution_prime_detail", args=[modification.json()["id"]]),
            {"date_debut": DEBUT.isoformat(), "date_fin": FIN.isoformat()},
        )
        self.assertEqual(suppression.status_code, 200)
        self.assertEqual(suppression.json()["synthese"]["montant_total"], "0.00")
        simple = get_user_model().objects.create_user(username="sans-paie", password="secret")
        self.client.force_login(simple)
        self.assertEqual(self.client.post(reverse("api_attributions_primes"), data="{}", content_type="application/json").status_code, 403)

    def eligibilites_api(self, debut=DEBUT, fin=FIN):
        response = self.client.get(reverse("api_attributions_primes"), {
            "date_debut": debut.isoformat(), "date_fin": fin.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def primes_eligibles_ligne(self, ligne):
        return [
            prime
            for semaine in ligne.get("semaines", [])
            for prime in semaine["primes_eligibles"]
        ] + ligne.get("primes_periode", [])

    def test_api_filtre_animateurs_et_primes_personnellement_eligibles(self):
        prime_cee = self.type_prime()
        prime_inactive = self.type_prime(active=False)
        apprenti = Animateur.objects.create(prenom="Barbara", nom="Apprentissage")
        Contrat.objects.create(
            animateur=apprenti, type_contrat=Contrat.TYPE_APPRENTISSAGE,
            date_debut=DEBUT, date_fin=FIN, salaire_mensuel_reference=Decimal("900"),
        )
        self.travailler(apprenti, DEBUT)

        data = self.eligibilites_api()
        par_id = {item["id"]: item for item in data["animateurs"]}
        self.assertIn(self.animateur.id, par_id)  # CEE implicite
        self.assertEqual({item["id"] for item in self.primes_eligibles_ligne(par_id[self.animateur.id])}, {prime_cee.id})
        self.assertNotIn(apprenti.id, par_id)
        self.assertNotIn(prime_inactive.id, {item["id"] for item in data["types_primes"]})

    def test_api_permanent_suit_uniquement_la_configuration_typeprime(self):
        permanent = Animateur.objects.create(prenom="Perrine", nom="Permanent")
        type_permanent = self.structure.types_contrats.get(code="permanent")
        Contrat.objects.create(
            animateur=permanent, type_contrat=Contrat.TYPE_PERMANENT,
            type_contrat_ref=type_permanent, date_debut=None, date_fin=None,
        )
        self.travailler(permanent, DEBUT)
        self.type_prime()  # CEE uniquement
        self.assertNotIn(permanent.id, {item["id"] for item in self.eligibilites_api()["animateurs"]})

        prime_permanent = self.type_prime(contrats=[Contrat.TYPE_PERMANENT])
        prime_permanent.types_contrats_eligibles.add(type_permanent)
        par_id = {item["id"]: item for item in self.eligibilites_api()["animateurs"]}
        self.assertEqual({item["id"] for item in self.primes_eligibles_ligne(par_id[permanent.id])}, {prime_permanent.id})

    def test_api_segmente_un_changement_de_contrat(self):
        debut = datetime.date(2026, 8, 1)
        fin = datetime.date(2026, 8, 31)
        mixte = Animateur.objects.create(prenom="Mixte", nom="Contrats")
        HistoriqueStatutAnimateur.objects.create(
            animateur=mixte, statut=self.statut, date_effet=debut
        )
        Contrat.objects.create(
            animateur=mixte, type_contrat=Contrat.TYPE_CEE,
            date_debut=debut, date_fin=datetime.date(2026, 8, 15),
            taux_journalier_reference=Decimal("50"),
        )
        Contrat.objects.create(
            animateur=mixte, type_contrat=Contrat.TYPE_APPRENTISSAGE,
            date_debut=datetime.date(2026, 8, 16), date_fin=fin,
            salaire_mensuel_reference=Decimal("900"),
        )
        for numero in range(1, 21):
            self.travailler(mixte, datetime.date(2026, 8, numero))
        prime = self.type_prime()
        ligne = next(item for item in self.eligibilites_api(debut, fin)["animateurs"] if item["id"] == mixte.id)
        jours = {
            jour
            for item in self.primes_eligibles_ligne(ligne) if item["id"] == prime.id
            for jour in item["jours_eligibles"]
        }
        self.assertEqual(jours, {datetime.date(2026, 8, numero).isoformat() for numero in range(1, 16)})

    def test_api_statut_restreint_commence_a_la_date_du_changement(self):
        diplome = Qualification.objects.create(nom="Diplômé prime contextuelle", est_statut=True)
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=diplome, date_effet=DEBUT + datetime.timedelta(days=14)
        )
        self.travailler(self.animateur, DEBUT + datetime.timedelta(days=14))
        prime = self.type_prime()
        prime.tous_statuts = False
        prime.save()
        prime.statuts_eligibles.add(diplome)

        ligne = next(item for item in self.eligibilites_api()["animateurs"] if item["id"] == self.animateur.id)
        eligible = next(item for item in self.primes_eligibles_ligne(ligne) if item["id"] == prime.id)
        self.assertEqual(eligible["segments_eligibles"][0]["date_debut"], (DEBUT + datetime.timedelta(days=14)).isoformat())

    def test_attribution_historique_reste_listee_apres_desactivation(self):
        prime = self.type_prime()
        attribution = creer_attribution_prime(
            animateur=self.animateur, type_prime=prime, date_debut=DEBUT, date_fin=DEBUT
        )
        prime.active = False
        prime.save()
        data = self.eligibilites_api()
        self.assertIn(attribution.id, {item["id"] for item in data["attributions"]})
        self.assertNotIn(prime.id, {item["id"] for item in data["types_primes"]})

    def test_api_ne_retourne_que_les_semaines_reellement_travaillees(self):
        animateur = Animateur.objects.create(prenom="Ange", nom="Semaines")
        HistoriqueStatutAnimateur.objects.create(animateur=animateur, statut=self.statut, date_effet=DEBUT)
        for jour in (datetime.date(2026, 7, 6), datetime.date(2026, 7, 13), datetime.date(2026, 7, 27)):
            self.travailler(animateur, jour)
        self.type_prime()
        ligne = next(item for item in self.eligibilites_api()["animateurs"] if item["id"] == animateur.id)
        self.assertEqual([item["date_debut"] for item in ligne["semaines"]], [
            "2026-07-06", "2026-07-13", "2026-07-27",
        ])
        self.assertEqual([len(item["jours_travailles"]) for item in ligne["semaines"]], [1, 1, 1])

    def test_api_propose_cinq_jours_cee_explicite_et_cee_par_defaut(self):
        prime = self.type_prime(mode=TypePrime.MODE_JOUR)
        lundi = datetime.date(2026, 7, 6)
        animateurs = []
        for prenom, explicite in (("Célia", True), ("Diane", False)):
            animateur = Animateur.objects.create(prenom=prenom, nom="Semaine éligible")
            HistoriqueStatutAnimateur.objects.create(
                animateur=animateur, statut=self.statut, date_effet=lundi
            )
            if explicite:
                Contrat.objects.create(
                    animateur=animateur, type_contrat=Contrat.TYPE_CEE,
                    date_debut=lundi, date_fin=lundi + datetime.timedelta(days=4),
                    taux_journalier_reference=Decimal("50.00"),
                )
            for decalage in range(5):
                self.travailler(animateur, lundi + datetime.timedelta(days=decalage))
            animateurs.append(animateur)

        par_id = {item["id"]: item for item in self.eligibilites_api()["animateurs"]}
        for animateur in animateurs:
            semaine = par_id[animateur.id]["semaines"][0]
            self.assertEqual(len(semaine["jours_travailles"]), 5)
            contexte = next(item for item in semaine["primes_eligibles"] if item["id"] == prime.id)
            self.assertEqual(len(contexte["jours_eligibles"]), 5)

    def test_api_periodicite_repartit_sans_supprimer_eligibilite(self):
        primes = {
            mode: self.type_prime(mode=mode)
            for mode in (
                TypePrime.MODE_JOUR, TypePrime.MODE_SEMAINE,
                TypePrime.MODE_MOIS, TypePrime.MODE_FORFAIT,
            )
        }
        ligne = next(
            item for item in self.eligibilites_api()["animateurs"]
            if item["id"] == self.animateur.id
        )
        self.assertEqual(
            {item["id"] for item in ligne["semaines"][0]["primes_eligibles"]},
            {primes[TypePrime.MODE_JOUR].id, primes[TypePrime.MODE_SEMAINE].id},
        )
        self.assertEqual(
            {item["id"] for item in ligne["primes_periode"]},
            {primes[TypePrime.MODE_MOIS].id, primes[TypePrime.MODE_FORFAIT].id},
        )
        contextes = {item["id"]: item for item in ligne["primes"]}
        self.assertEqual(contextes[primes[TypePrime.MODE_JOUR].id]["niveaux_saisie"], [
            "mois", "semaine", "jour",
        ])
        self.assertEqual(contextes[primes[TypePrime.MODE_SEMAINE].id]["niveaux_saisie"], [
            "mois", "semaine",
        ])
        self.assertEqual(contextes[primes[TypePrime.MODE_MOIS].id]["niveaux_saisie"], ["mois"])
        self.assertEqual(contextes[primes[TypePrime.MODE_FORFAIT].id]["niveaux_saisie"], [])
        self.assertEqual(
            contextes[primes[TypePrime.MODE_JOUR].id]["semaines_eligibles"][0]["jours_eligibles"],
            [DEBUT.isoformat()],
        )

    def test_prime_journaliere_accepte_uniquement_les_jours_choisis_et_travailles(self):
        lundi = datetime.date(2026, 7, 6)
        mercredi = datetime.date(2026, 7, 8)
        self.travailler(self.animateur, lundi)
        self.travailler(self.animateur, mercredi)
        prime = self.type_prime()
        response = self.client.post(reverse("api_attributions_primes"), data=json.dumps({
            "animateur_id": self.animateur.id, "type_prime_id": prime.id,
            "jours": [lundi.isoformat(), mercredi.isoformat()],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["attributions"]), 2)
        self.assertEqual(sum((item.montant_total for item in AttributionPrime.objects.filter(type_prime=prime)), Decimal("0")), Decimal("20.00"))

    def test_niveau_mois_journalier_conserve_les_dix_huit_jours_reels(self):
        jours = [
            datetime.date(2026, 7, numero)
            for numero in (7, 8, 9, 10, 13, 15, 16, 17, 20, 21, 22, 23, 24, 27, 28, 29, 30, 31)
        ]
        animateur = Animateur.objects.create(prenom="Cassidy", nom="Détail mois")
        HistoriqueStatutAnimateur.objects.create(
            animateur=animateur, statut=self.statut, date_effet=jours[0]
        )
        for jour in jours:
            self.travailler(animateur, jour)
        prime = self.type_prime(variable=True)
        response = self.client.post(reverse("api_attributions_primes"), data=json.dumps({
            "animateur_id": animateur.id, "type_prime_id": prime.id,
            "jours": [jour.isoformat() for jour in jours], "montant": "5.00",
        }), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            sum(AttributionPrime.objects.filter(
                animateur=animateur, type_prime=prime
            ).values_list("montant_total", flat=True), Decimal("0.00")),
            Decimal("90.00"),
        )

    def test_dix_jours_a_cinq_euros_creent_deux_segments_et_cinquante_euros(self):
        jours = [
            datetime.date(2026, 7, jour)
            for jour in (6, 7, 8, 9, 10, 13, 14, 15, 16, 17)
        ]
        animateur = Animateur.objects.create(prenom="Ange", nom="Régression doublons")
        HistoriqueStatutAnimateur.objects.create(
            animateur=animateur, statut=self.statut, date_effet=jours[0]
        )
        for jour in jours:
            self.travailler(animateur, jour)
        prime = self.type_prime(variable=True)
        payload = {
            "animateur_id": animateur.id, "type_prime_id": prime.id,
            "jours": [jour.isoformat() for jour in jours], "montant": "5.00",
        }
        response = self.client.post(
            reverse("api_attributions_primes"), data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            [item["nombre_jours"] for item in response.json()["attributions"]],
            [5, 5],
        )
        attributions = AttributionPrime.objects.filter(animateur=animateur, type_prime=prime)
        self.assertEqual(list(attributions.order_by("date_debut").values_list(
            "date_debut", "date_fin", "montant_unitaire", "montant_total"
        )), [
            (jours[0], jours[4], Decimal("5.00"), Decimal("25.00")),
            (jours[5], jours[9], Decimal("5.00"), Decimal("25.00")),
        ])
        self.assertEqual(sum(attributions.values_list("montant_total", flat=True)), Decimal("50.00"))
        resume = response.json()["synthese"]["contexte_prime"]["resume_attributions"]
        self.assertEqual(resume, {
            "nombre_attributions": 2,
            "quantite": 10,
            "montant_total": "50.00",
            "montant_unitaire": "5.00",
            "montants_variables": False,
        })
        recap = generer_recapitulatif(_dt(jours[0]), _dt(jours[-1] + datetime.timedelta(days=1)))
        ligne = next(
            item for item in enrichir_recapitulatif_paie(recap, jours[0], jours[-1])["animateurs"]
            if item["id"] == animateur.id
        )
        self.assertEqual(ligne["montant_primes_preparees"], "50.00")
        self.assertEqual(
            [item["nombre_jours"] for item in ligne["attributions_primes"]],
            [5, 5],
        )
        premier_segment = attributions.order_by("date_debut").first()
        suppression = self.client.delete(
            reverse("api_attribution_prime_detail", args=[premier_segment.id])
            + f"?date_debut={jours[0].isoformat()}&date_fin={jours[-1].isoformat()}"
        )
        self.assertEqual(suppression.status_code, 200)
        self.assertEqual(suppression.json()["synthese"]["montant_total"], "25.00")
        self.assertEqual(
            [(item["date_debut"], item["date_fin"]) for item in suppression.json()["synthese"]["attributions"]],
            [(jours[5].isoformat(), jours[9].isoformat())],
        )

    def test_soumission_repetee_de_cinq_jours_reutilise_le_segment_identique(self):
        jours = [datetime.date(2026, 7, 6) + datetime.timedelta(days=index) for index in range(5)]
        animateur = Animateur.objects.create(prenom="Alix", nom="Idempotence prime")
        HistoriqueStatutAnimateur.objects.create(
            animateur=animateur, statut=self.statut, date_effet=jours[0]
        )
        for jour in jours:
            self.travailler(animateur, jour)
        prime = self.type_prime(variable=True)
        payload = {
            "animateur_id": animateur.id, "type_prime_id": prime.id,
            "jours": [jour.isoformat() for jour in jours], "montant": "5.00",
        }
        for _ in range(2):
            response = self.client.post(
                reverse("api_attributions_primes"), data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201)
        attribution = AttributionPrime.objects.get(animateur=animateur, type_prime=prime)
        self.assertEqual(attribution.montant_unitaire, Decimal("5.00"))
        self.assertEqual(attribution.montant_total, Decimal("25.00"))

    def test_creer_supprimer_recreer_libere_immediatement_les_cinq_jours(self):
        jours = [datetime.date(2026, 7, 6) + datetime.timedelta(days=index) for index in range(5)]
        animateur = Animateur.objects.create(prenom="Ange", nom="Réattribution immédiate")
        HistoriqueStatutAnimateur.objects.create(
            animateur=animateur, statut=self.statut, date_effet=jours[0]
        )
        for jour in jours:
            self.travailler(animateur, jour)
        prime = self.type_prime(variable=True)
        payload = {
            "animateur_id": animateur.id, "type_prime_id": prime.id,
            "jours": [jour.isoformat() for jour in jours], "montant": "5.00",
            "periode_debut": DEBUT.isoformat(), "periode_fin": FIN.isoformat(),
        }
        premiere = self.client.post(
            reverse("api_attributions_primes"), data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(premiere.status_code, 201)
        attribution_id = premiere.json()["attributions"][0]["id"]
        suppression = self.client.delete(
            reverse("api_attribution_prime_detail", args=[attribution_id])
            + f"?date_debut={DEBUT.isoformat()}&date_fin={FIN.isoformat()}",
            data=json.dumps({"jours_eligibles": [jour.isoformat() for jour in jours]}),
            content_type="application/json",
        )
        self.assertEqual(suppression.status_code, 200)
        self.assertEqual(suppression.json()["synthese"]["montant_total"], "0.00")
        self.assertEqual(
            suppression.json()["synthese"]["contexte_prime"]["jours_disponibles"],
            [jour.isoformat() for jour in jours],
        )
        self.assertFalse(AttributionPrime.objects.filter(pk=attribution_id).exists())

        seconde = self.client.post(
            reverse("api_attributions_primes"), data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(seconde.status_code, 201)
        finales = AttributionPrime.objects.filter(animateur=animateur, type_prime=prime)
        self.assertEqual(finales.count(), 1)
        self.assertEqual(finales.get().montant_total, Decimal("25.00"))

    def test_modification_raccourcie_libere_les_jours_retires(self):
        jours = [datetime.date(2026, 7, 6) + datetime.timedelta(days=index) for index in range(5)]
        animateur = Animateur.objects.create(prenom="Mila", nom="Prime raccourcie")
        HistoriqueStatutAnimateur.objects.create(
            animateur=animateur, statut=self.statut, date_effet=jours[0]
        )
        for jour in jours:
            self.travailler(animateur, jour)
        prime = self.type_prime(variable=True)
        attribution = creer_attribution_prime(
            animateur=animateur, type_prime=prime, date_debut=jours[0], date_fin=jours[-1],
            montant="5.00",
        )
        modification = self.client.patch(
            reverse("api_attribution_prime_detail", args=[attribution.id]),
            data=json.dumps({
                "jours": [jour.isoformat() for jour in jours[:3]], "montant": "5.00",
                "periode_debut": DEBUT.isoformat(), "periode_fin": FIN.isoformat(),
            }), content_type="application/json",
        )
        self.assertEqual(modification.status_code, 200)
        self.assertEqual(modification.json()["synthese"]["montant_total"], "15.00")
        recreation = self.client.post(reverse("api_attributions_primes"), data=json.dumps({
            "animateur_id": animateur.id, "type_prime_id": prime.id,
            "jours": [jour.isoformat() for jour in jours[3:]], "montant": "5.00",
            "periode_debut": DEBUT.isoformat(), "periode_fin": FIN.isoformat(),
        }), content_type="application/json")
        self.assertEqual(recreation.status_code, 201)
        self.assertEqual(recreation.json()["synthese"]["montant_total"], "25.00")

    def test_quatre_jours_non_contigus_totalisent_vingt_euros(self):
        jours = [datetime.date(2026, 7, jour) for jour in (6, 7, 9, 10)]
        animateur = Animateur.objects.create(prenom="Lina", nom="Prime discontinue")
        HistoriqueStatutAnimateur.objects.create(
            animateur=animateur, statut=self.statut, date_effet=jours[0]
        )
        for jour in jours:
            self.travailler(animateur, jour)
        prime = self.type_prime(variable=True)
        response = self.client.post(reverse("api_attributions_primes"), data=json.dumps({
            "animateur_id": animateur.id, "type_prime_id": prime.id,
            "jours": [jour.isoformat() for jour in jours], "montant": "5.00",
        }), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        attributions = AttributionPrime.objects.filter(animateur=animateur, type_prime=prime)
        self.assertEqual(attributions.count(), 2)
        self.assertEqual(sum(attributions.values_list("montant_total", flat=True)), Decimal("20.00"))

    def test_prime_hebdomadaire_trois_semaines_totalise_cent_cinq_euros(self):
        prime = self.type_prime(mode=TypePrime.MODE_SEMAINE)
        prime.montant_fixe = Decimal("35.00")
        prime.save()
        semaines = (
            (datetime.date(2026, 7, 6), datetime.date(2026, 7, 10)),
            (datetime.date(2026, 7, 13), datetime.date(2026, 7, 17)),
            (datetime.date(2026, 7, 20), datetime.date(2026, 7, 24)),
        )
        for debut, fin in semaines:
            for decalage in range(5):
                self.travailler(self.animateur, debut + datetime.timedelta(days=decalage))
            response = self.client.post(reverse("api_attributions_primes"), data=json.dumps({
                "animateur_id": self.animateur.id, "type_prime_id": prime.id,
                "date_debut": debut.isoformat(), "date_fin": fin.isoformat(),
                "jours": [
                    (debut + datetime.timedelta(days=decalage)).isoformat()
                    for decalage in range(5)
                ],
            }), content_type="application/json")
            self.assertEqual(response.status_code, 201)
        self.assertEqual(AttributionPrime.objects.filter(type_prime=prime).count(), 3)
        self.assertEqual(
            sum(AttributionPrime.objects.filter(type_prime=prime).values_list(
                "montant_total", flat=True
            ), Decimal("0.00")),
            Decimal("105.00"),
        )

    def test_prime_mensuelle_est_proposee_une_seule_fois(self):
        animateur = Animateur.objects.create(prenom="Mila", nom="Mensuelle")
        HistoriqueStatutAnimateur.objects.create(animateur=animateur, statut=self.statut, date_effet=DEBUT)
        for jour in (datetime.date(2026, 7, 6), datetime.date(2026, 7, 13), datetime.date(2026, 7, 20)):
            self.travailler(animateur, jour)
        prime = self.type_prime(mode=TypePrime.MODE_MOIS)
        ligne = next(item for item in self.eligibilites_api()["animateurs"] if item["id"] == animateur.id)
        self.assertEqual([item["id"] for item in ligne["primes_periode"]], [prime.id])
        self.assertTrue(all(prime.id not in {item["id"] for item in semaine["primes_eligibles"]} for semaine in ligne["semaines"]))
