from django.db import migrations


def rattacher_toutes_les_periodes(apps, schema_editor):
    Evenement = apps.get_model("animateurs", "Evenement")
    PeriodeScolaire = apps.get_model("animateurs", "PeriodeScolaire")
    ids_periodes = list(PeriodeScolaire.objects.values_list("id", flat=True))
    if not ids_periodes:
        return
    for groupe in Evenement.objects.filter(permanent=True).iterator():
        groupe.periodes_scolaires.set(ids_periodes)


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0029_evenement_permanent")]
    operations = [migrations.RunPython(rattacher_toutes_les_periodes, migrations.RunPython.noop)]
