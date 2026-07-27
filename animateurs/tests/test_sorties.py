import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Disponibilite,
    EffectifEnfantsJour,
    Evenement,
    Qualification,
    PreferenceTransportUtilisateur,
    Sortie,
    SortieEtapeTransport,
    SortieResponsabilite,
    SortieRenfort,
    normaliser_cle_unique,
)
from animateurs.services.flottants import groupe_flottants_pour_centre
from animateurs.services.categories_groupes import categorie_age_groupe
from animateurs.services.localisation import LocalisationError
from animateurs.services.sorties import donnees_sortie
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_periode


class SortiesTests(ConnexionTestCase):
    def setUp(self):
        self.jour = datetime.date(2026, 7, 9)
        self.periode = creer_periode(debut=datetime.date(2026, 7, 6), nom="Été 2026 — Semaine 1")
        self.centre = Centre.objects.create(nom="Centre test", code="CT")
        self.groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Maternelles",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
            enfants_par_animateur_defaut=8,
        )
        self.groupe_2 = Evenement.objects.create(
            centre=self.centre,
            nom="Élémentaires",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
            enfants_par_animateur_defaut=12,
        )

    def _rendre_disponible(self, animateur):
        return Disponibilite.objects.create(
            animateur=animateur,
            debut=self.jour,
            fin=self.jour,
        )

    def _affecter(self, animateur, groupe):
        return Affectation.objects.create(
            animateur=animateur,
            centre=groupe.centre,
            evenement=groupe,
            debut=timezone.make_aware(datetime.datetime.combine(self.jour, datetime.time.min)),
            fin=timezone.make_aware(
                datetime.datetime.combine(self.jour + datetime.timedelta(days=1), datetime.time.min)
            ),
        )

    def _apercu(self, groupes):
        return self.client.post(
            reverse("api_sorties_apercu"),
            data=json.dumps({"date": self.jour.isoformat(), "groupes": groupes}),
            content_type="application/json",
        )

    def test_page_sorties_presente_creation_avec_participants_et_apercu(self):
        response = self.client.get(reverse("sorties"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nouvelle sortie")
        self.assertContains(response, 'id="sorties-periods"')
        self.assertContains(response, 'id="sortie-create-groups"')
        self.assertContains(response, "Aperçu du Planning")
        self.assertContains(response, "Nom du lieu ou de la destination")
        self.assertContains(response, "Légende du statut des sorties")
        self.assertContains(response, "Nom, date et destination")
        self.assertContains(response, "Encadrement conforme")
        self.assertNotContains(response, "Responsable de direction · Horaires")
        self.assertContains(response, "Adresse ou lieu-dit")
        self.assertContains(response, "Code postal")
        self.assertContains(response, "Commune")

    def test_statut_verifie_identite_destination_sans_exiger_responsable(self):
        sortie = Sortie.objects.create(
            nom="Sortie complète",
            date=self.jour,
            destination="Parc",
            heure_depart=datetime.time(8),
            heure_retour=datetime.time(17),
        )
        donnees = donnees_sortie(sortie)
        self.assertNotIn("Aucun responsable de direction", donnees["vigilances"])
        controles = {item["code"]: item for item in donnees["controles_completion"]}
        self.assertTrue(controles["identite"]["ok"])
        self.assertFalse(controles["groupes_effectifs"]["ok"])
        self.assertTrue(controles["horaires"]["ok"])

        # QuerySet.update permet de simuler une ancienne donnée incomplète en
        # contournant le nettoyage réalisé par Sortie.save().
        Sortie.objects.filter(pk=sortie.pk).update(nom="", destination="")
        sortie.refresh_from_db()
        vigilances = donnees_sortie(sortie)["vigilances"]
        self.assertIn("Nom de la sortie manquant", vigilances)
        self.assertIn("Destination manquante", vigilances)
        self.assertFalse(
            next(
                item["ok"]
                for item in donnees_sortie(sortie)["controles_completion"]
                if item["code"] == "identite"
            )
        )

    def test_fiche_affiche_la_carte_des_controles_de_completion(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        css = Path(settings.BASE_DIR, "static/css/sorties.css").read_text()
        self.assertIn("completionControlsMarkup", javascript)
        self.assertIn("Contrôle de la sortie", javascript)
        self.assertIn("sortie-summary-completion", javascript)
        self.assertIn("sortie-completion-icon--warning", css)
        self.assertIn("clip-path:polygon", css)

    def test_repartition_groupes_est_compacte_et_colore_le_ratio_reel(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        css = Path(settings.BASE_DIR, "static/css/sorties.css").read_text()
        self.assertIn("sortie-repartition-name", javascript)
        self.assertIn("sortie-effectifs-text", javascript)
        self.assertIn("sortie-ratio-real-badge", javascript)
        self.assertIn("Taux d’encadrement</th><th>Animateurs affectés", javascript)
        self.assertIn("Requis 1/", javascript)
        self.assertIn("Taux réel ${actual}", javascript)
        self.assertIn("sortie-coverage-badges", javascript)
        self.assertIn("data-label=\"Animateurs affectés\"", javascript)
        self.assertIn("@media (max-width:720px)", css)
        self.assertNotIn("sortie-repartition-total", javascript)
        self.assertNotIn("sortie-table-footnotes", javascript)

    def test_meteo_utilise_uniquement_la_localisation_destination(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Paléopolis", destination_adresse="Route de Bègues", destination_code_postal="03800", destination_commune="Gannat", destination_latitude=46.18, destination_longitude=3.19, destination_precision="adresse")
        url = reverse("api_sortie_detail", args=[sortie.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["meteo_lieu"]["libelle"], "Paléopolis")
        self.assertEqual(response.json()["meteo_lieu"]["latitude"], 46.18)
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        self.assertNotIn('name="meteo_adresse"', javascript)
        self.assertNotIn('name="meteo_latitude"', javascript)

    @patch("animateurs.views_sorties.rechercher_communes_par_code_postal")
    def test_api_communes_par_code_postal(self, rechercher):
        rechercher.return_value = [{"nom": "Gannat", "code_postal": "03800", "code_insee": "03118", "latitude": 46.10, "longitude": 3.20}]
        response = self.client.get(reverse("api_communes_recherche"), {"code_postal": "03800"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resultats"][0]["code_insee"], "03118")

    @patch("animateurs.views_sorties.rechercher_communes_par_nom")
    def test_api_communes_par_debut_de_nom(self, rechercher):
        rechercher.return_value = [{"nom": "Saint-Forgeux", "code_postal": "69490", "code_insee": "69209", "latitude": 45.85, "longitude": 4.47}]
        response = self.client.get(reverse("api_communes_recherche"), {"nom": "Saint-For"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resultats"][0]["code_postal"], "69490")

    @patch("animateurs.views_sorties.resoudre_localisation", side_effect=LocalisationError("Panne"))
    def test_panne_localisation_ne_bloque_pas_enregistrement_manuel(self, rechercher):
        sortie = Sortie.objects.create(nom="Ancienne", date=self.jour, destination="Salle")
        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps({
                "destination_code_postal": "42640",
                "destination_commune": "Saint-Germain-Lespinasse",
                "destination_localisation_demandee": True,
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        sortie.refresh_from_db()
        self.assertEqual(sortie.destination_commune, "Saint-Germain-Lespinasse")

    def test_creation_avec_plusieurs_groupes_est_atomique_et_classee(self):
        response = self.client.post(
            reverse("api_sorties"),
            data=json.dumps(
                {
                    "nom": "Zoo",
                    "date": self.jour.isoformat(),
                    "destination": "Parc animalier",
                    "groupes": [self.groupe.id, self.groupe_2.id, self.groupe.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        sortie = Sortie.objects.get(pk=response.json()["id"])
        self.assertEqual(sortie.participations.count(), 2)
        liste = self.client.get(reverse("api_sorties"), {"periode_ids": self.periode.id}).json()
        self.assertEqual(liste["semaines"][0]["sorties"][0]["id"], sortie.id)

    def test_creation_refuse_un_groupe_invalide_sans_creer_de_sortie(self):
        response = self.client.post(
            reverse("api_sorties"),
            data=json.dumps(
                {
                    "nom": "Zoo",
                    "date": self.jour.isoformat(),
                    "destination": "Parc animalier",
                    "groupes": [999999],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Sortie.objects.exists())

    def test_creation_refuse_le_groupe_technique_flottant(self):
        groupe_technique = groupe_flottants_pour_centre(self.centre)
        response = self.client.post(
            reverse("api_sorties"),
            data=json.dumps(
                {
                    "nom": "Zoo",
                    "date": self.jour.isoformat(),
                    "destination": "Parc animalier",
                    "groupes": [groupe_technique.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Sortie.objects.exists())

    def test_apercu_relit_effectif_taux_equipe_et_nombre_requis(self):
        EffectifEnfantsJour.objects.create(evenement=self.groupe, date=self.jour, nombre=9)
        alice = Animateur.objects.create(prenom="Alice", nom="Test")
        self._affecter(alice, self.groupe)

        response = self._apercu([self.groupe.id])
        self.assertEqual(response.status_code, 200)
        data = response.json()
        ligne = data["groupes"][0]
        self.assertEqual(ligne["effectif"], 9)
        self.assertEqual(ligne["ratio"], 8)
        self.assertEqual(ligne["animateurs_requis"], 2)
        self.assertEqual(ligne["animateurs"][0]["nom"], "Alice Test")
        self.assertEqual(ligne["non_couverts"], 1)
        self.assertEqual(data["totaux"]["animateurs"], 1)

    def test_apercu_utilise_le_taux_exceptionnel(self):
        EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=self.jour,
            nombre=9,
            ratio_encadrement_exceptionnel=5,
        )
        self._affecter(Animateur.objects.create(prenom="Alice", nom="Test"), self.groupe)
        self._affecter(Animateur.objects.create(prenom="Bruno", nom="Test"), self.groupe)

        ligne = self._apercu([self.groupe.id]).json()["groupes"][0]
        self.assertEqual(ligne["ratio"], 5)
        self.assertEqual(ligne["ratio_defaut"], 8)
        self.assertEqual(ligne["ratio_exceptionnel"], 5)
        self.assertEqual(ligne["animateurs_requis"], 2)
        self.assertEqual(ligne["non_couverts"], 0)
        self.assertEqual(ligne["ratio_reel"], 4.5)
        self.assertEqual(ligne["couverture"], "conforme")

    def test_ratio_reel_et_couverture_sont_calcules_sur_l_effectif_total(self):
        EffectifEnfantsJour.objects.create(evenement=self.groupe, date=self.jour, nombre=14)
        self._affecter(Animateur.objects.create(prenom="Alice", nom="Test"), self.groupe)
        self._affecter(Animateur.objects.create(prenom="Bruno", nom="Test"), self.groupe)

        ligne = self._apercu([self.groupe.id]).json()["groupes"][0]
        self.assertEqual(ligne["ratio"], 8)
        self.assertEqual(ligne["ratio_reel"], 7)
        self.assertEqual(ligne["non_couverts"], 0)
        self.assertEqual(ligne["couverture"], "conforme")

        EffectifEnfantsJour.objects.filter(evenement=self.groupe, date=self.jour).update(nombre=17)
        ligne = self._apercu([self.groupe.id]).json()["groupes"][0]
        self.assertEqual(ligne["ratio_reel"], 8.5)
        self.assertEqual(ligne["non_couverts"], 1)
        self.assertEqual(ligne["couverture"], "insuffisant")

    def test_flottant_couvre_uniquement_les_reliquats_et_n_est_compte_qu_une_fois(self):
        EffectifEnfantsJour.objects.create(evenement=self.groupe, date=self.jour, nombre=9)
        EffectifEnfantsJour.objects.create(evenement=self.groupe_2, date=self.jour, nombre=7)
        self._affecter(Animateur.objects.create(prenom="Alice", nom="Fixe"), self.groupe)
        flottant = Animateur.objects.create(prenom="Sophie", nom="Flottante")
        self._affecter(flottant, groupe_flottants_pour_centre(self.centre))

        data = self._apercu([self.groupe.id, self.groupe_2.id]).json()
        self.assertEqual(data["totaux"]["non_couverts"], 0)
        self.assertEqual(data["totaux"]["animateurs"], 2)
        self.assertEqual(len(data["flottants_par_centre"]), 1)
        self.assertEqual(data["flottants_par_centre"][0]["animateurs"][0]["nom"], "Sophie Flottante")
        self.assertNotIn(
            "Sophie Flottante",
            [animateur["nom"] for ligne in data["groupes"] for animateur in ligne["animateurs"]],
        )
        self.assertEqual(data["groupes"][0]["ratio_reel"], 9)
        self.assertTrue(data["groupes"][0]["flottants_mobilises"])

    def test_donnees_planning_ne_sont_pas_copiees_dans_la_sortie(self):
        sortie = Sortie.objects.create(nom="Piscine", date=self.jour, destination="Piscine")
        sortie.groupes.add(self.groupe)
        effectif = EffectifEnfantsJour.objects.create(evenement=self.groupe, date=self.jour, nombre=7)
        premier = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertEqual(premier["totaux"]["enfants"], 7)

        effectif.nombre = 12
        effectif.save(update_fields=["nombre"])
        second = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertEqual(second["totaux"]["enfants"], 12)

    def test_modification_date_reclasse_automatiquement_la_sortie(self):
        seconde = creer_periode(debut=datetime.date(2026, 7, 13), nom="Été 2026 — Semaine 2")
        sortie = Sortie.objects.create(nom="Piscine", date=self.jour, destination="Piscine")
        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps({"date": "2026-07-16"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        liste = self.client.get(
            reverse("api_sorties"), {"periode_ids": f"{self.periode.id},{seconde.id}"}
        ).json()
        self.assertEqual([len(item["sorties"]) for item in liste["semaines"]], [0, 1])

    def test_suppression_ne_touche_pas_aux_donnees_planning(self):
        sortie = Sortie.objects.create(nom="Piscine", date=self.jour, destination="Piscine")
        sortie.groupes.add(self.groupe)
        response = self.client.delete(reverse("api_sortie_detail", args=[sortie.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Evenement.objects.filter(pk=self.groupe.id).exists())

    def test_responsabilites_direction_lieux_et_groupes_sont_configurables(self):
        autre_centre = Centre.objects.create(nom="Autre centre", code="AC")
        autre_groupe = Evenement.objects.create(
            centre=autre_centre,
            nom="Maternelles 2",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
            enfants_par_animateur_defaut=8,
        )
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe, self.groupe_2, autre_groupe)
        direction = Animateur.objects.create(prenom="Betty", nom="Direction", telephone="0102030405")
        responsable_lieux = Animateur.objects.create(prenom="Ambre", nom="Lieux")
        responsable_groupe = Animateur.objects.create(prenom="Marie", nom="Groupe")
        self._rendre_disponible(direction)
        self._rendre_disponible(responsable_lieux)
        self._rendre_disponible(responsable_groupe)

        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps(
                {
                    "responsabilites": [
                        {
                            "animateur_id": direction.id,
                            "type": "direction",
                            "cibles": [],
                        },
                        {
                            "animateur_id": responsable_lieux.id,
                            "type": "lieu",
                            "cibles": [self.centre.id, autre_centre.id],
                        },
                        {
                            "animateur_id": responsable_groupe.id,
                            "type": "groupe",
                            "cibles": [self.groupe.id, self.groupe_2.id],
                        },
                    ],
                    "affectations_responsables": {
                        str(direction.id): self.groupe.id,
                        str(responsable_lieux.id): autre_groupe.id,
                        str(responsable_groupe.id): self.groupe.id,
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sortie.responsabilites.count(), 5)
        data = response.json()
        self.assertEqual(len(data["responsabilites"]), 5)
        self.assertIn("telephone", data["responsabilites"][0]["animateur"])
        self.assertNotIn("responsables", data)
        affectations = Affectation.objects.filter(
            animateur_id__in=[direction.id, responsable_lieux.id, responsable_groupe.id],
            debut__date=self.jour,
        )
        self.assertEqual(affectations.count(), 3)
        self.assertEqual(
            affectations.get(animateur=responsable_groupe).evenement_id,
            self.groupe.id,
        )
        self.assertTrue(
            affectations.filter(
                animateur=responsable_lieux,
                centre_id__in=[self.centre.id, autre_centre.id],
            ).exists()
        )

    def test_responsabilite_refuse_un_lieu_hors_sortie(self):
        autre_centre = Centre.objects.create(nom="Centre hors sortie", code="HS")
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Test")
        self._rendre_disponible(animateur)

        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps(
                {
                    "responsabilites": [
                        {
                            "animateur_id": animateur.id,
                            "type": "lieu",
                            "cibles": [autre_centre.id],
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SortieResponsabilite.objects.filter(sortie=sortie).exists())

    def test_responsable_non_affecte_exige_un_groupe_de_planning(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Disponible")
        self._rendre_disponible(animateur)

        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps(
                {
                    "responsabilites": [
                        {"animateur_id": animateur.id, "type": "direction", "cibles": []},
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("lieu et un groupe", response.json()["error"])
        self.assertFalse(sortie.responsabilites.exists())
        self.assertFalse(Affectation.objects.filter(animateur=animateur, debut__date=self.jour).exists())

    def test_suppression_responsable_peut_aussi_supprimer_son_affectation(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Disponible")
        self._rendre_disponible(animateur)
        creation = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps(
                {
                    "responsabilites": [
                        {"animateur_id": animateur.id, "type": "direction", "cibles": []},
                    ],
                    "affectations_responsables": {str(animateur.id): self.groupe.id},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(creation.status_code, 200)

        suppression = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps(
                {
                    "responsabilites": [],
                    "supprimer_affectations_responsables": [animateur.id],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(suppression.status_code, 200)
        self.assertFalse(sortie.responsabilites.exists())
        self.assertFalse(Affectation.objects.filter(animateur=animateur, debut__date=self.jour).exists())

    def test_suppression_affectation_responsable_preserve_les_autres_jours(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Semaine")
        debut = timezone.make_aware(
            datetime.datetime.combine(self.jour - datetime.timedelta(days=1), datetime.time.min)
        )
        fin = timezone.make_aware(
            datetime.datetime.combine(self.jour + datetime.timedelta(days=2), datetime.time.min)
        )
        affectation = Affectation.objects.create(
            animateur=animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut,
            fin=fin,
        )
        SortieResponsabilite.objects.create(
            sortie=sortie,
            animateur=animateur,
            type=SortieResponsabilite.TYPE_DIRECTION,
            affectation_creee=affectation,
        )

        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps(
                {
                    "responsabilites": [],
                    "supprimer_affectations_responsables": [animateur.id],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        plages = list(Affectation.objects.filter(animateur=animateur).order_by("debut"))
        self.assertEqual([(item.debut, item.fin) for item in plages], [(debut, debut + datetime.timedelta(days=1)), (debut + datetime.timedelta(days=2), fin)])

    def test_affectation_anterieure_a_la_responsabilite_ne_peut_pas_etre_supprimee(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Déjà affectée")
        affectation = self._affecter(animateur, self.groupe)
        SortieResponsabilite.objects.create(
            sortie=sortie,
            animateur=animateur,
            type=SortieResponsabilite.TYPE_DIRECTION,
        )

        detail = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertFalse(detail["responsabilites"][0]["affectation_creee"])
        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps(
                {
                    "responsabilites": [],
                    "supprimer_affectations_responsables": [animateur.id],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Affectation.objects.filter(pk=affectation.id).exists())
        self.assertTrue(sortie.responsabilites.exists())

    def test_responsable_direction_est_compte_comme_adulte_sans_double_compte(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        direction = Animateur.objects.create(prenom="Betty", nom="Direction")
        SortieResponsabilite.objects.create(
            sortie=sortie,
            animateur=direction,
            type=SortieResponsabilite.TYPE_DIRECTION,
        )
        premier = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertEqual(premier["totaux"]["animateurs"], 1)

        self._affecter(direction, self.groupe)
        second = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertEqual(second["totaux"]["animateurs"], 1)

    def test_catalogue_responsables_limite_aux_affectes_concernes_et_disponibles_libres(self):
        autre_centre = Centre.objects.create(nom="Centre extérieur", code="EXT")
        groupe_exterieur = Evenement.objects.create(
            centre=autre_centre,
            nom="Groupe extérieur",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
            enfants_par_animateur_defaut=12,
        )
        groupe_meme_lieu = Evenement.objects.create(
            centre=self.centre,
            nom="Ados",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
            enfants_par_animateur_defaut=12,
        )
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)

        affecte_groupe = Animateur.objects.create(prenom="Alice", nom="Groupe")
        affecte_lieu = Animateur.objects.create(prenom="Bruno", nom="Lieu")
        disponible_libre = Animateur.objects.create(prenom="Chloé", nom="Libre")
        indisponible = Animateur.objects.create(prenom="David", nom="Indisponible")
        affecte_ailleurs = Animateur.objects.create(prenom="Emma", nom="Ailleurs")
        flottant = Animateur.objects.create(prenom="Fanny", nom="Flottante")
        self._affecter(affecte_groupe, self.groupe)
        self._affecter(affecte_lieu, groupe_meme_lieu)
        self._rendre_disponible(disponible_libre)
        self._affecter(affecte_ailleurs, groupe_exterieur)
        self._affecter(flottant, groupe_flottants_pour_centre(self.centre))

        data = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        catalogue = {item["id"]: item for item in data["catalogue_animateurs"]}
        self.assertEqual(
            set(catalogue),
            {affecte_groupe.id, affecte_lieu.id, disponible_libre.id, flottant.id},
        )
        self.assertEqual(catalogue[affecte_groupe.id]["eligibilite"], "affecte")
        self.assertEqual(catalogue[affecte_lieu.id]["eligibilite"], "affecte")
        self.assertEqual(catalogue[disponible_libre.id]["eligibilite"], "disponible")
        self.assertNotIn(indisponible.id, catalogue)
        self.assertNotIn(affecte_ailleurs.id, catalogue)
        self.assertEqual(
            [item["id"] for item in data["animateurs_supplementaires"]],
            [disponible_libre.id],
        )

    def test_responsabilite_refuse_un_animateur_affecte_ailleurs(self):
        autre_centre = Centre.objects.create(nom="Centre extérieur", code="EXT2")
        groupe_exterieur = Evenement.objects.create(
            centre=autre_centre,
            nom="Groupe extérieur",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
            enfants_par_animateur_defaut=12,
        )
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Ailleurs")
        self._affecter(animateur, groupe_exterieur)

        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps(
                {
                    "responsabilites": [
                        {
                            "animateur_id": animateur.id,
                            "type": "direction",
                            "cibles": [],
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("disponible et non affecté", response.json()["error"])
        self.assertFalse(sortie.responsabilites.exists())

    def test_couleur_du_statut_est_exposee_sur_chaque_responsable(self):
        statut = Qualification.objects.create(nom="Diplômé", est_statut=True)
        animateur = Animateur.objects.create(prenom="Alice", nom="Diplômée")
        animateur.qualifications.add(statut)
        self._rendre_disponible(animateur)
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)

        catalogue = self.client.get(
            reverse("api_sortie_detail", args=[sortie.id])
        ).json()["catalogue_animateurs"]
        salarie = next(item for item in catalogue if item["id"] == animateur.id)
        self.assertEqual(salarie["statut_principal"]["nom"], "Diplômé")
        self.assertTrue(salarie["couleur_statut"].startswith("#"))
        self.assertTrue(salarie["couleur_fond_statut"].startswith("#"))

    def test_suppression_groupe_nettoie_les_responsabilites_associees(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe, self.groupe_2)
        animateur = Animateur.objects.create(prenom="Alice", nom="Test")
        SortieResponsabilite.objects.create(
            sortie=sortie,
            animateur=animateur,
            type=SortieResponsabilite.TYPE_GROUPE,
            evenement=self.groupe_2,
        )

        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps({"groupes": [self.groupe.id]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(sortie.responsabilites.exists())

    def test_ajout_depuis_repartition_cree_le_planning_et_recalcule_effectif(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        EffectifEnfantsJour.objects.create(evenement=self.groupe, date=self.jour, nombre=14)
        animateur = Animateur.objects.create(prenom="Alice", nom="Disponible")
        self._rendre_disponible(animateur)

        payload = {
            "animateur_id": animateur.id,
            "centre_id": self.centre.id,
            "evenement_id": self.groupe.id,
            "debut": self.jour.isoformat(),
        }
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        detail = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertEqual(len(detail["groupes"][0]["animateurs"]), 1)
        self.assertEqual(detail["groupes"][0]["ratio_reel"], 14)
        self.assertNotIn("affectation_id", detail["groupes"][0]["animateurs"][0])
        self.assertNotIn(animateur.id, [item["id"] for item in detail["catalogue_animateurs"] if item["eligibilite"] == "disponible"])

        doublon = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(doublon.status_code, 409)
        self.assertEqual(Affectation.objects.filter(animateur=animateur).count(), 1)

        second = Animateur.objects.create(prenom="Bruno", nom="Disponible")
        self._rendre_disponible(second)
        payload["animateur_id"] = second.id
        self.assertEqual(self.client.post(
            reverse("api_affectation_create"), data=json.dumps(payload),
            content_type="application/json",
        ).status_code, 201)
        detail = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertEqual(detail["groupes"][0]["ratio_reel"], 7)
        self.assertEqual(detail["groupes"][0]["non_couverts"], 0)

    def test_retrait_jour_planning_actualise_sortie_et_preserve_autres_jours(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Planifiée")
        self._rendre_disponible(animateur)
        debut = timezone.make_aware(datetime.datetime.combine(self.jour, datetime.time.min))
        affectation = Affectation.objects.create(
            animateur=animateur, centre=self.centre, evenement=self.groupe,
            debut=debut - datetime.timedelta(days=1), fin=debut + datetime.timedelta(days=2),
        )

        response = self.client.delete(
            reverse("api_affectation_detail", args=[affectation.id]) + f"?date={self.jour.isoformat()}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Affectation.objects.filter(animateur=animateur).count(), 2)
        detail = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertEqual(detail["groupes"][0]["animateurs"], [])
        self.assertIn(animateur.id, [item["id"] for item in detail["catalogue_animateurs"] if item["eligibilite"] == "disponible"])

    def test_utilisateur_non_direction_ne_peut_pas_modifier_le_planning(self):
        utilisateur = get_user_model().objects.create_user(username="animateur-test", password="secret-test")
        self.client.force_login(utilisateur)
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Affectation.objects.exists())

    def test_totaux_categories_multilieux_et_animateurs_uniques(self):
        autre_centre = Centre.objects.create(nom="Saint-Martin", code="SM")
        maternelle_2 = Evenement.objects.create(
            centre=autre_centre, nom="Maternelles", permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4], ferme_jours_feries=False,
        )
        elementaire_2 = Evenement.objects.create(
            centre=autre_centre, nom="Élémentaires", permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4], ferme_jours_feries=False,
        )
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe, self.groupe_2, maternelle_2, elementaire_2)
        for groupe, nombre in ((self.groupe, 7), (maternelle_2, 9), (self.groupe_2, 8), (elementaire_2, 11)):
            EffectifEnfantsJour.objects.create(evenement=groupe, date=self.jour, nombre=nombre)

        maternelle = Animateur.objects.create(prenom="Alice", nom="Maternelle")
        elementaire = Animateur.objects.create(prenom="Bruno", nom="Élémentaire")
        flottant = Animateur.objects.create(prenom="Chloé", nom="Flottante")
        # Une ancienne donnée incohérente ne doit malgré tout jamais doubler
        # une personne dans les agrégats de la fiche.
        self._affecter(maternelle, self.groupe)
        self._affecter(maternelle, maternelle_2)
        self._affecter(elementaire, self.groupe_2)
        self._affecter(flottant, groupe_flottants_pour_centre(autre_centre))

        totaux = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()["totaux"]
        self.assertEqual(totaux["categories"]["maternelle"], {"enfants": 16, "animateurs": 1})
        self.assertEqual(totaux["categories"]["elementaire"], {"enfants": 19, "animateurs": 1})
        self.assertEqual(totaux["animateurs_repartition"], 3)
        self.assertEqual([item["code"] for item in totaux["lieux"]], ["CT", "SM"])

    def test_colonne_affectes_est_strictement_informative(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        gabarit = Path(settings.BASE_DIR, "templates/sortie_detail.html").read_text()
        self.assertNotIn("data-remove-assignment", javascript)
        self.assertNotIn("sortie-removal-dialog", gabarit)
        self.assertNotIn('plural(totalGroups,"groupe")', javascript)

    def test_meteo_est_affichee_une_seule_fois_dans_la_synthese(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        styles = Path(settings.BASE_DIR, "static/css/sorties.css").read_text()
        self.assertNotIn("Météo de la sortie", javascript)
        self.assertEqual(javascript.count('data-block="meteo"'), 1)
        self.assertIn("weatherSummary(true)", javascript)
        self.assertIn("sortie-title-weather", javascript)
        self.assertNotIn("sortie-weather-kpi is-clickable", javascript)
        self.assertIn("repeat(auto-fit,minmax(min(180px,100%),1fr))", styles)

    def test_adresse_est_uniquement_dans_le_bandeau_principal(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        self.assertNotIn("<span>Adresse</span>", javascript)
        self.assertEqual(javascript.count("sortie-sheet-address"), 1)
        self.assertIn("destinationMarkup(data.destination_details)", javascript)
        self.assertIn("sortie-destination-name", javascript)
        self.assertIn("sortie-sheet-identity", javascript)

    def test_synthese_emploie_les_totaux_maternelles_et_elementaires(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        self.assertNotIn("<span>Enfants</span>", javascript)
        self.assertNotIn("<span>Adultes</span>", javascript)
        self.assertIn("<span>Maternelles</span>", javascript)
        self.assertIn("<span>Élémentaires</span>", javascript)
        self.assertIn("<span>Effectifs</span>", javascript)
        self.assertIn('plural(maternalTotal.enfants,"enfant")', javascript)
        self.assertIn('plural(elementaryTotal.animateurs,"animateur")', javascript)
        self.assertIn("buckets.maternels.length?", javascript)
        self.assertIn("buckets.elementaires.length?", javascript)
        self.assertNotIn("const maternalCard=", javascript)
        self.assertNotIn("const elementaryCard=", javascript)
        self.assertNotIn("function ageKey", javascript)
        self.assertIn('categoryBuckets[group.categorie_age]', javascript)

    def test_synthese_affiche_lieux_total_global_et_transport(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        self.assertIn("locationCodes.length?", javascript)
        self.assertIn("locationCodes.map(escapeHtml)", javascript)
        self.assertIn('class="sortie-effectifs-total"', javascript)
        self.assertIn("<span>Total</span>", javascript)
        self.assertIn('plural(totalChildren,"enfant")', javascript)
        self.assertIn('plural(totalAnimators,"animateur")', javascript)
        self.assertIn("<span>Transport</span>", javascript)

    def test_formulaire_transport_propose_quatre_modes_exclusifs(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        for mode in ("Car", "Minibus", "Ligne régulière", "Transport en commun"):
            self.assertIn(f'"{mode}"', javascript)
        self.assertIn('type="radio" name="mode_transport"', javascript)
        self.assertIn('["Car","Minibus"].includes(mode)', javascript)
        self.assertIn('mode==="Car"?"Nombre de cars":"Nombre de minibus"', javascript)

    def test_mode_enregistre_prime_sur_preference_et_preference_est_isolee(self):
        premiere = Sortie.objects.create(nom="Piscine", date=self.jour, destination="Piscine")
        url = reverse("api_sortie_detail", args=[premiere.id])
        response = self.client.patch(
            url,
            data=json.dumps({"mode_transport": "Minibus"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            PreferenceTransportUtilisateur.objects.get(utilisateur=self.compte_maitre).mode_transport,
            "Minibus",
        )

        sans_mode = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        transport = self.client.get(reverse("api_sortie_detail", args=[sans_mode.id])).json()["transport"]
        self.assertEqual(transport["mode_transport"], "")
        self.assertEqual(transport["mode_transport_suggere"], "Minibus")

        avec_mode = Sortie.objects.create(
            nom="Musée", date=self.jour, destination="Musée", mode_transport="Car"
        )
        transport = self.client.get(reverse("api_sortie_detail", args=[avec_mode.id])).json()["transport"]
        self.assertEqual(transport["mode_transport"], "Car")
        self.assertEqual(transport["mode_transport_suggere"], "Minibus")

        autre = get_user_model().objects.create_superuser(username="autre-direction", password="secret-test")
        self.client.force_login(autre)
        transport = self.client.get(reverse("api_sortie_detail", args=[sans_mode.id])).json()["transport"]
        self.assertEqual(transport["mode_transport_suggere"], "")

    def test_circuits_utilisent_une_seule_fois_les_lieux_concernes(self):
        autre_centre = Centre.objects.create(nom="Saint-Martin", code="SM", ordre=2)
        autre_groupe = Evenement.objects.create(
            centre=autre_centre, nom="Maternelles", permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4], ferme_jours_feries=False,
        )
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe, self.groupe_2, autre_groupe)

        transport = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()["transport"]
        self.assertEqual(
            [item["centre_id"] for item in transport["circuits"]["aller"]],
            [self.centre.id, autre_centre.id],
        )
        self.assertEqual(
            [item["centre_id"] for item in transport["circuits"]["retour"]],
            [autre_centre.id, self.centre.id],
        )

    def test_ordres_independants_et_horaires_generaux_sont_enregistres(self):
        autre_centre = Centre.objects.create(nom="Saint-Martin", code="SM", ordre=2)
        autre_groupe = Evenement.objects.create(
            centre=autre_centre, nom="Élémentaires", permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4], ferme_jours_feries=False,
        )
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe, autre_groupe)
        url = reverse("api_sortie_detail", args=[sortie.id])
        self.client.get(url)  # Initialise les circuits des anciennes sorties.
        payload = {
            "mode_transport": "Car",
            "nombre_vehicules": 2,
            "heure_depart": "08:30",
            "heure_arrivee": "10:00",
            "heure_retour": "16:00",
            "heure_arrivee_retour": "17:30",
            "circuit_aller": [autre_centre.id, self.centre.id],
            "circuit_retour": [self.centre.id, autre_centre.id],
        }
        response = self.client.patch(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        transport = self.client.get(url).json()["transport"]
        self.assertEqual([item["centre_id"] for item in transport["circuits"]["aller"]], payload["circuit_aller"])
        self.assertEqual([item["centre_id"] for item in transport["circuits"]["retour"]], payload["circuit_retour"])
        self.assertEqual(transport["heure_depart"], "08:30")
        self.assertNotIn("heure_depart_site", transport)
        self.assertEqual(transport["heure_arrivee"], "10:00")
        self.assertEqual(transport["heure_retour"], "16:00")
        self.assertEqual(transport["heure_arrivee_retour"], "17:30")
        self.assertNotIn("heure", {field.name for field in SortieEtapeTransport._meta.fields})

    def test_synchronisation_circuits_conserve_ordre_ajoute_et_retire_lieux(self):
        centre_b = Centre.objects.create(nom="Saint-Martin", code="SM", ordre=2)
        centre_c = Centre.objects.create(nom="Saint-Forgeux", code="SF", ordre=3)
        groupe_b = Evenement.objects.create(centre=centre_b, nom="Maternelles", permanent=True, jours_ouverts=[0, 1, 2, 3, 4], ferme_jours_feries=False)
        groupe_c = Evenement.objects.create(centre=centre_c, nom="Élémentaires", permanent=True, jours_ouverts=[0, 1, 2, 3, 4], ferme_jours_feries=False)
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        url = reverse("api_sortie_detail", args=[sortie.id])
        self.client.patch(url, data=json.dumps({"groupes": [self.groupe.id, groupe_b.id]}), content_type="application/json")
        self.client.patch(url, data=json.dumps({"circuit_aller": [centre_b.id, self.centre.id], "circuit_retour": [self.centre.id, centre_b.id]}), content_type="application/json")

        ajoute = self.client.patch(url, data=json.dumps({"groupes": [self.groupe.id, groupe_b.id, groupe_c.id]}), content_type="application/json").json()["transport"]["circuits"]
        self.assertEqual([item["centre_id"] for item in ajoute["aller"]], [centre_b.id, self.centre.id, centre_c.id])
        self.assertEqual([item["centre_id"] for item in ajoute["retour"]], [self.centre.id, centre_b.id, centre_c.id])

        retire = self.client.patch(url, data=json.dumps({"groupes": [self.groupe.id, groupe_c.id]}), content_type="application/json").json()["transport"]["circuits"]
        self.assertEqual([item["centre_id"] for item in retire["aller"]], [self.centre.id, centre_c.id])
        self.assertEqual([item["centre_id"] for item in retire["retour"]], [self.centre.id, centre_c.id])

    def test_circuit_invalide_ou_lieu_etranger_est_refuse(self):
        etranger = Centre.objects.create(nom="Étranger", code="EX")
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        url = reverse("api_sortie_detail", args=[sortie.id])
        for payload in (
            {"circuit_aller": [self.centre.id, self.centre.id], "circuit_retour": [self.centre.id]},
            {"circuit_aller": [etranger.id], "circuit_retour": [etranger.id]},
            {"circuit_aller": [self.centre.id]},
        ):
            response = self.client.patch(url, data=json.dumps(payload), content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_non_direction_ne_peut_pas_modifier_transport(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        utilisateur = get_user_model().objects.create_user(username="transport-interdit", password="secret-test")
        self.client.force_login(utilisateur)
        response = self.client.patch(
            reverse("api_sortie_detail", args=[sortie.id]),
            data=json.dumps({"mode_transport": "Car"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        sortie.refresh_from_db()
        self.assertEqual(sortie.mode_transport, "")

    def test_sortie_mixte_regroupe_elementaires_multilieux_et_conserve_total(self):
        autre_centre = Centre.objects.create(nom="Saint-Martin", code="SM", ordre=2)
        elementaire_sans_accent = Evenement.objects.create(
            centre=autre_centre,
            nom="Elementaire",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        groupe_autre = Evenement.objects.create(
            centre=autre_centre,
            nom="Ados",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe, self.groupe_2, elementaire_sans_accent, groupe_autre)
        for groupe, nombre in (
            (self.groupe, 7),
            (self.groupe_2, 8),
            (elementaire_sans_accent, 11),
            (groupe_autre, 5),
        ):
            EffectifEnfantsJour.objects.create(evenement=groupe, date=self.jour, nombre=nombre)

        data = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        categories_groupes = [item["categorie_age"] for item in data["groupes"]]
        self.assertEqual(categories_groupes.count("maternelle"), 1)
        self.assertEqual(categories_groupes.count("elementaire"), 2)
        self.assertEqual(categories_groupes.count("autre"), 1)
        self.assertEqual(data["totaux"]["categories"]["maternelle"]["enfants"], 7)
        self.assertEqual(data["totaux"]["categories"]["elementaire"]["enfants"], 19)
        self.assertEqual(data["totaux"]["categories"]["autre"]["enfants"], 5)
        self.assertEqual(
            data["totaux"]["enfants"],
            sum(item["enfants"] for item in data["totaux"]["categories"].values()),
        )
    def test_repartition_affiche_ratio_requis_reel_et_couverture(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        self.assertIn("Requis 1/", javascript)
        self.assertIn("Taux réel ${actual}", javascript)
        self.assertIn("bindRatioEditors", javascript)
        self.assertIn("ratios_encadrement", javascript)
        self.assertIn("Videz la valeur pour revenir au taux du groupe", javascript)
        self.assertIn("Number(row.group.non_couverts)", javascript)
        self.assertIn('missing?"is-danger":"is-ok"', javascript)
        self.assertNotIn("sortie-repartition-state", javascript)

    def test_taux_modifie_depuis_sortie_est_immediatement_partage_avec_planning(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        EffectifEnfantsJour.objects.create(evenement=self.groupe, date=self.jour, nombre=9)
        url_effectif = reverse("api_effectifs_enfants_groupe", args=[self.groupe.id])

        response = self.client.post(
            url_effectif,
            data=json.dumps({"ratios_encadrement": [{"date": self.jour.isoformat(), "ratio": 5}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        groupe = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()["groupes"][0]
        self.assertEqual(groupe["ratio"], 5)
        self.assertEqual(groupe["ratio_defaut"], 8)
        self.assertEqual(groupe["ratio_exceptionnel"], 5)

        self.client.post(
            url_effectif,
            data=json.dumps({"ratios_encadrement": [{"date": self.jour.isoformat(), "ratio": None}]}),
            content_type="application/json",
        )
        groupe = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()["groupes"][0]
        self.assertEqual(groupe["ratio"], 8)
        self.assertIsNone(groupe["ratio_exceptionnel"])

    def test_renfort_cree_affectation_et_peut_etre_detache_du_planning(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Renfort")
        self._rendre_disponible(animateur)
        response = self.client.post(
            reverse("api_sortie_renforts", args=[sortie.id]),
            data=json.dumps({"animateur_id": animateur.id, "evenement_id": self.groupe.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        renfort = SortieRenfort.objects.get(pk=response.json()["id"])
        affectation_id = renfort.affectation_id
        detail = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        self.assertEqual(detail["renforts"][0]["groupe"]["nom"], "Maternelles")

        response = self.client.delete(
            reverse("api_sortie_renfort_detail", args=[sortie.id, renfort.id]) + "?planning=0"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Affectation.objects.filter(pk=affectation_id).exists())
        self.assertFalse(SortieRenfort.objects.exists())

    def test_retrait_renfort_avec_planning_supprime_affectation(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        sortie.groupes.add(self.groupe)
        animateur = Animateur.objects.create(prenom="Alice", nom="Renfort")
        self._rendre_disponible(animateur)
        creation = self.client.post(
            reverse("api_sortie_renforts", args=[sortie.id]),
            data=json.dumps({"animateur_id": animateur.id, "evenement_id": self.groupe.id}),
            content_type="application/json",
        ).json()
        renfort = SortieRenfort.objects.get(pk=creation["id"])
        affectation_id = renfort.affectation_id
        self.client.delete(
            reverse("api_sortie_renfort_detail", args=[sortie.id, renfort.id]) + "?planning=1"
        )
        self.assertFalse(Affectation.objects.filter(pk=affectation_id).exists())
        self.assertFalse(SortieRenfort.objects.exists())

    def test_table_repartition_ne_contient_plus_les_animateurs_supplementaires(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        self.assertNotIn("Animateurs supplémentaires</th>", javascript)
        self.assertIn("Renforts animateurs", javascript)
        self.assertIn("Groupe et effectifs</th><th>Taux d’encadrement</th><th>Animateurs affectés", javascript)
        self.assertNotIn('colspan="2"', javascript)


class CategoriesGroupesTests(SimpleTestCase):
    def test_variantes_elementaires_sont_normalisees_par_la_regle_unique(self):
        variantes = (
            "Élémentaire",
            "Elementaire",
            "Elémentaire",
            "élémentaires",
            "  ÉLÉMENTAIRES  ",
            "6-10 ans",
            "6 / 11 ans",
        )
        for nom in variantes:
            with self.subTest(nom=nom):
                groupe = SimpleNamespace(groupe_id=None, cle_unique=normaliser_cle_unique(nom))
                self.assertEqual(categorie_age_groupe(groupe), "elementaire")

    def test_categorie_autre_est_explicite(self):
        groupe = SimpleNamespace(groupe_id=None, cle_unique="ados")
        self.assertEqual(categorie_age_groupe(groupe), "autre")
