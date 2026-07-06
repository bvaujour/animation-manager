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
    list_display = ("nom", "code", "couleur")


class PreferenceCentreInline(admin.TabularInline):
    model = PreferenceCentre
    extra = 1
    ordering = ["ordre"]


class DisponibiliteInline(admin.TabularInline):
    model = Disponibilite
    extra = 1
    ordering = ["debut"]


@admin.register(Animateur)
class AnimateurAdmin(admin.ModelAdmin):

    inlines = [PreferenceCentreInline, DisponibiliteInline]

    def formfield_for_manytomany(
        self,
        db_field,
        request,
        **kwargs
    ):

        if db_field.name == "qualifications":

            kwargs["widget"] = CheckboxSelectMultiple

        return super().formfield_for_manytomany(
            db_field,
            request,
            **kwargs
        )


@admin.register(Affectation)
class AffectationAdmin(admin.ModelAdmin):
    list_display = ("animateur", "centre", "debut", "fin")
    list_filter = ("centre", "animateur")
    date_hierarchy = "debut"


@admin.register(Disponibilite)
class DisponibiliteAdmin(admin.ModelAdmin):
    list_display = ("animateur", "debut", "fin")
    list_filter = ("animateur",)
    date_hierarchy = "debut"