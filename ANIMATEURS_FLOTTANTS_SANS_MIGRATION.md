# Animateurs flottants — fonctionnement sans migration

Cette version n'ajoute aucune colonne à la table `Affectation`.

- Une affectation normale reste rattachée à son groupe.
- Cocher « Animateur flottant » la rattache à un groupe technique invisible du lieu.
- Le groupe technique n'apparaît ni dans Gestion ni dans les calendriers de groupes.
- L'animateur apparaît dans la ligne « Animateurs flottants » sous les groupes du lieu.
- Décocher « Animateur flottant » le replace dans le premier groupe visible du lieu.

La base existante est compatible sans lancer `python manage.py migrate`.
