from django.db import migrations, models
import django.db.models.deletion
import animateurs.models


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0021_remove_evenement_heure_debut_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="evenement",
            name="jours_ouverts",
            field=models.JSONField(
                default=animateurs.models.jours_ouverts_par_defaut,
                help_text="Jours habituels d’ouverture, de 0=lundi à 6=dimanche.",
            ),
        ),
        migrations.CreateModel(
            name="DateExclueEvenement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("motif", models.CharField(blank=True, default="", max_length=120)),
                ("evenement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="dates_exclues", to="animateurs.evenement")),
            ],
            options={
                "ordering": ["date"],
                "constraints": [
                    models.UniqueConstraint(fields=("evenement", "date"), name="unique_date_exclue_evenement"),
                ],
            },
        ),
    ]
