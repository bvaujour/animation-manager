from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0013_indexes_and_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="qualification",
            name="selectionnable_remplissage_auto",
            field=models.BooleanField(
                default=True,
                help_text="Affiche cette qualification parmi les exigences du remplissage automatique.",
            ),
        ),
    ]
