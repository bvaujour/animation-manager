# Refonte de l’architecture de navigation Direction

## Objectif

Rendre Animation Manager compréhensible par une direction qui découvre le logiciel, sans modifier les fonctionnalités, les données, les API ni les règles métier.

## Navigation principale

L’ordre du rail Direction suit désormais les tâches métier :

1. **Tableau de bord**
2. **Équipe**
3. **Planning**
4. **Sorties**
5. **Matériel**
6. **Communication**
7. **Temps & paie**
8. **Configuration**
9. **Administration**

Sur PC, le rail reste compact au repos et s’élargit au survol pour afficher les libellés. Le planning conserve donc toute sa largeur hors survol.

## Équipe

- Salariés
- Formations
- Accès portail

Les pages et URL existantes sont conservées. « Accès portail » correspond à l’ancien écran « Comptes animateurs ».

## Communication

- Infos équipe
- Documents
- E-mails

Les informations et documents restent techniquement gérés dans `/gestion/`, et les e-mails dans `/administration/`. Seule leur présentation dans la navigation change.

## Temps & paie

L’ancienne entrée « Paie » devient **Temps & paie** pour refléter le contenu réel : temps de travail, primes, récapitulatif par centre et totaux par animateur.

## Configuration

- Centres
- Groupes
- Diplômes & statuts
- Vacances
- Calendrier scolaire
- Paramètres avancés (superuser)

Les anciens onglets de `/gestion/` restent présents dans le DOM comme routeurs techniques afin de ne pas modifier leur JavaScript. Ils sont simplement masqués au profit de la navigation métier.

## Administration

- Exports
- Administrateurs
- Mon mot de passe

Les fonctions « E-mails » et « Accès portail » ne sont plus présentées comme des fonctions d’administration, même si leur implémentation technique reste sur la page existante.

## Garanties de cette étape

Cette refonte ne modifie pas :

- les modèles Django ;
- les migrations ;
- les API ;
- les calculs ;
- les affectations ;
- les horaires ;
- les effectifs ;
- les droits existants ;
- le portail animateur ;
- les données en base.

Il s’agit uniquement d’un reclassement de la navigation, des intitulés et des points d’accès visuels.
