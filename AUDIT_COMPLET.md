# Audit complet — Animation Manager

**Date de l’audit : 20 juillet 2026**  
**Périmètre :** application Django, règles métier, navigation, gabarits HTML, CSS, JavaScript, configuration, migrations et tests.

## 1. Synthèse

Le projet est fonctionnel et déjà riche : gestion des salariés, centres, groupes, périodes, disponibilités, documents, effectifs enfants, planning, remplissage automatique, exports et e-mails. Son principal défaut n’était pas l’absence de fonctions, mais l’accumulation de plusieurs générations d’interface et de règles CSS qui finissaient par se contredire.

L’audit a donc privilégié une consolidation sans réécriture risquée : navigation réorganisée, espaces de travail stabilisés, accès directs aux outils, correction des compatibilités métier et validation complète du projet.

**État remis :** 182 tests réussis, contrôles Django et déploiement réussis, migrations cohérentes, Python et JavaScript valides.

## 2. Architecture constatée

- Django 5.2.15, application principale `animateurs`.
- SQLite en local, PostgreSQL/Supabase lorsqu’un `DB_HOST` est défini.
- 50 routes, 17 gabarits HTML, 19 fichiers JavaScript, 14 feuilles CSS.
- Services métier séparés pour les affectations, disponibilités, e-mails, exports, calendrier scolaire, qualifications et remplissage automatique.
- Authentification à deux niveaux métier : superutilisateur pour la direction, compte ordinaire relié à une fiche salarié pour un animateur.
- WhiteNoise pour les fichiers statiques en production et stockage local ou Supabase S3 pour les documents.

## 3. Problèmes importants trouvés et corrigés

### Navigation et lisibilité — corrigé

L’ancien menu latéral pouvait recouvrir le contenu sur ordinateur et plusieurs outils étaient dissimulés dans des onglets secondaires. Le menu est maintenant structuré par usage : Pilotage, Équipe, Organisation, Communication et Paramètres. Les pages Documents et E-mails ont un accès direct. Le menu ouvert réserve sa largeur ; le mode replié conserve un rail compact.

### Planning — corrigé

Le Planning cumulait des règles contradictoires de hauteur, largeur et défilement. La nouvelle disposition réserve une colonne à la liste des salariés, maintient les actions principales sur une ligne, empêche le défilement horizontal et laisse uniquement la zone des calendriers défiler verticalement. Les filtres ont été ramenés aux critères utiles : qualification et centre préféré.

### Salariés — corrigé

La page contenait deux actions d’ajout et plusieurs comportements hérités de l’ancienne fiche séparée. Elle utilise désormais une vraie vue maître/détail : liste compacte à gauche, fiche éditable à droite, défilements internes et un seul bouton d’ajout.

### Administration et e-mails — corrigé

L’accès direct aux e-mails redirige maintenant vers le bon onglet de l’Administration. Le serveur rend immédiatement l’onglet actif et son contenu visible, même avant l’exécution du JavaScript. Cela évite une page apparemment vide en cas de script lent ou indisponible.


### Compatibilité des centres salariés — corrigé

Le passage de l’ancien système « centre préféré + centres secondaires » au nouveau système « plusieurs préférés + interdits » cassait deux cas : la relecture des anciennes données et le respect d’une ancienne liste explicite de centres autorisés par le solveur. Les services acceptent maintenant les deux formats sans perdre les préférences existantes.

### Cohérence des migrations — corrigé

Le modèle `PreferenceCentre.est_prefere` n’était plus parfaitement aligné avec l’état déclaré par les migrations. La migration `0054_alter_preferencecentre_est_prefere.py` remet cet état en cohérence. `makemigrations --check` ne détecte plus de changement oublié.

### Configuration locale et production — corrigé

Le README demandait de copier `.env.example`, mais ce fichier n’existait pas. Il a été ajouté avec les variables Django, PostgreSQL, Supabase et SMTP. Les paramètres S3 de Supabase sont maintenant surchargeables par variables d’environnement tout en conservant les valeurs actuelles par défaut.

## 4. Réorganisation visuelle réalisée

Les feuilles `static/css/common-base.css` et `static/css/common-ui.css` consolident les fondations et composants communs :

- contenu décalé à côté du menu au lieu d’être recouvert ;
- largeur des pages et cartes harmonisée ;
- tableaux et formulaires contenus dans leur espace ;
- Planning et Salariés traités comme de vrais espaces de travail pleine hauteur ;
- menus de filtres correctement positionnés et superposés ;
- Administration et e-mails adaptables à la largeur disponible ;
- règles tablette et mobile conservées ;
- suppression du défilement horizontal global.

Les pages principales ont également reçu une cible de contenu cohérente pour la navigation et l’accessibilité.

## 5. Vérifications exécutées

| Vérification | Résultat |
|---|---:|
| `python manage.py check` | Réussi |
| `python manage.py check --deploy` avec configuration de production | Réussi |
| `python manage.py makemigrations --check --dry-run` | Aucun changement détecté |
| `python manage.py collectstatic --noinput` | Réussi |
| Compilation Python | Réussie |
| Vérification syntaxique de tous les fichiers JavaScript | Réussie |
| Ruff sur `animateurs` et `config` | Réussi |
| Suite Django | **182 tests réussis** |
| Contrôle structurel visuel en 1440 × 900 | Aucun débordement horizontal sur les écrans principaux |

Les tests couvrent les droits d’accès, l’accès direct aux e-mails et l’affichage serveur du bon onglet.

## 6. Dette technique encore présente

### Fichiers trop volumineux — priorité haute à moyen terme

- `animateurs/views.py` : environ 2 600 lignes ;
- `static/js/planning.js` : environ 2 600 lignes ;
- `static/css/planning.css` : environ 1 000 lignes ;
- `static/css/common-base.css` : environ 1 350 lignes ;
- `static/css/common-ui.css` : environ 470 lignes.

Ils fonctionnent, mais rendent chaque évolution plus risquée. La prochaine refonte devrait découper les vues par domaine, le Planning JavaScript par responsabilité et les feuilles CSS par composant. La couche d’audit limite actuellement les conflits, sans effacer cette dette.

### Dépendances CDN — priorité moyenne

FullCalendar est chargé depuis un CDN. Une indisponibilité réseau peut empêcher le Planning avancé de fonctionner. Il serait préférable de le figer dans les fichiers statiques du projet ou de prévoir une stratégie de repli.

### Tests d’interface réels — priorité moyenne

La suite Django couvre bien les services, routes et sorties HTML, mais le dépôt ne contient pas encore de tests de parcours navigateur. Ajouter Playwright permettrait de vérifier automatiquement le glisser-déposer, l’ouverture des filtres, le repli du menu, les onglets et les formulaires sur plusieurs tailles d’écran.


### Architecture des rôles — à documenter strictement

Le code considère uniquement les superutilisateurs comme direction. Le README a été corrigé en ce sens. Toute future création d’un rôle intermédiaire devra passer par une permission dédiée plutôt que par le simple statut `staff`.

## 7. Ordre conseillé pour la suite

1. Tester la version corrigée avec les données réelles sur une copie de la base de production.
2. Ajouter des tests Playwright sur Planning, Salariés, Gestion et E-mails.
3. Découper progressivement `views.py` et `planning.js`, sans modifier simultanément les règles métier.
5. Regrouper à terme les anciennes feuilles CSS autour d’une bibliothèque de composants unique.

## 8. Fichiers principaux modifiés

- `templates/partials/_nav.html`
- `templates/base.html`
- `static/css/common-base.css`
- `static/css/common-ui.css`
- `templates/planning.html`
- `templates/employes.html`
- `templates/gestion.html`
- `templates/administration.html`
- `templates/partials/_staff_filter.html`
- `templates/partials/_emails_admin.html`
- `animateurs/views.py`
- `config/urls.py`
- `animateurs/services/animateurs.py`
- `animateurs/services/serializers.py`
- `animateurs/services/planning_solver.py`
- `config/settings.py`
- `.env.example`
- tests concernés et migration `0054`

La base SQLite livrée a été remise dans son état d’origine : les données temporaires utilisées pour le contrôle visuel ne sont pas incluses dans l’archive finale.
