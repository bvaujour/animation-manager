from django.db import migrations, models


def convertir_anciens_roles(apps, schema_editor):
    Animateur = apps.get_model("animateurs", "Animateur")
    User = apps.get_model("auth", "User")
    for animateur in Animateur.objects.exclude(role="animateur"):
        if animateur.utilisateur_id:
            User.objects.filter(pk=animateur.utilisateur_id).update(
                is_staff=True,
                is_superuser=True,
                is_active=True,
            )
        animateur.role = "animateur"
        animateur.save(update_fields=["role"])


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0036_animateur_doit_changer_mot_de_passe")]
    operations = [
        migrations.RunPython(convertir_anciens_roles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="animateur",
            name="role",
            field=models.CharField(
                choices=[("animateur", "Animateur")],
                default="animateur",
                max_length=20,
                verbose_name="rôle dans l’application",
            ),
        ),
    ]
