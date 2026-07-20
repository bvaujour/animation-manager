# Refactorisation du code – Animation Manager

## Objectif

Réduire le couplage du projet sans modifier les comportements métier ni les URL utilisées par l’interface.

## Changements réalisés

### Découpage des vues Django

Le fichier `animateurs/views.py` regroupait environ 2 600 lignes et mélangeait les pages HTML, les comptes, le planning, les documents, les e-mails et les effectifs enfants.

Il est maintenant réparti ainsi :

- `animateurs/views.py` : vues générales, salariés, planning, gestion, périodes et documents ;
- `animateurs/views_communications.py` : modèles d’e-mails, contacts externes, envois groupés et historique individuel ;
- `animateurs/views_effectifs.py` : lecture et enregistrement des effectifs enfants.

`views.py` passe d’environ 2 600 à environ 1 800 lignes. Le code métier n’a pas été réécrit : il a été déplacé par domaine afin de limiter les risques de régression.

### Réorganisation des URL

Les routes applicatives ont été déplacées de `config/urls.py` vers `animateurs/urls.py`.

- `config/urls.py` ne contient plus que la route d’administration Django, l’inclusion des routes de l’application et le service des médias en développement ;
- `animateurs/urls.py` regroupe les pages et API de l’application par domaine ;
- toutes les URL et tous les noms de routes existants sont conservés.

La configuration racine passe d’environ 150 lignes à 14 lignes.

### Nettoyage des dépendances

- suppression des imports devenus inutiles dans `views.py` ;
- imports propres à chaque nouveau module ;
- aucun import inutilisé détecté dans les modules modifiés ;
- suppression des dépendances croisées inutiles entre les routes générales et les communications.

## Contrôles effectués

- compilation de tous les fichiers Python avec `compileall` ;
- analyse AST des imports inutilisés dans les modules modifiés ;
- vérification syntaxique de tous les fichiers JavaScript avec `node --check` ;
- vérification que les noms et chemins des routes restent inchangés.

La suite Django complète n’a pas pu être lancée dans cet environnement, car les dépendances Python de l’application ne sont pas installées et leur téléchargement avait déjà expiré lors de l’étape précédente.

## Suite recommandée

Le prochain découpage utile concerne `static/js/planning.js`, qui dépasse encore 2 600 lignes. Il peut être séparé en modules dédiés à l’état, aux calendriers, au glisser-déposer, aux effectifs enfants et aux fenêtres modales. Cette étape doit être accompagnée de tests visuels dans un navigateur, car elle touche directement le comportement interactif du Planning.
