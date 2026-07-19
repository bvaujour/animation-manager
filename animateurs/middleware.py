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


class JournalAuditMiddleware:
    """Enregistre les écritures réussies sans conserver les secrets ni fichiers."""

    METHODES_AUDITEES = {"POST", "PUT", "PATCH", "DELETE"}
    CHAMPS_SENSIBLES = {"password", "mot_de_passe", "confirmation", "old_password", "new_password", "new_password_confirmation"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method in self.METHODES_AUDITEES and response.status_code < 400:
            self._enregistrer(request, response.status_code)
        return response

    def _enregistrer(self, request, statut_http):
        from .models import JournalAudit

        donnees = {}
        if request.content_type and request.content_type.startswith("application/json"):
            try:
                import json
                donnees = json.loads(request.body.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                donnees = {}
        else:
            donnees = request.POST.dict()

        donnees = {
            cle: ("[masqué]" if cle.lower() in self.CHAMPS_SENSIBLES else valeur)
            for cle, valeur in donnees.items()
            if cle.lower() not in {"csrfmiddlewaretoken"}
        }
        if request.FILES:
            donnees["fichiers"] = [f.name for f in request.FILES.values()]

        utilisateur = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        adresse_ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
        try:
            JournalAudit.objects.create(
                utilisateur=utilisateur,
                methode=request.method,
                chemin=request.path[:500],
                statut_http=statut_http,
                adresse_ip=adresse_ip or None,
                description=self._description(request),
                donnees=donnees,
            )
        except Exception:
            # Le journal ne doit jamais bloquer une action métier réussie.
            return

    @staticmethod
    def _description(request):
        correspondances = {
            "/api/affectations/": "Modification du planning",
            "/api/animateurs/": "Modification d'un salarié",
            "/api/centres/": "Modification d'un lieu",
            "/api/groupes/": "Modification d'un groupe",
            "/api/qualifications/": "Modification d'une qualification",
            "/api/documents/": "Modification d'un document",
            "/api/envois-email/": "Envoi d'un e-mail",
            "/administration/": "Modification de l'administration",
        }
        for prefixe, description in correspondances.items():
            if request.path.startswith(prefixe):
                return description
        return "Action dans l'application"
