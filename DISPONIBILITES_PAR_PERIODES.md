# Disponibilités par périodes enregistrées

La saisie manuelle par dates a été remplacée dans la fiche salarié.

## Fonctionnement

- Les périodes proviennent uniquement de la bibliothèque **Périodes**.
- Une période cochée sélectionne tous ses jours par défaut.
- Le détail se déplie pour décocher les journées d'indisponibilité.
- Un compteur indique le nombre de journées disponibles.
- Décocher entièrement une période supprime les disponibilités correspondantes.
- Un jour extérieur aux périodes enregistrées est refusé par l'API.

## Stockage

Aucune nouvelle table n'est nécessaire. Les jours cochés sont convertis en plages
contiguës dans la table existante `Disponibilite`, ce qui conserve la compatibilité
avec le planning, le remplissage automatique et le récapitulatif.

## Vérifications

- 89 tests Django réussis ;
- aucune erreur `manage.py check` ;
- aucune migration manquante ;
- syntaxe JavaScript validée.
