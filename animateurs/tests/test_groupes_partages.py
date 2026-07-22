import json

from django.urls import reverse

from animateurs.models import Centre, Evenement, Groupe, Qualification
from animateurs.tests.base import ConnexionTestCase


class GroupesPartagesTests(ConnexionTestCase):
    def setUp(self):
        self.centre_a = Centre.objects.create(nom="Lieu A", code="LA")
        self.centre_b = Centre.objects.create(nom="Lieu B", code="LB")
        self.bafa = Qualification.objects.create(nom="BAFA")

    def test_un_groupe_est_instancie_dans_plusieurs_lieux(self):
        response = self.client.post(
            reverse("api_groupes_partages"),
            data=json.dumps(
                {
                    "nom": "Maternelles",
                    "enfants_par_animateur_defaut": 8,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        groupe_id = response.json()["id"]

        for centre, effectif in ((self.centre_a, 2), (self.centre_b, 4)):
            response = self.client.post(
                reverse("api_groupes", args=[centre.id]),
                data=json.dumps(
                    {
                        "groupe_id": groupe_id,
                        "effectif_cible": effectif,
                        "jours_ouverts": [0, 1, 2, 3, 4],
                        "permanent": True,
                        "qualifications_requises": {str(self.bafa.id): effectif},
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201)

        instances = Evenement.objects.filter(groupe_id=groupe_id).order_by("centre_id")
        self.assertEqual(list(instances.values_list("effectif_cible", flat=True)), [2, 4])
        self.assertEqual(
            list(instances.values_list("besoins_qualifications__nombre_minimum", flat=True)),
            [2, 4],
        )

    def test_modifier_le_schema_necrase_pas_les_besoins_des_instances(self):
        groupe = Groupe.objects.create(nom="Maternelles", enfants_par_animateur_defaut=8)
        instance = Evenement.objects.create(groupe=groupe, centre=self.centre_a, nom=groupe.nom)
        instance.besoins_qualifications.create(qualification=self.bafa, nombre_minimum=2)

        response = self.client.patch(
            reverse("api_groupe_partage_detail", args=[groupe.id]),
            data=json.dumps({"nom": "Petits", "enfants_par_animateur_defaut": 6}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(instance.besoins_qualifications.get().nombre_minimum, 2)

    def test_modifier_le_groupe_propage_ses_caracteristiques_pas_les_effectifs(self):
        groupe = Groupe.objects.create(nom="Maternelles", enfants_par_animateur_defaut=8)
        instance_a = Evenement.objects.create(groupe=groupe, centre=self.centre_a, nom=groupe.nom, effectif_cible=2)
        instance_b = Evenement.objects.create(groupe=groupe, centre=self.centre_b, nom=groupe.nom, effectif_cible=4)

        response = self.client.patch(
            reverse("api_groupe_partage_detail", args=[groupe.id]),
            data=json.dumps(
                {
                    "nom": "Petits",
                    "enfants_par_animateur_defaut": 6,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        instance_a.refresh_from_db()
        instance_b.refresh_from_db()
        self.assertEqual((instance_a.nom, instance_a.enfants_par_animateur_defaut), ("Petits", 6))
        self.assertEqual((instance_b.nom, instance_b.enfants_par_animateur_defaut), ("Petits", 6))
        self.assertEqual((instance_a.effectif_cible, instance_b.effectif_cible), (2, 4))
