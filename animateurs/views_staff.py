"""API des salariés et de leurs disponibilités."""

import datetime
import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from .models import (
    Affectation,
    AffiniteGroupeAnimateur,
    Animateur,
    Disponibilite,
    PeriodeScolaire,
    PreferenceCentre,
    Qualification,
    normaliser_cle_unique,
)
from .services.affinites import synchroniser_affinites_groupes
from .services.animateurs import (
    appliquer_centres_hierarchises,
    normaliser_centres_hierarchises,
    normaliser_evenement_preferee,
)
from .services.comptes import traiter_acces_compte
from .services.disponibilites import fusionner_et_nettoyer_disponibilites
from .services.serializers import animateur_planning_to_dict, animateur_to_dict
from .services.situation_semaine import jours_ouverts_planning, situation_animateur_semaine

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
