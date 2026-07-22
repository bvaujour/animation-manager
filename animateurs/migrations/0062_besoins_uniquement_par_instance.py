from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("animateurs", "0061_diplomes_auto_par_defaut"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="groupe",
            name="qualifications_requises",
        ),
        migrations.DeleteModel(
            name="BesoinQualificationGroupe",
        ),
    ]
