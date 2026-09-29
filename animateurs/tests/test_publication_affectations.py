import datetime
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from urllib.parse import urlencode, urlsplit

from animateurs.models import (
    Affectation, Animateur, Centre, DestinatairePublicationAffectation,
    Evenement, Groupe, HoraireAffectationJour, PeriodeCalendrier, PublicationAffectationsPeriode,
    PublicationPlanning, SignalementAffectationPublication,
)
from animateurs.services.comptes import creer_compte_animateur
from animateurs.services.actions_equipe import actions_actives_animateur, instantane_affectations


class PublicationAffectationsPeriodeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.direction = User.objects.create_superuser("direction", "dir@example.com", "secret")
        self.user = User.objects.create_user("alice", password="secret")
        self.alice = Animateur.objects.create(prenom="Alice", nom="Martin", utilisateur=self.user)
        self.bob = Animateur.objects.create(prenom="Bob", nom="Durand")
        self.periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.VACANCES, nom="Toussaint 2026", annee_scolaire="2026-2027",
            zone="A", debut=datetime.date(2026, 10, 19), fin=datetime.date(2026, 10, 30),
        )
        centre = Centre.objects.create(nom="Centre test", code="TEST")
        groupe = Groupe.objects.create(nom="6 ans et plus")
        evenement = Evenement.objects.create(centre=centre, groupe=groupe, nom="6 ans et plus", jours_ouverts=[0, 1, 2, 3, 4])
        for animateur in (self.alice, self.bob):
            Affectation.objects.create(
                animateur=animateur, centre=centre, evenement=evenement,
                debut=datetime.datetime(2026, 10, 19, tzinfo=datetime.timezone.utc),
                fin=datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc),
            )

    def test_publier_snapshot_sans_publier_le_planning(self):
        self.client.force_login(self.direction)
        response = self.client.post(reverse("publications_affectations"), {
            "periode_id": self.periode.pk, "message": "Bienvenue à Toussaint.",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        publication = PublicationAffectationsPeriode.objects.get(periode_calendrier=self.periode)
        self.assertTrue(publication.publie)
        self.assertEqual(publication.destinataires.count(), 2)
        self.assertFalse(PublicationPlanning.objects.exists())
        self.assertContains(response, "Sans compte portail")

    def test_confirmation_est_personnelle_et_idempotente(self):
        publication = PublicationAffectationsPeriode.objects.create(
            periode_calendrier=self.periode, message="Message", publie=True, publie_par=self.direction
        )
        alice = DestinatairePublicationAffectation.objects.create(publication=publication, animateur=self.alice)
        bob = DestinatairePublicationAffectation.objects.create(publication=publication, animateur=self.bob)
        self.client.force_login(self.user)
        url = reverse("affectation_a_confirmer", args=[alice.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        alice.refresh_from_db()
        self.assertIsNotNone(alice.confirme_le)
        confirme_le = alice.confirme_le
        self.client.post(url)
        alice.refresh_from_db()
        bob.refresh_from_db()
        self.assertEqual(alice.confirme_le, confirme_le)
        self.assertIsNone(bob.confirme_le)
        self.assertEqual(self.client.get(reverse("affectation_a_confirmer", args=[bob.pk])).status_code, 403)

    def _publier(self, periode=None, message="Message publié"):
        self.client.force_login(self.direction)
        response = self.client.post(reverse("publications_affectations"), {
            "periode_id": (periode or self.periode).pk, "message": message,
        })
        self.assertEqual(response.status_code, 302)
        return PublicationAffectationsPeriode.objects.get(periode_calendrier=periode or self.periode)

    def _annuler_affectation(self, animateur):
        Affectation.objects.filter(animateur=animateur).delete()
        return self._publier(message="Affectation annulée")

    def test_actions_a_faire_liste_toutes_les_affectations_et_le_compteur(self):
        seconde_periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.VACANCES, nom="Noël 2026", annee_scolaire="2026-2027",
            zone="A", debut=datetime.date(2026, 12, 21), fin=datetime.date(2026, 12, 25),
        )
        centre = Centre.objects.get(code="TEST")
        evenement = Evenement.objects.get(centre=centre)
        Affectation.objects.create(
            animateur=self.alice, centre=centre, evenement=evenement,
            debut=datetime.datetime(2026, 12, 21, tzinfo=datetime.timezone.utc),
            fin=datetime.datetime(2026, 12, 26, tzinfo=datetime.timezone.utc),
        )
        self._publier()
        self._publier(seconde_periode)

        self.client.force_login(self.user)
        response = self.client.get(reverse("actions_a_faire"))
        self.assertContains(response, "Nouvelle affectation à confirmer")
        self.assertEqual(response.context["actions_a_faire_count"], 2)
        self.assertContains(response, 'class="animator-actions-count"', html=False)
        self.assertContains(response, ">2</span>", html=False)

    def test_bandeau_partage_est_visible_sur_accueil_planning_et_documents(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)

        for vue in ("accueil", "plannings_animateur", "documents_animateur"):
            response = self.client.get(reverse(vue), {"semaine": "2026-10-19"})
            self.assertContains(response, 'aria-label="Action prioritaire"')
            self.assertContains(response, "Nouvelle affectation à confirmer")
            self.assertContains(response, reverse("affectation_a_confirmer", args=[destinataire.pk]))

    def test_absence_action_ne_rend_pas_le_bandeau_partage(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accueil"), {"semaine": "2026-10-19"})
        self.assertNotContains(response, 'aria-label="Action prioritaire"')

    def test_priorite_bandeau_annulation_puis_modification_puis_nouvelle_affectation(self):
        publication = self._publier()
        modifiee = publication.destinataires.get(animateur=self.alice)
        modifiee.instantane_modifie_le = datetime.datetime(2026, 9, 29, 21, 15, tzinfo=datetime.timezone.utc)
        modifiee.save(update_fields=["instantane_modifie_le"])

        periode_nouvelle = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.VACANCES, nom="Noël 2026", annee_scolaire="2026-2027",
            zone="A", debut=datetime.date(2026, 12, 21), fin=datetime.date(2026, 12, 25),
        )
        nouvelle_publication = PublicationAffectationsPeriode.objects.create(
            periode_calendrier=periode_nouvelle, publie=True, publie_par=self.direction
        )
        DestinatairePublicationAffectation.objects.create(
            publication=nouvelle_publication, animateur=self.alice,
            instantane_affectations=[{"centre": "Centre test"}], instantane_affectations_est_fige=True,
        )

        periode_annulee = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.VACANCES, nom="Hiver 2027", annee_scolaire="2026-2027",
            zone="A", debut=datetime.date(2027, 2, 8), fin=datetime.date(2027, 2, 12),
        )
        publication_annulee = PublicationAffectationsPeriode.objects.create(
            periode_calendrier=periode_annulee, publie=True, publie_par=self.direction
        )
        date_annulation = datetime.datetime(2026, 9, 29, 21, 15, tzinfo=datetime.timezone.utc)
        DestinatairePublicationAffectation.objects.create(
            publication=publication_annulee, animateur=self.alice, retire_le=date_annulation,
            annulation_notifiee_le=date_annulation,
        )

        actions = actions_actives_animateur(self.alice)
        self.assertEqual(
            [action["type"] for action in actions],
            [
                "annulation_affectation_a_prendre_en_compte",
                "affectation_modifiee_a_reconfirmer",
                "nouvelle_affectation_a_confirmer",
            ],
        )
        self.client.force_login(self.user)
        accueil = self.client.get(reverse("accueil"), {"semaine": "2026-10-19"})
        self.assertContains(accueil, "Votre affectation pour Hiver 2027 a été annulée")

    def test_confirmation_fait_disparaitre_l_action_sans_effacer_le_suivi(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)
        self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]))
        self.assertNotContains(self.client.get(reverse("actions_a_faire")), "Toussaint 2026")
        destinataire.refresh_from_db()
        self.assertIsNotNone(destinataire.confirme_le)
        self.client.force_login(self.direction)
        suivi = self.client.get(reverse("actions_equipe"), {"periode_id": self.periode.pk})
        self.assertContains(suivi, "1 confirmés")

    def test_connexion_oriente_vers_a_faire_lorsqu_une_action_est_en_attente(self):
        self._publier()
        self.client.logout()

        response = self.client.post(reverse("login"), {"username": "alice", "password": "secret"})

        self.assertRedirects(response, reverse("actions_a_faire"), fetch_redirect_response=False)

    def test_connexion_sans_action_conserve_l_accueil(self):
        response = self.client.post(reverse("login"), {"username": "alice", "password": "secret"})

        self.assertRedirects(response, reverse("accueil"), fetch_redirect_response=False)

    def test_connexion_respecte_next_valide_meme_si_une_action_est_en_attente(self):
        self._publier()
        url = reverse("login") + "?next=" + reverse("mon_profil")

        response = self.client.post(url, {"username": "alice", "password": "secret"})

        self.assertRedirects(response, reverse("mon_profil"), fetch_redirect_response=False)

    def test_badge_a_faire_affiche_le_compteur_et_disparait_a_zero(self):
        self._publier()
        self.client.force_login(self.user)
        response = self.client.get(reverse("actions_a_faire"))
        self.assertContains(response, 'class="animator-actions-count"', html=False)
        self.assertContains(response, ">1</span>", html=False)

        destinataire = PublicationAffectationsPeriode.objects.get().destinataires.get(animateur=self.alice)
        self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]))
        response = self.client.get(reverse("actions_a_faire"))
        self.assertNotContains(response, "animator-actions-count")

    def test_signalement_est_historise_sur_le_destinataire_sans_confirmer(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("affectation_a_confirmer", args=[destinataire.pk]),
            {"action": "signaler", "contenu": "Le transport du matin est impossible."},
        )

        self.assertEqual(response.status_code, 302)
        signalement = SignalementAffectationPublication.objects.get()
        self.assertEqual(signalement.destinataire_id, destinataire.pk)
        self.assertEqual(signalement.destinataire.animateur_id, self.alice.pk)
        self.assertEqual(signalement.destinataire.publication_id, publication.pk)
        self.assertEqual(signalement.contenu, "Le transport du matin est impossible.")
        self.assertEqual(signalement.instantane_affectations, destinataire.instantane_affectations)
        destinataire.refresh_from_db()
        self.assertIsNone(destinataire.confirme_le)
        self.assertContains(self.client.get(reverse("actions_a_faire")), "Toussaint 2026")

    def test_signalement_est_visible_pour_la_direction_et_confirmation_reste_possible(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)
        self.client.post(
            reverse("affectation_a_confirmer", args=[destinataire.pk]),
            {"action": "signaler", "contenu": "Question sur mon groupe."},
        )

        self.client.force_login(self.direction)
        suivi = self.client.get(reverse("actions_equipe"), {"periode_id": self.periode.pk})
        self.assertContains(suivi, "Question ou problème signalé")
        self.assertContains(suivi, "Question sur mon groupe.")
        self.assertContains(suivi, "À confirmer")

        self.client.force_login(self.user)
        self.assertEqual(
            self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]), {"action": "confirmer"}).status_code,
            302,
        )
        destinataire.refresh_from_db()
        self.assertIsNotNone(destinataire.confirme_le)

    def test_animateur_ne_peut_pas_signaler_sur_le_destinataire_d_un_autre(self):
        publication = self._publier()
        bob = publication.destinataires.get(animateur=self.bob)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("affectation_a_confirmer", args=[bob.pk]),
            {"action": "signaler", "contenu": "Tentative interdite."},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SignalementAffectationPublication.objects.exists())

    def test_signalement_conserve_son_instantane_si_le_destinataire_est_republie(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        instantane = list(destinataire.instantane_affectations)
        self.client.force_login(self.user)

        self.client.post(
            reverse("affectation_a_confirmer", args=[destinataire.pk]),
            {"action": "signaler", "contenu": "Besoin d'une précision."},
        )
        # Une republication modifiée remplace l'instantané du destinataire.
        # Le message doit néanmoins garder celui visible au moment de l'envoi.
        destinataire.instantane_affectations = [{"centre": "Centre republié"}]
        destinataire.save(update_fields=["instantane_affectations"])

        destinataire.refresh_from_db()
        signalement = destinataire.signalements.get()
        self.assertNotEqual(destinataire.instantane_affectations, instantane)
        self.assertEqual(signalement.instantane_affectations, instantane)

    def test_instantane_reste_identique_apres_modification_du_planning(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        instantane = destinataire.instantane_affectations
        self.assertEqual(instantane[0]["centre"], "Centre test")
        autre_centre = Centre.objects.create(nom="Centre modifié", code="MOD")
        groupe = Groupe.objects.create(nom="Autre groupe")
        evenement = Evenement.objects.create(centre=autre_centre, groupe=groupe, nom="Autre groupe", jours_ouverts=[0])
        affectation = Affectation.objects.filter(animateur=self.alice).first()
        affectation.centre = autre_centre
        affectation.evenement = evenement
        affectation.save(update_fields=["centre", "evenement"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("affectation_a_confirmer", args=[destinataire.pk]))
        self.assertContains(response, "Centre test")
        self.assertNotContains(response, "Centre modifié")

    def test_republication_inchangee_conserve_confirmation_et_modification_ciblee_la_reinitialise(self):
        publication = self._publier()
        alice = publication.destinataires.get(animateur=self.alice)
        bob = publication.destinataires.get(animateur=self.bob)
        self.client.force_login(self.user)
        self.client.post(reverse("affectation_a_confirmer", args=[alice.pk]))
        alice.refresh_from_db()
        confirme_le = alice.confirme_le

        self._publier(message="Message republication")
        alice.refresh_from_db()
        self.assertEqual(alice.confirme_le, confirme_le)

        autre_centre = Centre.objects.create(nom="Centre Alice", code="ALICE")
        groupe = Groupe.objects.create(nom="Groupe Alice")
        evenement = Evenement.objects.create(centre=autre_centre, groupe=groupe, nom="Groupe Alice", jours_ouverts=[0])
        affectation = Affectation.objects.filter(animateur=self.alice).first()
        affectation.centre = autre_centre
        affectation.evenement = evenement
        affectation.save(update_fields=["centre", "evenement"])
        self._publier(message="Message republication 2")
        alice.refresh_from_db()
        bob.refresh_from_db()
        self.assertIsNone(alice.confirme_le)
        self.assertIsNone(bob.confirme_le)

    def test_republication_conserve_deux_lignes_confirmees_et_signale_une_nouvelle(self):
        centre = Centre.objects.get(code="TEST")
        evenement = Evenement.objects.get(centre=centre)
        Affectation.objects.create(
            animateur=self.alice, centre=centre, evenement=evenement,
            debut=datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc),
            fin=datetime.datetime(2026, 10, 27, tzinfo=datetime.timezone.utc),
        )
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)
        self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]), {"action": "confirmer"})
        destinataire.refresh_from_db()
        confirmation_initiale = list(destinataire.instantane_affectations_confirmees)
        self.assertEqual(len(confirmation_initiale), 2)

        Affectation.objects.create(
            animateur=self.alice, centre=centre, evenement=evenement,
            debut=datetime.datetime(2026, 10, 27, tzinfo=datetime.timezone.utc),
            fin=datetime.datetime(2026, 10, 31, tzinfo=datetime.timezone.utc),
        )
        self._publier(message="Une affectation a été ajoutée")
        destinataire.refresh_from_db()

        self.assertIsNone(destinataire.confirme_le)
        self.assertEqual(destinataire.instantane_affectations_confirmees, confirmation_initiale)
        self.client.force_login(self.user)
        detail = self.client.get(reverse("affectation_a_confirmer", args=[destinataire.pk]))
        self.assertContains(detail, "✓ Déjà confirmée")
        self.assertContains(detail, "À CONFIRMER")
        self.assertContains(detail, "Confirmer cette affectation")
        self.assertEqual(detail.context["nombre_a_confirmer"], 1)

        self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]), {"action": "confirmer"})
        destinataire.refresh_from_db()
        self.assertIsNotNone(destinataire.confirme_le)
        self.assertEqual(len(destinataire.instantane_affectations_confirmees), 3)

    def test_affectation_confirmee_puis_supprimee_devient_une_annulation_a_prendre_en_compte(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)
        self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]), {"action": "confirmer"})
        destinataire.refresh_from_db()
        confirmation_initiale = destinataire.confirme_le
        instantane_initial = list(destinataire.instantane_affectations)

        self._annuler_affectation(self.alice)
        destinataire.refresh_from_db()
        self.assertIsNotNone(destinataire.retire_le)
        self.assertIsNotNone(destinataire.annulation_notifiee_le)
        self.assertIsNone(destinataire.annulation_prise_en_compte_le)
        self.assertEqual(destinataire.confirme_le, confirmation_initiale)
        self.assertEqual(destinataire.instantane_affectations, instantane_initial)

        self.client.force_login(self.user)
        actions = self.client.get(reverse("actions_a_faire"))
        self.assertContains(actions, "Votre affectation pour Toussaint 2026 a été annulée")
        self.assertNotContains(actions, "Nouvelle affectation à confirmer")
        detail = self.client.get(reverse("affectation_a_confirmer", args=[destinataire.pk]))
        self.assertContains(detail, "Centre test")
        self.assertContains(detail, "J’ai pris connaissance de cette annulation")
        self.assertNotContains(detail, "Confirmer cette affectation")

    def test_prise_en_compte_annulation_fait_disparaitre_l_action(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self._annuler_affectation(self.alice)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("affectation_a_confirmer", args=[destinataire.pk]),
            {"action": "prendre_en_compte_annulation"},
        )
        self.assertEqual(response.status_code, 302)
        destinataire.refresh_from_db()
        self.assertIsNotNone(destinataire.annulation_prise_en_compte_le)
        self.assertNotContains(self.client.get(reverse("actions_a_faire")), "Votre affectation pour Toussaint 2026 a été annulée")

    def test_actions_equipe_distingue_annulation_en_attente_et_prise_en_compte(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self._annuler_affectation(self.alice)
        self.client.force_login(self.direction)
        suivi = self.client.get(reverse("actions_equipe"), {"periode_id": self.periode.pk})
        self.assertContains(suivi, "Annulation à confirmer")

        self.client.force_login(self.user)
        self.client.post(
            reverse("affectation_a_confirmer", args=[destinataire.pk]),
            {"action": "prendre_en_compte_annulation"},
        )
        self.client.force_login(self.direction)
        suivi = self.client.get(reverse("actions_equipe"), {"periode_id": self.periode.pk})
        self.assertContains(suivi, "Annulation prise en compte")

    def test_affectation_non_confirmee_supprimee_ne_garde_que_l_annulation_active(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self._annuler_affectation(self.alice)
        self.client.force_login(self.user)

        actions = self.client.get(reverse("actions_a_faire"))
        self.assertEqual(actions.context["actions_a_faire_count"], 1)
        self.assertContains(actions, "Votre affectation pour Toussaint 2026 a été annulée")
        self.assertNotContains(actions, "Nouvelle affectation à confirmer")
        self.assertIsNone(destinataire.confirme_le)

    def test_suppression_partielle_reste_une_reconfirmation_sans_annulation(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)
        self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]), {"action": "confirmer"})
        affectation = Affectation.objects.get(animateur=self.alice)
        affectation.fin = datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc)
        affectation.save(update_fields=["fin"])

        self._publier(message="Affectation réduite")
        destinataire.refresh_from_db()
        self.assertIsNone(destinataire.retire_le)
        self.assertIsNone(destinataire.annulation_notifiee_le)
        self.assertIsNone(destinataire.confirme_le)
        self.client.force_login(self.user)
        actions = self.client.get(reverse("actions_a_faire"))
        self.assertContains(actions, "Affectation modifiée à reconfirmer")
        self.assertNotContains(actions, "a été annulée")

    def test_republication_apres_changement_horaire_journalier_redemande_confirmation(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)
        self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]), {"action": "confirmer"})
        affectation = Affectation.objects.get(animateur=self.alice)
        HoraireAffectationJour.objects.create(
            affectation=affectation,
            date=datetime.date(2026, 10, 19),
            heure_arrivee=datetime.time(9, 0),
            heure_depart=datetime.time(17, 0),
        )

        self._publier(message="Horaires modifiés")
        destinataire.refresh_from_db()
        self.assertIsNone(destinataire.confirme_le)
        self.assertIsNotNone(destinataire.instantane_modifie_le)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("actions_a_faire")), "Affectation modifiée à reconfirmer")

    def test_action_deja_en_attente_devient_modifiee_sans_doubler_le_compteur(self):
        centre = Centre.objects.get(code="TEST")
        evenement = Evenement.objects.get(centre=centre)
        Affectation.objects.create(
            animateur=self.alice, centre=centre, evenement=evenement,
            debut=datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc),
            fin=datetime.datetime(2026, 10, 28, tzinfo=datetime.timezone.utc),
        )
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        Affectation.objects.filter(animateur=self.alice).order_by("id").last().delete()

        self._publier(message="Affectation modifiée")
        destinataire.refresh_from_db()
        self.assertIsNotNone(destinataire.instantane_modifie_le)
        self.client.force_login(self.user)
        actions = self.client.get(reverse("actions_a_faire"))
        self.assertEqual(actions.context["actions_a_faire_count"], 1)
        self.assertEqual(actions.context["actions"][0]["type"], "affectation_modifiee_a_reconfirmer")
        self.assertContains(actions, "Affectation modifiée à reconfirmer")

    def test_republication_identique_ne_modifie_pas_le_marqueur_individuel(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        affectation = Affectation.objects.get(animateur=self.alice)
        HoraireAffectationJour.objects.create(
            affectation=affectation, date=datetime.date(2026, 10, 19),
            heure_arrivee=datetime.time(9, 0), heure_depart=datetime.time(17, 0),
        )
        self._publier(message="Horaires modifiés")
        destinataire.refresh_from_db()
        marqueur = destinataire.instantane_modifie_le

        self._publier(message="Republication identique")
        destinataire.refresh_from_db()
        self.assertEqual(destinataire.instantane_modifie_le, marqueur)

    def test_snapshot_historique_sans_cles_ajoutees_ne_declenche_pas_de_reconfirmation(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)
        self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk]), {"action": "confirmer"})
        destinataire.refresh_from_db()
        confirmation_initiale = destinataire.confirme_le
        cles_recentes = {"type_accueil_code", "modalite_periscolaire", "modalite_periscolaire_code", "horaires"}
        destinataire.instantane_affectations = [
            {cle: valeur for cle, valeur in detail.items() if cle not in cles_recentes}
            for detail in destinataire.instantane_affectations
        ]
        destinataire.instantane_affectations_confirmees = [
            {cle: valeur for cle, valeur in detail.items() if cle not in cles_recentes}
            for detail in destinataire.instantane_affectations_confirmees
        ]
        destinataire.save(update_fields=["instantane_affectations", "instantane_affectations_confirmees"])

        self._publier(message="Republication identique")
        destinataire.refresh_from_db()
        self.assertEqual(destinataire.confirme_le, confirmation_initiale)
        self.assertIsNone(destinataire.instantane_modifie_le)

    def test_accueil_met_en_avant_l_action_modifiee_avec_sa_date(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        affectation = Affectation.objects.get(animateur=self.alice)
        affectation.fin = datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc)
        affectation.save(update_fields=["fin"])
        self._publier(message="Affectation réduite")

        self.client.force_login(self.user)
        accueil = self.client.get(reverse("accueil"), {"semaine": "2026-10-19"})
        self.assertEqual(accueil.context["actions_a_faire_count"], 1)
        self.assertContains(accueil, "Affectation modifiée à reconfirmer")
        self.assertContains(accueil, "Mise à jour le")
        self.assertContains(accueil, reverse("affectation_a_confirmer", args=[destinataire.pk]))

    def test_snapshot_canonique_ignore_l_ordre_technique_des_affectations(self):
        centre = Centre.objects.get(code="TEST")
        groupe = Groupe.objects.create(nom="Autre groupe")
        autre_centre = Centre.objects.create(nom="Autre centre", code="AUTRE")
        autre_evenement = Evenement.objects.create(
            centre=autre_centre, groupe=groupe, nom="Autre groupe", jours_ouverts=[0, 1, 2, 3, 4]
        )
        Affectation.objects.create(
            animateur=self.alice, centre=autre_centre, evenement=autre_evenement,
            debut=datetime.datetime(2026, 10, 19, tzinfo=datetime.timezone.utc),
            fin=datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc),
        )
        initial = instantane_affectations(self.periode, self.alice)
        affectations = list(Affectation.objects.filter(animateur=self.alice))
        Affectation.objects.filter(pk__in=[affectation.pk for affectation in affectations]).delete()
        for affectation in reversed(affectations):
            Affectation.objects.create(
                animateur=self.alice, centre=affectation.centre, evenement=affectation.evenement,
                debut=affectation.debut, fin=affectation.fin,
                type_accueil=affectation.type_accueil,
                modalite_periscolaire=affectation.modalite_periscolaire,
            )
        self.assertEqual(instantane_affectations(self.periode, self.alice), initial)

    def test_deconnexion_est_visible_pour_animateur_et_absente_de_l_apercu(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("accueil")), 'aria-label="Déconnexion"')
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.client.force_login(self.direction)
        apercu = self.client.get(
            reverse("apercu_portail_animateur"), {"animateur_id": self.alice.pk, "semaine": "2026-10-19"}
        )
        self.assertNotContains(apercu, 'aria-label="Déconnexion"')

    def test_annulation_reste_visible_apres_activation_d_un_compte(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.bob)
        self._annuler_affectation(self.bob)
        creer_compte_animateur(self.bob)
        self.bob.refresh_from_db()
        self.bob.utilisateur.set_password("secret-annulation")
        self.bob.utilisateur.is_active = True
        self.bob.utilisateur.save(update_fields=["password", "is_active"])
        self.bob.doit_changer_mot_de_passe = False
        self.bob.save(update_fields=["doit_changer_mot_de_passe"])

        self.client.force_login(self.bob.utilisateur)
        actions = self.client.get(reverse("actions_a_faire"))
        self.assertContains(actions, "Votre affectation pour Toussaint 2026 a été annulée")
        self.assertContains(actions, reverse("affectation_a_confirmer", args=[destinataire.pk]))

    def test_reaffectation_apres_annulation_repart_sur_une_confirmation_normale(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self._annuler_affectation(self.alice)
        self.client.force_login(self.user)
        self.client.post(
            reverse("affectation_a_confirmer", args=[destinataire.pk]),
            {"action": "prendre_en_compte_annulation"},
        )
        centre = Centre.objects.get(code="TEST")
        evenement = Evenement.objects.get(centre=centre)
        Affectation.objects.create(
            animateur=self.alice, centre=centre, evenement=evenement,
            debut=datetime.datetime(2026, 10, 19, tzinfo=datetime.timezone.utc),
            fin=datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc),
        )

        self._publier(message="Nouvelle affectation")
        destinataire.refresh_from_db()
        self.assertIsNone(destinataire.retire_le)
        self.assertIsNone(destinataire.annulation_notifiee_le)
        self.assertIsNone(destinataire.annulation_prise_en_compte_le)
        self.assertIsNone(destinataire.confirme_le)
        self.assertEqual(destinataire.instantane_affectations_confirmees, [])
        self.client.force_login(self.user)
        actions = self.client.get(reverse("actions_a_faire"))
        self.assertContains(actions, "Nouvelle affectation à confirmer")
        self.assertNotContains(actions, "a été annulée")

    def test_apercu_annulation_est_strictement_en_lecture_seule(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self._annuler_affectation(self.alice)
        self.client.force_login(self.direction)
        suffixe = f"?apercu_portail=1&animateur_id={self.alice.pk}"
        actions = self.client.get(reverse("actions_a_faire") + suffixe)
        self.assertContains(actions, "Votre affectation pour Toussaint 2026 a été annulée")
        response = self.client.post(
            reverse("affectation_a_confirmer", args=[destinataire.pk]) + suffixe,
            {"action": "prendre_en_compte_annulation"},
        )
        self.assertEqual(response.status_code, 403)
        destinataire.refresh_from_db()
        self.assertIsNone(destinataire.annulation_prise_en_compte_le)

    def test_republication_ajoute_un_nouvel_animateur_sans_effacer_les_destinataires(self):
        publication = self._publier()
        charlie = Animateur.objects.create(prenom="Charlie", nom="Nouveau")
        centre = Centre.objects.get(code="TEST")
        evenement = Evenement.objects.get(centre=centre)
        Affectation.objects.create(
            animateur=charlie, centre=centre, evenement=evenement,
            debut=datetime.datetime(2026, 10, 19, tzinfo=datetime.timezone.utc),
            fin=datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc),
        )
        self._publier(message="Message republication")
        self.assertEqual(publication.destinataires.count(), 3)
        self.assertTrue(publication.destinataires.filter(animateur=charlie, confirme_le__isnull=True).exists())

    def test_actions_equipe_distingue_confirmation_attente_et_sans_acces(self):
        publication = self._publier()
        alice = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.user)
        self.client.post(reverse("affectation_a_confirmer", args=[alice.pk]))
        self.client.force_login(self.direction)
        response = self.client.get(reverse("actions_equipe"), {"periode_id": self.periode.pk})
        self.assertContains(response, "2 concernés")
        self.assertContains(response, "1 confirmés")
        self.assertContains(response, "1 en attente")
        self.assertContains(response, "1 sans accès portail")

    def test_apercu_voit_les_actions_sans_pouvoir_confirmer(self):
        publication = self._publier()
        destinataire = publication.destinataires.get(animateur=self.alice)
        self.client.force_login(self.direction)
        url = reverse("actions_a_faire") + f"?apercu_portail=1&animateur_id={self.alice.pk}"
        response = self.client.get(url)
        self.assertContains(response, 'aria-label="Action prioritaire"')
        self.assertContains(response, "Nouvelle affectation à confirmer")
        self.assertContains(response, f"apercu_portail=1&amp;animateur_id={self.alice.pk}")
        confirmation = self.client.post(
            reverse("affectation_a_confirmer", args=[destinataire.pk])
            + f"?apercu_portail=1&animateur_id={self.alice.pk}"
        )
        self.assertEqual(confirmation.status_code, 403)

    def test_destinataire_sans_compte_peut_confirmer_apres_activation(self):
        publication = PublicationAffectationsPeriode.objects.create(
            periode_calendrier=self.periode, message="Message", publie=True, publie_par=self.direction
        )
        destinataire = DestinatairePublicationAffectation.objects.create(publication=publication, animateur=self.bob)
        creer_compte_animateur(self.bob)
        self.bob.refresh_from_db()
        self.bob.utilisateur.set_password("secret-active")
        self.bob.utilisateur.is_active = True
        self.bob.utilisateur.save(update_fields=["password", "is_active"])
        self.bob.doit_changer_mot_de_passe = False
        self.bob.save(update_fields=["doit_changer_mot_de_passe"])

        self.client.force_login(self.bob.utilisateur)
        accueil = self.client.get(reverse("accueil"), {"semaine": "2026-10-19"})
        self.assertContains(accueil, "1 action à faire")
        self.assertContains(accueil, reverse("actions_a_faire"))
        detail = self.client.get(reverse("affectation_a_confirmer", args=[destinataire.pk]))
        self.assertContains(detail, "Centre test")
        self.assertEqual(self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk])).status_code, 302)
        destinataire.refresh_from_db()
        self.assertIsNotNone(destinataire.confirme_le)

    def test_legacy_sans_detail_reconstructible_n_est_pas_actionnable(self):
        publication = PublicationAffectationsPeriode.objects.create(
            periode_calendrier=self.periode, message="Message", publie=True, publie_par=self.direction
        )
        destinataire = DestinatairePublicationAffectation.objects.create(publication=publication, animateur=self.alice)
        Affectation.objects.filter(animateur=self.alice).delete()
        self.client.force_login(self.user)

        actions = self.client.get(reverse("actions_a_faire"))
        self.assertNotContains(actions, "Nouvelle affectation à confirmer")
        detail = self.client.get(reverse("affectation_a_confirmer", args=[destinataire.pk]))
        self.assertContains(detail, "Le détail de cette ancienne publication n’est plus disponible.")
        self.assertNotContains(detail, "Confirmer cette affectation")
        self.assertEqual(self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk])).status_code, 200)
        destinataire.refresh_from_db()
        self.assertIsNone(destinataire.confirme_le)

        self.client.force_login(self.direction)
        suivi = self.client.get(reverse("actions_equipe"), {"periode_id": self.periode.pk})
        self.assertContains(suivi, "Détail indisponible")

    def test_direction_peut_previsualiser_sans_usurper_un_compte(self):
        PublicationPlanning.objects.create(semaine_debut=datetime.date(2026, 10, 19), publie=True)
        self.client.force_login(self.direction)
        response = self.client.get(reverse("apercu_portail_animateur"), {"animateur_id": self.alice.pk, "semaine": "2026-10-19"})
        self.assertContains(response, "Aperçu du portail de Alice Martin")
        self.assertEqual(response.context["jours"][0]["centre"], "Centre test")
        self.assertEqual(response.wsgi_request.user, self.direction)

    def test_animateur_ne_peut_pas_ouvrir_l_apercu(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("apercu_portail_animateur"), {"animateur_id": self.bob.pk})
        self.assertRedirects(response, reverse("accueil"))

    def test_direction_ouvre_un_lanceur_apercu_sans_animateur(self):
        self.client.force_login(self.direction)
        response = self.client.get(reverse("apercu_portail_animateur"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ouvrir son portail en aperçu")
        self.assertContains(response, "Compte portail actif")
        self.assertNotContains(response, 'id="dashboard-root"')

    def test_lanceur_apercu_ouvre_le_portail_dans_un_nouvel_onglet(self):
        self.client.force_login(self.direction)
        response = self.client.get(reverse("apercu_portail_animateur"))
        self.assertContains(response, 'target="_blank"', html=False)
        self.assertContains(response, 'rel="noopener noreferrer"', html=False)
        self.assertContains(response, 'name="apercu_portail" value="1"', html=False)

    def test_direction_peut_previsualiser_un_animateur_sans_compte(self):
        PublicationPlanning.objects.create(semaine_debut=datetime.date(2026, 10, 19), publie=True)
        self.client.force_login(self.direction)
        response = self.client.get(reverse("apercu_portail_animateur"), {"animateur_id": self.bob.pk, "semaine": "2026-10-19"})
        self.assertContains(response, "Compte portail non activé")
        self.assertContains(response, "Bob Durand")
        self.assertEqual(response.context["jours"][0]["centre"], "Centre test")
        self.assertContains(response, reverse("administration") + "?onglet=comptes-animateurs")
        self.bob.refresh_from_db()
        self.assertIsNone(self.bob.utilisateur)

    def test_apercu_navigue_entre_semaines_en_conservant_l_animateur(self):
        PublicationPlanning.objects.create(semaine_debut=datetime.date(2026, 10, 19), publie=True)
        self.client.force_login(self.direction)
        semaines = [datetime.date(2026, 10, 12), datetime.date(2026, 10, 19), datetime.date(2026, 10, 26)]
        with patch("animateurs.views_pages._semaines_vacances_ouvertes", return_value=semaines):
            response = self.client.get(
                reverse("apercu_portail_animateur"),
                {"animateur_id": self.alice.pk, "semaine": "2026-10-19"},
            )
        self.assertEqual(response.context["animateur"].pk, self.alice.pk)
        self.assertEqual(response.context["semaine"]["debut"], semaines[1])
        self.assertEqual(response.context["semaine"]["precedente"], semaines[0])
        self.assertEqual(response.context["semaine"]["suivante"], semaines[2])
        self.assertContains(response, f"animateur_id={self.alice.pk}")
        self.assertEqual(response.context["jours"][0]["centre"], "Centre test")

    def test_apercu_est_strictement_en_lecture_seule(self):
        self.client.force_login(self.user)
        portail = self.client.get(reverse("accueil"), {"semaine": "2026-10-19"})
        self.assertNotContains(portail, "Affectations visibles cette semaine")

        self.client.force_login(self.direction)
        response = self.client.get(
            reverse("apercu_portail_animateur"),
            {"animateur_id": self.alice.pk, "semaine": "2026-10-19"},
        )
        self.assertNotContains(response, "Affectations visibles cette semaine")
        self.assertNotContains(response, "J’ai pris connaissance")
        self.assertNotContains(response, "enregistrer-disponibilites")
        self.assertNotContains(response, "material-dashboard-section")

    def test_apercu_reste_accessible_si_la_migration_publication_n_est_pas_encore_appliquee(self):
        self.client.force_login(self.direction)
        with patch("animateurs.views_pages.connection.introspection.table_names", return_value=[]):
            response = self.client.get(reverse("apercu_portail_animateur"), {"animateur_id": self.alice.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aperçu du portail de Alice Martin")

    def _url_apercu(self, route, **params):
        params.update(apercu_portail="1", animateur_id=self.alice.pk, semaine="2026-10-19")
        return reverse(route) + "?" + urlencode(params)

    def test_direction_parcourt_le_portail_complet_en_apercu_sans_impersonation(self):
        self.client.force_login(self.direction)
        for route, titre in (
            ("apercu_portail_animateur", "Accueil"), ("plannings_animateur", "Plannings"),
            ("infos_animateur", "Infos"), ("sorties_animateur", "Sorties"),
            ("documents_animateur", "Documents"), ("demandes_materiel", "Matériel"),
            ("mon_profil", "Mon profil"),
        ):
            with self.subTest(route=route):
                url = self._url_apercu(route)
                if route == "apercu_portail_animateur":
                    url = reverse(route) + "?" + urlencode({"animateur_id": self.alice.pk, "semaine": "2026-10-19"})
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, titre)
                self.assertContains(response, "Mode direction · Lecture seule")
                self.assertContains(response, "apercu_portail=1")
                self.assertContains(response, f"animateur_id={self.alice.pk}")
                self.assertContains(response, 'class="app-body animator-space-body')
                self.assertEqual(response.wsgi_request.user.pk, self.direction.pk)

    def test_animateur_ne_peut_pas_previsualiser_un_autre_animateur(self):
        self.client.force_login(self.user)
        response = self.client.get(self._url_apercu("infos_animateur", animateur_id=self.bob.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["animateur"].pk, self.alice.pk)
        self.assertFalse(response.context.get("apercu_portail", False))

    def test_apercu_conserve_l_animateur_dans_navigation_semaine(self):
        self.client.force_login(self.direction)
        response = self.client.get(self._url_apercu("plannings_animateur"))
        self.assertContains(response, "semaine=2026-10-12&amp;apercu_portail=1")
        self.assertContains(response, f"animateur_id={self.alice.pk}")

    def test_ecritures_personnelles_sont_refusees_en_apercu(self):
        publication = PublicationAffectationsPeriode.objects.create(
            periode_calendrier=self.periode, message="Message", publie=True, publie_par=self.direction
        )
        destinataire = DestinatairePublicationAffectation.objects.create(publication=publication, animateur=self.alice)
        self.client.force_login(self.direction)
        ecritures = (
            ("post", self._url_apercu("mon_profil"), {"action": "coordonnees", "email": "change@example.test"}),
            ("post", self._url_apercu("demandes_materiel"), {"action": "creer", "materiel": "Ballons"}),
            ("post", reverse("affectation_a_confirmer", args=[destinataire.pk]) + "?apercu_portail=1&animateur_id=" + str(self.alice.pk), {}),
            ("put", reverse("api_disponibilites", args=[self.alice.pk]) + "?apercu_portail=1&animateur_id=" + str(self.alice.pk), {"jours_disponibles": []}),
        )
        for methode, url, data in ecritures:
            with self.subTest(url=url):
                if methode == "put":
                    response = self.client.put(url, data, content_type="application/json")
                else:
                    response = self.client.post(url, data)
                self.assertEqual(response.status_code, 403)
        self.alice.refresh_from_db()
        destinataire.refresh_from_db()
        self.assertEqual(self.alice.email, "")
        self.assertIsNone(destinataire.confirme_le)

    def test_animateur_normal_conserve_ses_ecritures_personnelles(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("mon_profil"), {"action": "coordonnees", "email": "alice@example.test"})
        self.assertEqual(response.status_code, 200)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, "alice@example.test")

    def test_navigation_communication_est_hierarchisee_sans_selecteur_global(self):
        self.client.force_login(self.direction)
        response = self.client.get(reverse("gestion"), {"onglet": "invitations-portail"})
        self.assertContains(response, "Portail animateur")
        self.assertContains(response, "Aperçu portail")
        self.assertContains(response, "E-mails")
        self.assertContains(response, reverse("apercu_portail_animateur"))
        self.assertNotContains(response, "gestion-period-nav")
        for onglet in ("informations", "documents", "invitations-portail"):
            page = self.client.get(reverse("gestion"), {"onglet": onglet})
            self.assertNotContains(page, 'id="app-type-accueil"')
            self.assertNotContains(page, 'id="app-periode-accueil"')

    def test_invitations_resolvent_la_periode_sans_contexte_global(self):
        self.client.force_login(self.direction)
        session = self.client.session
        session["periode_calendrier_contexte"] = 999999
        session["type_accueil"] = "periscolaire"
        session.save()
        response = self.client.get(reverse("api_invitations_portail"), {"periode_id": self.periode.pk})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["periode_id"], self.periode.pk)
        self.assertEqual(payload["synthese"]["affectes"], 2)
        self.assertEqual({item["id"] for item in payload["animateurs"]}, {self.alice.pk, self.bob.pk})

    @override_settings(DEBUG=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_invitation_test_envoie_identifiant_et_lien_activation_individuel(self):
        """L'envoi est vérifié en mémoire : aucun e-mail réel n'est émis."""
        self.bob.email = "portail-test@example.invalid"
        self.bob.save(update_fields=["email"])
        self.client.force_login(self.direction)

        response = self.client.post(
            reverse("api_invitations_portail"),
            data={"periode_id": self.periode.pk, "animateur_ids": [self.bob.pk]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.bob.refresh_from_db()
        message = mail.outbox[0]
        self.assertEqual(message.to, ["portail-test@example.invalid"])
        self.assertIn(self.bob.utilisateur.username, message.body)
        self.assertIn("sous 3 jours", message.body)
        activation_url = response.json()["resultats"][0]["activation_url"]
        self.assertIn(activation_url, message.body)
        activation = self.client.get(urlsplit(activation_url).path)
        self.assertEqual(activation.status_code, 200)
        self.assertContains(activation, "mot de passe")

    def test_coordonnees_invitation_utilisent_la_fiche_et_rendent_sms_disponible(self):
        self.client.force_login(self.direction)
        response = self.client.patch(
            reverse("api_animateur_detail", args=[self.bob.pk]),
            data=json.dumps({"email": "bob@example.test", "telephone": "0612345678"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "bob@example.test")
        self.bob.refresh_from_db()
        self.assertEqual(self.bob.email, "bob@example.test")
        self.assertEqual(self.bob.telephone, "0612345678")

        self.client.patch(
            reverse("api_animateur_detail", args=[self.alice.pk]),
            data=json.dumps({"email": "alice-portail@example.test"}),
            content_type="application/json",
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "alice-portail@example.test")

        creer_compte_animateur(self.bob)
        invitation = self.client.get(reverse("api_invitations_portail"), {"periode_id": self.periode.pk}).json()
        ligne = next(item for item in invitation["animateurs"] if item["id"] == self.bob.pk)
        self.assertEqual(ligne["etat"], "attente")
        self.assertEqual(ligne["email"], "bob@example.test")
        self.assertEqual(ligne["telephone"], "0612345678")
        self.assertIn(ligne["username"], ligne["sms"])
        self.assertIn(ligne["activation_url"], ligne["sms"])

    def test_un_animateur_ne_peut_pas_modifier_des_coordonnees_par_l_api_direction(self):
        self.client.force_login(self.user)
        response = self.client.patch(
            reverse("api_animateur_detail", args=[self.bob.pk]),
            data=json.dumps({"email": "intrus@example.test"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.bob.refresh_from_db()
        self.assertEqual(self.bob.email, "")
