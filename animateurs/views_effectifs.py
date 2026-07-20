"""Endpoint de saisie et de lecture des effectifs enfants."""

import json

from django.db import transaction
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import EffectifEnfantsJour, Evenement

@never_cache
@require_http_methods(["GET", "POST"])
def api_effectifs_enfants_groupe(request, evenement_id):
    """Lit ou enregistre les effectifs et exceptions d’encadrement d’un groupe."""
    try:
        evenement = Evenement.objects.get(pk=evenement_id)
    except Evenement.DoesNotExist:
        return JsonResponse({"error": "Groupe introuvable."}, status=404)

    if request.method == "GET":
        debut = parse_date(request.GET.get("debut", ""))
        fin = parse_date(request.GET.get("fin", ""))
        queryset = evenement.effectifs_enfants.all()
        if debut:
            queryset = queryset.filter(date__gte=debut)
        if fin:
            queryset = queryset.filter(date__lt=fin)
        return JsonResponse(
            [
                {
                    "date": item.date.isoformat(),
                    "nombre": item.nombre,
                    "enfants_par_animateur": item.ratio_encadrement_effectif,
                    "ratio_encadrement_exceptionnel": item.ratio_encadrement_exceptionnel,
                }
                for item in queryset
            ],
            safe=False,
        )

    try:
        payload = json.loads(request.body)
        effectifs = payload.get("effectifs")
        ratios = payload.get("ratios_encadrement")

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

        if effectifs is None and ratios is None:
            raise ValueError
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
        return JsonResponse({"error": "Les données transmises sont invalides."}, status=400)

    with transaction.atomic():
        for jour, nombre in normalises_effectifs:
            ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour).first()
            if nombre == 0:
                if ligne and ligne.ratio_encadrement_exceptionnel:
                    ligne.nombre = 0
                    ligne.enfants_par_animateur = ligne.ratio_encadrement_effectif
                    ligne.save(update_fields=["nombre", "enfants_par_animateur", "modifie_le"])
                elif ligne:
                    ligne.delete()
            else:
                ratio = ligne.ratio_encadrement_effectif if ligne else evenement.enfants_par_animateur_defaut
                EffectifEnfantsJour.objects.update_or_create(
                    evenement=evenement,
                    date=jour,
                    defaults={"nombre": nombre, "enfants_par_animateur": ratio},
                )

        for jour, ratio in normalises_ratios:
            ligne = EffectifEnfantsJour.objects.filter(evenement=evenement, date=jour).first()
            if ratio is None:
                if ligne:
                    ligne.ratio_encadrement_exceptionnel = None
                    ligne.enfants_par_animateur = evenement.enfants_par_animateur_defaut
                    if ligne.nombre == 0:
                        ligne.delete()
                    else:
                        ligne.save(update_fields=[
                            "ratio_encadrement_exceptionnel",
                            "enfants_par_animateur",
                            "modifie_le",
                        ])
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
    return JsonResponse({"ok": True})
