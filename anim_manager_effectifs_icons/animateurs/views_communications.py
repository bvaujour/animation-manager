"""Endpoints consacrés aux modèles, contacts et envois d’e-mails."""

import json
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError, IntegrityError
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import (
    Animateur,
    ContactEmailExterne,
    Document,
    ModeleEmail,
    PeriodeScolaire,
    Qualification,
)
from .services.emails import (
    ConfigurationEmailError,
    PiecesJointesError,
    charger_pieces_jointes,
    connexion_email,
    envoyer_un_message,
    rendre_variables_email,
    statut_configuration_email,
    variables_email_disponibles,
)
from .services.serializers import document_to_dict


def _taille_document(document):
    try:
        return int(document.fichier.size)
    except (OSError, TypeError, ValueError):
        return None






def _modele_email_to_dict(modele):
    return {
        "id": modele.id,
        "nom": modele.nom,
        "objet": modele.objet,
        "message": modele.message,
        "actif": modele.actif,
        "ordre": modele.ordre,
        "date_creation": modele.date_creation.isoformat(),
        "date_modification": modele.date_modification.isoformat(),
    }


def _lire_modele_email(request, *, instance=None):
    """Valide les champs reçus pour créer ou modifier un modèle d’e-mail."""

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None, JsonResponse({"error": "JSON invalide."}, status=400)

    nom = str(payload.get("nom", "")).strip()
    objet = str(payload.get("objet", "")).strip()
    message = str(payload.get("message", "")).strip()
    actif = payload.get("actif", True if instance is None else instance.actif)

    if not nom:
        return None, JsonResponse({"error": "Le nom du modèle est obligatoire."}, status=400)
    if len(nom) > 120:
        return None, JsonResponse({"error": "Le nom ne peut pas dépasser 120 caractères."}, status=400)
    if not objet:
        return None, JsonResponse({"error": "L’objet du modèle est obligatoire."}, status=400)
    if len(objet) > 200:
        return None, JsonResponse({"error": "L’objet ne peut pas dépasser 200 caractères."}, status=400)
    if not message:
        return None, JsonResponse({"error": "Le message du modèle est obligatoire."}, status=400)
    if len(message) > 10000:
        return None, JsonResponse({"error": "Le message du modèle est trop long."}, status=400)
    if not isinstance(actif, bool):
        return None, JsonResponse({"error": "Le statut actif du modèle est invalide."}, status=400)

    doublon = ModeleEmail.objects.filter(nom__iexact=nom)
    if instance is not None:
        doublon = doublon.exclude(pk=instance.pk)
    if doublon.exists():
        return None, JsonResponse({"error": "Un modèle porte déjà ce nom."}, status=409)

    return {
        "nom": nom,
        "objet": objet,
        "message": message,
        "actif": actif,
    }, None


@require_http_methods(["GET", "POST"])
def api_modeles_email(request):
    """Liste et crée les modèles d’e-mail gérés depuis l’application."""

    if request.method == "GET":
        # Les modèles sont facultatifs. Sur une installation où la migration
        # correspondante n'a pas encore été exécutée, on conserve malgré tout
        # l'éditeur d'e-mail et ses variables de base.
        try:
            modeles = [_modele_email_to_dict(modele) for modele in ModeleEmail.objects.all()]
        except DatabaseError:
            modeles = []
        return JsonResponse({
            "modeles": modeles,
            "variables": variables_email_disponibles(),
        })

    donnees, erreur = _lire_modele_email(request)
    if erreur:
        return erreur

    try:
        modele = ModeleEmail.objects.create(**donnees)
    except IntegrityError:
        return JsonResponse({"error": "Un modèle porte déjà ce nom."}, status=409)

    return JsonResponse(_modele_email_to_dict(modele), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_modele_email_detail(request, modele_id):
    """Modifie, active/désactive ou supprime un modèle d’e-mail."""

    try:
        modele = ModeleEmail.objects.get(pk=modele_id)
    except ModeleEmail.DoesNotExist:
        return JsonResponse({"error": "Modèle d’e-mail introuvable."}, status=404)

    if request.method == "DELETE":
        modele.delete()
        return HttpResponse(status=204)

    donnees, erreur = _lire_modele_email(request, instance=modele)
    if erreur:
        return erreur

    for champ, valeur in donnees.items():
        setattr(modele, champ, valeur)
    try:
        modele.save(update_fields=[*donnees.keys(), "date_modification"])
    except IntegrityError:
        return JsonResponse({"error": "Un modèle porte déjà ce nom."}, status=409)

    return JsonResponse(_modele_email_to_dict(modele))


def _contact_email_to_dict(contact):
    return {
        "id": contact.id,
        "prenom": contact.prenom,
        "nom": contact.nom,
        "email": contact.email,
        "organisation": contact.organisation,
        "actif": contact.actif,
    }


def _periode_email_to_dict(periode):
    """Décompose une semaine pour le sélecteur Année > Vacances > Semaine."""

    nom = str(periode.nom or "").strip()
    correspondance = re.match(
        r"^(?P<vacances>.*?)(?:\s*[—–-]\s*)?(?P<semaine>Semaine\s+.+)$",
        nom,
        flags=re.IGNORECASE,
    )
    if correspondance and correspondance.group("vacances").strip():
        vacances = correspondance.group("vacances").strip()
        semaine = correspondance.group("semaine").strip()
    else:
        vacances = nom or "Autres périodes"
        semaine = f"Du {periode.debut:%d/%m/%Y} au {periode.fin:%d/%m/%Y}"
    return {
        "id": periode.id,
        "nom": periode.nom,
        "libelle": periode.libelle_avec_annee,
        "debut": periode.debut.isoformat(),
        "fin": periode.fin.isoformat(),
        "est_actuelle": periode.debut <= timezone.localdate() <= periode.fin,
        "annee_scolaire": periode.annee_scolaire,
        "vacances": vacances,
        "semaine": semaine,
    }


def _lire_contact_email(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None, JsonResponse({"error": "JSON invalide."}, status=400)
    prenom = str(payload.get("prenom", "")).strip()
    nom = str(payload.get("nom", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    organisation = str(payload.get("organisation", "")).strip()
    actif = bool(payload.get("actif", True))
    if not nom:
        return None, JsonResponse({"error": "Le nom du contact est obligatoire."}, status=400)
    try:
        validate_email(email)
    except ValidationError:
        return None, JsonResponse({"error": "L’adresse e-mail est invalide."}, status=400)
    return {"prenom": prenom, "nom": nom, "email": email, "organisation": organisation, "actif": actif}, None


@require_http_methods(["GET", "POST"])
def api_contacts_email(request):
    if request.method == "GET":
        return JsonResponse({"contacts": [_contact_email_to_dict(c) for c in ContactEmailExterne.objects.all()]})
    donnees, erreur = _lire_contact_email(request)
    if erreur:
        return erreur
    try:
        contact = ContactEmailExterne.objects.create(**donnees)
    except IntegrityError:
        return JsonResponse({"error": "Cette adresse e-mail est déjà enregistrée parmi les contacts externes."}, status=409)
    return JsonResponse(_contact_email_to_dict(contact), status=201)


@require_http_methods(["PATCH", "DELETE"])
def api_contact_email_detail(request, contact_id):
    try:
        contact = ContactEmailExterne.objects.get(pk=contact_id)
    except ContactEmailExterne.DoesNotExist:
        return JsonResponse({"error": "Contact introuvable."}, status=404)
    if request.method == "DELETE":
        contact.delete()
        return JsonResponse({"ok": True})
    donnees, erreur = _lire_contact_email(request)
    if erreur:
        return erreur
    for champ, valeur in donnees.items():
        setattr(contact, champ, valeur)
    try:
        contact.save()
    except IntegrityError:
        return JsonResponse({"error": "Cette adresse e-mail est déjà enregistrée parmi les contacts externes."}, status=409)
    return JsonResponse(_contact_email_to_dict(contact))


@require_http_methods(["GET", "POST"])
def api_envois_email(request):
    """Prépare et exécute les envois sans conserver leur contenu en base."""

    if request.method == "GET":
        animateurs = list(
            Animateur.objects.all()
            .prefetch_related("qualifications", "preferences__centre", "disponibilites", "affectations")
        )
        animateurs.sort(key=lambda a: (a.prenom.casefold(), a.nom.casefold(), a.pk))
        documents_qs = list(Document.objects.prefetch_related("periodes").all())
        qualifications = list(Qualification.objects.filter(est_statut=False).order_by("nom", "id"))
        return JsonResponse({
            "configuration": statut_configuration_email(),
            "contacts_externes": [_contact_email_to_dict(contact) for contact in ContactEmailExterne.objects.filter(actif=True)],
            "periodes": [
                _periode_email_to_dict(periode)
                for periode in PeriodeScolaire.objects.order_by("debut", "ordre", "nom")
            ],
            "qualifications": [
                {"id": qualification.id, "nom": qualification.nom}
                for qualification in qualifications
            ],
            "animateurs": [
                {
                    "id": animateur.id,
                    "prenom": animateur.prenom,
                    "nom": animateur.nom,
                    "email": animateur.email,
                    "qualifications": [q.nom for q in animateur.qualifications.all()],
                    "qualification_ids": [q.id for q in animateur.qualifications.all()],
                    "lieux": [pref.centre.nom for pref in animateur.preferences.all()],
                    "centre_prefere": next((
                        {"id": pref.centre_id, "nom": pref.centre.nom, "code": pref.centre.code}
                        for pref in animateur.preferences.all() if pref.est_prefere
                    ), None),
                    "disponibilites": [
                        {"debut": disponibilite.debut.isoformat(), "fin": disponibilite.fin.isoformat()}
                        for disponibilite in animateur.disponibilites.all()
                    ],
                    "affectations": [
                        {"debut": affectation.debut.isoformat(), "fin": affectation.fin.isoformat()}
                        for affectation in animateur.affectations.all()
                    ],
                }
                for animateur in animateurs
            ],
            "documents": [
                {
                    **document_to_dict(document),
                    "taille": _taille_document(document),
                }
                for document in documents_qs
            ],
            # Les modèles sont chargés par leur API dédiée. La clé vide est
            # conservée pour compatibilité, sans requête vers leur table.
            "modeles": [],
            "variables": variables_email_disponibles(),
        })

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide."}, status=400)

    objet = str(payload.get("objet", "")).strip()
    message = str(payload.get("message", "")).strip()
    animateur_ids = payload.get("animateur_ids", [])
    contact_ids = payload.get("contact_ids", [])
    document_ids = payload.get("document_ids", [])
    periode_ids_bruts = payload.get("periode_ids")
    if periode_ids_bruts is None:
        # Compatibilité avec les anciennes versions de l'interface.
        periode_id_legacy = payload.get("periode_id")
        periode_ids_bruts = [] if periode_id_legacy in (None, "") else [periode_id_legacy]
    if not isinstance(periode_ids_bruts, list):
        return JsonResponse({"error": "La sélection des semaines est invalide."}, status=400)
    try:
        periode_ids = list(dict.fromkeys(int(value) for value in periode_ids_bruts))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection des semaines est invalide."}, status=400)
    semaines_reference = list(
        PeriodeScolaire.objects.filter(pk__in=periode_ids).order_by("debut", "ordre", "nom")
    )
    if len(semaines_reference) != len(periode_ids):
        return JsonResponse({"error": "Une ou plusieurs semaines sélectionnées sont invalides."}, status=400)

    if not objet:
        return JsonResponse({"error": "L'objet de l'e-mail est obligatoire."}, status=400)
    if len(objet) > 200:
        return JsonResponse({"error": "L'objet ne peut pas dépasser 200 caractères."}, status=400)
    if not message:
        return JsonResponse({"error": "Le message est obligatoire."}, status=400)
    if len(message) > 10000:
        return JsonResponse({"error": "Le message est trop long."}, status=400)
    if not isinstance(animateur_ids, list) or not isinstance(contact_ids, list) or not (animateur_ids or contact_ids):
        return JsonResponse({"error": "Choisis au moins un destinataire."}, status=400)
    if not isinstance(document_ids, list):
        return JsonResponse({"error": "La sélection de documents est invalide."}, status=400)

    try:
        ids_animateurs = list(dict.fromkeys(int(value) for value in animateur_ids))
        ids_contacts = list(dict.fromkeys(int(value) for value in contact_ids))
        ids_documents = list(dict.fromkeys(int(value) for value in document_ids))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection contient un identifiant invalide."}, status=400)

    if len(ids_animateurs) + len(ids_contacts) > 250:
        return JsonResponse({"error": "Un envoi est limité à 250 destinataires."}, status=400)

    animateurs = list(
        Animateur.objects.filter(pk__in=ids_animateurs)
        .prefetch_related("qualifications", "preferences__centre")
    )
    contacts = list(ContactEmailExterne.objects.filter(pk__in=ids_contacts, actif=True))
    documents_selectionnes = list(Document.objects.filter(pk__in=ids_documents))
    animateurs.sort(key=lambda a: (a.prenom.casefold(), a.nom.casefold(), a.pk))

    if len(animateurs) != len(ids_animateurs):
        return JsonResponse({"error": "Un ou plusieurs salariés n'existent plus."}, status=400)
    if len(contacts) != len(ids_contacts):
        return JsonResponse({"error": "Un ou plusieurs contacts externes n'existent plus ou sont inactifs."}, status=400)
    if len(documents_selectionnes) != len(ids_documents):
        return JsonResponse({"error": "Un ou plusieurs documents n'existent plus."}, status=400)

    destinataires = [
        {"type": "salarie", "id": a.id, "objet": a, "animateur": a, "contact": None}
        for a in animateurs
    ] + [
        {"type": "contact", "id": c.id, "objet": c, "animateur": None, "contact": c}
        for c in contacts
    ]

    adresses_invalides = []
    for item in destinataires:
        personne = item["objet"]
        try:
            validate_email(personne.email)
        except ValidationError:
            adresses_invalides.append(f"{personne.prenom} {personne.nom}".strip())
    if adresses_invalides:
        return JsonResponse({"error": "Adresse e-mail absente ou invalide pour : " + ", ".join(adresses_invalides) + "."}, status=400)

    emails_utilises = {}
    for item in destinataires:
        personne = item["objet"]
        cle_email = personne.email.strip().casefold()
        emails_utilises.setdefault(cle_email, []).append(f"{personne.prenom} {personne.nom}".strip())
    doublons_email = [noms for noms in emails_utilises.values() if len(noms) > 1]
    if doublons_email:
        groupes = [" / ".join(noms) for noms in doublons_email]
        return JsonResponse({"error": "Une même adresse e-mail est sélectionnée plusieurs fois : " + "; ".join(groupes) + "."}, status=400)

    configuration = statut_configuration_email()
    if not configuration["operationnel"]:
        return JsonResponse({"error": configuration["message"]}, status=503)

    try:
        pieces = charger_pieces_jointes(documents_selectionnes)
    except PiecesJointesError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    resultats = []
    envoyes = 0
    echecs = 0
    try:
        with connexion_email() as connection:
            for item in destinataires:
                personne = item["objet"]
                objet_rendu = rendre_variables_email(objet, personne, semaines_reference).strip()
                message_rendu = rendre_variables_email(message, personne, semaines_reference).strip()
                try:
                    envoyer_un_message(
                        animateur=personne,
                        objet=objet_rendu,
                        message=message_rendu,
                        pieces=pieces,
                        connection=connection,
                        semaine_reference=semaines_reference,
                    )
                    statut = "envoye"
                    erreur_detail = ""
                    envoyes += 1
                except Exception as exc:
                    statut = "echec"
                    erreur_detail = str(exc)[:1000] or "Erreur d'envoi inconnue."
                    echecs += 1
                resultats.append({
                    "type": item["type"],
                    "id": item["id"],
                    "nom": f"{personne.prenom} {personne.nom}".strip(),
                    "email": personne.email,
                    "statut": statut,
                    "erreur": erreur_detail,
                })
    except ConfigurationEmailError as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except Exception as exc:
        deja_traites = {(r["type"], r["id"]) for r in resultats}
        erreur_connexion = str(exc)[:1000] or "Connexion au serveur e-mail impossible."
        for item in destinataires:
            if (item["type"], item["id"]) in deja_traites:
                continue
            personne = item["objet"]
            resultats.append({
                "type": item["type"],
                "id": item["id"],
                "nom": f"{personne.prenom} {personne.nom}".strip(),
                "email": personne.email,
                "statut": "echec",
                "erreur": erreur_connexion,
            })
            echecs += 1

    return JsonResponse({
        "ok": echecs == 0,
        "mode_test": configuration["mode_test"],
        "nombre_envoyes": envoyes,
        "nombre_echecs": echecs,
        "resultats": resultats,
    })

@require_http_methods(["GET", "POST"])
def api_emails_animateur(request, animateur_id):
    """Envoie directement un e-mail à un salarié, sans historique persistant."""

    try:
        animateur = (
            Animateur.objects.prefetch_related("qualifications", "preferences__centre")
            .get(pk=animateur_id)
        )
    except Animateur.DoesNotExist:
        return JsonResponse({"error": "Salarié introuvable."}, status=404)

    if request.method == "GET":
        documents_qs = list(Document.objects.prefetch_related("periodes").all())
        return JsonResponse({
            "configuration": statut_configuration_email(),
            "destinataire": animateur.email,
            "documents": [
                {
                    **document_to_dict(document),
                    "taille": _taille_document(document),
                }
                for document in documents_qs
            ],
            # Les modèles sont chargés par leur API dédiée. La clé vide est
            # conservée pour compatibilité, sans requête vers leur table.
            "modeles": [],
            "variables": variables_email_disponibles(),
        })

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide."}, status=400)

    objet = str(payload.get("objet", "")).strip()
    message = str(payload.get("message", "")).strip()
    document_ids = payload.get("document_ids", [])
    semaine_reference = None

    if not objet:
        return JsonResponse({"error": "L'objet de l'e-mail est obligatoire."}, status=400)
    if len(objet) > 200:
        return JsonResponse({"error": "L'objet ne peut pas dépasser 200 caractères."}, status=400)
    if not message:
        return JsonResponse({"error": "Le message est obligatoire."}, status=400)
    if len(message) > 10000:
        return JsonResponse({"error": "Le message est trop long."}, status=400)
    if not isinstance(document_ids, list):
        return JsonResponse({"error": "La sélection de documents est invalide."}, status=400)

    try:
        validate_email(animateur.email)
    except ValidationError:
        return JsonResponse({"error": "Ce salarié n'a pas d'adresse e-mail valide."}, status=400)

    try:
        ids_documents = list(dict.fromkeys(int(value) for value in document_ids))
    except (TypeError, ValueError):
        return JsonResponse({"error": "La sélection contient un document invalide."}, status=400)

    documents_selectionnes = list(Document.objects.filter(pk__in=ids_documents))
    if len(documents_selectionnes) != len(ids_documents):
        return JsonResponse({"error": "Un ou plusieurs documents n'existent plus."}, status=400)

    variables_supplementaires = {
        "identifiant": animateur.utilisateur.username if animateur.utilisateur_id else "Non disponible",
        "lien_connexion": request.build_absolute_uri("/connexion/"),
    }
    identifiants_provisoires = payload.get("identifiants_provisoires")
    if identifiants_provisoires is not None:
        if not isinstance(identifiants_provisoires, dict):
            return JsonResponse({"error": "Les identifiants provisoires sont invalides."}, status=400)
        username = str(identifiants_provisoires.get("username", "")).strip()
        temporary_password = str(identifiants_provisoires.get("temporary_password", "")).strip()
        if not animateur.utilisateur_id or username != animateur.utilisateur.username:
            return JsonResponse({"error": "L’identifiant provisoire ne correspond pas au compte du salarié."}, status=400)
        if not animateur.doit_changer_mot_de_passe or not temporary_password or len(temporary_password) > 200:
            return JsonResponse({"error": "Le mot de passe provisoire n’est plus disponible. Réinitialise-le avant l’envoi."}, status=400)
        variables_supplementaires["mot_de_passe_provisoire"] = temporary_password
    else:
        variables_supplementaires["mot_de_passe_provisoire"] = "[réinitialisation nécessaire]"

    configuration = statut_configuration_email()
    if not configuration["operationnel"]:
        return JsonResponse({"error": configuration["message"]}, status=503)

    try:
        pieces = charger_pieces_jointes(documents_selectionnes)
    except PiecesJointesError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    objet_rendu = rendre_variables_email(objet, animateur, semaine_reference, variables_supplementaires).strip()
    message_rendu = rendre_variables_email(message, animateur, semaine_reference, variables_supplementaires).strip()
    try:
        with connexion_email() as connection:
            envoyer_un_message(
                animateur=animateur,
                objet=objet_rendu,
                message=message_rendu,
                pieces=pieces,
                connection=connection,
                semaine_reference=semaine_reference,
                variables_supplementaires=variables_supplementaires,
            )
    except Exception as exc:
        return JsonResponse({
            "error": str(exc)[:1000] or "Erreur d'envoi inconnue.",
            "statut": "echec",
        }, status=502)

    return JsonResponse({
        "ok": True,
        "statut": "envoye",
        "mode_test": configuration["mode_test"],
    })
