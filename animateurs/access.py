from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.shortcuts import redirect


def _refus_json(message="Accès réservé à la direction.", status=403):
    return JsonResponse({"error": message}, status=status)


def profil_utilisateur(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.profil_animateur
    except ObjectDoesNotExist:
        return None


def est_direction(user):
    """Les fonctions de gestion sont réservées aux superusers."""
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))


def connexion_requise_page(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        return view(request, *args, **kwargs)
    return wrapper


def direction_requise(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not est_direction(request.user):
            return redirect("accueil")
        return view(request, *args, **kwargs)
    return wrapper


def direction_requise_api(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _refus_json("Connexion requise.", 401)
        if not est_direction(request.user):
            return _refus_json()
        return view(request, *args, **kwargs)
    return wrapper


def lecture_partagee_api(view):
    """Lecture pour tous les comptes connectés, écriture pour la direction."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _refus_json("Connexion requise.", 401)
        if request.method != "GET" and not est_direction(request.user):
            return _refus_json()
        return view(request, *args, **kwargs)
    return wrapper


def disponibilites_personnelles_api(view):
    @wraps(view)
    def wrapper(request, animateur_id, *args, **kwargs):
        if not request.user.is_authenticated:
            return _refus_json("Connexion requise.", 401)
        if est_direction(request.user):
            return view(request, animateur_id, *args, **kwargs)
        profil = profil_utilisateur(request.user)
        if profil is None or profil.pk != animateur_id:
            return _refus_json("Tu peux uniquement modifier tes propres disponibilités.")
        return view(request, animateur_id, *args, **kwargs)
    return wrapper
