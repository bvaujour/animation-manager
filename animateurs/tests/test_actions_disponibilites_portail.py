import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Animateur, CampagneDisponibilite, DemandeDisponibilite,
    DestinatairePublicationAffectation, PeriodeCalendrier,
    PublicationAffectationsPeriode,
)
from animateurs.services.actions_equipe import actions_actives_animateur


class ActionsDisponibilitesPortailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.direction = User.objects.create_superuser("direction", "direction@example.test", "secret")
        self.alice_user = User.objects.create_user("alice", password="secret")
        self.alice = Animateur.objects.create(prenom="Alice", nom="Martin", utilisateur=self.alice_user)
        self.bob = Animateur.objects.create(prenom="Bob", nom="Durand")

    def _demande(self, statut=DemandeDisponibilite.A_RENSEIGNER, *, animateur=None, cloturee=False, echeance=None):
        campagne = CampagneDisponibilite.objects.create(
            nom="Hiver / Printemps 2027",
            statut=CampagneDisponibilite.CLOTUREE if cloturee else CampagneDisponibilite.OUVERTE,
            date_limite_reponse=echeance,
            cree_par=self.direction,
            ouverte_le=timezone.now(),
        )
        return DemandeDisponibilite.objects.create(
            animateur=animateur or self.alice,
            campagne=campagne,
            nature=DemandeDisponibilite.PREMIERE_SAISIE,
            statut=statut,
        )

    def _publication_actionnable(self):
        periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.VACANCES, nom="Toussaint 2027", annee_scolaire="2027-2028",
            zone="A", debut=datetime.date(2027, 10, 18), fin=datetime.date(2027, 10, 29),
        )
        publication = PublicationAffectationsPeriode.objects.create(
            periode_calendrier=periode, publie=True, publie_le=timezone.now(), publie_par=self.direction,
        )
        return DestinatairePublicationAffectation.objects.create(
            publication=publication, animateur=self.alice,
            instantane_affectations=[{"centre": "Centre test"}],
            instantane_affectations_est_fige=True,
        )

    def test_demande_ouverte_a_renseigner_est_action_et_lien_vers_reponse(self):
        demande = self._demande()
        self.client.force_login(self.alice_user)

        response = self.client.get(reverse("actions_a_faire"))
        self.assertEqual(response.context["actions_a_faire_count"], 1)
        self.assertContains(response, "Disponibilités à renseigner")
        self.assertContains(response, "Campagne : Hiver / Printemps 2027")
        self.assertContains(response, reverse("demande_disponibilite_repondre", args=[demande.pk]))
        self.assertContains(response, "Répondre")

    def test_brouillon_est_a_terminer_et_statuts_non_actionnables_sont_absents(self):
        demande = self._demande(statut=DemandeDisponibilite.BROUILLON)
        self._demande(statut=DemandeDisponibilite.ENVOYEE, animateur=self.bob)
        self.client.force_login(self.alice_user)

        response = self.client.get(reverse("actions_a_faire"))
        self.assertEqual(response.context["actions_a_faire_count"], 1)
        self.assertContains(response, "Disponibilités à terminer")
        self.assertContains(response, "Continuer")
        self.assertContains(response, reverse("demande_disponibilite_repondre", args=[demande.pk]))

    def test_campagne_cloturee_est_absente_et_echeance_depassee_reste_actionnable(self):
        self._demande(cloturee=True)
        demande = self._demande(echeance=datetime.date(2020, 1, 1))

        actions = actions_actives_animateur(self.alice)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["id"], demande.pk)

    def test_badge_additionne_affectation_et_disponibilite_et_priorise_affectation(self):
        destinataire = self._publication_actionnable()
        demande = self._demande()
        self.client.force_login(self.alice_user)

        response = self.client.get(reverse("actions_a_faire"))
        self.assertEqual(response.context["actions_a_faire_count"], 2)
        self.assertEqual(response.context["action_a_faire_prioritaire"]["id"], destinataire.pk)
        self.assertContains(response, reverse("demande_disponibilite_repondre", args=[demande.pk]))
        self.assertContains(response, 'class="animator-actions-count"', html=False)

    def test_bandeau_affiche_disponibilite_sans_affectation_prioritaire(self):
        demande = self._demande()
        self.client.force_login(self.alice_user)

        response = self.client.get(reverse("accueil"))
        self.assertContains(response, 'aria-label="Action prioritaire"')
        self.assertContains(response, "Disponibilités à renseigner")
        self.assertContains(response, reverse("demande_disponibilite_repondre", args=[demande.pk]))

    def test_demande_d_un_autre_animateur_est_invisible_et_inaccessible(self):
        demande = self._demande(animateur=self.bob)
        self.client.force_login(self.alice_user)

        self.assertEqual(self.client.get(reverse("actions_a_faire")).context["actions_a_faire_count"], 0)
        self.assertEqual(
            self.client.get(reverse("demande_disponibilite_repondre", args=[demande.pk])).status_code,
            404,
        )

    def test_apercu_portail_conserve_lien_et_interdit_post(self):
        demande = self._demande()
        self.client.force_login(self.direction)
        suffixe = f"?apercu_portail=1&animateur_id={self.alice.pk}"

        response = self.client.get(reverse("actions_a_faire") + suffixe)
        self.assertEqual(response.context["actions_a_faire_count"], 1)
        self.assertContains(response, "Disponibilités à renseigner")
        self.assertContains(
            response,
            reverse("demande_disponibilite_repondre", args=[demande.pk])
            + f"?apercu_portail=1&amp;animateur_id={self.alice.pk}",
        )
        self.assertEqual(
            self.client.post(
                reverse("demande_disponibilite_repondre", args=[demande.pk]) + suffixe,
                {"action": "brouillon"},
            ).status_code,
            403,
        )

    def test_correction_hors_campagne_retrouve_contexte_ou_utilise_un_fallback(self):
        originale = self._demande(statut=DemandeDisponibilite.A_CORRIGER)
        correction = DemandeDisponibilite.objects.create(
            animateur=self.alice, nature=DemandeDisponibilite.MODIFICATION,
            statut=DemandeDisponibilite.BROUILLON, demande_precedente=originale,
        )
        self.client.force_login(self.alice_user)
        actions = self.client.get(reverse("actions_a_faire"))
        self.assertEqual(actions.context["actions_a_faire_count"], 1)
        self.assertContains(actions, "Campagne : Hiver / Printemps 2027")
        self.assertContains(actions, reverse("demande_disponibilite_repondre", args=[correction.pk]))
        self.assertContains(self.client.get(reverse("accueil")), "Disponibilités à corriger")
        self.client.force_login(self.direction)
        apercu = self.client.get(
            reverse("actions_a_faire") + f"?apercu_portail=1&animateur_id={self.alice.pk}"
        )
        self.assertEqual(apercu.context["actions_a_faire_count"], 1)
        self.assertContains(apercu, reverse("demande_disponibilite_repondre", args=[correction.pk]))

        sans_contexte = DemandeDisponibilite.objects.create(
            animateur=self.bob, nature=DemandeDisponibilite.MODIFICATION,
            statut=DemandeDisponibilite.A_CORRIGER,
        )
        DemandeDisponibilite.objects.create(
            animateur=self.bob, nature=DemandeDisponibilite.MODIFICATION,
            statut=DemandeDisponibilite.BROUILLON, demande_precedente=sans_contexte,
        )
        actions = actions_actives_animateur(self.bob)
        self.assertEqual(actions[0]["sous_titre"], "Demande de correction")
