from django.db import migrations, models


def definir_un_centre_prefere_par_animateur(apps, schema_editor):
    PreferenceCentre = apps.get_model("animateurs", "PreferenceCentre")
    animateur_ids = (
        PreferenceCentre.objects.order_by()
        .values_list("animateur_id", flat=True)
        .distinct()
    )
    for animateur_id in animateur_ids:
        premiere = (
            PreferenceCentre.objects.filter(animateur_id=animateur_id)
            .order_by("id")
            .first()
        )
        if premiere:
            PreferenceCentre.objects.filter(pk=premiere.pk).update(est_prefere=True)


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0014_qualification_selectionnable_auto"),
    ]

    operations = [
        migrations.AlterField(
            model_name="qualification",
            name="selectionnable_remplissage_auto",
            field=models.BooleanField(
                default=False,
                help_text="Affiche cette qualification parmi les exigences du remplissage automatique.",
            ),
        ),
        migrations.AddField(
            model_name="preferencecentre",
            name="est_prefere",
            field=models.BooleanField(
                default=False,
                help_text="Centre principal à privilégier lors du remplissage automatique.",
            ),
        ),
        migrations.RunPython(
            definir_un_centre_prefere_par_animateur,
            migrations.RunPython.noop,
        ),
        migrations.AlterModelOptions(
            name="preferencecentre",
            options={"ordering": ["-est_prefere", "centre__nom"]},
        ),
        migrations.AddConstraint(
            model_name="preferencecentre",
            constraint=models.UniqueConstraint(
                condition=models.Q(est_prefere=True),
                fields=("animateur",),
                name="unique_centre_prefere_par_animateur",
            ),
        ),
    ]
