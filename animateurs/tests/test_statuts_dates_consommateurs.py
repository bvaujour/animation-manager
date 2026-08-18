import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    BesoinQualification,
    Centre,
    Contrat,
    Disponibilite,
    Evenement,
    HistoriqueStatutAnimateur,
    Qualification,
    Sortie,
    SortieParticipation,
    TypePrime,
)
from animateurs.services.dashboard import generer_tableau_de_bord
from animateurs.services.parametres import get_parametres_structure, prime_est_eligible
from animateurs.services.planning_solver import generer_planning_auto
from animateurs.services.sorties import animateurs_eligibles_responsabilites
from animateurs.services.status_colors import couleur_pour_statut
from animateurs.services.statuts import (
    ids_qualifications_pour_date,
    prefetch_historiques_statuts,
    statut_pour_date,
)
from animateurs.tests.base import ConnexionTestCase


DEBUT = datetime.date(2026, 8, 24)
DATE_EFFET = datetime.date(2026, 8, 26)
FIN = datetime.date(2026, 8, 28)


def _dt(jour):
    return timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))


class ConsommateursStatutsDatesTests(ConnexionTestCase):
    def setUp(self):
        self.stagiaire = Qualification.objects.create(nom="Stagiaire BAFA daté", est_statut=True)
        self.diplome = Qualification.objects.create(nom="Diplômé BAFA daté", est_statut=True)
        self.psc1 = Qualification.objects.create(nom="PSC1 daté")
        self.animateur = Animateur.objects.create(prenom="Bruno", nom="Statut futur")
        self.animateur.qualifications.add(self.stagiaire, self.psc1)
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur,
            statut=self.stagiaire,
            date_effet=DEBUT,
        )
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur,
            statut=self.diplome,
            date_effet=DATE_EFFET,
        )
        # Le statut matérialisé reste volontairement ancien : aucun appel à la
        # fiche ni à synchroniser_statut_actuel() ne doit être nécessaire.
        self.animateur.qualifications.remove(self.diplome)
        self.animateur.qualifications.add(self.stagiaire)

    def test_helper_fusionne_qualifications_ordinaires_et_statut_du_jour(self):
        avant = ids_qualifications_pour_date(self.animateur, DEBUT)
        apres = ids_qualifications_pour_date(self.animateur, DATE_EFFET)
        self.assertEqual(avant, {self.psc1.id, self.stagiaire.id})
        self.assertEqual(apres, {self.psc1.id, self.diplome.id})
        self.assertEqual(statut_pour_date(self.animateur, DATE_EFFET), self.diplome)
        self.assertTrue(self.animateur.qualifications.filter(pk=self.stagiaire.pk).exists())

    def test_liste_planning_expose_la_bascule_au_milieu_de_semaine(self):
        with patch("django.utils.timezone.localdate", return_value=DATE_EFFET):
            response = self.client.get(reverse("api_animateurs"), {
                "format": "planning",
                "debut": DEBUT.isoformat(),
                "fin": (FIN + datetime.timedelta(days=1)).isoformat(),
            })
        self.assertEqual(response.status_code, 200)
        donnees = response.json()[0]
        self.assertEqual(donnees["statut_principal"]["id"], self.diplome.id)
        self.assertEqual(donnees["statuts_par_date"]["2026-08-24"]["id"], self.stagiaire.id)
        self.assertEqual(donnees["statuts_par_date"]["2026-08-25"]["id"], self.stagiaire.id)
        for jour in ("2026-08-26", "2026-08-27", "2026-08-28"):
            self.assertEqual(donnees["statuts_par_date"][jour]["id"], self.diplome.id)
        self.assertIn(self.psc1.id, donnees["qualification_ids"])
        self.assertNotIn(self.stagiaire.id, donnees["statut_ids"])

    def test_liste_actuelle_ne_depend_pas_du_statut_materialise(self):
        with patch("django.utils.timezone.localdate", return_value=DATE_EFFET):
            donnees = self.client.get(reverse("api_animateurs")).json()[0]
        self.assertEqual(donnees["statut_principal"]["id"], self.diplome.id)
        self.assertIn("PSC1 daté", donnees["qualifications"])

    def test_evenement_planning_utilise_le_statut_de_la_date(self):
        centre = Centre.objects.create(nom="Centre Planning daté", code="PD")
        groupe = Evenement.objects.create(
            centre=centre, nom="Groupe Planning daté", permanent=True
        )
        Affectation.objects.create(
            animateur=self.animateur,
            centre=centre,
            evenement=groupe,
            debut=_dt(DATE_EFFET),
            fin=_dt(DATE_EFFET + datetime.timedelta(days=1)),
        )
        response = self.client.get(reverse("api_planning"), {
            "start": DATE_EFFET.isoformat(),
            "end": (DATE_EFFET + datetime.timedelta(days=1)).isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["borderColor"], couleur_pour_statut(self.diplome))
        self.assertTrue(self.animateur.qualifications.filter(pk=self.stagiaire.pk).exists())

    def test_prime_datee_utilise_l_historique(self):
        contrat = Contrat.objects.create(
            animateur=self.animateur,
            type_contrat=Contrat.TYPE_CEE,
            date_debut=DEBUT,
            date_fin=FIN,
            taux_journalier_reference=Decimal("50.00"),
        )
        prime = TypePrime.objects.create(
            structure=get_parametres_structure(),
            nom="Prime diplômé datée",
            active=True,
            mode_calcul=TypePrime.MODE_JOUR,
            type_montant=TypePrime.MONTANT_FIXE,
            montant_fixe=Decimal("5.00"),
            contrats_eligibles=[Contrat.TYPE_CEE],
            tous_statuts=False,
        )
        prime.statuts_eligibles.add(self.diplome)
        self.assertFalse(prime_est_eligible(prime, self.animateur, contrat, date=DEBUT))
        self.assertTrue(prime_est_eligible(prime, self.animateur, contrat, date=DATE_EFFET))

    def test_prefetch_evite_une_requete_par_animateur_et_par_jour(self):
        for index in range(4):
            animateur = Animateur.objects.create(prenom=f"Test{index}", nom="Préchargement")
            animateur.qualifications.add(self.psc1)
            HistoriqueStatutAnimateur.objects.create(
                animateur=animateur, statut=self.diplome, date_effet=DATE_EFFET
            )
        queryset = prefetch_historiques_statuts(
            Animateur.objects.prefetch_related("qualifications"), date_fin=FIN
        )
        with self.assertNumQueries(3):
            animateurs = list(queryset)
            for animateur in animateurs:
                for offset in range(5):
                    ids_qualifications_pour_date(
                        animateur, DEBUT + datetime.timedelta(days=offset)
                    )


class ConsommateursStatutsDatesPlanningTests(TestCase):
    def setUp(self):
        self.stagiaire = Qualification.objects.create(nom="Stagiaire solveur", est_statut=True)
        self.diplome = Qualification.objects.create(nom="Diplômé solveur", est_statut=True)
        self.psc1 = Qualification.objects.create(nom="PSC1 solveur")
        self.animateur = Animateur.objects.create(prenom="Bruno", nom="Solveur daté")
        self.animateur.qualifications.add(self.stagiaire, self.psc1)
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=self.stagiaire, date_effet=DEBUT
        )
        HistoriqueStatutAnimateur.objects.create(
            animateur=self.animateur, statut=self.diplome, date_effet=DATE_EFFET
        )
        self.animateur.qualifications.remove(self.diplome)
        self.animateur.qualifications.add(self.stagiaire)
        Disponibilite.objects.create(animateur=self.animateur, debut=DEBUT, fin=FIN)
        self.centre = Centre.objects.create(nom="Centre statut daté", code="SD")
        self.groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Groupe statut daté",
            permanent=True,
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )

    def test_solveur_applique_le_statut_jour_par_jour(self):
        BesoinQualification.objects.create(
            evenement=self.groupe, qualification=self.diplome, nombre_minimum=1
        )
        resultat, code = generer_planning_auto({"debut": DEBUT.isoformat()})
        self.assertEqual(code, 200)
        self.assertEqual(resultat["created"], 3)
        dates = {
            timezone.localtime(item.debut).date() for item in Affectation.objects.all()
        }
        self.assertEqual(dates, {DATE_EFFET, DATE_EFFET + datetime.timedelta(days=1), FIN})

    def test_solveur_conserve_une_qualification_ordinaire(self):
        BesoinQualification.objects.create(
            evenement=self.groupe, qualification=self.psc1, nombre_minimum=1
        )
        resultat, code = generer_planning_auto({"debut": DEBUT.isoformat()})
        self.assertEqual(code, 200)
        self.assertEqual(resultat["created"], 5)

    def test_dashboard_controle_le_statut_de_chaque_jour(self):
        BesoinQualification.objects.create(
            evenement=self.groupe, qualification=self.diplome, nombre_minimum=1
        )
        for offset in range(5):
            jour = DEBUT + datetime.timedelta(days=offset)
            Affectation.objects.create(
                animateur=self.animateur,
                centre=self.centre,
                evenement=self.groupe,
                debut=_dt(jour),
                fin=_dt(jour + datetime.timedelta(days=1)),
            )
        jours = generer_tableau_de_bord(DEBUT)["semaine"]
        self.assertEqual([item["qualifications_manquantes"] for item in jours], [1, 1, 0, 0, 0])

    def test_sortie_utilise_le_statut_de_sa_date(self):
        sortie = Sortie.objects.create(
            nom="Sortie statuts datés",
            date=DATE_EFFET,
            destination="Parc",
        )
        SortieParticipation.objects.create(sortie=sortie, evenement=self.groupe)
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=_dt(DATE_EFFET),
            fin=_dt(DATE_EFFET + datetime.timedelta(days=1)),
        )
        donnees = animateurs_eligibles_responsabilites(sortie)
        self.assertEqual(donnees[0]["statut_principal"]["id"], self.diplome.id)
        self.assertTrue(self.animateur.qualifications.filter(pk=self.stagiaire.pk).exists())
