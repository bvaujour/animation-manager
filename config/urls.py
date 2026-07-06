"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from animateurs.views import accueil
from animateurs.views import documents
from animateurs.views import planning, api_planning
from animateurs.views import test
from animateurs.views import gestion
from animateurs.views import api_animateurs, api_animateur_detail, api_disponibilites
from animateurs.views import api_affectation_create, api_affectation_detail
from animateurs.views import api_centres, api_centre_detail
from animateurs.views import api_qualifications, api_qualification_detail

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", accueil, name="accueil"),
    path("documents/", documents, name="documents"),
    path("planning/", planning, name="planning"),
    path("gestion/", gestion, name="gestion"),
    path("test/", test, name="test"),

    path("api/planning/", api_planning, name="api_planning"),

    path("api/animateurs/", api_animateurs, name="api_animateurs"),
    path("api/animateurs/<int:animateur_id>/", api_animateur_detail, name="api_animateur_detail"),
    path("api/animateurs/<int:animateur_id>/disponibilites/", api_disponibilites, name="api_disponibilites"),

    path("api/centres/", api_centres, name="api_centres"),
    path("api/centres/<int:centre_id>/", api_centre_detail, name="api_centre_detail"),

    path("api/qualifications/", api_qualifications, name="api_qualifications"),
    path("api/qualifications/<int:qualification_id>/", api_qualification_detail, name="api_qualification_detail"),

    path("api/affectations/", api_affectation_create, name="api_affectation_create"),
    path("api/affectations/<int:affectation_id>/", api_affectation_detail, name="api_affectation_detail"),
]
