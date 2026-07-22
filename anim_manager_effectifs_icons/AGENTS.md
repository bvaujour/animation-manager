# Animation Manager

## Objectif

Animation Manager est un logiciel interne de gestion d'ALSH destiné aux directions.

Il doit rester :

- simple
- rapide
- ergonomique
- moderne
- orienté PC

Le logiciel n'est PAS destiné aux familles.

---

## Technologies

- Django
- PostgreSQL
- HTML
- CSS
- JavaScript

---

## Design

Toujours utiliser :

- couleurs pastel
- coins arrondis
- ombres légères
- interface très aérée

Éviter :

- fenêtres modales énormes
- scroll horizontal
- boutons inutiles
- textes explicatifs

---

## Planning

Le planning est le cœur du logiciel.

Toujours :

- utiliser toute la largeur disponible
- jamais de scroll horizontal
- calendriers adaptatifs
- drag & drop fluide
- échanges de position plutôt qu'insertion

---

## Code

Toujours :

- commenter le code complexe
- éviter les duplications
- conserver les migrations
- ne jamais supprimer une fonctionnalité sans demande

---

## Avant chaque modification

Toujours vérifier :

python manage.py check

Puis :

python manage.py test

S'il y a des tests.

---

## Après modification

Expliquer :

- fichiers modifiés
- pourquoi
- conséquences éventuelles