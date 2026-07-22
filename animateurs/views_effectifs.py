"""Endpoint de saisie et de lecture des effectifs enfants."""

import json
from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import EffectifEnfantsJour, Evenement
from .services.effectifs import enregistrer_nombre_effectif
from .services.flottants import est_groupe_flottants, groupes_partages_visibles, groupes_visibles


def _effectif_to_dict(item, *, inclure_groupe=False):
    data = {
        "date": item.date.isoformat(),
        "nombre": item.nombre,
        "enfants_par_animateur": item.ratio_encadrement_effectif,
        "ratio_encadrement_exceptionnel": item.ratio_encadrement_exceptionnel,
        "heure_arrivee": item.heure_arrivee.strftime("%H:%M") if item.heure_arrivee else "",
        "heure_depart": item.heure_depart.strftime("%H:%M") if item.heure_depart else "",
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
        EffectifEnfantsJour.objects.select_related("evenement")
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
        )
        .order_by("evenement_id", "date")
    )
    return JsonResponse(
        [_effectif_to_dict(item, inclure_groupe=True) for item in queryset],
        safe=False,
    )


@never_cache
@require_http_methods(["GET", "POST"])
def api_effectifs_enfants_groupe(request, evenement_id):
    """Lit ou enregistre les effectifs et exceptions d’encadrement d’un groupe."""
    try:
        evenement = Evenement.objects.select_related("groupe").get(pk=evenement_id)
        if est_groupe_flottants(evenement):
            raise Evenement.DoesNotExist
    except Evenement.DoesNotExist:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)

    if request.method == "GET":
        debut = parse_date(request.GET.get("debut", ""))
        fin = parse_date(request.GET.get("fin", ""))
        queryset = evenement.effectifs_enfants.select_related("evenement")
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
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Les données transmises sont invalides."}, status=400)

    with transaction.atomic():
        for jour, nombre in normalises_effectifs:
            enregistrer_nombre_effectif(evenement, jour, nombre)

        for jour, ratio in normalises_ratios:
            ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour).first()
            if ratio is None:
                if ligne:
                    ligne.ratio_encadrement_exceptionnel = None
                    ligne.enfants_par_animateur = evenement.enfants_par_animateur_defaut
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
                    defaults={
                        "nombre": ligne.nombre if ligne else 0,
                        "enfants_par_animateur": ratio,
                        "ratio_encadrement_exceptionnel": ratio,
                    },
                )

        for jour, arrivee, depart in normalises_horaires:
            ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour).first()
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
                    defaults={
                        "nombre": ligne.nombre if ligne else 0,
                        "enfants_par_animateur": (
                            ligne.ratio_encadrement_effectif if ligne else evenement.enfants_par_animateur_defaut
                        ),
                        "ratio_encadrement_exceptionnel": (ligne.ratio_encadrement_exceptionnel if ligne else None),
                        "heure_arrivee": arrivee,
                        "heure_depart": depart,
                    },
                )
    return JsonResponse({"ok": True})


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
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
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
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
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
