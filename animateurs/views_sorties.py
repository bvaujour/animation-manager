import datetime
import json

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Document,
    Evenement,
    PeriodeScolaire,
    Sortie,
    PreferenceTransportUtilisateur,
    SortieLien,
    SortieParticipation,
    SortieRenfort,
    SortieResponsabilite,
    code_postal_francais,
)
from animateurs.services.affectations import creer_affectation, supprimer_jour_affectation
from animateurs.services.flottants import groupes_visibles
from animateurs.services.documents import normaliser_nom_document
from animateurs.services.localisation import (
    LocalisationError,
    rechercher_communes_par_code_postal,
    rechercher_communes_par_nom,
    resoudre_localisation,
)
from animateurs.services.meteo_sorties import prevision_sortie
from animateurs.services.sorties import (
    animateurs_eligibles_responsabilites,
    calculer_participants_sortie,
    donnees_sortie,
    invalider_estimations_transport,
    remplacer_circuits_transport,
    synchroniser_circuits_transport,
)
from animateurs.services.routing import (
    RoutingError,
    estimate_sortie_route,
    routing_is_configured,
)


def sorties(request):
    return render(request, "sorties.html", {"active_page": "sorties"})


def sortie_detail(request, sortie_id):
    return render(request, "sortie_detail.html", {"active_page": "sorties", "sortie_id": sortie_id})


def _actualiser_localisation_destination(sortie, data):
    """Résout une sélection côté serveur sans rendre l'enregistrement dépendant du réseau."""

    if not data.get("destination_localisation_demandee") or not sortie.destination_code_postal:
        return
    try:
        localisation = resoudre_localisation(
            sortie.destination, sortie.destination_adresse,
            sortie.destination_code_postal, sortie.destination_commune,
            data.get("destination_code_insee", ""),
        )
        sortie.destination_code_insee = localisation["code_insee"]
        sortie.destination_latitude = localisation["latitude"]
        sortie.destination_longitude = localisation["longitude"]
        sortie.destination_precision = localisation["precision"]
    except LocalisationError:
        # La saisie textuelle reste valable et une nouvelle tentative sera
        # possible lors de la prochaine sélection ou modification.
        pass
    sortie.save(update_fields=[
        "destination_code_insee", "destination_latitude",
        "destination_longitude", "destination_precision",
    ])


@require_http_methods(["POST", "DELETE"])
def api_sortie_renforts(request, sortie_id, renfort_id=None):
    try:
        sortie = Sortie.objects.get(pk=sortie_id)
    except Sortie.DoesNotExist:
        return JsonResponse({"error": "Sortie introuvable."}, status=404)

    if request.method == "DELETE":
        try:
            renfort = SortieRenfort.objects.select_related("affectation").get(
                pk=renfort_id, sortie=sortie
            )
        except SortieRenfort.DoesNotExist:
            return JsonResponse({"error": "Renfort introuvable."}, status=404)
        with transaction.atomic():
            affectation = renfort.affectation
            renfort.delete()
            if request.GET.get("planning") == "1":
                supprimer_jour_affectation(affectation, sortie.date)
        return JsonResponse({"ok": True})

    try:
        data = _payload(request)
        animateur_id = int(data["animateur_id"])
        evenement_id = int(data["evenement_id"])
        evenement = Evenement.objects.select_related("centre").get(
            pk=evenement_id, participations_sorties__sortie=sortie
        )
        ids_disponibles = {
            item["id"] for item in animateurs_eligibles_responsabilites(sortie)
            if item["eligibilite"] == "disponible"
        }
        if animateur_id not in ids_disponibles:
            raise ValueError("Cet animateur vient d’être affecté ailleurs et n’est plus disponible.")
        debut = timezone.make_aware(datetime.datetime.combine(sortie.date, datetime.time.min))
        with transaction.atomic():
            affectation = creer_affectation(
                animateur=Animateur.objects.get(pk=animateur_id),
                centre=evenement.centre,
                evenement=evenement,
                debut=debut,
                fin=debut + datetime.timedelta(days=1),
            )
            renfort = SortieRenfort.objects.create(sortie=sortie, affectation=affectation)
    except (KeyError, TypeError, Animateur.DoesNotExist, Evenement.DoesNotExist):
        return JsonResponse({"error": "Animateur ou groupe invalide."}, status=400)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    return JsonResponse({"id": renfort.id}, status=201)


@require_http_methods(["GET"])
def api_communes_recherche(request):
    try:
        code_postal = request.GET.get("code_postal", "").strip()
        nom = request.GET.get("nom", "").strip()
        if code_postal:
            resultats = rechercher_communes_par_code_postal(code_postal)
        elif nom:
            resultats = rechercher_communes_par_nom(nom)
        else:
            raise ValueError("Renseignez un code postal ou un nom de commune.")
        return JsonResponse({"resultats": resultats})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except LocalisationError as exc:
        return JsonResponse({"error": str(exc), "resultats": []}, status=503)


@require_http_methods(["GET"])
def api_sortie_meteo(request, sortie_id):
    try:
        sortie = Sortie.objects.get(pk=sortie_id)
    except Sortie.DoesNotExist:
        return JsonResponse({"error": "Sortie introuvable."}, status=404)
    return JsonResponse(prevision_sortie(sortie, forcer=request.GET.get("forcer") == "1"))


def _payload(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Requête JSON invalide.") from exc


def _queryset_groupes_visibles():
    return groupes_visibles(
        Evenement.objects.select_related("centre", "groupe").prefetch_related(
            "periodes_scolaires", "dates_exclues"
        )
    ).order_by("centre__ordre", "centre__nom", "ordre", "nom")


def _groupe_ouvert_le(groupe, jour):
    dates_exclues = {item.date for item in groupe.dates_exclues.all()}
    return groupe.est_ouvert_le(jour, dates_exclues)


def _catalogue_groupes(jour=None):
    groupes = list(_queryset_groupes_visibles())
    return [
        {
            "id": item.id,
            "nom": item.nom,
            "centre_id": item.centre_id,
            "centre": item.centre.nom,
            "ouvert": _groupe_ouvert_le(item, jour) if jour else True,
        }
        for item in groupes
    ]


def _catalogue_animateurs(sortie):
    return animateurs_eligibles_responsabilites(sortie)


def _periodes_sortie(sortie):
    return PeriodeScolaire.objects.filter(
        debut__lte=sortie.date, fin__gte=sortie.date
    ).order_by("debut", "ordre", "id")


def _catalogue_documents_sortie(sortie):
    documents = Document.objects.filter(
        Q(periodes__debut__lte=sortie.date, periodes__fin__gte=sortie.date)
        | Q(periode_debut__lte=sortie.date, periode_fin__gte=sortie.date)
    ).distinct().order_by("titre", "id")
    return [
        {"id": item.id, "titre": item.titre, "url": item.fichier.url}
        for item in documents
    ]


def _ids_groupes(data):
    valeurs = data.get("groupes", [])
    if valeurs in (None, ""):
        return []
    if not isinstance(valeurs, list):
        raise ValueError("La liste des groupes est invalide.")
    try:
        return list(dict.fromkeys(int(value) for value in valeurs))
    except (TypeError, ValueError) as exc:
        raise ValueError("La liste des groupes est invalide.") from exc


def _groupes_selectionnes(ids_groupes):
    groupes = list(_queryset_groupes_visibles().filter(pk__in=ids_groupes))
    if len(groupes) != len(ids_groupes):
        raise ValueError("Un groupe sélectionné est invalide.")
    return groupes


def _queryset_sorties():
    return Sortie.objects.prefetch_related(
        "participations__evenement__centre",
        "participations__evenement__groupe",
        "liens",
        "documents",
        "responsabilites__animateur",
        "responsabilites__animateur__qualifications",
        "responsabilites__centre",
        "responsabilites__evenement__centre",
        "responsabilites__affectation_creee",
        "etapes_transport__centre",
    )


def _donnees_sortie_utilisateur(sortie, utilisateur):
    # Rend également les anciennes sorties immédiatement exploitables ; la
    # synchronisation est idempotente et n'écrit que si les lieux ont changé.
    synchroniser_circuits_transport(sortie)
    resultat = donnees_sortie(sortie)
    preference = PreferenceTransportUtilisateur.objects.filter(utilisateur=utilisateur).first()
    resultat["transport"]["mode_transport_suggere"] = (
        preference.mode_transport if preference else ""
    )
    resultat["transport"]["estimation_disponible"] = routing_is_configured()
    return resultat


@require_http_methods(["POST"])
def api_sortie_estimation_trajet(request, sortie_id):
    try:
        sortie = _queryset_sorties().get(pk=sortie_id)
        data = _payload(request)
        return JsonResponse(estimate_sortie_route(sortie, str(data.get("sens", ""))))
    except Sortie.DoesNotExist:
        return JsonResponse({"error": "Sortie introuvable."}, status=404)
    except RoutingError as exc:
        return JsonResponse(
            {"success": False, "code": exc.code, "message": str(exc), "error": str(exc)},
            status=exc.http_status,
        )
    except ValueError as exc:
        return JsonResponse(
            {"success": False, "code": "INVALID_ROUTE", "message": str(exc), "error": str(exc)},
            status=400,
        )


def _nettoyer_responsabilites_hors_perimetre(sortie):
    ids_groupes = set(sortie.participations.values_list("evenement_id", flat=True))
    ids_centres = set(
        sortie.participations.values_list("evenement__centre_id", flat=True).distinct()
    )
    sortie.responsabilites.filter(
        type=SortieResponsabilite.TYPE_GROUPE
    ).exclude(evenement_id__in=ids_groupes).delete()
    sortie.responsabilites.filter(
        type=SortieResponsabilite.TYPE_LIEU
    ).exclude(centre_id__in=ids_centres).delete()


def _remplacer_responsabilites(sortie, valeurs, affectations_responsables=None):
    if not isinstance(valeurs, list):
        raise ValueError("La liste des responsabilités est invalide.")

    affectations_creees = {
        animateur_id: affectation_id
        for animateur_id, affectation_id in sortie.responsabilites.exclude(
            affectation_creee_id=None
        ).values_list("animateur_id", "affectation_creee_id")
    }
    ids_groupes = set(sortie.participations.values_list("evenement_id", flat=True))
    ids_centres = set(
        sortie.participations.values_list("evenement__centre_id", flat=True).distinct()
    )
    groupes_valides = {
        item.id: item
        for item in Evenement.objects.filter(pk__in=ids_groupes).select_related("centre")
    }
    centres_valides = {
        item.id: item
        for item in Centre.objects.filter(pk__in=ids_centres)
    }

    ids_animateurs = set()
    normalisees = []
    for ordre, item in enumerate(valeurs):
        if not isinstance(item, dict):
            raise ValueError("Une responsabilité est invalide.")
        try:
            animateur_id = int(item.get("animateur_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Choisissez un responsable.") from exc
        ids_animateurs.add(animateur_id)
        type_responsabilite = str(item.get("type", "")).strip()
        cibles = item.get("cibles", [])
        if cibles in (None, ""):
            cibles = []
        if not isinstance(cibles, list):
            raise ValueError("Le périmètre d’une responsabilité est invalide.")
        try:
            cibles = list(dict.fromkeys(int(value) for value in cibles))
        except (TypeError, ValueError) as exc:
            raise ValueError("Le périmètre d’une responsabilité est invalide.") from exc

        if type_responsabilite == SortieResponsabilite.TYPE_DIRECTION:
            normalisees.append((ordre, animateur_id, type_responsabilite, None, None))
        elif type_responsabilite == SortieResponsabilite.TYPE_LIEU:
            if not cibles:
                raise ValueError("Choisissez au moins un lieu pour ce responsable.")
            if not set(cibles) <= set(centres_valides):
                raise ValueError("Un lieu sélectionné ne participe pas à cette sortie.")
            normalisees.extend(
                (ordre, animateur_id, type_responsabilite, centre_id, None)
                for centre_id in cibles
            )
        elif type_responsabilite == SortieResponsabilite.TYPE_GROUPE:
            if not cibles:
                raise ValueError("Choisissez au moins un groupe pour ce responsable.")
            if not set(cibles) <= set(groupes_valides):
                raise ValueError("Un groupe sélectionné ne participe pas à cette sortie.")
            normalisees.extend(
                (ordre, animateur_id, type_responsabilite, None, evenement_id)
                for evenement_id in cibles
            )
        else:
            raise ValueError("Le type de responsabilité est invalide.")

    animateurs = {item.id for item in Animateur.objects.filter(pk__in=ids_animateurs)}
    if animateurs != ids_animateurs:
        raise ValueError("Un responsable sélectionné est invalide.")

    ids_eligibles = {item["id"] for item in animateurs_eligibles_responsabilites(sortie)}
    if not ids_animateurs <= ids_eligibles:
        raise ValueError(
            "Un responsable doit être affecté à un groupe ou lieu concerné par la sortie, "
            "ou être disponible et non affecté ce jour-là."
        )

    affectations_responsables = affectations_responsables or {}
    if not isinstance(affectations_responsables, dict):
        raise ValueError("Les affectations des responsables sont invalides.")

    # Le groupe est choisi explicitement dans le second écran de la fiche.
    # Le service habituel conserve ensuite tous les contrôles du Planning.
    debut = timezone.make_aware(datetime.datetime.combine(sortie.date, datetime.time.min))
    fin = debut + datetime.timedelta(days=1)
    for animateur_id in ids_animateurs:
        if Affectation.objects.filter(animateur_id=animateur_id, debut__lt=fin, fin__gt=debut).exists():
            continue
        try:
            evenement_id = int(affectations_responsables.get(str(animateur_id)))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Choisissez un lieu et un groupe d’affectation pour chaque responsable non affecté."
            ) from exc
        evenement = groupes_valides.get(evenement_id)
        if evenement is None:
            raise ValueError("Le groupe d’affectation choisi ne participe pas à cette sortie.")
        affectation = creer_affectation(
            animateur=Animateur.objects.get(pk=animateur_id),
            centre=evenement.centre,
            evenement=evenement,
            debut=debut,
            fin=fin,
        )
        affectations_creees[animateur_id] = affectation.id

    # Évite les doublons lorsque plusieurs lignes identiques sont envoyées.
    uniques = []
    deja_vus = set()
    for valeur in normalisees:
        cle = valeur[1:]
        if cle in deja_vus:
            continue
        deja_vus.add(cle)
        uniques.append(valeur)

    sortie.responsabilites.all().delete()
    SortieResponsabilite.objects.bulk_create(
        [
            SortieResponsabilite(
                sortie=sortie,
                animateur_id=animateur_id,
                type=type_responsabilite,
                centre_id=centre_id,
                evenement_id=evenement_id,
                affectation_creee_id=affectations_creees.get(animateur_id),
                ordre=ordre,
            )
            for ordre, animateur_id, type_responsabilite, centre_id, evenement_id in uniques
        ]
    )


def _supprimer_affectations_responsables(sortie, valeurs, anciennes_affectations_creees):
    if valeurs in (None, ""):
        return
    if not isinstance(valeurs, list):
        raise ValueError("La suppression des affectations est invalide.")
    try:
        ids_animateurs = {int(value) for value in valeurs}
    except (TypeError, ValueError) as exc:
        raise ValueError("La suppression des affectations est invalide.") from exc
    if not ids_animateurs <= set(anciennes_affectations_creees):
        raise ValueError("Cette affectation n’a pas été créée lors de la nomination du responsable.")

    ids_centres = set(
        sortie.participations.values_list("evenement__centre_id", flat=True).distinct()
    )
    debut = timezone.make_aware(datetime.datetime.combine(sortie.date, datetime.time.min))
    fin = debut + datetime.timedelta(days=1)
    affectations = list(Affectation.objects.filter(
        pk__in=[anciennes_affectations_creees[item] for item in ids_animateurs],
        centre_id__in=ids_centres,
        debut__lt=fin,
        fin__gt=debut,
    ))
    for affectation in affectations:
        ancien_debut, ancienne_fin = affectation.debut, affectation.fin
        if ancien_debut >= debut and ancienne_fin <= fin:
            affectation.delete()
            continue
        affectation.horaires_journaliers.filter(date=sortie.date).delete()
        if ancien_debut < debut and ancienne_fin > fin:
            # La journée retirée coupe une plage longue en deux segments.
            affectation.fin = debut
            affectation.save(update_fields=["fin"])
            segment = Affectation.objects.create(
                animateur=affectation.animateur,
                centre=affectation.centre,
                evenement=affectation.evenement,
                debut=fin,
                fin=ancienne_fin,
            )
            affectation.horaires_journaliers.filter(date__gt=sortie.date).update(
                affectation=segment
            )
        elif ancien_debut < debut:
            affectation.fin = debut
            affectation.save(update_fields=["fin"])
        else:
            affectation.debut = fin
            affectation.save(update_fields=["debut"])


@require_http_methods(["POST"])
def api_sorties_apercu(request):
    """Aperçu sans création en base, calculé directement depuis le Planning."""
    try:
        data = _payload(request)
        jour = parse_date(str(data.get("date", "")))
        if not jour:
            raise ValueError("Choisissez une date pour afficher l’aperçu.")

        ids_groupes = _ids_groupes(data)
        groupes = _groupes_selectionnes(ids_groupes)
        groupes_ouverts = [item for item in groupes if _groupe_ouvert_le(item, jour)]
        groupes_fermes = [item for item in groupes if item not in groupes_ouverts]
        resultat = calculer_participants_sortie(jour, groupes_ouverts)
        if groupes_fermes:
            nombre = len(groupes_fermes)
            resultat["vigilances"].insert(
                0,
                f"{nombre} groupe{'s' if nombre > 1 else ''} fermé{'s' if nombre > 1 else ''} "
                "ce jour n’a pas été pris en compte",
            )

        return JsonResponse(
            {
                **resultat,
                "catalogue_groupes": _catalogue_groupes(jour),
                "groupes_selectionnes": [item.id for item in groupes_ouverts],
            }
        )
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc) or "Données invalides."}, status=400)



@require_http_methods(["GET"])
def api_sorties_calendrier(request):
    """Repères de sorties pour les calendriers partagés.

    Cette réponse volontairement compacte est accessible à tous les comptes
    connectés. Elle ne contient que le nom, la date et les groupes concernés.
    """
    debut = parse_date(str(request.GET.get("start", ""))[:10])
    fin = parse_date(str(request.GET.get("end", ""))[:10])
    if not debut or not fin or fin <= debut:
        return JsonResponse({"error": "Plage de dates invalide."}, status=400)

    sorties = (
        Sortie.objects.filter(date__gte=debut, date__lt=fin)
        .prefetch_related("participations")
        .order_by("date", "nom", "id")
    )
    return JsonResponse({
        "sorties": [
            {
                "id": sortie.id,
                "date": sortie.date.isoformat(),
                "nom": sortie.nom,
                "groupe_ids": [participation.evenement_id for participation in sortie.participations.all()],
            }
            for sortie in sorties
        ]
    })

@require_http_methods(["GET", "POST"])
def api_sorties(request):
    if request.method == "POST":
        try:
            data = _payload(request)
            nom = str(data.get("nom", "")).strip()
            destination = str(data.get("destination", "")).strip()
            destination_adresse = str(data.get("destination_adresse", "")).strip()
            destination_code_postal = str(data.get("destination_code_postal", "")).strip()
            destination_commune = str(data.get("destination_commune", "")).strip()
            if destination_code_postal:
                code_postal_francais(destination_code_postal)
            date = parse_date(str(data.get("date", "")))
            if not nom or not destination or not date:
                raise ValueError("Le nom, la date et la destination sont obligatoires.")

            ids_groupes = _ids_groupes(data)
            groupes = _groupes_selectionnes(ids_groupes)
            groupes_fermes = [item for item in groupes if not _groupe_ouvert_le(item, date)]
            if groupes_fermes:
                noms = ", ".join(f"{item.centre.nom} — {item.nom}" for item in groupes_fermes)
                raise ValueError(f"Groupe fermé à cette date : {noms}.")

            with transaction.atomic():
                sortie = Sortie.objects.create(
                    nom=nom,
                    date=date,
                    destination=destination,
                    destination_adresse=destination_adresse,
                    destination_code_postal=destination_code_postal,
                    destination_commune=destination_commune,
                )
                SortieParticipation.objects.bulk_create(
                    [SortieParticipation(sortie=sortie, evenement=item) for item in groupes]
                )
                synchroniser_circuits_transport(sortie)
            _actualiser_localisation_destination(sortie, data)
            return JsonResponse(_donnees_sortie_utilisateur(sortie, request.user), status=201)
        except ValidationError as exc:
            return JsonResponse({"error": " ".join(exc.messages)}, status=400)
        except (ValueError, TypeError) as exc:
            return JsonResponse({"error": str(exc) or "Données invalides."}, status=400)

    try:
        ids = [int(value) for value in request.GET.get("periode_ids", "").split(",") if value]
    except ValueError:
        return JsonResponse({"error": "Périodes invalides."}, status=400)
    periodes = list(PeriodeScolaire.objects.filter(id__in=ids).order_by("debut"))
    semaines = []
    for periode in periodes:
        items = _queryset_sorties().filter(date__range=(periode.debut, periode.fin))
        semaines.append(
            {
                "id": periode.id,
                "nom": periode.libelle_avec_annee,
                "debut": periode.debut.isoformat(),
                "fin": periode.fin.isoformat(),
                "sorties": [donnees_sortie(item) for item in items],
            }
        )
    return JsonResponse({"semaines": semaines})


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_sortie_detail(request, sortie_id):
    try:
        sortie = _queryset_sorties().get(pk=sortie_id)
    except Sortie.DoesNotExist:
        return JsonResponse({"error": "Sortie introuvable."}, status=404)
    if request.method == "DELETE":
        sortie.delete()
        return JsonResponse({"ok": True})
    if request.method == "GET":
        catalogue_animateurs = _catalogue_animateurs(sortie)
        return JsonResponse(
            {
                **_donnees_sortie_utilisateur(sortie, request.user),
                "catalogue_groupes": _catalogue_groupes(sortie.date),
                "catalogue_animateurs": catalogue_animateurs,
                "catalogue_documents": _catalogue_documents_sortie(sortie),
                # Liste dédiée, déjà filtrée côté serveur. Le navigateur ne
                # reçoit ici aucun salarié affecté, y compris les flottants.
                "animateurs_supplementaires": [
                    item for item in catalogue_animateurs
                    if item["eligibilite"] == "disponible"
                ],
            }
        )
    try:
        data = _payload(request)
        with transaction.atomic():
            destination_avant = (
                sortie.destination,
                sortie.destination_adresse,
                sortie.destination_code_postal,
                sortie.destination_commune,
            )
            for champ in (
                "nom",
                "destination",
                "destination_adresse",
                "destination_code_postal",
                "destination_commune",
                "trajet_ramassage",
                "consignes_transport",
                "objectifs_pedagogiques",
                "consignes_encadrement",
                "organisation_maternels",
                "organisation_elementaires",
                "repas_gouter",
            ):
                if champ in data:
                    setattr(sortie, champ, str(data[champ] or "").strip())
            if sortie.destination_code_postal:
                code_postal_francais(sortie.destination_code_postal)
            destination_apres = (
                sortie.destination,
                sortie.destination_adresse,
                sortie.destination_code_postal,
                sortie.destination_commune,
            )
            if destination_apres != destination_avant:
                sortie.destination_latitude = None
                sortie.destination_longitude = None
                sortie.destination_code_insee = ""
                sortie.destination_precision = Sortie.PRECISION_NON_LOCALISEE
                invalider_estimations_transport(sortie)
            if "mode_transport" in data:
                mode_transport = str(data["mode_transport"] or "").strip()
                modes_valides = {valeur for valeur, _ in Sortie.MODES_TRANSPORT}
                if mode_transport and mode_transport not in modes_valides:
                    raise ValueError("Le mode de transport sélectionné est invalide.")
                sortie.mode_transport = mode_transport
            if "date" in data:
                sortie.date = parse_date(str(data["date"])) or (_ for _ in ()).throw(
                    ValueError("Date invalide.")
                )
            for champ in (
                "heure_depart",
                "heure_arrivee",
                "heure_retour",
                "heure_arrivee_retour",
            ):
                if champ in data:
                    ancienne_valeur = getattr(sortie, champ)
                    valeur = parse_time(str(data[champ])) if data[champ] else None
                    if data[champ] and valeur is None:
                        raise ValueError("Un horaire de transport est invalide.")
                    setattr(sortie, champ, valeur)
                    if champ in {"heure_arrivee", "heure_arrivee_retour"}:
                        source_champ = (
                            "source_heure_arrivee" if champ == "heure_arrivee"
                            else "source_heure_arrivee_retour"
                        )
                        source = getattr(sortie, source_champ)
                        if valeur is None:
                            setattr(sortie, source_champ, "")
                        elif source != Sortie.SOURCE_HORAIRE_AUTOMATIQUE or valeur != ancienne_valeur:
                            setattr(sortie, source_champ, Sortie.SOURCE_HORAIRE_MANUELLE)
            if "temps_arret_par_site" in data:
                temps_arret = int(data["temps_arret_par_site"])
                if not 0 <= temps_arret <= 60:
                    raise ValueError("Le temps d’arrêt doit être compris entre 0 et 60 minutes.")
                if temps_arret != sortie.temps_arret_par_site:
                    invalider_estimations_transport(sortie)
                    sortie.temps_arret_par_site = temps_arret
            if "nombre_vehicules" in data:
                if data["nombre_vehicules"] in (None, ""):
                    sortie.nombre_vehicules = None
                else:
                    nombre_vehicules = int(data["nombre_vehicules"])
                    if not 1 <= nombre_vehicules <= 32767:
                        raise ValueError("Le nombre de véhicules doit être compris entre 1 et 32767.")
                    sortie.nombre_vehicules = nombre_vehicules
            if not sortie.nom or not sortie.destination:
                raise ValueError("Le nom et la destination sont obligatoires.")
            sortie.save()
            _actualiser_localisation_destination(sortie, data)
            if "mode_transport" in data and sortie.mode_transport:
                PreferenceTransportUtilisateur.objects.update_or_create(
                    utilisateur=request.user,
                    defaults={"mode_transport": sortie.mode_transport},
                )

            if "groupes" in data:
                ids_groupes = [int(value) for value in data["groupes"]]
                groupes = list(groupes_visibles(Evenement.objects.filter(pk__in=ids_groupes)))
                if len(groupes) != len(set(ids_groupes)):
                    raise ValueError("Un groupe sélectionné est invalide.")
                existantes = {item.evenement_id: item for item in sortie.participations.all()}
                sortie.participations.exclude(evenement_id__in=ids_groupes).delete()
                SortieParticipation.objects.bulk_create(
                    [
                        SortieParticipation(sortie=sortie, evenement=item)
                        for item in groupes
                        if item.id not in existantes
                    ]
                )
                _nettoyer_responsabilites_hors_perimetre(sortie)
                synchroniser_circuits_transport(sortie)

            if "circuit_aller" in data or "circuit_retour" in data:
                if "circuit_aller" not in data or "circuit_retour" not in data:
                    raise ValueError("Les circuits aller et retour doivent être enregistrés ensemble.")
                remplacer_circuits_transport(
                    sortie,
                    data["circuit_aller"],
                    data["circuit_retour"],
                )

            if "responsabilites" in data:
                anciennes_affectations_creees = {
                    animateur_id: affectation_id
                    for animateur_id, affectation_id in sortie.responsabilites.exclude(
                        affectation_creee_id=None
                    ).values_list("animateur_id", "affectation_creee_id")
                }
                _remplacer_responsabilites(
                    sortie,
                    data["responsabilites"],
                    data.get("affectations_responsables"),
                )
                _supprimer_affectations_responsables(
                    sortie,
                    data.get("supprimer_affectations_responsables"),
                    anciennes_affectations_creees,
                )

            if "activites" in data:
                for identifiant, valeur in data["activites"].items():
                    sortie.participations.filter(evenement_id=int(identifiant)).update(
                        activite_horaire=str(valeur).strip()
                    )
            if "liens" in data:
                liens = []
                validateur_url = URLValidator()
                for index, item in enumerate(data["liens"]):
                    libelle = str(item.get("libelle", "")).strip()
                    url = str(item.get("url", "")).strip()
                    if not libelle and not url:
                        continue
                    if not libelle or not url:
                        raise ValueError("Chaque lien doit avoir un libellé et une adresse.")
                    try:
                        validateur_url(url)
                    except ValidationError as exc:
                        raise ValueError(f"L’adresse du lien « {libelle} » est invalide.") from exc
                    liens.append(SortieLien(sortie=sortie, libelle=libelle, url=url, ordre=index))
                sortie.liens.all().delete()
                SortieLien.objects.bulk_create(liens)
            if "document_ids" in data:
                try:
                    document_ids = list(dict.fromkeys(int(value) for value in data["document_ids"]))
                except (TypeError, ValueError) as exc:
                    raise ValueError("La sélection de documents est invalide.") from exc
                documents_valides = Document.objects.filter(
                    Q(periodes__debut__lte=sortie.date, periodes__fin__gte=sortie.date)
                    | Q(periode_debut__lte=sortie.date, periode_fin__gte=sortie.date),
                    pk__in=document_ids,
                ).distinct()
                if documents_valides.count() != len(document_ids):
                    raise ValueError("Un document sélectionné n’appartient pas à la semaine de la sortie.")
                sortie.documents.set(documents_valides)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc) or "Données invalides."}, status=400)

    sortie = _queryset_sorties().get(pk=sortie.id)
    return JsonResponse(
        {
            **_donnees_sortie_utilisateur(sortie, request.user),
            "catalogue_groupes": _catalogue_groupes(sortie.date),
            "catalogue_animateurs": _catalogue_animateurs(sortie),
            "catalogue_documents": _catalogue_documents_sortie(sortie),
        }
    )


@require_http_methods(["POST"])
def api_sortie_document_upload(request, sortie_id):
    try:
        sortie = Sortie.objects.get(pk=sortie_id)
    except Sortie.DoesNotExist:
        return JsonResponse({"error": "Sortie introuvable."}, status=404)

    fichier = request.FILES.get("fichier")
    titre = request.POST.get("titre", "").strip()
    if not fichier:
        return JsonResponse({"error": "Choisissez un fichier."}, status=400)
    if not titre:
        titre = str(fichier.name).rsplit(".", 1)[0].strip() or "Document de la sortie"

    periodes = list(_periodes_sortie(sortie))
    if not periodes:
        return JsonResponse(
            {"error": "Aucune semaine ne correspond à la date de cette sortie."},
            status=400,
        )

    fichier.name = normaliser_nom_document(fichier.name)
    try:
        with transaction.atomic():
            document = Document.objects.create(
                titre=titre,
                fichier=fichier,
                permanent=False,
                periode_debut=min(item.debut for item in periodes),
                periode_fin=max(item.fin for item in periodes),
                publie=True,
            )
            document.periodes.set(periodes)
            sortie.documents.add(document)
    except Exception:
        return JsonResponse(
            {"error": "Le fichier n’a pas pu être enregistré. Réessaie plus tard."},
            status=503,
        )
    return JsonResponse(
        {"id": document.id, "titre": document.titre, "url": document.fichier.url},
        status=201,
    )
