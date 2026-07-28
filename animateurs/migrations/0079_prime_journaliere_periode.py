from decimal import Decimal

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("animateurs", "0078_activites_travail_complementaires")]

    operations = [
        migrations.CreateModel(
            name="PrimeJournalierePeriode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("montant", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=4, validators=[django.core.validators.MinValueValidator(Decimal("0.00")), django.core.validators.MaxValueValidator(Decimal("7.00"))])),
                ("date_modification", models.DateTimeField(auto_now=True)),
                ("animateur", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="primes_journalieres", to="animateurs.animateur")),
                ("periode", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="primes_journalieres", to="animateurs.periodescolaire")),
            ],
            options={
                "verbose_name": "prime journalière par période",
                "verbose_name_plural": "primes journalières par période",
                "ordering": ("periode__debut", "animateur__prenom", "animateur__nom"),
                "constraints": [
                    models.UniqueConstraint(fields=("animateur", "periode"), name="unique_prime_journaliere_animateur_periode"),
                    models.CheckConstraint(condition=models.Q(("montant__gte", 0), ("montant__lte", 7)), name="prime_journaliere_entre_zero_et_sept"),
                ],
            },
        ),
    ]
