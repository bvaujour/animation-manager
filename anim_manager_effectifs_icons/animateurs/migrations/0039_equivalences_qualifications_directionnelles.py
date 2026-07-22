from django.db import migrations, models
import django.db.models.deletion


def migrer_equivalences_existantes(apps, schema_editor):
    Qualification = apps.get_model("animateurs", "Qualification")
    EquivalenceQualification = apps.get_model("animateurs", "EquivalenceQualification")

    paires = set()
    for qualification in Qualification.objects.all():
        for equivalente_id in qualification.equivalences.values_list("id", flat=True):
            if qualification.id == equivalente_id:
                continue
            qualification_a_id, qualification_b_id = sorted((qualification.id, equivalente_id))
            paires.add((qualification_a_id, qualification_b_id))

    EquivalenceQualification.objects.bulk_create([
        EquivalenceQualification(
            qualification_a_id=qualification_a_id,
            qualification_b_id=qualification_b_id,
            sens="double",
        )
        for qualification_a_id, qualification_b_id in sorted(paires)
    ])


def restaurer_equivalences_symetriques(apps, schema_editor):
    Qualification = apps.get_model("animateurs", "Qualification")
    EquivalenceQualification = apps.get_model("animateurs", "EquivalenceQualification")

    for relation in EquivalenceQualification.objects.all():
        # L'ancien modèle ne savait représenter que le double sens.
        if relation.sens == "double":
            qualification = Qualification.objects.get(pk=relation.qualification_a_id)
            qualification.equivalences.add(relation.qualification_b_id)


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0038_journalaudit"),
    ]

    operations = [
        migrations.CreateModel(
            name="EquivalenceQualification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sens", models.CharField(choices=[("a_vers_b", "A vers B"), ("b_vers_a", "B vers A"), ("double", "Double sens")], default="double", max_length=16)),
                ("qualification_a", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="relations_equivalence_a", to="animateurs.qualification")),
                ("qualification_b", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="relations_equivalence_b", to="animateurs.qualification")),
            ],
            options={
                "ordering": ("qualification_a__nom", "qualification_b__nom"),
            },
        ),
        migrations.AddConstraint(
            model_name="equivalencequalification",
            constraint=models.UniqueConstraint(fields=("qualification_a", "qualification_b"), name="unique_paire_equivalence_qualification"),
        ),
        migrations.AddConstraint(
            model_name="equivalencequalification",
            constraint=models.CheckConstraint(condition=~models.Q(("qualification_a", models.F("qualification_b"))), name="equivalence_qualifications_distinctes"),
        ),
        migrations.RunPython(migrer_equivalences_existantes, restaurer_equivalences_symetriques),
        migrations.RemoveField(
            model_name="qualification",
            name="equivalences",
        ),
    ]
