from django.contrib import admin
from django.forms import CheckboxSelectMultiple

from .models import (
    Animateur,
    Document,
    Qualification
)


admin.site.register(Document)

admin.site.register(Qualification)


@admin.register(Animateur)
class AnimateurAdmin(admin.ModelAdmin):

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