import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from animateurs.models import Animateur, Centre, DemandeMateriel


class DemandesMaterielTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="lmartin", password="secret")
        self.animateur = Animateur.objects.create(prenom="Laure", nom="Martin", utilisateur=self.user)
        self.direction = user_model.objects.create_superuser(
            username="direction", email="direction@example.test", password="secret"
        )
        self.centre = Centre.objects.create(nom="La Pacaudière", code="PAC")

    def test_animateur_cree_une_demande_en_attente(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accueil"),
            {
                "module": "materiel",
                "action": "creer",
                "materiel": "Ballons",
                "quantite": "4",
                "date_besoin": "2026-08-10",
                "centre_id": str(self.centre.pk),
            },
        )
        self.assertEqual(response.status_code, 200)
        demande = DemandeMateriel.objects.get()
        self.assertEqual(demande.animateur, self.animateur)
        self.assertEqual(demande.statut, DemandeMateriel.STATUT_EN_ATTENTE)
        self.assertEqual(demande.quantite, 4)
        self.assertEqual(demande.date_besoin, datetime.date(2026, 8, 10))
        self.assertEqual(demande.centre, self.centre)
        self.assertIsNotNone(demande.date_creation)

    def test_direction_valide_une_demande(self):
        demande = DemandeMateriel.objects.create(
            animateur=self.animateur,
            materiel="Feutres",
            quantite=12,
            date_besoin=datetime.date(2026, 8, 12),
        )
        self.client.force_login(self.direction)
        response = self.client.post(
            reverse("demandes_materiel"),
            {"action": "valider", "demande_id": demande.pk},
        )
        self.assertEqual(response.status_code, 200)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeMateriel.STATUT_VALIDEE)
        self.assertEqual(demande.validee_par, self.direction)
        self.assertIsNotNone(demande.date_validation)

    def test_animateur_ne_peut_pas_valider(self):
        demande = DemandeMateriel.objects.create(
            animateur=self.animateur,
            materiel="Papier",
            quantite=2,
            date_besoin=datetime.date(2026, 8, 14),
        )
        self.client.force_login(self.user)
        self.client.post(
            reverse("demandes_materiel"),
            {"action": "valider", "demande_id": demande.pk},
        )
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeMateriel.STATUT_EN_ATTENTE)

    def test_animateur_supprime_sa_propre_demande(self):
        demande = DemandeMateriel.objects.create(
            animateur=self.animateur,
            materiel="Gobelets",
            quantite=20,
            date_besoin=datetime.date(2026, 8, 16),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accueil"),
            {"module": "materiel", "action": "supprimer", "demande_id": demande.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DemandeMateriel.objects.filter(pk=demande.pk).exists())

    def test_animateur_ne_supprime_pas_la_demande_d_un_autre(self):
        user_model = get_user_model()
        autre_user = user_model.objects.create_user(username="bdupont", password="secret")
        autre_animateur = Animateur.objects.create(prenom="Bruno", nom="Dupont", utilisateur=autre_user)
        demande = DemandeMateriel.objects.create(
            animateur=autre_animateur,
            materiel="Cordes",
            quantite=2,
            date_besoin=datetime.date(2026, 8, 18),
        )
        self.client.force_login(self.user)
        self.client.post(
            reverse("accueil"),
            {"module": "materiel", "action": "supprimer", "demande_id": demande.pk},
        )
        self.assertTrue(DemandeMateriel.objects.filter(pk=demande.pk).exists())

    def test_direction_supprime_n_importe_quelle_demande(self):
        demande = DemandeMateriel.objects.create(
            animateur=self.animateur,
            materiel="Peinture",
            quantite=6,
            date_besoin=datetime.date(2026, 8, 20),
        )
        self.client.force_login(self.direction)
        response = self.client.post(
            reverse("demandes_materiel"),
            {"action": "supprimer", "demande_id": demande.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DemandeMateriel.objects.filter(pk=demande.pk).exists())

