"""
Configuration des URLs du projet.

Toutes les routes de l'app "animateurs" sont déclarées ici (pas de
urls.py séparé dans l'app elle-même, le projet est assez petit pour
rester simple). Organisation :
  - pages HTML en haut ;
  - endpoints API ensuite, groupés par ressource (animateurs / centres /
    qualifications / planning / récapitulatif), dans le même ordre que
    dans animateurs/views.py pour s'y retrouver facilement.
"""
from django.contrib import admin
from django.urls import path

from animateurs.views import (
    accueil,
    documents,
    gestion,
    planning,
    recapitulatif,
    test,
)
from animateurs.views import (
    api_animateurs,
    api_animateur_detail,
    api_disponibilites,
)
from animateurs.views import (
    api_centres,
    api_centre_detail,
)
from animateurs.views import (
    api_qualifications,
    api_qualification_detail,
)
from animateurs.views import (
    api_planning,
    api_planning_plage,
    api_planning_auto,
    api_affectation_create,
    api_affectation_detail,
)
from animateurs.views import api_recapitulatif
from animateurs.views import api_documents, api_document_detail

urlpatterns = [
    path('admin/', admin.site.urls),

    # --- Pages ---
    path("", accueil, name="accueil"),
    path("documents/", documents, name="documents"),
    path("planning/", planning, name="planning"),
    path("gestion/", gestion, name="gestion"),
    path("recapitulatif/", recapitulatif, name="recapitulatif"),
    path("test/", test, name="test"),

    # --- API : animateurs ---
    path("api/animateurs/", api_animateurs, name="api_animateurs"),
    path("api/animateurs/<int:animateur_id>/", api_animateur_detail, name="api_animateur_detail"),
    path("api/animateurs/<int:animateur_id>/disponibilites/", api_disponibilites, name="api_disponibilites"),

    # --- API : centres ---
    path("api/centres/", api_centres, name="api_centres"),
    path("api/centres/<int:centre_id>/", api_centre_detail, name="api_centre_detail"),

    # --- API : qualifications ---
    path("api/qualifications/", api_qualifications, name="api_qualifications"),
    path("api/qualifications/<int:qualification_id>/", api_qualification_detail, name="api_qualification_detail"),

    # --- API : planning (lecture + actions groupées "vider"/"auto") ---
    path("api/planning/", api_planning, name="api_planning"),
    path("api/planning/plage/", api_planning_plage, name="api_planning_plage"),
    path("api/planning/auto/", api_planning_auto, name="api_planning_auto"),

    # --- API : affectations individuelles (créées depuis le planning) ---
    path("api/affectations/", api_affectation_create, name="api_affectation_create"),
    path("api/affectations/<int:affectation_id>/", api_affectation_detail, name="api_affectation_detail"),

    # --- API : récapitulatif ---
    path("api/recapitulatif/", api_recapitulatif, name="api_recapitulatif"),

    # --- API : documents ---
    path("api/documents/", api_documents, name="api_documents"),
    path("api/documents/<int:document_id>/", api_document_detail, name="api_document_detail"),
]
