import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from animateurs.models import Animateur, CategorieDocument, Document
from animateurs.tests.base import ConnexionTestCase


class CategoriesDocumentsApiTests(ConnexionTestCase):
    def setUp(self):
        self.list_url = reverse("api_categories_documents")

    def detail_url(self, categorie):
        return reverse("api_categorie_document_detail", args=[categorie.pk])

    def move_url(self, categorie):
        return reverse("api_categorie_document_deplacer", args=[categorie.pk])

    def test_affiche_les_cinq_categories_initiales_depuis_la_bibliotheque(self):
        response = self.client.get(f"{reverse('gestion')}?onglet=documents")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gérer les catégories")
        self.assertContains(response, 'id="document-categories-dialog"')
        self.assertContains(response, 'id="document-categories-dialog-content"')
        self.assertNotContains(response, 'data-tab="categories-documents"')
        self.assertNotContains(response, 'data-panel="categories-documents"')

        categories = self.client.get(self.list_url).json()
        self.assertEqual(len(categories), 5)
        self.assertEqual([item["code"] for item in categories], [
            "pedagogie_activites", "organisation_planning", "protocoles_securite", "administratif", "autre",
        ])

    def test_modal_monte_le_gestionnaire_unique_avec_les_scripts_versionnes(self):
        template = Path(settings.BASE_DIR, "templates/gestion.html").read_text(encoding="utf-8")
        script = Path(settings.BASE_DIR, "static/js/gestion.js").read_text(encoding="utf-8")

        documents_script = Path(settings.BASE_DIR, "static/js/documents-management.js").read_text(encoding="utf-8")

        self.assertNotIn('data-tab="categories-documents"', template)
        self.assertNotIn('data-panel="categories-documents"', template)
        self.assertNotIn('panel-categories-documents', template)
        self.assertIn('id="document-categories-dialog"', template)
        self.assertIn('gestion-categories-v5', template)
        self.assertIn('documents-categories-v2', template)
        self.assertIn('function mountCategoriesDocuments(container, options = {})', script)
        self.assertIn('options.embedded', script)
        self.assertIn('options.onChange?.()', script)
        self.assertIn('GestionApp.mountCategoriesDocuments(categoriesDialogContent', documents_script)
        self.assertIn('rafraichirApresMutationCategorie', documents_script)
        self.assertIn('categoriesDialog.showModal()', documents_script)
        self.assertIn('class="document-category-list-header"', script)
        self.assertIn('class="document-category-name"', script)
        self.assertIn('class="document-category-status"', script)
        self.assertIn('class="btn btn-danger btn-small document-category-delete"', script)
        self.assertIn('disabled aria-disabled="true"', script)
        self.assertIn('const libelleDocumentsLies', script)
        self.assertIn('document${count > 1 ? "s" : ""}', script)
        self.assertIn('Catégorie protégée', script)
        self.assertIn('Utilisée par ${libelleDocumentsLies(item.documents_count)}', script)
        self.assertIn('class="document-category-delete-tooltip"', script)
        self.assertNotIn('document-category-delete-reason', script)
        styles = Path(settings.BASE_DIR, "static/css/gestion.css").read_text(encoding="utf-8")
        self.assertIn("--document-category-actions-width:420px", styles)
        self.assertIn("80px var(--document-category-actions-width)", styles)

    def test_ajout_genere_un_code_unique_en_cas_de_collision(self):
        premier = self.client.post(
            self.list_url, data=json.dumps({"nom": "Nouvelle catégorie"}), content_type="application/json"
        )
        second = self.client.post(
            self.list_url, data=json.dumps({"nom": "Nouvelle-catégorie"}), content_type="application/json"
        )

        self.assertEqual(premier.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(premier.json()["code"], "nouvelle-categorie")
        self.assertEqual(second.json()["code"], "nouvelle-categorie-2")
        self.assertTrue(premier.json()["active"])

    def test_renommage_conserve_le_code(self):
        categorie = CategorieDocument.objects.get(code="administratif")
        response = self.client.patch(
            self.detail_url(categorie), data=json.dumps({"nom": "Administration"}), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        categorie.refresh_from_db()
        self.assertEqual(categorie.nom, "Administration")
        self.assertEqual(categorie.code, "administratif")

    def test_liste_expose_le_nombre_de_documents_lies_et_le_droit_de_suppression(self):
        utilisee = CategorieDocument.objects.get(code="pedagogie_activites")
        libre = CategorieDocument.objects.get(code="organisation_planning")
        Document.objects.create(
            titre="Document lié", fichier="documents/lie.pdf", categorie_ref=utilisee
        )

        categories = {item["code"]: item for item in self.client.get(self.list_url).json()}
        self.assertEqual(categories["pedagogie_activites"]["documents_count"], 1)
        self.assertFalse(categories["pedagogie_activites"]["peut_supprimer"])
        self.assertEqual(categories["organisation_planning"]["documents_count"], 0)
        self.assertTrue(categories["organisation_planning"]["peut_supprimer"])
        self.assertEqual(categories["autre"]["documents_count"], 0)
        self.assertFalse(categories["autre"]["peut_supprimer"])

    def test_reordonnancement_echange_les_deux_categories(self):
        categorie = CategorieDocument.objects.get(code="pedagogie_activites")
        response = self.client.post(
            self.move_url(categorie), data=json.dumps({"direction": "bas"}), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["code"] for item in response.json()[:2]], [
            "organisation_planning", "pedagogie_activites",
        ])

    def test_activation_et_desactivation(self):
        categorie = CategorieDocument.objects.get(code="administratif")
        response = self.client.patch(
            self.detail_url(categorie), data=json.dumps({"active": False}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["active"])

        response = self.client.patch(
            self.detail_url(categorie), data=json.dumps({"active": True}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["active"])

    def test_autre_ne_peut_etre_ni_desactivee_ni_supprimee(self):
        categorie = CategorieDocument.objects.get(code="autre")
        response = self.client.patch(
            self.detail_url(categorie), data=json.dumps({"active": False}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("doit rester active", response.json()["error"])
        self.assertEqual(self.client.delete(self.detail_url(categorie)).status_code, 400)
        self.assertTrue(CategorieDocument.objects.filter(pk=categorie.pk).exists())

    def test_supprime_une_categorie_inutilisee(self):
        categorie = CategorieDocument.objects.create(nom="À supprimer", code="a-supprimer", ordre=99)
        response = self.client.delete(self.detail_url(categorie))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(CategorieDocument.objects.filter(pk=categorie.pk).exists())

    def test_refuse_la_suppression_d_une_categorie_utilisee(self):
        categorie = CategorieDocument.objects.get(code="administratif")
        Document.objects.create(
            titre="Document lié", fichier="documents/lie.pdf", categorie_ref=categorie
        )

        response = self.client.delete(self.detail_url(categorie))
        self.assertEqual(response.status_code, 409)
        self.assertIn("utilisée", response.json()["error"])
        self.assertTrue(CategorieDocument.objects.filter(pk=categorie.pk).exists())


class CategoriesDocumentsPermissionsTests(TestCase):
    def setUp(self):
        self.list_url = reverse("api_categories_documents")

    def test_direction_superuser_est_autorisee(self):
        user = get_user_model().objects.create_superuser("direction", "direction@example.com", "secret")
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get(self.list_url).status_code, 200)

    def test_direction_non_superuser_et_animateur_sont_refuses(self):
        direction = get_user_model().objects.create_user(username="direction", password="secret", is_staff=True)
        animateur_user = get_user_model().objects.create_user(username="animateur", password="secret")
        Animateur.objects.create(prenom="Ada", nom="Lovelace", utilisateur=animateur_user)

        for user in (direction, animateur_user):
            with self.subTest(user=user.username):
                client = Client()
                client.force_login(user)
                self.assertEqual(client.get(self.list_url).status_code, 403)
                self.assertEqual(
                    client.post(self.list_url, data=json.dumps({"nom": "Interdit"}), content_type="application/json").status_code,
                    403,
                )
