from django.conf import settings

from .access import est_direction
from .models import Document, PeriodeScolaire, TypeAccueil
from .services.types_accueil import regrouper_periodes_vacances


def droits_application(request):
    utilisateur_direction = est_direction(request.user)
    documents_permanents = []
    if getattr(request.user, "is_authenticated", False) and not utilisateur_direction:
        # La navigation animateur reprend uniquement les documents permanents :
        # les documents de semaine restent accessibles depuis le tableau de bord
        # et la bibliothèque complète.
        documents_permanents = list(
            Document.objects.filter(permanent=True, publie=True).order_by("titre")[:6]
        )
    types_accueil = list(TypeAccueil.objects.filter(actif=True)) if getattr(request.user, "is_authenticated", False) else []
    code_demande = request.GET.get("type_accueil")
    if code_demande is not None:
        code_selectionne = code_demande if any(item.code == code_demande for item in types_accueil) else ""
        request.session["type_accueil"] = code_selectionne
    else:
        code_selectionne = request.session.get("type_accueil", "")
        if not any(item.code == code_selectionne for item in types_accueil):
            code_selectionne = ""

    periodes_qs = PeriodeScolaire.objects.select_related("type_accueil").all()
    if code_selectionne:
        periodes_qs = periodes_qs.filter(type_accueil__code=code_selectionne)
    semaines_accueil = list(periodes_qs.order_by("-debut", "ordre", "nom"))
    periodes_accueil = (
        regrouper_periodes_vacances(semaines_accueil)
        if code_selectionne == TypeAccueil.VACANCES
        else semaines_accueil
    )
    periode_demandee = request.GET.get("periode_accueil")
    ids_periodes = {
        str(periode["id"] if isinstance(periode, dict) else periode.pk)
        for periode in periodes_accueil
    }
    if periode_demandee is not None:
        periode_selectionnee = str(periode_demandee) if periode_demandee else None
        if periode_selectionnee not in ids_periodes:
            periode_selectionnee = None
        request.session["periode_accueil"] = periode_selectionnee
    else:
        periode_selectionnee = request.session.get("periode_accueil")
        periode_selectionnee = str(periode_selectionnee) if periode_selectionnee is not None else None
        if periode_selectionnee not in ids_periodes:
            periode_selectionnee = None

    periode_accueil_active = next((
        periode for periode in periodes_accueil
        if str(periode["id"] if isinstance(periode, dict) else periode.pk) == periode_selectionnee
    ), None)
    # Les écrans historiques restent pilotés par leurs semaines. On mémorise
    # donc seulement les identifiants composant la période complète choisie,
    # afin que leurs sélecteurs puissent reprendre ce contexte sans changer
    # aucune API métier ni recopier la notion de période sur leurs objets.
    semaine_ids_contexte = []
    if periode_accueil_active is not None:
        semaine_ids_contexte = (
            list(periode_accueil_active.get("semaine_ids", []))
            if isinstance(periode_accueil_active, dict)
            else [periode_accueil_active.pk]
        )
    request.session["semaines_contexte_travail"] = semaine_ids_contexte

    return {
        "utilisateur_est_direction": utilisateur_direction,
        "documents_permanents_nav": documents_permanents,
        "asset_version": settings.ASSET_VERSION,
        "password_min_length": settings.PASSWORD_MIN_LENGTH,
        "types_accueil": types_accueil,
        "type_accueil_selectionne": code_selectionne,
        "periodes_accueil": periodes_accueil,
        "periode_accueil_selectionnee": periode_selectionnee,
        "periode_accueil_active": periode_accueil_active,
    }
