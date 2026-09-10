from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import AnneeScolaire, PeriodeScolaire
from animateurs.services.annees_scolaires import annee_est_cloturee, changer_etat_annee


class ClotureAnneeTests(TestCase):
    def setUp(self):
        self.annee = AnneeScolaire.objects.get(libelle="2025-2026")
        self.admin = get_user_model().objects.create_superuser(username="admin-cloture", password="test")
        self.client.force_login(self.admin)

    def url(self, action):
        return reverse(f"admin:animateurs_anneescolaire_{action}", args=[self.annee.pk])

    def suivante(self, statut="PREPARATION"):
        return AnneeScolaire.objects.create(libelle="2026-2027", date_debut=date(2026, 9, 1), date_fin=date(2027, 8, 31), statut=statut)

    def test_cloture_conserve_periode_et_renseigne_date(self):
        periode = PeriodeScolaire.objects.create(nom="Toussaint", annee_scolaire="2025-2026", zone="A", debut=date(2025, 10, 20), fin=date(2025, 10, 24))
        avant = PeriodeScolaire.objects.values().get(pk=periode.pk)
        debut = timezone.now()
        annee = changer_etat_annee(self.annee.pk)
        self.assertEqual(annee.statut, "CLOTUREE")
        self.assertGreaterEqual(annee.date_cloture, debut)
        self.assertLessEqual(annee.date_cloture, timezone.now())
        self.assertFalse(AnneeScolaire.objects.filter(statut="ACTIVE").exists())
        self.assertEqual(PeriodeScolaire.objects.values().get(pk=periode.pk), avant)
        self.assertTrue(annee_est_cloturee("2025-2026"))
        self.assertFalse(annee_est_cloturee("2030-2031"))

    def test_double_cloture_et_preparation_refusees(self):
        annee = changer_etat_annee(self.annee.pk)
        with self.assertRaises(ValidationError):
            changer_etat_annee(annee.pk)
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.date_cloture, annee.date_cloture)
        with self.assertRaises(ValidationError):
            changer_etat_annee(self.suivante().pk)

    def test_reouverture_et_unicite_active(self):
        changer_etat_annee(self.annee.pk)
        annee = changer_etat_annee(self.annee.pk, reouvrir=True)
        self.assertEqual(annee.statut, "ACTIVE")
        self.assertIsNone(annee.date_cloture)
        self.assertFalse(annee_est_cloturee(annee.libelle))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.suivante("ACTIVE")
        with self.assertRaises(ValidationError):
            changer_etat_annee(annee.pk, reouvrir=True)

    def test_reouverture_bloquee_si_autre_active(self):
        fermee = changer_etat_annee(self.annee.pk)
        self.suivante("ACTIVE")
        response = self.client.post(self.url("reouvrir"), {"confirmer": "oui"}, follow=True)
        self.assertContains(response, "Une autre année scolaire est déjà active.")
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.statut, "CLOTUREE")
        self.assertEqual(self.annee.date_cloture, fermee.date_cloture)
        self.assertEqual(AnneeScolaire.objects.filter(statut="ACTIVE").count(), 1)

    def test_confirmation_et_boutons(self):
        self.assertContains(self.client.get(self.url("change")), "Clôturer l’année")
        self.assertContains(self.client.get(self.url("cloturer")), "historiques seront conservées")
        self.client.post(self.url("cloturer"), {})
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.statut, "ACTIVE")
        response = self.client.post(self.url("cloturer"), {"confirmer": "oui"}, follow=True)
        self.assertContains(response, "Réouvrir l’année")
        self.assertContains(response, "lecture seule")
        self.client.get(self.url("reouvrir"))
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.statut, "CLOTUREE")
        self.client.post(self.url("reouvrir"), {"confirmer": "oui"})
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.statut, "ACTIVE")
        self.assertIsNone(self.annee.date_cloture)

    def test_fiche_cloturee_non_modifiable_et_non_supprimable(self):
        changer_etat_annee(self.annee.pk)
        self.assertEqual(self.client.post(self.url("change"), {"libelle": "2030-2031", "statut": "ACTIVE"}).status_code, 403)
        self.assertEqual(self.client.post(self.url("delete"), {"post": "yes"}).status_code, 403)
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.libelle, "2025-2026")
        self.assertEqual(self.annee.statut, "CLOTUREE")

    def test_creation_cloturee_interdite(self):
        donnees = {"libelle": "2026-2027", "date_debut": "2026-09-01", "date_fin": "2027-08-31", "statut": "CLOTUREE"}
        self.client.post(reverse("admin:animateurs_anneescolaire_add"), donnees)
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())

    def test_permissions_lecture_et_modification(self):
        user = get_user_model().objects.create_user(username="lecteur-annees", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="view_anneescolaire"))
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url("change")).status_code, 200)
        for action in ("cloturer", "reouvrir"):
            self.assertEqual(self.client.get(self.url(action)).status_code, 403)
            self.assertEqual(self.client.post(self.url(action), {"confirmer": "oui"}).status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="change_anneescolaire"))
        self.client.post(self.url("cloturer"), {"confirmer": "oui"})
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.statut, "CLOTUREE")
        self.client.post(self.url("reouvrir"), {"confirmer": "oui"})
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.statut, "ACTIVE")

    def test_csrf_et_acces_anonyme(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url("cloturer"), {"confirmer": "oui"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.url("cloturer"), {"confirmer": "oui"}).status_code, 302)
        self.annee.refresh_from_db()
        self.assertEqual(self.annee.statut, "ACTIVE")
