from django.db import migrations, models


class Migration(migrations.Migration):
    """Ajoute les contraintes après la migration de données 0108.

    PostgreSQL refuse de créer les index de ces contraintes dans la même
    transaction que les nombreux UPDATE/INSERT de 0108 lorsque des événements
    de triggers sont encore en attente. Le découpage en deux migrations force
    un COMMIT entre la conversion des données et la création des index.
    """

    dependencies = [("animateurs", "0108_groupes_par_accueil")]

    operations = [
        migrations.AddConstraint(
            model_name="evenement",
            constraint=models.UniqueConstraint(
                condition=models.Q(("accueil_centre__isnull", False)),
                fields=("accueil_centre", "groupe"),
                name="unique_instance_groupe_par_accueil",
            ),
        ),
        migrations.AddConstraint(
            model_name="evenement",
            constraint=models.UniqueConstraint(
                condition=models.Q(("accueil_centre__isnull", True)),
                fields=("centre", "groupe"),
                name="unique_instance_groupe_legacy_par_lieu",
            ),
        ),
    ]
