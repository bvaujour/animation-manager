import datetime
import json

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    AccueilCentre,
    Affectation,
    BesoinEncadrement,
    Animateur,
    Centre,
    DateExclueEvenement,
    EffectifEnfantsJour,
    Disponibilite,
    Groupe,
    ModalitePeriscolaire,
    PeriodeScolaire,
    TypeAccueil,
)
from animateurs.services.affectations import creer_affectation
from animateurs.tests.base import ConnexionTestCase
from animateurs.services.besoins_encadrement import enregistrer_besoins_contextuels
from animateurs.services.evenements import creer_evenement, modifier_evenement
from animateurs.services.planning_solver import generer_planning_auto
from animateurs.services.recapitulatif import generer_recapitulatif
from animateurs.services.serializers import evenement_to_dict
from animateurs.views_catalogue import (
    _groupe_assistant_partage,
    _rattacher_periode_groupes_permanents,
)


class ArchitectureAccueilGroupesTests(TestCase):
    def setUp(self):
        self.vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES,
            defaults={"nom": "Vacances", "ordre": 10, "actif": True},
        )
        self.periscolaire, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.PERISCOLAIRE,
            defaults={"nom": "Périscolaire", "ordre": 20, "actif": True},
        )
        self.centre = Centre.objects.create(
            nom="Lieu architecture",
            code="ARC",
            couleur="#456789",
        )
        self.centre.types_accueil.add(self.vacances, self.periscolaire)
        self.accueil_vacances = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.vacances,
            date_debut=datetime.date(2026, 1, 1),
        )
        self.accueil_periscolaire = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            date_debut=datetime.date(2026, 1, 1),
            libelle="Semaine",
        )
        self.groupe_partage = Groupe.objects.create(
            nom="Maternelle architecture",
            cle_unique="maternelle-architecture",
            enfants_par_animateur_defaut=8,
        )
        self.groupe_partage.types_accueil.add(self.vacances, self.periscolaire)
        self.semaine_vacances = PeriodeScolaire.objects.create(
            nom="Toussaint — semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 10, 19),
            fin=datetime.date(2026, 10, 23),
            type_accueil=self.vacances,
        )
        self.semaine_vacances.types_accueil.add(self.vacances)
        self.semaine_periscolaire = PeriodeScolaire.objects.create(
            nom="Rentrée — semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 7),
            fin=datetime.date(2026, 9, 11),
            type_accueil=self.periscolaire,
        )
        self.semaine_periscolaire.types_accueil.add(self.periscolaire)

    def _creer_instance(self, accueil, periode, *, permanent=False):
        return creer_evenement(
            centre=self.centre,
            accueil_centre=accueil,
            nom=self.groupe_partage.nom,
            groupe_partage=self.groupe_partage,
            periode_ids=[periode.id],
            effectif_cible=1,
            enfants_par_animateur_defaut=8,
            jours_ouverts=[0, 1, 2, 3, 4],
            permanent=permanent,
        )

    def test_meme_groupe_partage_possede_deux_instances_independantes(self):
        vacances = self._creer_instance(self.accueil_vacances, self.semaine_vacances)
        periscolaire = self._creer_instance(self.accueil_periscolaire, self.semaine_periscolaire)

        self.assertNotEqual(vacances.pk, periscolaire.pk)
        self.assertEqual(vacances.groupe_id, periscolaire.groupe_id)
        self.assertEqual(vacances.accueil_centre_id, self.accueil_vacances.id)
        self.assertEqual(periscolaire.accueil_centre_id, self.accueil_periscolaire.id)

        autre_vacances = PeriodeScolaire.objects.create(
            nom="Noël — semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 12, 21),
            fin=datetime.date(2026, 12, 25),
            type_accueil=self.vacances,
        )
        autre_vacances.types_accueil.add(self.vacances)
        modifier_evenement(
            vacances,
            periode_ids=[autre_vacances.id],
            periodes_fournies=True,
        )

        self.assertEqual(list(vacances.periodes_scolaires.values_list("id", flat=True)), [autre_vacances.id])
        self.assertEqual(
            list(periscolaire.periodes_scolaires.values_list("id", flat=True)),
            [self.semaine_periscolaire.id],
        )

    def test_configuration_avancee_refuse_une_periode_de_l_autre_accueil(self):
        vacances = self._creer_instance(self.accueil_vacances, self.semaine_vacances)

        with self.assertRaises(ValidationError):
            modifier_evenement(
                vacances,
                periode_ids=[self.semaine_periscolaire.id],
                periodes_fournies=True,
            )

    def test_nouvelle_semaine_vacances_ne_contamine_pas_le_periscolaire(self):
        vacances = self._creer_instance(self.accueil_vacances, self.semaine_vacances, permanent=True)
        periscolaire = self._creer_instance(
            self.accueil_periscolaire,
            self.semaine_periscolaire,
            permanent=True,
        )
        nouvelle = PeriodeScolaire.objects.create(
            nom="Hiver — semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2027, 2, 15),
            fin=datetime.date(2027, 2, 19),
            type_accueil=self.vacances,
        )
        nouvelle.types_accueil.add(self.vacances)

        _rattacher_periode_groupes_permanents(nouvelle, self.vacances)

        self.assertTrue(vacances.periodes_scolaires.filter(pk=nouvelle.pk).exists())
        self.assertFalse(periscolaire.periodes_scolaires.filter(pk=nouvelle.pk).exists())

    def test_besoins_et_affectations_refusent_un_type_contradictoire(self):
        vacances = self._creer_instance(self.accueil_vacances, self.semaine_vacances)

        with self.assertRaises(ValidationError):
            enregistrer_besoins_contextuels(
                vacances,
                [{"type_accueil": TypeAccueil.PERISCOLAIRE, "effectif_cible": 1}],
            )

        animateur = Animateur.objects.create(prenom="Alice", nom="Architecture")
        debut = datetime.datetime(2026, 10, 19, tzinfo=datetime.timezone.utc)
        fin = debut + datetime.timedelta(days=1)
        with self.assertRaises(ValueError):
            creer_affectation(
                animateur=animateur,
                centre=self.centre,
                evenement=vacances,
                debut=debut,
                fin=fin,
                type_accueil=self.periscolaire,
            )

    def test_effectif_enfants_refuse_un_type_contradictoire(self):
        vacances = self._creer_instance(self.accueil_vacances, self.semaine_vacances)
        effectif = EffectifEnfantsJour(
            evenement=vacances,
            date=self.semaine_vacances.debut,
            nombre=12,
            type_accueil=self.periscolaire,
        )

        with self.assertRaises(ValidationError):
            effectif.full_clean()

    def test_recapitulatif_paie_ventile_par_accueil_centre(self):
        vacances = self._creer_instance(self.accueil_vacances, self.semaine_vacances)
        periscolaire = self._creer_instance(self.accueil_periscolaire, self.semaine_periscolaire)
        animateur = Animateur.objects.create(prenom="Paie", nom="Ventilation")
        for evenement, jour, type_accueil in (
            (periscolaire, self.semaine_periscolaire.debut, self.periscolaire),
            (vacances, self.semaine_vacances.debut, self.vacances),
        ):
            debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
            Affectation.objects.create(
                animateur=animateur,
                centre=self.centre,
                evenement=evenement,
                debut=debut,
                fin=debut + datetime.timedelta(days=1),
                type_accueil=type_accueil,
            )

        debut = timezone.make_aware(datetime.datetime(2026, 9, 1))
        fin = timezone.make_aware(datetime.datetime(2026, 11, 1))
        recapitulatif = generer_recapitulatif(debut, fin)

        self.assertEqual(
            {item["accueil_centre_id"] for item in recapitulatif["centres"]},
            {self.accueil_vacances.id, self.accueil_periscolaire.id},
        )
        ligne = recapitulatif["animateurs"][0]
        self.assertEqual(ligne["jours_affectation"], 2)
        self.assertEqual(
            {item["accueil_centre_id"]: item["jours_travailles"] for item in ligne["centres"]},
            {self.accueil_vacances.id: 1, self.accueil_periscolaire.id: 1},
        )

    def test_date_exclue_utilise_les_periodes_du_groupe(self):
        vacances = self._creer_instance(self.accueil_vacances, self.semaine_vacances)
        valide = DateExclueEvenement(
            evenement=vacances,
            date=datetime.date(2026, 10, 20),
            motif="Fermeture exceptionnelle",
        )
        valide.full_clean()

        hors_periode = DateExclueEvenement(
            evenement=vacances,
            date=datetime.date(2026, 11, 10),
        )
        with self.assertRaises(ValidationError):
            hors_periode.full_clean()

    def test_serialisation_expose_le_type_de_l_accueil_comme_source_directe(self):
        vacances = self._creer_instance(self.accueil_vacances, self.semaine_vacances)
        # Simule une ancienne relation M2M devenue incohérente : l'interface doit
        # malgré tout recevoir le type porté par AccueilCentre.
        vacances.types_accueil.set([self.periscolaire])

        payload = evenement_to_dict(vacances, include_effectifs=False)

        self.assertEqual(payload["type_accueil_code"], TypeAccueil.VACANCES)
        self.assertEqual(payload["type_accueil_codes"], [TypeAccueil.VACANCES])

    def test_assistant_ne_reutilise_pas_un_groupe_de_sejour_par_son_nom(self):
        Groupe.objects.create(
            nom="Nom temporaire",
            cle_unique="nom-temporaire",
            type_groupe=Groupe.TYPE_SEJOUR,
            date_debut_validite=datetime.date(2026, 7, 1),
            date_fin_validite=datetime.date(2026, 7, 7),
        )

        with self.assertRaises(ValidationError):
            _groupe_assistant_partage({"nom": "Nom temporaire"}, self.vacances)


class ArchitectureAccueilGroupesApiTests(ConnexionTestCase):
    def setUp(self):
        self.vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES,
            defaults={"nom": "Vacances", "ordre": 10, "actif": True},
        )
        self.periscolaire, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.PERISCOLAIRE,
            defaults={"nom": "Périscolaire", "ordre": 20, "actif": True},
        )
        self.centre = Centre.objects.create(
            nom="Lieu API architecture", code="AAPI", couleur="#345678"
        )
        self.centre.types_accueil.add(self.vacances, self.periscolaire)
        self.accueil = AccueilCentre.objects.create(
            centre=self.centre,
            type_accueil=self.periscolaire,
            libelle="Aide aux devoirs",
            date_debut=datetime.date(2026, 9, 1),
        )
        self.groupe = Groupe.objects.create(
            nom="Groupe mixte API",
            cle_unique="groupe-mixte-api",
            enfants_par_animateur_defaut=12,
        )
        self.groupe.types_accueil.add(self.periscolaire)
        self.periode = PeriodeScolaire.objects.create(
            nom="Rentrée API — semaine 1",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 1),
            fin=datetime.date(2026, 9, 4),
            type_accueil=self.periscolaire,
        )
        self.periode.types_accueil.add(self.periscolaire)
        self.evenement = creer_evenement(
            centre=self.centre,
            accueil_centre=self.accueil,
            nom=self.groupe.nom,
            groupe_partage=self.groupe,
            periode_ids=[self.periode.pk],
            jours_ouverts=[0, 1, 3],
        )

    def test_patch_groupe_periscolaire_ignore_la_carte_vacances_cachee(self):
        payload = {
            "besoins_encadrement": [
                {
                    "type_accueil": TypeAccueil.VACANCES,
                    "mode_calcul": BesoinEncadrement.MODE_MANUEL,
                    "effectif_cible": 4,
                    "qualifications_requises": {},
                },
                {
                    "type_accueil": TypeAccueil.PERISCOLAIRE,
                    "mode_calcul": BesoinEncadrement.MODE_MANUEL,
                    "effectif_cible": 2,
                    "qualifications_requises": {},
                },
            ]
        }

        response = self.client.patch(
            reverse("api_groupe_detail", args=[self.evenement.pk]),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            self.evenement.besoins_encadrement.filter(
                type_accueil=self.periscolaire, effectif_cible=2
            ).exists()
        )
        self.assertFalse(
            self.evenement.besoins_encadrement.filter(type_accueil=self.vacances).exists()
        )

    def test_service_metier_reste_strict_sur_un_vrai_type_contradictoire(self):
        with self.assertRaises(ValidationError):
            enregistrer_besoins_contextuels(
                self.evenement,
                [{
                    "type_accueil": TypeAccueil.VACANCES,
                    "mode_calcul": BesoinEncadrement.MODE_MANUEL,
                    "effectif_cible": 1,
                }],
            )

    def test_aide_aux_devoirs_a_trois_est_enregistree_affichee_et_utilisee(self):
        modalite = ModalitePeriscolaire.objects.create(
            code="aide_devoirs_integration",
            nom="Aide aux devoirs intégration",
            heure_debut=datetime.time(16, 30),
            heure_fin=datetime.time(18, 0),
            actif=True,
        )
        response = self.client.patch(
            reverse("api_groupe_detail", args=[self.evenement.pk]),
            data=json.dumps({
                "besoins_encadrement": [{
                    "type_accueil": TypeAccueil.PERISCOLAIRE,
                    "modalite_periscolaire": modalite.code,
                    "mode_calcul": BesoinEncadrement.MODE_MANUEL,
                    "effectif_cible": 3,
                    "qualifications_requises": {},
                }],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["besoins_encadrement"][0]["effectif_cible"], 3)

        for index in range(3):
            animateur = Animateur.objects.create(prenom=f"Aide{index}", nom="Devoirs")
            Disponibilite.objects.create(
                animateur=animateur,
                debut=self.periode.debut,
                fin=self.periode.fin,
            )

        resultat, statut = generer_planning_auto({
            "debut": self.periode.debut.isoformat(),
            "type_accueil": TypeAccueil.PERISCOLAIRE,
            "modalite_periscolaire": modalite.code,
        })

        self.assertEqual(statut, 200)
        self.assertEqual(resultat["total_places"], 6)
        self.assertEqual(resultat["created"], 6)
