from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0024_envoiemail_documents_titres"),
    ]

    operations = [
        migrations.CreateModel(
            name="PeriodeScolaire",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=140)),
                ("annee_scolaire", models.CharField(help_text="Ex. 2026-2027", max_length=9)),
                ("zone", models.CharField(choices=[("A", "Zone A"), ("B", "Zone B"), ("C", "Zone C")], max_length=1)),
                ("debut", models.DateField()),
                ("fin", models.DateField()),
                ("description_source", models.CharField(blank=True, default="", max_length=180)),
                ("ordre", models.PositiveSmallIntegerField(default=0)),
                ("date_import", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-annee_scolaire", "zone", "debut", "ordre", "nom"],
            },
        ),
        migrations.AddConstraint(
            model_name="periodescolaire",
            constraint=models.UniqueConstraint(
                fields=("annee_scolaire", "zone", "debut", "fin"),
                name="unique_periode_scolaire_zone_dates",
            ),
        ),
        migrations.AddConstraint(
            model_name="periodescolaire",
            constraint=models.CheckConstraint(
                condition=models.Q(fin__gte=models.F("debut")),
                name="periode_scolaire_fin_apres_debut",
            ),
        ),
    ]
