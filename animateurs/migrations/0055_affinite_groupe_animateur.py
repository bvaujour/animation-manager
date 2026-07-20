import datetime

from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def initialiser_affinites(apps, schema_editor):
    Affectation = apps.get_model("animateurs", "Affectation")
    Affinite = apps.get_model("animateurs", "AffiniteGroupeAnimateur")

    date_reference = timezone.localdate()
    jours_par_couple = {}
    for affectation in Affectation.objects.filter(debut__date__lt=date_reference).iterator():
        debut = timezone.localtime(affectation.debut).date()
        fin = min(timezone.localtime(affectation.fin).date(), date_reference)
        cle = (affectation.animateur_id, affectation.evenement_id)
        jours = jours_par_couple.setdefault(cle, set())
        jour = debut
        while jour < fin:
            jours.add(jour)
            jour += datetime.timedelta(days=1)

    Affinite.objects.bulk_create(
        [
            Affinite(
                animateur_id=animateur_id,
                evenement_id=evenement_id,
                jours_travailles=len(jours),
                dernier_jour_travaille=max(jours),
            )
            for (animateur_id, evenement_id), jours in jours_par_couple.items()
            if jours
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0054_alter_preferencecentre_est_prefere"),
    ]

    operations = [
        migrations.CreateModel(
            name="AffiniteGroupeAnimateur",
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
                (
                    "jours_travailles",
                    models.PositiveIntegerField(default=0, verbose_name="jours travaillés"),
                ),
                (
                    "dernier_jour_travaille",
                    models.DateField(blank=True, null=True, verbose_name="dernier jour travaillé"),
                ),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                (
                    "animateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="affinites_groupes",
                        to="animateurs.animateur",
                    ),
                ),
                (
                    "evenement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="affinites_animateurs",
                        to="animateurs.evenement",
                        verbose_name="groupe",
                    ),
                ),
            ],
            options={
                "verbose_name": "affinité animateur-groupe",
                "verbose_name_plural": "affinités animateurs-groupes",
                "ordering": (
                    "-jours_travailles",
                    "evenement__centre__nom",
                    "evenement__nom",
                ),
            },
        ),
        migrations.AddField(
            model_name="animateur",
            name="groupes_affinite",
            field=models.ManyToManyField(
                blank=True,
                related_name="animateurs_avec_affinite",
                through="animateurs.AffiniteGroupeAnimateur",
                to="animateurs.evenement",
                verbose_name="affinités avec les groupes",
            ),
        ),
        migrations.AddConstraint(
            model_name="affinitegroupeanimateur",
            constraint=models.UniqueConstraint(
                fields=("animateur", "evenement"),
                name="unique_affinite_animateur_groupe",
            ),
        ),
        migrations.AddIndex(
            model_name="affinitegroupeanimateur",
            index=models.Index(
                fields=["animateur", "jours_travailles"],
                name="affinite_anim_score_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="affinitegroupeanimateur",
            index=models.Index(
                fields=["evenement", "jours_travailles"],
                name="affinite_groupe_score_idx",
            ),
        ),
        migrations.RunPython(initialiser_affinites, migrations.RunPython.noop),
    ]
