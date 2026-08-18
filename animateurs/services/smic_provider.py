"""Abstraction de synchronisation SMIC.

Aucun endpoint n'est codé tant qu'une API officielle, stable et son schéma
n'ont pas été validés. La saisie locale reste donc la source opérationnelle.
"""


class SMICProviderIndisponible(RuntimeError):
    pass


class SMICProvider:
    disponible = False
    libelle = "Source officielle non configurée"

    def recuperer(self):
        raise SMICProviderIndisponible(
            "La synchronisation officielle n'est pas configurée. Ajoutez les références manuellement."
        )


def get_smic_provider():
    return SMICProvider()
