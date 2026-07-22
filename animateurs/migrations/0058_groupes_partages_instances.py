import django.db.models.deletion
from django.db import migrations, models


def creer_groupes_partages(apps, schema_editor):
    Evenement = apps.get_model("animateurs", "Evenement")
    Groupe = apps.get_model("animateurs", "Groupe")
    BesoinInstance = apps.get_model("animateurs", "BesoinQualification")
    BesoinGroupe = apps.get_model("animateurs", "BesoinQualificationGroupe")

    groupes_par_cle = {}
    for instance in Evenement.objects.order_by("id"):
        groupe = groupes_par_cle.get(instance.cle_unique)
        if groupe is None:
            groupe = Groupe.objects.create(
                nom=instance.nom,
                cle_unique=instance.cle_unique,
                enfants_par_animateur_defaut=instance.enfants_par_animateur_defaut,
            )
            groupes_par_cle[instance.cle_unique] = groupe
        instance.groupe_id = groupe.id
        instance.nom = groupe.nom
        instance.enfants_par_animateur_defaut = groupe.enfants_par_animateur_defaut
        instance.save(update_fields=["groupe", "nom", "enfants_par_animateur_defaut"])

        for besoin in BesoinInstance.objects.filter(evenement_id=instance.id):
            ligne, creation = BesoinGroupe.objects.get_or_create(
                groupe_id=groupe.id,
                qualification_id=besoin.qualification_id,
                defaults={"nombre_minimum": besoin.nombre_minimum},
            )
            if not creation and besoin.nombre_minimum > ligne.nombre_minimum:
                ligne.nombre_minimum = besoin.nombre_minimum
                ligne.save(update_fields=["nombre_minimum"])

    for instance in Evenement.objects.all():
        BesoinInstance.objects.filter(evenement_id=instance.id).delete()
        besoins = BesoinGroupe.objects.filter(groupe_id=instance.groupe_id)
        BesoinInstance.objects.bulk_create(
            [
                BesoinInstance(
                    evenement_id=instance.id,
                    qualification_id=besoin.qualification_id,
                    nombre_minimum=besoin.nombre_minimum,
                )
                for besoin in besoins
            ]
        )


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0057_effectifenfantsjour_heures")]

    operations = [
        migrations.CreateModel(
            name="Groupe",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=100)),
                ("cle_unique", models.CharField(default="", editable=False, max_length=120, unique=True)),
                (
                    "enfants_par_animateur_defaut",
                    models.PositiveSmallIntegerField(
                        default=8, verbose_name="nombre d’enfants par animateur par défaut"
                    ),
                ),
            ],
            options={"verbose_name": "groupe partagé", "verbose_name_plural": "groupes partagés", "ordering": ["nom"]},
        ),
        migrations.CreateModel(
            name="BesoinQualificationGroupe",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre_minimum", models.PositiveSmallIntegerField(default=1)),
                (
                    "groupe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="besoins_qualifications",
                        to="animateurs.groupe",
                    ),
                ),
                (
                    "qualification",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="animateurs.qualification"),
                ),
            ],
            options={"ordering": ["qualification__nom"]},
        ),
        migrations.AddConstraint(
            model_name="besoinqualificationgroupe",
            constraint=models.UniqueConstraint(
                fields=("groupe", "qualification"), name="unique_besoin_qualification_groupe_partage"
            ),
        ),
        migrations.AddField(
            model_name="groupe",
            name="qualifications_requises",
            field=models.ManyToManyField(
                blank=True,
                related_name="groupes_requerants",
                through="animateurs.BesoinQualificationGroupe",
                to="animateurs.qualification",
            ),
        ),
        migrations.AddField(
            model_name="evenement",
            name="groupe",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="instances",
                to="animateurs.groupe",
                verbose_name="groupe partagé",
            ),
        ),
        migrations.RunPython(creer_groupes_partages, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="evenement",
            name="groupe",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="instances",
                to="animateurs.groupe",
                verbose_name="groupe partagé",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="evenement",
            name="unique_groupe_nom_normalise_par_lieu",
        ),
        migrations.AddConstraint(
            model_name="evenement",
            constraint=models.UniqueConstraint(fields=("centre", "groupe"), name="unique_instance_groupe_par_lieu"),
        ),
    ]
