from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect


class ConnexionObligatoireMiddleware:
    """Exige une connexion et refuse les comptes ordinaires sans fiche salarié.

    Un superutilisateur Django est considéré comme un compte maître : il garde
    toujours un accès complet à l'application, même s'il n'est relié à aucune
    fiche salarié. Cela fournit un accès de secours indépendant des données
    métier.
    """

    CHEMINS_PUBLICS = (
        "/connexion/",
        "/admin/login/",
        "/static/",
        "/media/",
    )

    CHEMINS_COMPTE_NON_ASSOCIE = (
        "/deconnexion/",
        "/admin/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _a_un_profil_salarie(user):
        try:
            return user.profil_animateur is not None
        except ObjectDoesNotExist:
            return False

    def __call__(self, request):
        chemin = request.path_info or "/"
        est_public = chemin.startswith(self.CHEMINS_PUBLICS)
        est_api = chemin.startswith("/api/")

        if not request.user.is_authenticated:
            if not est_public and not est_api:
                return redirect_to_login(request.get_full_path())
            return self.get_response(request)

        # Le compte maître ne dépend jamais d'une fiche salarié.
        if request.user.is_superuser:
            return self.get_response(request)

        # Tous les autres comptes de l'application doivent être associés à un
        # salarié. Un utilisateur Django créé par erreur ne peut donc pas
        # contourner le système de rôles.
        if not self._a_un_profil_salarie(request.user):
            if chemin.startswith(self.CHEMINS_COMPTE_NON_ASSOCIE):
                return self.get_response(request)
            if est_api:
                return JsonResponse(
                    {"error": "Ce compte n'est associé à aucun salarié."},
                    status=403,
                )
            return HttpResponseForbidden(
                "Ce compte n'est associé à aucun salarié. "
                "Utilise un compte maître ou associe ce compte depuis la fiche du salarié."
            )

        return self.get_response(request)


class MotDePasseProvisoireMiddleware:
    """Bloque l'application tant que le mot de passe provisoire n'a pas été remplacé."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chemins_autorises = ("/changer-mot-de-passe/", "/deconnexion/", "/static/", "/media/")
        if request.user.is_authenticated and not request.path.startswith(chemins_autorises):
            try:
                profil = request.user.profil_animateur
            except ObjectDoesNotExist:
                profil = None
            if profil is not None and profil.doit_changer_mot_de_passe:
                return redirect("changer_mot_de_passe")
        return self.get_response(request)
