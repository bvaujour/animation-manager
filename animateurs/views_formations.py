"""Page et API de gestion autonome des formations."""

import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from .models import (
    Animateur,
    Document,
    Formation,
    HistoriqueStatutAnimateur,
    ParticipationFormation,
    Qualification,
    normaliser_cle_unique,
)
from .services.formations import conflits_formation


def formations(request):
    return render(request, "formations.html", {"active_page": "formations"})


def _formation_queryset():
    return Formation.objects.select_related("qualification").prefetch_related(
        "documents", "participations__animateur"
    )


def _document_dict(document):
    return {
        "id": document.id,
        "titre": document.titre,
        "url": document.fichier.url if document.fichier else "",
        "publie": document.publie,
    }


def _formation_dict(formation):
    statut_effectif = formation.statut_effectif
    participations = list(formation.participations.all())
    conflits = (
        conflits_formation(formation)
        if statut_effectif in (Formation.STATUT_PREVUE, Formation.STATUT_EN_COURS)
        else []
    )
    for conflit in conflits:
        conflit["planning_url"] = (
            f"{reverse('planning')}?mode=affectations&date={conflit['date']}"
        )
    return {
        "id": formation.id,
        "intitule": formation.intitule,
        "date_debut": formation.date_debut.isoformat(),
        "date_fin": formation.date_fin.isoformat(),
        "organisme": formation.organisme,
        "email_contact": formation.email_contact,
        "telephone_contact": formation.telephone_contact,
        "lieu": formation.lieu,
        "hebergement": formation.hebergement,
        "hebergement_libelle": formation.get_hebergement_display(),
        "statut": statut_effectif,
        "statut_stocke": formation.statut,
        "statut_libelle": dict(Formation.STATUT_CHOICES)[statut_effectif],
        "qualification": (
            {"id": formation.qualification_id, "nom": formation.qualification.nom}
            if formation.qualification_id else None
        ),
        "qualification_libre": formation.qualification_libre,
        "documents": [_document_dict(document) for document in formation.documents.all()],
        "commentaire": formation.commentaire,
        "animateurs": [
            {
                "id": participation.animateur.id,
                "prenom": participation.animateur.prenom,
                "nom": participation.animateur.nom,
                "presence": participation.presence,
                "presence_libelle": participation.get_presence_display(),
            }
            for participation in participations
        ],
        "date_creation": formation.date_creation.isoformat(),
        "date_modification": formation.date_modification.isoformat(),
        "conflits": conflits,
    }


def _catalogues():
    return {
        "animateurs": [
            {"id": item.id, "prenom": item.prenom, "nom": item.nom}
            for item in Animateur.objects.order_by("nom", "prenom", "id")
        ],
        "qualifications": [
            {"id": item.id, "nom": item.nom}
            for item in Qualification.objects.order_by("nom", "id")
        ],
        "documents": [
            _document_dict(item)
            for item in Document.objects.order_by("titre", "id")
        ],
        "statuts": [
            {"value": Formation.STATUT_PREVUE, "label": "Active (statut selon les dates)"},
            {"value": Formation.STATUT_ANNULEE, "label": "Annulée"},
        ],
    }


def _payload(request):
    try:
        return json.loads(request.body or "{}")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError("Données invalides.") from exc


def _valider_payload(data, formation=None):
    intitule = str(data.get("intitule", formation.intitule if formation else "") or "").strip()
    date_debut = parse_date(str(data.get("date_debut", formation.date_debut if formation else "")))
    date_fin = parse_date(str(data.get("date_fin", formation.date_fin if formation else "")))
    statut = str(data.get("statut", formation.statut if formation else Formation.STATUT_PREVUE))
    if not intitule:
        raise ValidationError("L’intitulé est obligatoire.")
    if not date_debut or not date_fin:
        raise ValidationError("Les dates de début et de fin sont obligatoires.")
    if date_fin < date_debut:
        raise ValidationError("La date de fin ne peut pas être antérieure à la date de début.")
    if statut == Formation.STATUT_EN_COURS or statut == Formation.STATUT_A_CLOTURER:
        statut = Formation.STATUT_PREVUE
    if statut == Formation.STATUT_TERMINEE and (not formation or formation.statut != Formation.STATUT_TERMINEE):
        raise ValidationError("Une formation devient terminée uniquement après validation des présences.")
    if statut not in dict(Formation.STATUT_CHOICES):
        raise ValidationError("Le statut sélectionné est invalide.")

    try:
        animateur_ids = {int(value) for value in data.get("animateur_ids", [])}
    except (TypeError, ValueError):
        raise ValidationError("La sélection des animateurs est invalide.")
    animateurs = list(Animateur.objects.filter(id__in=animateur_ids).order_by("nom", "prenom"))
    if not animateur_ids or len(animateurs) != len(animateur_ids):
        raise ValidationError("Sélectionnez au moins un animateur valide.")

    qualification_id = data.get("qualification_id") or None
    qualification = None
    if qualification_id:
        try:
            qualification = Qualification.objects.get(pk=int(qualification_id))
        except (Qualification.DoesNotExist, TypeError, ValueError):
            raise ValidationError("La qualification sélectionnée est invalide.")

    try:
        document_ids = {int(value) for value in data.get("document_ids", [])}
    except (TypeError, ValueError):
        raise ValidationError("La sélection des documents est invalide.")
    documents = list(Document.objects.filter(id__in=document_ids).order_by("titre", "id"))
    if len(documents) != len(document_ids):
        raise ValidationError("Un document sélectionné est introuvable.")

    hebergement = str(data.get("hebergement", formation.hebergement if formation else "") or "")
    if hebergement not in {"", *dict(Formation.HEBERGEMENT_CHOICES)}:
        raise ValidationError("Le mode d’hébergement sélectionné est invalide.")

    return {
        "intitule": intitule,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "organisme": str(data.get("organisme", formation.organisme if formation else "") or "").strip(),
        "email_contact": str(data.get("email_contact", formation.email_contact if formation else "") or "").strip(),
        "telephone_contact": str(data.get("telephone_contact", formation.telephone_contact if formation else "") or "").strip(),
        "lieu": str(data.get("lieu", formation.lieu if formation else "") or "").strip(),
        "hebergement": hebergement,
        "statut": statut,
        "qualification": qualification,
        "qualification_libre": str(data.get("qualification_libre", formation.qualification_libre if formation else "") or "").strip(),
        "commentaire": str(data.get("commentaire", formation.commentaire if formation else "") or "").strip(),
        "animateurs": animateurs,
        "documents": documents,
    }


def _qualification_libre(formation):
    nom = formation.qualification_libre.strip()
    if not nom:
        return None
    qualification, _ = Qualification.objects.get_or_create(
        cle_unique=normaliser_cle_unique(nom),
        defaults={"nom": nom},
    )
    return qualification


def _attribuer_qualifications_presentes(formation, qualification_libre):
    qualifications = {
        item.id: item
        for item in (formation.qualification, qualification_libre)
        if item is not None
    }
    for participation in formation.participations.filter(
        presence=ParticipationFormation.PRESENCE_PRESENT
    ).select_related("animateur"):
        for qualification in qualifications.values():
            if qualification.est_statut:
                HistoriqueStatutAnimateur.objects.get_or_create(
                    animateur=participation.animateur,
                    date_effet=formation.date_fin,
                    defaults={
                        "statut": qualification,
                        "origine": HistoriqueStatutAnimateur.ORIGINE_FORMATION,
                        "commentaire": f"Formation — {formation.intitule}",
                    },
                )
            else:
                participation.animateur.qualifications.add(qualification)


def _enregistrer(formation, valeurs):
    animateurs = valeurs.pop("animateurs")
    documents = valeurs.pop("documents")
    for champ, valeur in valeurs.items():
        setattr(formation, champ, valeur)
    formation.full_clean()
    formation.save()
    formation.animateurs.set(animateurs)
    formation.documents.set(documents)
    _qualification_libre(formation)
    return _formation_queryset().get(pk=formation.pk)


@require_http_methods(["GET", "POST"])
def api_formations(request):
    if request.method == "POST":
        try:
            with transaction.atomic():
                formation = _enregistrer(Formation(), _valider_payload(_payload(request)))
            return JsonResponse(_formation_dict(formation), status=201)
        except ValidationError as exc:
            return JsonResponse({"error": " ".join(exc.messages)}, status=400)

    queryset = _formation_queryset()
    statut = request.GET.get("statut", "").strip()
    if statut:
        if statut not in dict(Formation.STATUT_CHOICES):
            return JsonResponse({"error": "Filtre de statut invalide."}, status=400)
    animateur_id = request.GET.get("animateur_id", "").strip()
    if animateur_id:
        try:
            queryset = queryset.filter(animateurs__id=int(animateur_id))
        except ValueError:
            return JsonResponse({"error": "Filtre animateur invalide."}, status=400)
    formations_liste = list(queryset.order_by("date_debut", "intitule", "id"))
    if statut:
        formations_liste = [item for item in formations_liste if item.statut_effectif == statut]
    ordre = {
        Formation.STATUT_EN_COURS: 0,
        Formation.STATUT_A_CLOTURER: 1,
        Formation.STATUT_PREVUE: 2,
        Formation.STATUT_TERMINEE: 3,
        Formation.STATUT_ANNULEE: 4,
    }
    formations_liste.sort(key=lambda item: (ordre[item.statut_effectif], item.date_debut, item.intitule, item.id))
    return JsonResponse({"formations": [_formation_dict(item) for item in formations_liste], **_catalogues()})


@require_http_methods(["GET", "PATCH", "DELETE"])
def api_formation_detail(request, formation_id):
    formation = get_object_or_404(_formation_queryset(), pk=formation_id)
    if request.method == "GET":
        return JsonResponse(_formation_dict(formation))
    if request.method == "DELETE":
        formation.delete()
        return JsonResponse({"ok": True})
    try:
        with transaction.atomic():
            formation = _enregistrer(formation, _valider_payload(_payload(request), formation))
        return JsonResponse(_formation_dict(formation))
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)


@require_http_methods(["POST"])
def api_formation_cloture(request, formation_id):
    formation = get_object_or_404(_formation_queryset(), pk=formation_id)
    if formation.statut_effectif != Formation.STATUT_A_CLOTURER:
        return JsonResponse({"error": "Cette formation n’est pas à clôturer."}, status=400)
    try:
        data = _payload(request)
        presences = {int(item["animateur_id"]): str(item["presence"]) for item in data.get("presences", [])}
    except (KeyError, TypeError, ValueError, ValidationError):
        return JsonResponse({"error": "Les présences sont invalides."}, status=400)
    participations = list(formation.participations.select_related("animateur"))
    ids_attendus = {item.animateur_id for item in participations}
    if set(presences) != ids_attendus or any(
        valeur not in (ParticipationFormation.PRESENCE_PRESENT, ParticipationFormation.PRESENCE_ABSENT)
        for valeur in presences.values()
    ):
        return JsonResponse({"error": "Confirmez la présence ou l’absence de chaque participant."}, status=400)
    with transaction.atomic():
        for participation in participations:
            participation.presence = presences[participation.animateur_id]
            participation.save(update_fields=["presence"])
        formation.statut = Formation.STATUT_TERMINEE
        formation.save(update_fields=["statut", "date_modification"])
        _attribuer_qualifications_presentes(formation, _qualification_libre(formation))
    return JsonResponse(_formation_dict(_formation_queryset().get(pk=formation.pk)))
