import datetime
import tempfile
from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    CategorieDocument,
    Centre,
    Document,
    Formation,
    ModalitePeriscolaire,
    PeriodeScolaire,
    Sejour,
    Sortie,
    TypeAccueil,
)
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


class DocumentV2ModelTests(TestCase):
    def creer_document(self, titre, **kwargs):
        return Document.objects.create(titre=titre, fichier=f"documents/{titre}.pdf", **kwargs)

    def test_valeurs_par_defaut_et_categories_disponibles(self):
        document = self.creer_document("Par défaut")

        self.assertEqual(document.categorie, Document.CATEGORIE_AUTRE)
        self.assertFalse(document.important)
        self.assertIsNone(document.archive_le)
        self.assertEqual(
            Document.CATEGORIE_CHOICES,
            (
                ("pedagogie_activites", "Pédagogie & activités"),
                ("organisation_planning", "Organisation & planning"),
                ("protocoles_securite", "Protocoles & sécurité"),
                ("administratif", "Administratif"),
                ("autre", "Autre"),
            ),
        )

    def test_les_cinq_categories_sont_enregistrables(self):
        categories = [choix for choix, _ in Document.CATEGORIE_CHOICES]
        documents = [
            self.creer_document(f"Catégorie {categorie}", categorie=categorie)
            for categorie in categories
        ]

        self.assertEqual(
            set(
                Document.objects.filter(pk__in=[document.pk for document in documents]).values_list(
                    "categorie", flat=True
                )
            ),
            set(categories),
        )

    def test_categorie_reste_independante_de_la_portee_et_de_la_publication(self):
        permanent = self.creer_document(
            "Permanent organisation",
            categorie=Document.CATEGORIE_ORGANISATION_PLANNING,
            permanent=True,
            publie=False,
        )
        lie_periode = self.creer_document(
            "Période organisation",
            categorie=Document.CATEGORIE_ORGANISATION_PLANNING,
            permanent=False,
            periode_debut=datetime.date(2030, 7, 1),
            periode_fin=datetime.date(2030, 7, 5),
            publie=True,
        )

        self.assertEqual(permanent.categorie, lie_periode.categorie)
        self.assertTrue(permanent.permanent)
        self.assertFalse(lie_periode.permanent)
        self.assertFalse(permanent.publie)
        self.assertTrue(lie_periode.publie)

    def test_important_et_archive_le_sont_independants(self):
        archive_le = timezone.now()
        document = self.creer_document(
            "Document important archivé",
            important=True,
            archive_le=archive_le,
        )

        self.assertTrue(document.important)
        self.assertEqual(document.archive_le, archive_le)

    def test_migration_classe_sans_perdre_les_relations_existantes(self):
        type_accueil = TypeAccueil.objects.get(code="vacances")
        centre = Centre.objects.create(nom="Centre migration", code="CM")
        periode = PeriodeScolaire.objects.create(
            nom="Été migration",
            annee_scolaire="2030-2031",
            zone="A",
            debut=datetime.date(2030, 7, 1),
            fin=datetime.date(2030, 7, 5),
            type_accueil=type_accueil,
        )
        modalite = ModalitePeriscolaire.objects.create(code="migration", nom="Migration")
        programme = self.creer_document(
            "Programme historique",
            type_document=Document.TYPE_PROGRAMME_ACTIVITES,
            categorie=Document.CATEGORIE_AUTRE,
            important=True,
            archive_le=timezone.now(),
        )
        classique = self.creer_document(
            "Document classique historique",
            categorie=Document.CATEGORIE_PEDAGOGIE_ACTIVITES,
            important=True,
            archive_le=timezone.now(),
        )
        programme.periodes.add(periode)
        programme.centres.add(centre)
        programme.types_accueil.add(type_accueil)
        programme.modalites_periscolaires.add(modalite)
        sejour = Sejour.objects.create(nom="Séjour migration")
        sortie = Sortie.objects.create(
            nom="Sortie migration",
            date=datetime.date(2030, 7, 2),
            destination="Musée",
        )
        formation = Formation.objects.create(
            intitule="Formation migration",
            date_debut=datetime.date(2030, 7, 2),
            date_fin=datetime.date(2030, 7, 3),
        )
        sejour.documents.add(programme)
        sortie.documents.add(programme)
        formation.documents.add(programme)

        import_module("animateurs.migrations.0117_document_categories").classer_documents_existants(apps, None)

        programme.refresh_from_db()
        classique.refresh_from_db()
        self.assertEqual(programme.categorie, Document.CATEGORIE_PEDAGOGIE_ACTIVITES)
        self.assertEqual(classique.categorie, Document.CATEGORIE_AUTRE)
        self.assertFalse(programme.important)
        self.assertFalse(classique.important)
        self.assertIsNone(programme.archive_le)
        self.assertIsNone(classique.archive_le)
        self.assertEqual(programme.type_document, Document.TYPE_PROGRAMME_ACTIVITES)
        self.assertEqual(list(programme.periodes.values_list("pk", flat=True)), [periode.pk])
        self.assertEqual(list(programme.centres.values_list("pk", flat=True)), [centre.pk])
        self.assertEqual(list(programme.types_accueil.values_list("pk", flat=True)), [type_accueil.pk])
        self.assertEqual(list(programme.modalites_periscolaires.values_list("pk", flat=True)), [modalite.pk])
        self.assertEqual(list(programme.sejours.values_list("pk", flat=True)), [sejour.pk])
        self.assertEqual(list(programme.sorties.values_list("pk", flat=True)), [sortie.pk])
        self.assertEqual(list(programme.formations.values_list("pk", flat=True)), [formation.pk])


class CategorieDocumentLotATests(TestCase):
    CATEGORIES_ATTENDUES = (
        ("pedagogie_activites", "Pédagogie & activités", 1),
        ("organisation_planning", "Organisation & planning", 2),
        ("protocoles_securite", "Protocoles & sécurité", 3),
        ("administratif", "Administratif", 4),
        ("autre", "Autre", 5),
    )

    def test_categories_initiales_sont_creees_actives_et_ordonnees(self):
        self.assertEqual(
            list(CategorieDocument.objects.values_list("code", "nom", "ordre")),
            list(self.CATEGORIES_ATTENDUES),
        )
        self.assertFalse(CategorieDocument.objects.filter(active=False).exists())

    def test_migration_rattache_chaque_valeur_historique_sans_modifier_le_document(self):
        type_accueil = TypeAccueil.objects.get(code="vacances")
        centre = Centre.objects.create(nom="Centre catégories", code="CC")
        periode = PeriodeScolaire.objects.create(
            nom="Été catégories",
            annee_scolaire="2030-2031",
            zone="A",
            debut=datetime.date(2030, 7, 1),
            fin=datetime.date(2030, 7, 5),
            type_accueil=type_accueil,
        )
        modalite = ModalitePeriscolaire.objects.create(code="categories", nom="Catégories")
        documents = {}
        for code, _, _ in self.CATEGORIES_ATTENDUES:
            document = Document.objects.create(
                titre=f"Document {code}",
                fichier=f"documents/{code}.pdf",
                categorie=code,
            )
            documents[code] = document

        document_reference = documents["pedagogie_activites"]
        document_reference.periodes.add(periode)
        document_reference.centres.add(centre)
        document_reference.types_accueil.add(type_accueil)
        document_reference.modalites_periscolaires.add(modalite)
        sejour = Sejour.objects.create(nom="Séjour catégories")
        sortie = Sortie.objects.create(nom="Sortie catégories", date=datetime.date(2030, 7, 2), destination="Musée")
        formation = Formation.objects.create(
            intitule="Formation catégories",
            date_debut=datetime.date(2030, 7, 2),
            date_fin=datetime.date(2030, 7, 3),
        )
        sejour.documents.add(document_reference)
        sortie.documents.add(document_reference)
        formation.documents.add(document_reference)
        Document.objects.filter(pk__in=[document.pk for document in documents.values()]).update(categorie_ref=None)

        import_module(
            "animateurs.migrations.0118_categoriedocument_et_reference_temporaire"
        ).creer_categories_et_rattacher_documents(apps, None)

        for code, document in documents.items():
            document.refresh_from_db()
            self.assertEqual(document.categorie, code)
            self.assertEqual(document.categorie_ref.code, code)
            self.assertEqual(document.fichier.name, f"documents/{code}.pdf")

        document_reference.refresh_from_db()
        self.assertEqual(list(document_reference.periodes.values_list("pk", flat=True)), [periode.pk])
        self.assertEqual(list(document_reference.centres.values_list("pk", flat=True)), [centre.pk])
        self.assertEqual(list(document_reference.types_accueil.values_list("pk", flat=True)), [type_accueil.pk])
        self.assertEqual(list(document_reference.modalites_periscolaires.values_list("pk", flat=True)), [modalite.pk])
        self.assertEqual(list(document_reference.sejours.values_list("pk", flat=True)), [sejour.pk])
        self.assertEqual(list(document_reference.sorties.values_list("pk", flat=True)), [sortie.pk])
        self.assertEqual(list(document_reference.formations.values_list("pk", flat=True)), [formation.pk])

    def test_migration_refuse_une_valeur_historique_inconnue(self):
        document = Document.objects.create(titre="Valeur inconnue", fichier="documents/inconnue.pdf")
        Document.objects.filter(pk=document.pk).update(categorie="inconnue", categorie_ref=None)

        with self.assertRaisesRegex(RuntimeError, "Catégories Document historiques inconnues : inconnue"):
            import_module(
                "animateurs.migrations.0118_categoriedocument_et_reference_temporaire"
            ).creer_categories_et_rattacher_documents(apps, None)

    def test_categorie_utilisee_est_protegee_et_le_renommage_ne_change_pas_le_code(self):
        categorie = CategorieDocument.objects.get(code="autre")
        document = Document.objects.create(titre="Document protégé", fichier="documents/protege.pdf", categorie_ref=categorie)

        categorie.nom = "Documents divers"
        categorie.save(update_fields=["nom"])
        categorie.refresh_from_db()
        self.assertEqual(categorie.code, "autre")

        with self.assertRaises(ProtectedError):
            categorie.delete()
        self.assertTrue(Document.objects.filter(pk=document.pk).exists())


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
        self.assertEqual(document.type_document, Document.TYPE_CLASSIQUE)

    def test_cree_et_modifie_explicitement_un_programme_activites(self):
        response = self.client.post(
            reverse("api_documents"),
            data={
                "titre": "Programme semaine 1",
                "type_document": Document.TYPE_PROGRAMME_ACTIVITES,
                "categorie": Document.CATEGORIE_PEDAGOGIE_ACTIVITES,
                "important": "true",
                "permanent": "true",
                "fichier": SimpleUploadedFile("programme.jpg", b"image", content_type="image/jpeg"),
            },
        )

        self.assertEqual(response.status_code, 201)
        document = Document.objects.get()
        self.assertEqual(document.type_document, Document.TYPE_PROGRAMME_ACTIVITES)
        self.assertEqual(document.categorie, Document.CATEGORIE_PEDAGOGIE_ACTIVITES)
        self.assertTrue(document.important)
        self.assertEqual(response.json()["type_document"], Document.TYPE_PROGRAMME_ACTIVITES)
        self.assertEqual(response.json()["categorie"], Document.CATEGORIE_PEDAGOGIE_ACTIVITES)

        response = self.client.patch(
            reverse("api_document_detail", args=[document.id]),
            data={"type_document": Document.TYPE_CLASSIQUE},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        document.refresh_from_db()
        self.assertEqual(document.type_document, Document.TYPE_CLASSIQUE)

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


class DocumentV2DirectionApiTests(ConnexionTestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="Centre documents V2", code="DV2")
        self.autre_centre = Centre.objects.create(nom="Autre centre V2", code="AV2")
        type_accueil = TypeAccueil.objects.get(code="vacances")
        self.periode = PeriodeScolaire.objects.create(
            nom="Été V2", annee_scolaire="2030-2031", zone="A",
            debut=datetime.date(2030, 7, 1), fin=datetime.date(2030, 7, 5), type_accueil=type_accueil,
        )
        self.autre_periode = PeriodeScolaire.objects.create(
            nom="Été V2 semaine 2", annee_scolaire="2030-2031", zone="A",
            debut=datetime.date(2030, 7, 8), fin=datetime.date(2030, 7, 12), type_accueil=type_accueil,
        )

    def creer_document(self, titre, **kwargs):
        return Document.objects.create(titre=titre, fichier=f"documents/{titre}.pdf", **kwargs)

    def test_gestion_documents_expose_les_vues_et_champs_v2(self):
        response = self.client.get(reverse("gestion"), {"onglet": "documents"})

        self.assertContains(response, "Documents de la période")
        self.assertContains(response, "Permanents")
        self.assertContains(response, "Archives")
        self.assertContains(response, "Catégorie")
        self.assertContains(response, "Lié à une période")
        self.assertContains(response, "Publié à l’équipe")
        self.assertContains(response, "Important")

    def test_vue_periode_utilise_reellement_la_periode_selectionnee(self):
        retenu = self.creer_document("Période retenue", permanent=False, periode_debut=self.periode.debut, periode_fin=self.periode.fin)
        retenu.periodes.add(self.periode)
        autre = self.creer_document("Autre période", permanent=False, periode_debut=self.autre_periode.debut, periode_fin=self.autre_periode.fin)
        autre.periodes.add(self.autre_periode)
        self.creer_document("Permanent", permanent=True)

        response = self.client.get(reverse("api_documents"), {"vue": "periode", "periode_id": self.periode.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["titre"] for item in response.json()], ["Période retenue"])

    def test_vue_permanents_et_archives_distingueraient_les_documents(self):
        permanent = self.creer_document("Protocole permanent", permanent=True)
        passe = PeriodeScolaire.objects.create(
            nom="Historique V2", annee_scolaire="2020-2021", zone="A",
            debut=datetime.date(2020, 7, 1), fin=datetime.date(2020, 7, 5), type_accueil=TypeAccueil.objects.get(code="vacances"),
        )
        historique = self.creer_document("Document historique", permanent=False, periode_debut=passe.debut, periode_fin=passe.fin)
        historique.periodes.add(passe)

        permanents = self.client.get(reverse("api_documents"), {"vue": "permanents"}).json()
        archives = self.client.get(reverse("api_documents"), {"vue": "archives"}).json()

        self.assertEqual([item["id"] for item in permanents], [permanent.pk])
        self.assertEqual([item["id"] for item in archives], [historique.pk])

    def test_archivage_et_restauration_ne_suppriment_ni_fichier_ni_relations(self):
        document = self.creer_document("À archiver")
        document.centres.add(self.centre)
        fichier = document.fichier.name

        archive = self.client.patch(
            reverse("api_document_detail", args=[document.pk]), data={"archive": True}, content_type="application/json"
        )
        document.refresh_from_db()
        self.assertEqual(archive.status_code, 200)
        self.assertIsNotNone(document.archive_le)
        self.assertEqual(document.fichier.name, fichier)
        self.assertEqual(list(document.centres.values_list("pk", flat=True)), [self.centre.pk])

        restaure = self.client.patch(
            reverse("api_document_detail", args=[document.pk]), data={"archive": False}, content_type="application/json"
        )
        document.refresh_from_db()
        self.assertEqual(restaure.status_code, 200)
        self.assertIsNone(document.archive_le)
        self.assertEqual(document.fichier.name, fichier)
        self.assertEqual(list(document.centres.values_list("pk", flat=True)), [self.centre.pk])

    def test_filtres_categorie_centre_publication_et_important(self):
        visible = self.creer_document(
            "Important ciblé", categorie=Document.CATEGORIE_ADMINISTRATIF, important=True, publie=True
        )
        visible.centres.add(self.centre)
        autre = self.creer_document(
            "Autre ciblé", categorie=Document.CATEGORIE_ADMINISTRATIF, publie=False, tous_centres=False
        )
        autre.centres.add(self.autre_centre)

        response = self.client.get(
            reverse("api_documents"),
            {"vue": "permanents", "categorie": "administratif", "centre_id": self.centre.pk, "publie": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [visible.pk])
        self.assertTrue(response.json()[0]["important"])
        self.assertEqual(response.json()[0]["categorie"], Document.CATEGORIE_ADMINISTRATIF)

    def test_programme_activites_reste_identifie_et_serialize_avec_la_categorie(self):
        programme = self.creer_document(
            "Programme intact", type_document=Document.TYPE_PROGRAMME_ACTIVITES,
            categorie=Document.CATEGORIE_PEDAGOGIE_ACTIVITES,
        )

        response = self.client.get(reverse("api_documents"), {"vue": "permanents"})

        programme_json = next(item for item in response.json() if item["id"] == programme.pk)
        self.assertEqual(programme_json["type_document"], Document.TYPE_PROGRAMME_ACTIVITES)
        self.assertEqual(programme_json["categorie"], Document.CATEGORIE_PEDAGOGIE_ACTIVITES)
