from django.db import migrations


NOM_TECHNIQUE = "__animateurs_flottants__"
CLE_TECHNIQUE = "animateurs flottants"


def convertir_anciens_flottants(apps, schema_editor):
    """Déplace les anciennes lignes booléennes vers le groupe technique."""
    Affectation = apps.get_model("animateurs", "Affectation")
    Evenement = apps.get_model("animateurs", "Evenement")
    Groupe = apps.get_model("animateurs", "Groupe")

    centres_ids = list(
        Affectation.objects.filter(est_flottant=True)
        .values_list("centre_id", flat=True)
        .distinct()
    )
    if not centres_ids:
        return

    groupe, _ = Groupe.objects.get_or_create(
        cle_unique=CLE_TECHNIQUE,
        defaults={
            "nom": NOM_TECHNIQUE,
            "enfants_par_animateur_defaut": 1,
        },
    )

    for centre_id in centres_ids:
        evenement, _ = Evenement.objects.get_or_create(
            centre_id=centre_id,
            groupe_id=groupe.id,
            defaults={
                "nom": NOM_TECHNIQUE,
                "cle_unique": CLE_TECHNIQUE,
                "permanent": True,
                "ferme_jours_feries": False,
                "effectif_cible": 1,
                "enfants_par_animateur_defaut": 1,
                "jours_ouverts": [0, 1, 2, 3, 4, 5, 6],
                "ordre": 65535,
            },
        )
        Affectation.objects.filter(
            centre_id=centre_id,
            est_flottant=True,
        ).update(evenement_id=evenement.id)


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0067_affectation_est_flottant")]

    operations = [
        migrations.RunPython(convertir_anciens_flottants, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="affectation",
            name="est_flottant",
        ),
    ]
