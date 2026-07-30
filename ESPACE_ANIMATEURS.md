# Espace animateurs — tableau de bord

## Traduction de la maquette fournie

La page d’accueil des comptes animateurs reprend les principes visuels de la maquette :

- grande navigation latérale bleu nuit, différente de la navigation compacte de la direction ;
- en-tête personnel avec prénom et accès à la fiche ;
- bandeau de contexte pour la journée en cours ;
- navigation d’une semaine à l’autre ;
- bandeau « Informations de la semaine » ;
- cinq cartes journalières de structure identique, avec mise en évidence du jour courant ;
- cartes secondaires pour les sorties, disponibilités, documents, réunions et informations personnelles ;
- adaptation tablette et mobile sans défilement horizontal.

## Données réellement utilisées

Aucune donnée de démonstration n’est inscrite dans la page. Le tableau de bord lit les informations déjà présentes dans Animation Manager :

- affectations et horaires journaliers ;
- lieux, groupes, collègues et effectifs enfants ;
- sorties et responsabilités ;
- réunions de travail ;
- disponibilités personnelles ;
- documents permanents ou associés à la semaine.

Les blocs visibles dans l’image mais absents du modèle actuel — messages, demandes de matériel, tâches, échéances et programme d’animation — n’ont pas été simulés. Ils pourront être ajoutés ultérieurement lorsqu’un module métier correspondant existera.

## Séparation des espaces

- un superutilisateur conserve le tableau de bord et la barre de navigation de la direction ;
- un compte lié à un animateur voit automatiquement le nouvel espace personnel ;
- les informations affichées sont limitées au profil connecté et à ses affectations.

## Principaux fichiers

- `animateurs/services/animateur_dashboard.py` : agrégation des données personnelles ;
- `animateurs/views_pages.py` : chargement du tableau de bord animateur ;
- `animateurs/context_processors.py` : documents permanents de la navigation ;
- `templates/accueil.html` : nouvelle page ;
- `templates/partials/_nav.html` : navigation animateur ;
- `static/css/animator-space.css` : structure de l’espace personnel ;
- `static/css/animateur-dashboard.css` : mise en page du tableau de bord ;
- `animateurs/tests/test_tableau_de_bord_animateur.py` : scénarios de non-régression ajoutés.

## Contrôles effectués

- analyse syntaxique de 177 fichiers Python : OK ;
- syntaxe de 24 fichiers JavaScript : OK ;
- analyse de 14 feuilles CSS : OK ;
- audit statique des routes, vues, templates, références statiques et migrations : OK ;
- équilibre des blocs des templates Django : OK.

Les tests Django et `manage.py check` n’ont pas pu être lancés dans l’environnement de préparation, car Django 5.2.15 n’y était pas installé et aucun accès au dépôt de paquets n’était disponible.

## Menu latéral repliable

Le menu animateur peut désormais être replié en barre d’icônes avec le bouton hamburger. L’état choisi est mémorisé dans le navigateur. Sur mobile, le menu devient un panneau latéral hors écran, ouvert avec un bouton hamburger et fermé par le fond assombri, la touche Échap ou la sélection d’un lien.
