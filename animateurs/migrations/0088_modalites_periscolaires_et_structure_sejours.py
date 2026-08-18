import animateurs.models
import django.db.models.deletion
from django.db import migrations, models


MODALITES = (
    ("mercredi_journee", "Mercredi journée entière", None, None, True, 10),
    ("matin", "Accueil du matin", "07:00", "09:00", False, 20),
    ("midi", "Pause méridienne", "11:30", "14:00", False, 30),
    ("soir", "Accueil du soir", "16:00", "19:00", False, 40),
    ("aide_devoirs", "Aide aux devoirs", "16:30", "18:30", False, 50),
    ("autre", "Autre créneau configurable", None, None, False, 60),
)


def migrer_mercredis(apps, schema_editor):
    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    Modalite = apps.get_model("animateurs", "ModalitePeriscolaire")
    ancien = TypeAccueil.objects.get(code="mercredis")
    periscolaire = TypeAccueil.objects.get(code="periscolaire")
    sejours_type = TypeAccueil.objects.get(code="sejours")
    modalites = {}
    for code, nom, debut, fin, jour_entier, ordre in MODALITES:
        modalites[code], _ = Modalite.objects.update_or_create(
            code=code,
            defaults={"nom": nom, "heure_debut": debut, "heure_fin": fin, "jour_entier": jour_entier, "ordre": ordre, "actif": True},
        )
    mercredi = modalites["mercredi_journee"]

    for nom_modele in (
        "PeriodeScolaire", "EffectifEnfantsJour", "BesoinQualification", "Affectation",
        "ActiviteTravailComplementaire", "PublicationPlanning", "Sortie",
    ):
        Modele = apps.get_model("animateurs", nom_modele)
        Modele.objects.filter(type_accueil=ancien).update(type_accueil=periscolaire, modalite_periscolaire=mercredi)

    PeriodeScolaire = apps.get_model("animateurs", "PeriodeScolaire")
    for periode in PeriodeScolaire.objects.filter(modalite_periscolaire=mercredi).iterator():
        periode.modalites_periscolaires.add(mercredi)

    for nom_modele, champ in (
        ("Centre", "types_accueil"), ("Groupe", "types_accueil"), ("Evenement", "types_accueil"),
        ("Disponibilite", "types_accueil"), ("Document", "types_accueil"),
        ("ModeleEmail", "types_accueil"), ("PeriodeScolaire", "types_accueil"),
        ("PeriodeCalendrier", "types_accueil"),
    ):
        Modele = apps.get_model("animateurs", nom_modele)
        for objet in Modele.objects.filter(**{champ: ancien}).iterator():
            getattr(objet, champ).add(periscolaire)
            if nom_modele == "Evenement" and objet.modalite_periscolaire_id is None:
                objet.modalite_periscolaire = mercredi
                objet.save(update_fields=("modalite_periscolaire",))
            if nom_modele == "PeriodeScolaire":
                objet.modalites_periscolaires.add(mercredi)
            if nom_modele == "Document":
                objet.modalites_periscolaires.add(mercredi)

    Sejour = apps.get_model("animateurs", "Sejour")
    Sejour.objects.all().update(type_accueil=sejours_type)
    ancien.actif = False
    ancien.save(update_fields=("actif",))


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0087_periodes_calendrier_et_sejours")]
    operations = [
        migrations.CreateModel(
            name="ModalitePeriscolaire",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=40, unique=True)), ("nom", models.CharField(max_length=100)),
                ("heure_debut", models.TimeField(blank=True, null=True)), ("heure_fin", models.TimeField(blank=True, null=True)),
                ("jour_entier", models.BooleanField(default=False)), ("actif", models.BooleanField(default=True)),
                ("ordre", models.PositiveSmallIntegerField(default=0)),
            ], options={"ordering": ("ordre", "nom")},
        ),
        *[
            migrations.AddField(model_name=modele, name="modalite_periscolaire", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name=related, to="animateurs.modaliteperiscolaire"))
            for modele, related in (
                ("evenement", "groupes_accueil"), ("effectifenfantsjour", "effectifs"),
                ("besoinqualification", "besoins"), ("periodescolaire", "periodes_travail"),
                ("affectation", "affectations"), ("activitetravailcomplementaire", "activites_travail"),
                ("publicationplanning", "publications"), ("sortie", "sorties"),
            )
        ],
        migrations.AddField(model_name="document", name="modalites_periscolaires", field=models.ManyToManyField(blank=True, related_name="documents", to="animateurs.modaliteperiscolaire")),
        migrations.AddField(model_name="periodescolaire", name="modalites_periscolaires", field=models.ManyToManyField(blank=True, related_name="semaines_reference", to="animateurs.modaliteperiscolaire")),
        migrations.AddField(model_name="sejour", name="type_accueil", field=models.ForeignKey(default=animateurs.models.type_accueil_sejours_par_defaut, on_delete=django.db.models.deletion.PROTECT, related_name="sejours_structures", to="animateurs.typeaccueil")),
        migrations.AddField(model_name="sejour", name="responsable", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sejours_responsable", to="animateurs.animateur")),
        migrations.AddField(model_name="sejour", name="documents", field=models.ManyToManyField(blank=True, related_name="sejours", to="animateurs.document")),
        migrations.CreateModel(
            name="ParticipantSejour",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("prenom", models.CharField(max_length=100)), ("nom", models.CharField(max_length=100)),
                ("date_naissance", models.DateField(blank=True, null=True)),
                ("sejour", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participants", to="animateurs.sejour")),
            ], options={"ordering": ("nom", "prenom")},
        ),
        migrations.RunPython(migrer_mercredis, migrations.RunPython.noop),
    ]
