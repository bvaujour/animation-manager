import json

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from animateurs.models import Animateur, Document


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="test@example.com",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class EmailApiTests(TestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(
            prenom="Julie",
            nom="Martin",
            email="julie@example.com",
        )
        self.document = Document.objects.create(
            titre="Planning",
            fichier=SimpleUploadedFile("planning.txt", b"contenu", content_type="text/plain"),
            permanent=True,
        )

    def test_page_email_accessible(self):
        response = self.client.get(reverse("emails"))
        self.assertEqual(response.status_code, 200)

    def test_envoi_email_avec_animateur_et_document(self):
        response = self.client.post(
            reverse("api_email_send"),
            data=json.dumps({
                "animateur_ids": [self.animateur.id],
                "emails": ["direction@example.com"],
                "sujet": "Planning semaine",
                "message": "Bonjour, voici le planning.",
                "document_ids": [self.document.id],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(set(mail.outbox[0].to), {"julie@example.com", "direction@example.com"})
        self.assertEqual(len(mail.outbox[0].attachments), 1)

    def test_refuse_adresse_invalide(self):
        response = self.client.post(
            reverse("api_email_send"),
            data=json.dumps({
                "emails": ["pas-une-adresse"],
                "sujet": "Test",
                "message": "Bonjour",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
