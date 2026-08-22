from django.db import migrations, models
import django.db.models.deletion


def creer_accueils_historiques(apps, schema_editor):
    Centre = apps.get_model("animateurs", "Centre")
    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    AccueilCentre = apps.get_model("animateurs", "AccueilCentre")
    ParametresStructure = apps.get_model("animateurs", "ParametresStructure")

    pedt_global = False
    structure = ParametresStructure.objects.order_by("id").first()
    if structure is not None:
        pedt_global = bool(getattr(structure, "pedt_actif", False))

    for centre in Centre.objects.prefetch_related("types_accueil").all():
        for type_accueil in centre.types_accueil.all():
            if type_accueil.code not in ("vacances", "periscolaire"):
                continue
            AccueilCentre.objects.get_or_create(
                centre_id=centre.id,
                type_accueil_id=type_accueil.id,
                libelle="",
                defaults={
                    "date_debut": None,
                    "date_fin": None,
                    "pedt_applicable": pedt_global if type_accueil.code == "periscolaire" else False,
                },
            )


def rattacher_ouvertures_historiques(apps, schema_editor):
    AccueilCentre = apps.get_model("animateurs", "AccueilCentre")
    OuvertureCentrePeriode = apps.get_model("animateurs", "OuvertureCentrePeriode")
    accueils = {
        accueil.centre_id: accueil.id
        for accueil in AccueilCentre.objects.filter(type_accueil__code="periscolaire", libelle="")
    }
    for ouverture in OuvertureCentrePeriode.objects.filter(accueil_centre__isnull=True).iterator():
        accueil_id = accueils.get(ouverture.centre_id)
        if accueil_id:
            ouverture.accueil_centre_id = accueil_id
            ouverture.save(update_fields=["accueil_centre"])


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0106_groupes_sejour_validite")]

    operations = [
        migrations.CreateModel(
            name="AccueilCentre",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("libelle", models.CharField(blank=True, default="", help_text="Facultatif pour un accueil unique ; utile pour distinguer plusieurs accueils Périscolaire (ex. Mercredi, Semaine).", max_length=80, verbose_name="nom complémentaire")),
                ("date_debut", models.DateField(blank=True, help_text="Les accueils historiques migrés peuvent rester sans date.", null=True, verbose_name="début d'activité")),
                ("date_fin", models.DateField(blank=True, null=True, verbose_name="fin d'activité")),
                ("pedt_applicable", models.BooleanField(default=False, verbose_name="PEDT applicable au périscolaire")),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("centre", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="accueils", to="animateurs.centre")),
                ("type_accueil", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="accueils_centres", to="animateurs.typeaccueil")),
            ],
            options={
                "verbose_name": "accueil d'un lieu",
                "verbose_name_plural": "accueils des lieux",
                "ordering": ("centre__ordre", "centre__nom", "type_accueil__ordre", "type_accueil__nom", "libelle"),
            },
        ),
        migrations.AddConstraint(
            model_name="accueilcentre",
            constraint=models.UniqueConstraint(fields=("centre", "type_accueil", "libelle"), name="unique_accueil_type_libelle_par_centre"),
        ),
        migrations.AddConstraint(
            model_name="accueilcentre",
            constraint=models.CheckConstraint(
                condition=(models.Q(("date_debut__isnull", True)) | models.Q(("date_fin__isnull", True)) | models.Q(("date_fin__gte", models.F("date_debut")))),
                name="accueil_centre_fin_apres_debut",
            ),
        ),
        migrations.RunPython(creer_accueils_historiques, migrations.RunPython.noop),
        migrations.AddField(
            model_name="ouverturecentreperiode",
            name="accueil_centre",
            field=models.ForeignKey(blank=True, help_text="Accueil Périscolaire auquel appartient ce créneau. Null uniquement pour compatibilité historique.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ouvertures_periodes", to="animateurs.accueilcentre"),
        ),
        migrations.RunPython(rattacher_ouvertures_historiques, migrations.RunPython.noop),
    ]
