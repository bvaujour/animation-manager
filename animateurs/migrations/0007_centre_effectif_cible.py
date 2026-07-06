# Generated manually for animateurs app on 2026-07-06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('animateurs', '0006_disponibilite'),
    ]

    operations = [
        migrations.AddField(
            model_name='centre',
            name='effectif_cible',
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text="Nombre d'animateurs souhaités par jour dans ce centre (utilisé par le placement automatique)",
            ),
        ),
    ]
