# Correctif Planning – colonne Effectifs enfants

Le conteneur principal du Planning conservait sa grille à trois colonnes en mode Effectifs enfants. Les sélecteurs précédents utilisaient `body > main#layout`, alors que le template place le contenu dans un conteneur intermédiaire. La règle ne pouvait donc pas correspondre.

Le correctif :

- cible réellement `main#layout` dans la structure de la page ;
- remplace la grille par une seule colonne en mode Effectifs ;
- masque la liste des animateurs et sa poignée de redimensionnement ;
- place `#calendars-section` sur toute la largeur ;
- remet sa marge gauche à zéro ;
- utilise aussi l'attribut `data-planning-mode="effectifs"` pour sécuriser le changement de mode ;
- modifie la version du CSS afin d'éviter l'ancien fichier en cache.
