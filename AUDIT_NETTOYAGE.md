# Revue et nettoyage — Animation Manager

**Date : 30 juillet 2026**  
**Archive examinée :** `anim(3).zip`

## Résultat

Le nettoyage a été réalisé de façon conservatrice : seuls les éléments démontrés comme générés, dupliqués, orphelins, historiques ou sans appel ont été retirés. Les migrations Django et les tests protégeant encore une règle métier ont été conservés.

L’archive extraite est passée d’environ **11 Mo et 963 fichiers** à environ **2,5 Mo et 244 fichiers**.

## Éléments supprimés

- copie imbriquée complète `anim_manager_effectifs_icons/` : **212 fichiers** ;
- dossier généré `staticfiles/` : **159 fichiers**, recréé par `collectstatic` ;
- **325 fichiers `.pyc`** et tous les dossiers `__pycache__` ;
- base locale `db.sqlite3`, vide de données métier et d’utilisateurs, mais correctement migrée ;
- ancien écran Import PDF, sans route ni vue :
  - `templates/import_pdf.html` ;
  - `static/js/import-pdf.js` ;
  - `static/css/import-pdf.css` ;
- **20 notes techniques historiques** (`CORRECTIF_*`, `REFACTOR_*`, anciens rapports et variantes sur les animateurs flottants) ;
- deux fichiers de tests transitoires fondés sur l’ancienne structure du code :
  - `test_planning_refactor.py` ;
  - `test_routes_nettoyees.py` ;
- un test purement historique vérifiant seulement l’absence de l’ancien template salarié autonome.

La suite conservée contient **35 fichiers et 371 tests**. Au total, **17 tests transitoires ou redondants** ont été retirés.

## Code mort retiré

Trois fonctions JavaScript sans aucun appel ont été supprimées :

- `creerCalendrierCentre` dans `static/js/accueil.js`, ancien calendrier agrégé remplacé par les calendriers par groupe ;
- `formatContacts` dans `static/js/sortie-detail.js` ;
- `teamFor` dans `static/js/sortie-detail.js`.

Deux imports Python jamais utilisés ont également été supprimés :

- `SortieResponsabilite` dans `animateurs/services/sorties.py` ;
- `SortieEtapeTransport` dans `animateurs/views_sorties.py`.

Une nouvelle analyse croisée n’a ensuite trouvé aucun autre import Python inutilisé, aucune fonction JavaScript nommée manifestement sans appel et aucun fichier statique orphelin.

## Cohérence corrigée

`export_recapitulatif_excel` était bien utilisé par les routes, mais absent de `animateurs.views.__all__`. Il a été ajouté à la façade publique afin que les routes et les exports déclarés restent cohérents.

## Prévention des récidives

Ajouts ou rétablissements :

- `.gitignore` pour exclure caches, environnements virtuels, secrets, base SQLite locale, médias et `staticfiles` ;
- `.env.example`, attendu par le script d’installation et le README ;
- `Makefile`, attendu par les commandes documentées dans le README ;
- cible `make clean` pour supprimer les artefacts générés ;
- mise à jour du README vers le présent rapport.

## Vérifications exécutées

- audit statique interne : **OK** ;
- **175 fichiers Python** analysés syntaxiquement ;
- **21 templates** et **48 références statiques** contrôlés ;
- **52 vues** comparées aux routes et à la façade ;
- **77 migrations** numérotées, sans doublon ;
- syntaxe de tous les JavaScript avec `node --check` : **OK** ;
- aucun template ou fichier statique conservé sans référence identifiée ;
- aucun cache Python, dossier `staticfiles` ou projet imbriqué restant.

## Limite de validation

La suite Django complète, `manage.py check` et Ruff n’ont pas pu être exécutés dans l’environnement d’analyse : Django 5.2.15 et Ruff n’y étaient pas installés et le téléchargement des dépendances n’était pas disponible. La syntaxe et la cohérence statique sont validées, mais une validation finale doit être lancée dans l’environnement du projet :

```bash
make install
source .venv/bin/activate
make verify
```

Avant déploiement, il reste recommandé de tester manuellement la connexion, le Planning, les effectifs Excel, les salariés, les documents, les e-mails, les sorties et les exports avec une copie des données réelles.
