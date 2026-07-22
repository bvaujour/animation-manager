from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("animateurs", "0052_effectifenfantsjour_ratio_exceptionnel")]
    operations = [
        migrations.RemoveConstraint(model_name="preferencecentre", name="unique_centre_prefere_par_animateur"),
        migrations.AddField(model_name="preferencecentre", name="est_interdit", field=models.BooleanField(default=False, help_text="Centre dans lequel cet animateur ne doit jamais être affecté.")),
    ]
