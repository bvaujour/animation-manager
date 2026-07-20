from django.db import migrations, models


def reprendre_anciens_ratios(apps, schema_editor):
    Effectif = apps.get_model("animateurs", "EffectifEnfantsJour")
    for ligne in Effectif.objects.select_related("evenement").iterator():
        ratio_defaut = ligne.evenement.enfants_par_animateur_defaut
        if ligne.enfants_par_animateur != ratio_defaut:
            ligne.ratio_encadrement_exceptionnel = ligne.enfants_par_animateur
            ligne.save(update_fields=["ratio_encadrement_exceptionnel"])


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0051_evenement_enfants_par_animateur_defaut")]

    operations = [
        migrations.AddField(
            model_name="effectifenfantsjour",
            name="ratio_encadrement_exceptionnel",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="ratio d’encadrement exceptionnel"
            ),
        ),
        migrations.RunPython(reprendre_anciens_ratios, migrations.RunPython.noop),
    ]
