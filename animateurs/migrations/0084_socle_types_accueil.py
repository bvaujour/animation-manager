import django.db.models.deletion
from django.db import migrations, models


TYPES_ACCUEIL = (
    ("vacances", "Vacances", 10),
    ("mercredis", "Mercredis", 20),
    ("periscolaire", "Périscolaire", 30),
    ("sejours", "Séjours", 40),
)


def initialiser_types_accueil(apps, schema_editor):
    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    Centre = apps.get_model("animateurs", "Centre")
    Evenement = apps.get_model("animateurs", "Evenement")
    PeriodeScolaire = apps.get_model("animateurs", "PeriodeScolaire")
    Affectation = apps.get_model("animateurs", "Affectation")

    types = {}
    for code, nom, ordre in TYPES_ACCUEIL:
        types[code], _ = TypeAccueil.objects.update_or_create(
            code=code,
            defaults={"nom": nom, "ordre": ordre, "actif": True},
        )

    vacances = types["vacances"]
    # Le produit historique gère les vacances. Ces rattachements explicites
    # préservent donc son comportement sans tenter de deviner les futurs cas.
    for centre in Centre.objects.all().iterator():
        centre.types_accueil.add(vacances)
    for evenement in Evenement.objects.all().iterator():
        evenement.types_accueil.add(vacances)
    PeriodeScolaire.objects.filter(type_accueil__isnull=True).update(type_accueil=vacances)
    Affectation.objects.filter(type_accueil__isnull=True).update(type_accueil=vacances)


def retirer_initialisation(apps, schema_editor):
    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    Centre = apps.get_model("animateurs", "Centre")
    Evenement = apps.get_model("animateurs", "Evenement")
    PeriodeScolaire = apps.get_model("animateurs", "PeriodeScolaire")
    Affectation = apps.get_model("animateurs", "Affectation")
    Disponibilite = apps.get_model("animateurs", "Disponibilite")
    Document = apps.get_model("animateurs", "Document")
    ActiviteTravailComplementaire = apps.get_model("animateurs", "ActiviteTravailComplementaire")

    codes = [code for code, _nom, _ordre in TYPES_ACCUEIL]
    ids = list(TypeAccueil.objects.filter(code__in=codes).values_list("id", flat=True))
    if ids:
        Centre.types_accueil.through.objects.filter(typeaccueil_id__in=ids).delete()
        Evenement.types_accueil.through.objects.filter(typeaccueil_id__in=ids).delete()
        Disponibilite.types_accueil.through.objects.filter(typeaccueil_id__in=ids).delete()
        Document.types_accueil.through.objects.filter(typeaccueil_id__in=ids).delete()
        PeriodeScolaire.objects.filter(type_accueil_id__in=ids).update(type_accueil=None)
        Affectation.objects.filter(type_accueil_id__in=ids).update(type_accueil=None)
        ActiviteTravailComplementaire.objects.filter(type_accueil_id__in=ids).update(type_accueil=None)
        TypeAccueil.objects.filter(id__in=ids).delete()


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0083_document_centres")]

    operations = [
        migrations.CreateModel(
            name="TypeAccueil",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=24, unique=True)),
                ("nom", models.CharField(max_length=60, unique=True)),
                ("ordre", models.PositiveSmallIntegerField(default=0)),
                ("actif", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "type d'accueil",
                "verbose_name_plural": "types d'accueil",
                "ordering": ("ordre", "nom"),
            },
        ),
        migrations.AddField(
            model_name="centre",
            name="types_accueil",
            field=models.ManyToManyField(blank=True, help_text="Types d'accueil proposés dans ce lieu physique.", related_name="centres", to="animateurs.typeaccueil"),
        ),
        migrations.AddField(
            model_name="evenement",
            name="types_accueil",
            field=models.ManyToManyField(blank=True, related_name="groupes_accueil", to="animateurs.typeaccueil"),
        ),
        migrations.AddField(
            model_name="periodeScolaire",
            name="type_accueil",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="periodes", to="animateurs.typeaccueil"),
        ),
        migrations.AddField(
            model_name="disponibilite",
            name="types_accueil",
            field=models.ManyToManyField(blank=True, help_text="Vide signifie que la disponibilité reste générale.", related_name="disponibilites", to="animateurs.typeaccueil"),
        ),
        migrations.AddField(
            model_name="affectation",
            name="type_accueil",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="affectations", to="animateurs.typeaccueil"),
        ),
        migrations.AddField(
            model_name="activitetravailcomplementaire",
            name="type_accueil",
            field=models.ForeignKey(blank=True, help_text="Vide signifie que l'activité reste visible dans la vue générale.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="activites_travail_complementaires", to="animateurs.typeaccueil"),
        ),
        migrations.AddField(
            model_name="document",
            name="types_accueil",
            field=models.ManyToManyField(blank=True, help_text="Types d'accueil concernés ; vide conserve le comportement général historique.", related_name="documents", to="animateurs.typeaccueil"),
        ),
        migrations.CreateModel(
            name="Sejour",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=160)),
                ("date_debut", models.DateField(blank=True, null=True)),
                ("date_fin", models.DateField(blank=True, null=True)),
                ("destination", models.CharField(blank=True, default="", max_length=240)),
                ("hebergement", models.CharField(blank=True, default="", max_length=240)),
                ("actif", models.BooleanField(default=True)),
                ("source_lieu_legacy", models.OneToOneField(blank=True, help_text="Lieu historique conservé pendant sa migration progressive.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sejour_migre", to="animateurs.centre")),
            ],
            options={"ordering": ("date_debut", "nom")},
        ),
        migrations.RunPython(initialiser_types_accueil, retirer_initialisation),
    ]
