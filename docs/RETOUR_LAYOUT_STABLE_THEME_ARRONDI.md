# Retour au layout stable et thème arrondi

Base utilisée : version `animation_manager_sans_fleche_actions_rapides.zip`, antérieure au layout adaptatif calculé.

## Layout

- Aucun calcul supplémentaire de largeur ou de placement n'a été ajouté.
- Les deux dispositions existantes sont conservées : rail latéral sur PC et barre basse sur portable.
- Les en-têtes fixes, les onglets, le Planning et les listes conservent leur fonctionnement antérieur.
- Les changements de cette version portent uniquement sur l'identité visuelle afin de ne pas réintroduire de chevauchements.

## Identité visuelle

- Palette bleu, vert d'eau, violet doux, ambre et rouge clair.
- Navigation identique lorsqu'elle est à gauche ou en bas.
- Cartes avec rayons de 12 à 15 px et ombres légères.
- Boutons, champs, onglets, tableaux, calendriers et fenêtres harmonisés.
- Actions rapides à nouveau accompagnées de petits repères colorés.
- Aucun dégradé ajouté dans la nouvelle couche commune.

## Centralisation

Les variables de couleur et de rayon sont centralisées dans `common-base.css`. La source de vérité du layout et des surcharges visuelles communes reste `app-layout.css`, chargé après les feuilles propres aux pages.
