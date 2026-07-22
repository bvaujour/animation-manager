# Animateurs flottants

## Stockage

Aucun champ « flottant » n'existe dans la table `Affectation`.

Un animateur flottant est une affectation classique reliée à un groupe technique invisible propre au lieu. Le statut affiché par l'API est calculé à partir de ce rattachement ; il n'est pas enregistré dans une colonne booléenne.

La migration `0068_remove_affectation_est_flottant` supprime l'ancien champ temporaire si la migration 0067 avait déjà été appliquée.

## Utilisation

Dans Planning > Affectations, chaque lieu possède une ligne « Animateurs flottants » avec une case par jour.

- sélectionner un animateur puis cliquer dans la case ;
- ou glisser directement l'animateur dans la case ;
- un double dépôt identique renvoie l'affectation existante et ne crée pas de doublon ;
- une affectation du même lieu peut être déplacée vers la case flottante ; si elle couvre plusieurs jours, seule la journée choisie est isolée.

## Calcul de couverture

Les animateurs fixes couvrent d'abord les enfants de leur groupe. Les flottants couvrent uniquement les enfants restant non couverts dans le lieu. Avant chaque flottant, le calcul reprend le taux le plus contraignant parmi les reliquats encore présents.
