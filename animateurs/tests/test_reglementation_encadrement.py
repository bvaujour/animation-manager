import datetime
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from animateurs.models import Animateur, BesoinEncadrement, Centre, Evenement, Groupe, Qualification, TypeAccueil
from animateurs.services.reglementation_encadrement import (
    calculer_besoins_centres,
    categorie_legale_statut,
    contraintes_qualification,
)
from animateurs.services.statuts import statut_pour_date


class CalculEncadrementReglementaireTests(TestCase):
    def setUp(self):
        self.vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES,
            defaults={"nom": "Vacances", "ordre": 10, "actif": True},
        )
        self.centre = Centre.objects.create(nom="Centre mixte", code="MIX", couleur="#654321")
        self.centre.types_accueil.add(self.vacances)

        maternelles = Groupe.objects.create(
            nom="Maternelles",
            cle_unique="maternelles-reglementaires",
            categorie_age_reglementaire=Groupe.AGE_MOINS_6,
            enfants_par_animateur_defaut=8,
        )
        elementaires = Groupe.objects.create(
            nom="Élémentaires",
            cle_unique="elementaires-reglementaires",
            categorie_age_reglementaire=Groupe.AGE_6_PLUS,
            enfants_par_animateur_defaut=12,
        )
        maternelles.types_accueil.add(self.vacances)
        elementaires.types_accueil.add(self.vacances)
        self.maternelles = Evenement.objects.create(
            groupe=maternelles,
            centre=self.centre,
            nom=maternelles.nom,
            permanent=True,
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.elementaires = Evenement.objects.create(
            groupe=elementaires,
            centre=self.centre,
            nom=elementaires.nom,
            permanent=True,
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        for evenement in (self.maternelles, self.elementaires):
            evenement.types_accueil.add(self.vacances)

        BesoinEncadrement.objects.create(
            evenement=self.maternelles,
            type_accueil=self.vacances,
            mode_calcul=BesoinEncadrement.MODE_REGLEMENTAIRE,
            effectif_enfants_reference=9,
            effectif_cible=1,
        )
        BesoinEncadrement.objects.create(
            evenement=self.elementaires,
            type_accueil=self.vacances,
            mode_calcul=BesoinEncadrement.MODE_REGLEMENTAIRE,
            effectif_enfants_reference=13,
            effectif_cible=1,
        )

    def test_9_maternels_et_13_elementaires_donnent_3_postes_dont_un_mixte(self):
        calculs = calculer_besoins_centres(
            [self.maternelles, self.elementaires],
            datetime.date(2026, 7, 6),
            type_accueil=self.vacances,
        )

        centre = calculs[self.centre.id]
        self.assertEqual(centre.effectif_reglementaire_requis, 3)
        self.assertEqual(centre.postes_mixtes, 1)
        self.assertEqual(centre.groupes[self.maternelles.id].postes_reglementaires_directs, 1)
        self.assertEqual(centre.groupes[self.elementaires.id].postes_reglementaires_directs, 1)
        self.assertEqual(len(centre.contributions_mixtes), 1)


    def test_reutilise_les_statuts_existants_sans_second_classement(self):
        diplome = Qualification.objects.create(nom="Diplômé BAFA", est_statut=True)
        stagiaire = Qualification.objects.create(nom="Stagiaire BAFA", est_statut=True)
        non_diplome = Qualification.objects.create(nom="Non diplômé", est_statut=True)
        autre = Qualification.objects.create(nom="Direction", est_statut=True)

        self.assertEqual(categorie_legale_statut(diplome), "diplome")
        self.assertEqual(categorie_legale_statut(stagiaire), "stagiaire")
        self.assertEqual(categorie_legale_statut(non_diplome), "non_diplome")
        self.assertEqual(categorie_legale_statut(autre), "inconnu")

    def test_un_diplome_rattache_conserve_le_systeme_diplome_vers_statut_existant(self):
        statut_diplome = Qualification.objects.create(nom="Diplômé", est_statut=True)
        bafa = Qualification.objects.create(nom="BAFA", statut=statut_diplome)
        animateur = Animateur.objects.create(prenom="Alice", nom="BAFA")
        animateur.qualifications.add(bafa)

        statut = statut_pour_date(animateur, datetime.date(2026, 7, 6))
        self.assertEqual(statut, statut_diplome)
        self.assertEqual(categorie_legale_statut(statut), "diplome")

    def test_les_quotas_de_qualification_portent_sur_le_seul_effectif_requis(self):
        self.assertEqual(
            contraintes_qualification(2),
            {"effectif_requis": 2, "minimum_diplomes": 1, "maximum_non_diplomes": 0},
        )
        self.assertEqual(
            contraintes_qualification(3),
            {"effectif_requis": 3, "minimum_diplomes": 2, "maximum_non_diplomes": 1},
        )
        self.assertEqual(
            contraintes_qualification(5),
            {"effectif_requis": 5, "minimum_diplomes": 3, "maximum_non_diplomes": 1},
        )


class TerminologieAnimateurMixteTests(SimpleTestCase):
    def test_interface_utilise_mixte_sans_renommer_le_token_technique(self):
        planning = Path("static/js/planning.js").read_text(encoding="utf-8")
        template = Path("templates/planning.html").read_text(encoding="utf-8")
        self.assertIn("Animateur mixte", template)
        self.assertIn("animateur mixte", planning)
        self.assertIn('type_affectation: "flottant"', planning)
