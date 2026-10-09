import datetime
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Animateur, DemandeDisponibilite, Disponibilite, PeriodeScolaire, PropositionDisponibiliteDate
from animateurs.services.actions_equipe import actions_actives_animateur
from animateurs.services.demandes_disponibilites import (
    demande_modification_autonome_active,
    obtenir_ou_creer_brouillon_modification_autonome,
)


class DemandesModificationAutonomesTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.direction = User.objects.create_superuser("direction", "direction@example.test", "secret")
        self.alice_user = User.objects.create_user("alice", password="secret")
        self.alice = Animateur.objects.create(prenom="Alice", nom="Martin", utilisateur=self.alice_user)
        lundi = timezone.localdate() + datetime.timedelta(days=(7 - timezone.localdate().weekday()) % 7)
        if lundi == timezone.localdate():
            lundi += datetime.timedelta(days=7)
        self.lundi = lundi
        self.mardi = lundi + datetime.timedelta(days=1)
        PeriodeScolaire.objects.create(
            nom="Période test", annee_scolaire="2026-2027", zone="A", debut=lundi, fin=lundi + datetime.timedelta(days=4), ordre=1,
        )
        self.disponibilite = Disponibilite.objects.create(animateur=self.alice, debut=lundi, fin=lundi)

    def _url(self):
        return reverse("demande_disponibilite_modifier")

    def _post(self, *, ajouter_mardi=False, action="brouillon", extra=None):
        data = {"action": action, f"jour_{self.lundi.isoformat()}": "journee"}
        if ajouter_mardi:
            data[f"jour_{self.mardi.isoformat()}"] = "journee"
        if extra:
            data.update(extra)
        return self.client.post(self._url(), data)

    def test_animateur_ne_peut_plus_ecrire_les_disponibilites_officielles(self):
        self.client.force_login(self.alice_user)
        url = reverse("api_disponibilites", args=[self.alice.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.put(url, json.dumps({"jours_disponibles": []}), content_type="application/json").status_code, 403)
        detail = reverse("api_disponibilite_detail", args=[self.alice.pk, self.disponibilite.pk])
        self.assertEqual(self.client.patch(detail, json.dumps({"debut": self.mardi.isoformat()}), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.delete(detail).status_code, 403)
        self.disponibilite.refresh_from_db()
        self.assertEqual((self.disponibilite.debut, self.disponibilite.fin), (self.lundi, self.lundi))

    def test_direction_conserve_le_put_legacy(self):
        self.client.force_login(self.direction)
        response = self.client.put(
            reverse("api_disponibilites", args=[self.alice.pk]),
            json.dumps({"jours_disponibles": [self.mardi.isoformat()]}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Disponibilite.objects.filter(
            animateur=self.alice, debut__lte=self.mardi, fin__gte=self.mardi
        ).exists())

    def test_lecture_seule_et_creation_brouillon_avec_differences_et_snapshots(self):
        self.client.force_login(self.alice_user)
        accueil = self.client.get(reverse("accueil"))
        self.assertContains(accueil, "Mes disponibilités officielles")
        self.assertContains(accueil, "Demander une modification")
        self.assertNotContains(accueil, "enregistrer-disponibilites")
        self.client.get(self._url())
        response = self._post(ajouter_mardi=True)
        self.assertEqual(response.status_code, 302)
        demande = demande_modification_autonome_active(self.alice)
        self.assertEqual(demande.statut, DemandeDisponibilite.BROUILLON)
        proposition = demande.propositions.get(date=self.mardi)
        self.assertEqual((proposition.creneau, proposition.etait_disponible), (PropositionDisponibiliteDate.JOURNEE, False))
        snapshot = proposition.etait_disponible
        # Une écriture officielle concurrente ne doit pas supprimer le
        # différentiel ni réécrire son instantané lors de la reprise.
        Disponibilite.objects.create(animateur=self.alice, debut=self.mardi, fin=self.mardi)
        self._post(ajouter_mardi=True)
        proposition.refresh_from_db()
        self.assertEqual(proposition.etait_disponible, snapshot)
        self._post()
        self.assertFalse(demande.propositions.exists())
        self.assertTrue(Disponibilite.objects.filter(pk=self.disponibilite.pk).exists())

    def test_date_passee_ou_hors_periode_est_refusee_et_demande_vide_non_envoyable(self):
        self.client.force_login(self.alice_user)
        self.client.get(self._url())
        passee = self.lundi - datetime.timedelta(days=7)
        response = self._post(extra={f"jour_{passee.isoformat()}": "journee"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DemandeDisponibilite.objects.get(animateur=self.alice).propositions.exists())
        response = self._post(action="envoyer")
        self.assertEqual(response.status_code, 302)
        demande = demande_modification_autonome_active(self.alice)
        self.assertEqual(demande.statut, DemandeDisponibilite.BROUILLON)
        self.assertFalse(demande.propositions.exists())

    def test_envoi_direction_traitement_et_correction_restent_hors_campagne_a_la_journee(self):
        self.client.force_login(self.alice_user)
        self.client.get(self._url())
        self._post(ajouter_mardi=True, action="envoyer")
        demande = demande_modification_autonome_active(self.alice)
        self.assertEqual(demande.statut, DemandeDisponibilite.ENVOYEE)
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice, debut=self.mardi).exists())
        self.client.force_login(self.direction)
        equipe = self.client.get(reverse("actions_equipe"))
        traiter = reverse("demande_disponibilite_traiter", args=[demande.pk])
        self.assertContains(equipe, traiter)
        self.client.post(traiter, {"action": "correction", "commentaire_direction": "Vérifie ce jour."})
        demande.refresh_from_db()
        correction = DemandeDisponibilite.objects.get(demande_precedente=demande)
        self.assertIsNone(correction.campagne_id)
        self.client.force_login(self.alice_user)
        page = self.client.get(reverse("demande_disponibilite_repondre", args=[correction.pk]))
        self.assertContains(page, "Correction demandée")
        self.assertNotContains(page, "Matin")
        self.assertNotContains(page, "Après-midi")
        proposition = correction.propositions.get(date=self.mardi)
        self.client.post(reverse("demande_disponibilite_repondre", args=[correction.pk]), {
            "action": "brouillon", f"creneau_{proposition.pk}": PropositionDisponibiliteDate.MATIN,
        })
        proposition.refresh_from_db()
        self.assertEqual(proposition.creneau, PropositionDisponibiliteDate.JOURNEE)

    def test_validation_et_refus_autonomes_reutilisent_le_moteur_direction(self):
        self.client.force_login(self.alice_user)
        self.client.get(self._url())
        self._post(ajouter_mardi=True, action="envoyer")
        demande = demande_modification_autonome_active(self.alice)
        self.client.force_login(self.direction)
        traiter = reverse("demande_disponibilite_traiter", args=[demande.pk])
        self.client.post(traiter, {"action": "valider"})
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.VALIDEE)
        self.assertTrue(Disponibilite.objects.filter(
            animateur=self.alice, debut__lte=self.mardi, fin__gte=self.mardi
        ).exists())

        mercredi = self.mardi + datetime.timedelta(days=1)
        self.client.force_login(self.alice_user)
        self.client.get(self._url())
        self.client.post(self._url(), {
            "action": "envoyer",
            f"jour_{self.lundi.isoformat()}": "journee",
            f"jour_{self.mardi.isoformat()}": "journee",
            f"jour_{mercredi.isoformat()}": "journee",
        })
        seconde = demande_modification_autonome_active(self.alice)
        self.client.force_login(self.direction)
        self.client.post(reverse("demande_disponibilite_traiter", args=[seconde.pk]), {
            "action": "refuser", "commentaire_direction": "À préciser.",
        })
        seconde.refresh_from_db()
        self.assertEqual(seconde.statut, DemandeDisponibilite.REFUSEE)
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice, debut=mercredi).exists())

    def test_creation_serveur_reprend_le_meme_brouillon(self):
        premiere, creee = obtenir_ou_creer_brouillon_modification_autonome(self.alice)
        seconde, creee_bis = obtenir_ou_creer_brouillon_modification_autonome(self.alice)
        self.assertTrue(creee)
        self.assertFalse(creee_bis)
        self.assertEqual(premiere.pk, seconde.pk)
        self.assertEqual(actions_actives_animateur(self.alice)[0]["id"], premiere.pk)
