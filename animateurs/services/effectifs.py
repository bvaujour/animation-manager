"""Services communs d'enregistrement des effectifs enfants."""

from animateurs.models import EffectifEnfantsJour, Evenement


def enregistrer_nombre_effectif(evenement: Evenement, jour, nombre: int) -> str:
    """Enregistre un effectif en préservant ratio et horaires éventuels.

    Retourne ``created``, ``updated``, ``deleted`` ou ``unchanged`` afin que
    les imports puissent produire un bilan fiable.
    """

    ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour).first()
    ancien_nombre = ligne.nombre if ligne else 0
    if ancien_nombre == nombre:
        return "unchanged"

    if nombre == 0:
        if ligne and (ligne.ratio_encadrement_exceptionnel or ligne.heure_arrivee):
            ligne.nombre = 0
            ligne.enfants_par_animateur = ligne.ratio_encadrement_effectif
            ligne.save(update_fields=["nombre", "enfants_par_animateur", "modifie_le"])
            return "updated"
        if ligne:
            ligne.delete()
            return "deleted"
        return "unchanged"

    ratio = ligne.ratio_encadrement_effectif if ligne else evenement.enfants_par_animateur_defaut
    _, cree = EffectifEnfantsJour.objects.update_or_create(
        evenement=evenement,
        date=jour,
        defaults={"nombre": nombre, "enfants_par_animateur": ratio},
    )
    return "created" if cree else "updated"
