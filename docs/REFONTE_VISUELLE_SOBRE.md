# Refonte visuelle sobre

## Direction graphique

Le site utilise désormais une identité volontairement neutre et uniforme :

- fond gris très clair ;
- surfaces blanches ;
- bleu ardoise comme unique couleur d'interface ;
- vert, ambre et rouge réservés aux états fonctionnels ;
- aucun dégradé dans la feuille visuelle finale ;
- presque aucune ombre ;
- coins peu arrondis ;
- typographie système simple ;
- cartes compactes, dimensionnées par leur contenu.

## Deux layouts seulement

- **PC : 800 px et plus** — rail sombre fixe à gauche.
- **Portable : moins de 800 px** — le même rail, avec la même couleur, devient une barre basse.

Il n'existe aucun mode tablette intermédiaire.

## Composants harmonisés

La feuille `static/css/app-layout.css`, chargée après tous les styles de page, fixe l'apparence commune de :

- la navigation ;
- tous les en-têtes de page ;
- cartes et sections ;
- boutons, champs et badges ;
- onglets ;
- tableaux et listes ;
- modales ;
- tableau de bord direction ;
- tableau de bord animateur ;
- calendriers ;
- documents ;
- gestion, salariés, sorties et administration ;
- page de connexion.

Les feuilles propres à chaque page continuent de gérer leurs détails fonctionnels. Elles ne décident plus de l'identité générale.

## Fichiers modifiés

- `static/css/common-base.css` : palette, typographie et variables communes.
- `static/css/app-layout.css` : nouveau système visuel et les deux layouts PC/portable.
- `docs/REFONTE_VISUELLE_SOBRE.md` : description du système.

Aucune vue, route, migration, donnée ou fonctionnalité métier n'a été modifiée.
