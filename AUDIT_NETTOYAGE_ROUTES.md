# Audit et nettoyage des routes / code mort

## Résultat

Le projet n'était pas totalement nettoyé. Cette passe a supprimé les doublons et reliquats sûrs sans modifier le schéma de données.

## Routes supprimées

Les anciennes routes de compatibilité suivantes ont été retirées :

- `/evenement/`
- `/equipe/`
- `/groupes-accueil/`
- `/api/centres/<id>/evenements/`
- `/api/centres/<id>/groupes-accueil/`
- `/api/evenements/<id>/`
- `/api/groupes-accueil/<id>/`
- variantes `reordonner` correspondantes

Les routes canoniques sont maintenant :

- `/api/centres/<id>/groupes/`
- `/api/centres/<id>/groupes/reordonner/`
- `/api/groupes/<id>/`

Le JavaScript de la fiche animateur a été aligné sur ces routes.

## Code mort supprimé

- ancien moteur d'export `animateurs/services/planning_export.py`, doublonné et jamais importé ;
- fonction globale inutilisée de nettoyage de toutes les disponibilités ;
- constante historique `GROUPE_PRINCIPAL_NOM` inutilisée ;
- ancienne fiche déroulante d'animateur du Planning, jamais appelée, avec son CSS ;
- plusieurs fonctions JavaScript héritées d'anciennes interfaces et jamais appelées ;
- imports Python inutilisés détectés par Ruff ;
- dépendance directe inutile `python-dateutil` et dépendances transitives listées manuellement dans `requirements.txt`.

## Navigation

Le lien visible vers l'administration Django a été retiré du menu. La route `/admin/` reste volontairement disponible pour un accès direct d'administration.

## Éléments volontairement conservés

- Le modèle et la table portent encore le nom technique historique `Evenement`, ainsi que plusieurs clés étrangères `evenement`. Ils sont actifs et ne sont pas du code mort. Les renommer nécessiterait une migration de schéma risquée sans bénéfice fonctionnel immédiat.
- Les anciennes migrations contenant les mots équipe, horaire ou événement sont conservées. Elles constituent l'historique nécessaire pour reconstruire une base vierge avec `python manage.py migrate`.
- `DateExclueEvenement` reste utilisé par les règles d'ouverture, le solveur, le récapitulatif, les exports et l'administration Django.
- Les pages Documents et Administration sont actives et restent accessibles depuis le menu.

## Contrôles réalisés

- 86 tests Django réussis ;
- `python manage.py check` sans erreur ;
- aucune migration manquante ;
- syntaxe de tous les fichiers JavaScript validée ;
- Ruff sans erreur ;
- Vulture ne détecte aucun code Python mort avec une confiance d'au moins 80 %, hors signatures obligatoires des migrations ;
- installation validée dans un environnement virtuel neuf avec le `requirements.txt` simplifié.
