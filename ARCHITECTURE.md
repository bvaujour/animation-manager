# Architecture du projet

## Django

- `animateurs/models.py` : structure des données uniquement.
- `animateurs/views.py` : pages HTML et adaptation HTTP/JSON.
- `animateurs/services/` : règles métier réutilisables et testables.
- `animateurs/tests/` : tests des services, API et solveur.

### Services

- `affectations.py` : création, validation et déplacement des affectations.
- `animateurs.py` : couleurs et traitements propres aux animateurs.
- `dates.py` : lecture et validation des dates reçues par l'API.
- `disponibilites.py` : nettoyage, fusion et contrôle des disponibilités.
- `documents.py` : validation des documents permanents ou périodiques.
- `planning_solver.py` : placement automatique.
- `recapitulatif.py` : calcul des jours travaillés.
- `serializers.py` : transformation des modèles en JSON.

## Templates

- `templates/base.html` : structure HTML commune, navigation et scripts partagés.
- Les pages étendent `base.html` et ne contiennent plus le squelette HTML dupliqué.
- `templates/partials/` : fragments réutilisables, notamment la navigation.

## JavaScript

### Commun

- `static/js/ui.js` : API, dates, modales, onglets et notifications.
- `static/js/common/documents.js` : extension et type court des documents.
- `static/js/common/colors.js` : contraste du texte et couleurs RGBA.
- `static/js/common/forms.js` : options Qualifications/Centres des formulaires Animateur.

### Planning

- `static/js/planning/utils.js` : fonctions pures sur les événements et les dates.
- `static/js/planning.js` : orchestration de FullCalendar et interactions de la page.

Le gros fichier `planning.js` reste volontairement unique pour les fonctions fortement liées à son état interne. Les fonctions sans état en ont été extraites. Un découpage plus poussé devra être accompagné de tests navigateur du drag-and-drop.

## Commandes de contrôle

```bash
python manage.py check
python manage.py test animateurs.tests
python manage.py collectstatic --noinput
```

## Centres des animateurs

Chaque animateur peut désormais avoir :

- un seul **centre préféré** ;
- zéro ou plusieurs **centres secondaires**.

Le modèle historique `PreferenceCentre` est conservé, avec le booléen
`est_prefere`. Le solveur automatique n'utilise que ces centres et privilégie
le centre préféré. Les affectations manuelles restent libres.

## Qualifications proposées dans l'auto

Le champ `selectionnable_remplissage_auto` vaut désormais `False` par défaut
pour les nouvelles qualifications. Les qualifications déjà existantes gardent
leur valeur actuelle après migration.
