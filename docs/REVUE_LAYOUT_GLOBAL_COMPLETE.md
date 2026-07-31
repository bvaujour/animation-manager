# Revue globale du layout

## Objectif

Supprimer les pertes de largeur et les comportements contradictoires entre les pages, en conservant seulement deux mises en page :

- **PC : largeur à partir de 800 px**, rail fixe de 42 px à gauche ;
- **Portable : largeur inférieure à 800 px**, navigation fixe de 48 px en bas.

## Corrections principales

### Tableau de bord animateur

- Suppression des limites de largeur à 1 280, 1 440 et 1 540 px qui se cumulaient selon les feuilles CSS.
- Le tableau de bord et le bloc `Mon planning` utilisent maintenant toute la largeur restante.
- Les conteneurs des centres, groupes, calendriers et FullCalendar sont forcés à `width: 100%` avec `min-width: 0`.
- Sur portable, les calendriers sont sur une seule colonne et occupent toute la largeur entre les gouttières de 4 px.
- Sur PC, les calendriers utilisent une grille adaptative sans laisser de colonne vide.

### Toutes les pages

- Les pages riches en données ne sont plus limitées par d'anciens `max-width`.
- Les grilles et leurs enfants ont tous `min-width: 0`, ce qui évite qu'une carte réduise artificiellement la largeur disponible.
- Les cartes gardent leur hauteur naturelle et ne s'étirent plus pour remplir une ligne.
- Les en-têtes internes, badges et zones d'actions ont été resserrés de façon commune.
- Les cartes Documents utilisent une structure stable : icône, informations, puis actions sur une ligne séparée.

### Planning direction

- L'en-tête, les onglets, le planning et la page Temps de travail utilisent les mêmes gouttières.
- Le calendrier occupe tout l'espace restant à droite de la liste des animateurs sur PC.
- Sur portable, la zone des calendriers occupe toute la largeur et la liste des animateurs reste en dessous.
- Aucun padding hérité n'est conservé sur la grille principale du planning mobile.

### Tableau de bord direction

- Les cartes État des centres restent compactes.
- Les blocs du tableau de bord conservent leur hauteur propre.
- Les grilles utilisent toute la largeur disponible.

## Centralisation

La partie finale de `static/css/app-layout.css` a été remplacée par une seule couche autoritaire appelée **INTÉGRITÉ DU LAYOUT**. Elle centralise :

- la navigation PC et portable ;
- les largeurs racines des pages ;
- les grilles et cartes communes ;
- les calendriers ;
- les deux uniques seuils responsive.

Les anciens seuils `max-width: 800px` et `max-width: 359px` ont été supprimés. Il n'existe plus de chevauchement à 800 px.

## Fichiers modifiés

- `static/css/app-layout.css`
- `static/css/animateur-dashboard.css`
- `static/css/style.css`
- `static/css/calendars.css`
- `animateurs/tests/test_interface_harmonisation.py`

## Contrôles

- syntaxe de tous les fichiers Python : validée ;
- syntaxe de tous les fichiers JavaScript : validée ;
- structure des feuilles CSS : validée ;
- audit statique du projet : validé ;
- tests ajoutés pour protéger les deux layouts et la largeur du calendrier animateur.

Les tests Django complets n'ont pas pu être exécutés dans l'environnement de préparation, car Django 5.2.15 n'y est pas disponible.
