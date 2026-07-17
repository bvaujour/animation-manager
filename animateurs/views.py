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
import re
import secrets

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_POST

from .models import (
    Affectation, Animateur, Centre, DestinataireEnvoiEmail, Disponibilite,
    Document, EnvoiEmail, Evenement, PeriodeScolaire, Qualification,
)

from .services.affectations import creer_affectation, modifier_affectation
from .services.animateurs import (
    appliquer_centres_hierarchises,
    normaliser_centres_hierarchises,
    normaliser_evenement_preferee,
)
from .services.dates import parse_to_aware_datetime
from .services.disponibilites import fusionner_et_nettoyer_disponibilites
from .services.documents import valider_periode_document
from .services.emails import (
    ConfigurationEmailError,
    PiecesJointesError,
    charger_pieces_jointes,
    connexion_email,
    envoyer_un_message,
    statut_configuration_email,
)
from .services.calendrier_scolaire import (
    CalendrierScolaireError,
    recuperer_semaines,
)
from .services.centres import prochain_ordre_centre, reordonner_centres
from .services.evenements import (
    FermetureAvecAffectationsError,
    creer_evenement,
    modifier_evenement,
    reordonner_evenements,
    supprimer_evenement,
)
from .services.recapitulatif import generer_recapitulatif
from .services.planning_exports import generer_planning_excel, generer_planning_pdf
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

# ---------------------------------------------------------------------------
# Pages HTML
# ---------------------------------------------------------------------------
# Chaque vue ci-dessous se contente de rendre un template quasi vide : les
# données sont chargées côté client par le JS correspondant (voir
# static/js/<nom-de-la-page>.js), qui appelle les endpoints API plus bas.

def accueil(request):
    return render(request, "accueil.html", {"active_page": "accueil"})


def planning(request):
    """Page principale : un calendrier par centre, avec la liste des
    animateurs à glisser-déposer ou à affecter par clic."""
    return render(request, "planning.html", {"active_page": "planning"})



def gestion(request):
    """Page unique de gestion : salariés, lieux, groupes et qualifications."""
    return render(request, "gestion.html", {"active_page": "gestion"})


def recapitulatif(request):
    """Tableau de bord : jours travaillés par animateur/centre et alertes
    de suivi (animateurs jamais affectés, centres inutilisés, etc.)."""
    return render(request, "recapitulatif.html", {"active_page": "recapitulatif"})


def documents(request):
    """Page /documents/ : la liste elle-même est chargée dynamiquement en
    JS (voir static/js/documents.js + api_documents plus bas), cette vue
    ne fait que rendre le squelette de la page."""
    return render(request, "documents.html", {"active_page": "documents"})


def administration(request):
    """Page regroupant les outils d'export et, plus tard, de sauvegarde."""
    today = timezone.localdate()
    debut_mois = today.replace(day=1)
    return render(request, "administration.html", {
        "active_page": "administration",
        "periode_debut": debut_mois.isoformat(),
        "periode_fin": today.isoformat(),
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
            "evenement_preferee__centre",
        ).prefetch_related(
            "qualifications",
            "preferences__centre",
            "disponibilites",
        ).order_by("prenom", "nom", "id")

        return JsonResponse([animateur_to_dict(a) for a in animateurs], safe=False)

    try:
        payload = json.loads(request.body)

        prenom = payload["prenom"].strip()
        nom = payload["nom"].strip()
        telephone = payload.get("telephone", "").strip()
        email = payload.get("email", "").strip()
        date_naissance_raw = payload.get("date_naissance") or None
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
            couleur=couleur,
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

    animateur = Animateur.objects.select_related(
        "evenement_preferee__centre",
    ).prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    return JsonResponse(animateur_to_dict(animateur), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_animateur_detail(request, animateur_id):
    """GET : renvoie un animateur.
    PATCH : modifie un ou plusieurs champs de l'animateur, y compris ses qualifications et ses centres autorisés.
    DELETE : supprime l'animateur et, par cascade, son planning/disponibilités/centres autorisés."""

    try:
        animateur = Animateur.objects.select_related(
            "evenement_preferee__centre",
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
        animateur.delete()
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

        if "couleur" in payload:
            couleur = (payload.get("couleur") or "").strip()
            if couleur and not re.fullmatch(r"#[0-9A-Fa-f]{6}", couleur):
                return JsonResponse({"error": "La couleur doit être au format #RRGGBB."}, status=400)
            animateur.couleur = couleur

        if not animateur.prenom or not animateur.nom:
            return JsonResponse({"error": "Le prénom et le nom sont obligatoires."}, status=400)

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

    animateur = Animateur.objects.select_related(
        "evenement_preferee__centre",
    ).prefetch_related(
        "qualifications",
        "preferences__centre",
        "disponibilites",
    ).get(pk=animateur.id)

    return JsonResponse(animateur_to_dict(animateur))


@require_http_methods(["GET", "PUT"])
def api_disponibilites(request, animateur_id):
    """Gère les disponibilités à partir de la bibliothèque des périodes.

    GET renvoie les périodes regroupées avec leurs jours et l'état de chaque
    case. PUT remplace les disponibilités de l'animateur par la liste des
    journées cochées reçue dans ``jours_disponibles``.
    """
    try:
        animateur = Animateur.objects.get(pk=animateur_id)
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
        if payload.get("fin"):
            fin = parse_to_aware_datetime(payload["fin"])
        else:
            fin = debut + datetime.timedelta(days=1)

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

    try:
        centre.save()
    except IntegrityError:
        return JsonResponse({"error": f"Le code « {centre.code} » est déjà utilisé par un autre centre."}, status=409)

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
            .prefetch_related("periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification")
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
            qualifications=payload.get("qualifications_requises", {}),
            jours_ouverts=payload.get("jours_ouverts", [0, 1, 2, 3, 4, 5]),
            ferme_jours_feries=payload.get("ferme_jours_feries", True) is not False,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Un groupe de ce nom existe déjà dans ce lieu."}, status=409)

    evenement = Evenement.objects.select_related("centre").prefetch_related(
        "periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification"
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
            qualifications=payload.get("qualifications_requises", {}),
            qualifications_fournies="qualifications_requises" in payload,
            jours_ouverts=payload.get("jours_ouverts") if "jours_ouverts" in payload else None,
            ferme_jours_feries=payload.get("ferme_jours_feries") if "ferme_jours_feries" in payload else None,
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
        "periodes_scolaires", "dates_exclues", "besoins_qualifications__qualification"
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


@require_http_methods(["GET", "POST"])
def api_qualifications(request):
    """GET : liste des qualifications. POST : création d'une qualification."""

    if request.method == "GET":
        qualifications = Qualification.objects.all()
        return JsonResponse([qualification_to_dict(q) for q in qualifications], safe=False)

    try:
        payload = json.loads(request.body)
        nom = payload["nom"].strip()
        selectionnable_auto = bool(payload.get("selectionnable_remplissage_auto", False))

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    qualification = Qualification.objects.create(
        nom=nom,
        selectionnable_remplissage_auto=selectionnable_auto,
    )

    return JsonResponse(qualification_to_dict(qualification), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_qualification_detail(request, qualification_id):
    """GET : renvoie une qualification. PATCH : modifie son nom.
    DELETE : supprime la qualification (elle est simplement retirée de la liste
    des animateurs qui l'avaient, grâce au comportement par défaut de
    Django sur les relations ManyToMany)."""

    try:
        qualification = Qualification.objects.get(pk=qualification_id)
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

        if not nom:
            return JsonResponse({"error": "Le nom est obligatoire."}, status=400)

    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    qualification.nom = nom
    qualification.selectionnable_remplissage_auto = selectionnable_auto
    qualification.save(update_fields=["nom", "selectionnable_remplissage_auto"])

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
        "centres": [
            {
                "id": centre.id,
                "nom": centre.nom,
                "code": centre.code,
                "couleur": centre.couleur,
            }
            for centre in recap["centres"]
        ],
        "animateurs": recap["animateurs"],
        "evenements": recap["evenements"],
        "alertes": recap["alertes"],
        "synthese": recap["synthese"],
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
        documents_qs = Document.objects.all().order_by("-permanent", "-periode_debut", "-date_ajout")
        return JsonResponse([document_to_dict(d) for d in documents_qs], safe=False)

    titre = request.POST.get("titre", "").strip()
    fichier = request.FILES.get("fichier")
    permanent = request.POST.get("permanent", "false").lower() in {"1", "true", "on", "yes"}
    periode_debut = parse_date(request.POST.get("periode_debut", ""))
    periode_fin = parse_date(request.POST.get("periode_fin", ""))

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
        permanent=permanent,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
    )

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
    permanent = bool(payload.get("permanent", document.permanent))
    periode_debut = parse_date(payload.get("periode_debut") or "")
    periode_fin = parse_date(payload.get("periode_fin") or "")

    if not titre:
        return JsonResponse({"error": "Le titre est obligatoire."}, status=400)

    periode_debut, periode_fin, erreur = valider_periode_document(
        permanent=permanent,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
    )
    if erreur:
        return JsonResponse({"error": erreur}, status=400)

    document.titre = titre
    document.permanent = permanent
    document.periode_debut = periode_debut
    document.periode_fin = periode_fin
    document.full_clean()
    document.save(update_fields=["titre", "permanent", "periode_debut", "periode_fin"])

    return JsonResponse(document_to_dict(document))


# ---------------------------------------------------------------------------
# API - Envois d'e-mails aux salariés
# ---------------------------------------------------------------------------


def _taille_document(document):
    try:
        return int(document.fichier.size)
    except (OSError, TypeError, ValueError):
        return None


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


@require_http_methods(["GET", "POST"])
def api_envois_email(request):
    """Prépare, exécute et historise les envois de documents aux salariés."""

    if request.method == "GET":
        animateurs = list(
            Animateur.objects.all()
            .prefetch_related("qualifications", "preferences__centre")
        )
        animateurs.sort(key=lambda a: (a.prenom.casefold(), a.nom.casefold(), a.pk))
        documents_qs = list(Document.objects.all())
        historique = (
            EnvoiEmail.objects.prefetch_related("documents", "destinataires")
            .all()[:30]
        )
        return JsonResponse({
            "configuration": statut_configuration_email(),
            "animateurs": [
                {
                    "id": animateur.id,
                    "prenom": animateur.prenom,
                    "nom": animateur.nom,
                    "email": animateur.email,
                    "qualifications": [q.nom for q in animateur.qualifications.all()],
                    "lieux": [pref.centre.nom for pref in animateur.preferences.all()],
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
            "historique": [_envoi_email_to_dict(envoi) for envoi in historique],
        })

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide."}, status=400)

    objet = str(payload.get("objet", "")).strip()
    message = str(payload.get("message", "")).strip()
    animateur_ids = payload.get("animateur_ids", [])
    document_ids = payload.get("document_ids", [])

    if not objet:
        return JsonResponse({"error": "L'objet de l'e-mail est obligatoire."}, status=400)
    if len(objet) > 200:
        return JsonResponse({"error": "L'objet ne peut pas dépasser 200 caractères."}, status=400)
    if not message:
        return JsonResponse({"error": "Le message est obligatoire."}, status=400)
    if len(message) > 10000:
        return JsonResponse({"error": "Le message est trop long."}, status=400)
    if not isinstance(animateur_ids, list) or not animateur_ids:
        return JsonResponse({"error": "Choisis au moins un salarié."}, status=400)
    if not isinstance(document_ids, list) or not document_ids:
        return JsonResponse({"error": "Choisis au moins un document à joindre."}, status=400)

    try:
        ids_animateurs = list(dict.fromkeys(int(value) for value in animateur_ids))
        ids_documents = list(dict.fromkeys(int(value) for value in document_ids))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection contient un identifiant invalide."}, status=400)

    if len(ids_animateurs) > 250:
        return JsonResponse({"error": "Un envoi est limité à 250 salariés."}, status=400)

    animateurs = list(Animateur.objects.filter(pk__in=ids_animateurs))
    documents_selectionnes = list(Document.objects.filter(pk__in=ids_documents))
    animateurs.sort(key=lambda a: (a.prenom.casefold(), a.nom.casefold(), a.pk))

    if len(animateurs) != len(ids_animateurs):
        return JsonResponse({"error": "Un ou plusieurs salariés n'existent plus."}, status=400)
    if len(documents_selectionnes) != len(ids_documents):
        return JsonResponse({"error": "Un ou plusieurs documents n'existent plus."}, status=400)

    sans_email = []
    for animateur in animateurs:
        try:
            validate_email(animateur.email)
        except ValidationError:
            sans_email.append(f"{animateur.prenom} {animateur.nom}")
    if sans_email:
        return JsonResponse({
            "error": "Adresse e-mail absente ou invalide pour : " + ", ".join(sans_email) + "."
        }, status=400)

    emails_utilises = {}
    for animateur in animateurs:
        cle_email = animateur.email.strip().casefold()
        emails_utilises.setdefault(cle_email, []).append(f"{animateur.prenom} {animateur.nom}")
    doublons_email = [noms for noms in emails_utilises.values() if len(noms) > 1]
    if doublons_email:
        groupes = [" / ".join(noms) for noms in doublons_email]
        return JsonResponse({
            "error": "Une même adresse e-mail est utilisée par plusieurs salariés : " + "; ".join(groupes) + "."
        }, status=400)

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
        nombre_destinataires=len(animateurs),
        mode_test=configuration["mode_test"],
    )
    envoi.documents.set(documents_selectionnes)

    resultats = []
    envoyes = 0
    echecs = 0
    try:
        with connexion_email() as connection:
            for animateur in animateurs:
                try:
                    envoyer_un_message(
                        animateur=animateur,
                        objet=objet,
                        message=message,
                        pieces=pieces,
                        connection=connection,
                    )
                    statut = DestinataireEnvoiEmail.STATUT_ENVOYE
                    erreur = ""
                    envoyes += 1
                except Exception as exc:  # le détail est historisé destinataire par destinataire
                    statut = DestinataireEnvoiEmail.STATUT_ECHEC
                    erreur = str(exc)[:1000] or "Erreur d'envoi inconnue."
                    echecs += 1

                DestinataireEnvoiEmail.objects.create(
                    envoi=envoi,
                    animateur=animateur,
                    prenom=animateur.prenom,
                    nom=animateur.nom,
                    email=animateur.email,
                    statut=statut,
                    erreur=erreur,
                )
                resultats.append({
                    "animateur_id": animateur.id,
                    "nom": f"{animateur.prenom} {animateur.nom}",
                    "email": animateur.email,
                    "statut": statut,
                    "erreur": erreur,
                })
    except ConfigurationEmailError as exc:
        envoi.delete()
        return JsonResponse({"error": str(exc)}, status=503)
    except Exception as exc:
        deja_traites = {resultat["animateur_id"] for resultat in resultats}
        erreur_connexion = str(exc)[:1000] or "Connexion au serveur e-mail impossible."
        for animateur in animateurs:
            if animateur.id in deja_traites:
                continue
            DestinataireEnvoiEmail.objects.create(
                envoi=envoi,
                animateur=animateur,
                prenom=animateur.prenom,
                nom=animateur.nom,
                email=animateur.email,
                statut=DestinataireEnvoiEmail.STATUT_ECHEC,
                erreur=erreur_connexion,
            )
            resultats.append({
                "animateur_id": animateur.id,
                "nom": f"{animateur.prenom} {animateur.nom}",
                "email": animateur.email,
                "statut": DestinataireEnvoiEmail.STATUT_ECHEC,
                "erreur": erreur_connexion,
            })
            echecs += 1

    envoi.nombre_envoyes = envoyes
    envoi.nombre_echecs = echecs
    envoi.save(update_fields=["nombre_envoyes", "nombre_echecs"])

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
