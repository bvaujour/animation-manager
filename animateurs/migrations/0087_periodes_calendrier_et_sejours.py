import django.db.models.deletion
from django.db import migrations, models


def creer_references_vacances(apps, schema_editor):
    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    PeriodeScolaire = apps.get_model("animateurs", "PeriodeScolaire")
    PeriodeCalendrier = apps.get_model("animateurs", "PeriodeCalendrier")
    vacances = TypeAccueil.objects.get(code="vacances")
    PeriodeScolaire.objects.exclude(type_accueil=vacances).update(type_accueil=vacances)
    groupes = {}
    for semaine in PeriodeScolaire.objects.order_by("debut", "pk"):
        nom = semaine.nom.split("—", 1)[0].strip() or semaine.nom
        groupes.setdefault((semaine.annee_scolaire, semaine.zone, nom, semaine.debut.year), []).append(semaine)
    for (annee, zone, nom, _), semaines in groupes.items():
        reference, _ = PeriodeCalendrier.objects.get_or_create(
            categorie="vacances", annee_scolaire=annee, zone=zone,
            debut=min(item.debut for item in semaines), fin=max(item.fin for item in semaines),
            defaults={"nom": nom},
        )
        reference.types_accueil.add(vacances)
        for semaine in semaines:
            semaine.periode_calendrier = reference
            semaine.save(update_fields=("periode_calendrier",))
            semaine.types_accueil.add(vacances)


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0086_periodes_type_accueil_obligatoire")]
    operations = [
        migrations.CreateModel(
            name="PeriodeCalendrier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("categorie", models.CharField(choices=(("vacances", "Vacances scolaires"), ("scolaire", "Période scolaire")), max_length=12)),
                ("nom", models.CharField(max_length=140)),
                ("annee_scolaire", models.CharField(max_length=9)),
                ("zone", models.CharField(choices=(("A", "Zone A"), ("B", "Zone B"), ("C", "Zone C")), max_length=1)),
                ("debut", models.DateField()), ("fin", models.DateField()),
                ("types_accueil", models.ManyToManyField(blank=True, related_name="periodes_calendrier", to="animateurs.typeaccueil")),
            ],
            options={"ordering": ("-annee_scolaire", "zone", "debut", "nom")},
        ),
        migrations.AddConstraint(model_name="periodecalendrier", constraint=models.UniqueConstraint(fields=("categorie", "annee_scolaire", "zone", "debut", "fin"), name="unique_periode_calendrier_zone_dates")),
        migrations.AddConstraint(model_name="periodecalendrier", constraint=models.CheckConstraint(condition=models.Q(fin__gte=models.F("debut")), name="periode_calendrier_fin_apres_debut")),
        migrations.AddField(model_name="periodescolaire", name="periode_calendrier", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="semaines", to="animateurs.periodecalendrier")),
        migrations.AddField(model_name="periodescolaire", name="types_accueil", field=models.ManyToManyField(blank=True, help_text="Types utilisant cette même semaine de référence.", related_name="semaines_reference", to="animateurs.typeaccueil")),
        migrations.AddField(model_name="sejour", name="periode_vacances", field=models.ForeignKey(blank=True, limit_choices_to={"categorie": "vacances"}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sejours", to="animateurs.periodecalendrier")),
        migrations.AddField(model_name="sejour", name="equipe", field=models.ManyToManyField(blank=True, related_name="sejours", to="animateurs.animateur")),
        migrations.RunPython(creer_references_vacances, migrations.RunPython.noop),
    ]
