"""Services d'envoi d'e-mails.

La vue HTTP ne fait que valider la requête puis déléguer ici. Ce module
centralise la résolution des destinataires, les limites de pièces jointes
et l'appel au backend e-mail configuré dans Django.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email

from ..models import Animateur, Document

MAX_DESTINATAIRES = 100
MAX_DOCUMENTS = 10
MAX_TAILLE_PIECES_JOINTES = 20 * 1024 * 1024  # 20 Mo


@dataclass(frozen=True)
class ResultatEnvoi:
    destinataires: list[str]
    documents: list[str]
    backend_console: bool


def _normaliser_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email:
        raise ValueError("Une adresse e-mail est vide.")
    try:
        validate_email(email)
    except ValidationError as exc:
        raise ValueError(f"Adresse e-mail invalide : {email}") from exc
    return email


def resoudre_destinataires(*, animateur_ids, emails_manuels) -> list[str]:
    """Retourne une liste dédupliquée d'adresses valides."""
    destinataires: list[str] = []
    deja_vus: set[str] = set()

    ids = []
    for value in animateur_ids or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            raise ValueError("Identifiant d'animateur invalide.")

    for animateur in Animateur.objects.filter(pk__in=ids).only("email"):
        if not animateur.email:
            continue
        email = _normaliser_email(animateur.email)
        if email not in deja_vus:
            destinataires.append(email)
            deja_vus.add(email)

    for value in emails_manuels or []:
        email = _normaliser_email(value)
        if email not in deja_vus:
            destinataires.append(email)
            deja_vus.add(email)

    if not destinataires:
        raise ValueError("Ajoute au moins un destinataire avec une adresse e-mail valide.")
    if len(destinataires) > MAX_DESTINATAIRES:
        raise ValueError(f"Maximum {MAX_DESTINATAIRES} destinataires par envoi.")

    return destinataires


def _attacher_documents(message: EmailMessage, document_ids) -> list[str]:
    ids = []
    for value in document_ids or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            raise ValueError("Identifiant de document invalide.")

    ids = list(dict.fromkeys(ids))
    if len(ids) > MAX_DOCUMENTS:
        raise ValueError(f"Maximum {MAX_DOCUMENTS} documents par e-mail.")

    documents = list(Document.objects.filter(pk__in=ids))
    if len(documents) != len(ids):
        raise ValueError("Un des documents sélectionnés est introuvable.")

    total = 0
    titres = []
    for document in documents:
        document.fichier.open("rb")
        try:
            contenu = document.fichier.read()
        finally:
            document.fichier.close()

        total += len(contenu)
        if total > MAX_TAILLE_PIECES_JOINTES:
            raise ValueError("Les pièces jointes dépassent la limite totale de 20 Mo.")

        nom = document.fichier.name.rsplit("/", 1)[-1]
        mime_type, _ = mimetypes.guess_type(nom)
        message.attach(nom, contenu, mime_type or "application/octet-stream")
        titres.append(document.titre)

    return titres


def envoyer_email(*, animateur_ids, emails_manuels, sujet, corps, document_ids=None) -> ResultatEnvoi:
    sujet = str(sujet or "").strip()
    corps = str(corps or "").strip()
    if not sujet:
        raise ValueError("Le sujet est obligatoire.")
    if not corps:
        raise ValueError("Le message est obligatoire.")

    destinataires = resoudre_destinataires(
        animateur_ids=animateur_ids,
        emails_manuels=emails_manuels,
    )

    email = EmailMessage(
        subject=sujet,
        body=corps,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=destinataires,
        reply_to=[settings.EMAIL_REPLY_TO] if getattr(settings, "EMAIL_REPLY_TO", "") else None,
    )
    documents = _attacher_documents(email, document_ids)
    email.send(fail_silently=False)

    return ResultatEnvoi(
        destinataires=destinataires,
        documents=documents,
        backend_console=settings.EMAIL_BACKEND.endswith("console.EmailBackend"),
    )
