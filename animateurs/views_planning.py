"""API du planning et des affectations."""

import datetime
import json

from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods, require_POST

from .access import est_direction
from .models import Affectation, Animateur, Centre, Evenement, Formation, HoraireAffectationJour, PublicationPlanning, Qualification
from .services.affectations import (
    creer_affectation,
    creer_ou_deplacer_affectation_flottante,
    modifier_affectation,
    supprimer_jour_affectation,
)
from .services.dates import parse_to_aware_datetime
from .services.flottants import est_groupe_flottants
from .services.serializers import affectation_to_event

# ---------------------------------------------------------------------------
# API - Planning (lecture des groupes + écriture individuelle)
# ---------------------------------------------------------------------------


def _lundi_semaine(date):
    return date - datetime.timedelta(days=date.weekday())


@require_http_methods(["GET", "POST"])
def api_publication_planning(request):
    """Consulte ou modifie la publication de la semaine affichée."""
    valeur = request.GET.get("date") if request.method == "GET" else None
    if request.method == "POST":
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON invalide."}, status=400)
        valeur = payload.get("date")
    date_reference = parse_date(str(valeur or ""))
    if date_reference is None:
        return JsonResponse({"error": "Date invalide."}, status=400)
    lundi = _lundi_semaine(date_reference)
    publication, _ = PublicationPlanning.objects.get_or_create(semaine_debut=lundi)
    if request.method == "POST":
        publication.publie = bool(payload.get("publie"))
        publication.save(update_fields=["publie", "date_modification"])
    return JsonResponse({"semaine_debut": lundi.isoformat(), "publie": publication.publie})


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

    if not est_direction(request.user):
        date_reference = None
        try:
            if start:
                date_reference = parse_to_aware_datetime(start).date()
        except ValueError:
            return JsonResponse({"error": "Paramètre start invalide."}, status=400)
        if date_reference is not None:
            lundi = _lundi_semaine(date_reference)
            if not PublicationPlanning.objects.filter(semaine_debut=lundi, publie=True).exists():
                return JsonResponse([], safe=False)

    qualifications_statuts = Qualification.objects.select_related("statut").only(
        "id", "nom", "icone", "est_statut", "statut_id",
        "statut__id", "statut__nom", "statut__est_statut",
    )
    affectations = (
        Affectation.objects.select_related("animateur", "centre", "evenement", "evenement__groupe")
        .prefetch_related(
            "horaires_journaliers",
            Prefetch("animateur__qualifications", queryset=qualifications_statuts),
            Prefetch(
                "animateur__formations",
                queryset=Formation.objects.filter(
                    statut__in=(Formation.STATUT_PREVUE, Formation.STATUT_EN_COURS)
                ).only("id", "intitule", "date_debut", "date_fin", "statut"),
                to_attr="_planning_formations",
            ),
        )
    )

    if not est_direction(request.user):
        animateur = getattr(request.user, "profil_animateur", None)
        if animateur is None:
            return JsonResponse([], safe=False)
        affectations_personnelles = animateur.affectations.all()
        if start and end:
            try:
                debut_personnel = parse_to_aware_datetime(start)
                fin_personnelle = parse_to_aware_datetime(end)
                affectations_personnelles = affectations_personnelles.filter(
                    debut__lt=fin_personnelle,
                    fin__gt=debut_personnel,
                )
            except ValueError:
                return JsonResponse({"error": "Paramètres start/end invalides."}, status=400)
        centre_ids = affectations_personnelles.values_list("centre_id", flat=True).distinct()
        affectations = affectations.filter(centre_id__in=centre_ids)

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
            evenement = Evenement.objects.select_related("centre", "groupe").get(pk=evenement_id)
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
        type_demande = payload.get("type_affectation", "groupe")
        if type_demande == "flottant":
            affectation, creation = creer_ou_deplacer_affectation_flottante(
                animateur=animateur,
                centre=centre,
                debut=debut,
                fin=fin,
                autoriser_formation=payload.get("forcer_formation") is True,
            )
            return JsonResponse(
                affectation_to_event(affectation),
                status=201 if creation else 200,
            )
        if type_demande != "groupe":
            return JsonResponse({"error": "Type d’affectation invalide."}, status=400)

        affectation = creer_affectation(
            animateur=animateur,
            centre=centre,
            evenement=evenement,
            debut=debut,
            fin=fin,
            autoriser_formation=payload.get("forcer_formation") is True,
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
        jour = parse_date(request.GET.get("date", "")) if request.GET.get("date") else None
        if request.GET.get("date") and jour is None:
            return JsonResponse({"error": "Date invalide."}, status=400)
        try:
            if jour:
                supprimer_jour_affectation(affectation, jour)
            else:
                affectation.delete()
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
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
            nouvelle_evenement = Evenement.objects.select_related("centre", "groupe").get(pk=payload["evenement_id"])
            if est_groupe_flottants(nouvelle_evenement) and payload.get("type_affectation") != "flottant":
                return JsonResponse({"error": "Groupe introuvable."}, status=404)
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
            type_affectation=payload.get("type_affectation") if "type_affectation" in payload else None,
            autoriser_formation=payload.get("forcer_formation") is True,
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)

    return JsonResponse(affectation_to_event(affectation))


@require_POST
def api_horaires_affectations_groupe(request, evenement_id):
    """Enregistre les horaires de chaque animateur du groupe sur la semaine."""
    try:
        evenement = Evenement.objects.select_related("groupe").get(pk=evenement_id)
        if est_groupe_flottants(evenement):
            raise Evenement.DoesNotExist
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
