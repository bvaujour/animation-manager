# Planning — colonne latérale optimisée

## Modifications

- Sur ordinateur (largeur à partir de 1024 px), la liste des salariés est une vraie colonne à gauche du planning.
- Le planning occupe toute la largeur restante à droite.
- La colonne mesure 280 px par défaut et peut être redimensionnée entre 220 et 450 px avec la poignée verticale.
- La largeur choisie est mémorisée dans le navigateur.
- La liste défile verticalement sans déplacer le planning.
- Un champ de recherche compact permet de filtrer par prénom, nom, email ou téléphone.
- Un compteur indique le nombre de salariés visibles.
- Les marges, espacements et bandeaux ont été resserrés afin de maximiser la surface des calendriers.
- Sous 1024 px, l'affichage reste adapté aux petits écrans et la liste repasse au-dessus.

## Vérifications

- `python manage.py check` : aucune erreur.
- `python manage.py test --noinput` : 91 tests réussis.
- `node --check static/js/planning.js` : syntaxe JavaScript valide.
- Aucune migration de base de données nécessaire.
