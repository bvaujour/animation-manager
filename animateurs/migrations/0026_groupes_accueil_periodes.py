from django.db import migrations, models


def associer_periodes_existantes(apps, schema_editor):
    Evenement = apps.get_model("animateurs", "Evenement")
    PeriodeScolaire = apps.get_model("animateurs", "PeriodeScolaire")
    for groupe in Evenement.objects.all():
        qs = PeriodeScolaire.objects.all()
        if groupe.debut and groupe.fin:
            qs = qs.filter(debut__lte=groupe.fin, fin__gte=groupe.debut)
        periodes = list(qs)
        if not periodes:
            periodes = list(PeriodeScolaire.objects.all())
        if periodes:
            groupe.periodes_scolaires.set(periodes)
        jours = set(groupe.jours_ouverts or [])
        groupe.ferme_weekends = not (5 in jours or 6 in jours)
        groupe.save(update_fields=["ferme_weekends"])


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0025_periodes_scolaires_independantes")]

    operations = [
        migrations.AlterField(
            model_name="evenement",
            name="debut",
            field=models.DateField(blank=True, help_text="Premier jour du groupe d’accueil", null=True),
        ),
        migrations.AlterField(
            model_name="evenement",
            name="fin",
            field=models.DateField(blank=True, help_text="Dernier jour du groupe d’accueil inclus", null=True),
        ),
        migrations.AddField(
            model_name="evenement",
            name="ferme_jours_feries",
            field=models.BooleanField(default=True, verbose_name="fermé les jours fériés"),
        ),
        migrations.AddField(
            model_name="evenement",
            name="ferme_weekends",
            field=models.BooleanField(default=True, help_text="Si décoché, le samedi et le dimanche qui suivent chaque semaine sélectionnée sont ouverts.", verbose_name="fermé les week-ends"),
        ),
        migrations.AddField(
            model_name="evenement",
            name="periodes_scolaires",
            field=models.ManyToManyField(blank=True, related_name="groupes_accueil", to="animateurs.periodescolaire", verbose_name="périodes d’ouverture"),
        ),
        migrations.RunPython(associer_periodes_existantes, migrations.RunPython.noop),
    ]
