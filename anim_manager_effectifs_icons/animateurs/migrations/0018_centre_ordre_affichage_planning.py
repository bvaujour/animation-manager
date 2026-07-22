from django.db import migrations, models


def initialiser_ordre_centres(apps, schema_editor):
    """Conserve l'ordre alphabétique historique lors de la migration."""

    Centre = apps.get_model("animateurs", "Centre")
    for ordre, centre in enumerate(Centre.objects.order_by("nom", "id")):
        Centre.objects.filter(pk=centre.pk).update(ordre=ordre)


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0017_animateur_equipe_preferee"),
    ]

    operations = [
        migrations.AddField(
            model_name="centre",
            name="ordre",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Ordre d'affichage des centres sur la page planning.",
            ),
        ),
        migrations.RunPython(initialiser_ordre_centres, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="centre",
            options={"ordering": ["ordre", "nom"]},
        ),
    ]
