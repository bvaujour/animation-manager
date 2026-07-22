"""Création, synchronisation et validation des comptes de connexion."""

import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from animateurs.models import Animateur


def valider_mot_de_passe(mot_de_passe, *, utilisateur=None):
    """Retourne le premier message de validation Django, ou une chaîne vide."""
    try:
        validate_password(mot_de_passe, user=utilisateur)
    except ValidationError as exc:
        return exc.messages[0]
    return ""


def nom_utilisateur_disponible(prenom, nom):
    user_model = get_user_model()
    base = (slugify(f"{prenom}.{nom}") or "utilisateur")[:140]
    candidat = base
    numero = 2
    while user_model.objects.filter(username=candidat).exists():
        suffixe = f".{numero}"
        candidat = f"{base[:150 - len(suffixe)]}{suffixe}"
        numero += 1
    return candidat


def mot_de_passe_provisoire():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(14))


def synchroniser_droits_compte(animateur):
    """Un compte lié à un salarié est toujours un compte ordinaire."""
    utilisateur = animateur.utilisateur
    if utilisateur is None:
        return
    utilisateur.email = animateur.email or utilisateur.email
    utilisateur.first_name = animateur.prenom
    utilisateur.last_name = animateur.nom
    utilisateur.is_staff = False
    utilisateur.is_superuser = False
    utilisateur.save(update_fields=["email", "first_name", "last_name", "is_staff", "is_superuser"])


def creer_compte_animateur(animateur):
    if animateur.utilisateur_id:
        return None
    user_model = get_user_model()
    mot_de_passe = mot_de_passe_provisoire()
    utilisateur = user_model.objects.create_user(
        username=nom_utilisateur_disponible(animateur.prenom, animateur.nom),
        email=animateur.email,
        password=mot_de_passe,
        first_name=animateur.prenom,
        last_name=animateur.nom,
    )
    animateur.utilisateur = utilisateur
    animateur.doit_changer_mot_de_passe = True
    animateur.save(update_fields=["utilisateur", "doit_changer_mot_de_passe"])
    synchroniser_droits_compte(animateur)
    return {"username": utilisateur.username, "temporary_password": mot_de_passe}


def traiter_acces_compte(animateur, payload):
    """Applique les actions demandées et renvoie les identifiants temporaires."""
    if animateur.role != Animateur.ROLE_ANIMATEUR:
        animateur.role = Animateur.ROLE_ANIMATEUR
        animateur.save(update_fields=["role"])

    identifiants = None
    if payload.get("create_access") and not animateur.utilisateur_id:
        identifiants = creer_compte_animateur(animateur)

    if payload.get("remove_access") and animateur.utilisateur_id:
        utilisateur = animateur.utilisateur
        animateur.utilisateur = None
        animateur.save(update_fields=["utilisateur"])
        utilisateur.delete()
        return None

    if animateur.utilisateur_id:
        utilisateur = animateur.utilisateur
        if "access_active" in payload:
            utilisateur.is_active = bool(payload.get("access_active"))
            utilisateur.save(update_fields=["is_active"])
        synchroniser_droits_compte(animateur)
        if payload.get("reset_password"):
            mot_de_passe = mot_de_passe_provisoire()
            utilisateur.set_password(mot_de_passe)
            utilisateur.save(update_fields=["password"])
            animateur.doit_changer_mot_de_passe = True
            animateur.save(update_fields=["doit_changer_mot_de_passe"])
            identifiants = {"username": utilisateur.username, "temporary_password": mot_de_passe}
    return identifiants
