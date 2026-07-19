from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0049_effectifenfantsjour")]

    operations = [
        migrations.AddField(
            model_name="effectifenfantsjour",
            name="enfants_par_animateur",
            field=models.PositiveSmallIntegerField(
                default=8,
                verbose_name="nombre d’enfants par animateur",
            ),
        ),
    ]
