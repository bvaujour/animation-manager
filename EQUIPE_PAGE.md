# Page Équipe

La gestion des animateurs est désormais séparée de la page Gestion.

## Pages

- `/equipe/` : animateurs, fiche complète et disponibilités.
- `/gestion/` : centres et qualifications uniquement.

## Fonctionnalités de la fiche

- création et suppression d'un animateur ;
- modification du prénom, nom, téléphone, e-mail, date de naissance et couleur ;
- âge calculé automatiquement ;
- ajout/retrait des qualifications ;
- choix du centre préféré et des centres secondaires ;
- ajout, modification et suppression de chaque plage de disponibilité.

## API ajoutée

`PATCH|DELETE /api/animateurs/<animateur_id>/disponibilites/<disponibilite_id>/`
