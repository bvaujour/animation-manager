# Récapitulatif — sélection de plusieurs périodes

## Nouveau fonctionnement

Le récapitulatif ne demande plus de saisir manuellement une date de début et une date de fin.

Il utilise désormais un menu déroulant alimenté par les périodes enregistrées dans **Gestion > Périodes**.

- Plusieurs périodes peuvent être cochées en même temps.
- Les périodes sont regroupées par année scolaire et par zone.
- Les actions « Tout sélectionner » et « Tout désélectionner » sont disponibles.
- Le bouton « Afficher » recalcule le récapitulatif uniquement sur les semaines cochées.
- Des semaines discontinues peuvent être sélectionnées : les jours intermédiaires ne sont pas intégrés aux calculs.
- Par défaut, la semaine en cours est sélectionnée ; sinon la prochaine période enregistrée est choisie.

## API

L'API accepte maintenant :

```
/api/recapitulatif/?periode_ids=12,13,18
```

L'ancien fonctionnement `debut` / `fin` reste accepté pour compatibilité interne.

## Base de données

Aucune migration n'est nécessaire.

## Vérifications

- suite complète de tests Django validée ;
- cas de plusieurs périodes discontinues testé ;
- période inconnue refusée ;
- aucune migration manquante ;
- syntaxe JavaScript validée.
