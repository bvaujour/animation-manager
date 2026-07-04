from django.contrib import admin

# Register your models here.
from .models import Animateur, Document

admin.site.register(Document)
admin.site.register(Animateur)