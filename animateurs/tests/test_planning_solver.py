import datetime

from django.test import TestCase
from django.utils import timezone

from animateurs.models import (
    Affectation,
    AffiniteGroupeAnimateur,
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

SEMAINE_DEBUT = datetime.date(2026, 7, 6)
SEMAINE_FIN = datetime.date(2026, 7, 10)


def rendre_disponible(animateur, debut=SEMAINE_DEBUT, fin=SEMAINE_FIN):
    Disponibilite.objects.create(animateur=animateur, debut=debut, fin=fin)


def creer_affectation_historique(animateur, groupe, jour):
    Affectation.objects.create(
        animateur=animateur,
        centre=groupe.centre,
        evenement=groupe,
        debut=timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min)),
        fin=timezone.make_aware(
            datetime.datetime.combine(jour + datetime.timedelta(days=1), datetime.time.min)
        ),
    )


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
        self.alice = Animateur.objects.create(prenom="Alice", nom="Test")
        self.bruno = Animateur.objects.create(prenom="Bruno", nom="Test")
        rendre_disponible(self.alice)
        rendre_disponible(self.bruno)

    def lancer(self):
        return generer_planning_auto({"debut": SEMAINE_DEBUT.isoformat()})

    def test_reserve_le_poste_lorsque_la_qualification_manque(self):
        bafa = Qualification.objects.create(nom="BAFA")
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=bafa,
            nombre_minimum=1,
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)
        self.assertEqual(data["qualifications_manquantes"], 5)
        self.assertEqual(Affectation.objects.count(), 0)

    def test_remplit_les_postes_non_reserves_aux_qualifications(self):
        bafa = Qualification.objects.create(nom="BAFA")
        self.groupe.effectif_cible = 2
        self.groupe.save(update_fields=["effectif_cible"])
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=bafa,
            nombre_minimum=1,
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["unfilled"], 5)
        self.assertEqual(data["qualifications_manquantes"], 5)

    def test_priorise_un_animateur_qualifie(self):
        bafa = Qualification.objects.create(nom="BAFA")
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=bafa,
            nombre_minimum=1,
        )
        self.bruno.qualifications.add(bafa)

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["qualifications_manquantes"], 0)
        self.assertEqual(
            set(Affectation.objects.values_list("animateur_id", flat=True)),
            {self.bruno.id},
        )


    def test_une_equivalence_directionnelle_couvre_le_besoin(self):
        bafa = Qualification.objects.create(nom="BAFA")
        bpjeps = Qualification.objects.create(nom="BPJEPS")
        EquivalenceQualification.objects.create(
            qualification_a=bpjeps,
            qualification_b=bafa,
            sens=EquivalenceQualification.SENS_A_VERS_B,
        )
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=bafa,
            nombre_minimum=1,
        )
        self.bruno.qualifications.add(bpjeps)

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["qualifications_manquantes"], 0)
        self.assertEqual(
            set(Affectation.objects.values_list("animateur_id", flat=True)),
            {self.bruno.id},
        )

    def test_une_personne_multiqualifiee_peut_couvrir_plusieurs_exigences(self):
        bafa = Qualification.objects.create(nom="BAFA")
        psc1 = Qualification.objects.create(nom="PSC1")
        for qualification in (bafa, psc1):
            BesoinQualification.objects.create(
                evenement=self.groupe,
                qualification=qualification,
                nombre_minimum=1,
            )
        self.bruno.qualifications.add(bafa, psc1)

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["qualifications_manquantes"], 0)

    def test_respecte_les_disponibilites(self):
        self.alice.disponibilites.all().delete()
        self.bruno.disponibilites.all().delete()
        rendre_disponible(self.alice, SEMAINE_DEBUT, SEMAINE_DEBUT)

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 1)
        self.assertEqual(
            timezone.localtime(Affectation.objects.get().debut).date(),
            SEMAINE_DEBUT,
        )

    def test_exclut_les_animateurs_sans_disponibilite(self):
        self.alice.disponibilites.all().delete()
        self.bruno.disponibilites.all().delete()

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)

    def test_ne_touche_pas_au_samedi_manuel(self):
        self.groupe.jours_ouverts = [0, 1, 2, 3, 4, 5]
        self.groupe.save(update_fields=["jours_ouverts"])
        samedi = datetime.date(2026, 7, 11)
        affectation_samedi = Affectation.objects.create(
            animateur=self.bruno,
            centre=self.centre,
            evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(samedi, datetime.time.min)),
            fin=timezone.make_aware(
                datetime.datetime.combine(samedi + datetime.timedelta(days=1), datetime.time.min)
            ),
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertTrue(Affectation.objects.filter(pk=affectation_samedi.pk).exists())

    def test_seul_un_lieu_explicitement_interdit_est_bloque(self):
        autre_centre = Centre.objects.create(
            nom="Centre interdit", code="CI", couleur="#654321", effectif_cible=1
        )
        autre_groupe, _ = creer_groupe(
            autre_centre,
            nom="Élémentaires",
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.groupe.effectif_cible = 0
        self.groupe.save(update_fields=["effectif_cible"])
        for animateur in (self.alice, self.bruno):
            PreferenceCentre.objects.create(
                animateur=animateur,
                centre=autre_centre,
                est_interdit=True,
            )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)
        self.assertFalse(Affectation.objects.filter(evenement=autre_groupe).exists())

    def test_un_lieu_neutre_reste_autorise(self):
        autre_centre = Centre.objects.create(
            nom="Centre neutre", code="CN", couleur="#654321", effectif_cible=1
        )
        autre_groupe, _ = creer_groupe(
            autre_centre,
            nom="Élémentaires",
            effectif_cible=1,
            jours_ouverts=[0],
        )
        self.groupe.effectif_cible = 0
        self.groupe.save(update_fields=["effectif_cible"])

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 1)
        self.assertTrue(Affectation.objects.filter(evenement=autre_groupe).exists())

    def test_priorise_le_lieu_prefere(self):
        autre_centre = Centre.objects.create(
            nom="Autre centre", code="AC", couleur="#654321", effectif_cible=1
        )
        autre_groupe, _ = creer_groupe(
            autre_centre,
            nom="Autre groupe",
            effectif_cible=1,
            jours_ouverts=[0],
        )
        self.groupe.jours_ouverts = [0]
        self.groupe.save(update_fields=["jours_ouverts"])
        PreferenceCentre.objects.create(
            animateur=self.alice,
            centre=self.centre,
            est_prefere=True,
        )
        PreferenceCentre.objects.create(
            animateur=self.bruno,
            centre=autre_centre,
            est_prefere=True,
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 2)
        self.assertTrue(
            Affectation.objects.filter(animateur=self.alice, evenement=self.groupe).exists()
        )
        self.assertTrue(
            Affectation.objects.filter(animateur=self.bruno, evenement=autre_groupe).exists()
        )

    def test_conserve_la_meme_personne_sur_la_semaine(self):
        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["animateurs_utilises"], 1)
        self.assertEqual(
            Affectation.objects.values_list("animateur_id", flat=True).distinct().count(),
            1,
        )

    def test_historique_du_groupe_departage_les_candidats(self):
        creer_affectation_historique(
            self.bruno,
            self.groupe,
            datetime.date(2026, 6, 29),
        )

        data, status = self.lancer()

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertFalse(Affectation.objects.filter(debut__gte=timezone.make_aware(datetime.datetime(2026, 7, 6)), animateur=self.alice).exists())
        self.assertEqual(
            Affectation.objects.filter(animateur=self.bruno).count(),
            6,
        )
        self.assertEqual(
            AffiniteGroupeAnimateur.objects.get(
                animateur=self.bruno,
                evenement=self.groupe,
            ).jours_travailles,
            6,
        )


class PlanningSolverRepartitionGroupesTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="Centre répartition", code="CR", couleur="#123456", effectif_cible=2
        )

    def test_couvre_tous_les_groupes_avant_de_completer_un_seul_groupe(self):
        groupe_a, _ = creer_groupe(
            self.centre,
            nom="Groupe A",
            effectif_cible=2,
            jours_ouverts=[0],
        )
        groupe_b, _ = creer_groupe(
            self.centre,
            nom="Groupe B",
            effectif_cible=2,
            jours_ouverts=[0],
        )
        animateurs = [
            Animateur.objects.create(prenom="Alice", nom="Test"),
            Animateur.objects.create(prenom="Bruno", nom="Test"),
        ]
        for animateur in animateurs:
            rendre_disponible(animateur, SEMAINE_DEBUT, SEMAINE_DEBUT)

        data, status = generer_planning_auto({"debut": SEMAINE_DEBUT.isoformat()})

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 2)
        self.assertEqual(
            set(Affectation.objects.values_list("evenement_id", flat=True)),
            {groupe_a.id, groupe_b.id},
        )


    def test_garde_le_qualifie_pour_le_groupe_qui_en_a_besoin(self):
        qualification = Qualification.objects.create(nom="BAFA")
        groupe_qualifie, _ = creer_groupe(
            self.centre,
            nom="Groupe qualifié",
            effectif_cible=1,
            jours_ouverts=[0],
            ordre=1,
        )
        BesoinQualification.objects.create(
            evenement=groupe_qualifie,
            qualification=qualification,
            nombre_minimum=1,
        )
        autre_centre = Centre.objects.create(
            nom="Centre préféré", code="CP", couleur="#654321", effectif_cible=1
        )
        groupe_prefere, _ = creer_groupe(
            autre_centre,
            nom="Groupe sans exigence",
            effectif_cible=1,
            jours_ouverts=[0],
        )
        qualifie = Animateur.objects.create(prenom="Alice", nom="Qualifiée")
        non_qualifie = Animateur.objects.create(prenom="Bruno", nom="Disponible")
        qualifie.qualifications.add(qualification)
        PreferenceCentre.objects.create(
            animateur=qualifie,
            centre=autre_centre,
            est_prefere=True,
        )
        for animateur in (qualifie, non_qualifie):
            rendre_disponible(animateur, SEMAINE_DEBUT, SEMAINE_DEBUT)

        data, status = generer_planning_auto({"debut": SEMAINE_DEBUT.isoformat()})

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 2)
        self.assertEqual(data["qualifications_manquantes"], 0)
        self.assertTrue(
            Affectation.objects.filter(animateur=qualifie, evenement=groupe_qualifie).exists()
        )
        self.assertTrue(
            Affectation.objects.filter(animateur=non_qualifie, evenement=groupe_prefere).exists()
        )

    def test_remplit_tous_les_groupes_quand_les_effectifs_sont_disponibles(self):
        groupes = [
            creer_groupe(
                self.centre,
                nom=f"Groupe {index}",
                effectif_cible=2,
                jours_ouverts=[0],
                ordre=index,
            )[0]
            for index in range(3)
        ]
        for index in range(6):
            animateur = Animateur.objects.create(prenom=f"Anim{index}", nom="Test")
            rendre_disponible(animateur, SEMAINE_DEBUT, SEMAINE_DEBUT)

        data, status = generer_planning_auto({"debut": SEMAINE_DEBUT.isoformat()})

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 6)
        self.assertEqual(data["groupes_complets"], 3)
        self.assertEqual(data["groupes_vides"], 0)
        for groupe in groupes:
            self.assertEqual(Affectation.objects.filter(evenement=groupe).count(), 2)
