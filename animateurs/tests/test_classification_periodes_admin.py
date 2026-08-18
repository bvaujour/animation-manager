from datetime import date

from django.contrib.auth import get_user_model
from django.urls import reverse

from animateurs.models import Centre, Document, EffectifEnfantsJour, Evenement, PeriodeScolaire, TypeAccueil
from animateurs.services.rattachement_types_accueil import (
    filtrer_objets_par_type_herite,
    inferer_type_document,
    inferer_type_effectif,
    inferer_type_evenement,
)
from animateurs.tests.base import ConnexionTestCase


class ClassificationPeriodesAdminTests(ConnexionTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("admin:animateurs_periodescolaire_classification")
        self.vacances = TypeAccueil.objects.get(code=TypeAccueil.VACANCES)
        self.mercredis = TypeAccueil.objects.get(code=TypeAccueil.MERCREDIS)
        self.centre = Centre.objects.create(nom="Centre classification", code="CC")
        self.periode = PeriodeScolaire.objects.create(
            nom="Période à décider",
            annee_scolaire="2036-2037",
            zone="A",
            debut=date(2036, 7, 7),
            fin=date(2036, 7, 18),
        )
        self.groupe = Evenement.objects.create(centre=self.centre, nom="Groupe associé")
        self.groupe.periodes_scolaires.add(self.periode)

    def test_page_ne_propose_plus_les_periodes_desormais_classees(self):
        PeriodeScolaire.objects.create(
            nom="Déjà classée",
            annee_scolaire="2036-2037",
            zone="B",
            debut=date(2036, 8, 4),
            fin=date(2036, 8, 8),
            type_accueil=self.mercredis,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Toutes les périodes sont déjà classées")
        self.assertNotContains(response, "Période à décider")
        self.assertNotContains(response, "Déjà classée")

    def test_liste_admin_affiche_un_bouton_clairement_visible(self):
        response = self.client.get(reverse("admin:animateurs_periodescolaire_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Classifier les périodes")
        self.assertContains(response, self.url)

    def test_periodes_creees_hors_interface_recoivent_le_repli_vacances(self):
        seconde = PeriodeScolaire.objects.create(
            nom="Seconde période",
            annee_scolaire="2036-2037",
            zone="B",
            debut=date(2036, 9, 1),
            fin=date(2036, 9, 5),
        )
        self.periode.refresh_from_db()
        seconde.refresh_from_db()
        self.assertEqual(self.periode.type_accueil, self.vacances)
        self.assertEqual(seconde.type_accueil, self.vacances)

    def test_objets_lies_heritent_du_type_sans_recopie(self):
        effectif = EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=date(2036, 7, 8),
            nombre=9,
        )
        document = Document.objects.create(titre="Document hérité", fichier="documents/herite.pdf")
        document.periodes.add(self.periode)
        self.periode.type_accueil = self.vacances
        self.periode.save(update_fields=("type_accueil",))

        self.assertEqual(inferer_type_effectif(effectif), self.vacances)
        self.assertEqual(inferer_type_document(document), self.vacances)
        self.assertEqual(
            filtrer_objets_par_type_herite([effectif], TypeAccueil.VACANCES, inclure_generaux=False),
            [effectif],
        )
        self.assertIsNone(effectif.type_accueil)
        self.assertFalse(document.types_accueil.exists())

    def test_relation_ambigue_reste_indeterminee_et_inchangee(self):
        autre = PeriodeScolaire.objects.create(
            nom="Contexte non décidé",
            annee_scolaire="2036-2037",
            zone="B",
            debut=date(2036, 7, 7),
            fin=date(2036, 7, 18),
            type_accueil=self.mercredis,
        )
        self.groupe.periodes_scolaires.add(autre)
        self.periode.type_accueil = self.vacances
        self.periode.save(update_fields=("type_accueil",))

        self.assertIsNone(inferer_type_evenement(self.groupe))
        autre.refresh_from_db()
        self.assertEqual(autre.type_accueil, self.mercredis)

    def test_acces_anonyme_reste_protege(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/connexion/", response.url)

        utilisateur = get_user_model().objects.create_user(username="sans-permission", password="secret")
        utilisateur.is_staff = True
        utilisateur.save(update_fields=("is_staff",))
        self.client.force_login(utilisateur)
        self.assertEqual(self.client.get(self.url).status_code, 403)
