from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0075_geographie_et_estimation_transport")]

    operations = [
        migrations.AddField(
            model_name="sortie",
            name="destination_code_insee",
            field=models.CharField(blank=True, default="", max_length=5),
        ),
        migrations.AddField(
            model_name="sortie",
            name="destination_precision",
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
