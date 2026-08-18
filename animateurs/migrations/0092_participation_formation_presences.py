from django.db import migrations, models
import django.db.models.deletion


def copier_participants(apps, schema_editor):
    Formation = apps.get_model("animateurs", "Formation")
    ParticipationFormation = apps.get_model("animateurs", "ParticipationFormation")
    lignes = []
    for formation in Formation.objects.prefetch_related("animateurs"):
        lignes.extend(
            ParticipationFormation(
                formation_id=formation.id,
                animateur_id=animateur.id,
                presence="a_confirmer",
            )
            for animateur in formation.animateurs.all()
        )
    ParticipationFormation.objects.bulk_create(lignes, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0091_formation_coordonnees_hebergement_documents")]

    operations = [
        migrations.CreateModel(
            name="ParticipationFormation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("presence", models.CharField(choices=[("a_confirmer", "À confirmer"), ("present", "Présent"), ("absent", "Absent")], default="a_confirmer", max_length=16)),
                ("animateur", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participations_formations", to="animateurs.animateur")),
                ("formation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participations", to="animateurs.formation")),
            ],
            options={"ordering": ("animateur__nom", "animateur__prenom", "id")},
        ),
        migrations.AddConstraint(
            model_name="participationformation",
            constraint=models.UniqueConstraint(fields=("formation", "animateur"), name="unique_participation_formation_animateur"),
        ),
        migrations.RunPython(copier_participants, migrations.RunPython.noop),
        migrations.RemoveField(model_name="formation", name="animateurs"),
        migrations.AddField(
            model_name="formation",
            name="animateurs",
            field=models.ManyToManyField(related_name="formations", through="animateurs.ParticipationFormation", to="animateurs.animateur", verbose_name="animateurs concernés"),
        ),
        migrations.AlterField(
            model_name="formation",
            name="statut",
            field=models.CharField(choices=[("prevue", "Prévue"), ("en_cours", "En cours"), ("a_cloturer", "À clôturer"), ("terminee", "Terminée"), ("annulee", "Annulée")], default="prevue", max_length=20),
        ),
    ]
