from datetime import date
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from animateurs.models import AnneeScolaire, PeriodeCalendrier, PeriodeScolaire


class AnneeScolaireTests(TestCase):
    def creer(self, **kwargs):
        valeurs = dict(libelle="2026-2027", date_debut=date(2026, 9, 1), date_fin=date(2027, 8, 31))
        return AnneeScolaire.objects.create(**(valeurs | kwargs))

    def test_creation_et_ordre(self):
        annee = self.creer()
        annee.full_clean()
        self.assertEqual(str(annee), "2026-2027")
        self.assertEqual(annee.statut, "PREPARATION")
        self.assertEqual(AnneeScolaire.objects.first(), annee)

    def test_libelle_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.creer(libelle="2025-2026")

    def test_une_seule_active_en_base_et_validation(self):
        annee = self.creer(statut="ACTIVE") if not AnneeScolaire.objects.filter(statut="ACTIVE").exists() else self.creer()
        annee.statut = "ACTIVE"
        with self.assertRaises(ValidationError):
            annee.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            annee.save()

    def test_dates_invalides(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.creer(date_fin=date(2026, 8, 31))

    def test_migration_initiale_et_idempotence(self):
        annee = AnneeScolaire.objects.get(libelle="2025-2026")
        self.assertEqual(annee.statut, "ACTIVE")
        self.assertEqual((annee.date_debut, annee.date_fin), (date(2025, 9, 1), date(2026, 8, 31)))
        migration = import_module("animateurs.migrations.0114_initialiser_annee_scolaire")
        annee.statut = "CLOTUREE"
        annee.save()
        migration.initialiser_annee(apps, SimpleNamespace(connection=connection))
        annee.refresh_from_db()
        self.assertEqual(annee.statut, "CLOTUREE")
        self.assertEqual(AnneeScolaire.objects.filter(libelle="2025-2026").count(), 1)

    def test_migration_preserve_autre_active(self):
        AnneeScolaire.objects.all().delete()
        self.creer(statut="ACTIVE")
        migration = import_module("animateurs.migrations.0114_initialiser_annee_scolaire")
        migration.initialiser_annee(apps, SimpleNamespace(connection=connection))
        self.assertEqual(AnneeScolaire.objects.get(libelle="2025-2026").statut, "PREPARATION")

    def test_coexistence_annees_texte(self):
        periode = PeriodeScolaire.objects.create(nom="Toussaint", annee_scolaire="2025-2026", zone="A", debut=date(2025, 10, 20), fin=date(2025, 10, 24))
        self.creer()
        periode.refresh_from_db()
        self.assertEqual(periode.annee_scolaire, "2025-2026")
        for model in (PeriodeScolaire, PeriodeCalendrier):
            self.assertEqual(model._meta.get_field("annee_scolaire").get_internal_type(), "CharField")

    def test_admin_liste_creation_modification(self):
        self.client.force_login(get_user_model().objects.create_superuser(username="admin-annees", password="test"))
        liste = reverse("admin:animateurs_anneescolaire_changelist")
        self.assertContains(self.client.get(liste), "2025-2026")
        donnees = dict(libelle="2026-2027", date_debut="2026-09-01", date_fin="2027-08-31", statut="PREPARATION", _save="Enregistrer")
        self.assertEqual(self.client.post(reverse("admin:animateurs_anneescolaire_add"), donnees).status_code, 302)
        annee = AnneeScolaire.objects.get(libelle="2026-2027")
        url = reverse("admin:animateurs_anneescolaire_change", args=[annee.pk])
        self.assertContains(self.client.post(url, donnees | {"statut": "ACTIVE"}), "Une année scolaire est déjà active.")
        self.assertEqual(self.client.post(url, donnees | {"date_fin": "2027-08-30"}).status_code, 302)
        annee.refresh_from_db()
        self.assertEqual(annee.date_fin, date(2027, 8, 30))
