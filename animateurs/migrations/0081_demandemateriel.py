from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0080_publication_planning_document"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DemandeMateriel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("materiel", models.CharField(max_length=180)),
                ("quantite", models.PositiveIntegerField(default=1)),
                ("date_besoin", models.DateField(verbose_name="date souhaitée")),
                ("statut", models.CharField(choices=[("en_attente", "En attente"), ("validee", "Validée")], db_index=True, default="en_attente", max_length=20)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_validation", models.DateTimeField(blank=True, null=True)),
                ("animateur", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="demandes_materiel", to="animateurs.animateur")),
                ("validee_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="demandes_materiel_validees", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "demande de matériel",
                "verbose_name_plural": "demandes de matériel",
                "ordering": ("statut", "date_besoin", "-date_creation"),
            },
        ),
    ]
