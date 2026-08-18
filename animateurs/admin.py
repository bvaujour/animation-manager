"""
Configuration de l'admin Django pour l'app "animateurs".

La popup d'ajout rapide (planning) et la page /gestion/ couvrent les
besoins courants (ajouter/supprimer un animateur, un centre, une
qualification). Cet admin reste utile pour tout ce qu'elles ne
couvrent pas encore : saisir les centres autorisés, les disponibilités,
ou consulter/filtrer l'historique des affectations.
"""

from datetime import timedelta

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Q
from django.forms import CheckboxSelectMultiple
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .admin_forms import ClassificationPeriodesForm

from .models import (
    ActiviteTravailComplementaire,
    Affectation,
    AffiniteGroupeAnimateur,
    Animateur,
    Centre,
    ContactEmailExterne,
    DateExclueEvenement,
    Disponibilite,
    DemandeMateriel,
    Document,
    Evenement,
    Groupe,
    ModeleEmail,
    ModalitePeriscolaire,
    PeriodeScolaire,
    PeriodeCalendrier,
    ParticipationTravailComplementaire,
    ParticipantSejour,
    PrimeJournalierePeriode,
    PreferenceCentre,
    Qualification,
    Sejour,
    Sortie,
    SortieLien,
    SortieParticipation,
    SortieResponsabilite,
    TypeAccueil,
)


@admin.register(TypeAccueil)
class TypeAccueilAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "ordre", "actif")
    list_editable = ("ordre", "actif")
    ordering = ("ordre", "nom")


@admin.register(ModalitePeriscolaire)
class ModalitePeriscolaireAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "jour_entier", "heure_debut", "heure_fin", "actif", "ordre")
    list_editable = ("heure_debut", "heure_fin", "actif", "ordre")


class ParticipantSejourInline(admin.TabularInline):
    model = ParticipantSejour
    extra = 0


@admin.register(Sejour)
class SejourAdmin(admin.ModelAdmin):
    list_display = ("nom", "date_debut", "date_fin", "destination", "periode_vacances", "source_lieu_legacy", "actif")
    list_filter = ("actif", "date_debut")
    search_fields = ("nom", "destination", "hebergement", "source_lieu_legacy__nom")
    filter_horizontal = ("equipe",)
    inlines = (ParticipantSejourInline,)


class ParticipationTravailComplementaireInline(admin.TabularInline):
    model = ParticipationTravailComplementaire
    extra = 0


@admin.register(ActiviteTravailComplementaire)
class ActiviteTravailComplementaireAdmin(admin.ModelAdmin):
    list_display = ("intitule", "type", "type_accueil", "date", "date_modification")
    list_filter = ("type", "type_accueil", "date")
    search_fields = ("intitule", "remarque")
    filter_horizontal = ("periodes",)
    inlines = (ParticipationTravailComplementaireInline,)


@admin.register(PrimeJournalierePeriode)
class PrimeJournalierePeriodeAdmin(admin.ModelAdmin):
    list_display = ("animateur", "periode", "montant", "date_modification")
    list_filter = ("periode",)
    search_fields = ("animateur__prenom", "animateur__nom")


class SortieParticipationInline(admin.TabularInline):
    model = SortieParticipation
    extra = 0


class SortieLienInline(admin.TabularInline):
    model = SortieLien
    extra = 0


class SortieResponsabiliteInline(admin.TabularInline):
    model = SortieResponsabilite
    extra = 0



@admin.register(Sortie)
class SortieAdmin(admin.ModelAdmin):
    list_display = ("nom", "date", "destination", "modifie_le")
    list_filter = ("date",)
    search_fields = ("nom", "destination")
    inlines = (SortieParticipationInline, SortieResponsabiliteInline, SortieLienInline)


@admin.register(ModeleEmail)
class ModeleEmailAdmin(admin.ModelAdmin):
    list_display = ("nom", "actif", "ordre", "date_modification")
    list_editable = ("actif", "ordre")
    list_filter = ("actif",)
    search_fields = ("nom", "objet", "message")
    ordering = ("ordre", "nom")


@admin.register(DemandeMateriel)
class DemandeMaterielAdmin(admin.ModelAdmin):
    list_display = ("materiel", "quantite", "animateur", "centre", "date_besoin", "statut", "date_creation")
    list_filter = ("statut", "centre", "date_besoin")
    search_fields = ("materiel", "animateur__prenom", "animateur__nom")
    date_hierarchy = "date_creation"


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("titre", "permanent", "periode_debut", "periode_fin", "date_ajout")
    list_filter = ("permanent",)
    search_fields = ("titre",)
    date_hierarchy = "date_ajout"


@admin.register(Qualification)
class QualificationAdmin(admin.ModelAdmin):
    list_display = ("nom", "est_statut", "statut", "selectionnable_remplissage_auto")
    list_filter = ("est_statut", "statut", "selectionnable_remplissage_auto")
    search_fields = ("nom",)


@admin.register(PeriodeScolaire)
class PeriodeScolaireAdmin(admin.ModelAdmin):
    change_list_template = "admin/animateurs/periodescolaire/change_list.html"
    list_display = ("nom", "type_accueil", "annee_scolaire", "zone", "debut", "fin")
    list_filter = ("type_accueil", "annee_scolaire", "zone")
    search_fields = ("nom", "description_source")
    ordering = ("-annee_scolaire", "zone", "debut")

    def changelist_view(self, request, extra_context=None):
        context = {**(extra_context or {}), "peut_classifier_periodes": self.has_change_permission(request)}
        return super().changelist_view(request, extra_context=context)

    def get_urls(self):
        return [
            path(
                "classification/",
                self.admin_site.admin_view(self.classification_periodes),
                name="animateurs_periodescolaire_classification",
            ),
        ] + super().get_urls()

    @staticmethod
    def _semaines_comprises(periode):
        lundi = periode.debut - timedelta(days=periode.debut.weekday())
        semaines = []
        while lundi <= periode.fin:
            semaines.append((max(lundi, periode.debut), min(lundi + timedelta(days=6), periode.fin)))
            lundi += timedelta(days=7)
        return semaines

    def _details_periodes(self, periodes, selected_ids=()):
        selected_ids = {str(pk) for pk in selected_ids}
        details = []
        for periode in periodes:
            groupes = list(
                Evenement.objects.select_related("centre")
                .filter(Q(permanent=True) | Q(periodes_scolaires=periode))
                .order_by("centre__nom", "nom")
                .distinct()
            )
            details.append({
                "periode": periode,
                "semaines": self._semaines_comprises(periode),
                "groupes": groupes,
                "centres": sorted({groupe.centre.nom for groupe in groupes}),
                "selected": str(periode.pk) in selected_ids,
            })
        return details

    def classification_periodes(self, request):
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied

        confirmation = request.method == "POST" and "confirmer" in request.POST
        form = ClassificationPeriodesForm(request.POST or None)
        apercu = None

        if request.method == "POST" and form.is_valid():
            periodes = list(form.cleaned_data["periode_ids"])
            type_accueil = form.cleaned_data["type_accueil"]
            if confirmation:
                with transaction.atomic():
                    ids = [periode.pk for periode in periodes]
                    verrouillees = list(
                        PeriodeScolaire.objects.select_for_update().filter(
                            pk__in=ids,
                            type_accueil__isnull=True,
                        )
                    )
                    PeriodeScolaire.objects.filter(pk__in=[p.pk for p in verrouillees]).update(
                        type_accueil=type_accueil
                    )
                messages.success(
                    request,
                    f"{len(verrouillees)} période(s) classée(s) dans « {type_accueil.nom} ».",
                )
                return HttpResponseRedirect(reverse("admin:animateurs_periodescolaire_classification"))
            apercu = {
                "type_accueil": type_accueil,
                "details": self._details_periodes(periodes),
                "ids": [periode.pk for periode in periodes],
            }

        periodes_non_classees = PeriodeScolaire.objects.filter(type_accueil__isnull=True).order_by(
            "-debut", "nom"
        )
        context = {
            **self.admin_site.each_context(request),
            "title": "Classification des périodes",
            "opts": self.model._meta,
            "form": form,
            "apercu": apercu,
            "details_periodes": self._details_periodes(
                periodes_non_classees,
                request.POST.getlist("periode_ids") if request.method == "POST" else (),
            ),
        }
        return TemplateResponse(request, "admin/animateurs/periodescolaire/classification.html", context)


@admin.register(PeriodeCalendrier)
class PeriodeCalendrierAdmin(admin.ModelAdmin):
    list_display = ("nom", "categorie", "annee_scolaire", "zone", "debut", "fin")
    list_filter = ("categorie", "annee_scolaire", "zone", "types_accueil")
    filter_horizontal = ("types_accueil",)


@admin.register(Centre)
class CentreAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "couleur", "effectif_cible")
    filter_horizontal = ("types_accueil",)


@admin.register(Groupe)
class GroupeAdmin(admin.ModelAdmin):
    list_display = ("nom", "enfants_par_animateur_defaut")
    search_fields = ("nom",)


class DateExclueEvenementInline(admin.TabularInline):
    model = DateExclueEvenement
    extra = 0
    ordering = ("date",)


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    list_display = (
        "nom",
        "centre",
        "effectif_cible",
        "enfants_par_animateur_defaut",
        "ordre",
    )
    list_filter = ("centre", "ferme_jours_feries")
    search_fields = ("nom", "centre__nom")
    ordering = ("centre__nom", "ordre", "nom")
    inlines = [DateExclueEvenementInline]
    filter_horizontal = ("types_accueil", "periodes_scolaires")


# --- Inlines affichés directement sur la fiche d'un animateur ---
# (plutôt que d'avoir à naviguer vers un autre écran pour chaque
# centre autorisé de centre ou chaque plage de disponibilité)


class PreferenceCentreInline(admin.TabularInline):
    """Permet d'ajouter les centres où l'animateur peut être affecté
    directement depuis sa fiche, sans passer par un écran séparé."""

    model = PreferenceCentre
    extra = 1
    fields = ("centre", "est_prefere", "est_interdit")
    ordering = ["-est_prefere", "centre__nom"]


class DisponibiliteInline(admin.TabularInline):
    """Permet de saisir les plages de disponibilité d'un animateur
    directement depuis sa fiche."""

    model = Disponibilite
    extra = 1
    ordering = ["debut"]


class AffiniteGroupeAnimateurInline(admin.TabularInline):
    """Affiche les scores calculés automatiquement pour chaque groupe."""

    model = AffiniteGroupeAnimateur
    extra = 0
    can_delete = False
    readonly_fields = (
        "evenement",
        "jours_travailles",
        "dernier_jour_travaille",
        "modifie_le",
    )
    fields = readonly_fields
    ordering = ("-jours_travailles",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Animateur)
class AnimateurAdmin(admin.ModelAdmin):
    list_display = (
        "prenom",
        "utilisateur",
        "nom",
        "telephone",
        "email",
        "date_naissance",
        "paie_jour",
        "age",
        "evenement_preferee",
    )
    search_fields = ("prenom", "nom", "telephone", "email", "adresse", "numero_securite_sociale")
    inlines = [PreferenceCentreInline, DisponibiliteInline, AffiniteGroupeAnimateurInline]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        # Affiche les qualifications sous forme de cases à cocher plutôt
        # que la liste à sélection multiple par défaut de Django (plus
        # lisible avec peu de qualifications).
        if db_field.name == "qualifications":
            kwargs["widget"] = CheckboxSelectMultiple

        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(AffiniteGroupeAnimateur)
class AffiniteGroupeAnimateurAdmin(admin.ModelAdmin):
    list_display = (
        "animateur",
        "evenement",
        "jours_travailles",
        "dernier_jour_travaille",
        "modifie_le",
    )
    list_filter = ("evenement__centre", "evenement")
    search_fields = (
        "animateur__prenom",
        "animateur__nom",
        "evenement__nom",
        "evenement__centre__nom",
    )
    readonly_fields = (
        "animateur",
        "evenement",
        "jours_travailles",
        "dernier_jour_travaille",
        "modifie_le",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Affectation)
class AffectationAdmin(admin.ModelAdmin):
    """Vue d'ensemble/filtrable du planning, utile pour vérifier ou
    corriger des affectations en masse sans passer par l'interface
    glisser-déposer."""

    list_display = ("animateur", "centre", "evenement", "debut", "fin")
    list_filter = ("centre", "evenement", "animateur")
    date_hierarchy = "debut"


@admin.register(Disponibilite)
class DisponibiliteAdmin(admin.ModelAdmin):
    list_display = ("animateur", "debut", "fin")
    list_filter = ("animateur",)
    date_hierarchy = "debut"


@admin.register(ContactEmailExterne)
class ContactEmailExterneAdmin(admin.ModelAdmin):
    list_display = ("nom", "prenom", "email", "organisation", "actif")
    list_filter = ("actif", "organisation")
    search_fields = ("nom", "prenom", "email", "organisation")
