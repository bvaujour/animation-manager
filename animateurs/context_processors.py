from django.conf import settings

from .access import est_direction


def droits_application(request):
    return {
        "utilisateur_est_direction": est_direction(request.user),
        "asset_version": settings.ASSET_VERSION,
    }
