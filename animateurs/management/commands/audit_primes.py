from django.core.management.base import BaseCommand

from animateurs.models import PrimeJournalierePeriode


class Command(BaseCommand):
    help = "Liste sans les modifier les primes journalières contenant des centimes."

    def handle(self, *args, **options):
        primes = [
            prime
            for prime in PrimeJournalierePeriode.objects.select_related("animateur", "periode").order_by(
                "periode__debut", "animateur__nom", "animateur__prenom"
            )
            if prime.montant != prime.montant.to_integral_value()
        ]
        if not primes:
            self.stdout.write(self.style.SUCCESS("Aucune prime décimale détectée."))
            return
        self.stdout.write(f"{len(primes)} prime(s) décimale(s) détectée(s) :")
        for prime in primes:
            self.stdout.write(
                f"- {prime.animateur} – {prime.periode.libelle_avec_annee} : "
                f"{str(prime.montant).replace('.', ',')} €"
            )
