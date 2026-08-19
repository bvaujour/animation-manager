from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0099_permanent_dates_facultatives"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InformationAnimateur",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("titre", models.CharField(max_length=140)),
                ("message", models.TextField()),
                ("date_debut", models.DateField(verbose_name="début d'affichage")),
                ("date_fin", models.DateField(verbose_name="fin d'affichage")),
                (
                    "importance",
                    models.CharField(
                        choices=[("normale", "Normale"), ("importante", "Importante")],
                        db_index=True,
                        default="normale",
                        max_length=20,
                    ),
                ),
                ("publie", models.BooleanField(db_index=True, default=True)),
                (
                    "tous_animateurs",
                    models.BooleanField(
                        default=True,
                        help_text="Si coché, l'information est visible par tous les animateurs.",
                    ),
                ),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("date_modification", models.DateTimeField(auto_now=True)),
                (
                    "animateurs",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Animateurs ciblés lorsque l'information n'est pas destinée à toute l'équipe.",
                        related_name="informations_portail",
                        to="animateurs.animateur",
                    ),
                ),
                (
                    "auteur",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="informations_animateurs_creees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "information animateur",
                "verbose_name_plural": "informations animateurs",
                "ordering": ["importance", "-date_debut", "-date_creation"],
            },
        ),
        migrations.AddIndex(
            model_name="informationanimateur",
            index=models.Index(fields=["publie", "date_debut", "date_fin"], name="info_anim_periode_idx"),
        ),
    ]
