"""Routes de l’application Animation Manager, regroupées par domaine."""

from django.contrib.auth import views as auth_views
from django.urls import path

from .access import (
    connexion_requise_page,
    direction_requise,
    direction_requise_api,
    disponibilites_personnelles_api,
    lecture_partagee_api,
)
from .views import (
    accueil,
    administration,
    api_affectation_create,
    api_affectation_detail,
    api_animateur_detail,
    api_animateurs,
    api_centre_detail,
    api_centres,
    api_centres_reordonner,
    api_disponibilite_detail,
    api_disponibilites,
    api_document_detail,
    api_documents,
    api_groupe_detail,
    api_groupe_partage_detail,
    api_groupes,
    api_groupes_partages,
    api_groupes_reordonner,
    api_horaires_affectations_groupe,
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
    api_verification_export_planning,
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
from .views_communications import (
    api_contact_email_detail,
    api_contacts_email,
    api_emails_animateur,
    api_envois_email,
    api_modele_email_detail,
    api_modeles_email,
)
from .views_effectifs import (
    api_effectifs_enfants_groupe,
    api_effectifs_enfants_plage,
    api_effectifs_excel_analyser,
    api_effectifs_excel_gabarit,
    api_effectifs_excel_importer,
    api_effectifs_excel_previsualiser,
    api_profil_import_effectifs_detail,
    api_profils_import_effectifs,
)

urlpatterns = [
    path("connexion/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("changer-mot-de-passe/", connexion_requise_page(changer_mot_de_passe), name="changer_mot_de_passe"),
    # --- Pages ---
    path("", connexion_requise_page(accueil), name="accueil"),
    path("documents/", connexion_requise_page(documents), name="documents"),
    path("mes-disponibilites/", connexion_requise_page(mes_disponibilites), name="mes_disponibilites"),
    path("emails/", direction_requise(emails), name="emails"),
    path("administration/", direction_requise(administration), name="administration"),
    path("administration/export-planning.xlsx", direction_requise(export_planning_excel), name="export_planning_excel"),
    path("administration/export-planning.pdf", direction_requise(export_planning_pdf), name="export_planning_pdf"),
    path(
        "api/export-planning/verification/",
        direction_requise_api(api_verification_export_planning),
        name="api_verification_export_planning",
    ),
    path("planning/", direction_requise(planning), name="planning"),
    path("gestion/", direction_requise(gestion), name="gestion"),
    path("employes/", direction_requise(employes), name="employes"),
    path("employes/nouveau/", direction_requise(employe_detail), name="employe_nouveau"),
    path("employes/<int:animateur_id>/", direction_requise(employe_detail), name="employe_detail"),
    path("recapitulatif/", direction_requise(recapitulatif), name="recapitulatif"),
    # --- API : animateurs ---
    path("api/animateurs/", direction_requise_api(api_animateurs), name="api_animateurs"),
    path(
        "api/animateurs/<int:animateur_id>/", direction_requise_api(api_animateur_detail), name="api_animateur_detail"
    ),
    path(
        "api/animateurs/<int:animateur_id>/disponibilites/",
        disponibilites_personnelles_api(api_disponibilites),
        name="api_disponibilites",
    ),
    path(
        "api/animateurs/<int:animateur_id>/disponibilites/<int:disponibilite_id>/",
        disponibilites_personnelles_api(api_disponibilite_detail),
        name="api_disponibilite_detail",
    ),
    path(
        "api/animateurs/<int:animateur_id>/emails/",
        direction_requise_api(api_emails_animateur),
        name="api_emails_animateur",
    ),
    # --- API : centres ---
    path("api/centres/", lecture_partagee_api(api_centres), name="api_centres"),
    path("api/centres/reordonner/", direction_requise_api(api_centres_reordonner), name="api_centres_reordonner"),
    path("api/centres/<int:centre_id>/", direction_requise_api(api_centre_detail), name="api_centre_detail"),
    path("api/centres/<int:centre_id>/groupes/", lecture_partagee_api(api_groupes), name="api_groupes"),
    path("api/groupes-partages/", direction_requise_api(api_groupes_partages), name="api_groupes_partages"),
    path(
        "api/groupes-partages/<int:groupe_id>/",
        direction_requise_api(api_groupe_partage_detail),
        name="api_groupe_partage_detail",
    ),
    path(
        "api/centres/<int:centre_id>/groupes/reordonner/",
        direction_requise_api(api_groupes_reordonner),
        name="api_groupes_reordonner",
    ),
    path("api/groupes/<int:evenement_id>/", direction_requise_api(api_groupe_detail), name="api_groupe_detail"),
    path(
        "api/groupes/<int:evenement_id>/effectifs-enfants/",
        direction_requise_api(api_effectifs_enfants_groupe),
        name="api_effectifs_enfants_groupe",
    ),
    path(
        "api/effectifs-enfants/",
        direction_requise_api(api_effectifs_enfants_plage),
        name="api_effectifs_enfants_plage",
    ),
    path(
        "api/effectifs-enfants/excel/gabarit/",
        direction_requise_api(api_effectifs_excel_gabarit),
        name="api_effectifs_excel_gabarit",
    ),
    path(
        "api/effectifs-enfants/excel/analyser/",
        direction_requise_api(api_effectifs_excel_analyser),
        name="api_effectifs_excel_analyser",
    ),
    path(
        "api/effectifs-enfants/excel/previsualiser/",
        direction_requise_api(api_effectifs_excel_previsualiser),
        name="api_effectifs_excel_previsualiser",
    ),
    path(
        "api/effectifs-enfants/excel/importer/",
        direction_requise_api(api_effectifs_excel_importer),
        name="api_effectifs_excel_importer",
    ),
    path(
        "api/effectifs-enfants/excel/profils/",
        direction_requise_api(api_profils_import_effectifs),
        name="api_profils_import_effectifs",
    ),
    path(
        "api/effectifs-enfants/excel/profils/<int:profil_id>/",
        direction_requise_api(api_profil_import_effectifs_detail),
        name="api_profil_import_effectifs_detail",
    ),
    # --- API : qualifications ---
    path("api/qualifications/", direction_requise_api(api_qualifications), name="api_qualifications"),
    path(
        "api/qualifications/<int:qualification_id>/",
        direction_requise_api(api_qualification_detail),
        name="api_qualification_detail",
    ),
    # --- API : périodes scolaires (bibliothèque indépendante) ---
    path("api/periodes-scolaires/", lecture_partagee_api(api_periodes_scolaires), name="api_periodes_scolaires"),
    path(
        "api/periodes-scolaires/previsualiser/",
        direction_requise_api(api_periodes_scolaires_previsualiser),
        name="api_periodes_scolaires_previsualiser",
    ),
    path(
        "api/periodes-scolaires/importer/",
        direction_requise_api(api_periodes_scolaires_importer),
        name="api_periodes_scolaires_importer",
    ),
    path(
        "api/periodes-scolaires/<int:periode_id>/",
        direction_requise_api(api_periode_scolaire_detail),
        name="api_periode_scolaire_detail",
    ),
    # --- API : planning (lecture + action groupée "vider" + auto) ---
    path("api/planning/", lecture_partagee_api(api_planning), name="api_planning"),
    path("api/planning/plage/", direction_requise_api(api_planning_plage), name="api_planning_plage"),
    path("api/planning/auto/", direction_requise_api(api_planning_auto), name="api_planning_auto"),
    # --- API : affectations individuelles (créées depuis le planning) ---
    path("api/affectations/", direction_requise_api(api_affectation_create), name="api_affectation_create"),
    path(
        "api/affectations/<int:affectation_id>/",
        direction_requise_api(api_affectation_detail),
        name="api_affectation_detail",
    ),
    path(
        "api/groupes/<int:evenement_id>/horaires-affectations/",
        direction_requise_api(api_horaires_affectations_groupe),
        name="api_horaires_affectations_groupe",
    ),
    # --- API : tableau de bord et récapitulatif ---
    path("api/tableau-de-bord/", direction_requise_api(api_tableau_de_bord), name="api_tableau_de_bord"),
    path("api/recapitulatif/", direction_requise_api(api_recapitulatif), name="api_recapitulatif"),
    # --- API : documents ---
    path("api/documents/", lecture_partagee_api(api_documents), name="api_documents"),
    path("api/documents/<int:document_id>/", direction_requise_api(api_document_detail), name="api_document_detail"),
    path("api/envois-email/", direction_requise_api(api_envois_email), name="api_envois_email"),
    path("api/contacts-email/", direction_requise_api(api_contacts_email), name="api_contacts_email"),
    path(
        "api/contacts-email/<int:contact_id>/",
        direction_requise_api(api_contact_email_detail),
        name="api_contact_email_detail",
    ),
    path("api/modeles-email/", direction_requise_api(api_modeles_email), name="api_modeles_email"),
    path(
        "api/modeles-email/<int:modele_id>/",
        direction_requise_api(api_modele_email_detail),
        name="api_modele_email_detail",
    ),
]
