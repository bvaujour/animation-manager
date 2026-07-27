from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def initialiser_circuits(apps, schema_editor):
    Sortie = apps.get_model("animateurs", "Sortie")
    SortieEtapeTransport = apps.get_model("animateurs", "SortieEtapeTransport")
    SortieParticipation = apps.get_model("animateurs", "SortieParticipation")

    etapes = []
    for sortie in Sortie.objects.all().iterator():
        centres = list(
            SortieParticipation.objects.filter(sortie_id=sortie.id)
            .order_by("evenement__centre__ordre", "evenement__centre__nom", "evenement__centre_id")
            .values_list("evenement__centre_id", flat=True)
            .distinct()
        )
        for ordre, centre_id in enumerate(centres):
            etapes.append(SortieEtapeTransport(sortie_id=sortie.id, centre_id=centre_id, sens="aller", ordre=ordre))
        for ordre, centre_id in enumerate(reversed(centres)):
            etapes.append(SortieEtapeTransport(sortie_id=sortie.id, centre_id=centre_id, sens="retour", ordre=ordre))
    SortieEtapeTransport.objects.bulk_create(etapes)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("animateurs", "0073_sortierenfort"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sortie",
            name="mode_transport",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Car", "Car"),
                    ("Minibus", "Minibus"),
                    ("Ligne régulière", "Ligne régulière"),
                    ("Transport en commun", "Transport en commun"),
                ],
                default="",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="sortie",
            name="heure_arrivee_retour",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="PreferenceTransportUtilisateur",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode_transport", models.CharField(choices=[("Car", "Car"), ("Minibus", "Minibus"), ("Ligne régulière", "Ligne régulière"), ("Transport en commun", "Transport en commun")], max_length=100)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("utilisateur", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="preference_transport", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="SortieEtapeTransport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sens", models.CharField(choices=[("aller", "Aller"), ("retour", "Retour")], max_length=6)),
                ("ordre", models.PositiveSmallIntegerField()),
                ("centre", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="etapes_transport_sorties", to="animateurs.centre")),
                ("sortie", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="etapes_transport", to="animateurs.sortie")),
            ],
            options={"ordering": ("sens", "ordre", "id")},
        ),
        migrations.AddConstraint(
            model_name="sortieetapetransport",
            constraint=models.UniqueConstraint(fields=("sortie", "sens", "centre"), name="unique_centre_par_circuit_sortie"),
        ),
        migrations.AddConstraint(
            model_name="sortieetapetransport",
            constraint=models.UniqueConstraint(fields=("sortie", "sens", "ordre"), name="unique_ordre_par_circuit_sortie"),
        ),
        migrations.RunPython(initialiser_circuits, migrations.RunPython.noop),
    ]
