import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0084_socle_types_accueil")]

    operations = [
        migrations.AddField(
            model_name="groupe",
            name="types_accueil",
            field=models.ManyToManyField(
                blank=True,
                help_text="Types d'accueil utilisant cette définition partagée.",
                related_name="groupes_partages",
                to="animateurs.typeaccueil",
            ),
        ),
        migrations.AddField(
            model_name="effectifenfantsjour",
            name="type_accueil",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="effectifs_enfants",
                to="animateurs.typeaccueil",
            ),
        ),
        migrations.AddField(
            model_name="besoinqualification",
            name="type_accueil",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="besoins_qualifications",
                to="animateurs.typeaccueil",
            ),
        ),
        migrations.AddField(
            model_name="publicationplanning",
            name="type_accueil",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="publications_planning",
                to="animateurs.typeaccueil",
            ),
        ),
        migrations.AddField(
            model_name="sortie",
            name="type_accueil",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sorties",
                to="animateurs.typeaccueil",
            ),
        ),
        migrations.AddField(
            model_name="modeleemail",
            name="types_accueil",
            field=models.ManyToManyField(
                blank=True,
                help_text="Vide signifie que le modèle reste utilisable dans tous les contextes.",
                related_name="modeles_email",
                to="animateurs.typeaccueil",
            ),
        ),
    ]
