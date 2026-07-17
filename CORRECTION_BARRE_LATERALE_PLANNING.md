# Correction de la barre latérale du Planning

La liste des salariés est désormais réellement placée dans une colonne à gauche du planning sur les écrans d'au moins 1024 px.

## Cause du problème

Un ancien correctif CSS situé plus bas dans `planning.css` imposait encore `display: flex` et `flex-direction: column` avec `!important` sur le conteneur principal. Il annulait donc la grille en deux colonnes.

## Correction

- surcharge finale avec un sélecteur plus précis ;
- vraie grille à trois colonnes : liste, poignée de redimensionnement, planning ;
- largeur de la liste comprise entre 220 et 450 px ;
- liste verticale avec défilement indépendant ;
- planning occupant toute la largeur restante ;
- retour automatique à l'affichage vertical sous 1024 px.

Aucune migration n'est nécessaire.
