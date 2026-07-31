# Rapport de nettoyage et centralisation

## Éléments supprimés

- caches Python (`__pycache__`, `.pyc`, `.pyo`) et répertoires générés ;
- anciennes feuilles et scripts de navigation non chargés ;
- règles CSS de l'ancien tiroir/hamburger (`top-nav`, `nav-drawer`, overlays et
  états repliés) alors que le site utilise désormais `app-rail` ;
- huit notes de correctifs historiques à la racine, remplacées par la présente
  documentation ;
- fonctions JavaScript dupliquées pour les dates, pluriels et jours masqués ;
- sérialisations répétées des centres préférés et qualifications.

## Éléments centralisés

- palette finale dans `common-base.css` ;
- composants communs dans `common-ui.css` ;
- géométrie du site, rail PC, barre basse mobile, en-têtes, onglets et densité
  dans `app-layout.css` ;
- helpers JavaScript dans `ui.js` et `common/planning-data.js` ;
- règle de mot de passe dans `PASSWORD_MIN_LENGTH` ;
- construction des payloads communs dans `animateurs/services/serializers.py`.

## Garde-fous ajoutés

- `.gitignore` et `.env.example` complets ;
- l'audit statique détecte désormais les CSS/JS orphelins en plus des assets
  manquants ;
- les tests d'interface ont été alignés avec le tableau de bord et le layout
  actuels.

## Validation

L'audit statique, la syntaxe JavaScript et l'analyse CSS sont exécutés avant la
livraison. La suite Django complète nécessite Django 5.2.15, indisponible dans
l'environnement de nettoyage utilisé pour cette archive.

## Résultat chiffré

- fichiers du projet : 432 → 251 ;
- taille du dossier de travail : 4,5 Mo → 2,6 Mo ;
- ressources CSS/JavaScript : environ 54 Ko de règles et scripts obsolètes ou
  dupliqués retirés ;
- 178 fichiers Python, 21 templates, 39 références statiques, 38 CSS/JS,
  14 feuilles CSS, 52 vues et 77 migrations contrôlés par l'audit final ;
- syntaxe de tous les JavaScript validée avec `node --check` ;
- 14 feuilles CSS analysées sans erreur de parsing.
