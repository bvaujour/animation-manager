from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0125_annulation_publication_affectation"),
    ]

    operations = [
        migrations.AddField(
            model_name="destinatairepublicationaffectation",
            name="instantane_modifie_le",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
