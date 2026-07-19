# Audit et harmonisation d’Animation Manager

Audit réalisé le 18 juillet 2026 à partir de l’archive `AM(9).zip`.

## Résultat général

Le projet fonctionne après harmonisation et nettoyage :

- 154 tests Django réussis ;
- 75 % de couverture Python globale ;
- aucun problème signalé par `manage.py check` ;
- aucune migration manquante ;
- aucun avertissement avec `manage.py check --deploy` dans une configuration de production valide ;
- aucune erreur Ruff sur le code Python applicatif ;
- aucun problème Bandit sur le code Python applicatif ;
- aucune dépendance Python cassée selon `pip check` ;
- tous les fichiers JavaScript passent `node --check` ;
- les 16 templates Django se chargent sans erreur ;
- toutes les feuilles CSS ont des accolades équilibrées ;
- `collectstatic` fonctionne : 155 fichiers copiés et 463 fichiers post-traités.

L’interrogation en ligne d’une base de vulnérabilités des dépendances n’a pas pu être réalisée, l’environnement d’audit ne disposant pas d’un accès DNS au moment du contrôle. La cohérence locale des dépendances a toutefois été validée avec `pip check`.

## Harmonisation des sélecteurs de semaines

Un composant unique est désormais utilisé sur :

- Accueil ;
- Planning ;
- Administration → E-mails ;
- Gestion → Documents ;
- Récapitulatif.

Fichiers communs :

- `templates/partials/_week_picker.html` ;
- `templates/partials/_week_navigation.html` ;
- `static/js/common/week-picker.js` ;
- styles communs dans `static/css/base.css` et `static/css/components.css`.

Le composant gère maintenant de façon identique :

- la hiérarchie Année scolaire → Vacances → Semaines ;
- la sélection simple ou multiple ;
- le libellé et les dates ;
- l’ouverture automatique de l’année et des vacances contenant la semaine actuelle ;
- le repli et le dépli ;
- la remise à zéro ;
- les boutons semaine précédente, aujourd’hui et semaine suivante ;
- les événements JavaScript communs ;
- le comportement mobile.

La semaine courante est repérée à partir de ses dates, même si l’API ne fournit pas le champ `est_actuelle`. Le nom des vacances est également déduit correctement des champs `nom`, `vacances` ou `description_source`, afin d’éviter de créer un faux niveau de vacances différent pour chaque semaine.

Dans l’éditeur d’un document, le sélecteur dynamique clone directement le composant principal. Il n’existe donc plus de deuxième structure HTML susceptible de diverger de celle des E-mails.

## Harmonisation des filtres salariés

Un composant commun est utilisé sur :

- Planning ;
- Salariés ;
- Administration → E-mails.

Fichiers communs :

- `templates/partials/_staff_filter.html` ;
- `static/js/common/staff-filter.js` ;
- styles communs centralisés dans `base.css` et `components.css`.

Les trois pages partagent désormais :

- la même recherche ;
- le même bouton compact ;
- la même fenêtre de filtre ;
- les mêmes dimensions et règles responsive ;
- les qualifications ;
- la disponibilité ;
- l’affectation ;
- le centre préféré ;
- le compteur de filtres actifs ;
- la fermeture au clic extérieur et avec la touche Échap.

Les anciennes règles CSS propres à chaque page qui modifiaient encore la taille ou la position du composant ont été retirées.

## Erreurs corrigées

### Interface et dates

- Correction du décalage possible d’un jour dans les filtres de disponibilité et d’affectation : les dates calendaires locales ne passent plus par une conversion UTC inadaptée.
- Correction de l’ouverture automatique sur la semaine actuelle.
- Correction du regroupement Année → Vacances → Semaines.
- Accès en lecture à l’API des semaines autorisé aux comptes animateurs connectés : le sélecteur de l’Accueil ne reste plus vide pour eux.
- Ajout d’un cache-busting uniforme sur les ressources CSS et JavaScript pour éviter qu’un navigateur conserve une ancienne version après déploiement.

### Appels API et fichiers

- Le client API commun respecte maintenant les objets `FormData` : il ne force plus un en-tête JSON qui supprimait la frontière multipart nécessaire aux fichiers.
- Les envois de documents utilisent désormais ce client commun.
- Les appels `fetch` dispersés ont été remplacés par `apiFetch`, avec une gestion homogène du JSON, du CSRF et des erreurs.
- Correction d’un appel à une fonction JavaScript `getCsrfToken` inexistante dans l’envoi d’e-mail depuis une fiche salarié.
- Correction du rendu de données de documents sur l’Accueil afin d’échapper correctement les titres, URLs et intitulés injectés dans le HTML.

### API et e-mails

- Correction de l’option `include_affectations=1` de l’API salariés : `Prefetch` est maintenant correctement importé.
- Un envoi direct avec des identifiants provisoires invalides ne crée plus une ligne vide dans l’historique des e-mails.
- Les filtres de qualifications des destinataires appliquent une logique cohérente : toutes les qualifications cochées doivent être présentes.
- Les identifiants de filtres devenus invalides sont retirés lors d’un rechargement des données.
- Le filtre disponibilité/affectation ne donne plus de résultat trompeur lorsqu’aucune semaine n’est sélectionnée.
- Les recherches de salariés utilisent une table d’accès par identifiant pour éviter des parcours inutiles répétés.

### Sécurité et robustesse

- L’appel au calendrier scolaire valide explicitement le protocole HTTPS et le domaine officiel `data.education.gouv.fr` avant toute connexion.
- Les exceptions liées à l’absence d’un profil utilisateur ne masquent plus toutes les erreurs avec un `except Exception` trop large.
- Plusieurs exceptions Python sont maintenant chaînées correctement.
- Les boucles et associations `zip` dont les tailles doivent être identiques utilisent `strict=True`.
- Une fermeture du solveur de planning capture maintenant explicitement la bonne taille de groupe.
- Le client API gère les réponses 204, le texte non JSON, les pages HTML d’erreur et les erreurs réseau de façon plus lisible.

## Nettoyage effectué

Supprimés car sans route, sans inclusion et sans référence :

- `templates/import_pdf.html` ;
- `static/css/import-pdf.css` ;
- `static/js/import-pdf.js`.

Également supprimés ou remplacés :

- anciennes implémentations du sélecteur de semaine propres aux E-mails et au Récapitulatif ;
- anciennes implémentations concurrentes des filtres Planning, Salariés et E-mails ;
- règles CSS obsolètes qui écrasaient le composant partagé ;
- construction HTML dupliquée du sélecteur dans l’éditeur de documents ;
- appels réseau directs devenus redondants ;
- imports inutiles et incohérences de tri ;
- caches Python, couverture, environnement virtuel et fichiers produits uniquement par l’audit dans l’archive finale.

Une recherche de références a confirmé qu’aucun autre template ou fichier statique applicatif n’est actuellement orphelin.

## Éléments volontairement conservés

- Les migrations Django sont conservées : même anciennes, elles constituent l’historique nécessaire pour mettre à niveau une base existante.
- `db.sqlite3` est conservé afin de ne pas supprimer d’éventuelles données locales.
- Les grands fichiers `animateurs/views.py`, `static/js/planning.js` et `static/css/planning.css` restent volumineux, mais leur contenu est encore référencé et couvert en partie par les tests. Les découper aveuglément pendant un nettoyage fonctionnel aurait ajouté un risque sans supprimer de code mort démontré.
- Les feuilles CSS contenant plusieurs occurrences d’un sélecteur dans des media queries ou des étapes responsive ont été conservées lorsqu’une suppression sûre ne pouvait pas être démontrée.

## Prévention des régressions

Des tests ont été ajoutés pour vérifier notamment :

- l’utilisation du même sélecteur de semaines sur toutes les pages ;
- l’utilisation exacte du même composant dans Documents et E-mails ;
- le clonage du composant partagé dans l’éditeur de documents ;
- l’utilisation du même filtre salarié sur les trois pages concernées ;
- la prise en charge de `FormData` ;
- l’utilisation du client API commun ;
- l’accès d’un compte animateur à la liste des semaines ;
- l’absence de ligne d’historique vide en cas d’identifiants provisoires invalides.

Le fichier `pyproject.toml` configure désormais Ruff et le fichier `.gitignore` empêche de réintroduire les caches et artefacts locaux dans le projet.
