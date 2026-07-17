import json
import tempfile

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from animateurs.models import Animateur, DestinataireEnvoiEmail, Document, EnvoiEmail


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Gestion animation <planning@example.fr>",
    EMAIL_REPLY_TO="direction@example.fr",
    DEBUG=True,
)
class EnvoiEmailApiTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        self.override_media = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)

        self.ambre = Animateur.objects.create(
            prenom="Ambre", nom="Bain", email="ambre@example.fr"
        )
        self.gael = Animateur.objects.create(
            prenom="Gaël", nom="Jarlier", email="gael@example.fr"
        )
        self.sans_email = Animateur.objects.create(prenom="Léane", nom="Test")
        self.document = Document.objects.create(
            titre="Planning juillet",
            fichier=SimpleUploadedFile(
                "planning-juillet.pdf",
                b"contenu de test",
                content_type="application/pdf",
            ),
            permanent=True,
        )

    def test_preparation_liste_les_salaries_documents_et_configuration(self):
        response = self.client.get("/api/envois-email/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["configuration"]["operationnel"])
        self.assertTrue(payload["configuration"]["mode_test"])
        self.assertEqual(
            [animateur["prenom"] for animateur in payload["animateurs"]],
            ["Ambre", "Gaël", "Léane"],
        )
        self.assertEqual(payload["documents"][0]["titre"], "Planning juillet")
        self.assertEqual(payload["historique"], [])

    def test_envoi_un_message_separe_par_salarie_avec_piece_jointe(self):
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id, self.gael.id],
                "document_ids": [self.document.id],
                "objet": "Documents été",
                "message": "Tu trouveras les documents en pièce jointe.",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["nombre_envoyes"], 2)
        self.assertEqual(payload["nombre_echecs"], 0)
        self.assertTrue(payload["mode_test"])
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["ambre@example.fr"])
        self.assertEqual(mail.outbox[1].to, ["gael@example.fr"])
        self.assertEqual(mail.outbox[0].reply_to, ["direction@example.fr"])
        self.assertEqual(mail.outbox[0].attachments[0][0], "planning-juillet.pdf")
        self.assertIn("Bonjour Ambre", mail.outbox[0].body)
        self.assertIn("Bonjour Gaël", mail.outbox[1].body)

        envoi = EnvoiEmail.objects.get()
        self.assertEqual(envoi.nombre_destinataires, 2)
        self.assertEqual(envoi.nombre_envoyes, 2)
        self.assertEqual(envoi.documents.get(), self.document)
        self.assertEqual(
            envoi.destinataires.filter(statut=DestinataireEnvoiEmail.STATUT_ENVOYE).count(),
            2,
        )

    def test_refuse_deux_fiches_avec_la_meme_adresse(self):
        doublon = Animateur.objects.create(
            prenom="Autre", nom="Ambre", email="AMBRE@example.fr"
        )
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id, doublon.id],
                "document_ids": [self.document.id],
                "objet": "Documents été",
                "message": "Message",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("même adresse", response.json()["error"])
        self.assertEqual(len(mail.outbox), 0)

    def test_historique_conserve_le_titre_si_le_document_est_supprime(self):
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "document_ids": [self.document.id],
                "objet": "Documents été",
                "message": "Message",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.document.delete()
        historique = self.client.get("/api/envois-email/").json()["historique"]
        self.assertEqual(historique[0]["documents"], ["Planning juillet"])

    def test_refuse_un_salarie_sans_email(self):
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.sans_email.id],
                "document_ids": [self.document.id],
                "objet": "Documents été",
                "message": "Message",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Léane Test", response.json()["error"])
        self.assertEqual(EnvoiEmail.objects.count(), 0)

    def test_refuse_un_envoi_sans_document(self):
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "document_ids": [],
                "objet": "Documents été",
                "message": "Message",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("document", response.json()["error"].lower())


class ConfigurationEmailProductionTests(TestCase):
    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        EMAIL_HOST="",
        DEBUG=False,
    )
    def test_backend_console_refuse_en_production(self):
        animateur = Animateur.objects.create(
            prenom="Julie", nom="Martin", email="julie@example.fr"
        )
        document = Document.objects.create(
            titre="Contrat",
            fichier=SimpleUploadedFile("contrat.pdf", b"pdf"),
        )
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [animateur.id],
                "document_ids": [document.id],
                "objet": "Contrat",
                "message": "Voici ton contrat.",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("production", response.json()["error"].lower())
