from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("animateurs", "0088_modalites_periscolaires_et_structure_sejours"),
    ]

    operations = [
        migrations.CreateModel(
            name="StatutPreparationSemaine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("debut_semaine", models.DateField(unique=True)),
                ("est_force_prete", models.BooleanField(default=False)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                (
                    "modifie_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="statuts_preparation_semaines_modifies",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-debut_semaine",)},
        ),
    ]
