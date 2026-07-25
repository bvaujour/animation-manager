# Audit complet — Animation Manager

**Date : 24 juillet 2026**
**Archive auditée :** `anim(2).zip`
**Périmètre :** structure Django, configuration, routes, vues, services, modèles, migrations, base locale, templates, CSS, JavaScript, tests et fichiers générés.

## 1. Résultat général

Le projet possède une base métier cohérente et une suite de tests importante. Le principal risque venait de l'accumulation historique : une copie complète du projet était imbriquée dans l'archive, des fichiers compilés et `staticfiles` étaient versionnés, plusieurs rapports de corrections temporaires restaient à la racine et le fichier principal des vues dépassait 2 100 lignes.

La version remise est nettoyée et plus modulaire. Les routes publiques, noms de vues et fonctionnalités encore utilisées ont été conservés. Le seul écran fonctionnel supprimé est l'ancien import PDF, qui n'avait plus ni route ni vue ; l'import Excel actuellement utilisé dans le Planning est conservé.

## 2. Nettoyage réalisé

Éléments retirés :

- copie historique complète `anim_manager_effectifs_icons/` ;
- répertoire généré `staticfiles/` ;
- caches Python `__pycache__`, fichiers `.pyc` et `.pyo` ;
- ancien écran orphelin d'import PDF : template, CSS et JavaScript ;
- notes transitoires `CORRECTIF_*.md`, `REFACTOR_*.md`, `ANIMATEURS_FLOTTANTS*.md` et ancien rapport de suppression des historiques ;
- base `db.sqlite3` fournie, car elle ne contenait aucune donnée métier ni aucun utilisateur et n'était migrée que jusqu'à `0056`, alors que le code contient les migrations jusqu'à `0072`.

Tous les fichiers statiques et templates conservés ont au moins une référence identifiée dans le projet. La base locale sera recréée proprement par `python manage.py migrate`.

## 3. Refactorisation du backend

L'ancien `animateurs/views.py` de 2 163 lignes a été découpé sans changer le contrat des routes :

| Module | Responsabilité |
|---|---|
| `views.py` | façade de compatibilité et exports publics |
| `views_pages.py` | pages, administration, tableau de bord et exports |
| `views_staff.py` | salariés et disponibilités |
| `views_planning.py` | planning, affectations et remplissage automatique |
| `views_catalogue.py` | centres, groupes, qualifications et périodes scolaires |
| `views_reporting.py` | documents et récapitulatif |

Les modules déjà spécialisés (`views_communications.py`, `views_effectifs.py` et `views_sorties.py`) restent séparés. Un contrôle automatique compare désormais les 44 vues importées par `urls.py` avec les exports explicites de la façade.

## 4. Normalisation de l'interface

Les éléments récurrents ont été rapprochés d'une source commune :

- les pages utilisent un bloc `page_styles` homogène pour leurs feuilles spécialisées ;
- les en-têtes de Tableau de bord, Planning, Salariés, Gestion, Documents, Disponibilités, Récapitulatif, Administration, Sorties et Mon profil utilisent le partial commun `_page_header.html` ;
- le même composant gère maintenant une navigation hebdomadaire, un sélecteur multi-périodes ou un simple titre ;
- les versions de cache codées en dur ont été remplacées par une variable globale `ASSET_VERSION` injectée par le context processor ;
- la page Sorties conserve les mêmes identifiants attendus par son JavaScript tout en utilisant l'en-tête partagé.

Cette normalisation limite les divergences futures sans réécrire brutalement les écrans existants.

## 5. Environnement de développement reproductible

Ajouts réalisés :

- `.env.example` complet pour Django, PostgreSQL/Supabase, stockage et SMTP ;
- `.gitignore` pour les environnements, caches, secrets, médias, `staticfiles` et bases SQLite locales ;
- `Makefile` avec `install`, `check`, `test`, `lint`, `verify` et `run` ;
- `scripts/setup_dev.sh` pour créer `.venv`, installer les dépendances et migrer ;
- `scripts/verify.sh` pour enchaîner les contrôles disponibles ;
- `scripts/static_audit.py`, exécutable sans Django ;
- `build.sh` renforcé avec `set -Eeuo pipefail`, `python -m pip`, `manage.py check` et migration non interactive.

Un environnement virtuel isolé a été créé pendant l'audit. L'installation des dépendances n'a toutefois pas pu aboutir dans le bac à sable d'analyse : aucun accès DNS à PyPI et aucun cache local de Django n'étaient disponibles. Ce blocage appartient à l'environnement d'audit, pas au projet.

## 6. Contrôles réellement exécutés

| Contrôle | Résultat |
|---|---:|
| Analyse syntaxique Python par AST | **159 fichiers valides** |
| Syntaxe JavaScript avec `node --check` | **Tous les fichiers valides** |
| Templates analysés | **21** |
| Références statiques littérales contrôlées | **44, aucune manquante** |
| Vues de façade comparées aux routes | **44, cohérentes** |
| Fonctions déplacées comparées à leur AST d’origine | **52 sur 52 identiques** |
| Migrations numérotées | **70, aucun numéro en double** |
| Recherche de templates restants sans référence | **Aucun** |
| Recherche de fichiers statiques restants sans référence | **Aucun** |
| Recherche d'artefacts générés interdits | **Aucun** |
| `git diff --check` | **Réussi** |

La suite présente dans le dépôt contient **34 fichiers de tests et 292 méthodes `test_*`**. Elle n'a pas été exécutée dans cet environnement, car Django 5.2.15 n'a pas pu être installé. Pour la même raison, `manage.py check`, `makemigrations --check`, `collectstatic`, Ruff et les tests Django ne doivent pas être considérés comme validés ici. La commande `make verify` les exécutera automatiquement dès que les dépendances seront installées.

## 7. Points de vigilance encore présents

### JavaScript du Planning

`static/js/planning.js` reste le fichier le plus volumineux, environ 128 Ko. Il regroupe encore chargement, rendu, glisser-déposer, effectifs, affectations et interactions. Son découpage doit être progressif et accompagné de tests navigateur, car une séparation mécanique serait risquée.

### CSS historique

Les feuilles communes et spécialisées contiennent encore plusieurs redéfinitions de sélecteurs. Une partie est volontaire dans les media queries et dans les surcharges par page ; une suppression automatique pourrait modifier l'affichage. La prochaine étape raisonnable est de migrer composant par composant vers `common-ui.css`, avec comparaison visuelle à chaque écran.

### Modèle principal

`animateurs/models.py` reste volumineux, environ 40 Ko. Une séparation en paquet `models/` est possible mais ne doit être faite qu'avec Django installé, migrations vérifiées et suite complète verte.

### Tests d'interface

Les tests Django sont nombreux, mais aucun environnement Playwright/Cypress n'est présent pour valider réellement le glisser-déposer, les dialogues, le menu, les filtres et les différents formats d'écran.

### Configuration de production

Les valeurs par défaut `DEBUG=True` et la clé de développement sont adaptées au local uniquement. Sur Render, `DEBUG=False`, une vraie `SECRET_KEY`, `ALLOWED_HOSTS`, la base PostgreSQL et les paramètres SMTP doivent être définis. `manage.py check --deploy` doit faire partie de la validation avant mise en production.

## 8. Procédure de validation recommandée

```bash
make install
source .venv/bin/activate
make verify
python manage.py check --deploy
```

Puis tester manuellement, avec une copie des données réelles : connexion direction et animateur, Planning, affectations flottantes, effectifs Excel, Gestion, Salariés, Documents, E-mails, Sorties et exports.

## 9. Fichiers structurants modifiés ou ajoutés

- `animateurs/views.py`
- `animateurs/views_pages.py`
- `animateurs/views_staff.py`
- `animateurs/views_planning.py`
- `animateurs/views_catalogue.py`
- `animateurs/views_reporting.py`
- `animateurs/context_processors.py`
- `config/settings.py`
- `templates/base.html`
- `templates/partials/_page_header.html`
- templates des pages principales
- `.env.example`
- `.gitignore`
- `Makefile`
- `scripts/setup_dev.sh`
- `scripts/verify.sh`
- `scripts/static_audit.py`
- `build.sh`
- `README.md`
