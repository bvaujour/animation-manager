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
from django.contrib.auth import views as auth_views
from django.urls import path

from animateurs.access import (
    connexion_requise_page,
    direction_requise,
    direction_requise_api,
    disponibilites_personnelles_api,
    lecture_partagee_api,
)
from animateurs.views import (
    accueil,
    administration,
    api_affectation_create,
    api_affectation_detail,
    api_animateur_detail,
    api_animateurs,
    api_centre_detail,
    api_centres,
    api_centres_reordonner,
    api_contact_email_detail,
    api_contacts_email,
    api_disponibilite_detail,
    api_disponibilites,
    api_document_detail,
    api_documents,
    api_emails_animateur,
    api_envois_email,
    api_groupe_detail,
    api_effectifs_enfants_groupe,
    api_groupes,
    api_groupes_reordonner,
    api_modele_email_detail,
    api_modeles_email,
    api_periode_scolaire_detail,
    api_periodes_scolaires,
    api_periodes_scolaires_importer,
    api_periodes_scolaires_previsualiser,
    api_planning,
    api_planning_auto,
    api_planning_plage,
    api_qualification_detail,
    api_qualifications,
    api_recapitulatif,
    api_tableau_de_bord,
    changer_mot_de_passe,
    documents,
    emails,
    employe_detail,
    employes,
    export_planning_excel,
    export_planning_pdf,
    gestion,
    mes_disponibilites,
    planning,
    recapitulatif,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('connexion/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('deconnexion/', auth_views.LogoutView.as_view(), name='logout'),
    path('changer-mot-de-passe/', connexion_requise_page(changer_mot_de_passe), name='changer_mot_de_passe'),

    # --- Pages ---
    path("", connexion_requise_page(accueil), name="accueil"),
    path("documents/", connexion_requise_page(documents), name="documents"),
    path("mes-disponibilites/", connexion_requise_page(mes_disponibilites), name="mes_disponibilites"),
    path("emails/", direction_requise(emails), name="emails"),
    path("administration/", direction_requise(administration), name="administration"),
    path("administration/export-planning.xlsx", direction_requise(export_planning_excel), name="export_planning_excel"),
    path("administration/export-planning.pdf", direction_requise(export_planning_pdf), name="export_planning_pdf"),
    path("planning/", direction_requise(planning), name="planning"),
    path("gestion/", direction_requise(gestion), name="gestion"),
    path("employes/", direction_requise(employes), name="employes"),
    path("employes/nouveau/", direction_requise(employe_detail), name="employe_nouveau"),
    path("employes/<int:animateur_id>/", direction_requise(employe_detail), name="employe_detail"),
    path("recapitulatif/", direction_requise(recapitulatif), name="recapitulatif"),

    # --- API : animateurs ---
    path("api/animateurs/", direction_requise_api(api_animateurs), name="api_animateurs"),
    path("api/animateurs/<int:animateur_id>/", direction_requise_api(api_animateur_detail), name="api_animateur_detail"),
    path("api/animateurs/<int:animateur_id>/disponibilites/", disponibilites_personnelles_api(api_disponibilites), name="api_disponibilites"),
    path("api/animateurs/<int:animateur_id>/disponibilites/<int:disponibilite_id>/", disponibilites_personnelles_api(api_disponibilite_detail), name="api_disponibilite_detail"),
    path("api/animateurs/<int:animateur_id>/emails/", direction_requise_api(api_emails_animateur), name="api_emails_animateur"),

    # --- API : centres ---
    path("api/centres/", lecture_partagee_api(api_centres), name="api_centres"),
    path("api/centres/reordonner/", direction_requise_api(api_centres_reordonner), name="api_centres_reordonner"),
    path("api/centres/<int:centre_id>/", direction_requise_api(api_centre_detail), name="api_centre_detail"),
    path("api/centres/<int:centre_id>/groupes/", lecture_partagee_api(api_groupes), name="api_groupes"),
    path("api/centres/<int:centre_id>/groupes/reordonner/", direction_requise_api(api_groupes_reordonner), name="api_groupes_reordonner"),
    path("api/groupes/<int:evenement_id>/", direction_requise_api(api_groupe_detail), name="api_groupe_detail"),
    path("api/groupes/<int:evenement_id>/effectifs-enfants/", direction_requise_api(api_effectifs_enfants_groupe), name="api_effectifs_enfants_groupe"),

    # --- API : qualifications ---
    path("api/qualifications/", direction_requise_api(api_qualifications), name="api_qualifications"),
    path("api/qualifications/<int:qualification_id>/", direction_requise_api(api_qualification_detail), name="api_qualification_detail"),

    # --- API : périodes scolaires (bibliothèque indépendante) ---
    path("api/periodes-scolaires/", lecture_partagee_api(api_periodes_scolaires), name="api_periodes_scolaires"),
    path("api/periodes-scolaires/previsualiser/", direction_requise_api(api_periodes_scolaires_previsualiser), name="api_periodes_scolaires_previsualiser"),
    path("api/periodes-scolaires/importer/", direction_requise_api(api_periodes_scolaires_importer), name="api_periodes_scolaires_importer"),
    path("api/periodes-scolaires/<int:periode_id>/", direction_requise_api(api_periode_scolaire_detail), name="api_periode_scolaire_detail"),

    # --- API : planning (lecture + action groupée "vider" + auto) ---
    path("api/planning/", lecture_partagee_api(api_planning), name="api_planning"),
    path("api/planning/plage/", direction_requise_api(api_planning_plage), name="api_planning_plage"),
    path("api/planning/auto/", direction_requise_api(api_planning_auto), name="api_planning_auto"),

    # --- API : affectations individuelles (créées depuis le planning) ---
    path("api/affectations/", direction_requise_api(api_affectation_create), name="api_affectation_create"),
    path("api/affectations/<int:affectation_id>/", direction_requise_api(api_affectation_detail), name="api_affectation_detail"),

    # --- API : tableau de bord et récapitulatif ---
    path("api/tableau-de-bord/", direction_requise_api(api_tableau_de_bord), name="api_tableau_de_bord"),

    path("api/recapitulatif/", direction_requise_api(api_recapitulatif), name="api_recapitulatif"),

    # --- API : documents ---
    path("api/documents/", lecture_partagee_api(api_documents), name="api_documents"),
    path("api/documents/<int:document_id>/", direction_requise_api(api_document_detail), name="api_document_detail"),
    path("api/envois-email/", direction_requise_api(api_envois_email), name="api_envois_email"),
    path("api/contacts-email/", direction_requise_api(api_contacts_email), name="api_contacts_email"),
    path("api/contacts-email/<int:contact_id>/", direction_requise_api(api_contact_email_detail), name="api_contact_email_detail"),
    path("api/modeles-email/", direction_requise_api(api_modeles_email), name="api_modeles_email"),
    path("api/modeles-email/<int:modele_id>/", direction_requise_api(api_modele_email_detail), name="api_modele_email_detail"),
]

# En développement avec le stockage local (pas de S3 Supabase configuré),
# Django doit servir lui-même les fichiers uploadés depuis MEDIA_ROOT.
# En production (S3) ceci est sans effet car les URLs pointent vers S3.
if settings.DEBUG and getattr(settings, "MEDIA_ROOT", None):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
