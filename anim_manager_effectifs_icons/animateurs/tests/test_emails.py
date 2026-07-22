import datetime
import json
import tempfile

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    ContactEmailExterne,
    Document,
    Evenement,
    ModeleEmail,
    PeriodeScolaire,
    Qualification,
)
from animateurs.tests.base import ConnexionTestCase


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Gestion animation <planning@example.fr>",
    EMAIL_REPLY_TO="direction@example.fr",
    DEBUG=True,
)
class EnvoiEmailApiTests(ConnexionTestCase):
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
        self.assertEqual(payload["modeles"], [])
        self.assertEqual([variable["code"] for variable in payload["variables"]], ["{{prenom}}", "{{nom}}", "{{nom_semaine}}", "{{date_debut_semaine}}", "{{date_fin_semaine}}", "{{affectations_semaine}}"] )
        self.assertNotIn("historique", payload)

    def test_preparation_expose_les_qualifications_et_la_hierarchie_des_semaines(self):
        qualification = Qualification.objects.create(nom="BAFA")
        self.ambre.qualifications.add(qualification)
        periode = PeriodeScolaire.objects.create(
            nom="Été — Semaine 1",
            annee_scolaire="2025-2026",
            zone="A",
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )

        payload = self.client.get("/api/envois-email/").json()

        self.assertEqual(payload["qualifications"], [{"id": qualification.id, "nom": "BAFA"}])
        ambre = next(item for item in payload["animateurs"] if item["id"] == self.ambre.id)
        self.assertEqual(ambre["qualification_ids"], [qualification.id])
        semaine = next(item for item in payload["periodes"] if item["id"] == periode.id)
        self.assertEqual(semaine["annee_scolaire"], "2025-2026")
        self.assertEqual(semaine["vacances"], "Été")
        self.assertEqual(semaine["semaine"], "Semaine 1")

    def test_preparation_identifie_la_semaine_actuelle_sans_la_selectionner(self):
        aujourd_hui = timezone.localdate()
        actuelle = PeriodeScolaire.objects.create(
            nom="Période actuelle — Semaine 1",
            annee_scolaire="2025-2026",
            zone="A",
            debut=aujourd_hui - datetime.timedelta(days=2),
            fin=aujourd_hui + datetime.timedelta(days=2),
        )
        future = PeriodeScolaire.objects.create(
            nom="Période future — Semaine 2",
            annee_scolaire="2025-2026",
            zone="A",
            debut=aujourd_hui + datetime.timedelta(days=7),
            fin=aujourd_hui + datetime.timedelta(days=11),
        )

        periodes = {
            item["id"]: item
            for item in self.client.get("/api/envois-email/").json()["periodes"]
        }

        self.assertTrue(periodes[actuelle.id]["est_actuelle"])
        self.assertFalse(periodes[future.id]["est_actuelle"])

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
        self.assertEqual(mail.outbox[0].body, "Tu trouveras les documents en pièce jointe.")
        self.assertEqual(mail.outbox[1].body, "Tu trouveras les documents en pièce jointe.")

    def test_personnalise_les_variables_de_la_semaine_selectionnee(self):
        periode = PeriodeScolaire.objects.create(
            nom="Été — Semaine 3",
            annee_scolaire="2025-2026",
            zone="A",
            debut=datetime.date(2026, 7, 20),
            fin=datetime.date(2026, 7, 24),
        )
        preparation = self.client.get("/api/envois-email/").json()
        self.assertEqual(preparation["periodes"][0]["libelle"], "Été 2026 — Semaine 3")

        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "document_ids": [],
                "periode_id": periode.id,
                "objet": "{{nom_semaine}}",
                "message": "Du {{date_debut_semaine}} au {{date_fin_semaine}}",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mail.outbox[0].subject,
            "Été — période du 20/07/2026 au 24/07/2026",
        )
        self.assertEqual(mail.outbox[0].body, "Du 20/07/2026 au 24/07/2026")

    def test_personnalise_les_affectations_de_toute_la_semaine(self):
        periode = PeriodeScolaire.objects.create(
            nom="Été — Semaine 3",
            annee_scolaire="2025-2026",
            zone="A",
            debut=datetime.date(2026, 7, 20),
            fin=datetime.date(2026, 7, 24),
        )
        centre = Centre.objects.create(nom="La Pacaudière", code="PAC")
        groupe = Evenement.objects.create(centre=centre, nom="Élémentaires")
        Affectation.objects.create(
            animateur=self.ambre,
            centre=centre,
            evenement=groupe,
            debut=timezone.make_aware(datetime.datetime(2026, 7, 20, 0, 0)),
            fin=timezone.make_aware(datetime.datetime(2026, 7, 22, 0, 0)),
        )

        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "document_ids": [],
                "periode_id": periode.id,
                "objet": "Planning {{prenom}}",
                "message": "Tes affectations :\n{{affectations_semaine}}",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mail.outbox[0].body,
            "Tes affectations :\n"
            "Lundi 20/07/2026 — La Pacaudière — Élémentaires\n"
            "Mardi 21/07/2026 — La Pacaudière — Élémentaires",
        )

    def test_personnalise_plusieurs_semaines_selectionnees(self):
        semaine_1 = PeriodeScolaire.objects.create(
            nom="Été — Semaine 1",
            annee_scolaire="2025-2026",
            zone="A",
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )
        semaine_2 = PeriodeScolaire.objects.create(
            nom="Été — Semaine 2",
            annee_scolaire="2025-2026",
            zone="A",
            debut=datetime.date(2026, 7, 13),
            fin=datetime.date(2026, 7, 17),
        )
        centre = Centre.objects.create(nom="Le Crozet", code="CRO")
        groupe = Evenement.objects.create(centre=centre, nom="Maternels")
        Affectation.objects.create(
            animateur=self.ambre,
            centre=centre,
            evenement=groupe,
            debut=timezone.make_aware(datetime.datetime(2026, 7, 6, 0, 0)),
            fin=timezone.make_aware(datetime.datetime(2026, 7, 7, 0, 0)),
        )
        Affectation.objects.create(
            animateur=self.ambre,
            centre=centre,
            evenement=groupe,
            debut=timezone.make_aware(datetime.datetime(2026, 7, 14, 0, 0)),
            fin=timezone.make_aware(datetime.datetime(2026, 7, 15, 0, 0)),
        )

        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "document_ids": [],
                "periode_ids": [semaine_2.id, semaine_1.id],
                "objet": "{{nom_semaine}}",
                "message": "Du {{date_debut_semaine}} au {{date_fin_semaine}}\n{{affectations_semaine}}",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mail.outbox[0].subject,
            "Été — période du 06/07/2026 au 17/07/2026",
        )
        self.assertEqual(
            mail.outbox[0].body,
            "Du 06/07/2026 au 17/07/2026\n"
            "Lundi 06/07/2026 — Le Crozet — Maternels\n"
            "Mardi 14/07/2026 — Le Crozet — Maternels",
        )

    def test_nom_semaine_ne_regroupe_pas_des_semaines_non_consecutives(self):
        semaine_1 = PeriodeScolaire.objects.create(
            nom="Été — Semaine 1",
            annee_scolaire="2025-2026",
            zone="A",
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )
        semaine_3 = PeriodeScolaire.objects.create(
            nom="Été — Semaine 3",
            annee_scolaire="2025-2026",
            zone="A",
            debut=datetime.date(2026, 7, 20),
            fin=datetime.date(2026, 7, 24),
        )

        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "document_ids": [],
                "periode_ids": [semaine_1.id, semaine_3.id],
                "objet": "{{nom_semaine}}",
                "message": "Information",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mail.outbox[0].subject,
            "Été — période du 06/07/2026 au 10/07/2026 ; "
            "Été — période du 20/07/2026 au 24/07/2026",
        )

    def test_refuse_une_liste_de_semaines_invalide(self):
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "document_ids": [],
                "periode_ids": [999999],
                "objet": "Information",
                "message": "Message",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("semaines", response.json()["error"])

    def test_personnalise_nom_et_prenom_pour_chaque_salarie(self):
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id, self.gael.id],
                "document_ids": [],
                "objet": "Information pour {{prenom}} {{nom}}",
                "message": "Bonjour {{prenom}}, contenu libre. {{planning_semaine}}",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[0].subject, "Information pour Ambre Bain")
        self.assertEqual(mail.outbox[1].subject, "Information pour Gaël Jarlier")
        self.assertEqual(mail.outbox[0].body, "Bonjour Ambre, contenu libre. {{planning_semaine}}")
        self.assertEqual(mail.outbox[1].body, "Bonjour Gaël, contenu libre. {{planning_semaine}}")


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
        self.assertEqual(len(mail.outbox), 0)

    def test_autorise_un_envoi_sans_document(self):
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "document_ids": [],
                "objet": "Information été",
                "message": "Message sans pièce jointe.",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["nombre_envoyes"], 1)
        self.assertEqual(mail.outbox[0].attachments, [])

    def test_gere_des_contacts_externes_distincts_des_salaries(self):
        creation = self.client.post(
            "/api/contacts-email/",
            data=json.dumps({
                "prenom": "Julie",
                "nom": "Durand",
                "email": "julie.durand@example.fr",
                "organisation": "Mairie",
            }),
            content_type="application/json",
        )
        self.assertEqual(creation.status_code, 201)
        contact_id = creation.json()["id"]
        preparation = self.client.get("/api/envois-email/").json()
        self.assertEqual(preparation["contacts_externes"][0]["organisation"], "Mairie")

        envoi = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [self.ambre.id],
                "contact_ids": [contact_id],
                "document_ids": [],
                "objet": "Bonjour {{prenom}}",
                "message": "Message pour {{prenom}} {{nom}}",
            }),
            content_type="application/json",
        )
        self.assertEqual(envoi.status_code, 200)
        self.assertEqual(envoi.json()["nombre_envoyes"], 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].subject, "Bonjour Julie")

    def test_modifie_et_supprime_un_contact_externe(self):
        contact = ContactEmailExterne.objects.create(nom="Traiteur", email="contact@example.fr")
        modification = self.client.patch(
            f"/api/contacts-email/{contact.id}/",
            data=json.dumps({"prenom": "Paul", "nom": "Traiteur", "email": "paul@example.fr", "organisation": "Cuisine", "actif": True}),
            content_type="application/json",
        )
        self.assertEqual(modification.status_code, 200)
        contact.refresh_from_db()
        self.assertEqual(contact.prenom, "Paul")
        suppression = self.client.delete(f"/api/contacts-email/{contact.id}/")
        self.assertEqual(suppression.status_code, 200)
        self.assertFalse(ContactEmailExterne.objects.filter(pk=contact.id).exists())


class ConfigurationEmailProductionTests(ConnexionTestCase):
    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        EMAIL_HOST="",
        DEBUG=False,
    )
    def test_backend_console_refuse_en_production(self):
        animateur = Animateur.objects.create(
            prenom="Julie", nom="Martin", email="julie@example.fr"
        )
        response = self.client.post(
            "/api/envois-email/",
            data=json.dumps({
                "animateur_ids": [animateur.id],
                "document_ids": [],
                "objet": "Contrat",
                "message": "Voici ton contrat.",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("production", response.json()["error"].lower())


class ModeleEmailApiTests(ConnexionTestCase):
    def test_cree_modifie_desactive_et_supprime_un_modele(self):
        creation = self.client.post(
            "/api/modeles-email/",
            data=json.dumps({
                "nom": "Rappel équipe",
                "objet": "Rappel pour {{prenom}}",
                "message": "Réunion prévue le {{date_du_jour}}.",
                "actif": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(creation.status_code, 201)
        modele_id = creation.json()["id"]
        self.assertEqual(ModeleEmail.objects.count(), 1)

        liste = self.client.get("/api/modeles-email/")
        self.assertEqual(liste.status_code, 200)
        self.assertEqual(liste.json()["modeles"][0]["nom"], "Rappel équipe")
        self.assertIn("{{prenom}}", [item["code"] for item in liste.json()["variables"]])

        modification = self.client.patch(
            f"/api/modeles-email/{modele_id}/",
            data=json.dumps({
                "nom": "Rappel réunion",
                "objet": "Réunion de {{prenom}}",
                "message": "Merci de confirmer ta présence.",
                "actif": False,
            }),
            content_type="application/json",
        )
        self.assertEqual(modification.status_code, 200)
        self.assertFalse(modification.json()["actif"])
        self.assertEqual(ModeleEmail.objects.get().nom, "Rappel réunion")

        preparation_envoi = self.client.get("/api/envois-email/")
        self.assertEqual(preparation_envoi.json()["modeles"], [])

        suppression = self.client.delete(f"/api/modeles-email/{modele_id}/")
        self.assertEqual(suppression.status_code, 204)
        self.assertFalse(ModeleEmail.objects.exists())

    def test_refuse_deux_modeles_avec_le_meme_nom_sans_tenir_compte_de_la_casse(self):
        ModeleEmail.objects.create(nom="Planning", objet="Objet", message="Message")
        response = self.client.post(
            "/api/modeles-email/",
            data=json.dumps({
                "nom": "planning",
                "objet": "Autre objet",
                "message": "Autre message",
                "actif": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("déjà", response.json()["error"])

class VariablesEmailDisponiblesTests(ConnexionTestCase):
    def test_variables_destinataire_et_semaine_sont_proposees(self):
        animateur = Animateur.objects.create(prenom="Julie", nom="Test", email="julie@example.fr")
        response = self.client.get(f"/api/animateurs/{animateur.id}/emails/")
        self.assertEqual(response.status_code, 200)
        codes = [item["code"] for item in response.json()["variables"]]
        self.assertEqual(codes, ["{{prenom}}", "{{nom}}", "{{nom_semaine}}", "{{date_debut_semaine}}", "{{date_fin_semaine}}", "{{affectations_semaine}}"] )
