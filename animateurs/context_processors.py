from django.conf import settings

from .access import est_direction
from .models import Document


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
    return {
        "utilisateur_est_direction": utilisateur_direction,
        "documents_permanents_nav": documents_permanents,
        "asset_version": settings.ASSET_VERSION,
        "password_min_length": settings.PASSWORD_MIN_LENGTH,
    }
