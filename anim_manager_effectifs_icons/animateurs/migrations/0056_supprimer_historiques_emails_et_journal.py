from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0055_affinite_groupe_animateur")]

    operations = [
        migrations.DeleteModel(name="DestinataireEnvoiEmail"),
        migrations.DeleteModel(name="EnvoiEmail"),
        migrations.DeleteModel(name="JournalAudit"),
    ]
