# Affichage de l’année sur toutes les semaines

Toutes les semaines et périodes visibles dans l’interface affichent désormais clairement leur année civile.

Format commun :

- `Été 2026 — Semaine 1`
- `Toussaint 2026 — Semaine 2`
- `Hiver 2027 — Semaine 1`

La modification concerne notamment :

- le bandeau de semaine de l’Accueil ;
- le bandeau de semaine du Planning ;
- le sélecteur multi-périodes du Récapitulatif ;
- les disponibilités des animateurs ;
- la sélection des périodes dans les groupes ;
- la bibliothèque des périodes et son aperçu d’import ;
- les libellés techniques affichés par Django.

L’année utilisée est celle du début de la semaine. Aucun changement de schéma de base de données n’est nécessaire.

Vérifications : 91 tests Django réussis, JavaScript valide, aucune migration manquante.
