from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0082_demandemateriel_centre")]

    operations = [
        migrations.AddField(
            model_name="document",
            name="tous_centres",
            field=models.BooleanField(
                default=True,
                help_text="Si coché, le document concerne tous les centres.",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="centres",
            field=models.ManyToManyField(
                blank=True,
                help_text="Centres concernés lorsque le document n'est pas destiné à tous les centres.",
                related_name="documents",
                to="animateurs.centre",
            ),
        ),
    ]
