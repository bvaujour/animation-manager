# Generated manually for animateurs app on 2026-07-06

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('animateurs', '0005_centre_affectation_preferencecentre'),
    ]

    operations = [
        migrations.CreateModel(
            name='Disponibilite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('debut', models.DateField(help_text='Premier jour de disponibilité')),
                ('fin', models.DateField(help_text='Dernier jour de disponibilité (inclus)')),
                ('animateur', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='disponibilites', to='animateurs.animateur')),
            ],
            options={
                'ordering': ['debut'],
            },
        ),
        migrations.AddConstraint(
            model_name='disponibilite',
            constraint=models.CheckConstraint(condition=models.Q(('fin__gte', models.F('debut'))), name='dispo_fin_apres_debut'),
        ),
    ]
