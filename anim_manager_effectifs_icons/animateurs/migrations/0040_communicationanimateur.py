from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0039_equivalences_qualifications_directionnelles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CommunicationAnimateur",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("canal", models.CharField(choices=[("sms", "SMS"), ("whatsapp", "WhatsApp"), ("email", "E-mail"), ("messenger", "Messenger")], max_length=16)),
                ("destinataire", models.CharField(blank=True, max_length=254)),
                ("objet", models.CharField(blank=True, max_length=200)),
                ("message", models.TextField()),
                ("statut", models.CharField(choices=[("prepare", "Préparé"), ("ouvert", "Application ouverte"), ("envoye", "Envoyé"), ("echec", "Échec")], default="prepare", max_length=16)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("animateur", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="communications", to="animateurs.animateur")),
                ("auteur", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="communications_preparees", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-date_creation", "-id")},
        ),
    ]
