# Refactorisation CSS

## Résultat

- Avant : 14 feuilles CSS, 16 233 lignes.
- Après : 12 feuilles CSS, 2 743 lignes.
- Réduction : 13 490 lignes, soit environ 83 %.

## Nouvelle organisation

- `common-base.css` : fondations globales, navigation, formulaires et structure générale.
- `common-ui.css` : composants communs, thème visuel et règles d’ergonomie partagées.
- Les feuilles `planning.css`, `gestion.css`, `animateurs.css`, etc. ne conservent que les règles propres à leur page.

## Nettoyage effectué

- fusion de `base.css`, `components.css`, `app-theme.css` et `audit-layout.css` en deux couches communes ;
- conservation de l’ordre de chargement historique pour éviter les régressions de cascade ;
- suppression des blocs strictement dupliqués ;
- suppression des commentaires et espaces inutiles ;
- normalisation des feuilles à un bloc par ligne ;
- mise à jour des versions de cache CSS dans tous les templates ;
- suppression des anciennes références aux quatre feuilles remplacées.

## Vérifications

- Toutes les feuilles ont été analysées avec `tinycss2` : aucune erreur de syntaxe CSS.
- Les tests Django n’ont pas pu être relancés dans cet environnement, car l’installation des dépendances a expiré lors du téléchargement de `boto3`.
