from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0032_unicite_noms_normalises"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="animateur",
            name="utilisateur",
            field=models.OneToOneField(
                blank=True,
                help_text="Compte utilisé par ce salarié pour accéder à son espace animateur.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="profil_animateur",
                to=settings.AUTH_USER_MODEL,
                verbose_name="compte de connexion",
            ),
        ),
    ]
