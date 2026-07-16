from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0018_centre_ordre_affichage_planning")]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE animateurs_equipe RENAME TO animateurs_evenement;",
                "ALTER TABLE animateurs_affectation RENAME COLUMN equipe_id TO evenement_id;",
                "ALTER TABLE animateurs_animateur RENAME COLUMN equipe_preferee_id TO evenement_preferee_id;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameModel(old_name="Equipe", new_name="Evenement"),
                migrations.RenameField(model_name="animateur", old_name="equipe_preferee", new_name="evenement_preferee"),
                migrations.RenameField(model_name="affectation", old_name="equipe", new_name="evenement"),
            ],
        ),
        migrations.AddField(model_name="evenement", name="debut", field=models.DateField(blank=True, null=True, help_text="Premier jour de l’événement")),
        migrations.AddField(model_name="evenement", name="fin", field=models.DateField(blank=True, null=True, help_text="Dernier jour de l’événement inclus")),
        migrations.CreateModel(
            name="BesoinQualification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre_minimum", models.PositiveSmallIntegerField(default=1)),
                ("evenement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="besoins_qualifications", to="animateurs.evenement")),
                ("qualification", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="animateurs.qualification")),
            ],
            options={"ordering": ["qualification__nom"]},
        ),
        migrations.AddConstraint(
            model_name="besoinqualification",
            constraint=models.UniqueConstraint(fields=("evenement", "qualification"), name="unique_besoin_qualification_evenement"),
        ),
        migrations.AddField(
            model_name="evenement",
            name="qualifications_requises",
            field=models.ManyToManyField(blank=True, related_name="evenements_requerants", through="animateurs.BesoinQualification", to="animateurs.qualification"),
        ),
    ]
