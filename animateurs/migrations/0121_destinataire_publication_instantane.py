from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0120_publication_affectations_periode")]

    operations = [
        migrations.AddField(
            model_name="destinatairepublicationaffectation",
            name="instantane_affectations",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="destinatairepublicationaffectation",
            name="retire_le",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
