"""API de gestion des centres, groupes, qualifications et périodes."""

import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Prefetch, Q
from django.http import JsonResponse
from django.utils.dateparse import parse_date, parse_time
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods, require_POST

from .access import est_direction
from .models import (
    QUALIFICATION_ICON_CHOICES,
    Animateur,
    AccueilCentre,
    BesoinEncadrement,
    Centre,
    Evenement,
    Groupe,
    PeriodeScolaire,
    PeriodeCalendrier,
    ModalitePeriscolaire,
    OuvertureCentrePeriode,
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
from .services.besoins_encadrement import (
    besoins_contextuels_payload,
    enregistrer_besoins_contextuels,
)
from .services.accueils import centres_avec_accueil_sur_periode
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


TYPES_ACCUEIL_STRUCTURE = (TypeAccueil.VACANCES, TypeAccueil.PERISCOLAIRE)


def _types_accueil_structure(payload, *, obligatoire=False):
    """Résout les types Vacances/Périscolaire envoyés par les formulaires.

    ``None`` signifie que le champ n'a pas été fourni (PATCH partiel). Les
    séjours restent gérés par leur entité dédiée et ne qualifient pas un lieu
    physique ou un groupe partagé.
    """

    if "type_accueil_codes" not in payload:
        return None
    codes = payload.get("type_accueil_codes")
    if not isinstance(codes, list):
        raise ValidationError("Les types d'accueil sont invalides.")
    codes = list(dict.fromkeys(str(code).strip() for code in codes if str(code).strip()))
    if obligatoire and not codes:
        raise ValidationError("Choisissez au moins un type d'accueil.")
    if any(code not in TYPES_ACCUEIL_STRUCTURE for code in codes):
        raise ValidationError("Seuls Vacances et Périscolaire peuvent qualifier un lieu ou un groupe.")
    types = list(TypeAccueil.objects.filter(code__in=codes, actif=True).order_by("ordre", "nom"))
    if len(types) != len(codes):
        raise ValidationError("Un type d'accueil sélectionné n'est plus disponible.")
    return types


def _types_communs_instance(centre, groupe):
    codes_centre = set(centre.types_accueil.values_list("code", flat=True))
    return list(groupe.types_accueil.filter(code__in=codes_centre, actif=True))


def _synchroniser_types_instances_centre(centre):
    for instance in centre.evenements.select_related("groupe", "accueil_centre__type_accueil").all():
        if instance.accueil_centre_id:
            instance.types_accueil.set([instance.accueil_centre.type_accueil])
        else:
            instance.types_accueil.set(_types_communs_instance(centre, instance.groupe))


def _ouverture_to_dict(ouverture):
    return {
        "id": ouverture.pk,
        "accueil_centre_id": ouverture.accueil_centre_id,
        "accueil_nom": ouverture.accueil_centre.nom_affichage if ouverture.accueil_centre_id else "",
        "periode_calendrier_id": ouverture.periode_calendrier_id,
        "periode_debut": ouverture.periode_calendrier.debut.isoformat(),
        "periode_fin": ouverture.periode_calendrier.fin.isoformat(),
        "modalite_id": ouverture.modalite_periscolaire_id,
        "modalite_code": ouverture.modalite_periscolaire.code,
        "modalite_nom": ouverture.modalite_periscolaire.nom,
        "jour_semaine": ouverture.jour_semaine,
        "heure_debut": (
            ouverture.heure_debut_effective.strftime("%H:%M")
            if ouverture.heure_debut_effective else ""
        ),
        "heure_fin": (
            ouverture.heure_fin_effective.strftime("%H:%M")
            if ouverture.heure_fin_effective else ""
        ),
        "horaire_personnalise": bool(ouverture.heure_debut and ouverture.heure_fin),
        "actif": ouverture.actif,
    }


class RecuperationOuverturesHistoriquesRequise(Exception):
    """Demande une confirmation avant d'adopter des créneaux legacy.

    Avant ``AccueilCentre``, une ouverture périscolaire appartenait seulement
    au lieu. Lorsqu'un accueil précis est créé aujourd'hui, cette ancienne
    ligne ne doit ni être adoptée silencieusement ni être traitée comme un
    vrai conflit : l'utilisateur choisit explicitement de la récupérer.
    """

    def __init__(self, accueil, ouvertures):
        self.accueil = accueil
        self.ouvertures = ouvertures
        super().__init__("Des créneaux périscolaires historiques peuvent être récupérés.")


def _detail_ouverture_historique(ouverture):
    jours = dict(OuvertureCentrePeriode.JOURS_SEMAINE)
    return {
        "id": ouverture.pk,
        "modalite_id": ouverture.modalite_periscolaire_id,
        "modalite_nom": ouverture.modalite_periscolaire.nom,
        "jour_semaine": ouverture.jour_semaine,
        "jour_nom": jours.get(ouverture.jour_semaine, str(ouverture.jour_semaine)),
        "periode_calendrier_id": ouverture.periode_calendrier_id,
        "periode_nom": ouverture.periode_calendrier.nom,
        "annee_scolaire": ouverture.periode_calendrier.annee_scolaire,
        "heure_debut": (
            ouverture.heure_debut_effective.strftime("%H:%M")
            if ouverture.heure_debut_effective else ""
        ),
        "heure_fin": (
            ouverture.heure_fin_effective.strftime("%H:%M")
            if ouverture.heure_fin_effective else ""
        ),
    }


def _reponse_recuperation_ouvertures_historiques(exc):
    return JsonResponse(
        {
            "error": (
                "Animation Manager a trouvé un ou plusieurs anciens créneaux "
                "Périscolaire non rattachés à un accueil. Confirmez si vous souhaitez les récupérer."
            ),
            "code": "ouvertures_historiques_a_recuperer",
            "accueil_nom": exc.accueil.nom_affichage,
            "ouvertures": [_detail_ouverture_historique(item) for item in exc.ouvertures],
        },
        status=409,
    )


def _conflits_ouvertures_periscolaires(accueil, references, normalisees):
    """Prépare les conflits avant toute écriture.

    Un créneau déjà rattaché à un autre ``AccueilCentre`` est un vrai conflit
    et reste bloquant. Une ligne historique sans accueil explicite est au
    contraire proposée à la récupération.
    """

    historiques = {}
    for reference in references:
        for modalite, jour, _debut, _fin in normalisees:
            conflit = (
                accueil.centre.ouvertures_periodes.filter(
                    periode_calendrier=reference,
                    modalite_periscolaire=modalite,
                    jour_semaine=jour,
                )
                .exclude(accueil_centre=accueil)
                .select_related("accueil_centre", "periode_calendrier", "modalite_periscolaire")
                .first()
            )
            if conflit is None:
                continue
            if conflit.accueil_centre_id is not None:
                autre = conflit.accueil_centre.nom_affichage
                raise ValidationError(
                    f"Le créneau « {modalite.nom} » est déjà utilisé ce jour par {autre}."
                )
            historiques[conflit.pk] = conflit
    return list(historiques.values())


def _enregistrer_ouvertures_accueil(
    accueil, references, normalisees, *, recuperer_historiques=False
):
    """Enregistre les ouvertures d'un accueil avec reprise legacy explicite."""

    historiques = _conflits_ouvertures_periscolaires(accueil, references, normalisees)
    if historiques and not recuperer_historiques:
        raise RecuperationOuverturesHistoriquesRequise(accueil, historiques)

    for reference in references:
        accueil.ouvertures_periodes.filter(periode_calendrier=reference).delete()
        for modalite, jour, debut, fin in normalisees:
            conflit = (
                accueil.centre.ouvertures_periodes.filter(
                    periode_calendrier=reference,
                    modalite_periscolaire=modalite,
                    jour_semaine=jour,
                )
                .exclude(accueil_centre=accueil)
                .select_related("accueil_centre")
                .first()
            )
            if conflit is not None:
                if conflit.accueil_centre_id is None and recuperer_historiques:
                    conflit.accueil_centre = accueil
                    conflit.heure_debut = debut
                    conflit.heure_fin = fin
                    conflit.actif = True
                    conflit.full_clean()
                    conflit.save(update_fields=["accueil_centre", "heure_debut", "heure_fin", "actif"])
                    continue
                autre = conflit.accueil_centre.nom_affichage if conflit.accueil_centre_id else "un ancien créneau"
                raise ValidationError(
                    f"Le créneau « {modalite.nom} » est déjà utilisé ce jour par {autre}."
                )

            ouverture = OuvertureCentrePeriode(
                centre=accueil.centre,
                accueil_centre=accueil,
                periode_calendrier=reference,
                modalite_periscolaire=modalite,
                jour_semaine=jour,
                heure_debut=debut,
                heure_fin=fin,
            )
            ouverture.full_clean()
            ouverture.save()
        reference.types_accueil.add(accueil.type_accueil)
    accueil.centre.types_accueil.add(accueil.type_accueil)


def _besoins_encadrement_du_contexte(evenement, lignes):
    """Ne garde que les besoins appartenant à l'accueil de l'instance.

    L'API d'édition d'un groupe est déjà contextualisée par ``AccueilCentre``.
    Une ancienne version du formulaire pouvait néanmoins envoyer en plus une
    carte cachée de l'autre accueil. Ces lignes parasites sont ignorées à la
    frontière HTTP ; le service métier reste strict et continue de refuser un
    vrai appel contradictoire.
    """

    if not getattr(evenement, "accueil_centre_id", None) or not isinstance(lignes, list):
        return lignes
    code = evenement.accueil_centre.type_accueil.code
    return [
        ligne
        for ligne in lignes
        if isinstance(ligne, dict) and str(ligne.get("type_accueil", "")).strip() == code
    ]


def _evenement_personnel_to_dict(evenement):
    """Libellé lisible du groupe technique dans le planning salarié."""
    data = evenement_to_dict(evenement, include_effectifs=False)
    data["est_flottant"] = est_groupe_flottants(evenement)
    if data["est_flottant"]:
        data["nom"] = "Animateur mixte"
    return data


@require_http_methods(["GET", "POST"])
def api_centres(request):
    """GET : liste des centres. POST : création d'un centre."""

    if request.method == "GET":
        inclure_groupes = request.GET.get("include_groupes") == "1"
        animateur = None if est_direction(request.user) else getattr(request.user, "profil_animateur", None)
        tous_types = bool(est_direction(request.user) and request.GET.get("tous_types") == "1")
        centres = Centre.objects.prefetch_related("types_accueil", "accueils__type_accueil")
        code_type = request.session.get("type_accueil", "") if animateur is None and not tous_types else ""
        type_accueil_contexte = (
            TypeAccueil.objects.filter(code=code_type, actif=True).first()
            if code_type in TYPES_ACCUEIL_STRUCTURE else None
        )
        modalite_contexte = None
        if type_accueil_contexte and type_accueil_contexte.code == TypeAccueil.PERISCOLAIRE:
            code_modalite = str(request.GET.get("modalite_periscolaire", "") or "").strip()
            if code_modalite:
                modalite_contexte = ModalitePeriscolaire.objects.filter(code=code_modalite, actif=True).first()
        periode_calendrier_contexte = None
        periode_calendrier_id = request.session.get("periode_calendrier_contexte")
        if periode_calendrier_id:
            periode_calendrier_contexte = PeriodeCalendrier.objects.filter(pk=periode_calendrier_id).first()
        if code_type in TYPES_ACCUEIL_STRUCTURE:
            # La présence du type reste compatible avec les anciennes données ;
            # les dates d'AccueilCentre sont appliquées dès qu'un contexte de
            # calendrier est connu.
            centres = centres.filter(types_accueil__code=code_type).distinct()
            debut_accueil = periode_calendrier_contexte.debut if periode_calendrier_contexte else None
            fin_accueil = periode_calendrier_contexte.fin if periode_calendrier_contexte else None
            if not debut_accueil and request.GET.get("start"):
                try:
                    debut_accueil = parse_to_aware_datetime(request.GET.get("start")).date()
                except ValueError:
                    debut_accueil = None
            if not fin_accueil and request.GET.get("end"):
                try:
                    # end est généralement exclusif dans le Planning ; garder
                    # sa date suffit pour le test de chevauchement.
                    fin_accueil = parse_to_aware_datetime(request.GET.get("end")).date()
                except ValueError:
                    fin_accueil = None
            if not debut_accueil and not fin_accueil:
                semaine_ids_contexte = request.session.get("semaines_contexte_travail") or []
                if semaine_ids_contexte:
                    bornes = PeriodeScolaire.objects.filter(pk__in=semaine_ids_contexte).order_by("debut")
                    premiere = bornes.first()
                    derniere = bornes.order_by("-fin").first()
                    debut_accueil = premiere.debut if premiere else None
                    fin_accueil = derniere.fin if derniere else None
            centres = centres_avec_accueil_sur_periode(
                centres, type_accueil_contexte or code_type, debut_accueil, fin_accueil
            )
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
            groupes_source.select_related("groupe", "accueil_centre", "accueil_centre__type_accueil").prefetch_related(
                "periodes_scolaires",
                "types_accueil",
                "dates_exclues",
                "besoins_qualifications__qualification",
                Prefetch(
                    "besoins_encadrement",
                    queryset=BesoinEncadrement.objects.select_related(
                        "type_accueil", "modalite_periscolaire", "periode_calendrier"
                    ).order_by(
                        "type_accueil__ordre", "modalite_periscolaire__ordre",
                        "periode_calendrier__debut", "id",
                    ),
                ),
            )
            .annotate(nb_affectations=Count("affectations", distinct=True))
            .order_by("ordre", "nom")
        )
        if animateur is not None:
            groupes = groupes.filter(centre_id__in=centre_ids).distinct()
        elif not est_direction(request.user):
            groupes = groupes.none()
        elif code_type in TYPES_ACCUEIL_STRUCTURE:
            groupes = groupes.filter(types_accueil__code=code_type).distinct()
            # Les groupes appartiennent désormais à un accueil daté. On borne
            # directement les instances, et pas seulement le lieu, pour ne pas
            # afficher de lignes vides avant la création (ou après la fermeture)
            # de l'accueil concerné.
            if locals().get("debut_accueil"):
                groupes = groupes.filter(
                    Q(accueil_centre__isnull=True)
                    | Q(accueil_centre__date_fin__isnull=True)
                    | Q(accueil_centre__date_fin__gte=debut_accueil)
                )
            if locals().get("fin_accueil"):
                groupes = groupes.filter(
                    Q(accueil_centre__isnull=True)
                    | Q(accueil_centre__date_debut__isnull=True)
                    | Q(accueil_centre__date_debut__lte=fin_accueil)
                )
            if modalite_contexte is not None:
                groupes = groupes.filter(
                    accueil_centre__ouvertures_periodes__modalite_periscolaire=modalite_contexte,
                    accueil_centre__ouvertures_periodes__actif=True,
                )
                if periode_calendrier_contexte is not None:
                    groupes = groupes.filter(
                        accueil_centre__ouvertures_periodes__periode_calendrier=periode_calendrier_contexte
                    )
                elif locals().get("debut_accueil") or locals().get("fin_accueil"):
                    if locals().get("debut_accueil"):
                        groupes = groupes.filter(
                            accueil_centre__ouvertures_periodes__periode_calendrier__fin__gte=debut_accueil
                        )
                    if locals().get("fin_accueil"):
                        groupes = groupes.filter(
                            accueil_centre__ouvertures_periodes__periode_calendrier__debut__lte=fin_accueil
                        )
                groupes = groupes.distinct()

        semaine_ids = request.session.get("semaines_contexte_travail") or []
        if animateur is None and semaine_ids:
            groupes = groupes.filter(permanent=True) | groupes.filter(periodes_scolaires__id__in=semaine_ids)
            groupes = groupes.distinct().order_by("ordre", "nom")

        centres = Centre.objects.prefetch_related(
            "types_accueil",
            "accueils__type_accueil",
            "ouvertures_periodes__modalite_periscolaire",
            "ouvertures_periodes__periode_calendrier",
            Prefetch("evenements", queryset=groupes, to_attr="_groupes_planning"),
        )
        if animateur is not None:
            centres = centres.filter(id__in=centre_ids)
        elif not est_direction(request.user):
            centres = centres.none()
        elif code_type in TYPES_ACCUEIL_STRUCTURE:
            centres = centres.filter(types_accueil__code=code_type).distinct()
            centres = centres_avec_accueil_sur_periode(
                centres, type_accueil_contexte or code_type,
                locals().get("debut_accueil"), locals().get("fin_accueil")
            )
        data = []
        for centre in centres:
            item = centre_to_dict(centre)
            item["ouvertures_periscolaires"] = [
                _ouverture_to_dict(ouverture)
                for ouverture in centre.ouvertures_periodes.all()
                if ouverture.actif
            ]
            if animateur is None:
                # La direction ne reçoit jamais le groupe technique flottant :
                # conserver ce chemin direct évite une requête par groupe.
                item["evenements"] = [
                    evenement_to_dict(
                        groupe,
                        include_effectifs=False,
                        type_accueil=type_accueil_contexte,
                        modalite_periscolaire=modalite_contexte,
                        periode_calendrier=periode_calendrier_contexte,
                    )
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
        types_structure = _types_accueil_structure(payload, obligatoire=True)
        if types_structure is None:
            types_structure = list(TypeAccueil.objects.filter(code=TypeAccueil.VACANCES, actif=True))

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
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        # Le champ `code` est unique en base (contrainte du modèle) :
        # on transforme l'erreur SQL brute en message compréhensible.
        return JsonResponse({"error": f"Le code « {code} » est déjà utilisé par un autre centre."}, status=409)

    centre.types_accueil.set(types_structure)
    for type_accueil in types_structure:
        AccueilCentre.objects.get_or_create(centre=centre, type_accueil=type_accueil)
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
        types_structure = _types_accueil_structure(payload, obligatoire=True)

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

    if types_structure is not None:
        centre.types_accueil.set(types_structure)
        for type_accueil in types_structure:
            AccueilCentre.objects.get_or_create(centre=centre, type_accueil=type_accueil)
        _synchroniser_types_instances_centre(centre)
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
    types = list(groupe.types_accueil.filter(code__in=TYPES_ACCUEIL_STRUCTURE).order_by("ordre", "nom"))
    return {
        "id": groupe.id,
        "nom": groupe.nom,
        "type_groupe": groupe.type_groupe,
        "type_groupe_libelle": groupe.get_type_groupe_display(),
        "date_debut_validite": groupe.date_debut_validite.isoformat() if groupe.date_debut_validite else "",
        "date_fin_validite": groupe.date_fin_validite.isoformat() if groupe.date_fin_validite else "",
        "statut_validite": groupe.statut_validite,
        "enfants_par_animateur_defaut": groupe.enfants_par_animateur_defaut,
        "categorie_age_reglementaire": groupe.categorie_age_reglementaire,
        "categorie_age_reglementaire_libelle": groupe.get_categorie_age_reglementaire_display(),
        "type_accueil_codes": [item.code for item in types],
        "types_accueil": [{"code": item.code, "nom": item.nom} for item in types],
        "nombre_instances": groupe.instances.count(),
        "portee": groupe.portee,
        "centre_id": groupe.centre_id,
        "centre_nom": groupe.centre.nom if groupe.centre_id else None,
        "lieux": [
            {"id": instance.centre_id, "nom": instance.centre.nom}
            for instance in groupe.instances.select_related("centre").order_by("centre__nom")
        ],
    }


def _enregistrer_caracteristiques_groupe(groupe, payload):
    groupe.portee = payload.get("portee", groupe.portee)
    if "centre_id" in payload:
        groupe.centre_id = int(payload["centre_id"]) if payload["centre_id"] else None
    if groupe.portee == Groupe.PARTAGE:
        groupe.centre_id = None
    nom = str(payload.get("nom", groupe.nom)).strip()
    ratio = int(payload.get("enfants_par_animateur_defaut", groupe.enfants_par_animateur_defaut))
    categorie_age = str(
        payload.get("categorie_age_reglementaire", groupe.categorie_age_reglementaire or Groupe.AGE_AUTRE)
    ).strip()
    type_groupe = str(payload.get("type_groupe", groupe.type_groupe or Groupe.TYPE_STRUCTURE)).strip()
    if not nom or ratio < 1 or ratio > 999:
        raise ValidationError("Le nom et un ratio compris entre 1 et 999 sont obligatoires.")
    if categorie_age not in dict(Groupe.CATEGORIES_AGE_REGLEMENTAIRE):
        raise ValidationError("La catégorie d'âge réglementaire est invalide.")
    if type_groupe not in dict(Groupe.TYPES_GROUPE):
        raise ValidationError("Le type de groupe est invalide.")

    date_debut_validite = groupe.date_debut_validite
    date_fin_validite = groupe.date_fin_validite
    if "date_debut_validite" in payload:
        brute = str(payload.get("date_debut_validite") or "").strip()
        date_debut_validite = parse_date(brute) if brute else None
        if brute and date_debut_validite is None:
            raise ValidationError("La date de début du séjour est invalide.")
    if "date_fin_validite" in payload:
        brute = str(payload.get("date_fin_validite") or "").strip()
        date_fin_validite = parse_date(brute) if brute else None
        if brute and date_fin_validite is None:
            raise ValidationError("La date de fin du séjour est invalide.")

    types_structure = _types_accueil_structure(payload, obligatoire=True)
    nouveau = groupe.pk is None
    groupe.nom = nom
    groupe.cle_unique = normaliser_cle_unique(nom)
    groupe.enfants_par_animateur_defaut = ratio
    groupe.categorie_age_reglementaire = categorie_age
    groupe.type_groupe = type_groupe
    groupe.date_debut_validite = date_debut_validite
    groupe.date_fin_validite = date_fin_validite
    groupe.full_clean()
    groupe.save()
    if types_structure is not None:
        groupe.types_accueil.set(types_structure)
    elif nouveau and not groupe.types_accueil.exists():
        groupe.types_accueil.set(TypeAccueil.objects.filter(code=TypeAccueil.VACANCES, actif=True))

    for instance in groupe.instances.select_related(
        "centre", "accueil_centre", "accueil_centre__type_accueil"
    ).all():
        instance.nom = groupe.nom
        instance.enfants_par_animateur_defaut = groupe.enfants_par_animateur_defaut
        instance.save()
        if instance.accueil_centre_id:
            # Une définition partagée peut être utilisée à la fois en Vacances
            # et en Périscolaire, mais chacune de ses instances appartient à
            # un seul AccueilCentre. Modifier le nom ou le ratio du groupe ne
            # doit donc jamais remélanger les deux contextes.
            instance.types_accueil.set([instance.accueil_centre.type_accueil])
        else:
            instance.types_accueil.set(_types_communs_instance(instance.centre, groupe))
    return groupe


@require_http_methods(["GET", "POST"])
def api_groupes_partages(request):
    groupes = groupes_partages_visibles(Groupe.objects.all()).prefetch_related("types_accueil", "instances__centre", "instances__centre__types_accueil")
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
        evenements = groupes_visibles(centre.evenements.all())
        accueil_id = request.GET.get("accueil_id")
        if accueil_id:
            try:
                accueil = centre.accueils.get(pk=int(accueil_id))
            except (TypeError, ValueError, AccueilCentre.DoesNotExist):
                return JsonResponse({"error": "Accueil introuvable."}, status=404)
            evenements = evenements.filter(accueil_centre=accueil)
        evenements = (
            evenements.select_related("groupe", "accueil_centre", "accueil_centre__type_accueil").prefetch_related(
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
        with transaction.atomic():
            accueil = None
            accueil_id = payload.get("accueil_id") or payload.get("accueil_centre_id")
            if accueil_id:
                accueil = centre.accueils.select_related("type_accueil").get(pk=int(accueil_id))
            groupe_id = payload.get("groupe_id")
            if groupe_id:
                groupe_partage = groupes_partages_visibles(Groupe.objects.all()).get(pk=int(groupe_id))
            else:
                nom_groupe = str(payload.get("nom", "")).strip()
                from .services.multisite import trouver_ou_creer_groupe
                groupe_partage, creation = trouver_ou_creer_groupe(
                    nom_groupe, centre, portee=payload.get("portee"),
                    defaults={
                        "nom": nom_groupe,
                        "enfants_par_animateur_defaut": int(payload.get("enfants_par_animateur_defaut", 8) or 8),
                    },
                )
                if creation:
                    _enregistrer_caracteristiques_groupe(groupe_partage, payload)
                    if not groupe_partage.types_accueil.exists():
                        types_centre = centre.types_accueil.filter(code__in=TYPES_ACCUEIL_STRUCTURE, actif=True)
                        if types_centre.exists():
                            groupe_partage.types_accueil.set(types_centre)
                        else:
                            groupe_partage.types_accueil.set(
                                TypeAccueil.objects.filter(code=TypeAccueil.VACANCES, actif=True)
                            )
            doublons = centre.evenements.filter(groupe=groupe_partage)
            if accueil is not None:
                doublons = doublons.filter(accueil_centre=accueil)
            else:
                doublons = doublons.filter(accueil_centre__isnull=True)
            if doublons.exists():
                return JsonResponse(
                    {"error": "Ce groupe possède déjà une instance dans cet accueil."},
                    status=409,
                )
            evenement = creer_evenement(
                centre=centre,
                accueil_centre=accueil,
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
            if accueil is not None:
                evenement.types_accueil.set([accueil.type_accueil])
                groupe_partage.types_accueil.add(accueil.type_accueil)
            else:
                evenement.types_accueil.set(_types_communs_instance(centre, groupe_partage))
            if "besoins_encadrement" in payload:
                enregistrer_besoins_contextuels(
                    evenement,
                    _besoins_encadrement_du_contexte(evenement, payload.get("besoins_encadrement")),
                )
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Requête invalide."}, status=400)
    except AccueilCentre.DoesNotExist:
        return JsonResponse({"error": "Accueil introuvable."}, status=404)
    except Groupe.DoesNotExist:
        return JsonResponse({"error": "Groupe partagé introuvable."}, status=404)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Un groupe de ce nom existe déjà dans cet accueil."}, status=409)

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
        evenement = Evenement.objects.select_related(
            "centre", "groupe", "accueil_centre", "accueil_centre__type_accueil"
        ).get(pk=evenement_id)
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
        with transaction.atomic():
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
            if "besoins_encadrement" in payload:
                enregistrer_besoins_contextuels(
                    evenement,
                    _besoins_encadrement_du_contexte(evenement, payload.get("besoins_encadrement")),
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




def _date_accueil(payload, champ, *, obligatoire=False):
    brut = str(payload.get(champ, "") or "").strip()
    if not brut:
        if obligatoire:
            raise ValidationError("La date de début de l'accueil est obligatoire.")
        return None
    valeur = parse_date(brut)
    if valeur is None:
        raise ValidationError("Une date d'accueil est invalide.")
    return valeur


def _accueil_centre_to_dict(accueil):
    groupes = list(accueil.groupes.select_related("groupe").order_by("ordre", "nom"))
    return {
        "id": accueil.id,
        "centre_id": accueil.centre_id,
        "type_accueil_id": accueil.type_accueil_id,
        "type_accueil_code": accueil.type_accueil.code,
        "type_accueil_nom": accueil.type_accueil.nom,
        "libelle": accueil.libelle,
        "nom_affichage": accueil.nom_affichage,
        "date_debut": accueil.date_debut.isoformat() if accueil.date_debut else "",
        "date_fin": accueil.date_fin.isoformat() if accueil.date_fin else "",
        "pedt_applicable": bool(accueil.pedt_applicable),
        "statut": accueil.statut,
        "libelle_analytique": accueil.libelle_analytique,
        "groupes": [{"id": groupe.id, "groupe_id": groupe.groupe_id, "nom": groupe.nom} for groupe in groupes],
    }


def _normaliser_accueil_centre(centre, ligne, *, exiger_date=True, autoriser_existant=False):
    code = str(ligne.get("type_accueil") or ligne.get("type_accueil_code") or "").strip()
    if code not in TYPES_ACCUEIL_STRUCTURE:
        raise ValidationError("Choisissez Vacances ou Périscolaire.")
    try:
        type_accueil = TypeAccueil.objects.get(code=code, actif=True)
    except TypeAccueil.DoesNotExist as exc:
        raise ValidationError("Le type d'accueil n'est plus disponible.") from exc
    date_debut = _date_accueil(ligne, "date_debut", obligatoire=exiger_date)
    date_fin = _date_accueil(ligne, "date_fin")
    if date_debut and date_fin and date_fin < date_debut:
        raise ValidationError("La date de fin d'un accueil doit suivre sa date de début.")
    libelle = str(ligne.get("libelle", "") or "").strip()
    existants = AccueilCentre.objects.filter(centre=centre, type_accueil=type_accueil)
    accueil = None
    if autoriser_existant:
        accueil_id = ligne.get("id") or ligne.get("accueil_id")
        if accueil_id:
            accueil = existants.filter(pk=int(accueil_id)).first()
    if accueil is None:
        if code == TypeAccueil.VACANCES and existants.exists():
            raise ValidationError("L'accueil Vacances existe déjà dans ce lieu.")
        if code == TypeAccueil.PERISCOLAIRE:
            if existants.exists() and not libelle:
                raise ValidationError(
                    "Donnez un nom complémentaire pour distinguer ce nouvel accueil Périscolaire (ex. Mercredi ou Semaine)."
                )
            if existants.filter(libelle__iexact=libelle).exists():
                raise ValidationError("Un accueil Périscolaire du même nom existe déjà dans ce lieu.")
        accueil = AccueilCentre(centre=centre, type_accueil=type_accueil)
    accueil.libelle = libelle
    accueil.date_debut = date_debut
    accueil.date_fin = date_fin
    accueil.pedt_applicable = bool(ligne.get("pedt_applicable")) if code == TypeAccueil.PERISCOLAIRE else False
    accueil.save()
    centre.types_accueil.add(type_accueil)
    return accueil


@require_http_methods(["GET", "POST"])
def api_accueils_centre(request, centre_id):
    try:
        centre = Centre.objects.get(pk=centre_id)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Lieu introuvable."}, status=404)
    if request.method == "GET":
        accueils = centre.accueils.select_related("type_accueil").all()
        return JsonResponse([_accueil_centre_to_dict(item) for item in accueils], safe=False)
    try:
        payload = _payload_json(request)
        with transaction.atomic():
            accueil = _normaliser_accueil_centre(centre, payload, exiger_date=True)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Cet accueil existe déjà dans ce lieu."}, status=409)
    return JsonResponse(_accueil_centre_to_dict(accueil), status=201)


@require_http_methods(["PATCH"])
def api_accueil_centre_detail(request, accueil_id):
    try:
        accueil = AccueilCentre.objects.select_related("centre", "type_accueil").get(pk=accueil_id)
    except AccueilCentre.DoesNotExist:
        return JsonResponse({"error": "Accueil introuvable."}, status=404)
    try:
        payload = _payload_json(request)
        date_debut = _date_accueil(payload, "date_debut", obligatoire=True) if "date_debut" in payload else accueil.date_debut
        date_fin = _date_accueil(payload, "date_fin") if "date_fin" in payload else accueil.date_fin
        if date_debut and date_fin and date_fin < date_debut:
            raise ValidationError("La date de fin doit suivre la date de début.")
        accueil.date_debut = date_debut
        accueil.date_fin = date_fin
        if "libelle" in payload:
            accueil.libelle = str(payload.get("libelle") or "").strip()
        if accueil.type_accueil.code == TypeAccueil.PERISCOLAIRE and "pedt_applicable" in payload:
            accueil.pedt_applicable = bool(payload.get("pedt_applicable"))
        accueil.save()
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    return JsonResponse(_accueil_centre_to_dict(accueil))


def _groupe_assistant_partage(ligne, type_accueil, centre=None):
    if not isinstance(ligne, dict):
        raise ValidationError("Un groupe sélectionné est invalide.")
    groupe_id = ligne.get("id") or ligne.get("groupe_id")
    if groupe_id:
        groupe = groupes_partages_visibles(Groupe.objects.all()).get(pk=int(groupe_id))
        if groupe.type_groupe != Groupe.TYPE_STRUCTURE:
            raise ValidationError("Les groupes de séjour ne peuvent pas être utilisés dans cet assistant.")
    else:
        nom = str(ligne.get("nom", "")).strip()
        if not nom:
            raise ValidationError("Le nom du nouveau groupe est obligatoire.")
        cle = normaliser_cle_unique(nom)
        from .services.multisite import multisite_actif
        portee = ligne.get("portee") or (Groupe.PARTAGE if multisite_actif() else Groupe.LOCAL)
        groupe = Groupe.objects.filter(cle_unique=cle, portee=portee, centre=centre if portee == Groupe.LOCAL else None).first()
        if groupe is not None and groupe.type_groupe != Groupe.TYPE_STRUCTURE:
            raise ValidationError(
                "Un groupe de séjour porte déjà ce nom. Choisis un autre nom pour le groupe structurel."
            )
        if groupe is None:
            groupe = Groupe(
                nom=nom,
                cle_unique=cle,
                portee=portee,
                centre=centre if portee == Groupe.LOCAL else None,
                type_groupe=Groupe.TYPE_STRUCTURE,
                categorie_age_reglementaire=str(ligne.get("categorie_age_reglementaire") or Groupe.AGE_AUTRE),
                enfants_par_animateur_defaut=int(ligne.get("enfants_par_animateur_defaut", 8) or 8),
            )
            groupe.full_clean()
            groupe.save()
    groupe.types_accueil.add(type_accueil)
    return groupe


def _periodes_accueil(accueil, fonctionnement):
    code = accueil.type_accueil.code
    if code == TypeAccueil.VACANCES:
        permanent = bool(fonctionnement.get("permanent", False))
        if permanent:
            return list(
                PeriodeScolaire.objects.filter(
                    Q(type_accueil=accueil.type_accueil) | Q(types_accueil=accueil.type_accueil)
                ).distinct()
            ), permanent
        try:
            ids = sorted({int(item) for item in fonctionnement.get("periode_ids", [])})
        except (TypeError, ValueError) as exc:
            raise ValidationError("Les périodes Vacances sont invalides.") from exc
        if not ids:
            raise ValidationError("Choisissez les périodes de vacances ouvertes ou activez « toutes les périodes ».")
        periodes = list(
            PeriodeScolaire.objects.filter(pk__in=ids)
            .filter(Q(type_accueil=accueil.type_accueil) | Q(types_accueil=accueil.type_accueil))
            .distinct()
        )
        if len(periodes) != len(ids):
            raise ValidationError("Une période sélectionnée n'appartient pas à l'accueil Vacances.")
        return periodes, permanent
    try:
        references = sorted({int(item) for item in fonctionnement.get("periode_calendrier_ids", [])})
    except (TypeError, ValueError) as exc:
        raise ValidationError("Les périodes périscolaires sont invalides.") from exc
    if not references:
        raise ValidationError("Choisissez au moins une période scolaire pour le Périscolaire.")
    periodes = list(
        PeriodeScolaire.objects.filter(periode_calendrier_id__in=references)
        .filter(Q(type_accueil=accueil.type_accueil) | Q(types_accueil=accueil.type_accueil))
        .distinct()
    )
    references_trouvees = {periode.periode_calendrier_id for periode in periodes}
    if references_trouvees != set(references):
        raise ValidationError("Une période sélectionnée n'appartient pas à l'accueil Périscolaire.")
    return periodes, False


def _jours_accueil(accueil, fonctionnement):
    if accueil.type_accueil.code == TypeAccueil.VACANCES:
        try:
            jours = sorted({int(jour) for jour in fonctionnement.get("jours_ouverts", [])})
        except (TypeError, ValueError) as exc:
            raise ValidationError("Les jours d'ouverture Vacances sont invalides.") from exc
    else:
        try:
            jours = sorted({int(ligne.get("jour_semaine")) for ligne in fonctionnement.get("ouvertures", [])})
        except (TypeError, ValueError) as exc:
            raise ValidationError("Les jours d'ouverture Périscolaire sont invalides.") from exc
    if not jours:
        raise ValidationError("Choisissez au moins un jour d'ouverture.")
    return jours


def _groupes_assistant_accueil(accueil, lignes, fonctionnement):
    """Crée les instances de groupes propres à UN accueil.

    La définition Groupe reste partagée, mais l'instance Evenement appartient
    maintenant à l'AccueilCentre. Un même « Maternelle » peut donc avoir une
    configuration Vacances et une configuration Périscolaire totalement
    indépendantes dans le même lieu.
    """
    if not isinstance(lignes, list) or not lignes:
        raise ValidationError(f"Choisissez au moins un groupe pour {accueil.nom_affichage}.")
    periodes, permanent = _periodes_accueil(accueil, fonctionnement)
    jours = _jours_accueil(accueil, fonctionnement)
    evenements = []
    for ligne in lignes:
        groupe = _groupe_assistant_partage(ligne, accueil.type_accueil, accueil.centre)
        evenement = accueil.groupes.filter(groupe=groupe).first()
        if evenement is None:
            evenement = creer_evenement(
                centre=accueil.centre,
                accueil_centre=accueil,
                nom=groupe.nom,
                groupe_partage=groupe,
                periode_ids=[periode.id for periode in periodes],
                effectif_cible=1,
                enfants_par_animateur_defaut=groupe.enfants_par_animateur_defaut,
                jours_ouverts=jours,
                ferme_jours_feries=(fonctionnement.get("ferme_jours_feries", True) is not False),
                permanent=permanent,
            )
        else:
            evenement.permanent = permanent
            evenement.jours_ouverts = jours
            evenement.ferme_jours_feries = fonctionnement.get("ferme_jours_feries", True) is not False
            evenement.save(update_fields=["permanent", "jours_ouverts", "ferme_jours_feries"])
            evenement.periodes_scolaires.set(periodes)
            evenement.types_accueil.set([accueil.type_accueil])
        nouvelles_regles = _besoins_encadrement_du_contexte(
            evenement, ligne.get("besoins_encadrement") or []
        )
        if nouvelles_regles:
            # Cette instance appartient à un seul accueil : aucune règle de
            # l'autre accueil ne peut être écrasée par cette sauvegarde.
            enregistrer_besoins_contextuels(evenement, nouvelles_regles)
        evenements.append(evenement)
    return evenements


def _ouvertures_assistant(accueil, periscolaire):
    if accueil.type_accueil.code != TypeAccueil.PERISCOLAIRE:
        return
    try:
        ids = sorted({int(item) for item in periscolaire.get("periode_calendrier_ids", [])})
    except (TypeError, ValueError) as exc:
        raise ValidationError("Les périodes périscolaires sont invalides.") from exc
    if not ids:
        raise ValidationError("Choisissez au moins une période scolaire pour le Périscolaire.")
    references = list(PeriodeCalendrier.objects.filter(pk__in=ids, categorie=PeriodeCalendrier.SCOLAIRE))
    if len(references) != len(ids):
        raise ValidationError("Une période scolaire sélectionnée est introuvable.")
    lignes = periscolaire.get("ouvertures") or []
    if not isinstance(lignes, list) or not lignes:
        raise ValidationError("Choisissez au moins un jour et un créneau d'ouverture périscolaire.")
    modalites = {item.id: item for item in ModalitePeriscolaire.objects.filter(actif=True)}
    normalisees = []
    cles = set()
    for ligne in lignes:
        try:
            modalite_id = int(ligne.get("modalite_id"))
            jour = int(ligne.get("jour_semaine"))
        except (TypeError, ValueError) as exc:
            raise ValidationError("Un créneau périscolaire est invalide.") from exc
        if modalite_id not in modalites or not 0 <= jour <= 6 or (modalite_id, jour) in cles:
            raise ValidationError("Un créneau périscolaire est invalide ou dupliqué.")
        cles.add((modalite_id, jour))
        debut_brut = str(ligne.get("heure_debut") or "").strip()
        fin_brut = str(ligne.get("heure_fin") or "").strip()
        debut = parse_time(debut_brut) if debut_brut else None
        fin = parse_time(fin_brut) if fin_brut else None
        if bool(debut) != bool(fin) or (debut and fin <= debut):
            raise ValidationError("Les horaires d'un créneau périscolaire sont incohérents.")
        normalisees.append((modalites[modalite_id], jour, debut, fin))
    _enregistrer_ouvertures_accueil(
        accueil,
        references,
        normalisees,
        recuperer_historiques=bool(periscolaire.get("recuperer_ouvertures_historiques")),
    )


@require_POST
def api_assistant_lieu_accueils(request):
    """Crée le lieu puis configure chaque accueil indépendamment."""
    centre = None
    try:
        payload = _payload_json(request)
        centre_id = payload.get("centre_id")
        accueils_lignes = payload.get("accueils")
        if not isinstance(accueils_lignes, list) or not accueils_lignes:
            raise ValidationError("Configurez au moins un accueil.")
        with transaction.atomic():
            if centre_id:
                centre = Centre.objects.select_for_update().get(pk=int(centre_id))
            else:
                centre_data = payload.get("centre") or {}
                nom = str(centre_data.get("nom", "")).strip()
                code = str(centre_data.get("code", "")).strip()
                if not nom or not code:
                    raise ValidationError("Le nom et le nom court du lieu sont obligatoires.")
                code_postal = str(centre_data.get("code_postal", "")).strip()
                if code_postal:
                    code_postal_francais(code_postal)
                if Centre.objects.filter(cle_unique=normaliser_cle_unique(nom)).exists():
                    raise ValidationError(f"Le lieu « {nom} » existe déjà.")
                centre = Centre.objects.create(
                    nom=nom,
                    code=code,
                    couleur=str(centre_data.get("couleur", "#1f6f54") or "#1f6f54"),
                    adresse=str(centre_data.get("adresse", "")).strip(),
                    code_postal=code_postal,
                    commune=str(centre_data.get("commune", "")).strip(),
                    effectif_cible=1,
                    ordre=prochain_ordre_centre(),
                )
            total_groupes = 0
            for ligne in accueils_lignes:
                if not isinstance(ligne, dict):
                    raise ValidationError("Un accueil est invalide.")
                accueil = _normaliser_accueil_centre(centre, ligne, exiger_date=True, autoriser_existant=False)
                fonctionnement = ligne.get("fonctionnement") or {}
                if accueil.type_accueil.code == TypeAccueil.PERISCOLAIRE:
                    _ouvertures_assistant(accueil, fonctionnement)
                evenements = _groupes_assistant_accueil(
                    accueil,
                    ligne.get("groupes") or [],
                    fonctionnement,
                )
                total_groupes += len(evenements)

        warning = ""
        if not centre_id:
            centre_data = payload.get("centre") or {}
            centre_data = {**centre_data, "localisation_demandee": bool(centre_data.get("localisation_demandee", True))}
            warning = _localiser_centre(centre, centre_data)
        centre = Centre.objects.prefetch_related("types_accueil", "accueils__type_accueil").get(pk=centre.pk)
        resultat = centre_to_dict(centre)
        resultat["localisation_warning"] = warning
        resultat["groupes_crees_ou_completes"] = total_groupes
        return JsonResponse(resultat, status=201 if not centre_id else 200)
    except RecuperationOuverturesHistoriquesRequise as exc:
        return _reponse_recuperation_ouvertures_historiques(exc)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Lieu introuvable."}, status=404)
    except Groupe.DoesNotExist:
        return JsonResponse({"error": "Un groupe sélectionné est introuvable."}, status=404)
    except IntegrityError:
        return JsonResponse({"error": "Un lieu, un accueil ou un groupe existe déjà avec ces informations."}, status=409)
    except (TypeError, ValueError, ValidationError) as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)


# ---------------------------------------------------------------------------
# API - Référentiels Vacances / Périscolaire et ouvertures de centres
# ---------------------------------------------------------------------------


@require_http_methods(["GET"])
def api_types_accueil(request):
    types = TypeAccueil.objects.filter(actif=True, code__in=TYPES_ACCUEIL_STRUCTURE).order_by("ordre", "nom")
    return JsonResponse([{"id": item.pk, "code": item.code, "nom": item.nom} for item in types], safe=False)


def _modalite_periscolaire_to_dict(item):
    return {
        "id": item.pk,
        "code": item.code,
        "nom": item.nom,
        "heure_debut": item.heure_debut.strftime("%H:%M") if item.heure_debut else "",
        "heure_fin": item.heure_fin.strftime("%H:%M") if item.heure_fin else "",
        "jour_entier": bool(item.jour_entier),
        "actif": bool(item.actif),
        "ordre": item.ordre,
    }


def _horaires_modalite(payload):
    debut_brut = str(payload.get("heure_debut", "") or "").strip()
    fin_brut = str(payload.get("heure_fin", "") or "").strip()
    debut = parse_time(debut_brut) if debut_brut else None
    fin = parse_time(fin_brut) if fin_brut else None
    if bool(debut) != bool(fin):
        raise ValidationError("Renseignez les deux horaires ou laissez-les vides.")
    if debut and fin <= debut:
        raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")
    return debut, fin


def _nouveau_code_modalite(nom):
    base = slugify(nom).replace("-", "_")[:32] or "creneau"
    code = base
    index = 2
    while ModalitePeriscolaire.objects.filter(code=code).exists():
        suffixe = f"_{index}"
        code = f"{base[:40-len(suffixe)]}{suffixe}"
        index += 1
    return code


@require_http_methods(["GET", "POST"])
def api_modalites_periscolaires(request):
    if request.method == "GET":
        modalites = ModalitePeriscolaire.objects.all().order_by("ordre", "nom")
        if request.GET.get("tous") != "1":
            modalites = modalites.filter(actif=True)
        return JsonResponse([_modalite_periscolaire_to_dict(item) for item in modalites], safe=False)
    try:
        payload = _payload_json(request)
        nom = str(payload.get("nom", "") or "").strip()
        if not nom:
            raise ValidationError("Le nom du temps périscolaire est obligatoire.")
        if ModalitePeriscolaire.objects.filter(nom__iexact=nom).exists():
            raise ValidationError("Un temps périscolaire porte déjà ce nom.")
        debut, fin = _horaires_modalite(payload)
        ordre = (ModalitePeriscolaire.objects.aggregate(max_ordre=Max("ordre"))["max_ordre"] or 0) + 10
        item = ModalitePeriscolaire.objects.create(
            code=_nouveau_code_modalite(nom),
            nom=nom,
            heure_debut=debut,
            heure_fin=fin,
            jour_entier=bool(payload.get("jour_entier")),
            actif=True,
            ordre=ordre,
        )
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "Ce temps périscolaire existe déjà."}, status=409)
    return JsonResponse(_modalite_periscolaire_to_dict(item), status=201)


@require_http_methods(["PATCH"])
def api_modalite_periscolaire_detail(request, modalite_id):
    try:
        item = ModalitePeriscolaire.objects.get(pk=modalite_id)
    except ModalitePeriscolaire.DoesNotExist:
        return JsonResponse({"error": "Temps périscolaire introuvable."}, status=404)
    try:
        payload = _payload_json(request)
        if "nom" in payload:
            nom = str(payload.get("nom", "") or "").strip()
            if not nom:
                raise ValidationError("Le nom du temps périscolaire est obligatoire.")
            if ModalitePeriscolaire.objects.exclude(pk=item.pk).filter(nom__iexact=nom).exists():
                raise ValidationError("Un temps périscolaire porte déjà ce nom.")
            item.nom = nom
        if "heure_debut" in payload or "heure_fin" in payload:
            item.heure_debut, item.heure_fin = _horaires_modalite({
                "heure_debut": payload.get("heure_debut", item.heure_debut.strftime("%H:%M") if item.heure_debut else ""),
                "heure_fin": payload.get("heure_fin", item.heure_fin.strftime("%H:%M") if item.heure_fin else ""),
            })
        if "jour_entier" in payload:
            item.jour_entier = bool(payload.get("jour_entier"))
        if "actif" in payload:
            item.actif = bool(payload.get("actif"))
        item.save()
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)
    return JsonResponse(_modalite_periscolaire_to_dict(item))


@require_http_methods(["GET"])
def api_periodes_calendrier(request):
    queryset = PeriodeCalendrier.objects.prefetch_related("types_accueil").all()
    categorie = str(request.GET.get("categorie", "")).strip()
    if categorie in {PeriodeCalendrier.VACANCES, PeriodeCalendrier.SCOLAIRE}:
        queryset = queryset.filter(categorie=categorie)
    return JsonResponse([
        {
            "id": item.pk,
            "categorie": item.categorie,
            "nom": item.nom,
            "annee_scolaire": item.annee_scolaire,
            "zone": item.zone,
            "debut": item.debut.isoformat(),
            "fin": item.fin.isoformat(),
            "libelle": f"{item.nom} · {item.annee_scolaire}",
            "type_accueil_codes": list(item.types_accueil.values_list("code", flat=True)),
        }
        for item in queryset
    ], safe=False)


@require_http_methods(["GET", "POST"])
def api_ouvertures_periscolaires_centre(request, centre_id):
    try:
        centre = Centre.objects.prefetch_related("types_accueil", "accueils__type_accueil").get(pk=centre_id)
    except Centre.DoesNotExist:
        return JsonResponse({"error": "Lieu introuvable."}, status=404)

    accueils_perisco = centre.accueils.filter(
        type_accueil__code=TypeAccueil.PERISCOLAIRE
    ).select_related("type_accueil").order_by("libelle", "id")

    if request.method == "GET":
        queryset = centre.ouvertures_periodes.select_related(
            "periode_calendrier", "modalite_periscolaire", "accueil_centre", "accueil_centre__type_accueil"
        ).filter(actif=True)
        periode_id = request.GET.get("periode_calendrier_id")
        if periode_id:
            try:
                queryset = queryset.filter(periode_calendrier_id=int(periode_id))
            except (TypeError, ValueError):
                return JsonResponse({"error": "Période invalide."}, status=400)
        accueil_id = request.GET.get("accueil_id")
        if accueil_id:
            try:
                accueil = accueils_perisco.get(pk=int(accueil_id))
            except (TypeError, ValueError, AccueilCentre.DoesNotExist):
                return JsonResponse({"error": "Accueil périscolaire introuvable."}, status=404)
            queryset = queryset.filter(accueil_centre=accueil)
        elif accueils_perisco.count() == 1:
            queryset = queryset.filter(accueil_centre=accueils_perisco.first())
        return JsonResponse([_ouverture_to_dict(item) for item in queryset], safe=False)

    try:
        payload = _payload_json(request)
        periode_id = int(payload.get("periode_calendrier_id"))
        reference = PeriodeCalendrier.objects.get(pk=periode_id, categorie=PeriodeCalendrier.SCOLAIRE)
        accueil_id = payload.get("accueil_id")
        if accueil_id:
            accueil = accueils_perisco.get(pk=int(accueil_id))
        else:
            candidats = list(accueils_perisco[:2])
            if len(candidats) != 1:
                raise ValidationError("Choisissez l'accueil Périscolaire à configurer.")
            accueil = candidats[0]
        lignes = payload.get("ouvertures")
        if not isinstance(lignes, list):
            raise ValidationError("La liste des ouvertures est invalide.")
        modalites = {item.id: item for item in ModalitePeriscolaire.objects.filter(actif=True)}
        normalisees = []
        cles = set()
        for ligne in lignes:
            modalite_id = int(ligne.get("modalite_id"))
            jour = int(ligne.get("jour_semaine"))
            if modalite_id not in modalites or jour < 0 or jour > 6 or (modalite_id, jour) in cles:
                raise ValidationError("Un créneau d'ouverture est invalide ou dupliqué.")
            cles.add((modalite_id, jour))
            debut_brut = str(ligne.get("heure_debut", "") or "").strip()
            fin_brut = str(ligne.get("heure_fin", "") or "").strip()
            debut = parse_time(debut_brut) if debut_brut else None
            fin = parse_time(fin_brut) if fin_brut else None
            if bool(debut) != bool(fin) or (debut and fin <= debut):
                raise ValidationError("Les horaires d'un créneau sont incohérents.")
            normalisees.append((modalites[modalite_id], jour, debut, fin))
    except AccueilCentre.DoesNotExist:
        return JsonResponse({"error": "Accueil Périscolaire introuvable."}, status=404)
    except PeriodeCalendrier.DoesNotExist:
        return JsonResponse({"error": "Période scolaire introuvable."}, status=404)
    except (TypeError, ValueError, ValidationError) as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)

    try:
        with transaction.atomic():
            _enregistrer_ouvertures_accueil(
                accueil,
                [reference],
                normalisees,
                recuperer_historiques=bool(payload.get("recuperer_ouvertures_historiques")),
            )
    except RecuperationOuverturesHistoriquesRequise as exc:
        return _reponse_recuperation_ouvertures_historiques(exc)
    except ValidationError as exc:
        return JsonResponse({"error": _message_validation(exc)}, status=400)

    queryset = centre.ouvertures_periodes.select_related(
        "periode_calendrier", "modalite_periscolaire", "accueil_centre", "accueil_centre__type_accueil"
    ).filter(periode_calendrier=reference, accueil_centre=accueil, actif=True)
    return JsonResponse({"ok": True, "ouvertures": [_ouverture_to_dict(item) for item in queryset]})


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
    """Valide le calendrier scolaire commun, sans lui imposer un créneau.

    Les modalités sont configurées ensuite centre par centre. Cela évite de
    dupliquer les mêmes semaines pour le matin, le midi et le soir.
    """

    code = str(payload.get("type_accueil", TypeAccueil.PERISCOLAIRE)).strip()
    if code == TypeAccueil.MERCREDIS:
        code = TypeAccueil.PERISCOLAIRE
    if code != TypeAccueil.PERISCOLAIRE:
        raise ValidationError("Le calendrier scolaire est rattaché au Périscolaire.")
    try:
        return TypeAccueil.objects.get(code=TypeAccueil.PERISCOLAIRE, actif=True)
    except TypeAccueil.DoesNotExist as exc:
        raise ValidationError("Le type Périscolaire n'est pas disponible.") from exc


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


def _rattacher_periode_groupes_permanents(periode, type_accueil=None):
    """Ajoute une nouvelle semaine uniquement aux groupes du même accueil.

    Les instances modernes utilisent ``AccueilCentre`` comme source de vérité.
    Le repli M2M est limité aux anciennes instances qui n'ont pas encore
    d'``AccueilCentre`` afin de ne jamais contaminer l'autre accueil.
    """

    type_accueil = type_accueil or periode.type_accueil
    groupes = groupes_visibles(
        Evenement.objects.filter(permanent=True).filter(
            Q(accueil_centre__type_accueil=type_accueil)
            | Q(accueil_centre__isnull=True, types_accueil=type_accueil)
        )
    ).only("id")
    for groupe in groupes:
        groupe.periodes_scolaires.add(periode)


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
                _rattacher_periode_groupes_permanents(periode, periode.type_accueil)
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
                _rattacher_periode_groupes_permanents(periode, type_accueil)
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
        type_accueil = _contexte_periscolaire_requis(payload)
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
                    },
                )
                champs = []
                if travail.periode_calendrier_id is None:
                    travail.periode_calendrier = reference
                    champs.append("periode_calendrier")
                if travail.type_accueil_id is None:
                    travail.type_accueil = type_accueil
                    champs.append("type_accueil")
                if champs:
                    travail.save(update_fields=champs)
                travail.types_accueil.add(type_accueil)
                # Le calendrier est une référence commune : aucune modalité
                # n'est attachée ici. Les créneaux sont définis par centre.
                _rattacher_periode_groupes_permanents(travail, type_accueil)
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
