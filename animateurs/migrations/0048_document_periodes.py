from django.db import migrations, models


def rattacher_documents_existants(apps, schema_editor):
    Document = apps.get_model("animateurs", "Document")
    PeriodeScolaire = apps.get_model("animateurs", "PeriodeScolaire")
    for document in Document.objects.filter(permanent=False).exclude(periode_debut=None).exclude(periode_fin=None):
        periodes = PeriodeScolaire.objects.filter(debut__gte=document.periode_debut, fin__lte=document.periode_fin)
        document.periodes.set(periodes)


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0045_remove_evenement_date_bounds")]
    operations = [
        migrations.AddField(
            model_name="document",
            name="periodes",
            field=models.ManyToManyField(blank=True, help_text="Semaines auxquelles ce document est rattaché.", related_name="documents", to="animateurs.periodescolaire"),
        ),
        migrations.RunPython(rattacher_documents_existants, migrations.RunPython.noop),
    ]
