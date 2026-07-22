from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0064_profils_import_effectifs"),
    ]

    operations = [
        migrations.AddField(
            model_name="qualification",
            name="icone",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Aucune icône"),
                    ("diplome", "Diplôme / qualification"),
                    ("secours", "Premiers secours"),
                    ("baignade", "Surveillance baignade"),
                    ("conduite", "Permis / conduite"),
                    ("sport", "Sport"),
                    ("direction", "Direction"),
                    ("repas", "Repas / alimentation"),
                ],
                default="",
                help_text="Icône facultative affichée à côté des animateurs possédant ce diplôme.",
                max_length=20,
            ),
        ),
    ]
