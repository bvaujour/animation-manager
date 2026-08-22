"""Services communs d'enregistrement des effectifs enfants."""

from animateurs.models import EffectifEnfantsJour, Evenement
from animateurs.services.accueils import valider_contexte_accueil
from animateurs.services.categories_groupes import categorie_reglementaire_groupe
from animateurs.services.reglementation_encadrement import ratio_reglementaire


def ratio_encadrement_contexte(
    evenement: Evenement,
    jour,
    *,
    type_accueil=None,
    modalite_periscolaire=None,
) -> int:
    """Ratio réglementaire du contexte, avec repli historique sûr.

    Les appels anciens sans type d'accueil conservent le ratio configuré sur le
    groupe. Dès qu'un contexte Vacances/Périscolaire est connu, le référentiel
    central d'Encadrement & qualifications devient la source du taux proposé.
    Une exception saisie pour un jour précis reste gérée par le modèle et passe
    toujours avant cette valeur de référence.
    """

    if type_accueil is not None:
        ratio = ratio_reglementaire(
            type_accueil=type_accueil,
            categorie_age=categorie_reglementaire_groupe(evenement),
            centre=evenement.centre,
            jour=jour,
            modalite=modalite_periscolaire,
        )
        if ratio:
            return max(1, int(ratio))
    return max(1, int(evenement.enfants_par_animateur_defaut or 1))


def enregistrer_nombre_effectif(
    evenement: Evenement,
    jour,
    nombre: int,
    *,
    type_accueil=None,
    modalite_periscolaire=None,
) -> str:
    """Enregistre un effectif en préservant ratio et horaires éventuels.

    En vacances, ``modalite_periscolaire`` reste vide. En périscolaire, la
    modalité fait partie de la clé fonctionnelle : matin, midi et soir peuvent
    donc porter trois effectifs différents le même jour pour le même groupe.

    Le ratio journalier proposé provient du référentiel réglementaire du
    contexte ; une exception quotidienne déjà saisie reste prioritaire.

    Retourne ``created``, ``updated``, ``deleted`` ou ``unchanged`` afin que
    les imports puissent produire un bilan fiable.
    """

    type_accueil = valider_contexte_accueil(
        evenement, type_accueil, modalite_periscolaire
    )

    filtre = {
        "evenement": evenement,
        "date": jour,
        "modalite_periscolaire": modalite_periscolaire,
    }
    ligne = EffectifEnfantsJour.objects.filter(**filtre).first()
    ancien_nombre = ligne.nombre if ligne else 0
    contexte_change = bool(
        ligne and type_accueil is not None and ligne.type_accueil_id != type_accueil.pk
    )
    ratio_base = ratio_encadrement_contexte(
        evenement,
        jour,
        type_accueil=type_accueil,
        modalite_periscolaire=modalite_periscolaire,
    )
    ratio_change = bool(
        ligne
        and not ligne.ratio_encadrement_exceptionnel
        and int(ligne.enfants_par_animateur or 0) != ratio_base
    )
    if ancien_nombre == nombre and not contexte_change and not ratio_change:
        return "unchanged"

    if nombre == 0:
        if ligne and (ligne.ratio_encadrement_exceptionnel or ligne.heure_arrivee):
            ligne.nombre = 0
            ligne.enfants_par_animateur = ratio_base
            if type_accueil is not None:
                ligne.type_accueil = type_accueil
            ligne.save(update_fields=["nombre", "enfants_par_animateur", "type_accueil", "modifie_le"])
            return "updated"
        if ligne:
            ligne.delete()
            return "deleted"
        return "unchanged"

    defaults = {"nombre": nombre, "enfants_par_animateur": ratio_base}
    if type_accueil is not None:
        defaults["type_accueil"] = type_accueil
    _, cree = EffectifEnfantsJour.objects.update_or_create(
        **filtre,
        defaults=defaults,
    )
    return "created" if cree else "updated"
