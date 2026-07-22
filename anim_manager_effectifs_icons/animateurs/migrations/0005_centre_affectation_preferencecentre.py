# Generated manually for animateurs app on 2026-07-06

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('animateurs', '0004_qualification_animateur_qualifications'),
    ]

    operations = [
        migrations.CreateModel(
            name='Centre',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nom', models.CharField(max_length=100)),
                ('code', models.CharField(help_text='Abréviation courte affichée dans les badges, ex: PAC', max_length=10, unique=True)),
                ('couleur', models.CharField(default='#e03c00', help_text='Couleur hexadécimale utilisée pour les badges, ex: #e03c00', max_length=7)),
            ],
            options={
                'ordering': ['nom'],
            },
        ),
        migrations.CreateModel(
            name='Affectation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('debut', models.DateTimeField()),
                ('fin', models.DateTimeField()),
                ('animateur', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='affectations', to='animateurs.animateur')),
                ('centre', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='affectations', to='animateurs.centre')),
            ],
            options={
                'ordering': ['debut'],
            },
        ),
        migrations.CreateModel(
            name='PreferenceCentre',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ordre', models.PositiveSmallIntegerField(help_text='1 = centre préféré')),
                ('animateur', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='preferences', to='animateurs.animateur')),
                ('centre', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='preferences', to='animateurs.centre')),
            ],
            options={
                'ordering': ['ordre'],
            },
        ),
        migrations.AddConstraint(
            model_name='preferencecentre',
            constraint=models.UniqueConstraint(fields=('animateur', 'centre'), name='unique_animateur_centre'),
        ),
        migrations.AddConstraint(
            model_name='preferencecentre',
            constraint=models.UniqueConstraint(fields=('animateur', 'ordre'), name='unique_animateur_ordre'),
        ),
    ]
