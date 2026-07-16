"""Règles métier de gestion des équipes rattachées aux centres."""

from __future__ import annotations

import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum

from animateurs.models import Centre, Equipe


def parse_heure_optionnelle(value):
    """Convertit ``HH:MM`` en ``datetime.time`` ou renvoie ``None``.

    Une chaîne vide signifie volontairement « pas d'horaire spécifique ».
    """

    if value in (None, ""):
        return None
    if isinstance(value, datetime.time):
        return value
    try:
        return datetime.time.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError("L'heure doit être au format HH:MM.") from exc


def synchroniser_effectif_centre(centre: Centre) -> int:
    """Aligne l'effectif historique du centre sur ses équipes actives.

    Le planning actuel reste encore basé sur ``Centre.effectif_cible``.
    Pendant cette étape transitoire, on le maintient donc égal à la somme des
    effectifs cibles des équipes actives afin que les écrans existants gardent
    un total cohérent.
    """

    total = (
        centre.equipes.filter(active=True)
        .aggregate(total=Sum("effectif_cible"))["total"]
        or 0
    )
    Centre.objects.filter(pk=centre.pk).update(effectif_cible=total)
    centre.effectif_cible = total
    return total


def prochain_ordre(centre: Centre) -> int:
    maximum = centre.equipes.aggregate(maximum=Max("ordre"))["maximum"]
    return (maximum if maximum is not None else -1) + 1


def _valider_equipe(equipe: Equipe) -> None:
    try:
        equipe.full_clean()
    except ValidationError:
        raise


def creer_equipe(*, centre: Centre, nom: str, effectif_cible: int = 1,
                  active: bool = True, heure_debut=None, heure_fin=None) -> Equipe:
    nom = (nom or "").strip()
    if not nom:
        raise ValidationError("Le nom de l'équipe est obligatoire.")
    if effectif_cible < 1:
        raise ValidationError("L'effectif cible doit être d'au moins 1.")

    equipe = Equipe(
        centre=centre,
        nom=nom,
        effectif_cible=effectif_cible,
        active=active,
        ordre=prochain_ordre(centre),
        heure_debut=parse_heure_optionnelle(heure_debut),
        heure_fin=parse_heure_optionnelle(heure_fin),
    )
    _valider_equipe(equipe)

    with transaction.atomic():
        equipe.save()
        synchroniser_effectif_centre(centre)
    return equipe


def modifier_equipe(equipe: Equipe, *, nom=None, effectif_cible=None,
                     active=None, heure_debut=None, heure_fin=None,
                     horaires_fournis=False) -> Equipe:
    if nom is not None:
        nom = str(nom).strip()
        if not nom:
            raise ValidationError("Le nom de l'équipe est obligatoire.")
        equipe.nom = nom

    if effectif_cible is not None:
        effectif_cible = int(effectif_cible)
        if effectif_cible < 1:
            raise ValidationError("L'effectif cible doit être d'au moins 1.")
        equipe.effectif_cible = effectif_cible

    if active is not None:
        active = bool(active)
        if not active and equipe.active:
            autre_active = equipe.centre.equipes.filter(active=True).exclude(pk=equipe.pk).exists()
            if not autre_active:
                raise ValidationError("Un centre doit conserver au moins une équipe active.")
        equipe.active = active

    if horaires_fournis:
        equipe.heure_debut = parse_heure_optionnelle(heure_debut)
        equipe.heure_fin = parse_heure_optionnelle(heure_fin)

    _valider_equipe(equipe)

    with transaction.atomic():
        equipe.save()
        synchroniser_effectif_centre(equipe.centre)
    return equipe


def supprimer_equipe(equipe: Equipe) -> None:
    centre = equipe.centre
    if equipe.affectations.exists():
        raise ValidationError(
            "Cette équipe contient des affectations et ne peut pas être supprimée. "
            "Désactive-la ou déplace d'abord ses affectations."
        )
    if centre.equipes.exclude(pk=equipe.pk).count() == 0:
        raise ValidationError("Un centre doit conserver au moins une équipe.")
    if equipe.active and not centre.equipes.filter(active=True).exclude(pk=equipe.pk).exists():
        raise ValidationError("Un centre doit conserver au moins une équipe active.")

    with transaction.atomic():
        equipe.delete()
        synchroniser_effectif_centre(centre)


def reordonner_equipes(centre: Centre, equipe_ids: list[int]) -> None:
    equipes = list(centre.equipes.all())
    ids_existants = {equipe.id for equipe in equipes}
    if set(equipe_ids) != ids_existants or len(equipe_ids) != len(ids_existants):
        raise ValidationError("La liste d'équipes à réordonner est incomplète ou invalide.")

    equipes_par_id = {equipe.id: equipe for equipe in equipes}
    with transaction.atomic():
        for ordre, equipe_id in enumerate(equipe_ids):
            equipe = equipes_par_id[equipe_id]
            if equipe.ordre != ordre:
                equipe.ordre = ordre
                equipe.save(update_fields=["ordre"])
