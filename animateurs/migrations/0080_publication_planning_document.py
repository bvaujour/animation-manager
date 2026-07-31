from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0079_prime_journaliere_periode")]

    operations = [
        migrations.CreateModel(
            name="PublicationPlanning",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("semaine_debut", models.DateField(db_index=True, unique=True)),
                ("publie", models.BooleanField(db_index=True, default=False)),
                ("date_modification", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-semaine_debut"]},
        ),
        migrations.AddField(
            model_name="document",
            name="publie",
            field=models.BooleanField(db_index=True, default=False, help_text="Seuls les documents publiés sont visibles dans l’espace animateur.", verbose_name="publié pour les animateurs"),
        ),
    ]
