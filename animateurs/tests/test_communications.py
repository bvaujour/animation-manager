import json
import tempfile

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from animateurs.models import Animateur, DestinataireEnvoiEmail, Document, EnvoiEmail
from animateurs.tests.base import ConnexionTestCase


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Gestion animation <planning@example.fr>",
    EMAIL_REPLY_TO="direction@example.fr",
    DEBUG=True,
)
class EmailDirectAnimateurTests(ConnexionTestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        self.override_media = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)

        self.animateur = Animateur.objects.create(
            prenom="Julie", nom="Martin", telephone="0612345678", email="julie@example.fr"
        )
        self.document = Document.objects.create(
            titre="Planning juillet",
            fichier=SimpleUploadedFile(
                "planning-juillet.pdf", b"contenu de test", content_type="application/pdf"
            ),
            permanent=True,
        )

    def test_prepare_la_fiche_email_et_son_historique(self):
        response = self.client.get(f"/api/animateurs/{self.animateur.id}/emails/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["configuration"]["operationnel"])
        self.assertEqual(payload["destinataire"], "julie@example.fr")
        self.assertEqual(payload["documents"][0]["titre"], "Planning juillet")
        self.assertEqual(payload["modeles"], [])
        self.assertIn("{{prenom}}", [variable["code"] for variable in payload["variables"]])
        self.assertEqual(payload["historique"], [])

    def test_envoie_directement_un_email_sans_piece_jointe(self):
        response = self.client.post(
            f"/api/animateurs/{self.animateur.id}/emails/",
            data=json.dumps({
                "objet": "Planning",
                "message": "Ton planning a été modifié.",
                "document_ids": [],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["statut"], "envoye")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["julie@example.fr"])
        self.assertEqual(mail.outbox[0].subject, "Planning")
        self.assertEqual(mail.outbox[0].attachments, [])
        self.assertEqual(mail.outbox[0].body, "Ton planning a été modifié.")
        self.assertNotIn("Gestion animation", mail.outbox[0].body)

        envoi = EnvoiEmail.objects.get()
        self.assertEqual(envoi.nombre_envoyes, 1)
        self.assertEqual(envoi.nombre_echecs, 0)
        self.assertEqual(
            DestinataireEnvoiEmail.objects.get().statut,
            DestinataireEnvoiEmail.STATUT_ENVOYE,
        )

        historique = self.client.get(
            f"/api/animateurs/{self.animateur.id}/emails/"
        ).json()["historique"]
        self.assertEqual(historique[0]["objet"], "Planning")
        self.assertEqual(historique[0]["statut"], "envoye")
        self.assertEqual(historique[0]["documents"], [])

    def test_remplace_uniquement_le_nom_et_le_prenom(self):
        response = self.client.post(
            f"/api/animateurs/{self.animateur.id}/emails/",
            data=json.dumps({
                "objet": "Information pour {{prenom}} {{nom}}",
                "message": "Salut {{prenom}},\n\nTexte libre. {{planning_semaine}}",
                "document_ids": [],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[0].subject, "Information pour Julie Martin")
        self.assertEqual(mail.outbox[0].body, "Salut Julie,\n\nTexte libre. {{planning_semaine}}")
        historique = self.client.get(
            f"/api/animateurs/{self.animateur.id}/emails/"
        ).json()["historique"]
        self.assertEqual(historique[0]["message"], "Salut Julie,\n\nTexte libre. {{planning_semaine}}")



    def test_un_identifiant_provisoire_invalide_ne_cree_pas_d_historique(self):
        utilisateur = get_user_model().objects.create_user(
            username="julie.martin",
            password="mot-de-passe-test",
        )
        self.animateur.utilisateur = utilisateur
        self.animateur.doit_changer_mot_de_passe = True
        self.animateur.save(update_fields=["utilisateur", "doit_changer_mot_de_passe"])

        response = self.client.post(
            f"/api/animateurs/{self.animateur.id}/emails/",
            data=json.dumps({
                "objet": "Identifiants",
                "message": "{{mot_de_passe_provisoire}}",
                "document_ids": [],
                "identifiants_provisoires": {
                    "username": "mauvais-identifiant",
                    "temporary_password": "temporaire",
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(EnvoiEmail.objects.count(), 0)
        self.assertEqual(DestinataireEnvoiEmail.objects.count(), 0)

    def test_peut_joindre_un_document(self):
        response = self.client.post(
            f"/api/animateurs/{self.animateur.id}/emails/",
            data=json.dumps({
                "objet": "Document",
                "message": "Voici le document.",
                "document_ids": [self.document.id],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[0].attachments[0][0], "planning-juillet.pdf")
        self.assertEqual(EnvoiEmail.objects.get().documents_titres, ["Planning juillet"])

    def test_refuse_un_salarie_sans_email(self):
        sans_email = Animateur.objects.create(prenom="Léane", nom="Test")
        response = self.client.post(
            f"/api/animateurs/{sans_email.id}/emails/",
            data=json.dumps({
                "objet": "Information",
                "message": "Message",
                "document_ids": [],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("adresse e-mail", response.json()["error"])
        self.assertEqual(len(mail.outbox), 0)
