# Revue interface : cartes et layouts

## Règle de responsive

L'application utilise désormais deux layouts seulement :

- **Ordinateur (`>= 800 px`)** : rail fixe de 42 px à gauche, contenu décalé de la même largeur.
- **Portable (`< 800 px`)** : navigation fixe de 48 px en bas, contenu sur toute la largeur avec la hauteur de navigation réservée.

Il n'existe plus de variante intermédiaire dans la couche finale du layout.

## Navigation

Les couleurs sont identiques dans les deux modes :

- fond bleu nuit ;
- icônes claires ;
- survol bleu plus clair ;
- page active orange.

Le passage du rail latéral à la barre basse ne change donc plus le thème.

## Cartes

Les cartes d'information communes ont été harmonisées :

- padding réduit ;
- bordure, rayon et ombre communs ;
- titres plus courts et mieux hiérarchisés ;
- métadonnées discrètes ;
- actions placées sur une ligne séparée ;
- badges compacts ;
- tuiles de statistiques moins hautes ;
- cartes documents structurées en icône, contenu puis actions.

Sur portable, les cartes d'information passent sur une colonne. Les documents restent sur deux petites colonnes, puis une seule sous 360 px.

## Centralisation

Toutes les règles finales sont regroupées à la fin de `static/css/app-layout.css`, qui reste la source de vérité du layout global.

## Correction annexe

`api_publication_planning` a été ajouté à `animateurs.views.__all__`, car la route l'utilisait déjà mais l'audit de façade signalait son absence.
