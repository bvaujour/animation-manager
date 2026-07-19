import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from animateurs.models import JournalAudit


class JournalAuditTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="audit-admin", email="audit@example.test", password="mot-de-passe-solide"
        )
        self.client.force_login(self.user)

    def test_action_reussie_est_journalisee(self):
        response = self.client.post(
            "/api/centres/",
            data=json.dumps({"nom": "Centre audit", "code": "AUD", "couleur": "#2563EB"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        entree = JournalAudit.objects.get()
        self.assertEqual(entree.utilisateur, self.user)
        self.assertEqual(entree.methode, "POST")
        self.assertEqual(entree.chemin, "/api/centres/")
        self.assertEqual(entree.statut_http, 201)
        self.assertEqual(entree.donnees["nom"], "Centre audit")

    def test_action_refusee_n_est_pas_journalisee(self):
        response = self.client.post("/api/centres/", data="{", content_type="application/json")
        self.assertGreaterEqual(response.status_code, 400)
        self.assertFalse(JournalAudit.objects.exists())
