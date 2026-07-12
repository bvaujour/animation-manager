# Nettoyage de la base AM(7)

## Éléments supprimés

- Ancien module d'envoi groupé abandonné : service Python, page, JavaScript, CSS et tests.
- `animateurs/tests.py`, fichier vide en conflit avec le package `animateurs/tests/`.
- Fonctions de compatibilité `normaliser_centres_autorises` et `appliquer_centres_autorises`, plus appelées depuis le passage au centre préféré + centres secondaires.
- Parseur de dates dupliqué dans `planning_solver.py` : le solveur utilise désormais le service commun `services/dates.py`.
- Tous les `__pycache__`, fichiers `.pyc`, bases SQLite temporaires et sorties `collectstatic`.

## Bugs corrigés

- Ajout de l'import `re` manquant dans `views.py`, utilisé pour valider les couleurs animateur.
- Suppression d'imports Python inutilisés détectés par Ruff.
- Correction de la découverte globale des tests Django.
- Navigation latérale sortie du template HTML et centralisée dans `static/js/ui.js`.
- Documentation des modèles mise en cohérence avec la règle actuelle : sans disponibilité renseignée, un animateur est indisponible.

## Tests ajoutés

- Modification d'une couleur animateur valide par l'API.
- Refus d'une couleur animateur invalide par l'API.

## Vérifications réalisées

- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- `python manage.py test` : 25 tests réussis
- Ruff : aucune erreur Python
- Syntaxe de tous les fichiers JavaScript avec `node --check`
- `collectstatic`
- Migrations sur une base SQLite vierge
- Smoke test HTTP de toutes les pages et API GET principales
