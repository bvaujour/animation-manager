# Refactor du Planning — juillet 2026

## Objectif

Stabiliser la page Planning en supprimant l'accumulation de correctifs CSS et les dépendances obsolètes, sans changer les fonctions métier existantes.

## Architecture retenue

- `static/css/common-ui.css` : composants communs uniquement.
- `static/css/calendars.css` : cartes calendrier partagées entre l'accueil et le Planning.
- `static/css/planning.css` : toute la géométrie et tous les composants propres au Planning.
- `templates/base.html` expose le bloc `page_styles`, chargé après les styles communs.
- `templates/planning.html` charge `planning.css` dans ce bloc et ne dépend plus de `gestion.css`.

Le mode Affectations utilise exactement deux colonnes :

1. liste des animateurs ;
2. calendriers.

Le mode Effectifs masque la liste et utilise toute la largeur disponible.

## Éléments supprimés

- ancienne troisième colonne et poignée de redimensionnement inexistante ;
- anciens sélecteurs `planning-toolbar`, `planning-view-switcher` et `calendars-scroll-top` ;
- règles du Planning dupliquées dans `common-ui.css` ;
- références JavaScript à des éléments DOM absents ;
- double `requestAnimationFrame` lors du redimensionnement ;
- couleur personnelle et aléatoire des animateurs.

La couleur des animateurs est désormais entièrement dérivée de leur statut et reste identique dans la liste, les calendriers et les exports.

## Migration

```bash
python manage.py migrate
```

La migration `0066_supprimer_couleur_personnelle_animateur.py` supprime l'ancien champ de couleur individuelle.

## Contrôles

```bash
python manage.py check
ruff check .
node --check static/js/planning.js
node --check static/js/effectifs-excel.js
python manage.py test
```

Les tests comprennent des garde-fous empêchant le retour des anciennes colonnes, sélecteurs et règles CSS concurrentes.
