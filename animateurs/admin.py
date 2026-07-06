"""
Configuration de l'admin Django pour l'app "animateurs".

La popup d'ajout rapide (planning) et la page /gestion/ couvrent les
besoins courants (ajouter/supprimer un animateur, un centre, une
qualification). Cet admin reste utile pour tout ce qu'elles ne
couvrent pas encore : réordonner les préférences de centre d'un
animateur, saisir ses disponibilités, ou consulter/filtrer l'historique
des affectations.
"""

from django.contrib import admin
from django.forms import CheckboxSelectMultiple

from .models import (
    Affectation,
    Animateur,
    Centre,
    Disponibilite,
    Document,
    PreferenceCentre,
    Qualification
)


admin.site.register(Document)

admin.site.register(Qualification)


@admin.register(Centre)
class CentreAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "couleur", "effectif_cible")


# --- Inlines affichés directement sur la fiche d'un animateur ---
# (plutôt que d'avoir à naviguer vers un autre écran pour chaque
# préférence de centre ou chaque plage de disponibilité)

class PreferenceCentreInline(admin.TabularInline):
    """Permet d'ajouter/réordonner les centres préférés d'un animateur
    directement depuis sa fiche, sans passer par un écran séparé."""
    model = PreferenceCentre
    extra = 1
    ordering = ["ordre"]


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
    list_display = ("animateur", "centre", "debut", "fin")
    list_filter = ("centre", "animateur")
    date_hierarchy = "debut"


@admin.register(Disponibilite)
class DisponibiliteAdmin(admin.ModelAdmin):
    list_display = ("animateur", "debut", "fin")
    list_filter = ("animateur",)
    date_hierarchy = "debut"
