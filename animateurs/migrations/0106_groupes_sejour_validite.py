from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0105_encadrement_reglementaire_et_groupes_age"),
    ]

    operations = [
        migrations.AddField(
            model_name="groupe",
            name="type_groupe",
            field=models.CharField(
                choices=[
                    ("structure", "Groupe structurel"),
                    ("sejour", "Séjour temporaire"),
                ],
                default="structure",
                max_length=20,
                verbose_name="type de groupe",
            ),
        ),
        migrations.AddField(
            model_name="groupe",
            name="date_debut_validite",
            field=models.DateField(
                blank=True,
                help_text="Obligatoire pour un groupe de séjour temporaire.",
                null=True,
                verbose_name="début de validité",
            ),
        ),
        migrations.AddField(
            model_name="groupe",
            name="date_fin_validite",
            field=models.DateField(
                blank=True,
                help_text="Obligatoire pour un groupe de séjour temporaire.",
                null=True,
                verbose_name="fin de validité",
            ),
        ),
    ]
