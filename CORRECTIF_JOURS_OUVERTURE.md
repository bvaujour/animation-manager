# Correctif – sélection des jours d’ouverture

Le bandeau blanc provenait du masquage des cases à cocher avec `position:absolute` sans cadre de positionnement fiable. Selon le navigateur et la mise en page du formulaire, la case invisible pouvait recevoir le focus hors de son bouton visuel et provoquer un recouvrement ou un déplacement de la page.

Les cases des jours utilisent maintenant une technique de masquage accessible limitée à 1 px, tandis que le bouton visible reste dans le flux normal. Le focus clavier est toujours affiché sur le bouton du jour.

Le numéro de version de `gestion.css` a également été changé dans les pages Gestion et Planning afin d’éviter le cache navigateur.
