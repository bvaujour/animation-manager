# Publication des plannings et documents

## Planning
- La publication est gérée semaine par semaine depuis la page **Planning**.
- Le bouton indique **Planning publié** ou **Planning non publié** pour la semaine affichée.
- Un animateur ne voit le calendrier de la semaine que lorsque cette semaine est publiée.
- Une semaine non publiée affiche un message d’attente à la place du calendrier.

## Documents
- Chaque document possède désormais un statut **Publié / Non publié**.
- La direction peut choisir de publier dès l’ajout, puis modifier ce statut depuis la fiche du document.
- Les pages et tableaux de bord animateurs ne chargent que les documents publiés.

## Migration
La migration `0080_publication_planning_document.py` ajoute :
- le modèle `PublicationPlanning` ;
- le champ `Document.publie`.

Par sécurité, les semaines et documents existants sont non publiés après migration. La direction décide donc explicitement de ce qui devient visible.
