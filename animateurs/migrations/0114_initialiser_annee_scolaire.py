from datetime import date

from django.db import migrations


def initialiser_annee(apps, schema_editor):
    annees = apps.get_model("animateurs", "AnneeScolaire").objects.using(schema_editor.connection.alias)
    annees.get_or_create(
        libelle="2025-2026",
        defaults={
            "date_debut": date(2025, 9, 1),
            "date_fin": date(2026, 8, 31),
            "statut": "PREPARATION" if annees.filter(statut="ACTIVE").exists() else "ACTIVE",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0113_annee_scolaire")]
    operations = [migrations.RunPython(initialiser_annee, migrations.RunPython.noop)]
