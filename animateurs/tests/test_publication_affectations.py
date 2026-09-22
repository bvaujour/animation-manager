import datetime
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from urllib.parse import urlsplit

from animateurs.models import (
    Affectation, Animateur, Centre, DestinatairePublicationAffectation,
    Evenement, Groupe, PeriodeCalendrier, PublicationAffectationsPeriode,
    PublicationPlanning,
)
from animateurs.services.comptes import creer_compte_animateur


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
        self.assertContains(accueil, "Affectation Toussaint 2026 à confirmer")
        detail = self.client.get(reverse("affectation_a_confirmer", args=[destinataire.pk]))
        self.assertContains(detail, "Centre test")
        self.assertEqual(self.client.post(reverse("affectation_a_confirmer", args=[destinataire.pk])).status_code, 302)
        destinataire.refresh_from_db()
        self.assertIsNotNone(destinataire.confirme_le)

    def test_direction_peut_previsualiser_sans_usurper_un_compte(self):
        PublicationPlanning.objects.create(semaine_debut=datetime.date(2026, 10, 19), publie=True)
        self.client.force_login(self.direction)
        response = self.client.get(reverse("apercu_portail_animateur"), {"animateur_id": self.alice.pk, "semaine": "2026-10-19"})
        self.assertContains(response, "Aperçu du portail de Alice Martin")
        self.assertContains(response, "Centre test")
        self.assertEqual(response.wsgi_request.user, self.direction)

    def test_animateur_ne_peut_pas_ouvrir_l_apercu(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("apercu_portail_animateur"), {"animateur_id": self.bob.pk})
        self.assertRedirects(response, reverse("accueil"))

    def test_direction_peut_previsualiser_un_animateur_sans_compte(self):
        PublicationPlanning.objects.create(semaine_debut=datetime.date(2026, 10, 19), publie=True)
        self.client.force_login(self.direction)
        response = self.client.get(reverse("apercu_portail_animateur"), {"animateur_id": self.bob.pk, "semaine": "2026-10-19"})
        self.assertContains(response, "Compte portail non activé")
        self.assertContains(response, "Bob Durand")
        self.assertContains(response, "Centre test")
        self.assertContains(response, reverse("administration") + "?onglet=comptes-animateurs")
        self.bob.refresh_from_db()
        self.assertIsNone(self.bob.utilisateur)

    def test_apercu_reste_accessible_si_la_migration_publication_n_est_pas_encore_appliquee(self):
        self.client.force_login(self.direction)
        with patch("animateurs.views_pages.connection.introspection.table_names", return_value=[]):
            response = self.client.get(reverse("apercu_portail_animateur"), {"animateur_id": self.alice.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aperçu du portail de Alice Martin")

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
