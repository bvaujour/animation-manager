from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0035_animateur_role")]

    operations = [
        migrations.AddField(
            model_name="animateur",
            name="doit_changer_mot_de_passe",
            field=models.BooleanField(default=False, verbose_name="doit changer son mot de passe"),
        ),
    ]
