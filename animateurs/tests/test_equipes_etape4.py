import datetime
import json

from django.test import TestCase
from django.urls import reverse

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Disponibilite,
    Evenement,
    PreferenceCentre,
    Qualification,
)
from animateurs.services.planning_solver import generer_planning_auto


class EvenementPrefereeApiTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="La Pacaudière", code="LP4", couleur="#123456")
        self.maternelles = self.centre.evenements.get()
        self.maternelles.nom = "Maternelles"
        self.maternelles.save(update_fields=["nom"])
        self.elementaires = Evenement.objects.create(
            centre=self.centre, nom="Élémentaires", effectif_cible=2, ordre=1
        )
        self.autre_centre = Centre.objects.create(nom="Saint-Martin", code="SM4", couleur="#654321")
        self.autre_evenement = self.autre_centre.evenements.get()

    def test_creation_avec_evenement_preferee(self):
        response = self.client.post(
            reverse("api_animateurs"),
            data=json.dumps({
                "prenom": "Julie",
                "nom": "Test",
                "centre_prefere": self.centre.id,
                "centres_secondaires": [],
                "evenement_preferee": self.elementaires.id,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        data = response.json()
        self.assertEqual(data["evenement_preferee_id"], self.elementaires.id)
        self.assertEqual(data["evenement_preferee"]["nom"], "Élémentaires")
        self.assertEqual(Animateur.objects.get().evenement_preferee, self.elementaires)

    def test_refuse_evenement_preferee_hors_centre_prefere(self):
        response = self.client.post(
            reverse("api_animateurs"),
            data=json.dumps({
                "prenom": "Julie",
                "nom": "Test",
                "centre_prefere": self.centre.id,
                "centres_secondaires": [self.autre_centre.id],
                "evenement_preferee": self.autre_evenement.id,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("centre préféré", response.json()["error"])

    def test_changer_de_centre_prefere_efface_ancienne_evenement(self):
        animateur = Animateur.objects.create(
            prenom="Julie", nom="Test", evenement_preferee=self.elementaires
        )
        PreferenceCentre.objects.create(
            animateur=animateur, centre=self.centre, est_prefere=True
        )

        response = self.client.patch(
            reverse("api_animateur_detail", args=[animateur.id]),
            data=json.dumps({
                "centre_prefere": self.autre_centre.id,
                "centres_secondaires": [],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        animateur.refresh_from_db()
        self.assertIsNone(animateur.evenement_preferee_id)
        self.assertIsNone(response.json()["evenement_preferee"])


class PlanningAutoParEvenementTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="Centre", code="C4", couleur="#123456")
        self.evenement = self.centre.evenements.get()
        self.evenement.nom = "Maternelles"
        self.evenement.effectif_cible = 1
        self.evenement.save(update_fields=["nom", "effectif_cible"])
        self.bafa = Qualification.objects.create(nom="BAFA")
        self.permis = Qualification.objects.create(nom="Permis")

    def creer_animateur(self, prenom="Julie", qualifs=(), evenement_preferee=None):
        animateur = Animateur.objects.create(
            prenom=prenom,
            nom="Test",
            evenement_preferee=evenement_preferee,
        )
        animateur.qualifications.add(*qualifs)
        PreferenceCentre.objects.create(
            animateur=animateur,
            centre=self.centre,
            est_prefere=True,
        )
        Disponibilite.objects.create(
            animateur=animateur,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )
        return animateur

    def payload(self, evenements):
        return {"debut": "2026-07-06", "evenements": evenements}

    def test_une_personne_couvre_bafa_et_permis(self):
        animateur = self.creer_animateur(qualifs=(self.bafa, self.permis))
        data, status = generer_planning_auto(self.payload({
            str(self.evenement.id): {
                "effectif": 1,
                "qualifs": {str(self.bafa.id): 1, str(self.permis.id): 1},
            }
        }))
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertFalse(Affectation.objects.exclude(animateur=animateur).exists())
        self.assertFalse(Affectation.objects.exclude(evenement=self.evenement).exists())

    def test_deux_bafa_demandent_deux_personnes_distinctes(self):
        self.creer_animateur(qualifs=(self.bafa,))
        data, status = generer_planning_auto(self.payload({
            str(self.evenement.id): {
                "effectif": 1,
                "qualifs": {str(self.bafa.id): 2},
            }
        }))
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)

    def test_evenement_preferee_est_priorisee(self):
        autre = Evenement.objects.create(
            centre=self.centre, nom="Élémentaires", effectif_cible=1, ordre=1
        )
        animateur = self.creer_animateur(evenement_preferee=autre)
        data, status = generer_planning_auto(self.payload({
            str(self.evenement.id): {"effectif": 1, "qualifs": {}},
            str(autre.id): {"effectif": 1, "qualifs": {}},
        }))
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertFalse(Affectation.objects.exclude(animateur=animateur).exists())
        self.assertFalse(Affectation.objects.exclude(evenement=autre).exists())

    def test_matin_et_soir_peuvent_utiliser_la_meme_personne(self):
        self.evenement.heure_debut = datetime.time(7, 30)
        self.evenement.heure_fin = datetime.time(12, 0)
        self.evenement.save(update_fields=["heure_debut", "heure_fin"])
        soir = Evenement.objects.create(
            centre=self.centre,
            nom="Soir",
            effectif_cible=1,
            ordre=1,
            heure_debut=datetime.time(14, 0),
            heure_fin=datetime.time(18, 30),
        )
        animateur = self.creer_animateur()

        data, status = generer_planning_auto(self.payload({
            str(self.evenement.id): {"effectif": 1, "qualifs": {}},
            str(soir.id): {"effectif": 1, "qualifs": {}},
        }))
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 10)
        self.assertEqual(Affectation.objects.filter(animateur=animateur).count(), 10)

    def test_evenements_qui_se_chevauchent_ne_doublent_pas_une_personne(self):
        self.evenement.heure_debut = datetime.time(8, 0)
        self.evenement.heure_fin = datetime.time(13, 0)
        self.evenement.save(update_fields=["heure_debut", "heure_fin"])
        midi = Evenement.objects.create(
            centre=self.centre,
            nom="Midi",
            effectif_cible=1,
            ordre=1,
            heure_debut=datetime.time(12, 0),
            heure_fin=datetime.time(16, 0),
        )
        self.creer_animateur(evenement_preferee=self.evenement)

        data, status = generer_planning_auto(self.payload({
            str(self.evenement.id): {"effectif": 1, "qualifs": {}},
            str(midi.id): {"effectif": 1, "qualifs": {}},
        }))
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["unfilled"], 5)
        self.assertFalse(Affectation.objects.exclude(evenement=self.evenement).exists())


class PlanningPageEtape4Tests(TestCase):
    def test_bouton_remplissage_auto_est_reactive(self):
        response = self.client.get(reverse("planning"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="btn-auto-semaine"')
        self.assertNotContains(response, "Remplir auto — étape 4")
        self.assertNotContains(response, 'id="btn-auto-semaine" class="btn btn-primary" type="button" disabled')
