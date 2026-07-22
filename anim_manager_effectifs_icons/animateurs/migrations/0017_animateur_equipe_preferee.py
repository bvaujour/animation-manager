from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0016_equipes_par_centre_etape1"),
    ]

    operations = [
        migrations.AddField(
            model_name="animateur",
            name="equipe_preferee",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Équipe à privilégier lors du remplissage automatique. "
                    "Elle doit appartenir au centre préféré de l’animateur."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="animateurs_preferant",
                to="animateurs.equipe",
            ),
        ),
    ]
