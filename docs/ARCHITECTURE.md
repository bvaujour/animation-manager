# Architecture du projet

## Backend

- `animateurs/models.py` contient le schéma métier.
- `animateurs/views.py` est la façade publique importée par les routes.
- Les vues sont réparties par domaine dans `views_pages.py`, `views_staff.py`,
  `views_planning.py`, `views_catalogue.py`, `views_reporting.py`,
  `views_communications.py`, `views_effectifs.py`, `views_sorties.py` et
  `views_worktime.py`.
- `animateurs/services/` contient les règles métier, sérialisations, exports et
  intégrations externes. Une règle réutilisée par plusieurs vues doit être
  placée ici plutôt que recopiée.

## Interface

Les feuilles sont chargées dans cet ordre :

1. `static/css/common-base.css` : tokens visuels et composants élémentaires ;
2. `static/css/common-ui.css` : composants communs plus élaborés ;
3. feuille propre à la page ;
4. `static/css/app-layout.css` : source unique du layout global, de la
   navigation responsive et de la densité commune.

Le rail mesure 42 px sur ordinateur. Sous 801 px, il devient une barre basse de
48 px et le contenu réserve sa hauteur. Les pages ne doivent pas redéfinir ce
comportement.

Les helpers JavaScript communs sont dans `static/js/ui.js` et
`static/js/common/`. Les scripts de page ne doivent pas recopier les fonctions
de dates, pluriels, couleurs, documents, périodes ou données de planning déjà
exposées par ces fichiers.

## Templates

- `templates/base.html` définit l'ordre des ressources communes.
- `templates/partials/_nav.html` est l'unique navigation.
- `templates/partials/_page_header.html` est l'en-tête commun.
- Les sélecteurs de période utilisent `_week_navigation.html` et
  `_week_picker.html`.

## Comptes

La création d'un accès animateur passe par `animateurs/services/comptes.py`.
L'identifiant suit le format « initiale du prénom + nom » et les doublons sont
numérotés. La longueur minimale du mot de passe est centralisée dans
`PASSWORD_MIN_LENGTH` et transmise aux templates par le context processor.
