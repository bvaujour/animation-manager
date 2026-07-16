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
    Animateur,
    Centre,
    DateExclueEvenement,
    Evenement,
    Disponibilite,
    Document,
    EnvoiEmail,
    DestinataireEnvoiEmail,
    PreferenceCentre,
    Qualification
)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("titre", "permanent", "periode_debut", "periode_fin", "date_ajout")
    list_filter = ("permanent",)
    search_fields = ("titre",)
    date_hierarchy = "date_ajout"


@admin.register(Qualification)
class QualificationAdmin(admin.ModelAdmin):
    list_display = ("nom", "selectionnable_remplissage_auto")
    list_filter = ("selectionnable_remplissage_auto",)
    search_fields = ("nom",)



@admin.register(Centre)
class CentreAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "couleur", "effectif_cible")


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
        "active",
        "ordre",
    )
    list_filter = ("centre", "active")
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
    fields = ("centre", "est_prefere")
    ordering = ["-est_prefere", "centre__nom"]


class DisponibiliteInline(admin.TabularInline):
    """Permet de saisir les plages de disponibilité d'un animateur
    directement depuis sa fiche."""
    model = Disponibilite
    extra = 1
    ordering = ["debut"]


@admin.register(Animateur)
class AnimateurAdmin(admin.ModelAdmin):

    list_display = (
        "prenom",
        "nom",
        "telephone",
        "email",
        "date_naissance",
        "age",
        "couleur",
        "evenement_preferee",
    )
    search_fields = ("prenom", "nom", "telephone", "email")
    inlines = [PreferenceCentreInline, DisponibiliteInline]

    def formfield_for_manytomany(
        self,
        db_field,
        request,
        **kwargs
    ):
        # Affiche les qualifications sous forme de cases à cocher plutôt
        # que la liste à sélection multiple par défaut de Django (plus
        # lisible avec peu de qualifications).
        if db_field.name == "qualifications":

            kwargs["widget"] = CheckboxSelectMultiple

        return super().formfield_for_manytomany(
            db_field,
            request,
            **kwargs
        )


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


class DestinataireEnvoiEmailInline(admin.TabularInline):
    model = DestinataireEnvoiEmail
    extra = 0
    can_delete = False
    readonly_fields = ("prenom", "nom", "email", "statut", "erreur", "date_traitement")


@admin.register(EnvoiEmail)
class EnvoiEmailAdmin(admin.ModelAdmin):
    list_display = ("objet", "date_creation", "nombre_destinataires", "nombre_envoyes", "nombre_echecs", "mode_test")
    list_filter = ("mode_test", "date_creation")
    search_fields = ("objet", "message", "destinataires__email", "destinataires__nom")
    readonly_fields = ("date_creation", "documents_titres", "nombre_destinataires", "nombre_envoyes", "nombre_echecs", "mode_test")
    filter_horizontal = ("documents",)
    inlines = [DestinataireEnvoiEmailInline]
