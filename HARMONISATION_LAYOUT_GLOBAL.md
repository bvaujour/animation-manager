# Harmonisation globale des layouts

## Comportement ordinateur

- Le rail de navigation reste fixe à gauche.
- Le corps de page réserve exactement la largeur du rail.
- Aucun contenu ne peut passer sous la navigation.
- Les pages fluides, notamment le tableau de bord, conservent toute la largeur restante.
- L'espace supérieur inutile reste supprimé.

## Comportement téléphone

- Le rail de navigation passe en barre fixe en bas pour tous les utilisateurs, y compris la direction.
- Les nombreuses rubriques de direction restent accessibles par défilement horizontal de la barre.
- La déconnexion reste fixe à droite de la barre basse.
- Le contenu récupère toute la largeur du téléphone avec une gouttière de 6 px, ou 4 px sous 390 px.
- Une réserve en bas empêche la navigation de masquer les derniers champs et boutons.
- Les boutons flottants, notifications et indicateurs sont automatiquement placés au-dessus de la barre.
- Les en-têtes, onglets, formulaires, fenêtres et grilles utilisent les mêmes règles mobiles sur toutes les pages.

## Mise en œuvre

La feuille `static/css/responsive-layout.css` est chargée après tous les styles propres aux pages. Elle constitue donc la règle finale du layout et évite les conflits entre les anciens correctifs spécifiques aux différentes rubriques.

## Vérifications

- Compilation syntaxique de tous les fichiers Python réussie.
- La commande Django `manage.py check` n'a pas pu être exécutée, car Django n'est pas installé dans l'environnement d'analyse.
