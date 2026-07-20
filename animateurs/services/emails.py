"""Services d'envoi d'e-mails aux salariés avec pièces jointes.

Chaque destinataire reçoit un message séparé afin que les adresses des autres
salariés ne soient jamais exposées. Les documents sont lus une seule fois puis
réutilisés pour tous les messages de l'envoi.
"""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils import timezone
from django.utils.html import escape, linebreaks



MAX_PIECES_JOINTES_OCTETS = 18 * 1024 * 1024
VARIABLES_EMAIL = (
    ("prenom", "Prénom"),
    ("nom", "Nom"),
    ("nom_semaine", "Vacances et période de la sélection"),
    ("date_debut_semaine", "Date de début de la sélection"),
    ("date_fin_semaine", "Date de fin de la sélection"),
    ("affectations_semaine", "Lieu, groupe et date des affectations sélectionnées"),
)
VARIABLE_EMAIL_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


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


def variables_email_disponibles() -> list[dict]:
    """Variables proposées dans l'interface de rédaction."""

    return [
        {"nom": nom, "code": "{{" + nom + "}}", "libelle": libelle}
        for nom, libelle in VARIABLES_EMAIL
    ]


JOURS_SEMAINE_FR = (
    "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche",
)


def _date_locale(valeur):
    """Retourne la date locale d'un datetime Django, qu'il soit naïf ou aware."""

    if timezone.is_aware(valeur):
        valeur = timezone.localtime(valeur)
    return valeur.date()


def _normaliser_semaines_reference(semaine_reference) -> list:
    """Accepte une semaine unique ou une collection et renvoie une liste triée."""

    if semaine_reference is None:
        return []
    if isinstance(semaine_reference, (list, tuple, set)):
        semaines = [semaine for semaine in semaine_reference if semaine is not None]
    else:
        semaines = [semaine_reference]
    return sorted(
        semaines,
        key=lambda semaine: (semaine.debut, semaine.fin, getattr(semaine, "pk", 0) or 0),
    )


def _nom_vacances(semaine) -> str:
    """Extrait le nom des vacances depuis « Été — Semaine 2 »."""

    nom = str(getattr(semaine, "nom", "") or "").strip()
    correspondance = re.match(
        r"^(?P<vacances>.*?)(?:\s*[—–-]\s*)?Semaine\s+.+$",
        nom,
        flags=re.IGNORECASE,
    )
    if correspondance and correspondance.group("vacances").strip():
        return correspondance.group("vacances").strip()
    return nom or "Période"


def _libelle_semaines(semaines) -> str:
    """Décrit les vacances et les bornes de chaque période sélectionnée.

    Deux semaines consécutives des mêmes vacances sont regroupées dans une
    seule période. Deux semaines non consécutives restent présentées
    séparément afin de ne pas laisser croire que les dates intermédiaires ont
    également été sélectionnées.
    """

    if not semaines:
        return ""

    groupes = []
    for semaine in semaines:
        vacances = _nom_vacances(semaine)
        annee_scolaire = str(getattr(semaine, "annee_scolaire", "") or "")
        cle = (annee_scolaire, vacances.casefold())
        if (
            groupes
            and groupes[-1]["cle"] == cle
            and semaine.debut <= groupes[-1]["fin"] + timedelta(days=3)
        ):
            groupes[-1]["fin"] = max(groupes[-1]["fin"], semaine.fin)
            continue
        groupes.append({
            "cle": cle,
            "vacances": vacances,
            "debut": semaine.debut,
            "fin": semaine.fin,
        })

    return " ; ".join(
        f"{groupe['vacances']} — période du {groupe['debut']:%d/%m/%Y} "
        f"au {groupe['fin']:%d/%m/%Y}"
        for groupe in groupes
    )


def _affectations_semaine(animateur, semaine_reference) -> str:
    """Liste chaque journée affectée dans toutes les semaines sélectionnées.

    Une affectation couvrant plusieurs jours produit une ligne par journée. Les
    contacts externes, qui n'ont pas de planning, obtiennent une valeur vide.
    """

    semaines = _normaliser_semaines_reference(semaine_reference)
    if not semaines or not hasattr(animateur, "affectations"):
        return ""

    debut_selection = min(semaine.debut for semaine in semaines)
    fin_selection = max(semaine.fin for semaine in semaines)
    affectations = (
        animateur.affectations
        .filter(debut__date__lte=fin_selection, fin__date__gt=debut_selection)
        .select_related("centre", "evenement")
        .order_by("debut", "centre__ordre", "evenement__ordre", "pk")
    )
    lignes = []
    deja_vues = set()
    for affectation in affectations:
        premier_jour = max(_date_locale(affectation.debut), debut_selection)
        # `fin` est exclusive : on retire une microseconde pour retrouver le
        # dernier jour réellement couvert par l'affectation.
        dernier_jour = min(
            _date_locale(affectation.fin - timedelta(microseconds=1)),
            fin_selection,
        )
        jour = premier_jour
        while jour <= dernier_jour:
            jour_selectionne = any(
                semaine.debut <= jour <= semaine.fin for semaine in semaines
            )
            cle = (jour, affectation.centre_id, affectation.evenement_id)
            if jour_selectionne and cle not in deja_vues:
                deja_vues.add(cle)
                lignes.append(
                    f"{JOURS_SEMAINE_FR[jour.weekday()]} {jour:%d/%m/%Y} — "
                    f"{affectation.centre.nom} — {affectation.evenement.nom}"
                )
            jour += timedelta(days=1)
    return "\n".join(lignes)


def _valeurs_variables_email(animateur, semaine_reference=None, variables_supplementaires=None) -> dict[str, str]:
    """Construit les valeurs propres au destinataire et aux semaines choisies."""

    valeurs = {
        "prenom": str(animateur.prenom or "").strip(),
        "nom": str(animateur.nom or "").strip(),
    }
    semaines = _normaliser_semaines_reference(semaine_reference)
    if semaines:
        valeurs.update({
            "nom_semaine": _libelle_semaines(semaines),
            "date_debut_semaine": min(semaine.debut for semaine in semaines).strftime("%d/%m/%Y"),
            "date_fin_semaine": max(semaine.fin for semaine in semaines).strftime("%d/%m/%Y"),
            "affectations_semaine": _affectations_semaine(animateur, semaines),
        })
    if variables_supplementaires:
        valeurs.update({str(cle): str(valeur) for cle, valeur in variables_supplementaires.items()})
    return valeurs


def rendre_variables_email(texte: str, animateur, semaine_reference=None, variables_supplementaires=None) -> str:
    """Remplace les variables connues et laisse les marqueurs inconnus inchangés."""

    valeurs = _valeurs_variables_email(animateur, semaine_reference, variables_supplementaires)
    return VARIABLE_EMAIL_RE.sub(
        lambda match: valeurs.get(match.group(1), match.group(0)),
        str(texte or ""),
    )

def _corps_html(message: str) -> str:
    """Version HTML fidèle au texte saisi, sans salutation ni signature."""

    return (
        '<div style="font-family:Arial,sans-serif;line-height:1.55;color:#1e2a22">'
        f"{linebreaks(escape(message))}</div>"
    )


def envoyer_un_message(*, animateur, objet: str, message: str, pieces: list[PieceJointe], connection, semaine_reference=None, variables_supplementaires=None) -> tuple[str, str]:
    """Personnalise puis envoie un message individuel à un salarié."""

    objet_rendu = rendre_variables_email(objet, animateur, semaine_reference, variables_supplementaires).strip()
    message_rendu = rendre_variables_email(message, animateur, semaine_reference, variables_supplementaires).strip()
    if len(objet_rendu) > 200:
        raise ValueError("L'objet personnalisé dépasse 200 caractères.")

    reply_to = [settings.EMAIL_REPLY_TO] if settings.EMAIL_REPLY_TO else None
    texte = message_rendu
    email = EmailMultiAlternatives(
        subject=objet_rendu,
        body=texte,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[animateur.email],
        reply_to=reply_to,
        connection=connection,
    )
    email.attach_alternative(_corps_html(message_rendu), "text/html")
    for piece in pieces:
        email.attach(piece.nom, piece.contenu, piece.type_mime)
    nombre_envoye = email.send(fail_silently=False)
    if nombre_envoye != 1:
        raise RuntimeError(f"Le backend e-mail a retourné {nombre_envoye} message envoyé au lieu de 1.")
    return objet_rendu, message_rendu


def connexion_email():
    """Ouvre une connexion réutilisable pour un envoi groupé."""

    statut = statut_configuration_email()
    if not statut["operationnel"]:
        raise ConfigurationEmailError(statut["message"])
    return get_connection(fail_silently=False)
