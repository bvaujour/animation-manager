from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0119_retirer_categorie_document_historique")]

    operations = [
        migrations.CreateModel(
            name="PublicationAffectationsPeriode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message", models.TextField(blank=True, default="")),
                ("publie", models.BooleanField(db_index=True, default=False)),
                ("publie_le", models.DateTimeField(blank=True, null=True)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("periode_calendrier", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="publication_affectations", to="animateurs.periodecalendrier")),
                ("publie_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="publications_affectations_periode", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "publication d'affectations", "verbose_name_plural": "publications d'affectations"},
        ),
        migrations.CreateModel(
            name="DestinatairePublicationAffectation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("confirme_le", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("animateur", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="publications_affectations_recues", to="animateurs.animateur")),
                ("publication", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="destinataires", to="animateurs.publicationaffectationsperiode")),
            ],
            options={"ordering": ("animateur__nom", "animateur__prenom")},
        ),
        migrations.AddConstraint(
            model_name="destinatairepublicationaffectation",
            constraint=models.UniqueConstraint(fields=("publication", "animateur"), name="unique_destinataire_publication_affectation"),
        ),
    ]
