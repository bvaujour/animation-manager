import datetime

from django.test import SimpleTestCase

from animateurs.services.documents import valider_periode_document


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
