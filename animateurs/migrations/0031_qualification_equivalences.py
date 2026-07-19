from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0030_groupes_permanents_toutes_periodes"),
    ]

    operations = [
        migrations.AddField(
            model_name="qualification",
            name="equivalences",
            field=models.ManyToManyField(
                blank=True,
                help_text="Qualifications considérées comme équivalentes dans le remplissage automatique.",
                        to="animateurs.qualification",
            ),
        ),
    ]
