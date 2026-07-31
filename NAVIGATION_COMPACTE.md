# Navigation compacte

La navigation globale a été réduite et sécurisée dans les deux layouts.

- Ordinateur : rail fixe de 42 px, icônes de 34 px, avec une réserve de contenu exactement égale à 42 px.
- Téléphone : barre basse de 48 px, icônes seules dans des zones tactiles de 44 px.
- La zone de sécurité inférieure des téléphones est conservée.
- Le `padding-bottom` du contenu correspond à la hauteur réelle de la barre.
- Les boutons flottants, notifications et indicateurs de chargement sont automatiquement positionnés au-dessus de la navigation.
- Les libellés restent accessibles avec `aria-label` et `title`, sans augmenter la hauteur de la barre mobile.
