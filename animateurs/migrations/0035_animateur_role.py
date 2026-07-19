from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0034_alter_evenement_cle_unique")]

    operations = [
        migrations.AddField(
            model_name="animateur",
            name="role",
            field=models.CharField(
                choices=[
                    ("animateur", "Animateur"),
                    ("direction", "Direction"),
                    ("administrateur", "Administrateur"),
                ],
                default="animateur",
                max_length=20,
                verbose_name="rôle dans l’application",
            ),
        ),
    ]
