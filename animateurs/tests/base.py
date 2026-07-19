"""Base commune pour les tests qui appellent des pages ou l'API en tant que
direction.

Depuis l'ajout de ``ConnexionObligatoireMiddleware``, toute requête non
authentifiée est redirigée vers la connexion (302) et les comptes sans rôle
adéquat sont refusés (403). La très grande majorité des tests HTTP existants
supposaient un accès libre : ils vérifient une logique métier (planning,
groupes, disponibilités…) sans se soucier de l'authentification.

Plutôt que d'ajouter un ``force_login`` dans chaque ``setUp`` — fragile et
répétitif — cette base connecte automatiquement un **compte maître**
(superutilisateur) avant chaque test. Un compte maître traverse le middleware
sans dépendre d'une fiche salarié et a accès à toutes les pages de direction,
ce qui correspond exactement au contexte que ces tests présupposent.

L'authentification est posée dans ``_pre_setup``, le hook que Django appelle
juste après la création de ``self.client`` et juste avant le ``setUp`` de la
sous-classe. Résultat : les ``setUp`` métier existants n'ont pas besoin d'être
modifiés ni d'appeler ``super().setUp()``. Ils tournent déjà authentifiés.

À NE PAS utiliser pour :
- les tests qui vérifient le comportement de l'authentification elle-même
  (redirections, refus des comptes orphelins, rôles) : ils gèrent leur propre
  connexion et doivent partir d'un client anonyme ;
- les tests de services purs qui n'utilisent pas ``self.client`` : hériter de
  cette base est inutile (mais inoffensif).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase


class ConnexionTestCase(TestCase):
    """``TestCase`` dont le client est déjà connecté en compte maître.

    Le superutilisateur est recréé pour chaque test (dans la transaction de
    test, donc annulé automatiquement à la fin). Les sous-classes accèdent au
    compte via ``self.compte_maitre`` si elles en ont besoin.
    """

    def _pre_setup(self):
        super()._pre_setup()
        self.compte_maitre = get_user_model().objects.create_superuser(
            username="maitre-test",
            email="maitre-test@example.com",
            password="secret-test",
        )
        self.client.force_login(self.compte_maitre)
