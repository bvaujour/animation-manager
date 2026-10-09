import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from animateurs.models import (
    Animateur, CampagneDisponibilite, DemandeDisponibilite, Disponibilite,
    PeriodeScolaire, PropositionDisponibiliteDate, TypeAccueil,
)
from animateurs.services.demandes_disponibilites import appliquer_demande_validee, envoyer_demande


class CampagnesDisponibilitesDirectionTests(TestCase):
    def setUp(self):
        self.direction = get_user_model().objects.create_superuser(
            username="direction", password="secret", email="direction@example.test"
        )
        self.client.force_login(self.direction)
        self.alice = Animateur.objects.create(prenom="Alice", nom="Martin")
        self.bob = Animateur.objects.create(prenom="Bob", nom="Durand")
        accueil, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES, defaults={"nom": "Vacances", "ordre": 1}
        )
        self.hiver = PeriodeScolaire.objects.create(
            nom="Hiver — Semaine 1", annee_scolaire="2027-2028", zone="A",
            debut=datetime.date(2027, 2, 8), fin=datetime.date(2027, 2, 12), type_accueil=accueil,
        )
        self.printemps = PeriodeScolaire.objects.create(
            nom="Printemps — Semaine 1", annee_scolaire="2027-2028", zone="A",
            debut=datetime.date(2027, 4, 12), fin=datetime.date(2027, 4, 16), type_accueil=accueil,
        )

    def _creer_brouillon(self):
        response = self.client.post(reverse("campagnes_disponibilites"), {"nom": "Hiver-printemps"})
        self.assertEqual(response.status_code, 302)
        return CampagneDisponibilite.objects.get(nom="Hiver-printemps")

    def _url(self, campagne):
        return reverse("campagne_disponibilite_detail", args=[campagne.pk])

    def test_creation_brouillon_et_navigation_communication(self):
        campagne = self._creer_brouillon()
        response = self.client.get(self._url(campagne))
        self.assertContains(response, "Disponibilités")
        self.assertContains(response, "Invitations portail")
        self.assertContains(response, "Paramètres")
        self.assertContains(response, "Rechercher un animateur")
        self.assertContains(response, "Tout sélectionner")
        self.assertContains(response, "+ Période scolaire")
        self.assertContains(response, "+ Dates manuelles")
        self.assertContains(response, "Ouvrir la campagne")
        self.assertEqual(campagne.statut, CampagneDisponibilite.BROUILLON)

    def test_plusieurs_blocs_periodes_et_dates_exactes_persistes(self):
        campagne = self._creer_brouillon()
        for periode in (self.hiver, self.printemps):
            self.client.post(self._url(campagne), {"action": "ajouter_periode", "periode_id": periode.pk})
        self.client.post(self._url(campagne), {
            "action": "ajouter_dates", "libelle_bloc": "Mercredis", "dates_manuelles": "2027-01-06\n2027-01-13",
        })
        campagne.refresh_from_db()
        self.assertEqual(campagne.blocs.count(), 3)
        self.assertEqual(campagne.dates.count(), 12)
        self.assertTrue(campagne.dates.filter(date=datetime.date(2027, 1, 13)).exists())

    def test_periode_existante_copie_uniquement_les_jours_lundi_vendredi(self):
        mercredis, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.MERCREDIS, defaults={"nom": "Mercredis", "ordre": 2}
        )
        periode = PeriodeScolaire.objects.create(
            nom="Sélection semaine entière", annee_scolaire="2027-2028", zone="A",
            debut=datetime.date(2027, 5, 3), fin=datetime.date(2027, 5, 9), type_accueil=mercredis,
        )
        campagne = self._creer_brouillon()
        self.client.post(self._url(campagne), {"action": "ajouter_periode", "periode_id": periode.pk})
        dates = set(campagne.dates.values_list("date", flat=True))
        self.assertEqual(len(dates), 5)
        self.assertNotIn(datetime.date(2027, 5, 8), dates)
        self.assertNotIn(datetime.date(2027, 5, 9), dates)
        self.assertTrue(all(item.periode_scolaire_source_id == periode.pk for item in campagne.dates.all()))

    def test_date_peut_etre_retiree_avant_ouverture(self):
        campagne = self._creer_brouillon()
        self.client.post(self._url(campagne), {"action": "ajouter_periode", "periode_id": self.hiver.pk})
        date = campagne.dates.first()
        self.client.post(self._url(campagne), {"action": "retirer_date", "date_id": date.pk})
        self.assertFalse(campagne.dates.filter(pk=date.pk).exists())

    def test_destinataires_multiples_et_echeance_sont_enregistres(self):
        campagne = self._creer_brouillon()
        self.client.post(self._url(campagne), {
            "action": "enregistrer", "nom": campagne.nom, "date_limite_reponse": "2027-01-31",
            "validation_direction_requise": "on", "animateur_ids": [self.alice.pk, self.bob.pk],
        })
        campagne.refresh_from_db()
        self.assertEqual(campagne.date_limite_reponse, datetime.date(2027, 1, 31))
        self.assertEqual(set(campagne.destinataires.values_list("id", flat=True)), {self.alice.pk, self.bob.pk})

    def test_ouverture_cree_une_demande_par_destinataire_sans_modifier_l_officiel(self):
        campagne = self._creer_brouillon()
        self.client.post(self._url(campagne), {"action": "ajouter_periode", "periode_id": self.hiver.pk})
        self.client.post(self._url(campagne), {
            "action": "enregistrer", "nom": campagne.nom, "animateur_ids": [self.alice.pk, self.bob.pk],
        })
        Disponibilite.objects.create(animateur=self.alice, debut=self.hiver.debut, fin=self.hiver.fin)
        self.client.post(self._url(campagne), {"action": "ouvrir"})
        campagne.refresh_from_db()
        self.assertEqual(campagne.statut, CampagneDisponibilite.OUVERTE)
        self.assertEqual(campagne.demandes.count(), 2)
        self.assertTrue(all(d.statut == DemandeDisponibilite.A_RENSEIGNER for d in campagne.demandes.all()))
        self.assertTrue(Disponibilite.objects.filter(animateur=self.alice, debut=self.hiver.debut, fin=self.hiver.fin).exists())

    def test_ouverture_ne_peut_pas_etre_rejouee_ni_restructuree(self):
        campagne = self._creer_brouillon()
        self.client.post(self._url(campagne), {"action": "ajouter_periode", "periode_id": self.hiver.pk})
        self.client.post(self._url(campagne), {"action": "enregistrer", "nom": campagne.nom, "validation_direction_requise": "on", "animateur_ids": [self.alice.pk]})
        self.client.post(self._url(campagne), {"action": "ouvrir"})
        dates_avant = list(campagne.dates.values_list("date", flat=True))
        self.client.post(self._url(campagne), {"action": "ouvrir"})
        self.client.post(self._url(campagne), {"action": "ajouter_periode", "periode_id": self.printemps.pk})
        self.client.post(self._url(campagne), {"action": "enregistrer", "nom": "Modifiée", "animateur_ids": [self.bob.pk]})
        campagne.refresh_from_db()
        self.assertEqual(campagne.demandes.count(), 1)
        self.assertEqual(list(campagne.dates.values_list("date", flat=True)), dates_avant)
        self.assertEqual(set(campagne.destinataires.values_list("id", flat=True)), {self.alice.pk})

    def test_cloture_bloque_nouvelle_reponse_mais_conserve_et_permet_traiter_la_reponse_envoyee(self):
        campagne = self._creer_brouillon()
        self.client.post(self._url(campagne), {"action": "ajouter_periode", "periode_id": self.hiver.pk})
        self.client.post(self._url(campagne), {"action": "enregistrer", "nom": campagne.nom, "validation_direction_requise": "on", "animateur_ids": [self.alice.pk]})
        self.client.post(self._url(campagne), {"action": "ouvrir"})
        demande = campagne.demandes.get()
        demande.propositions.update(creneau=PropositionDisponibiliteDate.INDISPONIBLE)
        envoyer_demande(demande)
        self.client.post(self._url(campagne), {"action": "cloturer"})

        campagne.refresh_from_db()
        demande.refresh_from_db()
        self.assertEqual(campagne.statut, CampagneDisponibilite.CLOTUREE)
        self.assertEqual(demande.statut, DemandeDisponibilite.ENVOYEE)
        with self.assertRaises(ValidationError):
            demande.propositions.first().save()
        appliquer_demande_validee(demande, traite_par=self.direction)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.VALIDEE)

    def test_cloture_empeche_l_envoi_d_une_reponse_non_envoyee(self):
        campagne = self._creer_brouillon()
        self.client.post(self._url(campagne), {"action": "ajouter_periode", "periode_id": self.hiver.pk})
        self.client.post(self._url(campagne), {"action": "enregistrer", "nom": campagne.nom, "animateur_ids": [self.alice.pk]})
        self.client.post(self._url(campagne), {"action": "ouvrir"})
        demande = campagne.demandes.get()
        demande.propositions.update(creneau=PropositionDisponibiliteDate.INDISPONIBLE)
        self.client.post(self._url(campagne), {"action": "cloturer"})
        with self.assertRaises(ValidationError):
            envoyer_demande(demande)
