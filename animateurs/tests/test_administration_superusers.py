from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdministrationSuperusersTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.master = self.User.objects.create_superuser(
            username="master", email="master@example.com", password="Password123!"
        )
        self.client.force_login(self.master)

    def test_administration_regroupe_export_emails_et_superusers(self):
        response = self.client.get(reverse("administration"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planning calendrier par groupe")
        self.assertContains(response, "E-mails")
        self.assertContains(response, "Superusers")

    def test_acces_direct_aux_emails_active_le_bon_onglet(self):
        response = self.client.get(reverse("emails"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], "/administration/?onglet=emails")
        self.assertContains(response, 'data-admin-tab="emails" type="button" role="tab" aria-selected="true"', html=False)
        self.assertContains(response, 'data-admin-panel="emails">', html=False)
        self.assertNotContains(response, 'data-admin-panel="emails" hidden', html=False)

    def test_creation_et_suppression_superuser(self):
        response = self.client.post(reverse("administration"), {
            "action": "create_superuser",
            "username": "second",
            "email": "second@example.com",
            "password": "Password123!",
            "confirmation": "Password123!",
        })
        self.assertEqual(response.status_code, 200)
        second = self.User.objects.get(username="second")
        self.assertTrue(second.is_superuser)
        self.client.post(reverse("administration"), {
            "action": "delete_superuser", "user_id": second.pk,
        })
        self.assertFalse(self.User.objects.filter(pk=second.pk).exists())

    def test_modification_de_son_propre_mot_de_passe(self):
        response = self.client.post(reverse("administration"), {
            "action": "change_own_password",
            "old_password": "Password123!",
            "new_password": "NewPassword123!",
            "new_password_confirmation": "NewPassword123!",
        })
        self.assertEqual(response.status_code, 200)
        self.master.refresh_from_db()
        self.assertTrue(self.master.check_password("NewPassword123!"))
        self.assertEqual(self.client.get(reverse("administration")).status_code, 200)
