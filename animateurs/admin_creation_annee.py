import hashlib
import json
from datetime import date

from django.contrib import messages
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect, QueryDict
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse

from .forms_creation_annee import NouvelleAnneeForm, RepriseAnneeForm
from .models import AnneeScolaire
from .services.creation_annee import CATEGORIES, creer_annee, previsualiser_calendrier
from .services.multisite import multisite_actif


SALT = "assistant-annee-scolaire"


def donnees_formulaire(valeurs):
    data = QueryDict(mutable=True)
    for cle, valeurs_champ in valeurs.items():
        data.setlist(cle, valeurs_champ)
    return data


def empreinte(plan):
    if plan is None:
        return "vierge"
    sources = {code: [{champ.attname: getattr(obj, champ.attname) for champ in obj._meta.concrete_fields} for obj in objets]
               for code, objets in plan["lignes"].items()}
    sources["periodes"] = [{"id": p.pk, "nom": p.nom, "debut": p.debut, "fin": p.fin,
        "zone": p.zone, "categorie": p.categorie, "types": sorted(p.types_accueil.values_list("pk", flat=True))} for p in plan["periodes"]]
    # La confirmation doit aussi porter sur le calendrier effectivement affiché
    # et sur les seules semaines source susceptibles d'être rattachées.
    calendrier = plan.get("calendrier_officiel", {})
    sources["calendrier"] = {"zone": plan.get("zone"), "periodes": calendrier.get("periodes", []),
        "semaines": [s.to_dict() for s in calendrier.get("semaines", [])]}
    sources["semaines_ete"] = plan.get("semaines_ete", [])
    sources["periodes_scolaires"] = plan.get("periodes_scolaires", [])
    sources["vacances_courtes"] = plan.get("vacances_courtes", [])
    sources["rattachements"] = {e.pk: [
        {champ.attname: getattr(p, champ.attname) for champ in p._meta.concrete_fields}
        for p in e.periodes_scolaires.all() if p.annee_scolaire == plan["source_libelle"]
    ] for e in plan["evenements"]}
    return hashlib.sha256(json.dumps(sources, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()


def assistant(request, administration):
    if not administration.has_add_permission(request) or not administration.has_view_permission(request):
        raise PermissionDenied
    context = {**administration.admin_site.each_context(request), "opts": AnneeScolaire._meta,
               "title": "Créer une nouvelle année scolaire", "etape": "identite",
               "mode_multisite": multisite_actif()}
    derniere = AnneeScolaire.objects.order_by("-date_debut").first()
    initial = {"mode": "copie" if derniere else "vierge", "source": derniere}
    if derniere:
        debut = derniere.date_debut.year + 1
        initial.update(libelle=f"{debut}-{debut + 1}", date_debut=date(debut, 9, 1), date_fin=date(debut + 1, 8, 31), zone="A")
    form = NouvelleAnneeForm(initial=initial)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "continuer":
                donnees = {"identite": dict(request.POST.lists())}
            else:
                donnees = signing.loads(request.POST.get("jeton", ""), salt=SALT, max_age=7200)
            form = NouvelleAnneeForm(donnees_formulaire(donnees["identite"]))
            if form.is_valid():
                cible = form.instance
                source = form.cleaned_data.get("source")
                copie = form.cleaned_data["mode"] == "copie"
                context.update(cible=cible, source=source if copie else None)
                plan = None
                if copie:
                    options_data = request.POST if action == "previsualiser" else (
                        donnees_formulaire(donnees["options"]) if action == "creer" and "options" in donnees else None)
                    options = RepriseAnneeForm(options_data, cible=cible, source=source, zone=form.cleaned_data["zone"])
                    context.update(etape="options", options=options)
                    if options_data is not None and options.is_valid():
                        plan = options.plan
                        for code in plan["lignes"]:
                            if not request.user.has_perm(f"animateurs.add_{CATEGORIES[code][0]._meta.model_name}"):
                                raise PermissionDenied
                        if (plan["periodes"] or plan["calendrier_officiel"]["periodes"]) and not request.user.has_perm("animateurs.add_periodecalendrier"):
                            raise PermissionDenied
                        donnees["options"] = dict(options_data.lists())
                    else:
                        context["jeton"] = signing.dumps(donnees, salt=SALT, compress=True)
                        context["form"] = form
                        return TemplateResponse(request, "admin/animateurs/anneescolaire/assistant.html", context)
                if action == "creer":
                    if not donnees.get("confirme") or donnees.get("empreinte") != empreinte(plan):
                        raise ValidationError("La configuration source a changé ou la prévisualisation manque. Recommencez l’assistant.")
                    with transaction.atomic():
                        creer_annee(cible, plan)
                        administration.log_addition(request, cible, "Création par l’assistant")
                    administration.message_user(request, f"L’année scolaire {cible.libelle} a été créée en mode PREPARATION.", messages.SUCCESS)
                    rapport = signing.dumps({"id": cible.pk, "resume": plan["resume"] if plan else []}, salt=SALT)
                    from urllib.parse import urlencode
                    return HttpResponseRedirect(reverse("admin:animateurs_anneescolaire_configuration", args=[cible.pk]) + "?" + urlencode({"rapport": rapport}))
                donnees.update(confirme=True, empreinte=empreinte(plan))
                context.update(etape="preview", plan=plan,
                    calendrier_preview=previsualiser_calendrier(
                        cible, plan["zone"], plan["calendrier_officiel"], plan["periodes_scolaires"],
                        plan["vacances_courtes"], plan["semaines_ete"]) if plan else None,
                    periodes_preview=[(p, *plan["dates"][p.pk]) for p in plan["periodes"]] if plan else [],
                    jeton=signing.dumps(donnees, salt=SALT, compress=True))
        except (signing.BadSignature, KeyError):
            context["erreur"] = "Assistant expiré ou invalide. Recommencez la saisie."
        except ValidationError as erreur:
            context["erreur"] = " ".join(erreur.messages)
            context["etape"] = "identite"
        except IntegrityError:
            context["erreur"] = "Création annulée : cette année ou une configuration cible existe déjà. Aucune donnée n’a été écrasée."
            context["etape"] = "identite"
    context["form"] = form
    return TemplateResponse(request, "admin/animateurs/anneescolaire/assistant.html", context)


def configuration(request, object_id, administration):
    annee = get_object_or_404(AnneeScolaire, pk=object_id)
    if not administration.has_view_permission(request, annee):
        raise PermissionDenied
    resume = []
    try:
        rapport = signing.loads(request.GET.get("rapport", ""), salt=SALT, max_age=7200)
        if rapport["id"] == annee.pk:
            resume = rapport["resume"]
    except (signing.BadSignature, KeyError):
        pass
    return TemplateResponse(request, "admin/animateurs/anneescolaire/configuration.html", {
        **administration.admin_site.each_context(request), "opts": AnneeScolaire._meta,
        "title": f"Configuration de {annee.libelle}", "annee": annee, "resume": resume,
    })
