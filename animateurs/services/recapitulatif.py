"""Calcul du nombre de jours travaillés par animateur et par centre."""

from animateurs.models import Affectation, Animateur, Centre


def generer_recapitulatif(debut, fin):
    centres = list(Centre.objects.all().order_by("nom"))
    animateurs = list(Animateur.objects.all().order_by("prenom", "nom"))
    affectations = Affectation.objects.select_related("animateur", "centre").filter(
        debut__lt=fin,
        fin__gt=debut,
    )

    recap = {
        a.id: {
            "id": a.id,
            "prenom": a.prenom,
            "nom": a.nom,
            "total": 0,
            "centres": {c.id: 0 for c in centres},
        }
        for a in animateurs
    }

    for affectation in affectations:
        debut_effectif = max(affectation.debut, debut)
        fin_effective = min(affectation.fin, fin)
        nb_jours = max((fin_effective.date() - debut_effectif.date()).days, 1)
        ligne = recap[affectation.animateur_id]
        ligne["total"] += nb_jours
        ligne["centres"][affectation.centre_id] += nb_jours

    lignes = [
        {
            "id": ligne["id"],
            "prenom": ligne["prenom"],
            "nom": ligne["nom"],
            "total": ligne["total"],
            "centres": [{"id": c.id, "jours": ligne["centres"][c.id]} for c in centres],
        }
        for ligne in recap.values()
    ]
    lignes.sort(key=lambda item: (-item["total"], item["prenom"], item["nom"]))
    return centres, lignes
