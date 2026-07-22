from django.db import migrations


NOMS_MODELES_EXEMPLES = [
    "Information générale",
    "Modification du planning",
    "Rappel de réunion",
    "Document manquant",
    "Vérification des qualifications",
    "Confirmation d’affectation",
]


def supprimer_modeles_exemples(apps, schema_editor):
    ModeleEmail = apps.get_model("animateurs", "ModeleEmail")
    ModeleEmail.objects.filter(nom__in=NOMS_MODELES_EXEMPLES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0042_modeles_email_exemples"),
    ]

    operations = [
        migrations.RunPython(supprimer_modeles_exemples, migrations.RunPython.noop),
    ]
