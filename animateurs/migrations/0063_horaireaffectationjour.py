from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0062_besoins_uniquement_par_instance")]

    operations = [
        migrations.CreateModel(
            name="HoraireAffectationJour",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(db_index=True)),
                ("heure_arrivee", models.TimeField()),
                ("heure_depart", models.TimeField()),
                ("affectation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="horaires_journaliers", to="animateurs.affectation")),
            ],
            options={"ordering": ("date",)},
        ),
        migrations.AddConstraint(
            model_name="horaireaffectationjour",
            constraint=models.UniqueConstraint(fields=("affectation", "date"), name="horaire_unique_par_affectation_jour"),
        ),
        migrations.AddConstraint(
            model_name="horaireaffectationjour",
            constraint=models.CheckConstraint(
                condition=models.Q(heure_depart__gt=models.F("heure_arrivee")),
                name="horaire_affectation_depart_apres_arrivee",
            ),
        ),
    ]
