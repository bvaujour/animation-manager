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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from animateurs.views import (
    accueil,
    administration,
    documents,
    evenement,
    gestion,
    planning,
    recapitulatif,
    export_planning_excel,
    export_planning_pdf,
)
from animateurs.views import (
    api_animateurs,
    api_animateur_detail,
    api_disponibilites,
    api_disponibilite_detail,
)
from animateurs.views import (
    api_centres,
    api_centres_reordonner,
    api_centre_detail,
    api_evenements,
    api_evenement_detail,
    api_evenements_reordonner,
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
from animateurs.views import api_documents, api_document_detail, api_envois_email

urlpatterns = [
    path('admin/', admin.site.urls),

    # --- Pages ---
    path("", accueil, name="accueil"),
    path("documents/", documents, name="documents"),
    path("administration/", administration, name="administration"),
    path("administration/export-planning.xlsx", export_planning_excel, name="export_planning_excel"),
    path("administration/export-planning.pdf", export_planning_pdf, name="export_planning_pdf"),
    path("planning/", planning, name="planning"),
    path("evenement/", evenement, name="evenement"),
    path("equipe/", evenement, name="equipe"),
    path("gestion/", gestion, name="gestion"),
    path("recapitulatif/", recapitulatif, name="recapitulatif"),

    # --- API : animateurs ---
    path("api/animateurs/", api_animateurs, name="api_animateurs"),
    path("api/animateurs/<int:animateur_id>/", api_animateur_detail, name="api_animateur_detail"),
    path("api/animateurs/<int:animateur_id>/disponibilites/", api_disponibilites, name="api_disponibilites"),
    path("api/animateurs/<int:animateur_id>/disponibilites/<int:disponibilite_id>/", api_disponibilite_detail, name="api_disponibilite_detail"),

    # --- API : centres ---
    path("api/centres/", api_centres, name="api_centres"),
    path("api/centres/reordonner/", api_centres_reordonner, name="api_centres_reordonner"),
    path("api/centres/<int:centre_id>/", api_centre_detail, name="api_centre_detail"),
    path("api/centres/<int:centre_id>/evenements/", api_evenements, name="api_evenements"),
    path("api/centres/<int:centre_id>/evenements/reordonner/", api_evenements_reordonner, name="api_evenements_reordonner"),
    path("api/evenements/<int:evenement_id>/", api_evenement_detail, name="api_evenement_detail"),

    # --- API : qualifications ---
    path("api/qualifications/", api_qualifications, name="api_qualifications"),
    path("api/qualifications/<int:qualification_id>/", api_qualification_detail, name="api_qualification_detail"),

    # --- API : planning (lecture + action groupée "vider" + auto) ---
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
    path("api/envois-email/", api_envois_email, name="api_envois_email"),
]

# En développement avec le stockage local (pas de S3 Supabase configuré),
# Django doit servir lui-même les fichiers uploadés depuis MEDIA_ROOT.
# En production (S3) ceci est sans effet car les URLs pointent vers S3.
if settings.DEBUG and getattr(settings, "MEDIA_ROOT", None):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
