"""Pages HTML, tableau de bord et exports administratifs."""

import datetime

from django.contrib.auth import get_user_model, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache

from .access import est_direction
from .models import Centre, PeriodeScolaire
from .services.animateur_dashboard import generer_tableau_de_bord_animateur
from .services.comptes import valider_mot_de_passe
from .services.dashboard import generer_tableau_de_bord
from .services.planning_exports import generer_planning_excel, generer_planning_pdf, horaires_manquants_export

# ---------------------------------------------------------------------------
# Pages HTML
# ---------------------------------------------------------------------------
# Chaque vue ci-dessous se contente de rendre un template quasi vide : les
# données sont chargées côté client par le JS correspondant (voir
# static/js/<nom-de-la-page>.js), qui appelle les endpoints API plus bas.


def changer_mot_de_passe(request):
    """Impose le remplacement du mot de passe provisoire à la première connexion."""
    animateur = getattr(request.user, "profil_animateur", None)
    if animateur is None or not animateur.doit_changer_mot_de_passe:
        return redirect("accueil")
    erreur = ""
    if request.method == "POST":
        mot_de_passe = request.POST.get("mot_de_passe", "")
        confirmation = request.POST.get("confirmation", "")
        if mot_de_passe != confirmation:
            erreur = "Les deux mots de passe ne correspondent pas."
        else:
            erreur = valider_mot_de_passe(mot_de_passe, utilisateur=request.user)
        if not erreur:
            request.user.set_password(mot_de_passe)
            request.user.save(update_fields=["password"])
            animateur.doit_changer_mot_de_passe = False
            animateur.save(update_fields=["doit_changer_mot_de_passe"])
            update_session_auth_hash(request, request.user)
            return redirect("accueil")
    return render(request, "registration/changer_mot_de_passe.html", {"erreur": erreur})


def accueil(request):
    contexte = {"active_page": "accueil"}
    if not est_direction(request.user):
        animateur = getattr(request.user, "profil_animateur", None)
        contexte["animateur"] = animateur
        if animateur is not None:
            date_reference = parse_date(request.GET.get("semaine", "")) or timezone.localdate()
            contexte.update(generer_tableau_de_bord_animateur(animateur, date_reference))
    return render(request, "accueil.html", contexte)


def mon_planning(request):
    """Planning et séjours du seul salarié associé au compte connecté."""
    if est_direction(request.user):
        return redirect("planning")
    animateur = getattr(request.user, "profil_animateur", None)
    contexte = {"active_page": "mon_planning", "animateur": animateur}
    if animateur is not None:
        aujourd_hui = timezone.localdate()
        affectations = (
            animateur.affectations.select_related("centre", "evenement")
            .filter(fin__date__gt=aujourd_hui)
            .order_by("debut")
        )
        contexte["centres_affectes"] = Centre.objects.filter(
            affectations__animateur=animateur
        ).distinct().order_by("ordre", "nom")
        # Le modèle Groupe n'ayant pas encore de catégorie, les séjours sont
        # identifiés par leur libellé métier dans le groupe ou le lieu.
        contexte["sejours"] = affectations.filter(
            Q(centre__nom__icontains="séjour")
            | Q(centre__nom__icontains="sejour")
            | Q(evenement__nom__icontains="séjour")
            | Q(evenement__nom__icontains="sejour")
        )
    return render(request, "mon_planning.html", contexte)


def mon_profil(request):
    """Consultation et mise à jour des coordonnées du compte animateur."""
    if est_direction(request.user):
        return redirect("employes")

    animateur = getattr(request.user, "profil_animateur", None)
    message = ""
    erreur = ""
    action = ""

    if request.method == "POST" and animateur is not None:
        action = request.POST.get("action", "coordonnees")

        if action == "coordonnees":
            telephone = request.POST.get("telephone", "").strip()
            email = request.POST.get("email", "").strip().lower()

            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    erreur = "L’adresse e-mail saisie n’est pas valide."

            if not erreur:
                animateur.telephone = telephone
                animateur.email = email
                animateur.save(update_fields=["telephone", "email"])

                request.user.email = email
                request.user.save(update_fields=["email"])
                message = "Tes coordonnées ont bien été mises à jour."

        elif action == "mot_de_passe":
            mot_de_passe = request.POST.get("mot_de_passe", "")
            confirmation = request.POST.get("confirmation", "")

            if mot_de_passe != confirmation:
                erreur = "Les deux mots de passe ne correspondent pas."
            else:
                erreur = valider_mot_de_passe(mot_de_passe, utilisateur=request.user)

            if not erreur:
                request.user.set_password(mot_de_passe)
                request.user.save(update_fields=["password"])
                animateur.doit_changer_mot_de_passe = False
                animateur.save(update_fields=["doit_changer_mot_de_passe"])
                update_session_auth_hash(request, request.user)
                message = "Ton mot de passe a bien été modifié."

    return render(
        request,
        "mon_profil.html",
        {
            "active_page": "mon_profil",
            "animateur": animateur,
            "message": message,
            "erreur": erreur,
            "action": action,
        },
    )


@never_cache
def api_tableau_de_bord(request):
    """Données agrégées de l'ensemble des centres pour une semaine."""

    date_reference = (
        parse_date(request.GET.get("semaine", "")) or parse_date(request.GET.get("date", "")) or timezone.localdate()
    )
    return JsonResponse(generer_tableau_de_bord(date_reference))


def planning(request):
    """Page principale : un calendrier par centre, avec la liste des
    animateurs à glisser-déposer ou à affecter par clic."""
    return render(request, "planning.html", {"active_page": "planning"})


def gestion(request):
    """Gestion des lieux, groupes, qualifications, périodes et documents."""
    onglet = request.GET.get("onglet", "lieux")
    active_page = "documents" if onglet == "documents" else "gestion"
    return render(
        request,
        "gestion.html",
        {
            "active_page": active_page,
            "gestion_onglet": onglet,
        },
    )


def employes(request):
    """Annuaire des salariés, séparé de la rubrique Gestion."""
    return render(request, "employes.html", {"active_page": "employes"})


def employe_detail(request, animateur_id=None):
    """Compatibilité avec les anciennes adresses de fiches salariés.

    La fiche n'est plus rendue dans une page séparée : elle s'ouvre dans le
    panneau droit de l'espace Salariés.
    """
    if animateur_id is None:
        return redirect("/employes/?nouveau=1")
    return redirect(f"/employes/?salarie={animateur_id}")


def recapitulatif(request):
    """Tableau de bord : jours travaillés par animateur/centre et alertes
    de suivi (animateurs jamais affectés, centres inutilisés, etc.)."""
    return render(request, "recapitulatif.html", {"active_page": "recapitulatif"})


def documents(request):
    """Bibliothèque en lecture seule accessible à tous les comptes connectés."""
    return render(request, "documents_partages.html", {"active_page": "documents"})


def mes_disponibilites(request):
    """Espace personnel permettant à un animateur de déclarer ses jours disponibles."""
    if est_direction(request.user):
        return redirect("employes")
    animateur = getattr(request.user, "profil_animateur", None)
    return render(
        request,
        "mes_disponibilites.html",
        {
            "active_page": "disponibilites",
            "animateur": animateur,
            "erreur_profil": animateur is None,
        },
    )


def emails(request):
    """Accès direct au module d’e-mails intégré à l’administration."""
    return redirect("/administration/?onglet=emails")


def administration(request):
    """Exports, e-mails et gestion simple des comptes superuser."""
    User = get_user_model()
    message_admin = ""
    erreur_admin = ""

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create_superuser":
            username = request.POST.get("username", "").strip()
            email = request.POST.get("email", "").strip()
            password = request.POST.get("password", "")
            confirmation = request.POST.get("confirmation", "")
            if not username:
                erreur_admin = "Le nom d’utilisateur est obligatoire."
            elif User.objects.filter(username__iexact=username).exists():
                erreur_admin = "Ce nom d’utilisateur existe déjà."
            elif password != confirmation:
                erreur_admin = "Les deux mots de passe ne correspondent pas."
            else:
                erreur_admin = valider_mot_de_passe(password)
                if not erreur_admin:
                    User.objects.create_superuser(username=username, email=email, password=password)
                    message_admin = f"Le superuser {username} a été créé."
        elif action == "delete_superuser":
            try:
                cible = User.objects.get(pk=request.POST.get("user_id"), is_superuser=True)
            except (User.DoesNotExist, ValueError, TypeError):
                erreur_admin = "Compte superuser introuvable."
            else:
                if cible.pk == request.user.pk:
                    erreur_admin = "Tu ne peux pas supprimer le compte avec lequel tu es connectée."
                elif User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
                    erreur_admin = "Impossible de supprimer le dernier superuser actif."
                else:
                    nom = cible.username
                    cible.delete()
                    message_admin = f"Le superuser {nom} a été supprimé."
        elif action == "change_own_password":
            ancien = request.POST.get("old_password", "")
            nouveau = request.POST.get("new_password", "")
            confirmation = request.POST.get("new_password_confirmation", "")
            if not request.user.check_password(ancien):
                erreur_admin = "L’ancien mot de passe est incorrect."
            elif nouveau != confirmation:
                erreur_admin = "Les deux nouveaux mots de passe ne correspondent pas."
            else:
                erreur_admin = valider_mot_de_passe(nouveau, utilisateur=request.user)
                if not erreur_admin:
                    request.user.set_password(nouveau)
                    request.user.save(update_fields=["password"])
                    update_session_auth_hash(request, request.user)
                    message_admin = "Ton mot de passe a été modifié."

    today = timezone.localdate()
    periodes = list(PeriodeScolaire.objects.order_by("debut", "fin", "ordre", "id"))

    # L'export s'ouvre sur les vacances qui contiennent aujourd'hui. Entre deux
    # semaines, la période enregistrée la plus proche reste le meilleur repère.
    periode_export_courante = min(
        periodes,
        key=lambda periode: 0
        if periode.debut <= today <= periode.fin
        else min(abs((periode.debut - today).days), abs((periode.fin - today).days)),
        default=None,
    )
    for periode in periodes:
        periode.export_annee_ouverte = bool(
            periode_export_courante
            and periode.annee_scolaire == periode_export_courante.annee_scolaire
        )
        periode.export_vacances_ouvertes = bool(
            periode.export_annee_ouverte
            and periode.categorie_vacances == periode_export_courante.categorie_vacances
        )
    semaines_export = sorted(
        periodes,
        key=lambda periode: (-int(periode.annee_scolaire[:4]), periode.debut, periode.ordre, periode.nom),
    )

    dates_disponibles = set()
    for periode in periodes:
        nombre_jours = (periode.fin - periode.debut).days
        dates_disponibles.update(
            periode.debut + datetime.timedelta(days=decalage) for decalage in range(nombre_jours + 1)
        )

    if not dates_disponibles:
        dates_disponibles.update(today + datetime.timedelta(days=decalage) for decalage in range(-183, 184))

    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois_fr = [
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ]
    dates_triees = sorted(dates_disponibles)
    options_dates = [
        {
            "value": jour.isoformat(),
            "label": f"{jours_fr[jour.weekday()].capitalize()} {jour.day} {mois_fr[jour.month - 1]} {jour.year}",
        }
        for jour in dates_triees
    ]

    date_fin = (
        today
        if today in dates_disponibles
        else min(
            dates_triees,
            key=lambda jour: abs((jour - today).days),
        )
    )
    debut_mois = date_fin.replace(day=1)
    dates_avant_fin = [jour for jour in dates_triees if jour <= date_fin]
    date_debut = (
        debut_mois if debut_mois in dates_disponibles else (dates_avant_fin[0] if dates_avant_fin else dates_triees[0])
    )

    active_tab = request.POST.get("onglet") or request.GET.get("onglet") or "export"
    if active_tab not in {"export", "emails", "superusers", "mot-de-passe"}:
        active_tab = "export"

    return render(
        request,
        "administration.html",
        {
            "active_page": "emails" if active_tab == "emails" else "administration",
            "active_tab": active_tab,
            "periode_debut": date_debut.isoformat(),
            "periode_fin": date_fin.isoformat(),
            "options_dates": options_dates,
            "semaines_export": semaines_export,
            "superusers": User.objects.filter(is_superuser=True).order_by("username"),
            "message_admin": message_admin,
            "erreur_admin": erreur_admin,
        },
    )


def _periode_export(request):
    ids_bruts = request.GET.getlist("periode_ids")
    if ids_bruts:
        try:
            ids = {int(valeur) for valeur in ids_bruts}
        except ValueError:
            return None, None, None, "La sélection des semaines est invalide."
        periodes = list(PeriodeScolaire.objects.filter(pk__in=ids))
        if not ids or len(periodes) != len(ids):
            return None, None, None, "Une semaine sélectionnée est introuvable."
        jours = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in periodes
            for decalage in range((periode.fin - periode.debut).days + 1)
        }
        return min(jours), max(jours), jours, None

    debut = parse_date(request.GET.get("debut", ""))
    fin = parse_date(request.GET.get("fin", ""))
    if not debut or not fin:
        return None, None, None, "Sélectionne au moins une semaine."
    if fin < debut:
        return None, None, None, "La date de fin doit être postérieure ou égale à la date de début."
    if (fin - debut).days > 366:
        return None, None, None, "La période d'export ne peut pas dépasser 366 jours."
    return debut, fin, None, None


def api_verification_export_planning(request):
    """Vérifie les horaires juste avant le téléchargement d'un planning."""
    debut, fin, jours_selectionnes, erreur = _periode_export(request)
    if erreur:
        return JsonResponse({"error": erreur}, status=400)
    manquants = horaires_manquants_export(debut, fin, jours_selectionnes)
    return JsonResponse(
        {
            "nombre": len(manquants),
            "manquants": manquants[:20],
        }
    )


def export_planning_excel(request):
    debut, fin, jours_selectionnes, erreur = _periode_export(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    contenu = generer_planning_excel(debut, fin, jours_selectionnes)
    response = HttpResponse(
        contenu,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="planning_{debut:%Y%m%d}_{fin:%Y%m%d}.xlsx"'
    return response


def export_planning_pdf(request):
    debut, fin, jours_selectionnes, erreur = _periode_export(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    contenu = generer_planning_pdf(debut, fin, jours_selectionnes)
    response = HttpResponse(contenu, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="planning_{debut:%Y%m%d}_{fin:%Y%m%d}.pdf"'
    return response
