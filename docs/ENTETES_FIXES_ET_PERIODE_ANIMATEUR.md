# En-têtes fixes et période du tableau de bord animateur

## Modifications

- La navigation de semaine du tableau de bord animateur est intégrée dans son en-tête.
- Tous les véritables en-têtes de page sont désormais fixés au viewport et ne défilent plus avec le contenu.
- Leur hauteur est mesurée dynamiquement par `static/js/ui.js` puis réservée sur le `body`, afin qu'aucun contenu ne soit recouvert.
- Sur PC, l'en-tête commence à droite du rail latéral.
- Sur téléphone, il occupe toute la largeur, au-dessus du contenu et de la navigation basse.
- Les pages Planning et Salariés, qui utilisent une hauteur verrouillée, tiennent compte de la hauteur réelle de l'en-tête.

## Fichiers modifiés

- `templates/accueil.html`
- `static/css/app-layout.css`
- `static/js/ui.js`
