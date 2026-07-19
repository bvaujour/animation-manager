from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0037_deux_statuts_superuser_animateur"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="JournalAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("methode", models.CharField(max_length=10)),
                ("chemin", models.CharField(max_length=500)),
                ("statut_http", models.PositiveSmallIntegerField()),
                ("adresse_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("donnees", models.JSONField(blank=True, default=dict)),
                ("date_creation", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("utilisateur", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="actions_auditees", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "entrée du journal d'audit",
                "verbose_name_plural": "journal d'audit",
                "ordering": ("-date_creation", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="journalaudit",
            index=models.Index(fields=["utilisateur", "-date_creation"], name="audit_user_date_idx"),
        ),
        migrations.AddIndex(
            model_name="journalaudit",
            index=models.Index(fields=["chemin", "-date_creation"], name="audit_path_date_idx"),
        ),
    ]
