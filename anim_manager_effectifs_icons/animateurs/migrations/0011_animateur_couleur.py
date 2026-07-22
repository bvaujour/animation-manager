from django.db import migrations, models


PALETTE = [
    "#2563EB", "#059669", "#DC2626", "#9333EA", "#EA580C",
    "#0891B2", "#65A30D", "#DB2777", "#4F46E5", "#D97706",
    "#0F766E", "#BE123C", "#7C3AED", "#0284C7", "#16A34A",
    "#C2410C", "#A21CAF", "#0369A1", "#15803D", "#B91C1C",
]


def assigner_couleurs(apps, schema_editor):
    Animateur = apps.get_model("animateurs", "Animateur")
    for index, animateur in enumerate(Animateur.objects.order_by("id")):
        if not animateur.couleur:
            animateur.couleur = PALETTE[index % len(PALETTE)]
            animateur.save(update_fields=["couleur"])


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0010_centres_affectables_sans_ordre")]

    operations = [
        migrations.AddField(
            model_name="animateur",
            name="couleur",
            field=models.CharField(blank=True, default="", help_text="Couleur hexadécimale fixe utilisée dans le planning.", max_length=7),
        ),
        migrations.RunPython(assigner_couleurs, migrations.RunPython.noop),
    ]
