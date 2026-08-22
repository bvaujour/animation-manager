"""Services de lecture des accueils datés d'un lieu physique.

Le M2M ``Centre.types_accueil`` reste conservé pour les écrans historiques.
``AccueilCentre`` devient la couche métier qui distingue les accueils réels
(Vacances, Périscolaire, Périscolaire · Mercredi...) sans dupliquer le lieu.
"""

from django.core.exceptions import ValidationError
from django.db.models import Q

from ..models import AccueilCentre, PeriodeCalendrier, TypeAccueil


TYPES_ACCUEIL_LIEU = (TypeAccueil.VACANCES, TypeAccueil.PERISCOLAIRE)


def _code_type(type_accueil):
    return getattr(type_accueil, "code", str(type_accueil or ""))


def accueils_centres(centre, type_accueil=None, jour=None):
    if not centre:
        return AccueilCentre.objects.none()
    qs = AccueilCentre.objects.filter(centre=centre).select_related("type_accueil")
    if type_accueil is not None:
        type_id = getattr(type_accueil, "pk", None)
        if type_id:
            qs = qs.filter(type_accueil_id=type_id)
        else:
            qs = qs.filter(type_accueil__code=_code_type(type_accueil))
    if jour is not None:
        qs = qs.filter(
            Q(date_debut__isnull=True) | Q(date_debut__lte=jour),
            Q(date_fin__isnull=True) | Q(date_fin__gte=jour),
        )
    return qs.order_by("type_accueil__ordre", "libelle", "id")


def accueil_centre(centre, type_accueil, jour=None, modalite=None):
    """Résout l'accueil précis lorsqu'un contexte suffit à lever l'ambiguïté."""
    qs = accueils_centres(centre, type_accueil, jour=jour)
    code = _code_type(type_accueil)
    if code == TypeAccueil.PERISCOLAIRE and jour is not None and modalite is not None:
        reference = (
            PeriodeCalendrier.objects.filter(
                categorie=PeriodeCalendrier.SCOLAIRE,
                debut__lte=jour,
                fin__gte=jour,
            )
            .order_by("-debut", "id")
            .first()
        )
        if reference is not None:
            ouverture = (
                qs.filter(
                    ouvertures_periodes__periode_calendrier=reference,
                    ouvertures_periodes__modalite_periscolaire=modalite,
                    ouvertures_periodes__jour_semaine=jour.weekday(),
                    ouvertures_periodes__actif=True,
                )
                .distinct()
                .first()
            )
            if ouverture is not None:
                return ouverture
    elements = list(qs[:2])
    return elements[0] if len(elements) == 1 else None


def accueil_actif_le(centre, type_accueil, jour):
    qs = accueils_centres(centre, type_accueil, jour=jour)
    if qs.exists():
        return True
    if accueils_centres(centre, type_accueil).exists():
        return False
    code = _code_type(type_accueil)
    return centre.types_accueil.filter(code=code, actif=True).exists()


def valider_contexte_accueil(evenement, type_accueil=None, modalite=None):
    """Garantit qu'une écriture reste dans l'accueil propre au groupe.

    Les anciennes instances sans ``AccueilCentre`` restent tolérées pour la
    compatibilité. Dès qu'un groupe appartient à un accueil précis, ce dernier
    devient la source de vérité : un type d'accueil contradictoire est refusé.
    """

    if evenement is None:
        return type_accueil

    accueil = getattr(evenement, "accueil_centre", None)
    if getattr(evenement, "accueil_centre_id", None):
        attendu = accueil.type_accueil
        if type_accueil is not None:
            type_id = getattr(type_accueil, "pk", None)
            code = _code_type(type_accueil)
            if (type_id and type_id != attendu.pk) or (not type_id and code != attendu.code):
                raise ValidationError(
                    f"Le groupe appartient à l'accueil {attendu.nom} et ne peut pas être utilisé en {getattr(type_accueil, 'nom', code)}."
                )
        type_accueil = attendu

    if modalite is not None and _code_type(type_accueil) != TypeAccueil.PERISCOLAIRE:
        raise ValidationError("Un créneau périscolaire ne peut être utilisé qu'en Périscolaire.")
    return type_accueil


def centres_avec_accueil_sur_periode(queryset, type_accueil, debut=None, fin=None):
    code = _code_type(type_accueil)
    if not code:
        return queryset
    filtres_dates = Q()
    if debut:
        filtres_dates &= Q(accueils__date_fin__isnull=True) | Q(accueils__date_fin__gte=debut)
    if fin:
        filtres_dates &= Q(accueils__date_debut__isnull=True) | Q(accueils__date_debut__lte=fin)
    avec_ligne = Q(accueils__type_accueil__code=code) & filtres_dates
    legacy = Q(accueils__isnull=True, types_accueil__code=code)
    return queryset.filter(avec_ligne | legacy).distinct()
