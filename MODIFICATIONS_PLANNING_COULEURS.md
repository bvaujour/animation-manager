# Planning latéral et couleurs des salariés

## Planning sur ordinateur

- À partir de 1024 px de largeur, la liste des salariés est affichée dans une colonne à gauche du planning.
- La colonne défile verticalement indépendamment du planning.
- Sur tablette et mobile, la liste conserve son affichage horizontal au-dessus des calendriers.
- La mention « Classés par prénom » a été supprimée.

## Couleurs des salariés

- Lors de la création d’un salarié, une couleur est choisie aléatoirement dans une palette de 12 couleurs.
- La fiche permet de choisir directement une couleur dans cette palette.
- Le sélecteur de couleur libre reste disponible.
- Un bouton « Aléatoire » permet de tirer une nouvelle couleur.
- L’API attribue également une couleur aléatoire si une création est envoyée sans couleur.

## Vérifications

- `python manage.py check` : OK
- `python manage.py makemigrations --check --dry-run` : aucune migration nécessaire
- 91 tests Django : OK
- Syntaxe JavaScript : OK
