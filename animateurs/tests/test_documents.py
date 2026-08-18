import datetime
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Document
from animateurs.services.documents import normaliser_nom_document, valider_periode_document
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_groupe


class DocumentServiceTests(SimpleTestCase):
    def test_document_permanent_efface_les_dates(self):
        debut, fin, erreur = valider_periode_document(
            permanent=True,
            periode_debut=datetime.date(2026, 7, 1),
            periode_fin=datetime.date(2026, 7, 2),
        )
        self.assertIsNone(debut)
        self.assertIsNone(fin)
        self.assertIsNone(erreur)

    def test_document_temporaire_exige_une_periode_complete(self):
        _, _, erreur = valider_periode_document(permanent=False, periode_debut=None, periode_fin=None)
        self.assertIsNotNone(erreur)


class NomDocumentTests(SimpleTestCase):
    @patch("animateurs.services.documents.uuid.uuid4")
    def test_normalise_les_accents_espaces_et_caracteres_speciaux(self, uuid4_mock):
        uuid4_mock.return_value.hex = "a3f82c1d99999999"
        cas = {
            "ENF infos santé.pdf": "enf-infos-sante-a3f82c1d.pdf",
            "L'été des enfants.PDF": "l-ete-des-enfants-a3f82c1d.pdf",
            "Planning (version finale).DocX": "planning-version-finale-a3f82c1d.docx",
            "fiche @ groupe #1 !.XLSX": "fiche-groupe-1-a3f82c1d.xlsx",
        }
        for nom_original, nom_attendu in cas.items():
            with self.subTest(nom_original=nom_original):
                self.assertEqual(normaliser_nom_document(nom_original), nom_attendu)


class ApiAjoutDocumentTests(ConnexionTestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        self.override_media = override_settings(
            MEDIA_ROOT=self.media_dir.name,
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            },
        )
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)

    @patch("animateurs.services.documents.uuid.uuid4")
    def test_applique_le_nom_normalise_sans_modifier_le_titre(self, uuid4_mock):
        uuid4_mock.return_value.hex = "a3f82c1d99999999"
        response = self.client.post(
            reverse("api_documents"),
            data={
                "titre": "Informations santé des enfants",
                "permanent": "true",
                "fichier": SimpleUploadedFile(
                    "ENF infos santé (été) !.PDF",
                    b"contenu",
                    content_type="application/pdf",
                ),
            },
        )

        self.assertEqual(response.status_code, 201)
        document = Document.objects.get()
        self.assertEqual(document.titre, "Informations santé des enfants")
        self.assertEqual(document.fichier.name, "documents/enf-infos-sante-ete-a3f82c1d.pdf")

    @patch("animateurs.views_reporting.Document.objects.create", side_effect=RuntimeError("bucket indisponible"))
    @patch("animateurs.views_reporting.logger.exception")
    def test_erreur_stockage_reste_simple_et_journalise_le_contexte(self, logger_mock, _create_mock):
        response = self.client.post(
            reverse("api_documents"),
            data={
                "titre": "Document sensible",
                "permanent": "true",
                "fichier": SimpleUploadedFile(
                    "Dossier médical.pdf",
                    b"contenu confidentiel",
                    content_type="application/pdf",
                ),
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "Le fichier n'a pas pu être enregistré. Réessaie plus tard."})
        logger_mock.assert_called_once()
        message, *arguments = logger_mock.call_args.args
        journal = message % tuple(arguments)
        self.assertIn("nom_original='Dossier médical.pdf'", journal)
        self.assertRegex(journal, r"nom_normalise='dossier-medical-[0-9a-f]{8}\.pdf'")
        self.assertIn("taille=20", journal)
        self.assertIn("type_mime='application/pdf'", journal)
        self.assertIn("backend_stockage=", journal)
        self.assertIn("exception_type=RuntimeError", journal)
        self.assertIn("exception_detail='bucket indisponible'", journal)


class VisibiliteDocumentCentresTests(TestCase):
    def setUp(self):
        utilisateur = get_user_model().objects.create_user(username="anim-doc", password="secret-test")
        self.animateur = Animateur.objects.create(prenom="Ana", nom="Doc", utilisateur=utilisateur)
        self.client.force_login(utilisateur)
        self.centre = Centre.objects.create(nom="Centre concerné", code="CC")
        self.autre_centre = Centre.objects.create(nom="Autre centre", code="AC")
        groupe, _ = creer_groupe(self.centre, nom="Groupe documents")
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=groupe,
            debut=debut,
            fin=debut + datetime.timedelta(days=5),
        )

    def creer_document(self, titre, *, publie=True, tous_centres=True, debut=None, fin=None, centres=()):
        document = Document.objects.create(
            titre=titre,
            fichier=f"documents/{titre}.pdf",
            publie=publie,
            permanent=debut is None,
            periode_debut=debut,
            periode_fin=fin,
            tous_centres=tous_centres,
        )
        document.centres.set(centres)
        return document

    def test_combine_publication_periode_et_centres_affectes(self):
        semaine = (datetime.date(2026, 7, 6), datetime.date(2026, 7, 10))
        self.creer_document("visible-tous", debut=semaine[0], fin=semaine[1])
        self.creer_document(
            "visible-centre", tous_centres=False, debut=semaine[0], fin=semaine[1], centres=[self.centre]
        )
        self.creer_document(
            "masque-autre-centre", tous_centres=False, debut=semaine[0], fin=semaine[1], centres=[self.autre_centre]
        )
        self.creer_document(
            "masque-autre-semaine",
            debut=datetime.date(2026, 7, 20),
            fin=datetime.date(2026, 7, 24),
        )
        self.creer_document("masque-non-publie", publie=False)
        self.creer_document("permanent-tous")

        response = self.client.get(reverse("api_documents"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["titre"] for item in response.json()},
            {"visible-tous", "visible-centre", "permanent-tous"},
        )
