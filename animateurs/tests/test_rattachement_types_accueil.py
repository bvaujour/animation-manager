from datetime import date
from importlib import import_module

from django.db import migrations, models

from animateurs.models import (
    ActiviteTravailComplementaire,
    Centre,
    Document,
    EffectifEnfantsJour,
    Evenement,
    Groupe,
    ModeleEmail,
    PeriodeScolaire,
    PublicationPlanning,
    Sortie,
    TypeAccueil,
)
from animateurs.services.rattachement_types_accueil import (
    inferer_type_activite_travail,
    inferer_type_document,
    inferer_type_effectif,
    inferer_type_evenement,
    inferer_type_modele_email,
    inferer_type_publication,
    inferer_type_sortie,
)
from animateurs.tests.base import ConnexionTestCase


class RelationsTypesAccueilNonRegressionTests(ConnexionTestCase):
    def test_nouvelles_relations_restent_facultatives(self):
        centre = Centre.objects.create(nom="Lieu sans classement", code="LSC")
        evenement = Evenement.objects.create(centre=centre, nom="Groupe sans classement")
        effectif = EffectifEnfantsJour.objects.create(
            evenement=evenement,
            date=date(2035, 7, 9),
            nombre=12,
        )
        sortie = Sortie.objects.create(
            nom="Sortie sans classement",
            date=date(2035, 7, 9),
            destination="Destination test",
        )
        publication = PublicationPlanning.objects.create(semaine_debut=date(2035, 7, 9))
        modele = ModeleEmail.objects.create(nom="Modèle sans classement", objet="Test", message="Test")
        groupe = Groupe.objects.create(nom="Définition sans classement")

        self.assertIsNone(effectif.type_accueil)
        self.assertIsNone(sortie.type_accueil)
        self.assertIsNone(publication.type_accueil)
        self.assertFalse(modele.types_accueil.exists())
        self.assertFalse(groupe.types_accueil.exists())

    def test_migration_est_uniquement_structurelle_et_nullable(self):
        migration = import_module("animateurs.migrations.0085_relations_types_accueil_progressives")

        self.assertFalse(any(isinstance(operation, migrations.RunPython) for operation in migration.Migration.operations))
        for modele, champ in (
            (EffectifEnfantsJour, "type_accueil"),
            (PublicationPlanning, "type_accueil"),
            (Sortie, "type_accueil"),
        ):
            self.assertTrue(modele._meta.get_field(champ).null)
        for modele, champ in ((Groupe, "types_accueil"), (ModeleEmail, "types_accueil")):
            self.assertIsInstance(modele._meta.get_field(champ), models.ManyToManyField)
            self.assertTrue(modele._meta.get_field(champ).blank)


class InferenceTypesAccueilTests(ConnexionTestCase):
    def setUp(self):
        super().setUp()
        self.vacances = TypeAccueil.objects.get(code=TypeAccueil.VACANCES)
        self.mercredis = TypeAccueil.objects.get(code=TypeAccueil.MERCREDIS)
        self.centre = Centre.objects.create(nom="Lieu d'inférence", code="LI")

    def periode(self, nom, debut, fin, type_accueil, zone="A"):
        return PeriodeScolaire.objects.create(
            nom=nom,
            annee_scolaire="2035-2036",
            zone=zone,
            debut=debut,
            fin=fin,
            type_accueil=type_accueil,
        )

    def test_inference_concordante_necrit_aucune_donnee(self):
        periode = self.periode("Vacances", date(2035, 7, 9), date(2035, 7, 13), self.vacances)
        evenement = Evenement.objects.create(centre=self.centre, nom="Groupe vacances")
        evenement.periodes_scolaires.add(periode)
        effectif = EffectifEnfantsJour.objects.create(evenement=evenement, date=date(2035, 7, 10), nombre=10)
        document = Document.objects.create(titre="Document vacances", fichier="documents/vacances.pdf")
        document.periodes.add(periode)
        activite = ActiviteTravailComplementaire.objects.create(
            type=ActiviteTravailComplementaire.TYPE_PREPARATION,
            intitule="Préparation vacances",
        )
        activite.periodes.add(periode)
        publication = PublicationPlanning.objects.create(semaine_debut=date(2035, 7, 9))

        self.assertEqual(inferer_type_evenement(evenement), self.vacances)
        self.assertEqual(inferer_type_effectif(effectif), self.vacances)
        self.assertEqual(inferer_type_document(document), self.vacances)
        self.assertEqual(inferer_type_activite_travail(activite), self.vacances)
        self.assertEqual(inferer_type_publication(publication), self.vacances)
        effectif.refresh_from_db()
        document.refresh_from_db()
        self.assertIsNone(effectif.type_accueil)
        self.assertFalse(document.types_accueil.exists())

    def test_inference_refuse_les_donnees_ambigues(self):
        vacances = self.periode("Vacances ambiguës", date(2035, 8, 6), date(2035, 8, 10), self.vacances)
        mercredis = self.periode(
            "Mercredis ambigus",
            date(2035, 8, 6),
            date(2035, 8, 10),
            self.mercredis,
            zone="B",
        )
        evenement = Evenement.objects.create(centre=self.centre, nom="Groupe ambigu")
        evenement.periodes_scolaires.add(vacances, mercredis)
        document = Document.objects.create(titre="Document ambigu", fichier="documents/ambigu.pdf")
        document.periodes.add(vacances, mercredis)
        sortie = Sortie.objects.create(
            nom="Sortie non rattachée",
            date=date(2035, 8, 8),
            destination="Destination test",
        )
        modele = ModeleEmail.objects.create(nom="Modèle ambigu", objet="Test", message="Test")
        modele.types_accueil.add(self.vacances, self.mercredis)

        self.assertIsNone(inferer_type_evenement(evenement))
        self.assertIsNone(inferer_type_document(document))
        self.assertIsNone(inferer_type_sortie(sortie))
        self.assertIsNone(inferer_type_modele_email(modele))
