import datetime

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Disponibilite,
    Evenement,
    EQUIPE_PRINCIPALE_NOM,
    PreferenceCentre,
)
from animateurs.services.affectations import creer_affectation, modifier_affectation
from animateurs.services.planning_solver import generer_planning_auto


class EvenementDataLayerTests(TestCase):
    def setUp(self):
        self.centre_a = Centre.objects.create(
            nom="Centre A",
            code="CA",
            couleur="#123456",
            effectif_cible=3,
        )
        self.centre_b = Centre.objects.create(
            nom="Centre B",
            code="CB",
            couleur="#654321",
            effectif_cible=2,
        )
        self.animateur = Animateur.objects.create(prenom="Julie", nom="Test")
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )

    def test_nouveau_centre_recoit_une_evenement_principale(self):
        evenement = self.centre_a.evenements.get()
        self.assertEqual(evenement.nom, EQUIPE_PRINCIPALE_NOM)
        self.assertEqual(evenement.effectif_cible, 3)
        self.assertTrue(evenement.active)

    def test_creation_affectation_existante_utilise_evenement_principale(self):
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        affectation = creer_affectation(
            animateur=self.animateur,
            centre=self.centre_a,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

        self.assertEqual(affectation.evenement.centre, self.centre_a)
        self.assertEqual(affectation.evenement.nom, EQUIPE_PRINCIPALE_NOM)

    def test_deplacement_entre_centres_change_aussi_evenement(self):
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        affectation = creer_affectation(
            animateur=self.animateur,
            centre=self.centre_a,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

        modifier_affectation(affectation, centre=self.centre_b)
        affectation.refresh_from_db()

        self.assertEqual(affectation.centre, self.centre_b)
        self.assertEqual(affectation.evenement.centre, self.centre_b)

    def test_creation_directe_reste_compatible(self):
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        affectation = Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre_a,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )
        self.assertIsNotNone(affectation.evenement_id)
        self.assertEqual(affectation.evenement.centre, self.centre_a)

    def test_horaires_incoherents_refuses(self):
        evenement = Evenement(
            centre=self.centre_a,
            nom="Soir",
            heure_debut=datetime.time(18, 0),
            heure_fin=datetime.time(12, 0),
        )
        with self.assertRaises(ValidationError):
            evenement.full_clean()

    def test_solveur_actuel_rattache_les_affectations_a_une_evenement(self):
        PreferenceCentre.objects.create(
            animateur=self.animateur,
            centre=self.centre_a,
            est_prefere=True,
        )
        data, status = generer_planning_auto({
            "debut": "2026-07-06",
            "centres": {
                str(self.centre_a.id): {"effectif": 1, "qualifs": {}},
                str(self.centre_b.id): {"effectif": 0, "qualifs": {}},
            },
        })

        self.assertEqual(status, 200, data)
        self.assertTrue(Affectation.objects.exists())
        self.assertFalse(Affectation.objects.filter(evenement__isnull=True).exists())
        self.assertTrue(
            all(
                affectation.evenement.centre_id == affectation.centre_id
                for affectation in Affectation.objects.select_related("evenement")
            )
        )


class EvenementMigrationTests(TransactionTestCase):
    """Vérifie la migration avec des données créées avant l'arrivée d'Evenement."""

    reset_sequences = True
    migrate_from = [("animateurs", "0015_centre_prefere_secondaires_et_qualif_default")]
    migrate_to = [("animateurs", "0016_evenements_par_centre_etape1")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        CentreAncien = old_apps.get_model("animateurs", "Centre")
        AnimateurAncien = old_apps.get_model("animateurs", "Animateur")
        AffectationAncienne = old_apps.get_model("animateurs", "Affectation")

        centre = CentreAncien.objects.create(
            nom="Centre historique",
            code="HIST",
            couleur="#ABCDEF",
            effectif_cible=4,
        )
        animateur = AnimateurAncien.objects.create(prenom="Ancien", nom="Animateur")
        debut = timezone.make_aware(datetime.datetime(2026, 7, 6))
        affectation = AffectationAncienne.objects.create(
            animateur_id=animateur.id,
            centre_id=centre.id,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )
        self.centre_id = centre.id
        self.affectation_id = affectation.id

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def test_migration_preserve_et_rattache_les_donnees(self):
        EvenementHistorique = self.apps.get_model("animateurs", "Evenement")
        AffectationHistorique = self.apps.get_model("animateurs", "Affectation")

        evenement = EvenementHistorique.objects.get(centre_id=self.centre_id)
        affectation = AffectationHistorique.objects.get(pk=self.affectation_id)

        self.assertEqual(evenement.nom, EQUIPE_PRINCIPALE_NOM)
        self.assertEqual(evenement.effectif_cible, 4)
        self.assertEqual(affectation.evenement_id, evenement.id)
        self.assertEqual(affectation.centre_id, self.centre_id)
