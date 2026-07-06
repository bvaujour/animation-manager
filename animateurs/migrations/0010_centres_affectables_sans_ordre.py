# Generated manually on 2026-07-06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0009_alter_centre_effectif_cible"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="preferencecentre",
            name="unique_animateur_ordre",
        ),
        migrations.RemoveField(
            model_name="preferencecentre",
            name="ordre",
        ),
        migrations.AlterModelOptions(
            name="preferencecentre",
            options={"ordering": ["centre__nom"]},
        ),
    ]
