from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0090_formation")]

    operations = [
        migrations.AddField(
            model_name="formation",
            name="email_contact",
            field=models.EmailField(blank=True, max_length=254, verbose_name="e-mail du contact"),
        ),
        migrations.AddField(
            model_name="formation",
            name="telephone_contact",
            field=models.CharField(blank=True, max_length=40, verbose_name="téléphone du contact"),
        ),
        migrations.AddField(
            model_name="formation",
            name="hebergement",
            field=models.CharField(blank=True, choices=[("internat", "Internat"), ("externat", "Externat")], max_length=12),
        ),
        migrations.AddField(
            model_name="formation",
            name="qualification_libre",
            field=models.CharField(blank=True, max_length=180, verbose_name="autre qualification / qualification libre"),
        ),
        migrations.AddField(
            model_name="formation",
            name="documents",
            field=models.ManyToManyField(blank=True, help_text="Documents existants de la bibliothèque liés à cette formation.", related_name="formations", to="animateurs.document"),
        ),
    ]
