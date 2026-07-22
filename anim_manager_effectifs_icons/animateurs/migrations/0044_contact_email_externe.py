from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("animateurs", "0043_supprimer_modeles_email_exemples")]
    operations = [
        migrations.CreateModel(
            name="ContactEmailExterne",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("prenom", models.CharField(blank=True, max_length=100)),
                ("nom", models.CharField(max_length=100)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("organisation", models.CharField(blank=True, max_length=150)),
                ("actif", models.BooleanField(default=True)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "contact e-mail externe", "verbose_name_plural": "contacts e-mail externes", "ordering": ["nom", "prenom", "email"]},
        ),
        migrations.AddField(
            model_name="destinataireenvoiemail", name="contact_externe",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="emails_recus", to="animateurs.contactemailexterne"),
        ),
    ]
