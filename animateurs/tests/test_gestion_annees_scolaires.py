from datetime import date

from django.urls import reverse

from animateurs.models import AnneeScolaire
from animateurs.tests.base import ConnexionTestCase


class GestionAnneesScolairesTests(ConnexionTestCase):
    def setUp(self):
        self.active = AnneeScolaire.objects.get(libelle="2025-2026")
        self.preparation = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=date(2026, 9, 1), date_fin=date(2027, 8, 31), statut="PREPARATION")
        self.cloturee = AnneeScolaire.objects.create(
            libelle="2024-2025", date_debut=date(2024, 9, 1), date_fin=date(2025, 8, 31), statut="CLOTUREE")

    def test_page_metier_liste_les_statuts_et_les_actions_existantes(self):
        self.assertContains(self.client.get(reverse("gestion")), reverse("gestion_annees_scolaires"))
        response = self.client.get(reverse("gestion_annees_scolaires"))

        self.assertContains(response, "Années scolaires")
        self.assertContains(response, "Active")
        self.assertContains(response, "En préparation")
        self.assertContains(response, "Clôturée")
        self.assertContains(response, "01/09/2026")
        self.assertContains(response, reverse("admin:animateurs_anneescolaire_nouvelle"))
        self.assertContains(response, reverse("admin:animateurs_anneescolaire_change", args=[self.active.pk]))
        self.assertContains(response, reverse("admin:animateurs_anneescolaire_cloturer", args=[self.active.pk]))
        self.assertNotContains(response, reverse("admin:animateurs_anneescolaire_reouvrir", args=[self.cloturee.pk]))
        self.assertNotContains(response, reverse("admin:animateurs_anneescolaire_cloturer", args=[self.preparation.pk]))

        self.active.statut = AnneeScolaire.Statut.CLOTUREE
        self.active.save(update_fields=["statut"])
        response = self.client.get(reverse("gestion_annees_scolaires"))
        self.assertContains(response, reverse("admin:animateurs_anneescolaire_reouvrir", args=[self.cloturee.pk]))
