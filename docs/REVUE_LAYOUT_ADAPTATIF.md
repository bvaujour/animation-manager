# Revue du layout adaptatif

## Principe retenu

Le site utilise désormais les patterns classiques d'une application métier :

- **ordinateur** : rail de navigation fixe à gauche et espace de travail à droite ;
- **portable** : navigation fixe en bas et contenu sur toute la largeur ;
- **master/detail** pour Planning et Salariés quand la largeur le permet ;
- **empilement vertical** lorsque la partie utile deviendrait trop étroite ;
- **grilles intrinsèques** avec `auto-fit` et `minmax()` pour les cartes ;
- **container queries** pour adapter le contenu d'une carte à sa largeur réelle ;
- défilement horizontal limité aux tableaux larges et à la liste d'animateurs utilisée pour le glisser-déposer.

Il n'existe que deux enveloppes de navigation : moins de 800 px et 800 px ou plus. Les composants peuvent néanmoins se réorganiser à l'intérieur de leur enveloppe lorsque leur largeur réelle devient insuffisante.

## Espaces calculés

`static/js/ui.js` mesure avec `ResizeObserver` :

- la largeur réelle du rail PC ;
- la hauteur réelle de la barre basse mobile ;
- la hauteur de l'en-tête fixe ;
- la hauteur des onglets, y compris lorsqu'ils occupent plusieurs lignes ;
- la hauteur restante réellement utilisable ;
- la largeur disponible dans Planning et Salariés.

Ces valeurs alimentent les variables CSS suivantes :

- `--layout-rail-inline` ;
- `--layout-nav-block` ;
- `--app-fixed-header-height` ;
- `--app-fixed-tabs-height` ;
- `--app-fixed-stack-height` ;
- `--layout-content-block`.

Le contenu ne dépend donc plus d'une hauteur d'en-tête ou d'une largeur de menu codée en dur.

## Adaptations automatiques

- Les onglets calculent leur nombre de colonnes et reviennent à la ligne sans scroller.
- Les en-têtes et barres d'actions restent sur une ligne tant que leur contenu tient, puis s'empilent.
- Le Planning calcule la largeur utile de la liste des animateurs. Si le calendrier restant devient trop étroit, la liste passe sous les calendriers.
- La page Salariés suit la même logique pour la liste et la fiche.
- Les cartes de tableau de bord, documents, sorties, gestion et administration utilisent des grilles fluides.
- Sur portable, les formulaires et groupes d'actions passent de haut en bas.
- La barre basse répartit toutes ses icônes sur la largeur disponible au lieu de créer un défilement horizontal.

## Fichiers modifiés

- `static/css/app-layout.css` : système de layout global final.
- `static/js/ui.js` : moteur de mesure et d'adaptation.
- `animateurs/tests/test_interface_harmonisation.py` : protections statiques du nouveau système.

Aucune règle métier, route, migration ou donnée n'a été modifiée.
