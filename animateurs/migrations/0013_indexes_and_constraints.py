from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0012_document_periode")]

    operations = [
        migrations.AddIndex(
            model_name="disponibilite",
            index=models.Index(fields=["animateur", "debut", "fin"], name="dispo_anim_dates_idx"),
        ),
        migrations.AddIndex(
            model_name="affectation",
            index=models.Index(fields=["centre", "debut"], name="aff_centre_debut_idx"),
        ),
        migrations.AddIndex(
            model_name="affectation",
            index=models.Index(fields=["animateur", "debut"], name="aff_anim_debut_idx"),
        ),
        migrations.AddIndex(
            model_name="affectation",
            index=models.Index(fields=["debut", "fin"], name="aff_periode_idx"),
        ),
        migrations.AddConstraint(
            model_name="affectation",
            constraint=models.CheckConstraint(
                condition=models.Q(("fin__gt", models.F("debut"))),
                name="affectation_fin_apres_debut",
            ),
        ),
        migrations.AddIndex(
            model_name="document",
            index=models.Index(fields=["permanent", "periode_debut", "periode_fin"], name="document_periode_idx"),
        ),
    ]
