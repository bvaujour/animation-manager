import json

from animateurs.models import EquivalenceQualification, Qualification
from animateurs.tests.base import ConnexionTestCase


class EquivalencesQualificationsApiTests(ConnexionTestCase):
    def test_ancien_format_cree_une_equivalence_double_sens(self):
        bafa = Qualification.objects.create(nom="BAFA")

        response = self.client.post(
            "/api/qualifications/",
            data=json.dumps({
                "nom": "BPJEPS",
                "selectionnable_remplissage_auto": True,
                "equivalence_ids": [bafa.id],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        bpjeps = Qualification.objects.get(nom="BPJEPS")
        relation = EquivalenceQualification.objects.get()
        self.assertEqual(
            {relation.qualification_a_id, relation.qualification_b_id},
            {bafa.id, bpjeps.id},
        )
        self.assertEqual(relation.sens, EquivalenceQualification.SENS_DOUBLE)
        self.assertEqual(response.json()["relations_equivalence"][0]["sens"], "double")

    def test_creation_avec_equivalence_a_sens_unique(self):
        bafa = Qualification.objects.create(nom="BAFA")

        response = self.client.post(
            "/api/qualifications/",
            data=json.dumps({
                "nom": "BPJEPS",
                "relations_equivalence": [
                    {"qualification_id": bafa.id, "sens": "sortante"},
                ],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        bpjeps = Qualification.objects.get(nom="BPJEPS")
        relation = EquivalenceQualification.objects.get()
        # BPJEPS a été créé après BAFA : il est donc stocké côté B.
        self.assertEqual(relation.qualification_a_id, bafa.id)
        self.assertEqual(relation.qualification_b_id, bpjeps.id)
        self.assertEqual(relation.sens, EquivalenceQualification.SENS_B_VERS_A)
        self.assertEqual(response.json()["relations_equivalence"][0]["sens"], "sortante")

    def test_modification_remplace_toutes_les_relations_de_la_qualification(self):
        bafa = Qualification.objects.create(nom="BAFA")
        bpjeps = Qualification.objects.create(nom="BPJEPS")
        cpjeps = Qualification.objects.create(nom="CPJEPS")
        EquivalenceQualification.objects.create(
            qualification_a=bafa,
            qualification_b=bpjeps,
            sens=EquivalenceQualification.SENS_DOUBLE,
        )

        response = self.client.patch(
            f"/api/qualifications/{bafa.id}/",
            data=json.dumps({
                "relations_equivalence": [
                    {"qualification_id": cpjeps.id, "sens": "entrante"},
                ],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EquivalenceQualification.objects.count(), 1)
        relation = EquivalenceQualification.objects.get()
        self.assertEqual(
            {relation.qualification_a_id, relation.qualification_b_id},
            {bafa.id, cpjeps.id},
        )
        payload = response.json()["relations_equivalence"]
        self.assertEqual(payload, [{
            "qualification_id": cpjeps.id,
            "id": cpjeps.id,
            "nom": "CPJEPS",
            "sens": "entrante",
        }])
