import datetime

from django.test import TestCase
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    BesoinEncadrement,
    BesoinQualification,
    Centre,
    Disponibilite,
    Evenement,
    Groupe,
    ModalitePeriscolaire,
    PeriodeCalendrier,
    Qualification,
    TypeAccueil,
)
from animateurs.services.besoins_encadrement import (
    besoin_encadrement_effectif,
    enregistrer_besoins_contextuels,
)
from animateurs.services.planning_solver import generer_planning_auto


class BesoinsEncadrementContextuelsTests(TestCase):
    def setUp(self):
        self.vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES,
            defaults={"nom": "Vacances", "ordre": 10, "actif": True},
        )
        self.periscolaire, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.PERISCOLAIRE,
            defaults={"nom": "Périscolaire", "ordre": 20, "actif": True},
        )
        self.matin, _ = ModalitePeriscolaire.objects.get_or_create(
            code=ModalitePeriscolaire.MATIN,
            defaults={
                "nom": "Accueil du matin",
                "ordre": 10,
                "heure_debut": datetime.time(7, 15),
                "heure_fin": datetime.time(8, 30),
            },
        )
        self.midi, _ = ModalitePeriscolaire.objects.get_or_create(
            code=ModalitePeriscolaire.MIDI,
            defaults={
                "nom": "Pause méridienne",
                "ordre": 20,
                "heure_debut": datetime.time(11, 30),
                "heure_fin": datetime.time(13, 30),
            },
        )
        self.centre = Centre.objects.create(nom="Centre test", code="CTX", couleur="#654321")
        self.centre.types_accueil.add(self.vacances, self.periscolaire)
        self.groupe_partage = Groupe.objects.create(
            nom="Maternelles",
            cle_unique="maternelles-contextuel",
            enfants_par_animateur_defaut=8,
        )
        self.groupe_partage.types_accueil.add(self.vacances, self.periscolaire)
        self.groupe = Evenement.objects.create(
            groupe=self.groupe_partage,
            centre=self.centre,
            nom=self.groupe_partage.nom,
            permanent=True,
            effectif_cible=2,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.groupe.types_accueil.add(self.vacances, self.periscolaire)
        self.bafa = Qualification.objects.create(nom="BAFA contextualisé")
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.bafa,
            nombre_minimum=1,
        )

    def test_vacances_et_periscolaire_sont_independants_avec_surcharge_de_creneau(self):
        BesoinEncadrement.objects.create(
            evenement=self.groupe,
            type_accueil=self.vacances,
            effectif_cible=2,
        )
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.bafa,
            nombre_minimum=1,
            type_accueil=self.vacances,
        )
        defaut = BesoinEncadrement.objects.create(
            evenement=self.groupe,
            type_accueil=self.periscolaire,
            effectif_cible=3,
        )
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.bafa,
            nombre_minimum=2,
            type_accueil=self.periscolaire,
        )
        BesoinEncadrement.objects.create(
            evenement=self.groupe,
            type_accueil=self.periscolaire,
            modalite_periscolaire=self.midi,
            effectif_cible=5,
        )

        vacances = besoin_encadrement_effectif(self.groupe, type_accueil=self.vacances)
        matin = besoin_encadrement_effectif(
            self.groupe, type_accueil=self.periscolaire, modalite=self.matin
        )
        midi = besoin_encadrement_effectif(
            self.groupe, type_accueil=self.periscolaire, modalite=self.midi
        )

        self.assertEqual(vacances.effectif_cible, 2)
        self.assertEqual({item.qualification_id: item.nombre_minimum for item in vacances.qualifications}, {self.bafa.id: 1})
        self.assertEqual(matin.effectif_cible, 3)
        self.assertEqual(matin.regle, defaut)
        self.assertEqual({item.qualification_id: item.nombre_minimum for item in matin.qualifications}, {self.bafa.id: 2})
        self.assertEqual(midi.effectif_cible, 5)
        # Une surcharge de créneau possède ses propres exigences : une liste
        # vide signifie volontairement « aucune qualification minimale ».
        self.assertEqual(midi.qualifications, ())


    def test_absence_de_regle_periscolaire_ne_reprend_pas_les_vacances(self):
        BesoinEncadrement.objects.create(
            evenement=self.groupe,
            type_accueil=self.vacances,
            effectif_cible=4,
        )

        periscolaire = besoin_encadrement_effectif(
            self.groupe,
            type_accueil=self.periscolaire,
            modalite=self.matin,
        )

        self.assertFalse(periscolaire.configure)
        self.assertEqual(periscolaire.effectif_cible, 0)
        self.assertEqual(periscolaire.qualifications, ())

    def test_enregistrement_interface_preserve_les_surcharges_de_periode(self):
        periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.SCOLAIRE,
            nom="Rentrée → Toussaint",
            annee_scolaire="2026-2027",
            zone="A",
            debut=datetime.date(2026, 9, 1),
            fin=datetime.date(2026, 10, 16),
        )
        specifique = BesoinEncadrement.objects.create(
            evenement=self.groupe,
            type_accueil=self.periscolaire,
            modalite_periscolaire=self.midi,
            periode_calendrier=periode,
            effectif_cible=6,
        )

        enregistrer_besoins_contextuels(
            self.groupe,
            [
                {
                    "type_accueil": TypeAccueil.PERISCOLAIRE,
                    "modalite_periscolaire": ModalitePeriscolaire.MIDI,
                    "effectif_cible": 4,
                    "qualifications_requises": {str(self.bafa.id): 1},
                }
            ],
        )

        self.assertTrue(BesoinEncadrement.objects.filter(pk=specifique.pk).exists())
        self.assertTrue(
            BesoinEncadrement.objects.filter(
                evenement=self.groupe,
                type_accueil=self.periscolaire,
                modalite_periscolaire=self.midi,
                periode_calendrier__isnull=True,
                effectif_cible=4,
            ).exists()
        )


class RemplissageAutoPeriscolaireContextuelTests(TestCase):
    SEMAINE = datetime.date(2026, 9, 7)

    def setUp(self):
        self.vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES,
            defaults={"nom": "Vacances", "ordre": 10, "actif": True},
        )
        self.periscolaire, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.PERISCOLAIRE,
            defaults={"nom": "Périscolaire", "ordre": 20, "actif": True},
        )
        self.matin, _ = ModalitePeriscolaire.objects.get_or_create(
            code=ModalitePeriscolaire.MATIN,
            defaults={
                "nom": "Accueil du matin",
                "ordre": 10,
                "heure_debut": datetime.time(7, 15),
                "heure_fin": datetime.time(8, 30),
            },
        )
        self.midi, _ = ModalitePeriscolaire.objects.get_or_create(
            code=ModalitePeriscolaire.MIDI,
            defaults={
                "nom": "Pause méridienne",
                "ordre": 20,
                "heure_debut": datetime.time(11, 30),
                "heure_fin": datetime.time(13, 30),
            },
        )
        self.centre = Centre.objects.create(nom="Centre auto", code="AUT", couleur="#123456")
        self.centre.types_accueil.add(self.vacances, self.periscolaire)
        modele = Groupe.objects.create(
            nom="Élémentaires",
            cle_unique="elementaires-contextuel-auto",
            enfants_par_animateur_defaut=12,
        )
        modele.types_accueil.add(self.vacances, self.periscolaire)
        self.groupe = Evenement.objects.create(
            groupe=modele,
            centre=self.centre,
            nom=modele.nom,
            permanent=True,
            effectif_cible=1,
            jours_ouverts=[0, 1, 2, 3, 4],
        )
        self.groupe.types_accueil.add(self.vacances, self.periscolaire)
        BesoinEncadrement.objects.create(
            evenement=self.groupe,
            type_accueil=self.periscolaire,
            modalite_periscolaire=self.midi,
            effectif_cible=2,
        )
        self.qualification = Qualification.objects.create(nom="BAFA auto contextuel")
        BesoinQualification.objects.create(
            evenement=self.groupe,
            qualification=self.qualification,
            nombre_minimum=1,
            type_accueil=self.periscolaire,
            modalite_periscolaire=self.midi,
        )
        self.alice = Animateur.objects.create(prenom="Alice", nom="Contextuel")
        self.bruno = Animateur.objects.create(prenom="Bruno", nom="Contextuel")
        self.alice.qualifications.add(self.qualification)
        for animateur in (self.alice, self.bruno):
            Disponibilite.objects.create(
                animateur=animateur,
                debut=self.SEMAINE,
                fin=self.SEMAINE + datetime.timedelta(days=4),
            )

        # Une affectation du matin doit être conservée et ne doit pas empêcher
        # Alice d'être choisie à midi lorsque les créneaux ne se chevauchent pas.
        Affectation.objects.create(
            animateur=self.alice,
            centre=self.centre,
            evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(self.SEMAINE, datetime.time.min)),
            fin=timezone.make_aware(
                datetime.datetime.combine(self.SEMAINE + datetime.timedelta(days=1), datetime.time.min)
            ),
            type_accueil=self.periscolaire,
            modalite_periscolaire=self.matin,
        )

    def test_remplissage_auto_utilise_le_besoin_du_creneau_et_preserve_les_autres(self):
        data, status = generer_planning_auto(
            {
                "debut": self.SEMAINE.isoformat(),
                "type_accueil": TypeAccueil.PERISCOLAIRE,
                "modalite_periscolaire": ModalitePeriscolaire.MIDI,
            }
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["total_places"], 10)
        self.assertEqual(data["created"], 10)
        self.assertEqual(data["qualifications_manquantes"], 0)
        self.assertEqual(
            Affectation.objects.filter(
                type_accueil=self.periscolaire,
                modalite_periscolaire=self.matin,
            ).count(),
            1,
        )
        self.assertEqual(
            Affectation.objects.filter(
                type_accueil=self.periscolaire,
                modalite_periscolaire=self.midi,
            ).count(),
            10,
        )
        self.assertTrue(
            Affectation.objects.filter(
                animateur=self.alice,
                type_accueil=self.periscolaire,
                modalite_periscolaire=self.midi,
                debut__date=self.SEMAINE,
            ).exists()
        )
