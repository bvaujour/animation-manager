# Revue mobile verticale

## Objectif

Sous 800 px, l’interface utilise désormais une seule logique portable : les informations et les commandes suivent autant que possible un flux vertical, du haut vers le bas. À partir de 800 px, le layout PC reste inchangé.

## Règles communes ajoutées

- Les grilles de cartes, formulaires et panneaux passent sur une seule colonne.
- Les en-têtes de section affichent le titre, puis les informations, puis les actions.
- Les groupes de boutons passent verticalement et occupent toute la largeur disponible.
- Les cartes utilisent leur hauteur naturelle et ne conservent pas de hauteur artificielle.
- Les champs et panneaux ne peuvent plus imposer une largeur supérieure à l’écran.
- Les modales utilisent presque toute la largeur du téléphone et leurs formulaires sont linéarisés.
- Les pages Salariés et Gestion utilisent le défilement général de la page au lieu de zones internes difficiles à manipuler.

## Pages revues

- Tableau de bord direction : indicateurs, centres, alertes et actions en une colonne.
- Tableau de bord animateur : panneaux, disponibilités, profil et demandes de matériel empilés.
- Planning : commandes verticales et calendriers pleine largeur. La liste glissable des animateurs reste horizontale sous les calendriers, car cela correspond à son usage métier.
- Salariés : liste verticale au-dessus de la fiche, formulaires et onglets internes sur une colonne.
- Gestion : lieux, groupes, qualifications, périodes et documents en flux vertical.
- Administration : exports, e-mails, superusers et formulaires en une colonne.
- Sorties : fiches, formulaires, statistiques, transports, responsabilités et fenêtres en une colonne.
- Documents : cartes et actions verticales.
- Profil animateur : coordonnées et mot de passe en une colonne.
- Demandes de matériel : un champ par ligne et actions verticales.
- Récapitulatif : commandes et légendes verticales ; les tableaux denses gardent un défilement horizontal local pour ne supprimer aucune donnée.

## Exceptions conservées volontairement

Quelques éléments restent horizontaux car les empiler rendrait leur usage moins bon :

- les cinq jours d’un calendrier hebdomadaire ;
- les jours d’une semaine de disponibilités ;
- la liste des animateurs à glisser dans Planning → Affectations ;
- les tableaux métier contenant de nombreuses colonnes.

## Breakpoints

Il ne reste que deux layouts d’écran :

- PC : `min-width: 800px` ;
- portable : `max-width: 799px`.

L’ancien breakpoint spécifique à 430 px et la règle de conteneur à 620 px ont été supprimés. Les règles d’impression ne sont pas concernées.

## Fichiers modifiés

- `static/css/app-layout.css`
- `static/css/animateurs.css`
- `static/css/demandes-materiel.css`
- `static/css/gestion.css`

Aucune vue, route, donnée ou règle métier n’a été modifiée.

## Vérifications

- audit statique du projet : validé ;
- syntaxe des feuilles CSS : validée ;
- syntaxe de tous les JavaScript : validée ;
- absence de breakpoint d’écran intermédiaire : vérifiée.

`python manage.py check` et les tests Django n’ont pas pu être lancés dans l’environnement d’analyse, car Django n’y est pas installé.
