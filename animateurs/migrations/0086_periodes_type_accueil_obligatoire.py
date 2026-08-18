import animateurs.models
import django.db.models.deletion
from django.db import migrations, models


def classer_periodes_existantes(apps, schema_editor):
    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    PeriodeScolaire = apps.get_model("animateurs", "PeriodeScolaire")
    vacances = TypeAccueil.objects.get(code="vacances")
    PeriodeScolaire.objects.filter(type_accueil__isnull=True).update(type_accueil=vacances)


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0085_relations_types_accueil_progressives")]

    operations = [
        migrations.RunPython(classer_periodes_existantes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="periodescolaire",
            name="type_accueil",
            field=models.ForeignKey(
                default=animateurs.models.type_accueil_vacances_par_defaut,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="periodes",
                to="animateurs.typeaccueil",
            ),
        ),
    ]
