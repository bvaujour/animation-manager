from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0048_document_periodes")]
    operations = [
        migrations.CreateModel(
            name="EffectifEnfantsJour",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(db_index=True)),
                ("nombre", models.PositiveSmallIntegerField(default=0)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("evenement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="effectifs_enfants", to="animateurs.evenement", verbose_name="groupe")),
            ],
            options={"verbose_name": "effectif enfants journalier", "verbose_name_plural": "effectifs enfants journaliers", "ordering": ("date",)},
        ),
        migrations.AddConstraint(
            model_name="effectifenfantsjour",
            constraint=models.UniqueConstraint(fields=("evenement", "date"), name="unique_effectif_enfants_groupe_date"),
        ),
    ]
