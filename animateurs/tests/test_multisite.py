import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse

from animateurs.models import Centre, Evenement, Groupe, ParametresStructure
from animateurs.services.multisite import trouver_ou_creer_groupe
from animateurs.tests.base import ConnexionTestCase
from animateurs.views_sorties import _groupes_selectionnes


class MultisiteTests(ConnexionTestCase):
    def setUp(self):
        self.parametres, _ = ParametresStructure.objects.get_or_create(cle="principale")
        self.a = Centre.objects.create(nom="Centre A", code="CTA")

    def local(self, centre, nom="Petits"):
        return Groupe.objects.create(nom=nom, portee=Groupe.LOCAL, centre=centre)

    def instance(self, groupe, centre):
        return Evenement.objects.create(groupe=groupe, centre=centre, nom=groupe.nom)

    def test_configuration_defaut_et_monosite_coherent(self):
        self.assertTrue(self.parametres.multisite)
        self.parametres.multisite = False
        self.parametres.save()
        self.assertFalse(ParametresStructure.objects.get(pk=self.parametres.pk).multisite)
        self.assertFalse(self.client.get(reverse("api_parametres")).json()["multisite"])
        with self.assertRaises(ValidationError):
            Centre.objects.create(nom="Centre B", code="CTB")

    def test_parametres_api_et_refus_si_plusieurs_centres(self):
        url = reverse("api_parametres")
        data = self.client.get(url).json()
        data["multisite"] = False
        self.assertEqual(self.client.put(url, json.dumps(data), content_type="application/json").status_code, 200)
        data["multisite"] = True
        self.assertEqual(self.client.put(url, json.dumps(data), content_type="application/json").status_code, 200)
        Centre.objects.create(nom="Centre B", code="CTB")
        data["multisite"] = False
        response = self.client.put(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.parametres.refresh_from_db()
        self.assertTrue(self.parametres.multisite)

    def test_locaux_homonymes_distincts_et_unicite(self):
        b = Centre.objects.create(nom="Centre B", code="CTB")
        premier = self.local(self.a)
        second = self.local(b)
        partage = Groupe.objects.create(nom="Petits")
        self.assertEqual(len({premier.pk, second.pk, partage.pk}), 3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.local(self.a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Groupe.objects.create(nom="Petits")
        trouve, cree = trouver_ou_creer_groupe("Petits", b, portee="LOCAL")
        self.assertFalse(cree)
        self.assertEqual(trouve, second)

    def test_local_intercentre_refuse(self):
        b = Centre.objects.create(nom="Centre B", code="CTB")
        groupe = self.local(self.a)
        self.instance(groupe, self.a)
        with self.assertRaises(ValidationError):
            self.instance(groupe, b)
        response = self.client.post(reverse("api_groupes", args=[b.pk]), json.dumps({"groupe_id": groupe.pk}), content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_api_local_creation_et_absence_propagation_homonyme(self):
        b = Centre.objects.create(nom="Centre B", code="CTB")
        premier, second = self.local(self.a), self.local(b)
        un, deux = self.instance(premier, self.a), self.instance(second, b)
        response = self.client.patch(reverse("api_groupe_partage_detail", args=[premier.pk]), json.dumps({"nom": "Nouveau nom", "enfants_par_animateur_defaut": 6}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        un.refresh_from_db()
        deux.refresh_from_db()
        self.assertEqual(un.nom, "Nouveau nom")
        self.assertEqual(deux.nom, "Petits")
        response = self.client.post(reverse("api_groupes_partages"), json.dumps({"nom": "Grands", "portee": "LOCAL", "centre_id": self.a.pk}), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["centre_id"], self.a.pk)

    def test_partage_propagation_et_sortie_multisite_explicitement_selectionnee(self):
        b = Centre.objects.create(nom="Centre B", code="CTB")
        groupe = Groupe.objects.create(nom="Partagés", portee="PARTAGE")
        un, deux = self.instance(groupe, self.a), self.instance(groupe, b)
        self.assertEqual(len(_groupes_selectionnes([un.pk, deux.pk])), 2)
        self.assertEqual([g.pk for g in _groupes_selectionnes([un.pk])], [un.pk])
        self.client.patch(reverse("api_groupe_partage_detail", args=[groupe.pk]), json.dumps({"nom": "Renommés"}), content_type="application/json")
        un.refresh_from_db()
        deux.refresh_from_db()
        self.assertEqual((un.nom, deux.nom), ("Renommés", "Renommés"))
        groupe.portee, groupe.centre = "LOCAL", self.a
        with self.assertRaises(ValidationError):
            groupe.save()

    def test_monosite_anciens_rattachements_incompatibles_non_supprimes(self):
        b = Centre.objects.create(nom="Centre B", code="CTB")
        groupe = Groupe.objects.create(nom="Partagés")
        un = self.instance(groupe, self.a)
        # Simule une configuration incohérente importée : les écritures normales
        # ne permettent pas ce changement, mais les gardes doivent rester efficaces.
        ParametresStructure.objects.filter(pk=self.parametres.pk).update(multisite=False)
        with self.assertRaises(ValidationError):
            self.instance(groupe, b)
        self.assertTrue(Evenement.objects.filter(pk=un.pk).exists())

    def test_monosite_creation_sans_definition_reste_locale(self):
        self.parametres.multisite = False
        self.parametres.save()
        evenement = Evenement.objects.create(centre=self.a, nom="Automatique")
        self.assertEqual(evenement.groupe.portee, "LOCAL")
        self.assertEqual(evenement.groupe.centre_id, self.a.pk)


class MigrationMultisiteTests(TransactionTestCase):
    def test_migration_preserve_structure_et_instances(self):
        avant = [("animateurs", "0115_animateur_actif")]
        apres = [("animateurs", "0116_portee_groupes_multisite")]
        executor = MigrationExecutor(connection)
        executor.migrate(avant)
        try:
            apps = executor.loader.project_state(avant).apps
            param, _ = apps.get_model("animateurs", "ParametresStructure").objects.get_or_create(cle="principale")
            groupe = apps.get_model("animateurs", "Groupe").objects.create(nom="AJS partagé", cle_unique="ajs partage")
            ids = []
            for nom, code in (("A", "CTA"), ("B", "CTB")):
                centre = apps.get_model("animateurs", "Centre").objects.create(nom=nom, code=code, cle_unique=nom.lower())
                ids.append(apps.get_model("animateurs", "Evenement").objects.create(centre=centre, groupe=groupe, nom=groupe.nom).pk)
        finally:
            MigrationExecutor(connection).migrate(apres)
        self.assertTrue(ParametresStructure.objects.get(pk=param.pk).multisite)
        self.assertEqual(Groupe.objects.get(pk=groupe.pk).portee, "PARTAGE")
        self.assertEqual(Evenement.objects.filter(pk__in=ids, groupe_id=groupe.pk).count(), 2)
