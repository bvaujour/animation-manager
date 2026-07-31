# Optimisation des performances

## Page Temps de travail

La route `/api/temps-travail/` ne lance plus le générateur complet du récapitulatif de paie.
La synthèse affichée par cette page est calculée directement à partir :

- des dates d'affectation déjà chargées ;
- des participations aux réunions préchargées ;
- des journées de préparation préchargées.

Les conflits d'affectation de toutes les réunions sont désormais récupérés par une seule requête, au lieu d'une requête supplémentaire par réunion.

Les périodes et les participations sont préchargées avec `Prefetch(..., to_attr=...)`, puis réutilisées en mémoire sans nouveaux accès à la base.

## Effet attendu

Le nombre de requêtes ne dépend plus du nombre de réunions. Le calcul évite également de reconstruire le détail complet des centres, des jours et de la paie, informations qui ne sont pas nécessaires pour cette page.

Aucun format JSON exposé à l'interface n'a été modifié.
