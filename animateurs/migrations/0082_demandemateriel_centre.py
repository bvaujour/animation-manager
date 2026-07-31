from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0081_demandemateriel")]

    operations = [
        migrations.AddField(
            model_name="demandemateriel",
            name="centre",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="demandes_materiel",
                to="animateurs.centre",
            ),
        ),
    ]
