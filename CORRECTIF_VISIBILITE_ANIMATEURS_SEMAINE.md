# Correctif — visibilité des animateurs dans le Planning

## Règle métier

Dans la vue par défaut « Encore plaçables », un animateur reste visible tant qu'il existe au moins une date de la semaine qui est à la fois :

- ouverte dans au moins un groupe ;
- couverte par ses disponibilités ;
- non couverte par une affectation existante.

Il disparaît lorsque toutes ses journées possibles sont affectées, ou lorsqu'il n'est disponible sur aucun jour réellement ouvert.

## Cause des échecs précédents

Le navigateur reconstruisait cette situation à partir de plusieurs sources qui pouvaient diverger : calendriers visibles seulement, événements chargés de façon asynchrone, cache FullCalendar et datetimes UTC. Un centre masqué ou un décalage de date pouvait donc laisser croire qu'une journée restait libre.

## Correction

La situation hebdomadaire est maintenant calculée côté serveur sur tous les groupes et renvoyée par l'API Planning dans `situation_semaine`. Le JavaScript applique uniquement ces booléens et ne tente plus de recalculer la situation depuis les calendriers.

Le numéro de version du fichier `planning.js` a aussi été changé pour empêcher le navigateur de conserver l'ancien script.
