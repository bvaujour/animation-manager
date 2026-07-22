from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0044_contact_email_externe"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="evenement",
            name="evenement_fin_apres_debut",
        ),
        migrations.RemoveField(
            model_name="evenement",
            name="debut",
        ),
        migrations.RemoveField(
            model_name="evenement",
            name="fin",
        ),
    ]
