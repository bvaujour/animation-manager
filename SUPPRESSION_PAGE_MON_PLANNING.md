# Suppression de la page « Mon planning »

La page animateur distincte « Mon planning » a été supprimée, car son calendrier est désormais intégré directement au tableau de bord animateur.

Modifications :
- suppression de la route `/mon-planning/` ;
- suppression de la vue Django et du template associés ;
- suppression de l’icône « Mon planning » dans la navigation animateur ;
- suppression du dernier lien « Ouvrir le planning détaillé » du tableau de bord ;
- suppression des imports, tests de route et styles devenus inutiles.

Le calendrier personnel reste accessible directement depuis le tableau de bord animateur.
