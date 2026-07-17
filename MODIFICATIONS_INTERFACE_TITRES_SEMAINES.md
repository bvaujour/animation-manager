# Modifications de l’interface

## En-tête principal

Le libellé « Gestion animation » affiché dans la barre supérieure a été remplacé par le nom de la page active :

- Accueil
- Planning
- Gestion
- Récapitulatif
- Documents
- Administration

Le nom « Gestion animation » reste uniquement dans l’en-tête du menu latéral, comme identité de l’application.

## Navigation entre les semaines

Accueil et Planning utilisent désormais le même composant Django partagé :

`templates/partials/_week_navigation.html`

Le composant conserve les identifiants JavaScript propres à chaque page, tout en partageant exactement la même structure et le même style.

## Page Gestion

Le titre et le texte d’introduction ont été supprimés. La page commence directement par les onglets.

## Vérifications

- `python manage.py check` : OK
- 86 tests Django : OK
- syntaxe JavaScript Accueil : OK
- syntaxe JavaScript Planning : OK
- aucune migration à créer
