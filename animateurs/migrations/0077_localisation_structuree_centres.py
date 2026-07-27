from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0076_localisation_structuree_destination")]

    operations = [
        migrations.AddField(
            model_name="centre",
            name="code_insee",
            field=models.CharField(blank=True, default="", max_length=5),
        ),
        migrations.AddField(
            model_name="centre",
            name="precision_localisation",
            field=models.CharField(
                choices=[
                    ("adresse", "Adresse"),
                    ("commune", "Commune"),
                    ("code_postal", "Code postal"),
                    ("non_localisee", "Non localisée"),
                ],
                default="non_localisee",
                max_length=14,
            ),
        ),
    ]
