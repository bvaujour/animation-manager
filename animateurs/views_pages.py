"""Pages HTML, tableau de bord et exports administratifs."""

import copy
import datetime
import json
import re
from base64 import urlsafe_b64decode

from django.contrib import messages
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import connection, transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache

from .access import est_direction, resoudre_portail_consulte
from .models import (
    Affectation,
    Animateur,
    AnneeScolaire,
    Centre,
    CampagneDisponibilite,
    CampagneDisponibiliteBloc,
    CampagneDisponibiliteDate,
    DestinatairePublicationAffectation,
    DemandeMateriel,
    DemandeDisponibilite,
    Evenement,
    InformationAnimateur,
    PeriodeScolaire,
    PeriodeCalendrier,
    PublicationAffectationsPeriode,
    PropositionDisponibiliteDate,
    ResponsabiliteOperationnelle,
    SignalementAffectationPublication,
    StatutPreparationSemaine,
    TypeAccueil,
)
from .services.animateur_dashboard import generer_tableau_de_bord_animateur
from .services.actions_equipe import (
    actions_actives_animateur, affectations_restent_a_confirmer, detail_legacy_indisponible,
    details_affectations_avec_statut, instantane_affectations, instantanes_affectations_equivalents,
    suivi_actions_affectations,
)
from .services.comptes import valider_mot_de_passe
from .services.dashboard import generer_tableau_de_bord
from .services.planning_exports import generer_planning_excel, generer_planning_pdf, horaires_manquants_export
from .services.demandes_disponibilites import (
    DemandeDisponibiliteIncomplete,
    cloturer_campagne,
    envoyer_demande,
    ouvrir_campagne,
)


PORTAIL_ANIMATEUR_SEMAINE_SESSION_KEY = "portail_animateur_semaine"


class ConnexionAnimateurView(LoginView):
    """Priorise les actions portail seulement après une connexion ordinaire."""

    template_name = "registration/login.html"

    def get_success_url(self):
        # LoginView valide déjà la destination ``next`` avant de la retourner.
        next_url = self.get_redirect_url()
        if next_url:
            return next_url
        animateur = Animateur.objects.filter(utilisateur=self.request.user).first()
        if animateur is not None and actions_actives_animateur(animateur):
            return reverse("actions_a_faire")
        return super().get_success_url()


def _ajouter_contexte_apercu(contexte, animateur, apercu):
    if apercu:
        contexte.update({
            "apercu_portail": True,
            "animateurs_apercu": Animateur.objects.select_related("utilisateur").order_by("nom", "prenom"),
            "apercu_query_suffix": f"&apercu_portail=1&animateur_id={animateur.pk}",
            "apercu_query_prefix": f"?apercu_portail=1&animateur_id={animateur.pk}",
            "masquer_selecteurs_configuration": True,
        })
    return contexte


def _publication_affectations_disponible():
    """Évite de bloquer le portail pendant le déploiement de sa migration."""
    return PublicationAffectationsPeriode._meta.db_table in connection.introspection.table_names()


def _semaine_portail_animateur(request):
    """Résout la semaine du portail et mémorise toute sélection explicite valide."""
    semaines_ouvertes = _semaines_vacances_ouvertes(request)
    valeur = request.GET.get("semaine")
    if valeur is not None:
        date_reference = parse_date(valeur)
        if date_reference is not None:
            date_reference -= datetime.timedelta(days=date_reference.weekday())
            if semaines_ouvertes:
                date_reference = _fallback_semaine_ouverte(date_reference, semaines_ouvertes)
            request.session[PORTAIL_ANIMATEUR_SEMAINE_SESSION_KEY] = date_reference.isoformat()
            return date_reference
    memorisee = parse_date(request.session.get(PORTAIL_ANIMATEUR_SEMAINE_SESSION_KEY, ""))
    if memorisee is not None:
        memorisee -= datetime.timedelta(days=memorisee.weekday())
        if semaines_ouvertes:
            memorisee = _fallback_semaine_ouverte(memorisee, semaines_ouvertes)
        request.session[PORTAIL_ANIMATEUR_SEMAINE_SESSION_KEY] = memorisee.isoformat()
        return memorisee
    actuelle = _semaine_initiale_animateur(request)
    if semaines_ouvertes:
        actuelle = _fallback_semaine_ouverte(actuelle, semaines_ouvertes)
        request.session[PORTAIL_ANIMATEUR_SEMAINE_SESSION_KEY] = actuelle.isoformat()
    return actuelle


def _semaine_initiale_animateur(request):
    """Choisit la semaine courante, ou la prochaine semaine travaillée."""
    actuelle = timezone.localdate()
    lundi = actuelle - datetime.timedelta(days=actuelle.weekday())
    animateur = getattr(request.user, "profil_animateur", None)
    if animateur is None:
        return actuelle
    debut = timezone.make_aware(datetime.datetime.combine(lundi, datetime.time.min))
    fin = debut + datetime.timedelta(days=7)
    if Affectation.objects.filter(animateur=animateur, debut__lt=fin, fin__gt=debut).exists():
        return lundi
    maintenant = timezone.now()
    future = (
        Affectation.objects.filter(animateur=animateur, fin__gt=maintenant)
        .order_by("debut")
        .values_list("debut", flat=True)
    )
    for debut_affectation in future:
        semaine = timezone.localtime(debut_affectation).date()
        semaine -= datetime.timedelta(days=semaine.weekday())
        if semaine > lundi:
            return semaine
    return actuelle


def _semaines_vacances_ouvertes(request):
    """Retourne les lundis de vacances où au moins un groupe est ouvert.

    Le portail animateur ne possède pas de sélecteur ``type_accueil`` : les
    flèches visibles sont rendues directement par les templates du portail.
    La liste doit donc être calculée ici sans dépendre d'un paramètre de
    session ou de requête qui n'est jamais transmis par cette interface.
    """
    periodes = list(
        PeriodeScolaire.objects.filter(type_accueil__code=TypeAccueil.VACANCES).order_by("debut", "id")
    )
    groupes = list(
        Evenement.objects.filter(centre__isnull=False)
        .prefetch_related("periodes_scolaires", "dates_exclues")
    )
    ouvertes = []
    for periode in periodes:
        lundi = periode.debut - datetime.timedelta(days=periode.debut.weekday())
        dernier_lundi = periode.fin - datetime.timedelta(days=periode.fin.weekday())
        while lundi <= dernier_lundi:
            jours = [
                lundi + datetime.timedelta(days=decalage)
                for decalage in range(7)
                if periode.debut <= lundi + datetime.timedelta(days=decalage) <= periode.fin
            ]
            if any(groupe.est_ouvert_le(jour) for groupe in groupes for jour in jours):
                ouvertes.append(lundi)
            lundi += datetime.timedelta(days=7)
    return sorted(set(ouvertes))


def _fallback_semaine_ouverte(reference, semaines_ouvertes):
    return (
        next((semaine for semaine in semaines_ouvertes if semaine >= reference), None)
        or semaines_ouvertes[-1]
    )


def _navigation_semaine_portail(request, semaine):
    """Remplace les flèches Vacances par les semaines réellement ouvertes."""
    semaines = _semaines_vacances_ouvertes(request)
    if not semaines:
        return
    debut = semaine["debut"]
    index = semaines.index(debut) if debut in semaines else 0
    semaine["precedente"] = semaines[index - 1] if index else semaines[-1]
    semaine["suivante"] = semaines[index + 1] if index + 1 < len(semaines) else semaines[0]

# ---------------------------------------------------------------------------
# Pages HTML
# ---------------------------------------------------------------------------
# Chaque vue ci-dessous se contente de rendre un template quasi vide : les
# données sont chargées côté client par le JS correspondant (voir
# static/js/<nom-de-la-page>.js), qui appelle les endpoints API plus bas.


def changer_mot_de_passe(request):
    """Impose le remplacement du mot de passe provisoire à la première connexion."""
    animateur = getattr(request.user, "profil_animateur", None)
    if animateur is None or not animateur.doit_changer_mot_de_passe:
        return redirect("accueil")
    erreur = ""
    if request.method == "POST":
        mot_de_passe = request.POST.get("mot_de_passe", "")
        confirmation = request.POST.get("confirmation", "")
        if mot_de_passe != confirmation:
            erreur = "Les deux mots de passe ne correspondent pas."
        else:
            erreur = valider_mot_de_passe(mot_de_passe, utilisateur=request.user)
        if not erreur:
            request.user.set_password(mot_de_passe)
            request.user.save(update_fields=["password"])
            animateur.doit_changer_mot_de_passe = False
            animateur.save(update_fields=["doit_changer_mot_de_passe"])
            update_session_auth_hash(request, request.user)
            return redirect("accueil")
    return render(request, "registration/changer_mot_de_passe.html", {"erreur": erreur})


def activation_compte(request, uidb64, token):
    """Permet à un nouvel animateur de choisir son premier mot de passe."""
    try:
        uidb64 += "=" * (-len(uidb64) % 4)
        uid = urlsafe_b64decode(uidb64).decode()
        utilisateur = get_user_model().objects.get(pk=uid)
    except (ValueError, TypeError, OverflowError, UnicodeDecodeError, get_user_model().DoesNotExist):
        utilisateur = None
    try:
        animateur = utilisateur.profil_animateur if utilisateur else None
    except ObjectDoesNotExist:
        animateur = None
    valide = bool(
        utilisateur
        and animateur
        and not utilisateur.has_usable_password()
        and default_token_generator.check_token(utilisateur, token)
    )
    if not valide:
        return render(request, "registration/activation_invalide.html", status=400)
    form = SetPasswordForm(utilisateur, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        utilisateur.is_active = True
        utilisateur.save(update_fields=["password", "is_active"])
        animateur.doit_changer_mot_de_passe = False
        animateur.save(update_fields=["doit_changer_mot_de_passe"])
        login(request, utilisateur)
        return redirect("accueil")
    return render(request, "registration/activation_compte.html", {"form": form, "username": utilisateur.username})


def _centre_affectation_animateur(animateur, jour):
    if animateur is None or jour is None:
        return None
    debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
    fin = debut + datetime.timedelta(days=1)
    return (
        Affectation.objects.filter(animateur=animateur, debut__lt=fin, fin__gt=debut)
        .select_related("centre")
        .order_by("debut")
        .values_list("centre_id", flat=True)
        .first()
    )


def accueil(request):
    contexte = {"active_page": "accueil"}
    animateur, apercu = resoudre_portail_consulte(request, forcer_apercu=request.path.endswith("apercu-portail/"))
    if not est_direction(request.user) or apercu:
        contexte["animateur"] = animateur
        message_materiel = ""
        erreur_materiel = ""

        if request.method == "POST" and apercu:
            raise PermissionDenied("L’aperçu est strictement en lecture seule.")
        if request.method == "POST" and request.POST.get("module") == "materiel":
            action = request.POST.get("action", "creer")
            if animateur is None:
                erreur_materiel = "Ton compte n’est pas rattaché à une fiche salarié."
            elif action == "supprimer":
                try:
                    demande = DemandeMateriel.objects.get(pk=request.POST.get("demande_id"), animateur=animateur)
                except (DemandeMateriel.DoesNotExist, ValueError, TypeError):
                    erreur_materiel = "Cette demande n’existe plus ou ne t’appartient pas."
                else:
                    demande.delete()
                    message_materiel = "La demande a été supprimée."
            elif action == "creer":
                materiel = request.POST.get("materiel", "").strip()
                date_besoin = parse_date(request.POST.get("date_besoin", ""))
                try:
                    quantite = int(request.POST.get("quantite", "1"))
                except (TypeError, ValueError):
                    quantite = 0
                try:
                    centre = Centre.objects.get(pk=int(request.POST.get("centre_id", "")))
                except (TypeError, ValueError, Centre.DoesNotExist):
                    centre = None

                if not materiel:
                    erreur_materiel = "Indique le matériel demandé."
                elif quantite < 1:
                    erreur_materiel = "La quantité doit être au moins égale à 1."
                elif date_besoin is None:
                    erreur_materiel = "Indique une date précise pour cette demande."
                elif centre is None:
                    erreur_materiel = "Choisis le centre concerné."
                else:
                    DemandeMateriel.objects.create(
                        animateur=animateur,
                        centre=centre,
                        materiel=materiel,
                        quantite=quantite,
                        date_besoin=date_besoin,
                    )
                    message_materiel = "Ta demande de matériel a été enregistrée."

        if animateur is not None:
            date_reference = _semaine_portail_animateur(request)
            contexte.update(generer_tableau_de_bord_animateur(animateur, date_reference))
            _navigation_semaine_portail(request, contexte["semaine"])
            contexte["semaine_active"] = contexte["semaine"]["debut"]
            contexte.update({
                "planning_jours_affectes": sum(1 for jour in contexte["jours"] if jour.get("travaille")),
                "infos_sorties_count": len(contexte["sorties"]),
                "infos_documents_count": len(contexte["documents"]),
                "infos_reunions_count": len(contexte["reunions"]),
                "infos_infos_count": len(contexte.get("informations", [])),
                "infos_infos_important_count": sum(
                    1 for information in contexte.get("informations", []) if information.est_importante
                ),
            })
            contexte.update({
                "centres_materiel": Centre.objects.all(),
                "demandes_materiel": DemandeMateriel.objects.filter(animateur=animateur).select_related("centre"),
                "message_materiel": message_materiel,
                "erreur_materiel": erreur_materiel,
            })
            contexte["publication_affectation_a_confirmer"] = (
                DestinatairePublicationAffectation.objects.filter(
                    animateur=animateur, confirme_le__isnull=True, publication__publie=True
                )
                .select_related("publication__periode_calendrier")
                .order_by("publication__periode_calendrier__debut")
                .first()
                if _publication_affectations_disponible() else None
            )
            _ajouter_actions_portail(contexte, animateur)
            _ajouter_contexte_apercu(contexte, animateur, apercu)
    return render(request, "accueil.html", contexte)


def _ajouter_actions_portail(contexte, animateur):
    """Expose une seule fois les actions personnelles au layout du portail."""
    actions = actions_actives_animateur(animateur) if animateur is not None else []
    contexte["actions_a_faire"] = actions
    contexte["actions_a_faire_count"] = len(actions)
    contexte["action_a_faire_prioritaire"] = actions[0] if actions else None


def _contexte_portail_animateur(request, active_page):
    """Contexte partagé par les espaces animateur dépendant d'une semaine."""
    animateur, apercu = resoudre_portail_consulte(request)
    contexte = {"active_page": active_page, "animateur": animateur}
    if animateur is not None:
        date_reference = _semaine_portail_animateur(request)
        contexte.update(
            generer_tableau_de_bord_animateur(
                animateur,
                date_reference,
                inclure_programmes=active_page == "plannings",
            )
        )
        _navigation_semaine_portail(request, contexte["semaine"])
        contexte["semaine_active"] = contexte["semaine"]["debut"]
        _ajouter_actions_portail(contexte, animateur)
    return _ajouter_contexte_apercu(contexte, animateur, apercu)


def plannings_animateur(request):
    if est_direction(request.user) and request.GET.get("apercu_portail") != "1":
        return redirect("planning")
    return render(request, "plannings_animateur.html", _contexte_portail_animateur(request, "plannings"))


def infos_animateur(request):
    if est_direction(request.user) and request.GET.get("apercu_portail") != "1":
        return redirect("documents")
    return render(request, "infos_animateur.html", _contexte_portail_animateur(request, "infos"))


def sorties_animateur(request):
    if est_direction(request.user) and request.GET.get("apercu_portail") != "1":
        return redirect("sorties")
    return render(request, "sorties_animateur.html", _contexte_portail_animateur(request, "sorties_animateur"))


def documents_animateur(request):
    if est_direction(request.user) and request.GET.get("apercu_portail") != "1":
        return redirect("documents")
    return render(request, "documents_animateur.html", _contexte_portail_animateur(request, "documents_animateur"))


def _groupes_reponse_disponibilites(demande):
    """Prépare une lecture mobile : semaines seulement pour les dates continues."""
    propositions = list(demande.propositions.select_related("date_campagne__bloc").order_by(
        "date_campagne__bloc__ordre", "date", "id"
    ))
    blocs = []
    par_bloc = {}
    for proposition in propositions:
        bloc = proposition.date_campagne.bloc if proposition.date_campagne_id else None
        if bloc is not None:
            par_bloc.setdefault(bloc.pk, {"bloc": bloc, "propositions": []})["propositions"].append(proposition)

    for item in par_bloc.values():
        bloc, lignes = item["bloc"], item["propositions"]
        groupes = []
        if bloc.mode_saisie == CampagneDisponibiliteBloc.JOURNEE:
            semaines = {}
            for ligne in lignes:
                lundi = ligne.date - datetime.timedelta(days=ligne.date.weekday())
                semaines.setdefault(lundi, []).append(ligne)
            for lundi, lignes_semaine in semaines.items():
                lignes_semaine.sort(key=lambda ligne: ligne.date)
                # Un bloc de vacances est condensé seulement lorsque les dates
                # de la semaine forment réellement une suite continue.
                continuees = all(
                    suivante.date == precedente.date + datetime.timedelta(days=1)
                    for precedente, suivante in zip(lignes_semaine, lignes_semaine[1:])
                )
                groupes.append({
                    "type": "semaine" if len(lignes_semaine) > 1 and continuees else "dates",
                    "lundi": lundi,
                    "propositions": lignes_semaine,
                })
        else:
            groupes.append({"type": "dates", "propositions": lignes})
        blocs.append({"bloc": bloc, "groupes": groupes})
    return blocs, propositions


def _resume_reponse_disponibilites(propositions):
    total = len(propositions)
    renseignees = [p for p in propositions if p.creneau != PropositionDisponibiliteDate.NON_RENSEIGNE]
    return {
        "total": total,
        "renseignees": len(renseignees),
        "restantes": total - len(renseignees),
        "journees": sum(p.creneau == PropositionDisponibiliteDate.JOURNEE for p in propositions),
        "matins": sum(p.creneau == PropositionDisponibiliteDate.MATIN for p in propositions),
        "apres_midis": sum(p.creneau == PropositionDisponibiliteDate.APRES_MIDI for p in propositions),
        "zero_disponibilite": bool(propositions) and all(
            p.creneau == PropositionDisponibiliteDate.INDISPONIBLE for p in propositions
        ),
    }


@transaction.atomic
def _enregistrer_brouillon_disponibilites(demande, donnees, commentaire):
    """Conserve chaque choix explicite, y compris les dates non renseignées."""
    propositions = list(demande.propositions.select_related("date_campagne__bloc").order_by("date", "id"))
    valeurs_autorisees = set(dict(PropositionDisponibiliteDate.CRENEAUX))
    for proposition in propositions:
        valeur = donnees.get(f"creneau_{proposition.pk}", proposition.creneau)
        bloc = proposition.date_campagne.bloc if proposition.date_campagne_id else None
        if valeur not in valeurs_autorisees or (
            bloc is not None
            and bloc.mode_saisie == CampagneDisponibiliteBloc.JOURNEE
            and valeur not in {
                PropositionDisponibiliteDate.NON_RENSEIGNE,
                PropositionDisponibiliteDate.INDISPONIBLE,
                PropositionDisponibiliteDate.JOURNEE,
            }
        ):
            raise ValidationError("Une valeur de disponibilité est invalide.")
        if valeur != proposition.creneau:
            proposition.creneau = valeur
            proposition.save(update_fields=["creneau"])
    demande.commentaire_animateur = commentaire.strip()
    if demande.statut == DemandeDisponibilite.A_RENSEIGNER:
        demande.transition_vers(DemandeDisponibilite.BROUILLON)
    demande.save(update_fields=["commentaire_animateur", "statut"])


def demande_disponibilite_repondre(request, demande_id):
    """Saisie mobile d'une seule réponse, ou aperçu strictement en lecture seule."""
    if est_direction(request.user) and request.GET.get("apercu_portail") != "1":
        return redirect("campagnes_disponibilites")
    animateur, apercu = resoudre_portail_consulte(request)
    if animateur is None:
        raise PermissionDenied("Aucun profil animateur n’est associé à ce compte.")
    demande = get_object_or_404(
        DemandeDisponibilite.objects.select_related("campagne").prefetch_related(
            "propositions__date_campagne__bloc"
        ),
        pk=demande_id,
        animateur=animateur,
    )
    if demande.campagne_id is None:
        raise PermissionDenied("Cette page est réservée aux réponses de campagne.")
    if request.method == "POST":
        if apercu:
            raise PermissionDenied("L’aperçu est strictement en lecture seule.")
        if demande.campagne.statut != CampagneDisponibilite.OUVERTE:
            messages.error(request, "Cette campagne est clôturée et n’accepte plus de réponse.")
            return redirect("demande_disponibilite_repondre", demande_id=demande.pk)
        if demande.statut not in {DemandeDisponibilite.A_RENSEIGNER, DemandeDisponibilite.BROUILLON}:
            messages.error(request, "Cette réponse a déjà été envoyée et ne peut plus être modifiée.")
            return redirect("demande_disponibilite_repondre", demande_id=demande.pk)
        try:
            _enregistrer_brouillon_disponibilites(
                demande, request.POST, request.POST.get("commentaire_animateur", "")
            )
            demande.refresh_from_db()
            if request.POST.get("action") == "envoyer":
                propositions = list(demande.propositions.all())
                resume = _resume_reponse_disponibilites(propositions)
                if resume["zero_disponibilite"] and request.POST.get("confirmer_zero") != "1":
                    raise ValidationError("Confirme l’envoi sans aucune disponibilité.")
                envoyer_demande(demande)
                messages.success(request, "Tes disponibilités ont été envoyées.")
            else:
                messages.success(request, "Brouillon enregistré.")
        except (ValidationError, DemandeDisponibiliteIncomplete) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, ValidationError) else str(exc))
        return redirect("demande_disponibilite_repondre", demande_id=demande.pk)

    blocs, propositions = _groupes_reponse_disponibilites(demande)
    resume = _resume_reponse_disponibilites(propositions)
    est_cloturee = demande.campagne.statut == CampagneDisponibilite.CLOTUREE
    est_modifiable = (
        not apercu
        and not est_cloturee
        and demande.statut in {DemandeDisponibilite.A_RENSEIGNER, DemandeDisponibilite.BROUILLON}
    )
    retour = _contexte_portail_animateur(request, "disponibilites_reponse")
    retour.update({
        "demande": demande,
        "blocs_reponse": blocs,
        "resume_reponse": resume,
        "est_modifiable": est_modifiable,
        "est_cloturee": est_cloturee,
        "echeance_depassee": bool(
            demande.campagne.date_limite_reponse
            and demande.campagne.date_limite_reponse < timezone.localdate()
        ),
        "application_automatique_bloquee": (
            demande.statut == DemandeDisponibilite.ENVOYEE
            and not demande.validation_requise
            and any(p.creneau in {PropositionDisponibiliteDate.MATIN, PropositionDisponibiliteDate.APRES_MIDI} for p in propositions)
        ),
    })
    return render(request, "demande_disponibilite_repondre.html", retour)


def _affectations_periode(periode, animateur=None):
    """Lit les affectations existantes d'une période, sans en créer de copie."""
    debut = timezone.make_aware(datetime.datetime.combine(periode.debut, datetime.time.min))
    fin = timezone.make_aware(datetime.datetime.combine(periode.fin + datetime.timedelta(days=1), datetime.time.min))
    queryset = Affectation.objects.filter(debut__lt=fin, fin__gt=debut)
    if animateur is not None:
        queryset = queryset.filter(animateur=animateur)
    return list(queryset.select_related("animateur__utilisateur", "centre", "evenement__groupe").order_by(
        "animateur__nom", "animateur__prenom", "debut", "id"
    ))


def _details_affectations_periode(periode, animateur):
    affectations = _affectations_periode(periode, animateur)
    resultat = []
    for affectation in affectations:
        responsabilite = (
            ResponsabiliteOperationnelle.objects.filter(
                animateur=animateur, debut__lt=affectation.fin, fin__gt=affectation.debut
            )
            .select_related("fonction")
            .order_by("debut")
            .first()
        )
        resultat.append({"affectation": affectation, "role": responsabilite.fonction.nom if responsabilite else ""})
    return resultat


def publications_affectations(request):
    """Publication direction des affectations de période, indépendante du planning."""
    periode_id = request.GET.get("periode_id") or request.POST.get("periode_id")
    periode = PeriodeCalendrier.objects.filter(pk=periode_id).first() if periode_id else None
    periodes = PeriodeCalendrier.objects.filter(categorie=PeriodeCalendrier.VACANCES).order_by("debut")
    if periode is None:
        periode = periodes.filter(debut__gte=timezone.localdate()).first() or periodes.last()
    if periode is None:
        messages.error(request, "Aucune période de vacances n'est disponible.")
        return redirect("accueil")

    publication = PublicationAffectationsPeriode.objects.filter(periode_calendrier=periode).first()
    affectations = _affectations_periode(periode)
    animateurs = []
    deja_vus = set()
    for affectation in affectations:
        if affectation.animateur_id not in deja_vus:
            animateurs.append(affectation.animateur)
            deja_vus.add(affectation.animateur_id)

    if request.method == "POST":
        message = request.POST.get("message", "").strip()
        if not message:
            messages.error(request, "Le message d'information est obligatoire.")
        else:
            with transaction.atomic():
                publication, _ = PublicationAffectationsPeriode.objects.get_or_create(periode_calendrier=periode)
                publication.message = message
                publication.publie = True
                publication.publie_le = timezone.now()
                publication.publie_par = request.user
                publication.save()
                existants = {item.animateur_id: item for item in publication.destinataires.all()}
                ids_animateurs = {animateur.pk for animateur in animateurs}
                for animateur in animateurs:
                    instantane = instantane_affectations(periode, animateur)
                    destinataire = existants.get(animateur.pk)
                    if destinataire is None:
                        DestinatairePublicationAffectation.objects.create(
                            publication=publication, animateur=animateur,
                            instantane_affectations=instantane,
                            instantane_affectations_est_fige=True,
                        )
                    elif (
                        not destinataire.instantane_affectations_est_fige
                        or not instantanes_affectations_equivalents(destinataire.instantane_affectations, instantane)
                        or destinataire.retire_le is not None
                        or destinataire.annulation_notifiee_le is not None
                    ):
                        est_reaffectation = destinataire.retire_le is not None
                        instantane_reellement_modifie = (
                            destinataire.instantane_affectations_est_fige
                            and not instantanes_affectations_equivalents(destinataire.instantane_affectations, instantane)
                        )
                        details_confirmes = [] if est_reaffectation else details_affectations_avec_statut(destinataire)
                        destinataire.instantane_affectations = instantane
                        destinataire.instantane_affectations_confirmees = [
                            {cle: valeur for cle, valeur in detail.items() if cle != "statut_confirmation"}
                            for detail in details_confirmes if detail["statut_confirmation"] == "confirmee"
                        ]
                        destinataire.confirme_le = None if est_reaffectation or affectations_restent_a_confirmer(destinataire) else destinataire.confirme_le
                        destinataire.retire_le = None
                        destinataire.instantane_affectations_est_fige = True
                        destinataire.annulation_notifiee_le = None
                        destinataire.annulation_prise_en_compte_le = None
                        destinataire.instantane_modifie_le = (
                            publication.publie_le if instantane_reellement_modifie and not est_reaffectation else None
                        )
                        destinataire.save(update_fields=["instantane_affectations", "instantane_affectations_est_fige", "instantane_affectations_confirmees", "confirme_le", "retire_le", "annulation_notifiee_le", "annulation_prise_en_compte_le", "instantane_modifie_le"])
                    elif destinataire.retire_le is not None:
                        destinataire.retire_le = None
                        destinataire.save(update_fields=["retire_le"])
                for animateur_id, destinataire in existants.items():
                    if animateur_id not in ids_animateurs and destinataire.retire_le is None:
                        destinataire.retire_le = timezone.now()
                        destinataire.annulation_notifiee_le = timezone.now()
                        destinataire.annulation_prise_en_compte_le = None
                        destinataire.save(update_fields=["retire_le", "annulation_notifiee_le", "annulation_prise_en_compte_le"])
            messages.success(request, "Les affectations ont été publiées. Les confirmations inchangées sont conservées.")
            return redirect(f"{request.path}?periode_id={periode.pk}")

    destinataires = []
    if publication:
        destinataires = list(publication.destinataires.select_related("animateur__utilisateur").all())
    return render(request, "publications_affectations.html", {
        "active_page": "accueil", "periode": periode, "periodes": periodes,
        "publication": publication, "animateurs_affectes": animateurs, "destinataires": destinataires,
    })


def affectation_a_confirmer(request, publication_id):
    """Un animateur ne peut consulter et confirmer que sa propre publication."""
    animateur, apercu = resoudre_portail_consulte(request)
    if est_direction(request.user) and not apercu:
        return redirect("publications_affectations")
    destinataire = (
        DestinatairePublicationAffectation.objects.filter(
            pk=publication_id, animateur=animateur, publication__publie=True
        ).select_related("publication__periode_calendrier").first()
    )
    if destinataire is None:
        raise PermissionDenied
    if request.method != "GET" and apercu:
        raise PermissionDenied("L’aperçu est strictement en lecture seule.")
    details = details_affectations_avec_statut(destinataire)
    nombre_a_confirmer = sum(detail["statut_confirmation"] == "a_confirmer" for detail in details)
    detail_indisponible = detail_legacy_indisponible(destinataire)
    annulation_notifiee = destinataire.annulation_notifiee_le is not None
    annulation_a_prendre_en_compte = annulation_notifiee and destinataire.annulation_prise_en_compte_le is None
    a_confirmer = bool(nombre_a_confirmer) and not detail_indisponible and not annulation_notifiee
    if request.method == "POST" and annulation_a_prendre_en_compte:
        if request.POST.get("action") == "prendre_en_compte_annulation":
            destinataire.annulation_prise_en_compte_le = timezone.now()
            destinataire.save(update_fields=["annulation_prise_en_compte_le"])
            messages.success(request, "Tu as bien pris connaissance de l’annulation de ton affectation.")
            return redirect("affectation_a_confirmer", publication_id=destinataire.pk)
    elif request.method == "POST" and a_confirmer:
        if request.POST.get("action") == "signaler":
            contenu = request.POST.get("contenu", "").strip()
            if not contenu:
                messages.error(request, "Écris ton message avant de l’envoyer.")
            else:
                SignalementAffectationPublication.objects.create(
                    destinataire=destinataire,
                    contenu=contenu,
                    instantane_affectations=copy.deepcopy(destinataire.instantane_affectations),
                )
                messages.success(request, "Ton message a bien été envoyé à la direction. Ton affectation reste à confirmer.")
                return redirect("affectation_a_confirmer", publication_id=destinataire.pk)
        else:
            # Ne pas transformer une lecture legacy reconstruite en faux
            # instantané : seule une publication déjà figée peut être mémorisée
            # ligne par ligne comme confirmée.
            if destinataire.instantane_affectations_est_fige:
                destinataire.instantane_affectations_confirmees = copy.deepcopy(destinataire.instantane_affectations)
            destinataire.confirme_le = timezone.now()
            update_fields = ["confirme_le"]
            if destinataire.instantane_affectations_est_fige:
                update_fields.append("instantane_affectations_confirmees")
            destinataire.save(update_fields=update_fields)
            messages.success(request, "Ta confirmation a bien été enregistrée.")
            return redirect("affectation_a_confirmer", publication_id=destinataire.pk)
    contexte = {
        "active_page": "accueil", "destinataire": destinataire,
        "details": details,
        "a_confirmer": a_confirmer,
        "detail_indisponible": detail_indisponible,
        "annulation_notifiee": annulation_notifiee,
        "annulation_a_prendre_en_compte": annulation_a_prendre_en_compte,
        "nombre_a_confirmer": nombre_a_confirmer,
        "signalements": destinataire.signalements.all(),
    }
    return render(request, "affectation_a_confirmer.html", _ajouter_contexte_apercu(contexte, animateur, apercu))


def actions_a_faire(request):
    """Liste les interventions personnelles encore attendues."""
    animateur, apercu = resoudre_portail_consulte(request)
    if est_direction(request.user) and not apercu:
        return redirect("accueil")
    contexte = _contexte_portail_animateur(request, "actions_a_faire")
    contexte["actions"] = contexte.get("actions_a_faire", [])
    return render(request, "actions_a_faire.html", contexte)


def actions_equipe(request):
    """Suivi direction des actions d'affectations publiées."""
    periode_id = request.GET.get("periode_id")
    periodes = PeriodeCalendrier.objects.filter(categorie=PeriodeCalendrier.VACANCES).order_by("debut")
    periode = periodes.filter(pk=periode_id).first() if periode_id else None
    if periode is None:
        periode = periodes.filter(debut__gte=timezone.localdate()).first() or periodes.last()
    suivi = suivi_actions_affectations(periode) if periode else suivi_actions_affectations(type("P", (), {"publication_affectations": None})())
    return render(request, "actions_equipe.html", {
        "active_page": "gestion", "gestion_onglet": "actions-equipe", "masquer_selecteurs_configuration": True,
        "periodes": periodes, "periode": periode, "suivi": suivi,
    })


def campagnes_disponibilites(request):
    """Liste direction des campagnes et point d'entrée de leur création."""
    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        if not nom:
            messages.error(request, "Le nom de la campagne est obligatoire.")
        else:
            campagne = CampagneDisponibilite.objects.create(nom=nom, cree_par=request.user)
            return redirect("campagne_disponibilite_detail", campagne_id=campagne.pk)

    campagnes = list(CampagneDisponibilite.objects.prefetch_related("destinataires", "demandes").all())
    for campagne in campagnes:
        campagne.nombre_destinataires = campagne.destinataires.count()
        campagne.nombre_reponses = sum(
            demande.statut in {
                demande.ENVOYEE, demande.A_CORRIGER, demande.VALIDEE, demande.REFUSEE,
            }
            for demande in campagne.demandes.all()
        )
    return render(request, "campagnes_disponibilites.html", {
        "active_page": "gestion", "gestion_onglet": "disponibilites",
        "campagnes": campagnes,
    })


def _dates_manuelles(valeur):
    dates = set()
    for element in re.split(r"[\s,;]+", valeur.strip()):
        if not element:
            continue
        jour = parse_date(element)
        if jour is None:
            raise ValidationError("Utilise des dates au format AAAA-MM-JJ.")
        dates.add(jour)
    if not dates:
        raise ValidationError("Ajoute au moins une date.")
    return sorted(dates)


def campagne_disponibilite_detail(request, campagne_id):
    """Édite un brouillon ; une campagne ouverte reste strictement en lecture seule."""
    try:
        campagne = CampagneDisponibilite.objects.prefetch_related(
            "destinataires", "blocs__dates", "demandes__animateur"
        ).get(pk=campagne_id)
    except CampagneDisponibilite.DoesNotExist:
        messages.error(request, "Cette campagne n’existe plus.")
        return redirect("campagnes_disponibilites")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "cloturer":
            try:
                cloturer_campagne(campagne)
                messages.success(request, "Campagne clôturée. Les réponses déjà envoyées sont conservées.")
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
            return redirect("campagne_disponibilite_detail", campagne_id=campagne.pk)
        if campagne.statut != CampagneDisponibilite.BROUILLON:
            messages.error(request, "Une campagne ouverte ne peut plus être modifiée.")
            return redirect("campagne_disponibilite_detail", campagne_id=campagne.pk)
        try:
            if action == "enregistrer":
                nom = request.POST.get("nom", "").strip()
                if not nom:
                    raise ValidationError("Le nom de la campagne est obligatoire.")
                date_limite = parse_date(request.POST.get("date_limite_reponse", ""))
                if request.POST.get("date_limite_reponse") and date_limite is None:
                    raise ValidationError("L’échéance est invalide.")
                identifiants = {int(value) for value in request.POST.getlist("animateur_ids")}
                animateurs = list(Animateur.objects.filter(pk__in=identifiants, actif=True))
                if len(animateurs) != len(identifiants):
                    raise ValidationError("Un animateur sélectionné n’est plus disponible.")
                campagne.nom = nom
                campagne.date_limite_reponse = date_limite
                campagne.validation_direction_requise = request.POST.get("validation_direction_requise") == "on"
                campagne.save(update_fields=["nom", "date_limite_reponse", "validation_direction_requise"])
                campagne.destinataires.set(animateurs)
                messages.success(request, "Brouillon enregistré.")
            elif action == "ajouter_periode":
                periode = PeriodeScolaire.objects.get(pk=request.POST.get("periode_id"))
                mode_saisie = request.POST.get("mode_saisie", CampagneDisponibiliteBloc.JOURNEE)
                if mode_saisie not in dict(CampagneDisponibiliteBloc.MODES_SAISIE):
                    raise ValidationError("Le mode de saisie est invalide.")
                bloc = CampagneDisponibiliteBloc.objects.create(
                    campagne=campagne, libelle=periode.categorie_vacances or periode.nom,
                    ordre=campagne.blocs.count() + 1, mode_saisie=mode_saisie,
                )
                # La période existante reste une provenance ; seuls les jours
                # ouvrés sont copiés dans la campagne, qui devient autonome.
                jours = [
                    periode.debut + datetime.timedelta(days=index)
                    for index in range((periode.fin - periode.debut).days + 1)
                    if (periode.debut + datetime.timedelta(days=index)).weekday() < 5
                ]
                existantes = set(campagne.dates.values_list("date", flat=True))
                nouvelles = [jour for jour in jours if jour not in existantes]
                if not nouvelles:
                    bloc.delete()
                    raise ValidationError("Toutes les dates de cette période sont déjà dans la campagne.")
                CampagneDisponibiliteDate.objects.bulk_create([
                    CampagneDisponibiliteDate(
                        campagne=campagne, bloc=bloc, date=jour, ordre=index,
                        periode_scolaire_source=periode,
                    ) for index, jour in enumerate(nouvelles, start=1)
                ])
                messages.success(request, "Période ajoutée au brouillon.")
            elif action == "ajouter_dates":
                libelle = request.POST.get("libelle_bloc", "").strip() or "Dates personnalisées"
                mode_saisie = request.POST.get("mode_saisie", CampagneDisponibiliteBloc.JOURNEE)
                if mode_saisie not in dict(CampagneDisponibiliteBloc.MODES_SAISIE):
                    raise ValidationError("Le mode de saisie est invalide.")
                jours = _dates_manuelles(request.POST.get("dates_manuelles", ""))
                existantes = set(campagne.dates.values_list("date", flat=True))
                nouvelles = [jour for jour in jours if jour not in existantes]
                if not nouvelles:
                    raise ValidationError("Toutes ces dates sont déjà dans la campagne.")
                bloc = CampagneDisponibiliteBloc.objects.create(
                    campagne=campagne, libelle=libelle, ordre=campagne.blocs.count() + 1,
                    mode_saisie=mode_saisie,
                )
                CampagneDisponibiliteDate.objects.bulk_create([
                    CampagneDisponibiliteDate(campagne=campagne, bloc=bloc, date=jour, ordre=index)
                    for index, jour in enumerate(nouvelles, start=1)
                ])
                messages.success(request, "Dates personnalisées ajoutées.")
            elif action == "retirer_date":
                CampagneDisponibiliteDate.objects.filter(
                    pk=request.POST.get("date_id"), campagne=campagne
                ).delete()
                messages.success(request, "Date retirée du brouillon.")
            elif action == "supprimer_bloc":
                CampagneDisponibiliteBloc.objects.filter(
                    pk=request.POST.get("bloc_id"), campagne=campagne
                ).delete()
                messages.success(request, "Bloc retiré du brouillon.")
            elif action == "modifier_mode_bloc":
                bloc = CampagneDisponibiliteBloc.objects.get(
                    pk=request.POST.get("bloc_id"), campagne=campagne
                )
                mode_saisie = request.POST.get("mode_saisie")
                if mode_saisie not in dict(CampagneDisponibiliteBloc.MODES_SAISIE):
                    raise ValidationError("Le mode de saisie est invalide.")
                bloc.mode_saisie = mode_saisie
                bloc.save(update_fields=["mode_saisie"])
                messages.success(request, "Mode de saisie du bloc enregistré.")
            elif action == "ouvrir":
                if not campagne.dates.exists():
                    raise ValidationError("Ajoute au moins une date avant d’ouvrir la campagne.")
                ouvrir_campagne(campagne)
                messages.success(request, "Campagne ouverte : les animateurs peuvent désormais renseigner leurs disponibilités.")
            else:
                raise ValidationError("Action inconnue.")
        except (CampagneDisponibilite.DoesNotExist, PeriodeScolaire.DoesNotExist, TypeError, ValueError, ValidationError) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, ValidationError) else "La modification est invalide.")
        return redirect("campagne_disponibilite_detail", campagne_id=campagne.pk)

    campagne = CampagneDisponibilite.objects.prefetch_related(
        "destinataires", "blocs__dates", "demandes__animateur"
    ).get(pk=campagne.pk)
    blocs = list(campagne.blocs.all())
    for bloc in blocs:
        bloc.dates_campagne = list(bloc.dates.all())
    return render(request, "campagne_disponibilite_detail.html", {
        "active_page": "gestion", "gestion_onglet": "disponibilites", "campagne": campagne,
        "blocs": blocs,
        "periodes": PeriodeScolaire.objects.order_by("debut", "ordre", "id"),
        "animateurs": Animateur.objects.filter(actif=True).order_by("nom", "prenom"),
        "destinataire_ids": set(campagne.destinataires.values_list("id", flat=True)),
        "nombre_dates": campagne.dates.count(),
    })


def apercu_portail_animateur(request):
    """Vue direction en lecture seule, fondée sur le vrai service portail."""
    if not request.GET.get("animateur_id"):
        return render(request, "apercu_portail_animateur.html", {
            "active_page": "gestion",
            "animateurs_apercu": Animateur.objects.select_related("utilisateur").order_by("nom", "prenom"),
        })
    return accueil(request)


@never_cache
def api_mon_centre_affectation(request):
    if est_direction(request.user):
        return JsonResponse({"centre_id": None})
    animateur = getattr(request.user, "profil_animateur", None)
    jour = parse_date(request.GET.get("date", ""))
    return JsonResponse({"centre_id": _centre_affectation_animateur(animateur, jour)})



def demandes_materiel(request):
    """Traitement des demandes côté direction; côté animateur tout est sur le tableau de bord."""
    animateur, apercu = resoudre_portail_consulte(request)
    direction = est_direction(request.user) and not apercu
    message = ""
    erreur = ""

    if request.method != "GET" and apercu:
        raise PermissionDenied("L’aperçu est strictement en lecture seule.")
    if request.method == "POST":
        action = request.POST.get("action", "creer")

        if action == "supprimer":
            demande_id = request.POST.get("demande_id")
            demandes_autorisees = DemandeMateriel.objects.all()
            if not direction:
                if animateur is None:
                    demandes_autorisees = DemandeMateriel.objects.none()
                else:
                    demandes_autorisees = demandes_autorisees.filter(animateur=animateur)
            try:
                demande = demandes_autorisees.get(pk=demande_id)
            except (DemandeMateriel.DoesNotExist, ValueError, TypeError):
                erreur = "Cette demande n’existe plus ou tu ne peux pas la supprimer."
            else:
                demande.delete()
                message = "La demande de matériel a été supprimée."

        elif direction and action in {"valider", "remettre_en_attente"}:
            demande_id = request.POST.get("demande_id")
            try:
                demande = DemandeMateriel.objects.get(pk=demande_id)
            except (DemandeMateriel.DoesNotExist, ValueError, TypeError):
                erreur = "Cette demande n’existe plus."
            else:
                if action == "valider":
                    demande.statut = DemandeMateriel.STATUT_VALIDEE
                    demande.date_validation = timezone.now()
                    demande.validee_par = request.user
                    message = "La demande a été marquée comme validée."
                else:
                    demande.statut = DemandeMateriel.STATUT_EN_ATTENTE
                    demande.date_validation = None
                    demande.validee_par = None
                    message = "La demande a été remise en attente."
                demande.save(update_fields=["statut", "date_validation", "validee_par"])

        elif not direction and action == "creer":
            if animateur is None:
                erreur = "Ton compte n’est pas rattaché à une fiche salarié."
            else:
                materiel = request.POST.get("materiel", "").strip()
                date_besoin = parse_date(request.POST.get("date_besoin", ""))
                try:
                    quantite = int(request.POST.get("quantite", "1"))
                except (TypeError, ValueError):
                    quantite = 0
                try:
                    centre = Centre.objects.get(pk=int(request.POST.get("centre_id", "")))
                except (TypeError, ValueError, Centre.DoesNotExist):
                    centre = None

                if not materiel:
                    erreur = "Indique le matériel demandé."
                elif quantite < 1:
                    erreur = "La quantité doit être au moins égale à 1."
                elif date_besoin is None:
                    erreur = "Indique une date précise pour cette demande."
                elif centre is None:
                    erreur = "Choisis le centre concerné."
                else:
                    DemandeMateriel.objects.create(
                        animateur=animateur,
                        centre=centre,
                        materiel=materiel,
                        quantite=quantite,
                        date_besoin=date_besoin,
                    )
                    message = "Ta demande de matériel a été enregistrée."
        else:
            erreur = "Action non autorisée."

    if direction:
        demandes = DemandeMateriel.objects.select_related("animateur", "centre", "validee_par").all()
    elif animateur is not None:
        demandes = DemandeMateriel.objects.filter(animateur=animateur).select_related("animateur", "centre", "validee_par")
    else:
        demandes = DemandeMateriel.objects.none()

    semaine_portail = None
    if not direction and animateur is not None:
        date_reference = _semaine_portail_animateur(request)
        semaine_portail = generer_tableau_de_bord_animateur(animateur, date_reference)["semaine"]
        _navigation_semaine_portail(request, semaine_portail)

    contexte = {
            "active_page": "materiel",
            "direction": direction,
            "animateur": animateur,
            "centres_materiel": Centre.objects.all() if not direction else None,
            "demandes": demandes,
            "message": message,
            "erreur": erreur,
            "semaine": semaine_portail,
            "semaine_active": semaine_portail["debut"] if semaine_portail else None,
    }
    _ajouter_actions_portail(contexte, animateur)
    return render(request, "demandes_materiel.html", _ajouter_contexte_apercu(contexte, animateur, apercu))


def mon_profil(request):
    """Consultation et mise à jour des coordonnées du compte animateur."""
    animateur, apercu = resoudre_portail_consulte(request)
    if est_direction(request.user) and not apercu:
        return redirect("employes")
    semaine_active = parse_date(request.session.get(PORTAIL_ANIMATEUR_SEMAINE_SESSION_KEY, ""))
    message = ""
    erreur = ""
    action = ""

    if request.method != "GET" and apercu:
        raise PermissionDenied("L’aperçu est strictement en lecture seule.")
    if request.method == "POST" and animateur is not None:
        action = request.POST.get("action", "coordonnees")

        if action == "coordonnees":
            telephone = request.POST.get("telephone", "").strip()
            email = request.POST.get("email", "").strip().lower()
            adresse = request.POST.get("adresse", "").strip()

            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    erreur = "L’adresse e-mail saisie n’est pas valide."

            if not erreur:
                animateur.telephone = telephone
                animateur.email = email
                animateur.adresse = adresse
                animateur.save(update_fields=["telephone", "email", "adresse"])

                request.user.email = email
                request.user.save(update_fields=["email"])
                message = "Tes coordonnées ont bien été mises à jour."

        elif action == "mot_de_passe":
            mot_de_passe = request.POST.get("mot_de_passe", "")
            confirmation = request.POST.get("confirmation", "")

            if mot_de_passe != confirmation:
                erreur = "Les deux mots de passe ne correspondent pas."
            else:
                erreur = valider_mot_de_passe(mot_de_passe, utilisateur=request.user)

            if not erreur:
                request.user.set_password(mot_de_passe)
                request.user.save(update_fields=["password"])
                animateur.doit_changer_mot_de_passe = False
                animateur.save(update_fields=["doit_changer_mot_de_passe"])
                update_session_auth_hash(request, request.user)
                message = "Ton mot de passe a bien été modifié."

    contexte = {
            "active_page": "mon_profil",
            "animateur": animateur,
            "message": message,
            "erreur": erreur,
            "action": action,
            "semaine_active": semaine_active,
    }
    _ajouter_actions_portail(contexte, animateur)
    return render(request, "mon_profil.html", _ajouter_contexte_apercu(contexte, animateur, apercu))


@never_cache
def api_tableau_de_bord(request):
    """Données agrégées de l'ensemble des centres pour une semaine."""

    date_reference = (
        parse_date(request.GET.get("semaine", "")) or parse_date(request.GET.get("date", "")) or timezone.localdate()
    )
    return JsonResponse(generer_tableau_de_bord(date_reference))


@never_cache
def api_statut_preparation_semaine(request):
    """Force ou rétablit le seul libellé de préparation d'une semaine."""

    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Données invalides."}, status=400)
    date_reference = parse_date(str(payload.get("semaine", "")))
    if date_reference is None or not isinstance(payload.get("forcer"), bool):
        return JsonResponse({"error": "Semaine ou statut invalide."}, status=400)
    debut_semaine = date_reference - datetime.timedelta(days=date_reference.weekday())
    statut, _ = StatutPreparationSemaine.objects.update_or_create(
        debut_semaine=debut_semaine,
        defaults={
            "est_force_prete": payload["forcer"],
            "modifie_par": request.user,
        },
    )
    return JsonResponse(
        {
            "debut_semaine": debut_semaine.isoformat(),
            "est_force_prete": statut.est_force_prete,
            "modifie_par": request.user.get_username(),
            "modifie_le": statut.modifie_le.isoformat(),
        }
    )


def planning(request):
    """Page principale des affectations et des effectifs enfants."""
    if request.GET.get("mode") == "temps-travail":
        return redirect("/recapitulatif/?onglet=temps-travail")
    from .models import FonctionOperationnelle
    from .services.responsabilites import regle_eligibilite_fonction
    fonctions = list(FonctionOperationnelle.objects.filter(active=True))
    for fonction in fonctions:
        fonction.regle_eligibilite = regle_eligibilite_fonction(fonction)
    return render(request, "planning.html", {
        "active_page": "planning",
        "fonctions_responsabilite": fonctions,
    })



def temps_travail(request):
    """Conserve les anciens liens vers la saisie désormais intégrée à Paie."""
    return redirect("/recapitulatif/?onglet=temps-travail")

def gestion(request):
    """Gestion des référentiels, documents et informations du portail animateur."""
    onglet = request.GET.get("onglet", "lieux")

    if request.method == "POST" and request.POST.get("module") == "informations-animateurs":
        action = request.POST.get("action", "enregistrer")
        information_id = request.POST.get("information_id")
        information = None
        if information_id:
            try:
                information = InformationAnimateur.objects.get(pk=information_id)
            except (InformationAnimateur.DoesNotExist, TypeError, ValueError):
                messages.error(request, "Cette information n’existe plus.")
                return redirect("/gestion/?onglet=informations")

        if action == "supprimer":
            if information is None:
                messages.error(request, "Information introuvable.")
            else:
                information.delete()
                messages.success(request, "L’information a été supprimée.")
            return redirect("/gestion/?onglet=informations")

        if action in {"publier", "depublier"}:
            if information is None:
                messages.error(request, "Information introuvable.")
            else:
                information.publie = action == "publier"
                information.save(update_fields=["publie", "date_modification"])
                messages.success(
                    request,
                    "L’information est maintenant publiée." if information.publie else "L’information a été remise en brouillon.",
                )
            return redirect("/gestion/?onglet=informations")

        titre = request.POST.get("titre", "").strip()
        message = request.POST.get("message", "").strip()
        date_debut = parse_date(request.POST.get("date_debut", ""))
        date_fin = parse_date(request.POST.get("date_fin", ""))
        importance = request.POST.get("importance", InformationAnimateur.IMPORTANCE_NORMALE)
        cible = request.POST.get("cible", "tous")
        tous_animateurs = cible != "selection"
        animateur_ids = request.POST.getlist("animateur_ids")
        publie = request.POST.get("publie") == "on"

        erreurs = []
        if not titre:
            erreurs.append("Le titre est obligatoire.")
        if not message:
            erreurs.append("Le message est obligatoire.")
        if date_debut is None or date_fin is None:
            erreurs.append("La période d’affichage doit être renseignée.")
        elif date_fin < date_debut:
            erreurs.append("La date de fin doit être postérieure ou égale à la date de début.")
        if importance not in dict(InformationAnimateur.IMPORTANCE_CHOICES):
            erreurs.append("Le niveau d’importance est invalide.")
        if not tous_animateurs and not animateur_ids:
            erreurs.append("Sélectionne au moins un animateur ou choisis Toute l’équipe.")

        animateurs_cibles = list(Animateur.objects.filter(pk__in=animateur_ids)) if animateur_ids else []
        if not tous_animateurs and len(animateurs_cibles) != len(set(animateur_ids)):
            erreurs.append("Une partie des animateurs sélectionnés n’existe plus.")

        if erreurs:
            for erreur in erreurs:
                messages.error(request, erreur)
            query = "?onglet=informations"
            if information is not None:
                query += f"&information={information.pk}"
            return redirect(f"/gestion/{query}")

        if information is None:
            information = InformationAnimateur(auteur=request.user)
        information.titre = titre
        information.message = message
        information.date_debut = date_debut
        information.date_fin = date_fin
        information.importance = importance
        information.tous_animateurs = tous_animateurs
        information.publie = publie
        try:
            information.full_clean()
        except ValidationError as exc:
            for messages_champ in exc.message_dict.values():
                for erreur in messages_champ:
                    messages.error(request, erreur)
            query = "?onglet=informations"
            if information.pk:
                query += f"&information={information.pk}"
            return redirect(f"/gestion/{query}")
        information.save()
        information.animateurs.set([] if tous_animateurs else animateurs_cibles)
        messages.success(request, "L’information a été enregistrée.")
        return redirect("/gestion/?onglet=informations")

    information_editee = None
    if onglet == "informations" and request.GET.get("information"):
        try:
            information_editee = InformationAnimateur.objects.prefetch_related("animateurs").get(
                pk=request.GET.get("information")
            )
        except (InformationAnimateur.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Cette information n’existe plus.")

    return render(
        request,
        "gestion.html",
        {
            "active_page": "gestion",
            "gestion_onglet": onglet,
            "masquer_selecteurs_configuration": True,
            "informations_animateurs": InformationAnimateur.objects.select_related("auteur").prefetch_related("animateurs"),
            "information_editee": information_editee,
            "information_editee_ids": [item.pk for item in information_editee.animateurs.all()] if information_editee else [],
            "animateurs_informations": Animateur.objects.order_by("nom", "prenom"),
        },
    )


def gestion_annees_scolaires(request):
    """Expose le suivi des années dans l'interface Direction."""
    if not request.user.has_perm("animateurs.view_anneescolaire"):
        raise PermissionDenied
    annees_scolaires = AnneeScolaire.objects.all()
    return render(request, "gestion_annees_scolaires.html", {
        "active_page": "gestion",
        "gestion_onglet": "annees-scolaires",
        "masquer_selecteurs_configuration": True,
        "annees_scolaires": annees_scolaires,
        "peut_creer_annee": request.user.has_perm("animateurs.add_anneescolaire"),
        "peut_modifier_annee": request.user.has_perm("animateurs.change_anneescolaire"),
        "reouverture_possible": not annees_scolaires.filter(statut=AnneeScolaire.Statut.ACTIVE).exists(),
    })


def employes(request):
    """Annuaire des salariés, séparé de la rubrique Gestion."""
    return render(request, "employes.html", {"active_page": "employes"})


def employe_detail(request, animateur_id=None):
    """Compatibilité avec les anciennes adresses de fiches salariés.

    La fiche n'est plus rendue dans une page séparée : elle s'ouvre dans le
    panneau droit de l'espace Salariés.
    """
    if animateur_id is None:
        return redirect("/employes/?nouveau=1")
    return redirect(f"/employes/?salarie={animateur_id}")


def recapitulatif(request):
    """Tableau de bord : jours travaillés par animateur/centre et alertes
    de suivi (animateurs jamais affectés, centres inutilisés, etc.)."""
    return render(request, "recapitulatif.html", {"active_page": "recapitulatif"})


def documents(request):
    """La bibliothèque animateur est intégrée au tableau de bord."""
    if not est_direction(request.user):
        return redirect("accueil")
    return render(request, "documents_partages.html", {"active_page": "documents"})


def mes_disponibilites(request):
    """Espace personnel permettant à un animateur de déclarer ses jours disponibles."""
    if est_direction(request.user):
        return redirect("employes")
    return redirect("mon_profil")


def emails(request):
    """Accès direct au module d’e-mails intégré à l’administration."""
    return redirect("/administration/?onglet=emails")


def administration(request):
    """Exports, e-mails et gestion simple des comptes superuser."""
    User = get_user_model()
    message_admin = ""
    erreur_admin = ""

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create_superuser":
            username = request.POST.get("username", "").strip()
            email = request.POST.get("email", "").strip()
            password = request.POST.get("password", "")
            confirmation = request.POST.get("confirmation", "")
            if not username:
                erreur_admin = "Le nom d’utilisateur est obligatoire."
            elif User.objects.filter(username__iexact=username).exists():
                erreur_admin = "Ce nom d’utilisateur existe déjà."
            elif password != confirmation:
                erreur_admin = "Les deux mots de passe ne correspondent pas."
            else:
                erreur_admin = valider_mot_de_passe(password)
                if not erreur_admin:
                    User.objects.create_superuser(username=username, email=email, password=password)
                    message_admin = f"Le superuser {username} a été créé."
        elif action == "delete_superuser":
            try:
                cible = User.objects.get(pk=request.POST.get("user_id"), is_superuser=True)
            except (User.DoesNotExist, ValueError, TypeError):
                erreur_admin = "Compte superuser introuvable."
            else:
                if cible.pk == request.user.pk:
                    erreur_admin = "Tu ne peux pas supprimer le compte avec lequel tu es connectée."
                elif User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
                    erreur_admin = "Impossible de supprimer le dernier superuser actif."
                else:
                    nom = cible.username
                    cible.delete()
                    message_admin = f"Le superuser {nom} a été supprimé."
        elif action == "change_own_password":
            ancien = request.POST.get("old_password", "")
            nouveau = request.POST.get("new_password", "")
            confirmation = request.POST.get("new_password_confirmation", "")
            if not request.user.check_password(ancien):
                erreur_admin = "L’ancien mot de passe est incorrect."
            elif nouveau != confirmation:
                erreur_admin = "Les deux nouveaux mots de passe ne correspondent pas."
            else:
                erreur_admin = valider_mot_de_passe(nouveau, utilisateur=request.user)
                if not erreur_admin:
                    request.user.set_password(nouveau)
                    request.user.save(update_fields=["password"])
                    update_session_auth_hash(request, request.user)
                    message_admin = "Ton mot de passe a été modifié."

    today = timezone.localdate()
    periodes = list(PeriodeScolaire.objects.order_by("debut", "fin", "ordre", "id"))

    # L'export s'ouvre sur les vacances qui contiennent aujourd'hui. Entre deux
    # semaines, la période enregistrée la plus proche reste le meilleur repère.
    periode_export_courante = min(
        periodes,
        key=lambda periode: 0
        if periode.debut <= today <= periode.fin
        else min(abs((periode.debut - today).days), abs((periode.fin - today).days)),
        default=None,
    )
    for periode in periodes:
        periode.export_annee_ouverte = bool(
            periode_export_courante
            and periode.annee_scolaire == periode_export_courante.annee_scolaire
        )
        periode.export_vacances_ouvertes = bool(
            periode.export_annee_ouverte
            and periode.categorie_vacances == periode_export_courante.categorie_vacances
        )
    semaines_export = sorted(
        periodes,
        key=lambda periode: (-int(periode.annee_scolaire[:4]), periode.debut, periode.ordre, periode.nom),
    )

    dates_disponibles = set()
    for periode in periodes:
        nombre_jours = (periode.fin - periode.debut).days
        dates_disponibles.update(
            periode.debut + datetime.timedelta(days=decalage) for decalage in range(nombre_jours + 1)
        )

    if not dates_disponibles:
        dates_disponibles.update(today + datetime.timedelta(days=decalage) for decalage in range(-183, 184))

    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois_fr = [
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ]
    dates_triees = sorted(dates_disponibles)
    options_dates = [
        {
            "value": jour.isoformat(),
            "label": f"{jours_fr[jour.weekday()].capitalize()} {jour.day} {mois_fr[jour.month - 1]} {jour.year}",
        }
        for jour in dates_triees
    ]

    date_fin = (
        today
        if today in dates_disponibles
        else min(
            dates_triees,
            key=lambda jour: abs((jour - today).days),
        )
    )
    debut_mois = date_fin.replace(day=1)
    dates_avant_fin = [jour for jour in dates_triees if jour <= date_fin]
    date_debut = (
        debut_mois if debut_mois in dates_disponibles else (dates_avant_fin[0] if dates_avant_fin else dates_triees[0])
    )

    active_tab = request.POST.get("onglet") or request.GET.get("onglet") or "export"
    if active_tab not in {"export", "emails", "superusers", "comptes-animateurs", "mot-de-passe"}:
        active_tab = "export"

    return render(
        request,
        "administration.html",
        {
            "active_page": "emails" if active_tab == "emails" else "administration",
            "active_tab": active_tab,
            "periode_debut": date_debut.isoformat(),
            "periode_fin": date_fin.isoformat(),
            "options_dates": options_dates,
            "semaines_export": semaines_export,
            "superusers": User.objects.filter(is_superuser=True).order_by("username"),
            "message_admin": message_admin,
            "erreur_admin": erreur_admin,
        },
    )


def _periode_export(request):
    ids_bruts = request.GET.getlist("periode_ids")
    if ids_bruts:
        try:
            ids = {int(valeur) for valeur in ids_bruts}
        except ValueError:
            return None, None, None, "La sélection des semaines est invalide."
        periodes = list(PeriodeScolaire.objects.filter(pk__in=ids))
        if not ids or len(periodes) != len(ids):
            return None, None, None, "Une semaine sélectionnée est introuvable."
        jours = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in periodes
            for decalage in range((periode.fin - periode.debut).days + 1)
        }
        return min(jours), max(jours), jours, None

    debut = parse_date(request.GET.get("debut", ""))
    fin = parse_date(request.GET.get("fin", ""))
    if not debut or not fin:
        return None, None, None, "Sélectionne au moins une semaine."
    if fin < debut:
        return None, None, None, "La date de fin doit être postérieure ou égale à la date de début."
    if (fin - debut).days > 366:
        return None, None, None, "La période d'export ne peut pas dépasser 366 jours."
    return debut, fin, None, None


def api_verification_export_planning(request):
    """Vérifie les horaires juste avant le téléchargement d'un planning."""
    debut, fin, jours_selectionnes, erreur = _periode_export(request)
    if erreur:
        return JsonResponse({"error": erreur}, status=400)
    manquants = horaires_manquants_export(debut, fin, jours_selectionnes)
    return JsonResponse(
        {
            "nombre": len(manquants),
            "manquants": manquants[:20],
        }
    )


def export_planning_excel(request):
    debut, fin, jours_selectionnes, erreur = _periode_export(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    contenu = generer_planning_excel(debut, fin, jours_selectionnes)
    response = HttpResponse(
        contenu,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="planning_{debut:%Y%m%d}_{fin:%Y%m%d}.xlsx"'
    return response


def export_planning_pdf(request):
    debut, fin, jours_selectionnes, erreur = _periode_export(request)
    if erreur:
        return HttpResponse(erreur, status=400, content_type="text/plain; charset=utf-8")
    contenu = generer_planning_pdf(debut, fin, jours_selectionnes)
    response = HttpResponse(contenu, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="planning_{debut:%Y%m%d}_{fin:%Y%m%d}.pdf"'
    return response
