"""Pages HTML, tableau de bord et exports administratifs."""

import datetime
import json

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache

from .access import est_direction
from .models import (
    Affectation,
    Animateur,
    Centre,
    DemandeMateriel,
    InformationAnimateur,
    PeriodeScolaire,
    StatutPreparationSemaine,
)
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


def _centre_affectation_animateur(animateur, jour):
    if animateur is None or jour is None:
        return None
    debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
    fin = debut + datetime.timedelta(days=1)
    return (
        Affectation.objects.filter(animateur=animateur, debut__lt=fin, fin__gt=debut)
        .select_related("centre")
        .order_by("debut")
        .values_list("centre_id", flat=True)
        .first()
    )


def accueil(request):
    contexte = {"active_page": "accueil"}
    if not est_direction(request.user):
        animateur = getattr(request.user, "profil_animateur", None)
        contexte["animateur"] = animateur
        message_materiel = ""
        erreur_materiel = ""

        if request.method == "POST" and request.POST.get("module") == "materiel":
            action = request.POST.get("action", "creer")
            if animateur is None:
                erreur_materiel = "Ton compte n’est pas rattaché à une fiche salarié."
            elif action == "supprimer":
                try:
                    demande = DemandeMateriel.objects.get(pk=request.POST.get("demande_id"), animateur=animateur)
                except (DemandeMateriel.DoesNotExist, ValueError, TypeError):
                    erreur_materiel = "Cette demande n’existe plus ou ne t’appartient pas."
                else:
                    demande.delete()
                    message_materiel = "La demande a été supprimée."
            elif action == "creer":
                materiel = request.POST.get("materiel", "").strip()
                date_besoin = parse_date(request.POST.get("date_besoin", ""))
                try:
                    quantite = int(request.POST.get("quantite", "1"))
                except (TypeError, ValueError):
                    quantite = 0
                try:
                    centre = Centre.objects.get(pk=int(request.POST.get("centre_id", "")))
                except (TypeError, ValueError, Centre.DoesNotExist):
                    centre = None

                if not materiel:
                    erreur_materiel = "Indique le matériel demandé."
                elif quantite < 1:
                    erreur_materiel = "La quantité doit être au moins égale à 1."
                elif date_besoin is None:
                    erreur_materiel = "Indique une date précise pour cette demande."
                elif centre is None:
                    erreur_materiel = "Choisis le centre concerné."
                else:
                    DemandeMateriel.objects.create(
                        animateur=animateur,
                        centre=centre,
                        materiel=materiel,
                        quantite=quantite,
                        date_besoin=date_besoin,
                    )
                    message_materiel = "Ta demande de matériel a été enregistrée."

        if animateur is not None:
            date_reference = parse_date(request.GET.get("semaine", "")) or timezone.localdate()
            contexte.update(generer_tableau_de_bord_animateur(animateur, date_reference))
            contexte.update({
                "planning_jours_affectes": sum(1 for jour in contexte["jours"] if jour.get("travaille")),
                "infos_sorties_count": len(contexte["sorties"]),
                "infos_documents_count": len(contexte["documents"]),
                "infos_reunions_count": len(contexte["reunions"]),
                "infos_infos_count": len(contexte.get("informations", [])),
                "infos_infos_important_count": sum(
                    1 for information in contexte.get("informations", []) if information.est_importante
                ),
            })
            contexte.update({
                "centres_materiel": Centre.objects.all(),
                "demandes_materiel": DemandeMateriel.objects.filter(animateur=animateur).select_related("centre"),
                "message_materiel": message_materiel,
                "erreur_materiel": erreur_materiel,
            })
    return render(request, "accueil.html", contexte)


def _contexte_portail_animateur(request, active_page):
    """Contexte partagé par les espaces animateur dépendant d'une semaine."""
    animateur = getattr(request.user, "profil_animateur", None)
    contexte = {"active_page": active_page, "animateur": animateur}
    if animateur is not None:
        date_reference = parse_date(request.GET.get("semaine", "")) or timezone.localdate()
        contexte.update(
            generer_tableau_de_bord_animateur(
                animateur,
                date_reference,
                inclure_programmes=active_page == "plannings",
            )
        )
    return contexte


def plannings_animateur(request):
    if est_direction(request.user):
        return redirect("planning")
    return render(request, "plannings_animateur.html", _contexte_portail_animateur(request, "plannings"))


def infos_animateur(request):
    if est_direction(request.user):
        return redirect("documents")
    return render(request, "infos_animateur.html", _contexte_portail_animateur(request, "infos"))


def sorties_animateur(request):
    if est_direction(request.user):
        return redirect("sorties")
    return render(request, "sorties_animateur.html", _contexte_portail_animateur(request, "sorties_animateur"))


def documents_animateur(request):
    if est_direction(request.user):
        return redirect("documents")
    return render(request, "documents_animateur.html", _contexte_portail_animateur(request, "documents_animateur"))


@never_cache
def api_mon_centre_affectation(request):
    if est_direction(request.user):
        return JsonResponse({"centre_id": None})
    animateur = getattr(request.user, "profil_animateur", None)
    jour = parse_date(request.GET.get("date", ""))
    return JsonResponse({"centre_id": _centre_affectation_animateur(animateur, jour)})



def demandes_materiel(request):
    """Traitement des demandes côté direction; côté animateur tout est sur le tableau de bord."""
    direction = est_direction(request.user)
    animateur = getattr(request.user, "profil_animateur", None)
    message = ""
    erreur = ""

    if request.method == "POST":
        action = request.POST.get("action", "creer")

        if action == "supprimer":
            demande_id = request.POST.get("demande_id")
            demandes_autorisees = DemandeMateriel.objects.all()
            if not direction:
                if animateur is None:
                    demandes_autorisees = DemandeMateriel.objects.none()
                else:
                    demandes_autorisees = demandes_autorisees.filter(animateur=animateur)
            try:
                demande = demandes_autorisees.get(pk=demande_id)
            except (DemandeMateriel.DoesNotExist, ValueError, TypeError):
                erreur = "Cette demande n’existe plus ou tu ne peux pas la supprimer."
            else:
                demande.delete()
                message = "La demande de matériel a été supprimée."

        elif direction and action in {"valider", "remettre_en_attente"}:
            demande_id = request.POST.get("demande_id")
            try:
                demande = DemandeMateriel.objects.get(pk=demande_id)
            except (DemandeMateriel.DoesNotExist, ValueError, TypeError):
                erreur = "Cette demande n’existe plus."
            else:
                if action == "valider":
                    demande.statut = DemandeMateriel.STATUT_VALIDEE
                    demande.date_validation = timezone.now()
                    demande.validee_par = request.user
                    message = "La demande a été marquée comme validée."
                else:
                    demande.statut = DemandeMateriel.STATUT_EN_ATTENTE
                    demande.date_validation = None
                    demande.validee_par = None
                    message = "La demande a été remise en attente."
                demande.save(update_fields=["statut", "date_validation", "validee_par"])

        elif not direction and action == "creer":
            if animateur is None:
                erreur = "Ton compte n’est pas rattaché à une fiche salarié."
            else:
                materiel = request.POST.get("materiel", "").strip()
                date_besoin = parse_date(request.POST.get("date_besoin", ""))
                try:
                    quantite = int(request.POST.get("quantite", "1"))
                except (TypeError, ValueError):
                    quantite = 0
                try:
                    centre = Centre.objects.get(pk=int(request.POST.get("centre_id", "")))
                except (TypeError, ValueError, Centre.DoesNotExist):
                    centre = None

                if not materiel:
                    erreur = "Indique le matériel demandé."
                elif quantite < 1:
                    erreur = "La quantité doit être au moins égale à 1."
                elif date_besoin is None:
                    erreur = "Indique une date précise pour cette demande."
                elif centre is None:
                    erreur = "Choisis le centre concerné."
                else:
                    DemandeMateriel.objects.create(
                        animateur=animateur,
                        centre=centre,
                        materiel=materiel,
                        quantite=quantite,
                        date_besoin=date_besoin,
                    )
                    message = "Ta demande de matériel a été enregistrée."
        else:
            erreur = "Action non autorisée."

    if direction:
        demandes = DemandeMateriel.objects.select_related("animateur", "centre", "validee_par").all()
    elif animateur is not None:
        demandes = DemandeMateriel.objects.filter(animateur=animateur).select_related("animateur", "centre", "validee_par")
    else:
        demandes = DemandeMateriel.objects.none()

    semaine_portail = None
    if not direction and animateur is not None:
        date_reference = parse_date(request.GET.get("semaine", "")) or timezone.localdate()
        semaine_portail = generer_tableau_de_bord_animateur(animateur, date_reference)["semaine"]

    return render(
        request,
        "demandes_materiel.html",
        {
            "active_page": "materiel",
            "direction": direction,
            "animateur": animateur,
            "centres_materiel": Centre.objects.all() if not direction else None,
            "demandes": demandes,
            "message": message,
            "erreur": erreur,
            "semaine": semaine_portail,
        },
    )


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
            adresse = request.POST.get("adresse", "").strip()

            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    erreur = "L’adresse e-mail saisie n’est pas valide."

            if not erreur:
                animateur.telephone = telephone
                animateur.email = email
                animateur.adresse = adresse
                animateur.save(update_fields=["telephone", "email", "adresse"])

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


@never_cache
def api_statut_preparation_semaine(request):
    """Force ou rétablit le seul libellé de préparation d'une semaine."""

    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Données invalides."}, status=400)
    date_reference = parse_date(str(payload.get("semaine", "")))
    if date_reference is None or not isinstance(payload.get("forcer"), bool):
        return JsonResponse({"error": "Semaine ou statut invalide."}, status=400)
    debut_semaine = date_reference - datetime.timedelta(days=date_reference.weekday())
    statut, _ = StatutPreparationSemaine.objects.update_or_create(
        debut_semaine=debut_semaine,
        defaults={
            "est_force_prete": payload["forcer"],
            "modifie_par": request.user,
        },
    )
    return JsonResponse(
        {
            "debut_semaine": debut_semaine.isoformat(),
            "est_force_prete": statut.est_force_prete,
            "modifie_par": request.user.get_username(),
            "modifie_le": statut.modifie_le.isoformat(),
        }
    )


def planning(request):
    """Page principale des affectations et des effectifs enfants."""
    if request.GET.get("mode") == "temps-travail":
        return redirect("/recapitulatif/?onglet=temps-travail")
    return render(request, "planning.html", {"active_page": "planning"})



def temps_travail(request):
    """Conserve les anciens liens vers la saisie désormais intégrée à Paie."""
    return redirect("/recapitulatif/?onglet=temps-travail")

def gestion(request):
    """Gestion des référentiels, documents et informations du portail animateur."""
    onglet = request.GET.get("onglet", "lieux")

    if request.method == "POST" and request.POST.get("module") == "informations-animateurs":
        action = request.POST.get("action", "enregistrer")
        information_id = request.POST.get("information_id")
        information = None
        if information_id:
            try:
                information = InformationAnimateur.objects.get(pk=information_id)
            except (InformationAnimateur.DoesNotExist, TypeError, ValueError):
                messages.error(request, "Cette information n’existe plus.")
                return redirect("/gestion/?onglet=informations")

        if action == "supprimer":
            if information is None:
                messages.error(request, "Information introuvable.")
            else:
                information.delete()
                messages.success(request, "L’information a été supprimée.")
            return redirect("/gestion/?onglet=informations")

        if action in {"publier", "depublier"}:
            if information is None:
                messages.error(request, "Information introuvable.")
            else:
                information.publie = action == "publier"
                information.save(update_fields=["publie", "date_modification"])
                messages.success(
                    request,
                    "L’information est maintenant publiée." if information.publie else "L’information a été remise en brouillon.",
                )
            return redirect("/gestion/?onglet=informations")

        titre = request.POST.get("titre", "").strip()
        message = request.POST.get("message", "").strip()
        date_debut = parse_date(request.POST.get("date_debut", ""))
        date_fin = parse_date(request.POST.get("date_fin", ""))
        importance = request.POST.get("importance", InformationAnimateur.IMPORTANCE_NORMALE)
        cible = request.POST.get("cible", "tous")
        tous_animateurs = cible != "selection"
        animateur_ids = request.POST.getlist("animateur_ids")
        publie = request.POST.get("publie") == "on"

        erreurs = []
        if not titre:
            erreurs.append("Le titre est obligatoire.")
        if not message:
            erreurs.append("Le message est obligatoire.")
        if date_debut is None or date_fin is None:
            erreurs.append("La période d’affichage doit être renseignée.")
        elif date_fin < date_debut:
            erreurs.append("La date de fin doit être postérieure ou égale à la date de début.")
        if importance not in dict(InformationAnimateur.IMPORTANCE_CHOICES):
            erreurs.append("Le niveau d’importance est invalide.")
        if not tous_animateurs and not animateur_ids:
            erreurs.append("Sélectionne au moins un animateur ou choisis Toute l’équipe.")

        animateurs_cibles = list(Animateur.objects.filter(pk__in=animateur_ids)) if animateur_ids else []
        if not tous_animateurs and len(animateurs_cibles) != len(set(animateur_ids)):
            erreurs.append("Une partie des animateurs sélectionnés n’existe plus.")

        if erreurs:
            for erreur in erreurs:
                messages.error(request, erreur)
            query = "?onglet=informations"
            if information is not None:
                query += f"&information={information.pk}"
            return redirect(f"/gestion/{query}")

        if information is None:
            information = InformationAnimateur(auteur=request.user)
        information.titre = titre
        information.message = message
        information.date_debut = date_debut
        information.date_fin = date_fin
        information.importance = importance
        information.tous_animateurs = tous_animateurs
        information.publie = publie
        try:
            information.full_clean()
        except ValidationError as exc:
            for messages_champ in exc.message_dict.values():
                for erreur in messages_champ:
                    messages.error(request, erreur)
            query = "?onglet=informations"
            if information.pk:
                query += f"&information={information.pk}"
            return redirect(f"/gestion/{query}")
        information.save()
        information.animateurs.set([] if tous_animateurs else animateurs_cibles)
        messages.success(request, "L’information a été enregistrée.")
        return redirect("/gestion/?onglet=informations")

    information_editee = None
    if onglet == "informations" and request.GET.get("information"):
        try:
            information_editee = InformationAnimateur.objects.prefetch_related("animateurs").get(
                pk=request.GET.get("information")
            )
        except (InformationAnimateur.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Cette information n’existe plus.")

    return render(
        request,
        "gestion.html",
        {
            "active_page": "gestion",
            "gestion_onglet": onglet,
            "informations_animateurs": InformationAnimateur.objects.select_related("auteur").prefetch_related("animateurs"),
            "information_editee": information_editee,
            "information_editee_ids": [item.pk for item in information_editee.animateurs.all()] if information_editee else [],
            "animateurs_informations": Animateur.objects.order_by("nom", "prenom"),
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
    """La bibliothèque animateur est intégrée au tableau de bord."""
    if not est_direction(request.user):
        return redirect("accueil")
    return render(request, "documents_partages.html", {"active_page": "documents"})


def mes_disponibilites(request):
    """Espace personnel permettant à un animateur de déclarer ses jours disponibles."""
    if est_direction(request.user):
        return redirect("employes")
    return redirect("mon_profil")


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
