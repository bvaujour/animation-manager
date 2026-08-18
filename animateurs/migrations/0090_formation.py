from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0089_statut_preparation_semaine")]

    operations = [
        migrations.CreateModel(
            name="Formation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("intitule", models.CharField(max_length=180)),
                ("date_debut", models.DateField()),
                ("date_fin", models.DateField()),
                ("organisme", models.CharField(blank=True, max_length=180)),
                ("lieu", models.CharField(blank=True, max_length=180)),
                ("statut", models.CharField(choices=[("prevue", "Prévue"), ("en_cours", "En cours"), ("terminee", "Terminée"), ("annulee", "Annulée")], default="prevue", max_length=20)),
                ("commentaire", models.TextField(blank=True, verbose_name="commentaire / notes")),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                ("animateurs", models.ManyToManyField(related_name="formations", to="animateurs.animateur", verbose_name="animateurs concernés")),
                ("qualification", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="formations_liees", to="animateurs.qualification", verbose_name="qualification liée")),
            ],
            options={"verbose_name": "formation", "verbose_name_plural": "formations", "ordering": ("date_debut", "intitule", "id")},
        )
    ]
