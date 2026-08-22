import django.db.models.deletion
from django.db import migrations, models


def completer_types_structures(apps, schema_editor):
    """Complète seulement les rattachements absents, sans écraser les choix existants."""

    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    Centre = apps.get_model("animateurs", "Centre")
    Groupe = apps.get_model("animateurs", "Groupe")
    Evenement = apps.get_model("animateurs", "Evenement")

    vacances = TypeAccueil.objects.filter(code="vacances").first()
    if vacances is None:
        return

    for centre in Centre.objects.all().iterator():
        if not centre.types_accueil.exists():
            centre.types_accueil.add(vacances)

    for evenement in Evenement.objects.select_related("groupe", "centre").iterator():
        if not evenement.types_accueil.exists():
            evenement.types_accueil.add(vacances)
        # Le groupe partagé hérite des usages déjà connus de ses instances.
        for type_accueil in evenement.types_accueil.all():
            evenement.groupe.types_accueil.add(type_accueil)

    for groupe in Groupe.objects.all().iterator():
        if not groupe.types_accueil.exists():
            groupe.types_accueil.add(vacances)


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0102_activitetravailcomplementaire_heure_debut_and_more")]

    operations = [
        migrations.RemoveConstraint(
            model_name="effectifenfantsjour",
            name="unique_effectif_enfants_groupe_date",
        ),
        migrations.AddConstraint(
            model_name="effectifenfantsjour",
            constraint=models.UniqueConstraint(
                condition=models.Q(modalite_periscolaire__isnull=True),
                fields=("evenement", "date"),
                name="unique_effectif_enfants_groupe_date_sans_modalite",
            ),
        ),
        migrations.AddConstraint(
            model_name="effectifenfantsjour",
            constraint=models.UniqueConstraint(
                condition=models.Q(modalite_periscolaire__isnull=False),
                fields=("evenement", "date", "modalite_periscolaire"),
                name="unique_effectif_enfants_groupe_date_modalite",
            ),
        ),
        migrations.CreateModel(
            name="OuvertureCentrePeriode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("jour_semaine", models.PositiveSmallIntegerField(choices=((0, "Lundi"), (1, "Mardi"), (2, "Mercredi"), (3, "Jeudi"), (4, "Vendredi"), (5, "Samedi"), (6, "Dimanche")))),
                ("heure_debut", models.TimeField(blank=True, null=True)),
                ("heure_fin", models.TimeField(blank=True, null=True)),
                ("actif", models.BooleanField(default=True)),
                ("centre", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ouvertures_periodes", to="animateurs.centre")),
                ("modalite_periscolaire", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ouvertures_centres", to="animateurs.modaliteperiscolaire")),
                ("periode_calendrier", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ouvertures_centres", to="animateurs.periodecalendrier")),
            ],
            options={
                "ordering": ("periode_calendrier__debut", "centre__ordre", "modalite_periscolaire__ordre", "jour_semaine"),
            },
        ),
        migrations.AddConstraint(
            model_name="ouverturecentreperiode",
            constraint=models.UniqueConstraint(
                fields=("centre", "periode_calendrier", "modalite_periscolaire", "jour_semaine"),
                name="unique_ouverture_centre_periode_modalite_jour",
            ),
        ),
        migrations.AddConstraint(
            model_name="ouverturecentreperiode",
            constraint=models.CheckConstraint(
                condition=models.Q(jour_semaine__gte=0, jour_semaine__lte=6),
                name="ouverture_centre_jour_semaine_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="ouverturecentreperiode",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(heure_debut__isnull=True, heure_fin__isnull=True)
                    | models.Q(heure_debut__isnull=False, heure_fin__isnull=False, heure_fin__gt=models.F("heure_debut"))
                ),
                name="ouverture_centre_horaires_coherents",
            ),
        ),
        migrations.RunPython(completer_types_structures, migrations.RunPython.noop),
    ]
