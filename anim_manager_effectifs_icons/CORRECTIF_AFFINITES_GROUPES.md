# Affinité persistante entre salariés et groupes

## Objectif

Le nombre de journées déjà travaillées par un salarié dans un groupe est maintenant enregistré dans une table dédiée et utilisé par le remplissage automatique.

Un champ simple dans `Animateur` ne pouvait pas convenir, car un même salarié peut avoir une valeur différente pour chacun des groupes. La relation est donc stockée dans la table intermédiaire `AffiniteGroupeAnimateur`.

## Données enregistrées

Pour chaque couple salarié–groupe :

- le nombre de journées terminées dans le groupe ;
- le dernier jour travaillé ;
- la date de dernière synchronisation.

Une journée terminée ajoute un point. Les affectations futures et la journée en cours ne sont pas comptées comme déjà travaillées.

## Mise à jour automatique

Les scores sont recalculés lors :

- de la création, modification ou suppression d’une affectation ;
- de l’ouverture de la liste des salariés avec les affectations ;
- du lancement du remplissage automatique.

La synchronisation recalcule les valeurs depuis les affectations réelles. Elle corrige donc automatiquement un éventuel compteur incohérent.

## Utilisation par le remplissage automatique

Les contraintes et priorités sont appliquées dans cet ordre général :

1. disponibilité et absence de double affectation ;
2. lieu interdit ;
3. qualifications requises ;
4. couverture des groupes et des effectifs ;
5. lieu préféré ;
6. continuité de l’équipe pendant la semaine ;
7. score d’affinité avec le groupe ;
8. expérience globale dans le lieu et départage stable.

L’affinité ne permet donc jamais de contourner une qualification obligatoire ou un lieu interdit.

## Interface

Dans `Salariés > Affectations`, la rubrique **Affinité avec les groupes** affiche pour chaque groupe :

- le lieu ;
- le score d’affinité ;
- le nombre de journées à l’origine du score.

## Migration

La migration `0055_affinite_groupe_animateur.py` crée la table et initialise les scores à partir des affectations passées déjà enregistrées.

Commande habituelle après installation :

```bash
python manage.py migrate
```

## Validation

- 185 tests Django réussis ;
- migration testée sur une copie de la base SQLite ;
- `manage.py check` réussi ;
- aucune migration manquante ;
- Ruff réussi sur les fichiers modifiés ;
- syntaxe de tous les fichiers JavaScript validée.
