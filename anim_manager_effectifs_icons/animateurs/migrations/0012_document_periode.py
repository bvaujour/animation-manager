from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0011_animateur_couleur"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="permanent",
            field=models.BooleanField(
                default=True,
                help_text="Cocher si le document n'est lié à aucune période précise.",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="periode_debut",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="document",
            name="periode_fin",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterModelOptions(
            name="document",
            options={"ordering": ["-permanent", "-periode_debut", "-date_ajout"]},
        ),
    ]
