from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0028_animateur_adresse_animateur_numero_securite_sociale_and_more")]

    operations = [
        migrations.AddField(
            model_name="evenement",
            name="permanent",
            field=models.BooleanField(
                default=False,
                help_text="Un groupe permanent est ouvert à toutes les périodes selon ses jours habituels.",
                verbose_name="groupe permanent",
            ),
        ),
    ]
