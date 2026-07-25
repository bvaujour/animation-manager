import unicodedata

import django.db.models.deletion
from django.db import migrations, models


def _normaliser(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in value if not unicodedata.combining(char)).lower()


def copier_anciens_responsables(apps, schema_editor):
    Sortie = apps.get_model("animateurs", "Sortie")
    Responsabilite = apps.get_model("animateurs", "SortieResponsabilite")
    Participation = apps.get_model("animateurs", "SortieParticipation")

    for sortie in Sortie.objects.all().iterator():
        ordre = 0
        if sortie.responsable_general_id:
            Responsabilite.objects.get_or_create(
                sortie_id=sortie.id,
                animateur_id=sortie.responsable_general_id,
                type="direction",
                centre_id=None,
                evenement_id=None,
                defaults={"ordre": ordre},
            )
            ordre += 1

        for animateur_id, mots_cles in (
            (sortie.responsable_maternels_id, ("mater", "3/5")),
            (sortie.responsable_elementaires_id, ("elemen", "6/10")),
        ):
            if not animateur_id:
                continue
            participations = list(
                Participation.objects.filter(sortie_id=sortie.id).select_related("evenement")
            )
            cibles = [
                item.evenement_id
                for item in participations
                if any(mot in _normaliser(item.evenement.nom) for mot in mots_cles)
            ]
            if cibles:
                for evenement_id in cibles:
                    Responsabilite.objects.get_or_create(
                        sortie_id=sortie.id,
                        animateur_id=animateur_id,
                        type="groupe",
                        centre_id=None,
                        evenement_id=evenement_id,
                        defaults={"ordre": ordre},
                    )
            else:
                Responsabilite.objects.get_or_create(
                    sortie_id=sortie.id,
                    animateur_id=animateur_id,
                    type="direction",
                    centre_id=None,
                    evenement_id=None,
                    defaults={"ordre": ordre},
                )
            ordre += 1


def restaurer_anciens_responsables(apps, schema_editor):
    Sortie = apps.get_model("animateurs", "Sortie")
    Responsabilite = apps.get_model("animateurs", "SortieResponsabilite")

    for sortie in Sortie.objects.all().iterator():
        responsabilites = list(
            Responsabilite.objects.filter(sortie_id=sortie.id)
            .select_related("evenement")
            .order_by("ordre", "id")
        )
        direction = next((item for item in responsabilites if item.type == "direction"), None)
        maternels = next(
            (
                item
                for item in responsabilites
                if item.type == "groupe"
                and item.evenement_id
                and ("mater" in _normaliser(item.evenement.nom) or "3/5" in _normaliser(item.evenement.nom))
            ),
            None,
        )
        elementaires = next(
            (
                item
                for item in responsabilites
                if item.type == "groupe"
                and item.evenement_id
                and ("elemen" in _normaliser(item.evenement.nom) or "6/10" in _normaliser(item.evenement.nom))
            ),
            None,
        )
        sortie.responsable_general_id = direction.animateur_id if direction else None
        sortie.responsable_maternels_id = maternels.animateur_id if maternels else None
        sortie.responsable_elementaires_id = elementaires.animateur_id if elementaires else None
        sortie.save(
            update_fields=(
                "responsable_general",
                "responsable_maternels",
                "responsable_elementaires",
            )
        )


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0069_sortie_sortielien_sortieparticipation_sortie_groupes_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SortieResponsabilite",
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
                    "type",
                    models.CharField(
                        choices=[
                            ("direction", "Direction"),
                            ("lieu", "Responsable de lieu"),
                            ("groupe", "Responsable de groupe"),
                        ],
                        max_length=12,
                    ),
                ),
                ("ordre", models.PositiveSmallIntegerField(default=0)),
                (
                    "animateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="responsabilites_sorties",
                        to="animateurs.animateur",
                    ),
                ),
                (
                    "centre",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="responsabilites_sorties",
                        to="animateurs.centre",
                    ),
                ),
                (
                    "evenement",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="responsabilites_sorties",
                        to="animateurs.evenement",
                    ),
                ),
                (
                    "sortie",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="responsabilites",
                        to="animateurs.sortie",
                    ),
                ),
            ],
            options={
                "ordering": ("ordre", "type", "centre__ordre", "evenement__ordre", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="sortieresponsabilite",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(type="direction", centre__isnull=True, evenement__isnull=True)
                    | models.Q(type="lieu", centre__isnull=False, evenement__isnull=True)
                    | models.Q(type="groupe", centre__isnull=True, evenement__isnull=False)
                ),
                name="responsabilite_sortie_perimetre_coherent",
            ),
        ),
        migrations.AddConstraint(
            model_name="sortieresponsabilite",
            constraint=models.UniqueConstraint(
                condition=models.Q(type="direction"),
                fields=("sortie", "animateur"),
                name="unique_direction_anim_par_sortie",
            ),
        ),
        migrations.AddConstraint(
            model_name="sortieresponsabilite",
            constraint=models.UniqueConstraint(
                condition=models.Q(type="lieu"),
                fields=("sortie", "animateur", "centre"),
                name="unique_lieu_anim_par_sortie",
            ),
        ),
        migrations.AddConstraint(
            model_name="sortieresponsabilite",
            constraint=models.UniqueConstraint(
                condition=models.Q(type="groupe"),
                fields=("sortie", "animateur", "evenement"),
                name="unique_groupe_anim_par_sortie",
            ),
        ),
        migrations.RunPython(copier_anciens_responsables, restaurer_anciens_responsables),
        migrations.RemoveField(model_name="sortie", name="responsable_general"),
        migrations.RemoveField(model_name="sortie", name="responsable_maternels"),
        migrations.RemoveField(model_name="sortie", name="responsable_elementaires"),
    ]
