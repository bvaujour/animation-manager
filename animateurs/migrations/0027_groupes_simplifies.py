from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0026_groupes_accueil_periodes")]

    operations = [
        migrations.RemoveField(
            model_name="evenement",
            name="active",
        ),
        migrations.RemoveField(
            model_name="evenement",
            name="ferme_weekends",
        ),
        migrations.AlterField(
            model_name="evenement",
            name="debut",
            field=models.DateField(blank=True, help_text="Premier jour du groupe", null=True),
        ),
        migrations.AlterField(
            model_name="evenement",
            name="fin",
            field=models.DateField(blank=True, help_text="Dernier jour du groupe inclus", null=True),
        ),
        migrations.AlterField(
            model_name="evenement",
            name="periodes_scolaires",
            field=models.ManyToManyField(
                blank=True,
                related_name="groupes",
                to="animateurs.periodescolaire",
                verbose_name="périodes",
            ),
        ),
        migrations.AlterModelOptions(
            name="evenement",
            options={
                "ordering": ["centre__nom", "ordre", "nom"],
                "verbose_name": "groupe",
                "verbose_name_plural": "groupes",
            },
        ),
        migrations.AlterField(
            model_name="animateur",
            name="evenement_preferee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="animateurs_preferant",
                to="animateurs.evenement",
                verbose_name="groupe préféré",
            ),
        ),
        migrations.AlterField(
            model_name="dateexclueevenement",
            name="evenement",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                related_name="dates_exclues",
                to="animateurs.evenement",
                verbose_name="groupe",
            ),
        ),
        migrations.AlterField(
            model_name="besoinqualification",
            name="evenement",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                related_name="besoins_qualifications",
                to="animateurs.evenement",
                verbose_name="groupe",
            ),
        ),
        migrations.AlterField(
            model_name="affectation",
            name="evenement",
            field=models.ForeignKey(
                on_delete=models.deletion.PROTECT,
                related_name="affectations",
                to="animateurs.evenement",
                verbose_name="groupe",
            ),
        ),
    ]
