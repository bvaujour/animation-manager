import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0059_categories_qualifications"),
    ]

    operations = [
        migrations.RenameField(
            model_name="qualification",
            old_name="est_categorie",
            new_name="est_statut",
        ),
        migrations.RenameField(
            model_name="qualification",
            old_name="categorie",
            new_name="statut",
        ),
        migrations.AlterField(
            model_name="qualification",
            name="est_statut",
            field=models.BooleanField(
                default=False,
                help_text="Statut regroupant plusieurs diplômes (ex. Diplômé).",
            ),
        ),
        migrations.AlterField(
            model_name="qualification",
            name="statut",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={"est_statut": True},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="diplomes",
                to="animateurs.qualification",
            ),
        ),
        migrations.DeleteModel(
            name="EquivalenceQualification",
        ),
    ]
