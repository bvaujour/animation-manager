"""
Vues de l'application "animateurs".

Ce fichier regroupe :
  - les pages HTML (rendues via render(), pas grand-chose dedans : le vrai
    contenu est chargé en JS via les endpoints API ci-dessous) ;
  - une API JSON "maison" (pas de Django REST Framework ici, on répond
    directement avec JsonResponse) utilisée par les fichiers JS dans
    static/js/ (planning.js, gestion.js, recapitulatif.js).

Convention utilisée partout : les endpoints qui modifient des données
renvoient soit l'objet créé/modifié en JSON, soit {"error": "..."} avec un
code HTTP adapté (400 = requête invalide, 404 = introuvable,
409 = conflit métier comme un doublon ou un code déjà pris).
"""

import datetime
import json
import logging
import re
import secrets
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .access import est_direction
from .models import (
    Affectation,
    Animateur,
    Centre,
    ContactEmailExterne,
    DestinataireEnvoiEmail,
    Disponibilite,
    Document,
    EnvoiEmail,
    EquivalenceQualification,
    Evenement,
    EffectifEnfantsJour,
    JournalAudit,
    ModeleEmail,
    PeriodeScolaire,
    Qualification,
    normaliser_cle_unique,
)
from .services.affectations import creer_affectation, modifier_affectation
from .services.animateurs import (
    appliquer_centres_hierarchises,
    normaliser_centres_hierarchises,
    normaliser_evenement_preferee,
)
from .services.calendrier_scolaire import (
    CalendrierScolaireError,
    recuperer_semaines,
)
from .services.centres import prochain_ordre_centre, reordonner_centres
from .services.dates import parse_to_aware_datetime
from .services.disponibilites import fusionner_et_nettoyer_disponibilites
from .services.dashboard import generer_tableau_de_bord
from .services.documents import valider_periode_document
from .services.emails import (
    ConfigurationEmailError,
    PiecesJointesError,
    charger_pieces_jointes,
    connexion_email,
    envoyer_un_message,
    rendre_variables_email,
    statut_configuration_email,
    variables_email_disponibles,
)
from .services.evenements import (
    FermetureAvecAffectationsError,
    creer_evenement,
    modifier_evenement,
    reordonner_evenements,
    supprimer_evenement,
)
from .services.planning_exports import generer_planning_excel, generer_planning_pdf
from .services.recapitulatif import generer_recapitulatif
from .services.serializers import (
    affectation_to_event,
    animateur_to_dict,
    centre_to_dict,
    document_to_dict,
    evenement_to_dict,
    qualification_to_dict,
)

ANIMATEUR_COLOR_PALETTE = (
    "#2563EB", "#7C3AED", "#DB2777", "#DC2626",
    "#EA580C", "#CA8A04", "#16A34A", "#059669",
    "#0891B2", "#4F46E5", "#9333EA", "#475569",
)


def _nom_utilisateur_disponible(prenom, nom):
    User = get_user_model()
    base = slugify(f"{prenom}.{nom}") or "utilisateur"
    base = base[:140]
    candidat = base
    numero = 2
    while User.objects.filter(username=candidat).exists():
        suffixe = f".{numero}"
        candidat = f"{base[:150-len(suffixe)]}{suffixe}"
        numero += 1
    return candidat


def _mot_de_passe_provisoire():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(14))


def _synchroniser_droits_compte(animateur):
    """Un compte lié à un salarié est toujours un compte Animateur ordinaire."""
    utilisateur = animateur.utilisateur
    if utilisateur is None:
        return
    utilisateur.email = animateur.email or utilisateur.email
    utilisateur.first_name = animateur.prenom
    utilisateur.last_name = animateur.nom
    utilisateur.is_staff = False
    utilisateur.is_superuser = False
    utilisateur.save(update_fields=["email", "first_name", "last_name", "is_staff", "is_superuser"])


def _creer_compte_animateur(animateur):
    if animateur.utilisateur_id:
        return None
    User = get_user_model()
    mot_de_passe = _mot_de_passe_provisoire()
    utilisateur = User.objects.create_user(
        username=_nom_utilisateur_disponible(animateur.prenom, animateur.nom),
        email=animateur.email,
        password=mot_de_passe,
        first_name=animateur.prenom,
        last_name=animateur.nom,
    )
    animateur.utilisateur = utilisateur
    animateur.doit_changer_mot_de_passe = True
    animateur.save(update_fields=["utilisateur", "doit_changer_mot_de_passe"])
    _synchroniser_droits_compte(animateur)
    return {"username": utilisateur.username, "temporary_password": mot_de_passe}


def _traiter_acces_compte(animateur, payload):
    """Applique les actions de compte demandées et renvoie d'éventuels identifiants temporaires."""
    if animateur.role != Animateur.ROLE_ANIMATEUR:
        animateur.role = Animateur.ROLE_ANIMATEUR
        animateur.save(update_fields=["role"])

    identifiants = None
    if payload.get("create_access") and not animateur.utilisateur_id:
        identifiants = _creer_compte_animateur(animateur)

    if payload.get("remove_access") and animateur.utilisateur_id:
        utilisateur = animateur.utilisateur
        animateur.utilisateur = None
        animateur.save(update_fields=["utilisateur"])
        utilisateur.delete()
        return None

    if animateur.utilisateur_id:
        utilisateur = animateur.utilisateur
        if "access_active" in payload:
            utilisateur.is_active = bool(payload.get("access_active"))
            utilisateur.save(update_fields=["is_active"])
        _synchroniser_droits_compte(animateur)
        if payload.get("reset_password"):
            mot_de_passe = _mot_de_passe_provisoire()
            utilisateur.set_password(mot_de_passe)
            utilisateur.save(update_fields=["password"])
            animateur.doit_changer_mot_de_passe = True
            animateur.save(update_fields=["doit_changer_mot_de_passe"])
            identifiants = {"username": utilisateur.username, "temporary_password": mot_de_passe}
    return identifiants

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
        if len(mot_de_passe) < 8:
            erreur = "Le mot de passe doit contenir au moins 8 caractères."
        elif mot_de_passe != confirmation:
            erreur = "Les deux mots de passe ne correspondent pas."
        else:
            request.user.set_password(mot_de_passe)
            request.user.save(update_fields=["password"])
            animateur.doit_changer_mot_de_passe = False
            animateur.save(update_fields=["doit_changer_mot_de_passe"])
            update_session_auth_hash(request, request.user)
            return redirect("accueil")
    return render(request, "registration/changer_mot_de_passe.html", {"erreur": erreur})


def accueil(request):
    return render(request, "accueil.html", {"active_page": "accueil"})


@never_cache
def api_tableau_de_bord(request):
    """Données agrégées du poste de pilotage de la direction."""

    date_reference = parse_date(request.GET.get("date", "")) or timezone.localdate()
    centre_id_brut = request.GET.get("centre_id", "").strip()
    centre_id = None
    if centre_id_brut:
        try:
            centre_id = int(centre_id_brut)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Le centre sélectionné est invalide."}, status=400)
        if not Centre.objects.filter(pk=centre_id).exists():
            return JsonResponse({"error": "Le centre sélectionné est introuvable."}, status=404)

    return JsonResponse(generer_tableau_de_bord(date_reference, centre_id=centre_id))


def planning(request):
    """Page principale : un calendrier par centre, avec la liste des
    animateurs à glisser-déposer ou à affecter par clic."""
    return render(request, "planning.html", {"active_page": "planning"})



def gestion(request):
    """Gestion des lieux, groupes, qualifications et périodes."""
    return render(request, "gestion.html", {"active_page": "gestion"})


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
    if animateur is None:
        return render(request, "mes_disponibilites.html", {
            "active_page": "disponibilites",
            "animateur": None,
            "erreur_profil": True,
        })
    return render(request, "mes_disponibilites.html", {
        "active_page": "disponibilites",
        "animateur": animateur,
        "erreur_profil": False,
    })


def emails(request):
    """Ancienne adresse conservée : les e-mails sont maintenant dans Administration."""
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
            elif len(password) < 8:
                erreur_admin = "Le mot de passe doit contenir au moins 8 caractères."
            elif password != confirmation:
                erreur_admin = "Les deux mots de passe ne correspondent pas."
            else:
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
            elif len(nouveau) < 8:
                erreur_admin = "Le nouveau mot de passe doit contenir au moins 8 caractères."
            elif nouveau != confirmation:
                erreur_admin = "Les deux nouveaux mots de passe ne correspondent pas."
            else:
                request.user.set_password(nouveau)
                request.user.save(update_fields=["password"])
                update_session_auth_hash(request, request.user)
                message_admin = "Ton mot de passe a été modifié."

    today = timezone.localdate()
    periodes = list(PeriodeScolaire.objects.order_by("debut", "fin", "ordre", "id"))

    dates_disponibles = set()
    for periode in periodes:
        nombre_jours = (periode.fin - periode.debut).days
        dates_disponibles.update(
            periode.debut + datetime.timedelta(days=decalage)
            for decalage in range(nombre_jours + 1)
        )

    if not dates_disponibles:
        dates_disponibles.update(
            today + datetime.timedelta(days=decalage)
            for decalage in range(-183, 184)
        )

    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois_fr = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ]
    dates_triees = sorted(dates_disponibles)
    options_dates = [
        {
            "value": jour.isoformat(),
            "label": f"{jours_fr[jour.weekday()].capitalize()} {jour.day} {mois_fr[jour.month - 1]} {jour.year}",
        }
        for jour in dates_triees
    ]

    date_fin = today if today in dates_disponibles else min(
        dates_triees,
        key=lambda jour: abs((jour - today).days),
    )
    debut_mois = date_fin.replace(day=1)
    dates_avant_fin = [jour for jour in dates_triees if jour <= date_fin]
    date_debut = debut_mois if debut_mois in dates_disponibles else (
        dates_avant_fin[0] if dates_avant_fin else dates_triees[0]
    )

    active_tab = request.POST.get("onglet") or request.GET.get("onglet") or "export"
    if active_tab not in {"export", "emails", "superusers", "historique", "mot-de-passe"}:
        active_tab = "export"

    return render(request, "administration.html", {
        "active_page": "administration",
        "active_tab": active_tab,
        "periode_debut": date_debut.isoformat(),
        "periode_fin": date_fin.isoformat(),
        "options_dates": options_dates,
        "superusers": User.objects.filter(is_superuser=True).order_by("username"),
        "journal_audit": JournalAudit.objects.select_related("utilisateur")[:100],
        "message_admin": message_admin,
        "erreur_admin": erreur_admin,
    })


def _periode_export(request):
    debut = parse_date(request.GET.get("debut", ""))
    fin = parse_date(request.GET.get("fin", ""))
    if not debut or not fin:
        return None, None, "Les dates de début et de fin sont obligatoires."
    if fin < debut:
        return None, None, "La date de fin doit être postérieure ou égale à la date de début."
    if (fin - debut).days > 366:
        return None, None, "La période d'export ne peut pas dépasser 366 jours."
    return debut, fin, None


def export_planning_excel(request):
    debut, fin, erreur = _periode_export(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    contenu = generer_planning_excel(debut, fin)
    response = HttpResponse(
        contenu,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="planning_{debut:%Y%m%d}_{fin:%Y%m%d}.xlsx"'
    return response


def export_planning_pdf(request):
    debut, fin, erreur = _periode_export(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    contenu = generer_planning_pdf(debut, fin)
    response = HttpResponse(contenu, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="planning_{debut:%Y%m%d}_{fin:%Y%m%d}.pdf"'
    return response


# ---------------------------------------------------------------------------
# API - Animateurs (lecture, création, suppression)
# ---------------------------------------------------------------------------


logger = logging.getLogger("animateurs.emails")

@require_http_methods(["GET", "POST"])
def api_animateurs(request):
    """GET : liste tous les animateurs.
    POST : crée un animateur avec ses coordonnées, qualifications, un centre préféré et des centres secondaires."""

    if request.method == "GET":
        # Cette route est volontairement en lecture seule. L'ancienne version
        # nettoyait et réécrivait les disponibilités de chaque salarié à
        # chaque affichage de la liste, ce qui provoquait des centaines de
        # requêtes sur PostgreSQL/Supabase.
        #
        # Les disponibilités sont déjà normalisées lorsqu'elles sont ajoutées
        # ou modifiées dans les routes dédiées. Ici, on charge simplement
        # toutes les relations utiles en un nombre fixe de requêtes.
        animateurs = Animateur.objects.select_related(
            "evenement_preferee__centre", "utilisateur",
        ).prefetch_related(
            "qualifications",
            "preferences__centre",
            "disponibilites",
        )
        if request.GET.get("include_affectations") == "1":
            animateurs = animateurs.prefetch_related(
                Prefetch("affectations", to_attr="_filtre_affectations")
            )
        animateurs = animateurs.order_by("prenom", "nom", "id")

        return JsonResponse([animateur_to_dict(a) for a in animateurs], safe=False)

    try:
        payload = json.loads(request.body)

        prenom = payload["prenom"].strip()
        nom = payload["nom"].strip()
        telephone = payload.get("telephone", "").strip()
        email = payload.get("email", "").strip()
        date_naissance_raw = payload.get("date_naissance") or None
        adresse = payload.get("adresse", "").strip()
        numero_securite_sociale = payload.get("numero_securite_sociale", "").strip()
        paie_jour_raw = payload.get("paie_jour")
        paie_jour = None
        if paie_jour_raw not in (None, ""):
            try:
                paie_jour = Decimal(str(paie_jour_raw).replace(",", "."))
            except (InvalidOperation, ValueError):
                return JsonResponse({"error": "La paie par jour est invalide."}, status=400)
            if paie_jour < 0:
                return JsonResponse({"error": "La paie par jour ne peut pas être négative."}, status=400)
        date_naissance = parse_date(date_naissance_raw) if date_naissance_raw else None
        couleur = (payload.get("couleur") or "").strip() or secrets.choice(ANIMATEUR_COLOR_PALETTE)
        qualification_ids = payload.get("qualifications", [])
        centre_prefere, centres_secondaires, erreur_centres = normaliser_centres_hierarchises(payload)
        if erreur_centres:
            return JsonResponse({"error": erreur_centres}, status=400)
        evenement_preferee, evenement_preferee_fournie, erreur_evenement = normaliser_evenement_preferee(
            payload, centre_prefere
        )
        if erreur_evenement:
            return JsonResponse({"error": erreur_evenement}, status=400)

        if not prenom or not nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

        role = Animateur.ROLE_ANIMATEUR

        if Animateur.objects.filter(cle_unique=normaliser_cle_unique(prenom, nom)).exists():
            return JsonResponse({"error": f"L’employé « {prenom} {nom} » existe déjà."}, status=409)

        if date_naissance_raw and date_naissance is None:
            return JsonResponse({"error": "La date de naissance est invalide."}, status=400)

        if couleur and not re.fullmatch(r"#[0-9A-Fa-f]{6}", couleur):
            return JsonResponse({"error": "La couleur doit être au format #RRGGBB."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    with transaction.atomic():
        animateur = Animateur.objects.create(
            prenom=prenom,
            nom=nom,
            telephone=telephone,
            email=email,
            date_naissance=date_naissance,
            adresse=adresse,
            numero_securite_sociale=numero_securite_sociale,
            paie_jour=paie_jour,
            couleur=couleur,
            role=role,
            evenement_preferee=evenement_preferee if evenement_preferee_fournie else None,
        )

        if qualification_ids:
            # .set() sur un ManyToMany remplace toute la liste en une requête.
            animateur.qualifications.set(
                Qualification.objects.filter(pk__in=qualification_ids)
            )

        appliquer_centres_hierarchises(animateur, centre_prefere, centres_secondaires)

        if evenement_preferee_fournie:
            animateur.evenement_preferee = evenement_preferee
            animateur.save(update_fields=["evenement_preferee"])

        try:
            identifiants = _traiter_acces_compte(animateur, payload)
        except ValidationError as exc:
            return JsonResponse({"error": exc.messages[0]}, status=400)

    animateur = Animateur.objects.select_related(
        "evenement_preferee__centre", "utilisateur",
    ).prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    resultat = animateur_to_dict(animateur)
    if identifiants:
        resultat["temporary_credentials"] = identifiants
    return JsonResponse(resultat, status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_animateur_detail(request, animateur_id):
    """GET : renvoie un animateur.
    PATCH : modifie un ou plusieurs champs de l'animateur, y compris ses qualifications et ses centres autorisés.
    DELETE : supprime l'animateur et, par cascade, son planning/disponibilités/centres autorisés."""

    try:
        animateur = Animateur.objects.select_related(
            "evenement_preferee__centre", "utilisateur",
        ).prefetch_related(
            "qualifications",
            "preferences__centre",
            "disponibilites",
        ).get(pk=animateur_id)
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Animateur introuvable."}, status=404)

    if request.method == "GET":
        return JsonResponse(animateur_to_dict(animateur))

    if request.method == "DELETE":
        utilisateur = animateur.utilisateur
        animateur.delete()
        if utilisateur is not None:
            utilisateur.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)

        if "prenom" in payload:
            animateur.prenom = payload["prenom"].strip()

        if "nom" in payload:
            animateur.nom = payload["nom"].strip()

        if "telephone" in payload:
            animateur.telephone = payload.get("telephone", "").strip()

        if "email" in payload:
            animateur.email = payload.get("email", "").strip()

        if "date_naissance" in payload:
            date_naissance_raw = payload.get("date_naissance") or None
            date_naissance = parse_date(date_naissance_raw) if date_naissance_raw else None
            if date_naissance_raw and date_naissance is None:
                return JsonResponse({"error": "La date de naissance est invalide."}, status=400)
            animateur.date_naissance = date_naissance

        if "adresse" in payload:
            animateur.adresse = payload.get("adresse", "").strip()

        if "numero_securite_sociale" in payload:
            animateur.numero_securite_sociale = payload.get("numero_securite_sociale", "").strip()

        if "paie_jour" in payload:
            paie_jour_raw = payload.get("paie_jour")
            if paie_jour_raw in (None, ""):
                animateur.paie_jour = None
            else:
                try:
                    paie_jour = Decimal(str(paie_jour_raw).replace(",", "."))
                except (InvalidOperation, ValueError):
                    return JsonResponse({"error": "La paie par jour est invalide."}, status=400)
                if paie_jour < 0:
                    return JsonResponse({"error": "La paie par jour ne peut pas être négative."}, status=400)
                animateur.paie_jour = paie_jour

        if "couleur" in payload:
            couleur = (payload.get("couleur") or "").strip()
            if couleur and not re.fullmatch(r"#[0-9A-Fa-f]{6}", couleur):
                return JsonResponse({"error": "La couleur doit être au format #RRGGBB."}, status=400)
            animateur.couleur = couleur

        if not animateur.prenom or not animateur.nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

        if Animateur.objects.exclude(pk=animateur.pk).filter(
            cle_unique=normaliser_cle_unique(animateur.prenom, animateur.nom)
        ).exists():
            return JsonResponse({"error": f"L’employé « {animateur.prenom} {animateur.nom} » existe déjà."}, status=409)

        qualification_ids = payload.get("qualifications", None)
        centre_prefere, centres_secondaires, erreur_centres = normaliser_centres_hierarchises(payload)
        if erreur_centres:
            return JsonResponse({"error": erreur_centres}, status=400)

        if centre_prefere is None and centres_secondaires is None:
            relation_preferee = next(
                (pref for pref in animateur.preferences.all() if pref.est_prefere),
                None,
            )
            centre_prefere_effectif = relation_preferee.centre_id if relation_preferee else None
        else:
            centre_prefere_effectif = centre_prefere

        evenement_preferee, evenement_preferee_fournie, erreur_evenement = normaliser_evenement_preferee(
            payload, centre_prefere_effectif
        )
        if erreur_evenement:
            return JsonResponse({"error": erreur_evenement}, status=400)

    except (TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    with transaction.atomic():
        animateur.save()

        if qualification_ids is not None:
            animateur.qualifications.set(
                Qualification.objects.filter(pk__in=qualification_ids)
            )

        appliquer_centres_hierarchises(animateur, centre_prefere, centres_secondaires)

        if evenement_preferee_fournie:
            animateur.evenement_preferee = evenement_preferee
            animateur.save(update_fields=["evenement_preferee"])

        try:
            identifiants = _traiter_acces_compte(animateur, payload)
        except ValidationError as exc:
            return JsonResponse({"error": exc.messages[0]}, status=400)

    animateur = Animateur.objects.select_related(
        "evenement_preferee__centre", "utilisateur",
    ).prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    resultat = animateur_to_dict(animateur)
    if identifiants:
        resultat["temporary_credentials"] = identifiants
    return JsonResponse(resultat)


@require_http_methods(["GET", "PUT"])
def api_disponibilites(request, animateur_id):
    """Gère les disponibilités à partir de la bibliothèque des périodes.

    GET renvoie les périodes regroupées avec leurs jours et l'état de chaque
    case. PUT remplace les disponibilités de l'animateur par la liste des
    journées cochées reçue dans ``jours_disponibles``.
    """
    try:
        animateur = (
            Animateur.objects.prefetch_related("qualifications", "preferences__centre", "disponibilites", "affectations")
            .get(pk=animateur_id)
        )
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Animateur introuvable."}, status=404)

    def jours_ouvres(debut, fin):
        jour = debut
        while jour <= fin:
            if jour.weekday() < 5:
                yield jour
            jour += datetime.timedelta(days=1)

    def periodes_regroupees():
        groupes = {}
        for periode in PeriodeScolaire.objects.order_by("debut", "ordre", "id"):
            cle = (periode.nom, periode.annee_scolaire, periode.zone)
            groupe = groupes.setdefault(cle, {
                "id": f"{periode.annee_scolaire}-{periode.zone}-{periode.nom}",
                "nom": periode.nom,
                "annee_scolaire": periode.annee_scolaire,
                "zone": periode.zone,
                "debut": periode.debut,
                "fin": periode.fin,
                "jours": set(),
            })
            groupe["debut"] = min(groupe["debut"], periode.debut)
            groupe["fin"] = max(groupe["fin"], periode.fin)
            groupe["jours"].update(jours_ouvres(periode.debut, periode.fin))
        return sorted(groupes.values(), key=lambda item: (item["debut"], item["nom"]))

    if request.method == "PUT":
        try:
            payload = json.loads(request.body or b"{}")
            valeurs = payload.get("jours_disponibles", [])
            if not isinstance(valeurs, list):
                raise ValueError
            jours = sorted({parse_date(str(valeur)) for valeur in valeurs})
            if any(jour is None for jour in jours):
                raise ValueError
        except (ValueError, TypeError, json.JSONDecodeError):
            return JsonResponse({"error": "Liste de jours invalide."}, status=400)

        jours_autorises = {
            jour
            for groupe in periodes_regroupees()
            for jour in groupe["jours"]
        }
        if any(jour not in jours_autorises for jour in jours):
            return JsonResponse({"error": "Un jour ne correspond à aucune période enregistrée."}, status=400)

        plages = []
        if jours:
            debut = precedent = jours[0]
            for jour in jours[1:]:
                if jour == precedent + datetime.timedelta(days=1):
                    precedent = jour
                    continue
                plages.append((debut, precedent))
                debut = precedent = jour
            plages.append((debut, precedent))

        with transaction.atomic():
            animateur.disponibilites.all().delete()
            Disponibilite.objects.bulk_create([
                Disponibilite(animateur=animateur, debut=debut, fin=fin)
                for debut, fin in plages
            ])

    disponibilites = list(animateur.disponibilites.all())
    def est_disponible(jour):
        return any(plage.debut <= jour <= plage.fin for plage in disponibilites)

    resultat = []
    for groupe in periodes_regroupees():
        jours = sorted(groupe["jours"])
        jours_json = [
            {"date": jour.isoformat(), "disponible": est_disponible(jour)}
            for jour in jours
        ]
        resultat.append({
            "id": groupe["id"],
            "nom": groupe["nom"],
            "annee_scolaire": groupe["annee_scolaire"],
            "zone": groupe["zone"],
            "debut": groupe["debut"].isoformat(),
            "fin": groupe["fin"].isoformat(),
            "selectionnee": any(item["disponible"] for item in jours_json),
            "jours": jours_json,
        })

    plages_json = [
        {"id": dispo.id, "debut": dispo.debut.isoformat(), "fin": dispo.fin.isoformat()}
        for dispo in animateur.disponibilites.all()
    ]
    return JsonResponse({"periodes": resultat, "disponibilites": plages_json})


@require_http_methods(["PATCH", "DELETE"])
def api_disponibilite_detail(request, animateur_id, disponibilite_id):
    """Modifie ou supprime une plage de disponibilité précise."""

    try:
        animateur = Animateur.objects.get(pk=animateur_id)
        disponibilite = Disponibilite.objects.get(pk=disponibilite_id, animateur=animateur)
    except (Animateur.DoesNotExist, Disponibilite.DoesNotExist):
        return JsonResponse({"error": "Disponibilité introuvable."}, status=404)

    if request.method == "DELETE":
        disponibilite.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)
        debut = parse_date(payload.get("debut"))
        fin = parse_date(payload.get("fin") or payload.get("debut"))
        if debut is None or fin is None:
            raise ValueError("date invalide")
        if fin < debut:
            return JsonResponse({"error": "La date de fin doit être après la date de début."}, status=400)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    disponibilite.debut = debut
    disponibilite.fin = fin
    disponibilite.save(update_fields=["debut", "fin"])
    fusionner_et_nettoyer_disponibilites(animateur)

    plages = [
        {"id": dispo.id, "debut": dispo.debut.isoformat(), "fin": dispo.fin.isoformat()}
        for dispo in animateur.disponibilites.all()
    ]
    return JsonResponse({"disponibilites": plages})


# ---------------------------------------------------------------------------
# API - Planning (lecture des groupes + écriture individuelle)
# ---------------------------------------------------------------------------

def api_planning(request):
    """Renvoie les affectations au format FullCalendar.

    FullCalendar envoie automatiquement `start` et `end` dans la requête.
    On filtre donc côté serveur pour ne renvoyer que la période affichée :
    cela évite de recharger inutilement tout l'historique et réduit les
    risques d'affichage incohérent après un déplacement/suppression.
    """

    centre_id = request.GET.get("centre_id")
    evenement_id = request.GET.get("evenement_id")
    start = request.GET.get("start")
    end = request.GET.get("end")

    affectations = Affectation.objects.select_related("animateur", "centre", "evenement")

    if evenement_id:
        affectations = affectations.filter(evenement_id=evenement_id)
    elif centre_id:
        affectations = affectations.filter(centre_id=centre_id)

    if start and end:
        try:
            debut = parse_to_aware_datetime(start)
            fin = parse_to_aware_datetime(end)
            affectations = affectations.filter(debut__lt=fin, fin__gt=debut)
        except ValueError:
            return JsonResponse({"error": "Paramètres start/end invalides."}, status=400)

    events = [affectation_to_event(a) for a in affectations]

    return JsonResponse(events, safe=False)


@require_POST
def api_affectation_create(request):
    """Crée une affectation (glisser-déposer ou clic sur un jour dans le
    planning). Passe par _valider_affectation() pour refuser les doublons
    et les jours hors disponibilité."""

    try:
        payload = json.loads(request.body)

        animateur = Animateur.objects.get(pk=payload["animateur_id"])
        evenement = None
        evenement_id = payload.get("evenement_id")
        centre_id = payload.get("centre_id")

        if evenement_id is not None:
            evenement = Evenement.objects.select_related("centre").get(pk=evenement_id)
            centre = evenement.centre
            if centre_id is not None and int(centre_id) != centre.id:
                return JsonResponse(
                    {"error": "Le groupe sélectionné n'appartient pas à ce centre."},
                    status=400,
                )
        elif centre_id is not None:
            centre = Centre.objects.get(pk=centre_id)
        else:
            return JsonResponse({"error": "Un groupe ou un centre doit être indiqué."}, status=400)

        debut = parse_to_aware_datetime(payload["debut"])
        # Si "fin" n'est pas fourni, on suppose une affectation d'un seul
        # jour. ATTENTION : la convention "allDay" de FullCalendar veut une
        # borne de fin EXCLUSIVE, donc une journée = debut + 1 jour. Mettre
        # fin = debut donnerait un groupe de durée nulle (start == end)
        # qui ne s'affiche pas dans le calendrier.
        fin = (
            parse_to_aware_datetime(payload["fin"])
            if payload.get("fin")
            else debut + datetime.timedelta(days=1)
        )

    except (Animateur.DoesNotExist, Centre.DoesNotExist, Evenement.DoesNotExist):
        return JsonResponse({"error": "Animateur, centre ou groupe introuvable."}, status=404)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        affectation = creer_affectation(
            animateur=animateur, centre=centre, evenement=evenement, debut=debut, fin=fin
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)

    return JsonResponse(affectation_to_event(affectation), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_affectation_detail(request, affectation_id):
    """PATCH : déplacement ou redimensionnement d'une affectation existante
    dans le calendrier (revalidée comme à la création).
    DELETE : suppression d'une affectation (clic sur le groupe)."""

    try:
        affectation = Affectation.objects.get(pk=affectation_id)
    except Affectation.DoesNotExist:
        return JsonResponse({"error": "Affectation introuvable."}, status=404)

    if request.method == "DELETE":
        affectation.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)

        debut = (
            parse_to_aware_datetime(payload["debut"])
            if "debut" in payload
            else affectation.debut
        )
        fin = (
            parse_to_aware_datetime(payload["fin"])
            if "fin" in payload
            else affectation.fin
        )

        nouvelle_evenement = None
        nouveau_centre = None
        if "evenement_id" in payload:
            nouvelle_evenement = Evenement.objects.select_related("centre").get(pk=payload["evenement_id"])
            if "centre_id" in payload and int(payload["centre_id"]) != nouvelle_evenement.centre_id:
                return JsonResponse(
                    {"error": "Le groupe sélectionné n'appartient pas à ce centre."},
                    status=400,
                )
        elif "centre_id" in payload:
            nouveau_centre = Centre.objects.get(pk=payload["centre_id"])

    except (Centre.DoesNotExist, Evenement.DoesNotExist):
        return JsonResponse({"error": "Centre ou groupe introuvable."}, status=404)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        affectation = modifier_affectation(
            affectation,
            debut=debut,
            fin=fin,
            centre=nouveau_centre,
            evenement=nouvelle_evenement,
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)

    return JsonResponse(affectation_to_event(affectation))


@require_http_methods(["DELETE"])
def api_planning_plage(request):
    """Supprime en une fois toutes les affectations (tous centres
    confondus) qui chevauchent une plage de dates donnée en query params
    (?debut=...&fin=...). C'est le bouton "Vider la semaine" du planning.

    Sécurité importante : on ne supprime JAMAIS de jours déjà passés,
    même si `debut` est antérieur à aujourd'hui — la borne de début
    réellement utilisée est toujours au plus tôt "maintenant". Ça évite
    qu'un vidage de semaine efface accidentellement l'historique de ce
    qui a déjà été travaillé.

    On renvoie le nombre de lignes supprimées pour que le message de
    confirmation côté front soit précis.
    """

    debut_str = request.GET.get("debut")
    fin_str = request.GET.get("fin")

    try:
        debut_demande = parse_to_aware_datetime(debut_str)
        fin = parse_to_aware_datetime(fin_str)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Paramètres debut/fin invalides."}, status=400)

    # Pour le bouton "Vider la semaine", on vide vraiment toute la
    # semaine affichée, même si certains jours sont déjà passés.
    # Sinon l'interface peut garder des affectations visibles et donner
    # l'impression que le calendrier n'a pas été remis à zéro.
    debut = debut_demande

    if debut >= fin:
        return JsonResponse({"error": "La date de début doit être avant la date de fin."}, status=400)

    # .delete() sur un queryset supprime tout en une seule requête SQL et
    # renvoie (nombre_total_supprime, détail_par_modèle).
    nb_supprimees, _detail = Affectation.objects.filter(
        debut__lt=fin,
        fin__gt=debut,
    ).delete()

    return JsonResponse({"supprimees": nb_supprimees})


# ---------------------------------------------------------------------------
# API - Gestion (CRUD centres / groupes / qualifications)
# ---------------------------------------------------------------------------


def _message_validation(exc):
    if hasattr(exc, "message_dict"):
        messages = []
        for valeurs in exc.message_dict.values():
            messages.extend(valeurs)
        return " ".join(messages)
    if hasattr(exc, "messages"):
        return " ".join(exc.messages)
    return str(exc)


@require_http_methods(["GET", "POST"])
def api_centres(request):
    """GET : liste des centres. POST : création d'un centre."""

    if request.method == "GET":
        centres = Centre.objects.all()
        return JsonResponse([centre_to_dict(c) for c in centres], safe=False)

    try:
        payload = json.loads(request.body)

        nom = payload["nom"].strip()
        code = payload["code"].strip()
        couleur = payload.get("couleur", "#e03c00").strip() or "#e03c00"
        effectif_cible = int(payload.get("effectif_cible", 1) or 1)

        if not nom or not code:
            return JsonResponse({"error": "Le nom et le code sont obligatoires."}, status=400)

        if Centre.objects.filter(cle_unique=normaliser_cle_unique(nom)).exists():
            return JsonResponse({"error": f"Le lieu « {nom} » existe déjà."}, status=409)

        if effectif_cible < 1:
            return JsonResponse({"error": "L'effectif souhaité doit être d'au moins 1."}, status=400)

    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        centre = Centre.objects.create(
            nom=nom,
            code=code,
            couleur=couleur,
            effectif_cible=effectif_cible,
            ordre=prochain_ordre_centre(),
        )
    except IntegrityError:
        # Le champ `code` est unique en base (contrainte du modèle) :
        # on transforme l'erreur SQL brute en message compréhensible.
        return JsonResponse({"error": f"Le code « {code} » est déjà utilisé par un autre centre."}, status=409)

    return JsonResponse(centre_to_dict(centre), status=201)


@require_POST
def api_centres_reordonner(request):
    """Enregistre l'ordre d'affichage des blocs centres du planning."""

    try:
        payload = json.loads(request.body)
        centre_ids = [int(centre_id) for centre_id in payload.get("centre_ids", [])]
        reordonner_centres(centre_ids)
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)

    return JsonResponse({"ok": True})


@require_http_methods(["PATCH", "DELETE"])
def api_centre_detail(request, centre_id):
    """PATCH : met à jour un ou plusieurs champs d'un centre (utilisé pour
    ajuster l'effectif souhaité sans avoir à le recréer).
    DELETE : supprime le centre (et, par cascade, ses centres autorisés/
    affectations liées)."""

    try:
        centre = Centre.objects.get(pk=centre_id)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Centre introuvable."}, status=404)

    if request.method == "DELETE":
        if centre.affectations.exists():
            return JsonResponse(
                {"error": "Ce centre contient des affectations et ne peut pas être supprimé."},
                status=409,
            )
        centre.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)

        if "nom" in payload:
            centre.nom = payload["nom"].strip()

        if "code" in payload:
            centre.code = payload["code"].strip()

        if "couleur" in payload:
            centre.couleur = payload["couleur"].strip()

        if "effectif_cible" in payload:
            effectif_cible = int(payload["effectif_cible"])
            if effectif_cible < 1:
                return JsonResponse({"error": "L'effectif souhaité doit être d'au moins 1."}, status=400)
            centre.effectif_cible = effectif_cible

    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    if Centre.objects.exclude(pk=centre.pk).filter(cle_unique=normaliser_cle_unique(centre.nom)).exists():
        return JsonResponse({"error": f"Le lieu « {centre.nom} » existe déjà."}, status=409)
    try:
        centre.save()
    except IntegrityError:
        return JsonResponse({"error": "Un lieu avec ce nom ou ce code existe déjà."}, status=409)

    return JsonResponse(centre_to_dict(centre))


@require_http_methods(["GET", "POST"])
def api_groupes(request, centre_id):
    """Liste ou crée les groupes d’un lieu."""

    try:
        centre = Centre.objects.get(pk=centre_id)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Centre introuvable."}, status=404)

    if request.method == "GET":
        evenements = (
            centre.evenements
            .prefetch_related("periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification", "effectifs_enfants")
            .annotate(nb_affectations=Count("affectations", distinct=True))
            .order_by("ordre", "nom")
        )
        nb_evenements = evenements.count()
        data = []
        for evenement in evenements:
            evenement.nb_evenements_centre = nb_evenements
            data.append(evenement_to_dict(evenement))
        return JsonResponse(data, safe=False)

    try:
        payload = json.loads(request.body)
        evenement = creer_evenement(
            centre=centre,
            nom=payload.get("nom", ""),
            periode_ids=payload.get("periode_ids", []),
            effectif_cible=int(payload.get("effectif_cible", 1) or 1),
            enfants_par_animateur_defaut=int(payload.get("enfants_par_animateur_defaut", 8) or 8),
            qualifications=payload.get("qualifications_requises", {}),
            jours_ouverts=payload.get("jours_ouverts", [0, 1, 2, 3, 4, 5]),
            ferme_jours_feries=payload.get("ferme_jours_feries", True) is not False,
            permanent=bool(payload.get("permanent", False)),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Un groupe de ce nom existe déjà dans ce lieu."}, status=409)

    evenement = Evenement.objects.select_related("centre").prefetch_related(
        "periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification", "effectifs_enfants"
    ).get(pk=evenement.pk)
    evenement.nb_affectations = 0
    evenement.nb_evenements_centre = centre.evenements.count()
    return JsonResponse(evenement_to_dict(evenement), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_groupe_detail(request, evenement_id):
    """Modifie ou supprime un groupe sans détruire ses affectations."""

    try:
        evenement = Evenement.objects.select_related("centre").get(pk=evenement_id)
    except Evenement.DoesNotExist:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)

    if request.method == "DELETE":
        try:
            supprimer_evenement(evenement)
        except ValidationError as exc:
            return JsonResponse({"error": _message_validation(exc)}, status=409)
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)
        evenement = modifier_evenement(
            evenement,
            nom=payload.get("nom") if "nom" in payload else None,
            periode_ids=payload.get("periode_ids", []),
            periodes_fournies="periode_ids" in payload,
            effectif_cible=payload.get("effectif_cible") if "effectif_cible" in payload else None,
            enfants_par_animateur_defaut=payload.get("enfants_par_animateur_defaut") if "enfants_par_animateur_defaut" in payload else None,
            qualifications=payload.get("qualifications_requises", {}),
            qualifications_fournies="qualifications_requises" in payload,
            jours_ouverts=payload.get("jours_ouverts") if "jours_ouverts" in payload else None,
            ferme_jours_feries=payload.get("ferme_jours_feries") if "ferme_jours_feries" in payload else None,
            permanent=payload.get("permanent") if "permanent" in payload else None,
            supprimer_affectations_dates_fermees=bool(
                payload.get("supprimer_affectations_dates_fermees", False)
            ),
        )
    except FermetureAvecAffectationsError as exc:
        return JsonResponse({
            "error": _message_validation(exc),
            "code": "affectations_dates_fermees",
            "nb_affectations": len(exc.affectations),
            "dates": [date.isoformat() for date in exc.dates],
        }, status=409)
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Un groupe de ce nom existe déjà dans ce lieu."}, status=409)

    evenement = Evenement.objects.select_related("centre").prefetch_related(
        "periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification", "effectifs_enfants"
    ).get(pk=evenement.pk)
    evenement.nb_affectations = evenement.affectations.count()
    evenement.nb_evenements_centre = evenement.centre.evenements.count()
    return JsonResponse(evenement_to_dict(evenement))


@require_POST
def api_groupes_reordonner(request, centre_id):
    try:
        centre = Centre.objects.get(pk=centre_id)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Centre introuvable."}, status=404)

    try:
        payload = json.loads(request.body)
        evenement_ids = [int(evenement_id) for evenement_id in payload.get("evenement_ids", [])]
        reordonner_evenements(centre, evenement_ids)
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)

    return JsonResponse({"ok": True})


SENS_EQUIVALENCE_API = {"sortante", "entrante", "double"}


def _relations_equivalence_depuis_payload(payload, obligatoire=False):
    """Lit les règles depuis le JSON, avec compatibilité pour l'ancien format."""

    if "relations_equivalence" in payload:
        brutes = payload.get("relations_equivalence")
        if not isinstance(brutes, list):
            raise ValueError("Le format des équivalences est invalide.")
        relations = {}
        for brute in brutes:
            if not isinstance(brute, dict):
                raise ValueError("Le format des équivalences est invalide.")
            qualification_id = int(brute.get("qualification_id"))
            sens = str(brute.get("sens", "")).strip()
            if sens not in SENS_EQUIVALENCE_API:
                raise ValueError("Le sens d'une équivalence est invalide.")
            relations[qualification_id] = sens
        return relations

    if "equivalence_ids" in payload:
        # L'ancien écran ne connaissait que le double sens.
        return {int(value): "double" for value in payload.get("equivalence_ids", [])}

    return {} if obligatoire else None


def _remplacer_relations_equivalence(qualification, relations):
    """Remplace toutes les règles impliquant la qualification donnée."""

    relations = relations or {}
    relations.pop(qualification.id, None)
    autres = Qualification.objects.in_bulk(relations.keys())

    EquivalenceQualification.objects.filter(
        Q(qualification_a=qualification) | Q(qualification_b=qualification)
    ).delete()

    nouvelles = []
    for autre_id, sens_perspective in relations.items():
        autre = autres.get(autre_id)
        if not autre:
            continue

        if qualification.id < autre.id:
            qualification_a = qualification
            qualification_b = autre
            sens_stocke = {
                "sortante": EquivalenceQualification.SENS_A_VERS_B,
                "entrante": EquivalenceQualification.SENS_B_VERS_A,
                "double": EquivalenceQualification.SENS_DOUBLE,
            }[sens_perspective]
        else:
            qualification_a = autre
            qualification_b = qualification
            sens_stocke = {
                "sortante": EquivalenceQualification.SENS_B_VERS_A,
                "entrante": EquivalenceQualification.SENS_A_VERS_B,
                "double": EquivalenceQualification.SENS_DOUBLE,
            }[sens_perspective]

        nouvelles.append(EquivalenceQualification(
            qualification_a=qualification_a,
            qualification_b=qualification_b,
            sens=sens_stocke,
        ))

    EquivalenceQualification.objects.bulk_create(nouvelles)


def _qualifications_avec_relations():
    return Qualification.objects.prefetch_related(
        "relations_equivalence_a__qualification_b",
        "relations_equivalence_b__qualification_a",
    )


@require_http_methods(["GET", "POST"])
def api_qualifications(request):
    """GET : liste des qualifications. POST : création d'une qualification."""

    if request.method == "GET":
        qualifications = _qualifications_avec_relations().order_by("nom", "id")
        return JsonResponse([qualification_to_dict(q) for q in qualifications], safe=False)

    try:
        payload = json.loads(request.body)
        nom = payload["nom"].strip()
        selectionnable_auto = bool(payload.get("selectionnable_remplissage_auto", False))
        relations = _relations_equivalence_depuis_payload(payload, obligatoire=True)

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

        if Qualification.objects.filter(cle_unique=normaliser_cle_unique(nom)).exists():
            return JsonResponse({"error": f"La qualification « {nom} » existe déjà."}, status=409)

    except ValueError as exc:
        return JsonResponse({"error": str(exc) or "Requête invalide."}, status=400)
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        with transaction.atomic():
            qualification = Qualification.objects.create(
                nom=nom,
                selectionnable_remplissage_auto=selectionnable_auto,
            )
            _remplacer_relations_equivalence(qualification, relations)
    except IntegrityError:
        return JsonResponse({"error": f"La qualification « {nom} » existe déjà."}, status=409)

    qualification = _qualifications_avec_relations().get(pk=qualification.pk)
    return JsonResponse(qualification_to_dict(qualification), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_qualification_detail(request, qualification_id):
    """Consulte, modifie ou supprime une qualification et ses équivalences."""

    try:
        qualification = _qualifications_avec_relations().get(pk=qualification_id)
    except Qualification.DoesNotExist:
        return JsonResponse({"error": "Qualification introuvable."}, status=404)

    if request.method == "GET":
        return JsonResponse(qualification_to_dict(qualification))

    if request.method == "DELETE":
        qualification.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body)
        nom = payload.get("nom", qualification.nom).strip()
        selectionnable_auto = bool(
            payload.get(
                "selectionnable_remplissage_auto",
                qualification.selectionnable_remplissage_auto,
            )
        )
        relations = _relations_equivalence_depuis_payload(payload)

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

    except ValueError as exc:
        return JsonResponse({"error": str(exc) or "Requête invalide."}, status=400)
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        with transaction.atomic():
            qualification.nom = nom
            qualification.selectionnable_remplissage_auto = selectionnable_auto
            qualification.save(update_fields=["nom", "selectionnable_remplissage_auto", "cle_unique"])
            if relations is not None:
                _remplacer_relations_equivalence(qualification, relations)
    except IntegrityError:
        return JsonResponse({"error": f"La qualification « {nom} » existe déjà."}, status=409)

    qualification = _qualifications_avec_relations().get(pk=qualification.pk)
    return JsonResponse(qualification_to_dict(qualification))


# ---------------------------------------------------------------------------
# API - Périodes scolaires indépendantes
# ---------------------------------------------------------------------------

def _periode_scolaire_to_dict(periode):
    return {
        "id": periode.id,
        "nom": periode.nom,
        "libelle": periode.libelle_avec_annee,
        "annee_scolaire": periode.annee_scolaire,
        "zone": periode.zone,
        "debut": periode.debut.isoformat(),
        "fin": periode.fin.isoformat(),
        "description_source": periode.description_source,
        "ordre": periode.ordre,
    }


def _payload_import_periodes(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise CalendrierScolaireError("Requête invalide.") from exc
    return (
        str(payload.get("annee_scolaire", "")).strip(),
        str(payload.get("zone", "")).strip().upper(),
    )


@require_http_methods(["GET"])
def api_periodes_scolaires(request):
    """Liste les semaines importées, sans effet sur les autres modules."""
    periodes = PeriodeScolaire.objects.all()
    annee_scolaire = request.GET.get("annee_scolaire", "").strip()
    zone = request.GET.get("zone", "").strip().upper()
    if annee_scolaire:
        periodes = periodes.filter(annee_scolaire=annee_scolaire)
    if zone:
        periodes = periodes.filter(zone=zone)
    return JsonResponse(
        [_periode_scolaire_to_dict(periode) for periode in periodes],
        safe=False,
    )


@require_POST
def api_periodes_scolaires_previsualiser(request):
    """Interroge l'API officielle sans rien enregistrer en base."""
    try:
        annee_scolaire, zone = _payload_import_periodes(request)
        semaines = recuperer_semaines(annee_scolaire, zone)
    except CalendrierScolaireError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    existantes = set(
        PeriodeScolaire.objects.filter(
            annee_scolaire=annee_scolaire, zone=zone
        ).values_list("debut", "fin")
    )
    resultat = []
    for semaine in semaines:
        item = semaine.to_dict()
        item["deja_enregistree"] = (semaine.debut, semaine.fin) in existantes
        resultat.append(item)

    return JsonResponse({
        "annee_scolaire": annee_scolaire,
        "zone": zone,
        "periodes": resultat,
        "nombre": len(resultat),
    })


@require_POST
def api_periodes_scolaires_importer(request):
    """Enregistre toutes les semaines officielles de façon idempotente."""
    try:
        annee_scolaire, zone = _payload_import_periodes(request)
        semaines = recuperer_semaines(annee_scolaire, zone)
    except CalendrierScolaireError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    creees = 0
    mises_a_jour = 0
    with transaction.atomic():
        for ordre, semaine in enumerate(semaines):
            periode, creee = PeriodeScolaire.objects.get_or_create(
                annee_scolaire=annee_scolaire,
                zone=zone,
                debut=semaine.debut,
                fin=semaine.fin,
                defaults={
                    "nom": semaine.nom,
                    "description_source": semaine.description_source,
                    "ordre": ordre,
                },
            )
            if creee:
                creees += 1
                # Toute nouvelle semaine appartient automatiquement aux groupes permanents.
                for groupe in Evenement.objects.filter(permanent=True).only("id"):
                    groupe.periodes_scolaires.add(periode)
                continue
            champs = []
            if periode.nom != semaine.nom:
                periode.nom = semaine.nom
                champs.append("nom")
            if periode.description_source != semaine.description_source:
                periode.description_source = semaine.description_source
                champs.append("description_source")
            if periode.ordre != ordre:
                periode.ordre = ordre
                champs.append("ordre")
            if champs:
                periode.save(update_fields=champs)
                mises_a_jour += 1

    periodes = PeriodeScolaire.objects.filter(
        annee_scolaire=annee_scolaire, zone=zone
    )
    return JsonResponse({
        "ok": True,
        "cree": creees,
        "mis_a_jour": mises_a_jour,
        "periodes": [_periode_scolaire_to_dict(p) for p in periodes],
    }, status=201 if creees else 200)


@require_http_methods(["DELETE"])
def api_periode_scolaire_detail(request, periode_id):
    try:
        periode = PeriodeScolaire.objects.get(pk=periode_id)
    except PeriodeScolaire.DoesNotExist:
        return JsonResponse({"error": "Période introuvable."}, status=404)
    periode.delete()
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# API - Récapitulatif (statistiques pour la page de suivi)
# ---------------------------------------------------------------------------

def api_recapitulatif(request):
    """Tableau de bord du planning sur une ou plusieurs périodes enregistrées.

    Le paramètre ``periode_ids`` contient les identifiants séparés par des
    virgules. Les semaines peuvent être discontinues : seules leurs dates sont
    intégrées aux calculs. L'ancien couple ``debut``/``fin`` reste accepté pour
    compatibilité avec les appels existants.
    """

    periode_ids_bruts = request.GET.get("periode_ids", "").strip()
    periodes = []
    jours_selectionnes = None

    if periode_ids_bruts:
        try:
            periode_ids = [int(valeur) for valeur in periode_ids_bruts.split(",") if valeur.strip()]
        except ValueError:
            return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)

        if not periode_ids:
            return JsonResponse({"error": "Sélectionne au moins une période."}, status=400)

        periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
        if len(periodes) != len(set(periode_ids)):
            return JsonResponse({"error": "Une période sélectionnée est introuvable."}, status=400)

        jours_selectionnes = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in periodes
            for decalage in range((periode.fin - periode.debut).days + 1)
        }
        debut_date = min(jours_selectionnes)
        fin_date = max(jours_selectionnes) + datetime.timedelta(days=1)
        debut = timezone.make_aware(datetime.datetime.combine(debut_date, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(fin_date, datetime.time.min))
    else:
        debut_str = request.GET.get("debut")
        fin_str = request.GET.get("fin")
        aujourd_hui = timezone.localdate()

        if debut_str:
            debut = parse_to_aware_datetime(debut_str)
        else:
            premier_jour = aujourd_hui.replace(day=1)
            debut = timezone.make_aware(datetime.datetime.combine(premier_jour, datetime.time.min))

        if fin_str:
            fin = parse_to_aware_datetime(fin_str)
        else:
            if aujourd_hui.month == 12:
                mois_suivant = aujourd_hui.replace(year=aujourd_hui.year + 1, month=1, day=1)
            else:
                mois_suivant = aujourd_hui.replace(month=aujourd_hui.month + 1, day=1)
            fin = timezone.make_aware(datetime.datetime.combine(mois_suivant, datetime.time.min))

    if debut >= fin:
        return JsonResponse({"error": "La date de début doit être avant la date de fin."}, status=400)

    recap = generer_recapitulatif(debut, fin, jours_selectionnes=jours_selectionnes)

    return JsonResponse({
        "periode": {
            "debut": debut.date().isoformat(),
            "fin": fin.date().isoformat(),
            "ids": [periode.id for periode in periodes],
            "libelles": [periode.libelle_avec_annee for periode in periodes],
        },
        "dates": recap["dates"],
        "centres": recap["centres"],
        "animateurs": recap["animateurs"],
        "total_jours": recap["total_jours"],
        "total_paie_connue": recap["total_paie_connue"],
        "tarifs_manquants": recap["tarifs_manquants"],
    })

# ---------------------------------------------------------------------------
# API - Documents (liste, upload, suppression)
# ---------------------------------------------------------------------------
# Particularité par rapport aux autres endpoints de ce fichier : la
# création se fait via un formulaire multipart/form-data (request.POST +
# request.FILES), pas du JSON, puisqu'il y a un fichier à envoyer. Le
# fichier est stocké via le backend configuré dans STORAGES (voir
# settings.py : ici un bucket S3 Supabase), donc `document.fichier.url`
# renvoie directement l'URL publique du fichier, quel que soit le
# stockage utilisé.


@require_http_methods(["GET", "POST"])
def api_documents(request):
    """GET : liste des documents (les plus récents en premier).
    POST : ajoute un document multipart avec son titre, son fichier et
    soit le statut permanent, soit une période début/fin."""

    if request.method == "GET":
        documents_qs = Document.objects.prefetch_related("periodes").all().order_by("-date_ajout")
        return JsonResponse([document_to_dict(d) for d in documents_qs], safe=False)

    titre = request.POST.get("titre", "").strip()
    fichier = request.FILES.get("fichier")
    permanent = False
    periode_ids_bruts = request.POST.getlist("periode_ids") or request.POST.getlist("periode_ids[]")
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in periode_ids_bruts))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)
    periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))
    if not periode_ids:
        return JsonResponse({"error": "Sélectionne au moins une semaine."}, status=400)
    if len(periodes) != len(periode_ids):
        return JsonResponse({"error": "Une semaine sélectionnée est introuvable."}, status=400)
    periode_debut = min(periode.debut for periode in periodes)
    periode_fin = max(periode.fin for periode in periodes)

    if not titre or not fichier:
        return JsonResponse({"error": "Le titre et le fichier sont obligatoires."}, status=400)

    periode_debut, periode_fin, erreur = valider_periode_document(
        permanent=permanent,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
    )
    if erreur:
        return JsonResponse({"error": erreur}, status=400)

    document = Document.objects.create(
        titre=titre,
        fichier=fichier,
        permanent=False,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
    )
    document.periodes.set(periodes)

    return JsonResponse(document_to_dict(document), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_document_detail(request, document_id):
    """Supprime un document, y compris le fichier physique/distant
    associé (sans quoi il resterait orphelin dans le stockage)."""

    try:
        document = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return JsonResponse({"error": "Document introuvable."}, status=404)

    if request.method == "DELETE":
        document.fichier.delete(save=False)
        document.delete()
        return JsonResponse({"ok": True})

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide."}, status=400)

    titre = str(payload.get("titre", document.titre)).strip()
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in payload.get("periode_ids", [])))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection de périodes est invalide."}, status=400)
    periodes = list(PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom"))

    if not titre:
        return JsonResponse({"error": "Le titre est obligatoire."}, status=400)
    if not periode_ids:
        return JsonResponse({"error": "Sélectionne au moins une semaine."}, status=400)
    if len(periodes) != len(periode_ids):
        return JsonResponse({"error": "Une semaine sélectionnée est introuvable."}, status=400)

    document.titre = titre
    document.permanent = False
    document.periode_debut = min(periode.debut for periode in periodes)
    document.periode_fin = max(periode.fin for periode in periodes)
    document.save(update_fields=["titre", "permanent", "periode_debut", "periode_fin"])
    document.periodes.set(periodes)

    return JsonResponse(document_to_dict(document))


# ---------------------------------------------------------------------------
# API - Envois d'e-mails aux salariés
# ---------------------------------------------------------------------------


def _taille_document(document):
    try:
        return int(document.fichier.size)
    except (OSError, TypeError, ValueError):
        return None






def _modele_email_to_dict(modele):
    return {
        "id": modele.id,
        "nom": modele.nom,
        "objet": modele.objet,
        "message": modele.message,
        "actif": modele.actif,
        "ordre": modele.ordre,
        "date_creation": modele.date_creation.isoformat(),
        "date_modification": modele.date_modification.isoformat(),
    }


def _lire_modele_email(request, *, instance=None):
    """Valide les champs reçus pour créer ou modifier un modèle d’e-mail."""

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None, JsonResponse({"error": "JSON invalide."}, status=400)

    nom = str(payload.get("nom", "")).strip()
    objet = str(payload.get("objet", "")).strip()
    message = str(payload.get("message", "")).strip()
    actif = payload.get("actif", True if instance is None else instance.actif)

    if not nom:
        return None, JsonResponse({"error": "Le nom du modèle est obligatoire."}, status=400)
    if len(nom) > 120:
        return None, JsonResponse({"error": "Le nom ne peut pas dépasser 120 caractères."}, status=400)
    if not objet:
        return None, JsonResponse({"error": "L’objet du modèle est obligatoire."}, status=400)
    if len(objet) > 200:
        return None, JsonResponse({"error": "L’objet ne peut pas dépasser 200 caractères."}, status=400)
    if not message:
        return None, JsonResponse({"error": "Le message du modèle est obligatoire."}, status=400)
    if len(message) > 10000:
        return None, JsonResponse({"error": "Le message du modèle est trop long."}, status=400)
    if not isinstance(actif, bool):
        return None, JsonResponse({"error": "Le statut actif du modèle est invalide."}, status=400)

    doublon = ModeleEmail.objects.filter(nom__iexact=nom)
    if instance is not None:
        doublon = doublon.exclude(pk=instance.pk)
    if doublon.exists():
        return None, JsonResponse({"error": "Un modèle porte déjà ce nom."}, status=409)

    return {
        "nom": nom,
        "objet": objet,
        "message": message,
        "actif": actif,
    }, None


@require_http_methods(["GET", "POST"])
def api_modeles_email(request):
    """Liste et crée les modèles d’e-mail gérés depuis l’application."""

    if request.method == "GET":
        # Les modèles sont facultatifs. Sur une installation où la migration
        # correspondante n'a pas encore été exécutée, on conserve malgré tout
        # l'éditeur d'e-mail et ses variables de base.
        try:
            modeles = [_modele_email_to_dict(modele) for modele in ModeleEmail.objects.all()]
        except DatabaseError:
            modeles = []
        return JsonResponse({
            "modeles": modeles,
            "variables": variables_email_disponibles(),
        })

    donnees, erreur = _lire_modele_email(request)
    if erreur:
        return erreur

    try:
        modele = ModeleEmail.objects.create(**donnees)
    except IntegrityError:
        return JsonResponse({"error": "Un modèle porte déjà ce nom."}, status=409)

    return JsonResponse(_modele_email_to_dict(modele), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_modele_email_detail(request, modele_id):
    """Modifie, active/désactive ou supprime un modèle d’e-mail."""

    try:
        modele = ModeleEmail.objects.get(pk=modele_id)
    except ModeleEmail.DoesNotExist:
        return JsonResponse({"error": "Modèle d’e-mail introuvable."}, status=404)

    if request.method == "DELETE":
        modele.delete()
        return HttpResponse(status=204)

    donnees, erreur = _lire_modele_email(request, instance=modele)
    if erreur:
        return erreur

    for champ, valeur in donnees.items():
        setattr(modele, champ, valeur)
    try:
        modele.save(update_fields=[*donnees.keys(), "date_modification"])
    except IntegrityError:
        return JsonResponse({"error": "Un modèle porte déjà ce nom."}, status=409)

    return JsonResponse(_modele_email_to_dict(modele))


def _envoi_email_to_dict(envoi):
    destinataires = list(envoi.destinataires.all())
    return {
        "id": envoi.id,
        "objet": envoi.objet,
        "date_creation": envoi.date_creation.isoformat(),
        "nombre_destinataires": envoi.nombre_destinataires,
        "nombre_envoyes": envoi.nombre_envoyes,
        "nombre_echecs": envoi.nombre_echecs,
        "mode_test": envoi.mode_test,
        "documents": envoi.documents_titres or [document.titre for document in envoi.documents.all()],
        "echecs": [
            {
                "prenom": destinataire.prenom,
                "nom": destinataire.nom,
                "email": destinataire.email,
                "erreur": destinataire.erreur,
            }
            for destinataire in destinataires
            if destinataire.statut == DestinataireEnvoiEmail.STATUT_ECHEC
        ],
    }


def _contact_email_to_dict(contact):
    return {
        "id": contact.id,
        "prenom": contact.prenom,
        "nom": contact.nom,
        "email": contact.email,
        "organisation": contact.organisation,
        "actif": contact.actif,
    }


def _periode_email_to_dict(periode):
    """Décompose une semaine pour le sélecteur Année > Vacances > Semaine."""

    nom = str(periode.nom or "").strip()
    correspondance = re.match(
        r"^(?P<vacances>.*?)(?:\s*[—–-]\s*)?(?P<semaine>Semaine\s+.+)$",
        nom,
        flags=re.IGNORECASE,
    )
    if correspondance and correspondance.group("vacances").strip():
        vacances = correspondance.group("vacances").strip()
        semaine = correspondance.group("semaine").strip()
    else:
        vacances = nom or "Autres périodes"
        semaine = f"Du {periode.debut:%d/%m/%Y} au {periode.fin:%d/%m/%Y}"
    return {
        "id": periode.id,
        "nom": periode.nom,
        "libelle": periode.libelle_avec_annee,
        "debut": periode.debut.isoformat(),
        "fin": periode.fin.isoformat(),
        "est_actuelle": periode.debut <= timezone.localdate() <= periode.fin,
        "annee_scolaire": periode.annee_scolaire,
        "vacances": vacances,
        "semaine": semaine,
    }


def _lire_contact_email(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None, JsonResponse({"error": "JSON invalide."}, status=400)
    prenom = str(payload.get("prenom", "")).strip()
    nom = str(payload.get("nom", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    organisation = str(payload.get("organisation", "")).strip()
    actif = bool(payload.get("actif", True))
    if not nom:
        return None, JsonResponse({"error": "Le nom du contact est obligatoire."}, status=400)
    try:
        validate_email(email)
    except ValidationError:
        return None, JsonResponse({"error": "L’adresse e-mail est invalide."}, status=400)
    return {"prenom": prenom, "nom": nom, "email": email, "organisation": organisation, "actif": actif}, None


@require_http_methods(["GET", "POST"])
def api_contacts_email(request):
    if request.method == "GET":
        return JsonResponse({"contacts": [_contact_email_to_dict(c) for c in ContactEmailExterne.objects.all()]})
    donnees, erreur = _lire_contact_email(request)
    if erreur:
        return erreur
    try:
        contact = ContactEmailExterne.objects.create(**donnees)
    except IntegrityError:
        return JsonResponse({"error": "Cette adresse e-mail est déjà enregistrée parmi les contacts externes."}, status=409)
    return JsonResponse(_contact_email_to_dict(contact), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_contact_email_detail(request, contact_id):
    try:
        contact = ContactEmailExterne.objects.get(pk=contact_id)
    except ContactEmailExterne.DoesNotExist:
        return JsonResponse({"error": "Contact introuvable."}, status=404)
    if request.method == "DELETE":
        contact.delete()
        return JsonResponse({"ok": True})
    donnees, erreur = _lire_contact_email(request)
    if erreur:
        return erreur
    for champ, valeur in donnees.items():
        setattr(contact, champ, valeur)
    try:
        contact.save()
    except IntegrityError:
        return JsonResponse({"error": "Cette adresse e-mail est déjà enregistrée parmi les contacts externes."}, status=409)
    return JsonResponse(_contact_email_to_dict(contact))


@require_http_methods(["GET", "POST"])
def api_envois_email(request):
    """Prépare, exécute et historise les envois de documents aux salariés."""

    if request.method == "GET":
        animateurs = list(
            Animateur.objects.all()
            .prefetch_related("qualifications", "preferences__centre", "disponibilites", "affectations")
        )
        animateurs.sort(key=lambda a: (a.prenom.casefold(), a.nom.casefold(), a.pk))
        documents_qs = list(Document.objects.prefetch_related("periodes").all())
        qualifications = list(Qualification.objects.order_by("nom", "id"))
        # L'historique ne doit jamais empêcher l'affichage des salariés.
        # Cela couvre notamment un déploiement où les migrations du module
        # e-mail n'ont pas encore été appliquées sur Supabase.
        try:
            historique = list(
                EnvoiEmail.objects.prefetch_related("documents", "destinataires")
                .all()[:30]
            )
        except DatabaseError:
            historique = []
        return JsonResponse({
            "configuration": statut_configuration_email(),
            "contacts_externes": [_contact_email_to_dict(contact) for contact in ContactEmailExterne.objects.filter(actif=True)],
            "periodes": [
                _periode_email_to_dict(periode)
                for periode in PeriodeScolaire.objects.order_by("debut", "ordre", "nom")
            ],
            "qualifications": [
                {"id": qualification.id, "nom": qualification.nom}
                for qualification in qualifications
            ],
            "animateurs": [
                {
                    "id": animateur.id,
                    "prenom": animateur.prenom,
                    "nom": animateur.nom,
                    "email": animateur.email,
                    "qualifications": [q.nom for q in animateur.qualifications.all()],
                    "qualification_ids": [q.id for q in animateur.qualifications.all()],
                    "lieux": [pref.centre.nom for pref in animateur.preferences.all()],
                    "centre_prefere": next((
                        {"id": pref.centre_id, "nom": pref.centre.nom, "code": pref.centre.code}
                        for pref in animateur.preferences.all() if pref.est_prefere
                    ), None),
                    "disponibilites": [
                        {"debut": disponibilite.debut.isoformat(), "fin": disponibilite.fin.isoformat()}
                        for disponibilite in animateur.disponibilites.all()
                    ],
                    "affectations": [
                        {"debut": affectation.debut.isoformat(), "fin": affectation.fin.isoformat()}
                        for affectation in animateur.affectations.all()
                    ],
                }
                for animateur in animateurs
            ],
            "documents": [
                {
                    **document_to_dict(document),
                    "taille": _taille_document(document),
                }
                for document in documents_qs
            ],
            # Les modèles sont chargés par leur API dédiée. La clé vide est
            # conservée pour compatibilité, sans requête vers leur table.
            "modeles": [],
            "variables": variables_email_disponibles(),
            "historique": [_envoi_email_to_dict(envoi) for envoi in historique],
        })

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide."}, status=400)

    objet = str(payload.get("objet", "")).strip()
    message = str(payload.get("message", "")).strip()
    animateur_ids = payload.get("animateur_ids", [])
    contact_ids = payload.get("contact_ids", [])
    document_ids = payload.get("document_ids", [])
    periode_ids_bruts = payload.get("periode_ids")
    if periode_ids_bruts is None:
        # Compatibilité avec les anciennes versions de l'interface.
        periode_id_legacy = payload.get("periode_id")
        periode_ids_bruts = [] if periode_id_legacy in (None, "") else [periode_id_legacy]
    if not isinstance(periode_ids_bruts, list):
        return JsonResponse({"error": "La sélection des semaines est invalide."}, status=400)
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in periode_ids_bruts))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection des semaines est invalide."}, status=400)
    semaines_reference = list(
        PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom")
    )
    if len(semaines_reference) != len(periode_ids):
        return JsonResponse({"error": "Une ou plusieurs semaines sélectionnées sont invalides."}, status=400)

    if not objet:
        return JsonResponse({"error": "L'objet de l'e-mail est obligatoire."}, status=400)
    if len(objet) > 200:
        return JsonResponse({"error": "L'objet ne peut pas dépasser 200 caractères."}, status=400)
    if not message:
        return JsonResponse({"error": "Le message est obligatoire."}, status=400)
    if len(message) > 10000:
        return JsonResponse({"error": "Le message est trop long."}, status=400)
    if not isinstance(animateur_ids, list) or not isinstance(contact_ids, list) or not (animateur_ids or contact_ids):
        return JsonResponse({"error": "Choisis au moins un destinataire."}, status=400)
    if not isinstance(document_ids, list):
        return JsonResponse({"error": "La sélection de documents est invalide."}, status=400)

    try:
        ids_animateurs = list(dict.fromkeys(int(value) for value in animateur_ids))
        ids_contacts = list(dict.fromkeys(int(value) for value in contact_ids))
        ids_documents = list(dict.fromkeys(int(value) for value in document_ids))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection contient un identifiant invalide."}, status=400)

    if len(ids_animateurs) + len(ids_contacts) > 250:
        return JsonResponse({"error": "Un envoi est limité à 250 destinataires."}, status=400)

    animateurs = list(
        Animateur.objects.filter(pk__in=ids_animateurs)
        .prefetch_related("qualifications", "preferences__centre")
    )
    contacts = list(ContactEmailExterne.objects.filter(pk__in=ids_contacts, actif=True))
    documents_selectionnes = list(Document.objects.filter(pk__in=ids_documents))
    animateurs.sort(key=lambda a: (a.prenom.casefold(), a.nom.casefold(), a.pk))

    if len(animateurs) != len(ids_animateurs):
        return JsonResponse({"error": "Un ou plusieurs salariés n'existent plus."}, status=400)
    if len(contacts) != len(ids_contacts):
        return JsonResponse({"error": "Un ou plusieurs contacts externes n'existent plus ou sont inactifs."}, status=400)
    if len(documents_selectionnes) != len(ids_documents):
        return JsonResponse({"error": "Un ou plusieurs documents n'existent plus."}, status=400)

    destinataires = [
        {"type": "salarie", "id": a.id, "objet": a, "animateur": a, "contact": None}
        for a in animateurs
    ] + [
        {"type": "contact", "id": c.id, "objet": c, "animateur": None, "contact": c}
        for c in contacts
    ]

    adresses_invalides = []
    for item in destinataires:
        personne = item["objet"]
        try:
            validate_email(personne.email)
        except ValidationError:
            adresses_invalides.append(f"{personne.prenom} {personne.nom}".strip())
    if adresses_invalides:
        return JsonResponse({"error": "Adresse e-mail absente ou invalide pour : " + ", ".join(adresses_invalides) + "."}, status=400)

    emails_utilises = {}
    for item in destinataires:
        personne = item["objet"]
        cle_email = personne.email.strip().casefold()
        emails_utilises.setdefault(cle_email, []).append(f"{personne.prenom} {personne.nom}".strip())
    doublons_email = [noms for noms in emails_utilises.values() if len(noms) > 1]
    if doublons_email:
        groupes = [" / ".join(noms) for noms in doublons_email]
        return JsonResponse({"error": "Une même adresse e-mail est sélectionnée plusieurs fois : " + "; ".join(groupes) + "."}, status=400)

    configuration = statut_configuration_email()
    logger.info("Demande d’envoi reçue : %s salarié(s), %s contact(s), %s document(s)", len(animateurs), len(contacts), len(documents_selectionnes))
    if not configuration["operationnel"]:
        return JsonResponse({"error": configuration["message"]}, status=503)

    try:
        pieces = charger_pieces_jointes(documents_selectionnes)
    except PiecesJointesError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    envoi = EnvoiEmail.objects.create(
        objet=objet,
        message=message,
        documents_titres=[document.titre for document in documents_selectionnes],
        nombre_destinataires=len(destinataires),
        mode_test=configuration["mode_test"],
    )
    envoi.documents.set(documents_selectionnes)

    resultats = []
    envoyes = 0
    echecs = 0
    try:
        with connexion_email() as connection:
            for item in destinataires:
                personne = item["objet"]
                objet_rendu = rendre_variables_email(objet, personne, semaines_reference).strip()
                message_rendu = rendre_variables_email(message, personne, semaines_reference).strip()
                try:
                    envoyer_un_message(animateur=personne, objet=objet_rendu, message=message_rendu, pieces=pieces, connection=connection, semaine_reference=semaines_reference)
                    statut = DestinataireEnvoiEmail.STATUT_ENVOYE
                    erreur_detail = ""
                    envoyes += 1
                except Exception as exc:
                    logger.exception("Échec de l’envoi SMTP vers %s", personne.email)
                    statut = DestinataireEnvoiEmail.STATUT_ECHEC
                    erreur_detail = str(exc)[:1000] or "Erreur d'envoi inconnue."
                    echecs += 1
                DestinataireEnvoiEmail.objects.create(
                    envoi=envoi, animateur=item["animateur"], contact_externe=item["contact"],
                    prenom=personne.prenom, nom=personne.nom, email=personne.email, statut=statut,
                    objet_rendu=objet_rendu, message_rendu=message_rendu, erreur=erreur_detail,
                )
                resultats.append({"type": item["type"], "id": item["id"], "nom": f"{personne.prenom} {personne.nom}".strip(), "email": personne.email, "statut": statut, "erreur": erreur_detail})
    except ConfigurationEmailError as exc:
        logger.error("Configuration e-mail invalide : %s", exc)
        envoi.delete()
        return JsonResponse({"error": str(exc)}, status=503)
    except Exception as exc:
        logger.exception("Impossible d’ouvrir ou d’utiliser la connexion SMTP")
        deja_traites = {(r["type"], r["id"]) for r in resultats}
        erreur_connexion = str(exc)[:1000] or "Connexion au serveur e-mail impossible."
        for item in destinataires:
            if (item["type"], item["id"]) in deja_traites:
                continue
            personne = item["objet"]
            DestinataireEnvoiEmail.objects.create(
                envoi=envoi, animateur=item["animateur"], contact_externe=item["contact"],
                prenom=personne.prenom, nom=personne.nom, email=personne.email,
                statut=DestinataireEnvoiEmail.STATUT_ECHEC,
                objet_rendu=rendre_variables_email(objet, personne, semaines_reference).strip(),
                message_rendu=rendre_variables_email(message, personne, semaines_reference).strip(), erreur=erreur_connexion,
            )
            resultats.append({"type": item["type"], "id": item["id"], "nom": f"{personne.prenom} {personne.nom}".strip(), "email": personne.email, "statut": DestinataireEnvoiEmail.STATUT_ECHEC, "erreur": erreur_connexion})
            echecs += 1

    envoi.nombre_envoyes = envoyes
    envoi.nombre_echecs = echecs
    envoi.save(update_fields=["nombre_envoyes", "nombre_echecs"])
    logger.info("Envoi terminé : %s envoyé(s), %s échec(s)", envoyes, echecs)

    return JsonResponse({
        "ok": echecs == 0,
        "mode_test": configuration["mode_test"],
        "nombre_envoyes": envoyes,
        "nombre_echecs": echecs,
        "resultats": resultats,
        "envoi": _envoi_email_to_dict(
            EnvoiEmail.objects.prefetch_related("documents", "destinataires").get(pk=envoi.pk)
        ),
    })


@require_POST
def api_planning_auto(request):
    """Endpoint HTTP du remplissage automatique.

    La logique métier est dans animateurs.services.planning_solver pour
    garder ce fichier concentré sur les entrées/sorties HTTP.
    """

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Requête invalide."}, status=400)

    from .services.planning_solver import generer_planning_auto

    data, status = generer_planning_auto(payload)
    return JsonResponse(data, status=status)


@require_http_methods(["GET", "POST"])
def api_emails_animateur(request, animateur_id):
    """Envoie directement un e-mail à un salarié et retourne son historique."""

    try:
        animateur = (
            Animateur.objects.prefetch_related("qualifications", "preferences__centre")
            .get(pk=animateur_id)
        )
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Salarié introuvable."}, status=404)

    if request.method == "GET":
        historique = (
            animateur.emails_recus.select_related("envoi")
            .order_by("-date_traitement", "-id")[:50]
        )
        documents_qs = list(Document.objects.prefetch_related("periodes").all())
        return JsonResponse({
            "configuration": statut_configuration_email(),
            "destinataire": animateur.email,
            "documents": [
                {
                    **document_to_dict(document),
                    "taille": _taille_document(document),
                }
                for document in documents_qs
            ],
            # Les modèles sont chargés par leur API dédiée. La clé vide est
            # conservée pour compatibilité, sans requête vers leur table.
            "modeles": [],
            "variables": variables_email_disponibles(),
            "historique": [
                {
                    "id": item.id,
                    "objet": item.objet_rendu or item.envoi.objet,
                    "message": item.message_rendu or item.envoi.message,
                    "documents": item.envoi.documents_titres,
                    "statut": item.statut,
                    "statut_libelle": item.get_statut_display(),
                    "erreur": item.erreur,
                    "date_creation": item.date_traitement.isoformat(),
                    "mode_test": item.envoi.mode_test,
                }
                for item in historique
            ],
        })

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide."}, status=400)

    objet = str(payload.get("objet", "")).strip()
    message = str(payload.get("message", "")).strip()
    document_ids = payload.get("document_ids", [])
    semaine_reference = None

    if not objet:
        return JsonResponse({"error": "L'objet de l'e-mail est obligatoire."}, status=400)
    if len(objet) > 200:
        return JsonResponse({"error": "L'objet ne peut pas dépasser 200 caractères."}, status=400)
    if not message:
        return JsonResponse({"error": "Le message est obligatoire."}, status=400)
    if len(message) > 10000:
        return JsonResponse({"error": "Le message est trop long."}, status=400)
    if not isinstance(document_ids, list):
        return JsonResponse({"error": "La sélection de documents est invalide."}, status=400)

    try:
        validate_email(animateur.email)
    except ValidationError:
        return JsonResponse({"error": "Ce salarié n'a pas d'adresse e-mail valide."}, status=400)

    try:
        ids_documents = list(dict.fromkeys(int(value) for value in document_ids))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection contient un document invalide."}, status=400)

    documents_selectionnes = list(Document.objects.filter(pk__in=ids_documents))
    if len(documents_selectionnes) != len(ids_documents):
        return JsonResponse({"error": "Un ou plusieurs documents n'existent plus."}, status=400)

    variables_supplementaires = {
        "identifiant": animateur.utilisateur.username if animateur.utilisateur_id else "Non disponible",
        "lien_connexion": request.build_absolute_uri("/connexion/"),
    }
    identifiants_provisoires = payload.get("identifiants_provisoires")
    if identifiants_provisoires is not None:
        if not isinstance(identifiants_provisoires, dict):
            return JsonResponse({"error": "Les identifiants provisoires sont invalides."}, status=400)
        username = str(identifiants_provisoires.get("username", "")).strip()
        temporary_password = str(identifiants_provisoires.get("temporary_password", "")).strip()
        if not animateur.utilisateur_id or username != animateur.utilisateur.username:
            return JsonResponse({"error": "L’identifiant provisoire ne correspond pas au compte du salarié."}, status=400)
        if not animateur.doit_changer_mot_de_passe or not temporary_password or len(temporary_password) > 200:
            return JsonResponse({"error": "Le mot de passe provisoire n’est plus disponible. Réinitialise-le avant l’envoi."}, status=400)
        variables_supplementaires["mot_de_passe_provisoire"] = temporary_password
    else:
        variables_supplementaires["mot_de_passe_provisoire"] = "[réinitialisation nécessaire]"

    configuration = statut_configuration_email()
    if not configuration["operationnel"]:
        return JsonResponse({"error": configuration["message"]}, status=503)

    try:
        pieces = charger_pieces_jointes(documents_selectionnes)
    except PiecesJointesError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    envoi = EnvoiEmail.objects.create(
        objet=objet,
        message=message,
        documents_titres=[document.titre for document in documents_selectionnes],
        nombre_destinataires=1,
        mode_test=configuration["mode_test"],
    )
    envoi.documents.set(documents_selectionnes)

    objet_rendu = rendre_variables_email(objet, animateur, semaine_reference, variables_supplementaires).strip()
    message_rendu = rendre_variables_email(message, animateur, semaine_reference, variables_supplementaires).strip()
    statut = DestinataireEnvoiEmail.STATUT_ECHEC
    erreur = ""
    try:
        with connexion_email() as connection:
            envoyer_un_message(
                animateur=animateur,
                objet=objet_rendu,
                message=message_rendu,
                pieces=pieces,
                connection=connection,
                semaine_reference=semaine_reference,
                variables_supplementaires=variables_supplementaires,
            )
        statut = DestinataireEnvoiEmail.STATUT_ENVOYE
        envoi.nombre_envoyes = 1
    except Exception as exc:
        erreur = str(exc)[:1000] or "Erreur d'envoi inconnue."
        envoi.nombre_echecs = 1

    destinataire = DestinataireEnvoiEmail.objects.create(
        envoi=envoi,
        animateur=animateur,
        prenom=animateur.prenom,
        nom=animateur.nom,
        email=animateur.email,
        statut=statut,
        objet_rendu=objet_rendu,
        message_rendu=(
            message_rendu.replace(variables_supplementaires.get("mot_de_passe_provisoire", ""), "[mot de passe provisoire envoyé]")
            if identifiants_provisoires else message_rendu
        ),
        erreur=erreur,
    )
    envoi.save(update_fields=["nombre_envoyes", "nombre_echecs"])

    if statut == DestinataireEnvoiEmail.STATUT_ECHEC:
        return JsonResponse({
            "error": erreur,
            "statut": statut,
            "historique_id": destinataire.id,
        }, status=502)

    return JsonResponse({
        "ok": True,
        "statut": statut,
        "mode_test": configuration["mode_test"],
        "historique_id": destinataire.id,
    })



@never_cache
@require_http_methods(["GET", "POST"])
def api_effectifs_enfants_groupe(request, evenement_id):
    """Lit ou enregistre les effectifs et exceptions d’encadrement d’un groupe."""
    try:
        evenement = Evenement.objects.get(pk=evenement_id)
    except Evenement.DoesNotExist:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)

    if request.method == "GET":
        debut = parse_date(request.GET.get("debut", ""))
        fin = parse_date(request.GET.get("fin", ""))
        queryset = evenement.effectifs_enfants.all()
        if debut:
            queryset = queryset.filter(date__gte=debut)
        if fin:
            queryset = queryset.filter(date__lt=fin)
        return JsonResponse(
            [
                {
                    "date": item.date.isoformat(),
                    "nombre": item.nombre,
                    "enfants_par_animateur": item.ratio_encadrement_effectif,
                    "ratio_encadrement_exceptionnel": item.ratio_encadrement_exceptionnel,
                }
                for item in queryset
            ],
            safe=False,
        )

    try:
        payload = json.loads(request.body)
        effectifs = payload.get("effectifs")
        ratios = payload.get("ratios_encadrement")

        if effectifs is not None:
            if not isinstance(effectifs, list):
                raise ValueError
            normalises_effectifs = []
            for valeur in effectifs:
                jour = parse_date(str(valeur.get("date", "")))
                nombre = int(valeur.get("nombre", 0))
                if not jour or nombre < 0 or nombre > 999:
                    raise ValueError
                normalises_effectifs.append((jour, nombre))
        else:
            normalises_effectifs = []

        if ratios is not None:
            if not isinstance(ratios, list):
                raise ValueError
            normalises_ratios = []
            for valeur in ratios:
                jour = parse_date(str(valeur.get("date", "")))
                brut = valeur.get("ratio")
                ratio = None if brut in (None, "") else int(brut)
                if not jour or (ratio is not None and (ratio < 1 or ratio > 999)):
                    raise ValueError
                normalises_ratios.append((jour, ratio))
        else:
            normalises_ratios = []

        if effectifs is None and ratios is None:
            raise ValueError
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Les données transmises sont invalides."}, status=400)

    with transaction.atomic():
        for jour, nombre in normalises_effectifs:
            ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour).first()
            if nombre == 0:
                if ligne and ligne.ratio_encadrement_exceptionnel:
                    ligne.nombre = 0
                    ligne.enfants_par_animateur = ligne.ratio_encadrement_effectif
                    ligne.save(update_fields=["nombre", "enfants_par_animateur", "modifie_le"])
                elif ligne:
                    ligne.delete()
            else:
                ratio = ligne.ratio_encadrement_effectif if ligne else evenement.enfants_par_animateur_defaut
                EffectifEnfantsJour.objects.update_or_create(
                    evenement=evenement,
                    date=jour,
                    defaults={"nombre": nombre, "enfants_par_animateur": ratio},
                )

        for jour, ratio in normalises_ratios:
            ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour).first()
            if ratio is None:
                if ligne:
                    ligne.ratio_encadrement_exceptionnel = None
                    ligne.enfants_par_animateur = evenement.enfants_par_animateur_defaut
                    if ligne.nombre == 0:
                        ligne.delete()
                    else:
                        ligne.save(update_fields=[
                            "ratio_encadrement_exceptionnel",
                            "enfants_par_animateur",
                            "modifie_le",
                        ])
            else:
                EffectifEnfantsJour.objects.update_or_create(
                    evenement=evenement,
                    date=jour,
                    defaults={
                        "nombre": ligne.nombre if ligne else 0,
                        "enfants_par_animateur": ratio,
                        "ratio_encadrement_exceptionnel": ratio,
                    },
                )
    return JsonResponse({"ok": True})
