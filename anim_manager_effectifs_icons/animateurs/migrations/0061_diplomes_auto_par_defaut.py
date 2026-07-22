from django.db import migrations, models


def activer_diplomes_existants(apps, schema_editor):
    Qualification = apps.get_model("animateurs", "Qualification")
    Qualification.objects.filter(est_statut=False).update(selectionnable_remplissage_auto=True)


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0060_statuts_diplomes_sans_equivalences"),
    ]

    operations = [
        migrations.AlterField(
            model_name="qualification",
            name="selectionnable_remplissage_auto",
            field=models.BooleanField(
                default=True,
                help_text="Propose ce diplôme ou statut dans les besoins du remplissage automatique.",
            ),
        ),
        migrations.RunPython(activer_diplomes_existants, migrations.RunPython.noop),
    ]
