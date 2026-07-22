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
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .access import est_direction
from .models import (
    QUALIFICATION_ICON_CHOICES,
    Affectation,
    AffiniteGroupeAnimateur,
    Animateur,
    Centre,
    Disponibilite,
    Document,
    Evenement,
    Groupe,
    HoraireAffectationJour,
    PeriodeScolaire,
    PreferenceCentre,
    Qualification,
    normaliser_cle_unique,
)
from .services.affectations import creer_affectation, modifier_affectation
from .services.affinites import synchroniser_affinites_groupes
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
from .services.comptes import traiter_acces_compte, valider_mot_de_passe
from .services.dashboard import generer_tableau_de_bord
from .services.dates import parse_to_aware_datetime
from .services.disponibilites import fusionner_et_nettoyer_disponibilites
from .services.documents import valider_periode_document
from .services.evenements import (
    FermetureAvecAffectationsError,
    creer_evenement,
    modifier_evenement,
    reordonner_evenements,
    supprimer_evenement,
)
from .services.planning_exports import (
    generer_planning_excel,
    generer_planning_pdf,
    horaires_manquants_export,
)
from .services.recapitulatif import generer_recapitulatif
from .services.serializers import (
    affectation_to_event,
    animateur_planning_to_dict,
    animateur_to_dict,
    centre_to_dict,
    document_to_dict,
    evenement_to_dict,
    qualification_to_dict,
)
from .services.situation_semaine import jours_ouverts_planning, situation_animateur_semaine

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
    return render(request, "accueil.html", {"active_page": "accueil"})


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
    if animateur is None:
        return render(
            request,
            "mes_disponibilites.html",
            {
                "active_page": "disponibilites",
                "animateur": None,
                "erreur_profil": True,
            },
        )
    return render(
        request,
        "mes_disponibilites.html",
        {
            "active_page": "disponibilites",
            "animateur": animateur,
            "erreur_profil": False,
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
            "semaines_export": PeriodeScolaire.objects.all().order_by("-annee_scolaire", "debut", "ordre", "nom"),
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


# ---------------------------------------------------------------------------
# API - Animateurs (lecture, création, suppression)
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
def api_animateurs(request):
    """GET : liste tous les animateurs.
    POST : crée un animateur avec ses coordonnées, qualifications, un centre préféré et des centres secondaires."""

    if request.method == "GET":
        inclure_affectations = request.GET.get("include_affectations") == "1"
        format_planning = request.GET.get("format") == "planning"
        debut_brut = request.GET.get("debut", "")
        fin_brut = request.GET.get("fin", "")
        debut_filtre = parse_date(debut_brut)
        fin_filtre = parse_date(fin_brut)
        plage_incomplete = bool(debut_brut) != bool(fin_brut)
        plage_invalide = bool(debut_brut) and (not debut_filtre or not fin_filtre or fin_filtre <= debut_filtre)
        if plage_incomplete or plage_invalide:
            return JsonResponse({"error": "La plage debut/fin est invalide."}, status=400)
        # Cette route doit rester strictement en lecture seule. Les affinités
        # sont déjà recalculées par les signaux lors des créations, déplacements
        # et suppressions d’affectations, ainsi qu’avant/après le remplissage
        # automatique. Une synchronisation globale ici provoquait des écritures
        # concurrentes au simple chargement du Planning et pouvait entraîner des
        # erreurs 500 intermittentes (notamment « database is locked » sous
        # SQLite).
        # Cette route est volontairement en lecture seule. L'ancienne version
        # nettoyait et réécrivait les disponibilités de chaque salarié à
        # chaque affichage de la liste, ce qui provoquait des centaines de
        # requêtes sur PostgreSQL/Supabase.
        #
        # Les disponibilités sont déjà normalisées lorsqu'elles sont ajoutées
        # ou modifiées dans les routes dédiées. Ici, on charge simplement
        # toutes les relations utiles en un nombre fixe de requêtes.
        disponibilites = Disponibilite.objects.only("id", "animateur_id", "debut", "fin")
        if debut_filtre and fin_filtre:
            disponibilites = disponibilites.filter(debut__lt=fin_filtre, fin__gte=debut_filtre)

        qualifications = Qualification.objects.select_related("statut").only(
            "id", "nom", "icone", "est_statut", "statut_id",
            "statut__id", "statut__nom", "statut__est_statut",
        )
        preferences = PreferenceCentre.objects.select_related("centre").only(
            "id",
            "animateur_id",
            "centre_id",
            "est_prefere",
            "est_interdit",
            "centre__id",
            "centre__nom",
            "centre__code",
            "centre__couleur",
        )
        animateurs = Animateur.objects.prefetch_related(
            Prefetch("qualifications", queryset=qualifications),
            Prefetch("preferences", queryset=preferences),
            Prefetch("disponibilites", queryset=disponibilites, to_attr="_filtre_disponibilites"),
        )
        if format_planning:
            animateurs = animateurs.only("id", "prenom", "nom", "telephone", "email")
        else:
            affinites = AffiniteGroupeAnimateur.objects.select_related("evenement__centre")
            animateurs = animateurs.select_related(
                "evenement_preferee__centre",
                "utilisateur",
            ).prefetch_related(Prefetch("affinites_groupes", queryset=affinites))
        if inclure_affectations:
            affectations = Affectation.objects.only("id", "animateur_id", "centre_id", "debut", "fin")
            if debut_filtre and fin_filtre:
                tz = timezone.get_current_timezone()
                debut_dt = timezone.make_aware(datetime.datetime.combine(debut_filtre, datetime.time.min), tz)
                fin_dt = timezone.make_aware(datetime.datetime.combine(fin_filtre, datetime.time.min), tz)
                affectations = affectations.filter(debut__lt=fin_dt, fin__gt=debut_dt)
            animateurs = animateurs.prefetch_related(
                Prefetch(
                    "affectations",
                    queryset=affectations,
                    to_attr="_filtre_affectations",
                )
            )
        animateurs = list(animateurs.order_by("prenom", "nom", "id"))

        # La situation de la semaine est calculée côté serveur à partir de tous
        # les groupes, y compris ceux dont le centre est masqué dans l'interface.
        # Cela évite de dépendre du chargement asynchrone des calendriers et des
        # conversions de fuseau horaire dans le navigateur.
        if format_planning and debut_filtre and fin_filtre:
            jours_ouverts = jours_ouverts_planning(debut_filtre, fin_filtre)
            for animateur in animateurs:
                animateur._situation_semaine = situation_animateur_semaine(
                    animateur,
                    jours_ouverts,
                    debut_filtre,
                    fin_filtre,
                )

        serializer = animateur_planning_to_dict if format_planning else animateur_to_dict
        return JsonResponse([serializer(a) for a in animateurs], safe=False)

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
        qualification_ids = payload.get("qualifications", [])
        centres_preferes, centres_interdits, erreur_centres = normaliser_centres_hierarchises(payload)
        if erreur_centres:
            return JsonResponse({"error": erreur_centres}, status=400)
        evenement_preferee, evenement_preferee_fournie, erreur_evenement = normaliser_evenement_preferee(
            payload, (centres_preferes[0] if centres_preferes else None)
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
            role=role,
            evenement_preferee=evenement_preferee if evenement_preferee_fournie else None,
        )

        if qualification_ids:
            # .set() sur un ManyToMany remplace toute la liste en une requête.
            animateur.qualifications.set(Qualification.objects.filter(pk__in=qualification_ids))

        appliquer_centres_hierarchises(animateur, centres_preferes, centres_interdits)

        if evenement_preferee_fournie:
            animateur.evenement_preferee = evenement_preferee
            animateur.save(update_fields=["evenement_preferee"])

        try:
            identifiants = traiter_acces_compte(animateur, payload)
        except ValidationError as exc:
            return JsonResponse({"error": exc.messages[0]}, status=400)

    animateur = (
        Animateur.objects.select_related(
            "evenement_preferee__centre",
            "utilisateur",
        )
        .prefetch_related(
            "qualifications",
            "preferences__centre",
            "disponibilites",
            "affinites_groupes__evenement__centre",
        )
        .get(pk=animateur.id)
    )

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
        animateur = (
            Animateur.objects.select_related(
                "evenement_preferee__centre",
                "utilisateur",
            )
            .prefetch_related(
                "qualifications",
                "preferences__centre",
                "disponibilites",
            )
            .get(pk=animateur_id)
        )
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Animateur introuvable."}, status=404)

    if request.method == "GET":
        synchroniser_affinites_groupes(animateur_ids=[animateur.id])
        animateur = (
            Animateur.objects.select_related(
                "evenement_preferee__centre",
                "utilisateur",
            )
            .prefetch_related(
                "qualifications",
                "preferences__centre",
                "disponibilites",
                "affinites_groupes__evenement__centre",
            )
            .get(pk=animateur.id)
        )
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

        if not animateur.prenom or not animateur.nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

        if (
            Animateur.objects.exclude(pk=animateur.pk)
            .filter(cle_unique=normaliser_cle_unique(animateur.prenom, animateur.nom))
            .exists()
        ):
            return JsonResponse({"error": f"L’employé « {animateur.prenom} {animateur.nom} » existe déjà."}, status=409)

        qualification_ids = payload.get("qualifications", None)
        centres_preferes, centres_interdits, erreur_centres = normaliser_centres_hierarchises(payload)
        if erreur_centres:
            return JsonResponse({"error": erreur_centres}, status=400)

        if centres_preferes is None and centres_interdits is None:
            relation_preferee = next(
                (pref for pref in animateur.preferences.all() if pref.est_prefere),
                None,
            )
            centre_prefere_effectif = relation_preferee.centre_id if relation_preferee else None
        else:
            centre_prefere_effectif = centres_preferes[0] if centres_preferes else None

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
            animateur.qualifications.set(Qualification.objects.filter(pk__in=qualification_ids))

        appliquer_centres_hierarchises(animateur, centres_preferes, centres_interdits)

        if evenement_preferee_fournie:
            animateur.evenement_preferee = evenement_preferee
            animateur.save(update_fields=["evenement_preferee"])

        try:
            identifiants = traiter_acces_compte(animateur, payload)
        except ValidationError as exc:
            return JsonResponse({"error": exc.messages[0]}, status=400)

    animateur = (
        Animateur.objects.select_related(
            "evenement_preferee__centre",
            "utilisateur",
        )
        .prefetch_related(
            "qualifications",
            "preferences__centre",
            "disponibilites",
            "affinites_groupes__evenement__centre",
        )
        .get(pk=animateur.id)
    )

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
        animateur = Animateur.objects.prefetch_related(
            "qualifications", "preferences__centre", "disponibilites", "affectations"
        ).get(pk=animateur_id)
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
            groupe = groupes.setdefault(
                cle,
                {
                    "id": f"{periode.annee_scolaire}-{periode.zone}-{periode.nom}",
                    "nom": periode.nom,
                    "annee_scolaire": periode.annee_scolaire,
                    "zone": periode.zone,
                    "debut": periode.debut,
                    "fin": periode.fin,
                    "jours": set(),
                },
            )
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

        jours_autorises = {jour for groupe in periodes_regroupees() for jour in groupe["jours"]}
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
            Disponibilite.objects.bulk_create(
                [Disponibilite(animateur=animateur, debut=debut, fin=fin) for debut, fin in plages]
            )

    disponibilites = list(animateur.disponibilites.all())

    def est_disponible(jour):
        return any(plage.debut <= jour <= plage.fin for plage in disponibilites)

    resultat = []
    for groupe in periodes_regroupees():
        jours = sorted(groupe["jours"])
        jours_json = [{"date": jour.isoformat(), "disponible": est_disponible(jour)} for jour in jours]
        resultat.append(
            {
                "id": groupe["id"],
                "nom": groupe["nom"],
                "annee_scolaire": groupe["annee_scolaire"],
                "zone": groupe["zone"],
                "debut": groupe["debut"].isoformat(),
                "fin": groupe["fin"].isoformat(),
                "selectionnee": any(item["disponible"] for item in jours_json),
                "jours": jours_json,
            }
        )

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

    qualifications_statuts = Qualification.objects.select_related("statut").only(
        "id", "nom", "icone", "est_statut", "statut_id",
        "statut__id", "statut__nom", "statut__est_statut",
    )
    affectations = (
        Affectation.objects.select_related("animateur", "centre", "evenement")
        .prefetch_related(
            "horaires_journaliers",
            Prefetch("animateur__qualifications", queryset=qualifications_statuts),
        )
    )

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
        fin = parse_to_aware_datetime(payload["fin"]) if payload.get("fin") else debut + datetime.timedelta(days=1)

    except (Animateur.DoesNotExist, Centre.DoesNotExist, Evenement.DoesNotExist):
        return JsonResponse({"error": "Animateur, centre ou groupe introuvable."}, status=404)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        affectation = creer_affectation(animateur=animateur, centre=centre, evenement=evenement, debut=debut, fin=fin)
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

        if "horaires" in payload:
            horaires = payload["horaires"]
            if not isinstance(horaires, list):
                raise ValueError
            debut_jour = timezone.localtime(affectation.debut).date()
            fin_jour = timezone.localtime(affectation.fin).date()
            normalises = []
            for item in horaires:
                if not isinstance(item, dict):
                    raise ValueError
                jour = parse_date(item.get("date", ""))
                arrivee = parse_time(item.get("heure_arrivee", ""))
                depart = parse_time(item.get("heure_depart", ""))
                if not jour or not arrivee or not depart or depart <= arrivee or not (debut_jour <= jour < fin_jour):
                    raise ValueError
                normalises.append((jour, arrivee, depart))
            with transaction.atomic():
                affectation.horaires_journaliers.exclude(date__in=[item[0] for item in normalises]).delete()
                for jour, arrivee, depart in normalises:
                    HoraireAffectationJour.objects.update_or_create(
                        affectation=affectation,
                        date=jour,
                        defaults={"heure_arrivee": arrivee, "heure_depart": depart},
                    )
            # L'affectation de cette vue n'est pas toujours chargée avec
            # prefetch_related : le cache peut donc ne pas exister du tout.
            getattr(affectation, "_prefetched_objects_cache", {}).pop("horaires_journaliers", None)
            return JsonResponse(affectation_to_event(affectation))

        debut = parse_to_aware_datetime(payload["debut"]) if "debut" in payload else affectation.debut
        fin = parse_to_aware_datetime(payload["fin"]) if "fin" in payload else affectation.fin

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


@require_POST
def api_horaires_affectations_groupe(request, evenement_id):
    """Enregistre les horaires de chaque animateur du groupe sur la semaine."""
    try:
        evenement = Evenement.objects.get(pk=evenement_id)
        payload = json.loads(request.body)
        horaires = payload.get("horaires")
        if not isinstance(horaires, list):
            raise ValueError

        normalises = []
        for item in horaires:
            if not isinstance(item, dict):
                raise ValueError
            affectation_id = int(item.get("affectation_id"))
            jour = parse_date(item.get("date", ""))
            arrivee = parse_time(item.get("heure_arrivee", ""))
            depart = parse_time(item.get("heure_depart", ""))
            if not jour or not arrivee or not depart or depart <= arrivee:
                raise ValueError
            normalises.append((affectation_id, jour, arrivee, depart))
    except Evenement.DoesNotExist:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Horaires invalides."}, status=400)

    affectations = {
        affectation.id: affectation
        for affectation in Affectation.objects.filter(
            evenement=evenement,
            id__in=[item[0] for item in normalises],
        )
    }
    if len(affectations) != len({item[0] for item in normalises}):
        return JsonResponse({"error": "Une affectation ne correspond pas à ce groupe."}, status=400)
    for affectation_id, jour, _, _ in normalises:
        affectation = affectations[affectation_id]
        debut_jour = timezone.localtime(affectation.debut).date()
        fin_jour = timezone.localtime(affectation.fin).date()
        if not debut_jour <= jour < fin_jour:
            return JsonResponse({"error": "La date est hors de l’affectation."}, status=400)

    nombre = 0
    with transaction.atomic():
        for affectation_id, jour, arrivee, depart in normalises:
            affectation = affectations[affectation_id]
            HoraireAffectationJour.objects.update_or_create(
                affectation=affectation,
                date=jour,
                defaults={"heure_arrivee": arrivee, "heure_depart": depart},
            )
            nombre += 1

    return JsonResponse({"ok": True, "nombre": nombre})


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
        inclure_groupes = request.GET.get("include_groupes") == "1"
        if not inclure_groupes:
            centres = Centre.objects.all()
            return JsonResponse([centre_to_dict(c) for c in centres], safe=False)

        groupes = (
            Evenement.objects.prefetch_related(
                "periodes_scolaires",
                "dates_exclues",
                "besoins_qualifications__qualification",
            )
            .annotate(nb_affectations=Count("affectations", distinct=True))
            .order_by("ordre", "nom")
        )
        centres = Centre.objects.prefetch_related(
            Prefetch("evenements", queryset=groupes, to_attr="_groupes_planning")
        )
        data = []
        for centre in centres:
            item = centre_to_dict(centre)
            item["evenements"] = [
                evenement_to_dict(groupe, include_effectifs=False)
                for groupe in centre._groupes_planning
            ]
            data.append(item)
        return JsonResponse(data, safe=False)

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


def _groupe_partage_to_dict(groupe):
    return {
        "id": groupe.id,
        "nom": groupe.nom,
        "enfants_par_animateur_defaut": groupe.enfants_par_animateur_defaut,
        "nombre_instances": groupe.instances.count(),
        "lieux": [
            {"id": instance.centre_id, "nom": instance.centre.nom}
            for instance in groupe.instances.select_related("centre").order_by("centre__nom")
        ],
    }


def _enregistrer_caracteristiques_groupe(groupe, payload):
    nom = str(payload.get("nom", groupe.nom)).strip()
    ratio = int(payload.get("enfants_par_animateur_defaut", groupe.enfants_par_animateur_defaut))
    if not nom or ratio < 1 or ratio > 999:
        raise ValidationError("Le nom et un ratio compris entre 1 et 999 sont obligatoires.")
    groupe.nom = nom
    groupe.enfants_par_animateur_defaut = ratio
    groupe.save()

    for instance in groupe.instances.all():
        instance.nom = groupe.nom
        instance.enfants_par_animateur_defaut = groupe.enfants_par_animateur_defaut
        instance.save()
    return groupe


@require_http_methods(["GET", "POST"])
def api_groupes_partages(request):
    groupes = Groupe.objects.prefetch_related("instances__centre")
    if request.method == "GET":
        return JsonResponse([_groupe_partage_to_dict(groupe) for groupe in groupes], safe=False)
    try:
        payload = json.loads(request.body)
        with transaction.atomic():
            groupe = _enregistrer_caracteristiques_groupe(Groupe(), payload)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, ValidationError) as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Un groupe de ce nom existe déjà."}, status=409)
    return JsonResponse(_groupe_partage_to_dict(groupe), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_groupe_partage_detail(request, groupe_id):
    try:
        groupe = Groupe.objects.get(pk=groupe_id)
    except Groupe.DoesNotExist:
        return JsonResponse({"error": "Groupe partagé introuvable."}, status=404)
    if request.method == "DELETE":
        if groupe.instances.exists():
            return JsonResponse(
                {"error": "Ce groupe est encore utilisé dans un ou plusieurs lieux."},
                status=409,
            )
        groupe.delete()
        return JsonResponse({"ok": True})
    try:
        payload = json.loads(request.body)
        with transaction.atomic():
            _enregistrer_caracteristiques_groupe(groupe, payload)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, ValidationError) as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Un groupe de ce nom existe déjà."}, status=409)
    return JsonResponse(_groupe_partage_to_dict(groupe))


@require_http_methods(["GET", "POST"])
def api_groupes(request, centre_id):
    """Liste ou crée les groupes d’un lieu."""

    try:
        centre = Centre.objects.get(pk=centre_id)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Centre introuvable."}, status=404)

    if request.method == "GET":
        evenements = (
            centre.evenements.prefetch_related(
                "periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification", "effectifs_enfants"
            )
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
        groupe_id = payload.get("groupe_id")
        if groupe_id:
            groupe_partage = Groupe.objects.get(pk=int(groupe_id))
        else:
            nom_groupe = str(payload.get("nom", "")).strip()
            groupe_partage, creation = Groupe.objects.get_or_create(
                cle_unique=normaliser_cle_unique(nom_groupe),
                defaults={
                    "nom": nom_groupe,
                    "enfants_par_animateur_defaut": int(payload.get("enfants_par_animateur_defaut", 8) or 8),
                },
            )
            if creation:
                _enregistrer_caracteristiques_groupe(groupe_partage, payload)
        if centre.evenements.filter(groupe=groupe_partage).exists():
            return JsonResponse(
                {"error": "Ce groupe possède déjà une instance dans ce lieu."},
                status=409,
            )
        evenement = creer_evenement(
            centre=centre,
            nom=groupe_partage.nom,
            groupe_partage=groupe_partage,
            periode_ids=payload.get("periode_ids", []),
            effectif_cible=int(payload.get("effectif_cible", 1) or 1),
            enfants_par_animateur_defaut=groupe_partage.enfants_par_animateur_defaut,
            qualifications=payload.get("qualifications_requises"),
            jours_ouverts=payload.get("jours_ouverts", [0, 1, 2, 3, 4, 5]),
            ferme_jours_feries=payload.get("ferme_jours_feries", True) is not False,
            permanent=bool(payload.get("permanent", False)),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)
    except Groupe.DoesNotExist:
        return JsonResponse({"error": "Groupe partagé introuvable."}, status=404)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Un groupe de ce nom existe déjà dans ce lieu."}, status=409)

    evenement = (
        Evenement.objects.select_related("centre")
        .prefetch_related(
            "periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification", "effectifs_enfants"
        )
        .get(pk=evenement.pk)
    )
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
        if any(cle in payload for cle in ("nom", "enfants_par_animateur_defaut")):
            _enregistrer_caracteristiques_groupe(evenement.groupe, payload)
        evenement = modifier_evenement(
            evenement,
            nom=None,
            periode_ids=payload.get("periode_ids", []),
            periodes_fournies="periode_ids" in payload,
            effectif_cible=payload.get("effectif_cible") if "effectif_cible" in payload else None,
            enfants_par_animateur_defaut=None,
            qualifications=payload.get("qualifications_requises"),
            qualifications_fournies="qualifications_requises" in payload,
            jours_ouverts=payload.get("jours_ouverts") if "jours_ouverts" in payload else None,
            ferme_jours_feries=payload.get("ferme_jours_feries") if "ferme_jours_feries" in payload else None,
            permanent=payload.get("permanent") if "permanent" in payload else None,
            supprimer_affectations_dates_fermees=bool(payload.get("supprimer_affectations_dates_fermees", False)),
        )
    except FermetureAvecAffectationsError as exc:
        return JsonResponse(
            {
                "error": _message_validation(exc),
                "code": "affectations_dates_fermees",
                "nb_affectations": len(exc.affectations),
                "dates": [date.isoformat() for date in exc.dates],
            },
            status=409,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Un groupe de ce nom existe déjà dans ce lieu."}, status=409)

    evenement = (
        Evenement.objects.select_related("centre")
        .prefetch_related(
            "periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification", "effectifs_enfants"
        )
        .get(pk=evenement.pk)
    )
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


def _diplomes_avec_statut():
    return Qualification.objects.select_related("statut")


@require_http_methods(["GET", "POST"])
def api_qualifications(request):
    """GET : liste des diplômes/statuts. POST : création."""

    if request.method == "GET":
        qualifications = _diplomes_avec_statut().order_by("nom", "id")
        return JsonResponse([qualification_to_dict(q) for q in qualifications], safe=False)

    try:
        payload = json.loads(request.body)
        nom = payload["nom"].strip()
        selectionnable_auto = bool(payload.get("selectionnable_remplissage_auto", True))
        est_statut = bool(payload.get("est_statut", False))
        statut_id = payload.get("statut_id") or None
        icone = str(payload.get("icone", "") or "").strip()
        icones_valides = {cle for cle, _libelle in QUALIFICATION_ICON_CHOICES}

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

        if Qualification.objects.filter(cle_unique=normaliser_cle_unique(nom)).exists():
            return JsonResponse({"error": f"Le diplôme ou statut « {nom} » existe déjà."}, status=409)
        if statut_id and not Qualification.objects.filter(pk=statut_id, est_statut=True).exists():
            return JsonResponse({"error": "Le statut sélectionné est invalide."}, status=400)
        if icone not in icones_valides:
            return JsonResponse({"error": "L’icône sélectionnée est invalide."}, status=400)

    except ValueError as exc:
        return JsonResponse({"error": str(exc) or "Requête invalide."}, status=400)
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        with transaction.atomic():
            qualification = Qualification.objects.create(
                nom=nom,
                selectionnable_remplissage_auto=selectionnable_auto,
                est_statut=est_statut,
                statut_id=None if est_statut else statut_id,
                icone="" if est_statut else icone,
            )
    except IntegrityError:
        return JsonResponse({"error": f"Le diplôme ou statut « {nom} » existe déjà."}, status=409)

    qualification = _diplomes_avec_statut().get(pk=qualification.pk)
    return JsonResponse(qualification_to_dict(qualification), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_qualification_detail(request, qualification_id):
    """Consulte, modifie ou supprime un diplôme ou un statut."""

    try:
        qualification = _diplomes_avec_statut().get(pk=qualification_id)
    except Qualification.DoesNotExist:
        return JsonResponse({"error": "Diplôme ou statut introuvable."}, status=404)

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
        est_statut = bool(payload.get("est_statut", qualification.est_statut))
        statut_id = payload.get("statut_id", qualification.statut_id) or None
        icone = str(payload.get("icone", qualification.icone) or "").strip()
        icones_valides = {cle for cle, _libelle in QUALIFICATION_ICON_CHOICES}

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)
        if statut_id and not Qualification.objects.filter(pk=statut_id, est_statut=True).exclude(pk=qualification.pk).exists():
            return JsonResponse({"error": "Le statut sélectionné est invalide."}, status=400)
        if icone not in icones_valides:
            return JsonResponse({"error": "L’icône sélectionnée est invalide."}, status=400)

    except ValueError as exc:
        return JsonResponse({"error": str(exc) or "Requête invalide."}, status=400)
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        with transaction.atomic():
            qualification.nom = nom
            qualification.selectionnable_remplissage_auto = selectionnable_auto
            qualification.est_statut = est_statut
            qualification.statut_id = None if est_statut else statut_id
            qualification.icone = "" if est_statut else icone
            qualification.save(update_fields=["nom", "selectionnable_remplissage_auto", "est_statut", "statut", "icone", "cle_unique"])
    except IntegrityError:
        return JsonResponse({"error": f"Le diplôme ou statut « {nom} » existe déjà."}, status=409)

    qualification = _diplomes_avec_statut().get(pk=qualification.pk)
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
        PeriodeScolaire.objects.filter(annee_scolaire=annee_scolaire, zone=zone).values_list("debut", "fin")
    )
    resultat = []
    for semaine in semaines:
        item = semaine.to_dict()
        item["deja_enregistree"] = (semaine.debut, semaine.fin) in existantes
        resultat.append(item)

    return JsonResponse(
        {
            "annee_scolaire": annee_scolaire,
            "zone": zone,
            "periodes": resultat,
            "nombre": len(resultat),
        }
    )


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

    periodes = PeriodeScolaire.objects.filter(annee_scolaire=annee_scolaire, zone=zone)
    return JsonResponse(
        {
            "ok": True,
            "cree": creees,
            "mis_a_jour": mises_a_jour,
            "periodes": [_periode_scolaire_to_dict(p) for p in periodes],
        },
        status=201 if creees else 200,
    )


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

    return JsonResponse(
        {
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
        }
    )


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
