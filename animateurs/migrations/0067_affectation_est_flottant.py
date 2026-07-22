from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0066_supprimer_couleur_personnelle_animateur")]

    operations = [
        migrations.AddField(
            model_name="affectation",
            name="est_flottant",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Ancien indicateur temporaire des animateurs flottants.",
            ),
        ),
    ]
