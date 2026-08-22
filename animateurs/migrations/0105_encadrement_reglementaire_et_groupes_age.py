import unicodedata

from django.db import migrations, models


def _cle(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()


def initialiser_encadrement(apps, schema_editor):
    Groupe = apps.get_model("animateurs", "Groupe")
    Evenement = apps.get_model("animateurs", "Evenement")
    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    BesoinEncadrement = apps.get_model("animateurs", "BesoinEncadrement")
    BesoinQualification = apps.get_model("animateurs", "BesoinQualification")

    for groupe in Groupe.objects.all().iterator():
        cle = _cle(groupe.nom)
        if "maternel" in cle or "3 5" in cle or "3-5" in cle or "3 6" in cle or "3-6" in cle:
            groupe.categorie_age_reglementaire = "moins_6"
        elif "elementair" in cle or "6 10" in cle or "6-10" in cle or "6 11" in cle or "6-11" in cle:
            groupe.categorie_age_reglementaire = "six_plus"
        else:
            groupe.categorie_age_reglementaire = "autre"
        groupe.save(update_fields=["categorie_age_reglementaire"])

    vacances = TypeAccueil.objects.filter(code="vacances").first()
    if vacances:
        for evenement in Evenement.objects.select_related("groupe").all().iterator():
            if evenement.groupe_id and "animateurs_flottants" in _cle(evenement.groupe.nom):
                continue
            BesoinEncadrement.objects.get_or_create(
                evenement_id=evenement.id,
                type_accueil_id=vacances.id,
                modalite_periscolaire_id=None,
                periode_calendrier_id=None,
                defaults={
                    "effectif_cible": max(1, int(evenement.effectif_cible or 1)),
                    "mode_calcul": "manuel",
                    "renforts_souhaites": 0,
                },
            )
            generiques = BesoinQualification.objects.filter(
                evenement_id=evenement.id,
                type_accueil_id=None,
                modalite_periscolaire_id=None,
                periode_calendrier_id=None,
            )
            for besoin in generiques.iterator():
                BesoinQualification.objects.get_or_create(
                    evenement_id=evenement.id,
                    qualification_id=besoin.qualification_id,
                    type_accueil_id=vacances.id,
                    modalite_periscolaire_id=None,
                    periode_calendrier_id=None,
                    defaults={"nombre_minimum": besoin.nombre_minimum},
                )


class Migration(migrations.Migration):
    dependencies = [
        ("animateurs", "0104_besoins_encadrement_contextuels"),
    ]

    operations = [
        migrations.AddField(
            model_name="groupe",
            name="categorie_age_reglementaire",
            field=models.CharField(
                choices=[
                    ("moins_6", "Moins de 6 ans"),
                    ("six_plus", "6 ans et plus"),
                    ("autre", "Autre / non réglementaire"),
                ],
                default="autre",
                help_text="Utilisée pour calculer automatiquement les taux d'encadrement.",
                max_length=20,
                verbose_name="catégorie d'âge réglementaire",
            ),
        ),
        migrations.AddField(
            model_name="besoinencadrement",
            name="mode_calcul",
            field=models.CharField(
                choices=[
                    ("manuel", "Nombre de postes défini manuellement"),
                    ("reglementaire", "Calcul automatique selon les effectifs"),
                ],
                default="manuel",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="besoinencadrement",
            name="effectif_enfants_reference",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Utilisée pour préparer le planning lorsque l'effectif réel n'est pas encore saisi.",
                null=True,
                verbose_name="fréquentation de référence",
            ),
        ),
        migrations.AddField(
            model_name="besoinencadrement",
            name="renforts_souhaites",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Postes opérationnels ajoutés au-delà du minimum réglementaire.",
                verbose_name="renforts souhaités",
            ),
        ),
        migrations.AddField(model_name="parametresstructure", name="pedt_actif", field=models.BooleanField(default=False, verbose_name="PEDT applicable au périscolaire")),
        migrations.AddField(model_name="parametresstructure", name="ratio_vacances_moins_6", field=models.PositiveSmallIntegerField(default=8)),
        migrations.AddField(model_name="parametresstructure", name="ratio_vacances_6_plus", field=models.PositiveSmallIntegerField(default=12)),
        migrations.AddField(model_name="parametresstructure", name="ratio_periscolaire_court_moins_6", field=models.PositiveSmallIntegerField(default=10)),
        migrations.AddField(model_name="parametresstructure", name="ratio_periscolaire_court_6_plus", field=models.PositiveSmallIntegerField(default=14)),
        migrations.AddField(model_name="parametresstructure", name="ratio_periscolaire_long_moins_6", field=models.PositiveSmallIntegerField(default=8)),
        migrations.AddField(model_name="parametresstructure", name="ratio_periscolaire_long_6_plus", field=models.PositiveSmallIntegerField(default=12)),
        migrations.AddField(model_name="parametresstructure", name="ratio_periscolaire_pedt_court_moins_6", field=models.PositiveSmallIntegerField(default=14)),
        migrations.AddField(model_name="parametresstructure", name="ratio_periscolaire_pedt_court_6_plus", field=models.PositiveSmallIntegerField(default=18)),
        migrations.AddField(model_name="parametresstructure", name="ratio_periscolaire_pedt_long_moins_6", field=models.PositiveSmallIntegerField(default=10)),
        migrations.AddField(model_name="parametresstructure", name="ratio_periscolaire_pedt_long_6_plus", field=models.PositiveSmallIntegerField(default=14)),
        migrations.AddField(model_name="parametresstructure", name="pourcentage_qualifies_minimum", field=models.PositiveSmallIntegerField(default=50)),
        migrations.AddField(model_name="parametresstructure", name="pourcentage_non_qualifies_maximum", field=models.PositiveSmallIntegerField(default=20)),
        migrations.RunPython(initialiser_encadrement, migrations.RunPython.noop),
    ]
