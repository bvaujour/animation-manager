# Audit initial — AM(6)

## Version de référence

Ce projet provient du fichier `AM(6).zip` fourni par l'utilisatrice.

## Règle calendrier validée

- Lundi à samedi visibles dans les calendriers.
- Dimanche masqué.
- Samedi disponible pour les affectations manuelles.
- Le remplissage automatique travaille uniquement du lundi au vendredi.
- Le remplissage automatique ne supprime pas les affectations manuelles du samedi.
- Le bouton « Vider la semaine » vide uniquement du lundi au vendredi et conserve le samedi.

## Nettoyage effectué

- Suppression de `animateurs/tests.py`, fichier vide hérité de `startapp` qui entrait en conflit avec le package `animateurs/tests/` et empêchait `python manage.py test` de découvrir tous les tests.
- Suppression des caches Python et de l'environnement de test avant livraison.

## Vérifications exécutées

- `python manage.py check`
- suite complète `python manage.py test`
- syntaxe de tous les fichiers JavaScript avec `node --check`

## Résultats

- 13 tests exécutés, 13 réussis.
- Création manuelle d'une affectation le samedi testée.
- Conservation d'une affectation du samedi lors du remplissage automatique testée.
- Conservation du samedi lors de « Vider la semaine » testée.
- Aucune affectation automatique créée le samedi ou le dimanche.

## Points à auditer ensuite

1. `planning.js` reste volumineux et concentre encore beaucoup d'état UI.
2. `views.py` reste long malgré la présence des services métier.
3. Les permissions et l'authentification des pages/API doivent être définies avant une ouverture à l'équipe.
4. Le fuseau horaire du projet est encore `UTC`; il faudra décider s'il doit passer à `Europe/Paris` après tests ciblés sur les dates.
5. Ajouter des tests navigateur pour le drag & drop FullCalendar serait la prochaine étape de stabilisation front.

## Règles du remplissage automatique renforcées

- Les centres sélectionnés sur la fiche animateur sont désormais une contrainte stricte pour le remplissage automatique.
- Les affectations manuelles restent libres et peuvent utiliser n'importe quel centre.
- Le score du solveur privilégie maintenant la continuité de l'équipe dans chaque centre sur toute la semaine.
- À remplissage égal, le solveur préfère les mêmes animateurs plusieurs jours de suite plutôt qu'une rotation importante.
- Le samedi reste visible et manuel : il n'est ni rempli ni supprimé par l'automatisation.
