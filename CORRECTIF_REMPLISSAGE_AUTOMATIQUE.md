# Nouveau remplissage automatique

## Logique reconstruite

L'ancien solveur par combinaisons a été supprimé. Le remplissage fonctionne désormais journée par journée avec une affectation à capacité maximale.

Chaque journée comporte deux passages :

1. placer une première personne dans le maximum de groupes ouverts ;
2. compléter ensuite chaque groupe jusqu'au nombre d'animateurs enregistré dans `effectif_cible`.

Cette méthode garantit que le solveur ne concentre plus toute l'équipe dans quelques groupes lorsqu'il est possible de couvrir les autres.

## Contraintes et priorités

Les seules interdictions strictes sont :

- l'animateur n'est pas disponible ce jour-là ;
- l'animateur est déjà affecté ce jour-là ;
- le lieu est explicitement marqué comme interdit.

Un lieu sans préférence particulière reste autorisé. Les anciennes relations neutres ne forment plus une liste blanche.

Parmi les affectations possibles, le solveur favorise dans cet ordre :

1. le lieu préféré ;
2. le maintien dans le même groupe que les jours précédents de la semaine ;
3. le nombre de jours déjà réalisés dans ce groupe au cours de la semaine ;
4. l'expérience historique de l'animateur dans ce groupe ;
5. la continuité dans le même lieu.

Les qualifications enregistrées et l'ancien champ « groupe préféré » ne bloquent plus le remplissage automatique.

## Historique par groupe dans la fiche salarié

La rubrique **Salariés > Affectations** affiche maintenant « Jours travaillés par groupe ».

Le nombre est calculé automatiquement depuis les affectations passées. Il n'y a pas de double saisie ni de nouveau compteur à maintenir manuellement. Cet historique est utilisé lors des prochains remplissages automatiques pour privilégier les personnes qui connaissent déjà le groupe.

## Validation

- 175 tests Django réussis ;
- aucun changement de migration ;
- contrôle Django réussi ;
- syntaxe de tous les fichiers Python et JavaScript vérifiée ;
- contrôle de structure des feuilles CSS réussi.
