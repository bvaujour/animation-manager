from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0074_transport_sortie_structure")]

    operations = [
        migrations.AddField(model_name="centre", name="adresse", field=models.CharField(blank=True, default="", max_length=240)),
        migrations.AddField(model_name="centre", name="code_postal", field=models.CharField(blank=True, default="", max_length=5, validators=[RegexValidator(message="Le code postal doit contenir exactement 5 chiffres.", regex="^\\d{5}$")])),
        migrations.AddField(model_name="centre", name="commune", field=models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField(model_name="centre", name="latitude", field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField(model_name="centre", name="longitude", field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField(model_name="sortie", name="destination_adresse", field=models.CharField(blank=True, default="", max_length=240)),
        migrations.AddField(model_name="sortie", name="destination_code_postal", field=models.CharField(blank=True, default="", max_length=5, validators=[RegexValidator(message="Le code postal doit contenir exactement 5 chiffres.", regex="^\\d{5}$")])),
        migrations.AddField(model_name="sortie", name="destination_commune", field=models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField(model_name="sortie", name="destination_latitude", field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField(model_name="sortie", name="destination_longitude", field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField(model_name="sortie", name="source_heure_arrivee", field=models.CharField(blank=True, choices=[("automatique", "Estimation automatique"), ("manuelle", "Heure ajustée manuellement")], default="", max_length=12)),
        migrations.AddField(model_name="sortie", name="source_heure_arrivee_retour", field=models.CharField(blank=True, choices=[("automatique", "Estimation automatique"), ("manuelle", "Heure ajustée manuellement")], default="", max_length=12)),
        migrations.AddField(model_name="sortie", name="temps_arret_par_site", field=models.PositiveSmallIntegerField(default=10, validators=[MinValueValidator(0), MaxValueValidator(60)])),
    ]
