"""
Configuration de l'admin Django pour l'app "animateurs".

La popup d'ajout rapide (planning) et la page /gestion/ couvrent les
besoins courants (ajouter/supprimer un animateur, un centre, une
qualification). Cet admin reste utile pour tout ce qu'elles ne
couvrent pas encore : saisir les centres autorisés, les disponibilités,
ou consulter/filtrer l'historique des affectations.
"""

from django.contrib import admin
from django.forms import CheckboxSelectMultiple

from .models import (
    Affectation,
    AffiniteGroupeAnimateur,
    Animateur,
    Centre,
    ContactEmailExterne,
    DateExclueEvenement,
    Disponibilite,
    Document,
    Evenement,
    Groupe,
    ModeleEmail,
    PeriodeScolaire,
    PreferenceCentre,
    Qualification,
)


@admin.register(ModeleEmail)
class ModeleEmailAdmin(admin.ModelAdmin):
    list_display = ("nom", "actif", "ordre", "date_modification")
    list_editable = ("actif", "ordre")
    list_filter = ("actif",)
    search_fields = ("nom", "objet", "message")
    ordering = ("ordre", "nom")


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
    list_display = ("nom", "annee_scolaire", "zone", "debut", "fin")
    list_filter = ("annee_scolaire", "zone")
    search_fields = ("nom", "description_source")
    ordering = ("-annee_scolaire", "zone", "debut")


@admin.register(Centre)
class CentreAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "couleur", "effectif_cible")


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
