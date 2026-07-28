from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0077_localisation_structuree_centres")]

    operations = [
        migrations.CreateModel(
            name="ActiviteTravailComplementaire",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(choices=[("reunion", "Réunion"), ("preparation", "Télétravail / préparation")], max_length=20)),
                ("intitule", models.CharField(max_length=160)),
                ("date", models.DateField(blank=True, null=True)),
                ("remarque", models.TextField(blank=True, default="")),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                ("periodes", models.ManyToManyField(related_name="activites_travail_complementaires", to="animateurs.periodescolaire")),
            ],
            options={
                "verbose_name": "activité de travail complémentaire",
                "verbose_name_plural": "activités de travail complémentaires",
                "ordering": ("date", "intitule", "id"),
                "indexes": [models.Index(fields=["type", "date"], name="activite_travail_type_date_idx")],
            },
        ),
        migrations.CreateModel(
            name="ParticipationTravailComplementaire",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre_jours", models.DecimalField(decimal_places=2, default=Decimal("1.00"), max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal("0.00"))])),
                ("remarque", models.CharField(blank=True, default="", max_length=240)),
                ("autoriser_double_comptage", models.BooleanField(default=False)),
                ("activite", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participations", to="animateurs.activitetravailcomplementaire")),
                ("animateur", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participations_travail_complementaire", to="animateurs.animateur")),
            ],
            options={
                "verbose_name": "participation de travail complémentaire",
                "verbose_name_plural": "participations de travail complémentaire",
                "ordering": ("animateur__prenom", "animateur__nom"),
                "constraints": [
                    models.UniqueConstraint(fields=("activite", "animateur"), name="unique_participation_activite_animateur"),
                    models.CheckConstraint(condition=models.Q(("nombre_jours__gte", 0)), name="participation_nombre_jours_positif"),
                ],
            },
        ),
    ]
