"""API de gestion des centres, groupes, qualifications et périodes."""

import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from .access import est_direction
from .models import (
    QUALIFICATION_ICON_CHOICES,
    Animateur,
    Centre,
    Evenement,
    Groupe,
    PeriodeScolaire,
    PeriodeCalendrier,
    ModalitePeriscolaire,
    Qualification,
    Sortie,
    Sejour,
    ParticipantSejour,
    TypeAccueil,
    code_postal_francais,
    normaliser_cle_unique,
)
from .services.calendrier_scolaire import (
    CalendrierScolaireError,
    calculer_periodes_scolaires,
    recuperer_semaines,
    regrouper_semaines_vacances,
)
from .services.centres import prochain_ordre_centre, reordonner_centres
from .services.dates import parse_to_aware_datetime
from .services.evenements import (
    FermetureAvecAffectationsError,
    creer_evenement,
    modifier_evenement,
    reordonner_evenements,
    supprimer_evenement,
)
from .services.flottants import est_groupe_flottants, groupes_partages_visibles, groupes_visibles
from .services.localisation import LocalisationError, resoudre_localisation
from .services.serializers import centre_to_dict, evenement_to_dict, qualification_to_dict
from .services.types_accueil import filtrer_semaines_contexte_travail


def _localiser_centre(centre, payload):
    """Géocode un lieu depuis la source officielle sans bloquer sa sauvegarde."""

    if not payload.get("localisation_demandee"):
        return ""
    if not centre.code_postal:
        return "Code postal manquant : le lieu est enregistré sans localisation."
    try:
        localisation = resoudre_localisation(
            centre.nom, centre.adresse, centre.code_postal, centre.commune,
            payload.get("code_insee", ""),
        )
        centre.code_insee = localisation["code_insee"]
        centre.latitude = localisation["latitude"]
        centre.longitude = localisation["longitude"]
        centre.precision_localisation = localisation["precision"]
        centre.save(update_fields=["code_insee", "latitude", "longitude", "precision_localisation"])
        if centre.latitude is None or centre.longitude is None:
            return "La localisation n’a pas pu être confirmée. Vérifiez la commune sélectionnée."
        return ""
    except LocalisationError:
        return "Service de localisation indisponible. Le lieu a été enregistré sans coordonnées."
    except ValueError as exc:
        return str(exc)

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


def _evenement_personnel_to_dict(evenement):
    """Libellé lisible du groupe technique dans le planning salarié."""
    data = evenement_to_dict(evenement, include_effectifs=False)
    data["est_flottant"] = est_groupe_flottants(evenement)
    if data["est_flottant"]:
        data["nom"] = "Animateur flottant"
    return data


@require_http_methods(["GET", "POST"])
def api_centres(request):
    """GET : liste des centres. POST : création d'un centre."""

    if request.method == "GET":
        inclure_groupes = request.GET.get("include_groupes") == "1"
        animateur = None if est_direction(request.user) else getattr(request.user, "profil_animateur", None)
        centres = Centre.objects.all()
        if animateur is not None:
            affectations_personnelles = animateur.affectations.all()
            start = request.GET.get("start")
            end = request.GET.get("end")
            if start and end:
                try:
                    debut = parse_to_aware_datetime(start)
                    fin = parse_to_aware_datetime(end)
                except ValueError:
                    return JsonResponse({"error": "Paramètres start/end invalides."}, status=400)
                affectations_personnelles = affectations_personnelles.filter(debut__lt=fin, fin__gt=debut)
            centre_ids = affectations_personnelles.values_list("centre_id", flat=True).distinct()
            centres = centres.filter(id__in=centre_ids)
        elif not est_direction(request.user):
            centres = centres.none()
        if not inclure_groupes:
            return JsonResponse([centre_to_dict(c) for c in centres], safe=False)

        groupes_source = groupes_visibles(Evenement.objects.all()) if animateur is None else Evenement.objects.all()
        groupes = (
            groupes_source.prefetch_related(
                "periodes_scolaires",
                "dates_exclues",
                "besoins_qualifications__qualification",
            )
            .annotate(nb_affectations=Count("affectations", distinct=True))
            .order_by("ordre", "nom")
        )
        if animateur is not None:
            groupes = groupes.filter(centre_id__in=centre_ids).distinct()
        elif not est_direction(request.user):
            groupes = groupes.none()
        centres = Centre.objects.prefetch_related(
            Prefetch("evenements", queryset=groupes, to_attr="_groupes_planning")
        )
        if animateur is not None:
            centres = centres.filter(id__in=centre_ids)
        elif not est_direction(request.user):
            centres = centres.none()
        data = []
        for centre in centres:
            item = centre_to_dict(centre)
            if animateur is None:
                # La direction ne reçoit jamais le groupe technique flottant :
                # conserver ce chemin direct évite une requête par groupe.
                item["evenements"] = [
                    evenement_to_dict(groupe, include_effectifs=False)
                    for groupe in centre._groupes_planning
                ]
            else:
                item["evenements"] = [
                    _evenement_personnel_to_dict(groupe)
                    for groupe in centre._groupes_planning
                    if not est_groupe_flottants(groupe) or groupe.nb_affectations > 0
                ]
            data.append(item)
        return JsonResponse(data, safe=False)

    try:
        payload = json.loads(request.body)

        nom = payload["nom"].strip()
        code = payload["code"].strip()
        couleur = payload.get("couleur", "#e03c00").strip() or "#e03c00"
        adresse = str(payload.get("adresse", "")).strip()
        code_postal = str(payload.get("code_postal", "")).strip()
        commune = str(payload.get("commune", "")).strip()
        if code_postal:
            code_postal_francais(code_postal)
        effectif_cible = int(payload.get("effectif_cible", 1) or 1)

        if not nom or not code:
            return JsonResponse({"error": "Le nom et le code sont obligatoires."}, status=400)

        if Centre.objects.filter(cle_unique=normaliser_cle_unique(nom)).exists():
            return JsonResponse({"error": f"Le lieu « {nom} » existe déjà."}, status=409)

        if effectif_cible < 1:
            return JsonResponse({"error": "L'effectif souhaité doit être d'au moins 1."}, status=400)

    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    try:
        centre = Centre.objects.create(
            nom=nom,
            code=code,
            couleur=couleur,
            adresse=adresse,
            code_postal=code_postal,
            commune=commune,
            effectif_cible=effectif_cible,
            ordre=prochain_ordre_centre(),
        )
    except IntegrityError:
        # Le champ `code` est unique en base (contrainte du modèle) :
        # on transforme l'erreur SQL brute en message compréhensible.
        return JsonResponse({"error": f"Le code « {code} » est déjà utilisé par un autre centre."}, status=409)

    avertissement = _localiser_centre(centre, payload)
    resultat = centre_to_dict(centre)
    resultat["localisation_warning"] = avertissement
    return JsonResponse(resultat, status=201)


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

        geographie_modifiee = False
        code_insee_demande = str(payload.get("code_insee", "") or "").strip().upper()
        for champ in ("adresse", "code_postal", "commune"):
            if champ in payload:
                valeur = str(payload[champ] or "").strip()
                if champ == "code_postal" and valeur:
                    code_postal_francais(valeur)
                geographie_modifiee = geographie_modifiee or getattr(centre, champ) != valeur
                setattr(centre, champ, valeur)
        if geographie_modifiee:
            centre.latitude = None
            centre.longitude = None
            centre.code_insee = ""
            centre.precision_localisation = "non_localisee"
        doit_localiser = bool(payload.get("localisation_demandee")) and (
            geographie_modifiee
            or centre.latitude is None
            or centre.longitude is None
            or (code_insee_demande and code_insee_demande != centre.code_insee)
        )

        if "effectif_cible" in payload:
            effectif_cible = int(payload["effectif_cible"])
            if effectif_cible < 1:
                return JsonResponse({"error": "L'effectif souhaité doit être d'au moins 1."}, status=400)
            centre.effectif_cible = effectif_cible

    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)

    if Centre.objects.exclude(pk=centre.pk).filter(cle_unique=normaliser_cle_unique(centre.nom)).exists():
        return JsonResponse({"error": f"Le lieu « {centre.nom} » existe déjà."}, status=409)
    try:
        centre.save()
    except IntegrityError:
        return JsonResponse({"error": "Un lieu avec ce nom ou ce code existe déjà."}, status=409)

    avertissement = _localiser_centre(centre, payload) if doit_localiser else ""
    if geographie_modifiee or doit_localiser:
        # Une estimation automatique fondée sur les anciennes coordonnées ne
        # doit pas survivre à la correction de l'adresse d'un site.
        from .services.sorties import invalider_estimations_transport

        sorties = Sortie.objects.filter(participations__evenement__centre=centre).distinct()
        for sortie in sorties:
            invalider_estimations_transport(sortie)

    resultat = centre_to_dict(centre)
    resultat["localisation_warning"] = avertissement
    return JsonResponse(resultat)


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
    groupes = groupes_partages_visibles(Groupe.objects.all()).prefetch_related("instances__centre")
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
        groupe = groupes_partages_visibles(Groupe.objects.all()).get(pk=groupe_id)
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
            groupes_visibles(centre.evenements.all()).prefetch_related(
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
            groupe_partage = groupes_partages_visibles(Groupe.objects.all()).get(pk=int(groupe_id))
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
    evenement.nb_evenements_centre = groupes_visibles(centre.evenements.all()).count()
    return JsonResponse(evenement_to_dict(evenement), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_groupe_detail(request, evenement_id):
    """Modifie ou supprime un groupe sans détruire ses affectations."""

    try:
        evenement = Evenement.objects.select_related("centre", "groupe").get(pk=evenement_id)
        if est_groupe_flottants(evenement):
            raise Evenement.DoesNotExist
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
    evenement.nb_evenements_centre = groupes_visibles(evenement.centre.evenements.all()).count()
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
        if (
            statut_id
            and not Qualification.objects.filter(pk=statut_id, est_statut=True)
            .exclude(pk=qualification.pk)
            .exists()
        ):
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
            qualification.save(
                update_fields=[
                    "nom",
                    "selectionnable_remplissage_auto",
                    "est_statut",
                    "statut",
                    "icone",
                    "cle_unique",
                ]
            )
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
        "type_accueil": periode.type_accueil.code if periode.type_accueil_id else None,
        "type_accueil_nom": periode.type_accueil.nom if periode.type_accueil_id else None,
        "types_accueil": list(periode.types_accueil.values_list("code", flat=True)),
        "periode_calendrier_id": periode.periode_calendrier_id,
    }


def _payload_json(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValidationError("Requête invalide.") from exc


def _type_accueil_requis(payload):
    code = str(payload.get("type_accueil", "")).strip()
    try:
        return TypeAccueil.objects.get(
            code=code,
            actif=True,
            code__in=("vacances", "mercredis", "periscolaire", "sejours"),
        )
    except TypeAccueil.DoesNotExist as exc:
        raise ValidationError("Le type d'accueil est obligatoire.") from exc


def _contexte_periscolaire_requis(payload):
    code = str(payload.get("type_accueil", "periscolaire")).strip()
    code_modalite = str(payload.get("modalite_periscolaire", "")).strip()
    if code == TypeAccueil.MERCREDIS:
        code = TypeAccueil.PERISCOLAIRE
        code_modalite = code_modalite or ModalitePeriscolaire.MERCREDI_JOURNEE
    if code != TypeAccueil.PERISCOLAIRE:
        raise ValidationError("Le calendrier scolaire est rattaché au Périscolaire.")
    try:
        return (
            TypeAccueil.objects.get(code=TypeAccueil.PERISCOLAIRE, actif=True),
            ModalitePeriscolaire.objects.get(code=code_modalite, actif=True),
        )
    except (TypeAccueil.DoesNotExist, ModalitePeriscolaire.DoesNotExist) as exc:
        raise ValidationError("Choisis une modalité périscolaire valide.") from exc


def _appliquer_payload_periode(periode, payload):
    periode.nom = str(payload.get("nom", "")).strip()
    periode.annee_scolaire = str(payload.get("annee_scolaire", "")).strip()
    periode.zone = str(payload.get("zone", "")).strip().upper()
    periode.debut = payload.get("debut")
    periode.fin = payload.get("fin")
    periode.type_accueil = _type_accueil_requis(payload)
    periode.full_clean()
    periode.save()
    periode.types_accueil.add(periode.type_accueil)
    return periode


def _payload_import_periodes(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise CalendrierScolaireError("Requête invalide.") from exc
    return (
        str(payload.get("annee_scolaire", "")).strip(),
        str(payload.get("zone", "")).strip().upper(),
        payload,
    )


@require_http_methods(["GET", "POST"])
def api_periodes_scolaires(request):
    """Liste les semaines importées, sans effet sur les autres modules."""
    if request.method == "POST":
        try:
            payload = _payload_json(request)
            with transaction.atomic():
                periode = _appliquer_payload_periode(PeriodeScolaire(), payload)
                if periode.type_accueil.code == TypeAccueil.VACANCES:
                    reference, _ = PeriodeCalendrier.objects.get_or_create(
                        categorie=PeriodeCalendrier.VACANCES,
                        annee_scolaire=periode.annee_scolaire,
                        zone=periode.zone,
                        debut=periode.debut,
                        fin=periode.fin,
                        defaults={"nom": periode.categorie_vacances},
                    )
                    reference.types_accueil.add(periode.type_accueil)
                    periode.periode_calendrier = reference
                    periode.save(update_fields=("periode_calendrier",))
                for groupe in groupes_visibles(Evenement.objects.filter(permanent=True)).only("id"):
                    groupe.periodes_scolaires.add(periode)
        except ValidationError as exc:
            return JsonResponse({"error": _message_validation(exc)}, status=400)
        except IntegrityError:
            return JsonResponse({"error": "Cette période existe déjà pour cette zone."}, status=409)
        return JsonResponse(_periode_scolaire_to_dict(periode), status=201)

    periodes = PeriodeScolaire.objects.select_related("type_accueil").all()
    if request.GET.get("contexte_travail") == "1":
        periodes = filtrer_semaines_contexte_travail(periodes, request)
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
        annee_scolaire, zone, _payload = _payload_import_periodes(request)
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

    groupes = regrouper_semaines_vacances(semaines)
    for groupe in groupes:
        for semaine in groupe["semaines"]:
            semaine["deja_enregistree"] = (
                PeriodeScolaire.objects.filter(
                    annee_scolaire=annee_scolaire,
                    zone=zone,
                    debut=semaine["debut"],
                    fin=semaine["fin"],
                ).exists()
            )

    return JsonResponse(
        {
            "annee_scolaire": annee_scolaire,
            "zone": zone,
            "periodes": resultat,
            "nombre": len(resultat),
            "groupes": groupes,
        }
    )


@require_POST
def api_periodes_scolaires_importer(request):
    """Enregistre toutes les semaines officielles de façon idempotente."""
    try:
        annee_scolaire, zone, payload = _payload_import_periodes(request)
        type_accueil = _type_accueil_requis(payload)
        if type_accueil.code != TypeAccueil.VACANCES:
            raise ValidationError("L'import officiel des vacances utilise toujours le type Vacances.")
        semaines = recuperer_semaines(annee_scolaire, zone)
    except CalendrierScolaireError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)

    ids_selectionnes = {str(item) for item in payload.get("semaine_ids", [])}
    semaines_a_importer = [
        semaine for semaine in semaines
        if "semaine_ids" not in payload or semaine.debut.isoformat() in ids_selectionnes
    ]
    groupes = regrouper_semaines_vacances(semaines)
    creees = 0
    mises_a_jour = 0
    with transaction.atomic():
        for ordre, semaine in enumerate(semaines_a_importer):
            groupe = next(item for item in groupes if any(s["debut"] == semaine.debut.isoformat() for s in item["semaines"]))
            reference, _ = PeriodeCalendrier.objects.get_or_create(
                categorie=PeriodeCalendrier.VACANCES,
                annee_scolaire=annee_scolaire,
                zone=zone,
                debut=groupe["semaines"][0]["debut"],
                fin=groupe["semaines"][-1]["fin"],
                defaults={"nom": groupe["nom"].rsplit(" ", 1)[0]},
            )
            reference.types_accueil.add(type_accueil)
            periode, creee = PeriodeScolaire.objects.get_or_create(
                annee_scolaire=annee_scolaire,
                zone=zone,
                debut=semaine.debut,
                fin=semaine.fin,
                defaults={
                    "nom": semaine.nom,
                    "description_source": semaine.description_source,
                    "ordre": ordre,
                    "type_accueil": type_accueil,
                    "periode_calendrier": reference,
                },
            )
            if creee:
                periode.types_accueil.add(type_accueil)
                creees += 1
                # Toute nouvelle semaine appartient automatiquement aux groupes permanents.
                for groupe in groupes_visibles(Evenement.objects.filter(permanent=True)).only("id"):
                    groupe.periodes_scolaires.add(periode)
                continue
            champs = []
            periode.types_accueil.add(type_accueil)
            if periode.periode_calendrier_id is None:
                periode.periode_calendrier = reference
                champs.append("periode_calendrier")
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


@require_http_methods(["PATCH", "DELETE"])
def api_periode_scolaire_detail(request, periode_id):
    try:
        periode = PeriodeScolaire.objects.get(pk=periode_id)
    except PeriodeScolaire.DoesNotExist:
        return JsonResponse({"error": "Période introuvable."}, status=404)
    if request.method == "DELETE":
        periode.delete()
        return JsonResponse({"ok": True})
    try:
        periode = _appliquer_payload_periode(periode, _payload_json(request))
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Cette période existe déjà pour cette zone."}, status=409)
    return JsonResponse(_periode_scolaire_to_dict(periode))


@require_POST
def api_calendrier_scolaire_previsualiser(request):
    """Calcule les périodes entre vacances depuis la même source officielle."""
    try:
        annee_scolaire, zone, _payload = _payload_import_periodes(request)
        semaines_vacances = recuperer_semaines(annee_scolaire, zone)
        periodes = calculer_periodes_scolaires(annee_scolaire, semaines_vacances)
    except CalendrierScolaireError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    for periode in periodes:
        periode["deja_enregistree"] = PeriodeCalendrier.objects.filter(
            categorie=PeriodeCalendrier.SCOLAIRE,
            annee_scolaire=annee_scolaire,
            zone=zone,
            debut=periode["debut"],
            fin=periode["fin"],
        ).exists()
    return JsonResponse({"annee_scolaire": annee_scolaire, "zone": zone, "periodes": periodes})


@require_POST
def api_calendrier_scolaire_enregistrer(request):
    try:
        annee_scolaire, zone, payload = _payload_import_periodes(request)
        type_accueil, modalite = _contexte_periscolaire_requis(payload)
        periodes = calculer_periodes_scolaires(annee_scolaire, recuperer_semaines(annee_scolaire, zone))
        selections = {int(item) for item in payload.get("periode_ids", [])}
    except (CalendrierScolaireError, ValidationError, TypeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, CalendrierScolaireError) else _message_validation(exc)
        return JsonResponse({"error": message}, status=400)

    creees = 0
    with transaction.atomic():
        for index, periode_data in enumerate(periodes):
            if index not in selections:
                continue
            reference, _ = PeriodeCalendrier.objects.get_or_create(
                categorie=PeriodeCalendrier.SCOLAIRE,
                annee_scolaire=annee_scolaire,
                zone=zone,
                debut=periode_data["debut"],
                fin=periode_data["fin"],
                defaults={"nom": periode_data["nom"]},
            )
            reference.types_accueil.add(type_accueil)
            for numero, semaine in enumerate(periode_data["semaines"], 1):
                travail, nouvelle = PeriodeScolaire.objects.get_or_create(
                    annee_scolaire=annee_scolaire,
                    zone=zone,
                    debut=semaine["debut"],
                    fin=semaine["fin"],
                    defaults={
                        "nom": f"{periode_data['nom']} — Semaine {numero}",
                        "type_accueil": type_accueil,
                        "periode_calendrier": reference,
                        "modalite_periscolaire": modalite,
                    },
                )
                if travail.periode_calendrier_id is None:
                    travail.periode_calendrier = reference
                    travail.save(update_fields=("periode_calendrier",))
                if travail.modalite_periscolaire_id is None:
                    travail.modalite_periscolaire = modalite
                    travail.save(update_fields=("modalite_periscolaire",))
                travail.types_accueil.add(type_accueil)
                travail.modalites_periscolaires.add(modalite)
                creees += int(nouvelle)
    return JsonResponse({"ok": True, "cree": creees})


def _sejour_to_dict(sejour):
    return {
        "id": sejour.pk,
        "nom": sejour.nom,
        "date_debut": sejour.date_debut.isoformat() if sejour.date_debut else "",
        "date_fin": sejour.date_fin.isoformat() if sejour.date_fin else "",
        "destination": sejour.destination,
        "periode_vacances_id": sejour.periode_vacances_id,
        "equipe_ids": list(sejour.equipe.values_list("pk", flat=True)),
        "responsable_id": sejour.responsable_id,
        "document_ids": list(sejour.documents.values_list("pk", flat=True)),
        "participants": list(sejour.participants.values("id", "prenom", "nom", "date_naissance")),
        "type_accueil": sejour.type_accueil.code,
        "avertissement": sejour.avertissement_periode_vacances,
    }


@require_http_methods(["GET", "POST"])
def api_sejours(request):
    if request.method == "GET":
        sejours = Sejour.objects.prefetch_related("equipe").select_related("periode_vacances")
        references = PeriodeCalendrier.objects.filter(categorie=PeriodeCalendrier.VACANCES)
        return JsonResponse({
            "sejours": [_sejour_to_dict(item) for item in sejours],
            "periodes_vacances": [{"id": item.pk, "nom": str(item)} for item in references],
            "animateurs": list(Animateur.objects.order_by("prenom", "nom").values("id", "prenom", "nom")),
        })
    try:
        payload = _payload_json(request)
        sejour = Sejour(
            nom=str(payload.get("nom", "")).strip(),
            date_debut=payload.get("date_debut") or None,
            date_fin=payload.get("date_fin") or None,
            destination=str(payload.get("destination", "")).strip(),
            periode_vacances_id=payload.get("periode_vacances_id") or None,
            responsable_id=payload.get("responsable_id") or None,
        )
        sejour.full_clean()
        sejour.save()
        sejour.equipe.set(Animateur.objects.filter(pk__in=payload.get("equipe_ids", [])))
        sejour.documents.set(payload.get("document_ids", []))
        for participant in payload.get("participants", []):
            ParticipantSejour.objects.create(
                sejour=sejour,
                prenom=str(participant.get("prenom", "")).strip(),
                nom=str(participant.get("nom", "")).strip(),
                date_naissance=participant.get("date_naissance") or None,
            )
    except (ValidationError, ValueError, TypeError) as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    return JsonResponse(_sejour_to_dict(sejour), status=201)
