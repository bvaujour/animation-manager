import datetime
import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
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
    SortieLien,
    SortieParticipation,
    SortieResponsabilite,
)
from animateurs.services.affectations import creer_affectation
from animateurs.services.flottants import groupes_visibles
from animateurs.services.meteo_sorties import geocoder_lieux, prevision_sortie
from animateurs.services.sorties import (
    animateurs_eligibles_responsabilites,
    calculer_participants_sortie,
    donnees_sortie,
)


def sorties(request):
    return render(request, "sorties.html", {"active_page": "sorties"})


def sortie_detail(request, sortie_id):
    return render(request, "sortie_detail.html", {"active_page": "sorties", "sortie_id": sortie_id})


@require_http_methods(["GET"])
def api_sorties_geocodage(request):
    try:
        return JsonResponse({"resultats": geocoder_lieux(request.GET.get("q", ""), 5)})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except RuntimeError as exc:
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


@require_http_methods(["GET", "POST"])
def api_sorties(request):
    if request.method == "POST":
        try:
            data = _payload(request)
            nom = str(data.get("nom", "")).strip()
            destination = str(data.get("destination", "")).strip()
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
                sortie = Sortie.objects.create(nom=nom, date=date, destination=destination)
                SortieParticipation.objects.bulk_create(
                    [SortieParticipation(sortie=sortie, evenement=item) for item in groupes]
                )
            return JsonResponse(donnees_sortie(sortie), status=201)
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
        return JsonResponse(
            {
                **donnees_sortie(sortie),
                "catalogue_groupes": _catalogue_groupes(sortie.date),
                "catalogue_animateurs": _catalogue_animateurs(sortie),
            }
        )
    try:
        data = _payload(request)
        with transaction.atomic():
            for champ in (
                "nom",
                "destination",
                "mode_transport",
                "trajet_ramassage",
                "consignes_transport",
                "objectifs_pedagogiques",
                "consignes_encadrement",
                "organisation_maternels",
                "organisation_elementaires",
                "repas_gouter",
                "meteo_lieu_libelle",
                "meteo_adresse",
                "meteo_code_departement",
            ):
                if champ in data:
                    setattr(sortie, champ, str(data[champ] or "").strip())
            if "meteo_latitude" in data or "meteo_longitude" in data:
                try:
                    latitude = Decimal(str(data.get("meteo_latitude", "")))
                    longitude = Decimal(str(data.get("meteo_longitude", "")))
                except (InvalidOperation, TypeError) as exc:
                    raise ValueError("Coordonnées météo invalides.") from exc
                if not (Decimal("-90") <= latitude <= Decimal("90") and Decimal("-180") <= longitude <= Decimal("180")):
                    raise ValueError("Coordonnées météo invalides.")
                sortie.meteo_latitude, sortie.meteo_longitude = latitude, longitude
            if "date" in data:
                sortie.date = parse_date(str(data["date"])) or (_ for _ in ()).throw(
                    ValueError("Date invalide.")
                )
            for champ in ("heure_depart", "heure_arrivee", "heure_depart_site", "heure_retour"):
                if champ in data:
                    setattr(sortie, champ, parse_time(str(data[champ])) if data[champ] else None)
            if "nombre_vehicules" in data:
                sortie.nombre_vehicules = (
                    int(data["nombre_vehicules"])
                    if data["nombre_vehicules"] not in (None, "")
                    else None
                )
            if not sortie.nom or not sortie.destination:
                raise ValueError("Le nom et la destination sont obligatoires.")
            sortie.save()

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
                sortie.documents.set(Document.objects.filter(pk__in=data["document_ids"]))
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc) or "Données invalides."}, status=400)

    sortie = _queryset_sorties().get(pk=sortie.id)
    return JsonResponse(
        {
            **donnees_sortie(sortie),
            "catalogue_groupes": _catalogue_groupes(sortie.date),
            "catalogue_animateurs": _catalogue_animateurs(sortie),
        }
    )
