import datetime

from django.test import TestCase
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    BesoinQualification,
    Centre,
    Disponibilite,
    EquivalenceQualification,
    PreferenceCentre,
    Qualification,
)
from animateurs.services.planning_solver import generer_planning_auto
from animateurs.tests.factories import creer_groupe


class PlanningSolverTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="Centre test", code="CT", couleur="#123456", effectif_cible=1
        )
        self.groupe, _ = creer_groupe(
            self.centre,
            nom="Maternelles",
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.bafa = Qualification.objects.create(nom="BAFA")
        self.qualifie = Animateur.objects.create(prenom="Qualifié", nom="Test")
        self.qualifie.qualifications.add(self.bafa)
        self.non_qualifie = Animateur.objects.create(prenom="Sans", nom="Qualification")
        PreferenceCentre.objects.create(animateur=self.qualifie, centre=self.centre)
        PreferenceCentre.objects.create(animateur=self.non_qualifie, centre=self.centre)
        for animateur in (self.qualifie, self.non_qualifie):
            Disponibilite.objects.create(
                animateur=animateur,
                debut=datetime.date(2026, 7, 6),
                fin=datetime.date(2026, 7, 10),
            )

    def lancer(self):
        return generer_planning_auto({"debut": "2026-07-06"})

    def test_respecte_qualification_demandee(self):
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.bafa,
            nombre_minimum=1,
        )
        data, status = self.lancer()
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertFalse(Affectation.objects.exclude(animateur=self.qualifie).exists())

    def test_respecte_les_disponibilites(self):
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.bafa,
            nombre_minimum=1,
        )
        self.qualifie.disponibilites.all().delete()
        Disponibilite.objects.create(
            animateur=self.qualifie,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 6),
        )
        data, status = self.lancer()
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 1)
        self.assertEqual(timezone.localtime(Affectation.objects.get().debut).date(), datetime.date(2026, 7, 6))

    def test_exclut_les_animateurs_sans_disponibilite(self):
        self.qualifie.disponibilites.all().delete()
        self.non_qualifie.disponibilites.all().delete()
        data, status = self.lancer()
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)

    def test_ne_touche_pas_au_samedi_manuel(self):
        # Le samedi est ouvert pour ce groupe parce qu'il fait partie de ses
        # jours sélectionnés, mais le remplissage automatique reste basé sur
        # la semaine de travail du lundi au vendredi.
        self.groupe.jours_ouverts = [0, 1, 2, 3, 4, 5]
        self.groupe.save(update_fields=["jours_ouverts"])
        samedi = datetime.date(2026, 7, 11)
        affectation_samedi = Affectation.objects.create(
            animateur=self.non_qualifie,
            centre=self.centre,
            evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(samedi, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(samedi + datetime.timedelta(days=1), datetime.time.min)),
        )

        data, status = self.lancer()
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertTrue(Affectation.objects.filter(pk=affectation_samedi.pk).exists())

    def test_respecte_strictement_les_centres_autorises(self):
        autre_centre = Centre.objects.create(
            nom="Centre interdit", code="CI", couleur="#654321", effectif_cible=1
        )
        autre_groupe, _ = creer_groupe(
            autre_centre,
            nom="Élémentaires",
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        # Le centre principal n'a aucun besoin, afin d'isoler le centre interdit.
        self.groupe.effectif_cible = 0
        self.groupe.save(update_fields=["effectif_cible"])
        data, status = self.lancer()
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)
        self.assertFalse(Affectation.objects.filter(evenement=autre_groupe).exists())

    def test_conserve_la_meme_personne_sur_la_semaine(self):
        data, status = self.lancer()
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["animateurs_utilises"], 1)
        self.assertEqual(
            Affectation.objects.values_list("animateur_id", flat=True).distinct().count(),
            1,
        )

    def test_accepte_une_equivalence_double_sens(self):
        bpjeps = Qualification.objects.create(nom="BPJEPS")
        EquivalenceQualification.objects.create(
            qualification_a=self.bafa,
            qualification_b=bpjeps,
            sens=EquivalenceQualification.SENS_DOUBLE,
        )
        self.qualifie.qualifications.clear()
        self.qualifie.qualifications.add(bpjeps)
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.bafa,
            nombre_minimum=1,
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertFalse(Affectation.objects.exclude(animateur=self.qualifie).exists())

    def test_accepte_une_equivalence_dans_le_sens_autorise(self):
        bpjeps = Qualification.objects.create(nom="BPJEPS")
        # BPJEPS → BAFA : un titulaire BPJEPS couvre un besoin BAFA.
        EquivalenceQualification.objects.create(
            qualification_a=self.bafa,
            qualification_b=bpjeps,
            sens=EquivalenceQualification.SENS_B_VERS_A,
        )
        self.qualifie.qualifications.clear()
        self.qualifie.qualifications.add(bpjeps)
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.bafa,
            nombre_minimum=1,
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)

    def test_equivalence_sens_unique_ne_fonctionne_pas_a_lenvers(self):
        bpjeps = Qualification.objects.create(nom="BPJEPS")
        # BPJEPS → BAFA ne permet pas à BAFA de couvrir BPJEPS.
        EquivalenceQualification.objects.create(
            qualification_a=self.bafa,
            qualification_b=bpjeps,
            sens=EquivalenceQualification.SENS_B_VERS_A,
        )
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=bpjeps,
            nombre_minimum=1,
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)

    def test_equivalence_directionnelle_est_transitive(self):
        bpjeps = Qualification.objects.create(nom="BPJEPS")
        cpjeps = Qualification.objects.create(nom="CPJEPS")
        # CPJEPS → BPJEPS → BAFA.
        EquivalenceQualification.objects.create(
            qualification_a=self.bafa,
            qualification_b=bpjeps,
            sens=EquivalenceQualification.SENS_B_VERS_A,
        )
        EquivalenceQualification.objects.create(
            qualification_a=bpjeps,
            qualification_b=cpjeps,
            sens=EquivalenceQualification.SENS_B_VERS_A,
        )
        self.qualifie.qualifications.clear()
        self.qualifie.qualifications.add(cpjeps)
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.bafa,
            nombre_minimum=1,
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)

