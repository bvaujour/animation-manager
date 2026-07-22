from django.db import migrations, models
import django.db.models.deletion


EQUIPE_PRINCIPALE_NOM = "Équipe principale"


def creer_equipes_principales_et_rattacher_affectations(apps, schema_editor):
    Centre = apps.get_model("animateurs", "Centre")
    Equipe = apps.get_model("animateurs", "Equipe")
    Affectation = apps.get_model("animateurs", "Affectation")

    for centre in Centre.objects.all().iterator():
        equipe, _ = Equipe.objects.get_or_create(
            centre_id=centre.id,
            nom=EQUIPE_PRINCIPALE_NOM,
            defaults={
                "effectif_cible": max(1, centre.effectif_cible),
                "ordre": 0,
                "active": True,
            },
        )
        Affectation.objects.filter(
            centre_id=centre.id,
            equipe__isnull=True,
        ).update(equipe_id=equipe.id)


def retour_sans_suppression(apps, schema_editor):
    """La colonne `equipe` sera supprimée automatiquement au rollback.

    Les équipes créées n'ont donc pas besoin d'être supprimées ici : le modèle
    Equipe lui-même disparaît lors du retour à la migration précédente.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0015_centre_prefere_secondaires_et_qualif_default"),
    ]

    operations = [
        migrations.CreateModel(
            name="Equipe",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nom", models.CharField(max_length=100)),
                ("effectif_cible", models.PositiveSmallIntegerField(default=1)),
                ("ordre", models.PositiveSmallIntegerField(default=0)),
                ("active", models.BooleanField(default=True)),
                ("heure_debut", models.TimeField(blank=True, null=True)),
                ("heure_fin", models.TimeField(blank=True, null=True)),
                (
                    "centre",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="equipes",
                        to="animateurs.centre",
                    ),
                ),
            ],
            options={
                "ordering": ["centre__nom", "ordre", "nom"],
            },
        ),
        migrations.AddConstraint(
            model_name="equipe",
            constraint=models.UniqueConstraint(
                fields=("centre", "nom"),
                name="unique_nom_equipe_par_centre",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipe",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(heure_debut__isnull=True, heure_fin__isnull=True)
                    | models.Q(
                        heure_debut__isnull=False,
                        heure_fin__isnull=False,
                        heure_fin__gt=models.F("heure_debut"),
                    )
                ),
                name="equipe_horaires_coherents",
            ),
        ),
        migrations.AddField(
            model_name="affectation",
            name="equipe",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="affectations",
                to="animateurs.equipe",
            ),
        ),
        migrations.RunPython(
            creer_equipes_principales_et_rattacher_affectations,
            retour_sans_suppression,
        ),
        migrations.AlterField(
            model_name="affectation",
            name="equipe",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="affectations",
                to="animateurs.equipe",
            ),
        ),
        migrations.AddIndex(
            model_name="affectation",
            index=models.Index(
                fields=["equipe", "debut"],
                name="aff_equipe_debut_idx",
            ),
        ),
    ]
