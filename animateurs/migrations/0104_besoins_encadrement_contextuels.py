import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0103_ouvertures_periscolaires_et_effectifs_par_modalite"),
    ]

    operations = [
        migrations.CreateModel(
            name="BesoinEncadrement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("effectif_cible", models.PositiveSmallIntegerField(default=1)),
                (
                    "evenement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="besoins_encadrement",
                        to="animateurs.evenement",
                        verbose_name="groupe",
                    ),
                ),
                (
                    "modalite_periscolaire",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="besoins_encadrement",
                        to="animateurs.modaliteperiscolaire",
                    ),
                ),
                (
                    "periode_calendrier",
                    models.ForeignKey(
                        blank=True,
                        help_text="Optionnel : permet de surcharger les besoins pour une année/période précise.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="besoins_encadrement",
                        to="animateurs.periodecalendrier",
                    ),
                ),
                (
                    "type_accueil",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="besoins_encadrement",
                        to="animateurs.typeaccueil",
                    ),
                ),
            ],
            options={
                "ordering": (
                    "evenement_id",
                    "type_accueil__ordre",
                    "modalite_periscolaire__ordre",
                    "periode_calendrier__debut",
                ),
            },
        ),
        migrations.AddField(
            model_name="besoinqualification",
            name="periode_calendrier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="besoins_qualifications",
                to="animateurs.periodecalendrier",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="besoinqualification",
            name="unique_besoin_qualification_evenement",
        ),
        migrations.AddConstraint(
            model_name="besoinencadrement",
            constraint=models.UniqueConstraint(
                condition=models.Q(modalite_periscolaire__isnull=True, periode_calendrier__isnull=True),
                fields=("evenement", "type_accueil"),
                name="unique_besoin_encadrement_type",
            ),
        ),
        migrations.AddConstraint(
            model_name="besoinencadrement",
            constraint=models.UniqueConstraint(
                condition=models.Q(modalite_periscolaire__isnull=False, periode_calendrier__isnull=True),
                fields=("evenement", "type_accueil", "modalite_periscolaire"),
                name="unique_besoin_encadrement_type_modalite",
            ),
        ),
        migrations.AddConstraint(
            model_name="besoinencadrement",
            constraint=models.UniqueConstraint(
                condition=models.Q(modalite_periscolaire__isnull=True, periode_calendrier__isnull=False),
                fields=("evenement", "type_accueil", "periode_calendrier"),
                name="unique_besoin_encadrement_type_periode",
            ),
        ),
        migrations.AddConstraint(
            model_name="besoinencadrement",
            constraint=models.UniqueConstraint(
                condition=models.Q(modalite_periscolaire__isnull=False, periode_calendrier__isnull=False),
                fields=("evenement", "type_accueil", "modalite_periscolaire", "periode_calendrier"),
                name="unique_besoin_encadrement_contexte",
            ),
        ),
        migrations.AddConstraint(
            model_name="besoinqualification",
            constraint=models.UniqueConstraint(
                condition=models.Q(type_accueil__isnull=True, modalite_periscolaire__isnull=True, periode_calendrier__isnull=True),
                fields=("evenement", "qualification"),
                name="unique_besoin_qualification_generique",
            ),
        ),
        migrations.AddConstraint(
            model_name="besoinqualification",
            constraint=models.UniqueConstraint(
                condition=models.Q(type_accueil__isnull=False, modalite_periscolaire__isnull=True, periode_calendrier__isnull=True),
                fields=("evenement", "qualification", "type_accueil"),
                name="unique_besoin_qualification_type",
            ),
        ),
        migrations.AddConstraint(
            model_name="besoinqualification",
            constraint=models.UniqueConstraint(
                condition=models.Q(type_accueil__isnull=False, modalite_periscolaire__isnull=False, periode_calendrier__isnull=True),
                fields=("evenement", "qualification", "type_accueil", "modalite_periscolaire"),
                name="unique_besoin_qualification_modalite",
            ),
        ),
        migrations.AddConstraint(
            model_name="besoinqualification",
            constraint=models.UniqueConstraint(
                condition=models.Q(type_accueil__isnull=False, modalite_periscolaire__isnull=True, periode_calendrier__isnull=False),
                fields=("evenement", "qualification", "type_accueil", "periode_calendrier"),
                name="unique_besoin_qualification_periode",
            ),
        ),
        migrations.AddConstraint(
            model_name="besoinqualification",
            constraint=models.UniqueConstraint(
                condition=models.Q(type_accueil__isnull=False, modalite_periscolaire__isnull=False, periode_calendrier__isnull=False),
                fields=("evenement", "qualification", "type_accueil", "modalite_periscolaire", "periode_calendrier"),
                name="unique_besoin_qualification_contexte",
            ),
        ),
    ]
