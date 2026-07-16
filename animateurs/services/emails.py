"""Services d'envoi d'e-mails aux salariés avec pièces jointes.

Chaque destinataire reçoit un message séparé afin que les adresses des autres
salariés ne soient jamais exposées. Les documents sont lus une seule fois puis
réutilisés pour tous les messages de l'envoi.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils.html import escape, linebreaks


MAX_PIECES_JOINTES_OCTETS = 18 * 1024 * 1024


@dataclass(frozen=True)
class PieceJointe:
    nom: str
    contenu: bytes
    type_mime: str


class ConfigurationEmailError(RuntimeError):
    """La configuration ne permet pas un vrai envoi en production."""


class PiecesJointesError(ValueError):
    """Les documents demandés ne peuvent pas être joints au message."""


def statut_configuration_email() -> dict:
    """Décrit le mode d'envoi actif pour l'affichage et les contrôles API."""

    backend = settings.EMAIL_BACKEND
    mode_test = backend.endswith("console.EmailBackend") or backend.endswith("locmem.EmailBackend")
    est_smtp = backend.endswith("smtp.EmailBackend")

    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        return {
            "operationnel": False,
            "mode_test": False,
            "message": "EMAIL_USE_TLS et EMAIL_USE_SSL ne peuvent pas être activés ensemble.",
        }

    if est_smtp and not settings.EMAIL_HOST:
        return {
            "operationnel": False,
            "mode_test": False,
            "message": "Le serveur SMTP n'est pas configuré.",
        }

    if backend.endswith("dummy.EmailBackend"):
        return {
            "operationnel": False,
            "mode_test": False,
            "message": "Le backend e-mail factice ne permet pas d'envoyer de messages.",
        }

    if mode_test and not settings.DEBUG:
        return {
            "operationnel": False,
            "mode_test": True,
            "message": "L'envoi de test ne peut pas être utilisé en production.",
        }

    return {
        "operationnel": True,
        "mode_test": mode_test,
        "message": (
            "Mode test : les messages sont interceptés localement."
            if mode_test
            else "Configuration e-mail opérationnelle."
        ),
    }


def charger_pieces_jointes(documents) -> list[PieceJointe]:
    """Charge les fichiers et applique une limite commune raisonnable.

    La limite de 18 Mio laisse de la marge pour l'encodage MIME, les fournisseurs
    limitant souvent un message complet à environ 20-25 Mio.
    """

    pieces: list[PieceJointe] = []
    taille_totale = 0

    for document in documents:
        try:
            taille = int(document.fichier.size)
        except (OSError, ValueError, TypeError) as exc:
            raise PiecesJointesError(
                f'Impossible de déterminer la taille du document « {document.titre} ».'
            ) from exc

        taille_totale += taille
        if taille_totale > MAX_PIECES_JOINTES_OCTETS:
            raise PiecesJointesError(
                "Les pièces jointes dépassent 18 Mo au total. Retire un ou plusieurs documents."
            )

        try:
            with document.fichier.open("rb") as fichier:
                contenu = fichier.read()
        except (OSError, ValueError) as exc:
            raise PiecesJointesError(
                f'Impossible de lire le document « {document.titre} ».'
            ) from exc

        nom = Path(document.fichier.name).name
        type_mime = mimetypes.guess_type(nom)[0] or "application/octet-stream"
        pieces.append(PieceJointe(nom=nom, contenu=contenu, type_mime=type_mime))

    return pieces


def _corps_html(message: str, prenom: str) -> str:
    salutation = f"Bonjour {escape(prenom)}," if prenom else "Bonjour,"
    corps = linebreaks(escape(message))
    return (
        '<div style="font-family:Arial,sans-serif;line-height:1.55;color:#1e2a22">'
        f"<p>{salutation}</p>{corps}"
        '<p style="margin-top:24px;color:#5c6b60;font-size:13px">'
        "Ce message a été envoyé depuis l’application Gestion animation."
        "</p></div>"
    )


def envoyer_un_message(*, animateur, objet: str, message: str, pieces: list[PieceJointe], connection) -> None:
    """Envoie un message individuel à un salarié."""

    reply_to = [settings.EMAIL_REPLY_TO] if settings.EMAIL_REPLY_TO else None
    texte = f"Bonjour {animateur.prenom},\n\n{message}\n\nCe message a été envoyé depuis l’application Gestion animation."
    email = EmailMultiAlternatives(
        subject=objet,
        body=texte,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[animateur.email],
        reply_to=reply_to,
        connection=connection,
    )
    email.attach_alternative(_corps_html(message, animateur.prenom), "text/html")
    for piece in pieces:
        email.attach(piece.nom, piece.contenu, piece.type_mime)
    email.send(fail_silently=False)


def connexion_email():
    """Ouvre une connexion réutilisable pour un envoi groupé."""

    statut = statut_configuration_email()
    if not statut["operationnel"]:
        raise ConfigurationEmailError(statut["message"])
    return get_connection(fail_silently=False)
