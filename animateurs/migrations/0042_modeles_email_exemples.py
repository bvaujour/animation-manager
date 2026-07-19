from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0041_delete_communicationanimateur"),
    ]

    operations = [
        migrations.CreateModel(
            name="ModeleEmail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=120, unique=True)),
                ("objet", models.CharField(max_length=200)),
                ("message", models.TextField()),
                ("actif", models.BooleanField(default=True)),
                ("ordre", models.PositiveSmallIntegerField(default=0)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "modèle d’e-mail",
                "verbose_name_plural": "modèles d’e-mail",
                "ordering": ("ordre", "nom"),
            },
        ),
        migrations.AddField(
            model_name="destinataireenvoiemail",
            name="message_rendu",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="destinataireenvoiemail",
            name="objet_rendu",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
    ]
