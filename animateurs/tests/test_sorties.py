import datetime
import json
from unittest.mock import patch

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
    Sortie,
    SortieResponsabilite,
)
from animateurs.services.flottants import groupe_flottants_pour_centre
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

    def test_enregistre_et_valide_la_localisation_meteo(self):
        sortie = Sortie.objects.create(nom="Parc", date=self.jour, destination="Parc")
        url = reverse("api_sortie_detail", args=[sortie.id])
        response = self.client.patch(url, data=json.dumps({"meteo_lieu_libelle": "Paléopolis", "meteo_adresse": "03800 Gannat", "meteo_latitude": 46.18, "meteo_longitude": 3.19, "meteo_code_departement": "03"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["meteo_lieu"]["libelle"], "Paléopolis")
        invalide = self.client.patch(url, data=json.dumps({"meteo_latitude": 120, "meteo_longitude": 3}), content_type="application/json")
        self.assertEqual(invalide.status_code, 400)

    @patch("animateurs.views_sorties.geocoder_lieux")
    def test_api_geocodage_ne_retourne_que_les_resultats_internes(self, geocoder):
        geocoder.return_value = [{"libelle": "Parc", "adresse": "Gannat", "latitude": 46.18, "longitude": 3.19, "code_departement": "03"}]
        response = self.client.get(reverse("api_sorties_geocodage"), {"q": "Parc Gannat"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resultats"][0]["code_departement"], "03")

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
        self.assertEqual(ligne["animateurs_requis"], 2)
        self.assertEqual(ligne["non_couverts"], 0)

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
        self._affecter(affecte_groupe, self.groupe)
        self._affecter(affecte_lieu, groupe_meme_lieu)
        self._rendre_disponible(disponible_libre)
        self._affecter(affecte_ailleurs, groupe_exterieur)

        data = self.client.get(reverse("api_sortie_detail", args=[sortie.id])).json()
        catalogue = {item["id"]: item for item in data["catalogue_animateurs"]}
        self.assertEqual(
            set(catalogue),
            {affecte_groupe.id, affecte_lieu.id, disponible_libre.id},
        )
        self.assertEqual(catalogue[affecte_groupe.id]["eligibilite"], "affecte")
        self.assertEqual(catalogue[affecte_lieu.id]["eligibilite"], "affecte")
        self.assertEqual(catalogue[disponible_libre.id]["eligibilite"], "disponible")
        self.assertNotIn(indisponible.id, catalogue)
        self.assertNotIn(affecte_ailleurs.id, catalogue)

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
