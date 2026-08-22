"""Endpoint de saisie et de lecture des effectifs enfants."""

import json
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .access import est_direction
from .models import EffectifEnfantsJour, Evenement, ModalitePeriscolaire, TypeAccueil
from .services.accueils import valider_contexte_accueil
from .services.effectifs import enregistrer_nombre_effectif, ratio_encadrement_contexte
from .services.affectations import _ouverture_periscolaire_pour_date
from .services.flottants import est_groupe_flottants, groupes_partages_visibles, groupes_visibles


def _contexte_effectifs(request, payload=None, *, exiger_modalite=False):
    payload = payload or {}
    code = str(
        payload.get("type_accueil")
        or request.GET.get("type_accueil")
        or request.session.get("type_accueil", "")
    ).strip()
    if code == TypeAccueil.MERCREDIS:
        code = TypeAccueil.PERISCOLAIRE
    type_accueil = None
    if code in (TypeAccueil.VACANCES, TypeAccueil.PERISCOLAIRE):
        type_accueil = TypeAccueil.objects.filter(code=code, actif=True).first()

    code_modalite = str(
        payload.get("modalite_periscolaire")
        or request.GET.get("modalite_periscolaire")
        or ""
    ).strip()
    modalite = None
    if code_modalite:
        modalite = ModalitePeriscolaire.objects.filter(code=code_modalite, actif=True).first()
        if modalite is None:
            raise ValueError("Créneau périscolaire invalide.")
    if exiger_modalite and type_accueil and type_accueil.code == TypeAccueil.PERISCOLAIRE and modalite is None:
        raise ValueError("Choisissez un créneau périscolaire avant de saisir les effectifs.")
    if type_accueil is None or type_accueil.code != TypeAccueil.PERISCOLAIRE:
        modalite = None
    return type_accueil, modalite




def _filtrer_effectifs_contexte(queryset, type_accueil, modalite):
    """Applique un contexte sans confondre les anciennes lignes journalières.

    Les enregistrements historiques sans ``type_accueil`` et sans modalité
    restent assimilés aux Vacances. En Périscolaire, une ligne générique sans
    modalité ne doit jamais apparaître comme un effectif du matin/midi/soir.
    """

    if type_accueil is None:
        return queryset
    if type_accueil.code == TypeAccueil.PERISCOLAIRE:
        queryset = queryset.filter(
            Q(type_accueil=type_accueil)
            | Q(type_accueil__isnull=True, modalite_periscolaire__isnull=False)
        )
        if modalite is not None:
            queryset = queryset.filter(modalite_periscolaire=modalite)
        return queryset
    return queryset.filter(
        Q(type_accueil=type_accueil) | Q(type_accueil__isnull=True),
        modalite_periscolaire__isnull=True,
    )

def _effectif_to_dict(item, *, inclure_groupe=False):
    data = {
        "date": item.date.isoformat(),
        "nombre": item.nombre,
        "enfants_par_animateur": item.ratio_encadrement_effectif,
        "ratio_encadrement_exceptionnel": item.ratio_encadrement_exceptionnel,
        "heure_arrivee": item.heure_arrivee.strftime("%H:%M") if item.heure_arrivee else "",
        "heure_depart": item.heure_depart.strftime("%H:%M") if item.heure_depart else "",
        "type_accueil": item.type_accueil.code if item.type_accueil_id else None,
        "modalite_periscolaire": item.modalite_periscolaire.code if item.modalite_periscolaire_id else None,
        "modalite_periscolaire_nom": item.modalite_periscolaire.nom if item.modalite_periscolaire_id else None,
    }
    if inclure_groupe:
        data["groupe_id"] = item.evenement_id
    return data


@never_cache
@require_http_methods(["GET"])
def api_effectifs_enfants_plage(request):
    """Renvoie en une requête les effectifs de tous les groupes sur une plage."""

    debut = parse_date(request.GET.get("debut", ""))
    fin = parse_date(request.GET.get("fin", ""))
    if not debut or not fin or fin <= debut:
        return JsonResponse({"error": "La plage debut/fin est invalide."}, status=400)

    queryset = (
        EffectifEnfantsJour.objects.select_related("evenement", "type_accueil", "modalite_periscolaire")
        .filter(date__gte=debut, date__lt=fin)
        .only(
            "evenement_id",
            "evenement__enfants_par_animateur_defaut",
            "date",
            "nombre",
            "enfants_par_animateur",
            "ratio_encadrement_exceptionnel",
            "heure_arrivee",
            "heure_depart",
            "type_accueil_id",
            "type_accueil__code",
            "modalite_periscolaire_id",
            "modalite_periscolaire__code",
            "modalite_periscolaire__nom",
        )
        .order_by("evenement_id", "date", "modalite_periscolaire_id")
    )
    try:
        type_accueil, modalite = _contexte_effectifs(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    queryset = _filtrer_effectifs_contexte(queryset, type_accueil, modalite)
    direction = est_direction(request.user)
    if not direction:
        animateur = getattr(request.user, "profil_animateur", None)
        if animateur is None:
            queryset = queryset.none()
        else:
            # Le lieu visible dépend de la semaine demandée : une ancienne
            # affectation dans un autre centre ne doit pas exposer ses effectifs.
            debut_dt = timezone.make_aware(datetime.combine(debut, datetime.min.time()))
            fin_dt = timezone.make_aware(datetime.combine(fin, datetime.min.time()))
            centre_ids = animateur.affectations.filter(
                debut__lt=fin_dt,
                fin__gt=debut_dt,
            ).values_list("centre_id", flat=True).distinct()
            queryset = queryset.filter(evenement__centre_id__in=centre_ids)

    lignes = [_effectif_to_dict(item, inclure_groupe=True) for item in queryset]

    # Le Planning Direction a besoin du ratio de référence même avant la
    # première saisie d'enfants. Cet enrichissement est volontairement opt-in
    # afin de ne pas modifier le contrat historique de l'API pour les autres
    # écrans : les lignes virtuelles ne sont jamais enregistrées en base.
    inclure_references = direction and request.GET.get("inclure_references") == "1"
    if inclure_references:
        existantes = {(int(item["groupe_id"]), item["date"]) for item in lignes}
        groupes = list(
            groupes_visibles(
                Evenement.objects.select_related(
                    "centre", "groupe", "accueil_centre", "accueil_centre__type_accueil"
                ).prefetch_related("periodes_scolaires", "dates_exclues", "types_accueil")
            )
        )
        if type_accueil is not None:
            groupes = [
                groupe for groupe in groupes
                if not groupe.types_accueil.all() or type_accueil in groupe.types_accueil.all()
            ]
        jour = debut
        while jour < fin:
            date_iso = jour.isoformat()
            for groupe in groupes:
                cle = (groupe.id, date_iso)
                if cle in existantes or not groupe.est_ouvert_le(jour):
                    continue
                if (
                    type_accueil is not None
                    and type_accueil.code == TypeAccueil.PERISCOLAIRE
                    and modalite is not None
                ):
                    ouvert, _debut, _fin = _ouverture_periscolaire_pour_date(
                        groupe.centre,
                        jour,
                        modalite,
                        groupe.accueil_centre,
                    )
                    if not ouvert:
                        continue
                ratio = ratio_encadrement_contexte(
                    groupe,
                    jour,
                    type_accueil=type_accueil,
                    modalite_periscolaire=modalite,
                )
                lignes.append({
                    "groupe_id": groupe.id,
                    "date": date_iso,
                    "nombre": 0,
                    "enfants_par_animateur": ratio,
                    "ratio_encadrement_exceptionnel": None,
                    "heure_arrivee": "",
                    "heure_depart": "",
                    "type_accueil": type_accueil.code if type_accueil else None,
                    "modalite_periscolaire": modalite.code if modalite else None,
                    "modalite_periscolaire_nom": modalite.nom if modalite else None,
                    "virtuel": True,
                })
            jour += timedelta(days=1)
        lignes.sort(key=lambda item: (int(item["groupe_id"]), item["date"], item.get("modalite_periscolaire") or ""))

    return JsonResponse(lignes, safe=False)


@never_cache
@require_http_methods(["GET", "POST"])
def api_effectifs_enfants_groupe(request, evenement_id):
    """Lit ou enregistre les effectifs et exceptions d’encadrement d’un groupe."""
    try:
        evenement = Evenement.objects.select_related(
            "groupe", "centre", "accueil_centre", "accueil_centre__type_accueil"
        ).get(pk=evenement_id)
        if est_groupe_flottants(evenement):
            raise Evenement.DoesNotExist
    except Evenement.DoesNotExist:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)

    if request.method == "GET":
        debut = parse_date(request.GET.get("debut", ""))
        fin = parse_date(request.GET.get("fin", ""))
        queryset = evenement.effectifs_enfants.select_related("evenement", "type_accueil", "modalite_periscolaire")
        try:
            type_accueil, modalite = _contexte_effectifs(request)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        queryset = _filtrer_effectifs_contexte(queryset, type_accueil, modalite)
        if debut:
            queryset = queryset.filter(date__gte=debut)
        if fin:
            queryset = queryset.filter(date__lt=fin)
        return JsonResponse(
            [_effectif_to_dict(item) for item in queryset],
            safe=False,
        )

    try:
        payload = json.loads(request.body)
        type_accueil, modalite = _contexte_effectifs(request, payload, exiger_modalite=True)
        effectifs = payload.get("effectifs")
        ratios = payload.get("ratios_encadrement")
        horaires = payload.get("horaires")

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

        if horaires is not None:
            if not isinstance(horaires, list):
                raise ValueError
            normalises_horaires = []
            for valeur in horaires:
                jour = parse_date(str(valeur.get("date", "")))
                arrivee_brute = valeur.get("heure_arrivee", "")
                depart_brut = valeur.get("heure_depart", "")
                arrivee = parse_time(arrivee_brute) if arrivee_brute else None
                depart = parse_time(depart_brut) if depart_brut else None
                if not jour or (arrivee_brute and arrivee is None) or (depart_brut and depart is None):
                    raise ValueError
                if bool(arrivee) != bool(depart) or (arrivee and depart <= arrivee):
                    raise ValueError
                normalises_horaires.append((jour, arrivee, depart))
        else:
            normalises_horaires = []

        if effectifs is None and ratios is None and horaires is None:
            raise ValueError

        # Validation centrale : AccueilCentre est la source de vérité pour les
        # nouvelles instances. Un type contradictoire est refusé côté serveur.
        type_accueil = valider_contexte_accueil(evenement, type_accueil, modalite)

        dates_modifiees = {jour for jour, _nombre in normalises_effectifs}
        dates_modifiees.update(jour for jour, _ratio in normalises_ratios)
        dates_modifiees.update(jour for jour, _arrivee, _depart in normalises_horaires)
        dates_exclues = set(evenement.dates_exclues.values_list("date", flat=True))
        for jour in dates_modifiees:
            if not evenement.est_ouvert_le(jour, dates_exclues):
                raise ValueError
            if type_accueil and type_accueil.code == TypeAccueil.PERISCOLAIRE:
                ouvert, _heure_debut, _heure_fin = _ouverture_periscolaire_pour_date(
                    evenement.centre,
                    jour,
                    modalite,
                    evenement.accueil_centre,
                )
                if not ouvert:
                    raise ValueError
    except (TypeError, ValueError, AttributeError, ValidationError, json.JSONDecodeError):
        return JsonResponse({"error": "Les données transmises sont invalides ou le groupe est fermé dans cet accueil à cette date."}, status=400)

    with transaction.atomic():
        for jour, nombre in normalises_effectifs:
            enregistrer_nombre_effectif(evenement, jour, nombre, type_accueil=type_accueil, modalite_periscolaire=modalite)

        for jour, ratio in normalises_ratios:
            ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour, modalite_periscolaire=modalite).first()
            if ratio is None:
                if ligne:
                    ligne.ratio_encadrement_exceptionnel = None
                    ligne.enfants_par_animateur = ratio_encadrement_contexte(
                        evenement,
                        jour,
                        type_accueil=type_accueil,
                        modalite_periscolaire=modalite,
                    )
                    if ligne.nombre == 0 and not ligne.heure_arrivee:
                        ligne.delete()
                    else:
                        ligne.save(
                            update_fields=[
                                "ratio_encadrement_exceptionnel",
                                "enfants_par_animateur",
                                "modifie_le",
                            ]
                        )
            else:
                EffectifEnfantsJour.objects.update_or_create(
                    evenement=evenement,
                    date=jour,
                    modalite_periscolaire=modalite,
                    defaults={
                        "nombre": ligne.nombre if ligne else 0,
                        "enfants_par_animateur": ratio,
                        "ratio_encadrement_exceptionnel": ratio,
                        "type_accueil": type_accueil,
                    },
                )

        for jour, arrivee, depart in normalises_horaires:
            ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour, modalite_periscolaire=modalite).first()
            if arrivee is None:
                if ligne:
                    ligne.heure_arrivee = None
                    ligne.heure_depart = None
                    if ligne.nombre == 0 and not ligne.ratio_encadrement_exceptionnel:
                        ligne.delete()
                    else:
                        ligne.save(update_fields=["heure_arrivee", "heure_depart", "modifie_le"])
            else:
                EffectifEnfantsJour.objects.update_or_create(
                    evenement=evenement,
                    date=jour,
                    modalite_periscolaire=modalite,
                    defaults={
                        "nombre": ligne.nombre if ligne else 0,
                        "enfants_par_animateur": (
                            ligne.ratio_encadrement_effectif
                            if ligne and ligne.ratio_encadrement_exceptionnel
                            else ratio_encadrement_contexte(
                                evenement,
                                jour,
                                type_accueil=type_accueil,
                                modalite_periscolaire=modalite,
                            )
                        ),
                        "ratio_encadrement_exceptionnel": (ligne.ratio_encadrement_exceptionnel if ligne else None),
                        "heure_arrivee": arrivee,
                        "heure_depart": depart,
                        "type_accueil": type_accueil,
                    },
                )
    return JsonResponse({"ok": True})


def _excel_indisponible_en_periscolaire(request):
    """Protège l'import historique tant qu'il n'est pas ventilé par créneau.

    Le classeur Vacances est indexé par groupe + date. En Périscolaire, cette
    clé est insuffisante puisqu'un même groupe peut avoir matin, midi et soir
    le même jour. On préfère donc bloquer explicitement cette fonction plutôt
    que d'écraser ou mélanger des effectifs entre créneaux.
    """
    code = str(
        request.GET.get("type_accueil")
        or request.POST.get("type_accueil")
        or request.session.get("type_accueil", "")
    ).strip()
    return code in (TypeAccueil.PERISCOLAIRE, TypeAccueil.MERCREDIS)


def _reponse_excel_periscolaire():
    return JsonResponse(
        {
            "error": (
                "L’import Excel des effectifs reste disponible pour les Vacances. "
                "En Périscolaire, saisissez les effectifs directement par créneau."
            )
        },
        status=400,
    )


def _catalogue_import_excel(request):
    from .models import Centre, Groupe, ProfilImportEffectifs

    return {
        "centres": [
            {"id": centre.id, "nom": centre.nom, "code": centre.code}
            for centre in Centre.objects.all().order_by("ordre", "nom")
        ],
        "groupes": [
            {"id": groupe.id, "nom": groupe.nom}
            for groupe in groupes_partages_visibles(Groupe.objects.all()).order_by("nom")
        ],
        "profiles": [
            {"id": profil.id, "nom": profil.nom, "configuration": profil.configuration}
            for profil in ProfilImportEffectifs.objects.filter(utilisateur=request.user)
        ],
    }


@never_cache
@require_http_methods(["GET"])
def api_effectifs_excel_gabarit(request):
    """Génère un gabarit .xlsx multi-lieux pour une plage de dates."""
    if _excel_indisponible_en_periscolaire(request):
        return _reponse_excel_periscolaire()
    from django.http import HttpResponse

    from .services.effectifs_excel import ErreurExcel, generer_gabarit_excel

    debut = parse_date(request.GET.get("debut", ""))
    fin = parse_date(request.GET.get("fin", ""))
    centre_brut = request.GET.getlist("centre") or request.GET.get("centres", "").split(",")
    try:
        centre_ids = sorted({int(item) for item in centre_brut if str(item).strip()})
        if not debut or not fin:
            raise ErreurExcel("Choisissez une date de début et une date de fin.")
        contenu = generer_gabarit_excel(centre_ids, debut, fin)
    except (TypeError, ValueError, ErreurExcel) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    nom = f"effectifs_{debut:%Y%m%d}_{fin:%Y%m%d}.xlsx"
    response = HttpResponse(
        contenu,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{nom}"'
    response["Cache-Control"] = "no-store"
    return response


@never_cache
@require_http_methods(["POST"])
def api_effectifs_excel_analyser(request):
    """Détecte feuilles, en-têtes et valeurs d'un fichier Excel externe."""
    if _excel_indisponible_en_periscolaire(request):
        return _reponse_excel_periscolaire()
    from .services.effectifs_excel import ErreurExcel, analyser_classeur

    fichier = request.FILES.get("fichier")
    if not fichier:
        return JsonResponse({"error": "Choisissez un fichier Excel .xlsx."}, status=400)
    try:
        resultat = analyser_classeur(fichier)
    except ErreurExcel as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    resultat.update(_catalogue_import_excel(request))
    return JsonResponse(resultat)


@never_cache
@require_http_methods(["POST"])
def api_effectifs_excel_previsualiser(request):
    """Normalise un classeur sans modifier la base et renvoie l'aperçu."""
    if _excel_indisponible_en_periscolaire(request):
        return _reponse_excel_periscolaire()
    from .services.effectifs_excel import ErreurExcel, previsualiser_classeur

    fichier = request.FILES.get("fichier")
    if not fichier:
        return JsonResponse({"error": "Choisissez un fichier Excel .xlsx."}, status=400)
    configuration = None
    brut = request.POST.get("configuration", "").strip()
    if brut:
        try:
            configuration = json.loads(brut)
        except json.JSONDecodeError:
            return JsonResponse({"error": "La correspondance des colonnes est invalide."}, status=400)
    try:
        resultat = previsualiser_classeur(fichier, configuration)
    except ErreurExcel as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(resultat)


@never_cache
@require_http_methods(["POST"])
def api_effectifs_excel_importer(request):
    """Valide l'aperçu sélectionné et enregistre les effectifs."""
    if _excel_indisponible_en_periscolaire(request):
        return _reponse_excel_periscolaire()
    try:
        payload = json.loads(request.body)
        lignes = payload.get("rows")
        if not isinstance(lignes, list) or not lignes or len(lignes) > 5000:
            raise ValueError
        normalisees = []
        cles = set()
        for ligne in lignes:
            evenement_id = int(ligne.get("evenement_id"))
            jour = parse_date(str(ligne.get("date", "")))
            nombre = int(ligne.get("importe"))
            if not jour or nombre < 0 or nombre > 999 or (evenement_id, jour) in cles:
                raise ValueError
            cles.add((evenement_id, jour))
            normalisees.append((evenement_id, jour, nombre))
    except (TypeError, ValueError, AttributeError, ValidationError, json.JSONDecodeError):
        return JsonResponse({"error": "Les lignes à importer sont invalides."}, status=400)

    evenements = {
        item.id: item
        for item in groupes_visibles(Evenement.objects.filter(id__in=[item[0] for item in normalisees])).select_related("groupe")
    }
    if len(evenements) != len({item[0] for item in normalisees}):
        return JsonResponse({"error": "Un groupe de l'aperçu n'existe plus."}, status=409)

    bilan = {"created": 0, "updated": 0, "deleted": 0, "unchanged": 0}
    with transaction.atomic():
        for evenement_id, jour, nombre in normalisees:
            statut = enregistrer_nombre_effectif(evenements[evenement_id], jour, nombre)
            bilan[statut] += 1
    # Le client peut importer plusieurs semaines dans un seul classeur. On
    # renvoie les semaines réellement touchées afin qu'il puisse invalider et
    # précharger chacune d'elles immédiatement, sans attendre une navigation
    # ou un rafraîchissement manuel de la page.
    semaines = sorted({jour - timedelta(days=jour.weekday()) for _, jour, _ in normalisees})
    periodes = [
        {
            "debut": lundi.isoformat(),
            "fin": (lundi + timedelta(days=7)).isoformat(),
        }
        for lundi in semaines
    ]
    return JsonResponse({"ok": True, "count": len(normalisees), "periodes": periodes, **bilan})


@never_cache
@require_http_methods(["GET", "POST"])
def api_profils_import_effectifs(request):
    """Liste ou enregistre les profils de correspondance Excel de l'utilisateur."""
    from django.db import IntegrityError

    from .models import ProfilImportEffectifs

    if request.method == "GET":
        return JsonResponse([
            {"id": profil.id, "nom": profil.nom, "configuration": profil.configuration}
            for profil in ProfilImportEffectifs.objects.filter(utilisateur=request.user)
        ], safe=False)

    try:
        payload = json.loads(request.body)
        nom = str(payload.get("nom", "")).strip()
        configuration = payload.get("configuration")
        if not nom or len(nom) > 120 or not isinstance(configuration, dict):
            raise ValueError
        profil_id = payload.get("id")
        if profil_id:
            profil = ProfilImportEffectifs.objects.get(pk=int(profil_id), utilisateur=request.user)
            profil.nom = nom
            profil.configuration = configuration
            profil.save()
            statut = 200
        else:
            profil = ProfilImportEffectifs.objects.create(
                utilisateur=request.user,
                nom=nom,
                configuration=configuration,
            )
            statut = 201
    except ProfilImportEffectifs.DoesNotExist:
        return JsonResponse({"error": "Profil introuvable."}, status=404)
    except IntegrityError:
        return JsonResponse({"error": "Un profil porte déjà ce nom."}, status=409)
    except (TypeError, ValueError, AttributeError, ValidationError, json.JSONDecodeError):
        return JsonResponse({"error": "Le nom et la configuration du profil sont obligatoires."}, status=400)
    return JsonResponse({"id": profil.id, "nom": profil.nom, "configuration": profil.configuration}, status=statut)


@never_cache
@require_http_methods(["DELETE"])
def api_profil_import_effectifs_detail(request, profil_id):
    from .models import ProfilImportEffectifs

    supprime, _ = ProfilImportEffectifs.objects.filter(pk=profil_id, utilisateur=request.user).delete()
    if not supprime:
        return JsonResponse({"error": "Profil introuvable."}, status=404)
    return JsonResponse({"ok": True})
