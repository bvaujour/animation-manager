import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Animateur, CampagneDisponibilite, CampagneDisponibiliteBloc,
    CampagneDisponibiliteDate, DemandeDisponibilite, PropositionDisponibiliteDate,
)


class ReponsesDisponibilitesDirectionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.direction = User.objects.create_superuser("direction", "direction@example.test", "secret")
        self.animateur_user = User.objects.create_user("alice", password="secret")
        self.alice = Animateur.objects.create(prenom="Alice", nom="Martin", utilisateur=self.animateur_user)
        self.bob = Animateur.objects.create(prenom="Bob", nom="Durand")
        self.charlie = Animateur.objects.create(prenom="Charlie", nom="Roux")
        self.campagne = CampagneDisponibilite.objects.create(
            nom="Hiver / Printemps 2027", statut=CampagneDisponibilite.OUVERTE,
            cree_par=self.direction, ouverte_le=timezone.now(),
        )
        journee = CampagneDisponibiliteBloc.objects.create(
            campagne=self.campagne, libelle="Hiver — semaine 1", ordre=1,
        )
        demi_journee = CampagneDisponibiliteBloc.objects.create(
            campagne=self.campagne, libelle="Mercredis", ordre=2,
            mode_saisie=CampagneDisponibiliteBloc.DEMI_JOURNEE,
        )
        self.date_journee = CampagneDisponibiliteDate.objects.create(
            campagne=self.campagne, bloc=journee, date=datetime.date(2027, 2, 15), ordre=1,
        )
        self.date_indisponible = CampagneDisponibiliteDate.objects.create(
            campagne=self.campagne, bloc=journee, date=datetime.date(2027, 2, 16), ordre=2,
        )
        self.date_matin = CampagneDisponibiliteDate.objects.create(
            campagne=self.campagne, bloc=demi_journee, date=datetime.date(2027, 1, 6), ordre=1,
        )
        self.date_apres_midi = CampagneDisponibiliteDate.objects.create(
            campagne=self.campagne, bloc=demi_journee, date=datetime.date(2027, 1, 13), ordre=2,
        )
        self.envoyee = DemandeDisponibilite.objects.create(
            animateur=self.alice, campagne=self.campagne,
            nature=DemandeDisponibilite.PREMIERE_SAISIE,
            statut=DemandeDisponibilite.ENVOYEE, envoyee_le=timezone.now(),
            commentaire_animateur="Disponible à partir de 13h30 le mercredi.",
        )
        for date_campagne, creneau in (
            (self.date_journee, PropositionDisponibiliteDate.JOURNEE),
            (self.date_indisponible, PropositionDisponibiliteDate.INDISPONIBLE),
            (self.date_matin, PropositionDisponibiliteDate.MATIN),
            (self.date_apres_midi, PropositionDisponibiliteDate.APRES_MIDI),
        ):
            PropositionDisponibiliteDate.objects.create(
                demande=self.envoyee, date_campagne=date_campagne,
                date=date_campagne.date, creneau=creneau, etait_disponible=False,
            )
        self.brouillon = DemandeDisponibilite.objects.create(
            animateur=self.bob, campagne=self.campagne, nature=DemandeDisponibilite.PREMIERE_SAISIE,
            statut=DemandeDisponibilite.BROUILLON,
        )
        self.a_renseigner = DemandeDisponibilite.objects.create(
            animateur=self.charlie, campagne=self.campagne, nature=DemandeDisponibilite.PREMIERE_SAISIE,
        )
        self.client.force_login(self.direction)

    def _campagne_url(self):
        return reverse("campagne_disponibilite_detail", args=[self.campagne.pk])

    def _reponse_url(self, demande=None, campagne=None):
        return reverse(
            "campagne_disponibilite_reponse",
            args=[(campagne or self.campagne).pk, (demande or self.envoyee).pk],
        )

    def test_liste_reponses_resume_statuts_et_lien_uniquement_pour_envoyee(self):
        response = self.client.get(self._campagne_url())

        self.assertContains(response, "1 réponse envoyée · 1 brouillon · 1 à renseigner")
        self.assertContains(response, "Alice Martin")
        self.assertContains(response, "Bob Durand")
        self.assertContains(response, "Charlie Roux")
        self.assertContains(response, "Réponse envoyée")
        self.assertContains(response, "Brouillon")
        self.assertContains(response, "À renseigner")
        self.assertContains(response, self._reponse_url())
        self.assertEqual(response.content.decode().count("Voir la réponse"), 1)

    def test_detail_reponse_affiche_creneaux_commentaire_et_resume_sans_mutation(self):
        avant = list(self.envoyee.propositions.values_list("pk", "creneau"))
        response = self.client.get(self._reponse_url())

        self.assertContains(response, "Alice Martin")
        self.assertContains(response, "Hiver — semaine 1")
        self.assertContains(response, "Journée entière")
        self.assertContains(response, "Indisponible")
        self.assertContains(response, "Matin")
        self.assertContains(response, "Après-midi")
        self.assertContains(response, "Disponible à partir de 13h30 le mercredi.")
        self.assertContains(response, "1 journée · 1 matin · 1 après-midi · 1 indisponible")
        self.assertEqual(avant, list(self.envoyee.propositions.values_list("pk", "creneau")))

    def test_demande_d_une_autre_campagne_et_brouillon_sont_inaccessibles(self):
        autre = CampagneDisponibilite.objects.create(
            nom="Autre campagne", statut=CampagneDisponibilite.OUVERTE, cree_par=self.direction,
        )
        autre_demande = DemandeDisponibilite.objects.create(
            animateur=self.alice, campagne=autre, nature=DemandeDisponibilite.PREMIERE_SAISIE,
            statut=DemandeDisponibilite.ENVOYEE,
        )

        self.assertEqual(self.client.get(self._reponse_url(autre_demande)).status_code, 404)
        self.assertEqual(self.client.get(self._reponse_url(self.brouillon)).status_code, 404)

    def test_acces_est_reserve_a_la_direction_et_post_est_refuse(self):
        self.client.force_login(self.animateur_user)
        self.assertEqual(self.client.get(self._reponse_url()).status_code, 302)

        self.client.force_login(self.direction)
        self.assertEqual(self.client.post(self._reponse_url()).status_code, 403)
        self.envoyee.refresh_from_db()
        self.assertEqual(self.envoyee.statut, DemandeDisponibilite.ENVOYEE)
