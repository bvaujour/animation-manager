import json
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from animateurs.models import Centre, EffectifEnfantsJour, Evenement


class EffectifsEnfantsPlanningTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="direction", password="test")
        user.is_superuser = True
        user.is_staff = True
        user.save()
        self.client.force_login(user)
        self.centre = Centre.objects.create(nom="Centre test", code="CT")
        self.groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Maternels",
            permanent=True,
            enfants_par_animateur_defaut=8,
        )
        self.url = reverse("api_effectifs_enfants_groupe", args=[self.groupe.id])

    def test_enregistre_lit_et_efface_un_effectif(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"effectifs": [{"date": "2026-07-20", "nombre": 18}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            EffectifEnfantsJour.objects.filter(evenement=self.groupe, date=date(2026, 7, 20), nombre=18).exists()
        )

        response = self.client.get(self.url, {"debut": "2026-07-20", "fin": "2026-07-21"})
        self.assertEqual(
            response.json(),
            [
                {
                    "date": "2026-07-20",
                    "nombre": 18,
                    "enfants_par_animateur": 8,
                    "ratio_encadrement_exceptionnel": None,
                    "heure_arrivee": "",
                    "heure_depart": "",
                }
            ],
        )

        response = self.client.post(
            self.url,
            data=json.dumps({"effectifs": [{"date": "2026-07-20", "nombre": 0}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EffectifEnfantsJour.objects.filter(evenement=self.groupe).exists())

    def test_saisie_effectif_preserve_le_ratio_exceptionnel(self):
        EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=date(2026, 7, 20),
            nombre=12,
            enfants_par_animateur=6,
            ratio_encadrement_exceptionnel=6,
        )

        response = self.client.post(
            self.url,
            data=json.dumps({"effectifs": [{"date": "2026-07-20", "nombre": 18}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        ligne = EffectifEnfantsJour.objects.get(evenement=self.groupe, date=date(2026, 7, 20))
        self.assertEqual(ligne.nombre, 18)
        self.assertEqual(ligne.ratio_encadrement_exceptionnel, 6)
        self.assertEqual(ligne.ratio_encadrement_effectif, 6)

    def test_enregistre_et_reinitialise_un_ratio_exceptionnel(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"ratios_encadrement": [{"date": "2026-07-20", "ratio": 5}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        ligne = EffectifEnfantsJour.objects.get(evenement=self.groupe, date=date(2026, 7, 20))
        self.assertEqual(ligne.nombre, 0)
        self.assertEqual(ligne.ratio_encadrement_exceptionnel, 5)
        self.assertEqual(ligne.ratio_encadrement_effectif, 5)

        response = self.client.post(
            self.url,
            data=json.dumps({"ratios_encadrement": [{"date": "2026-07-20", "ratio": None}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EffectifEnfantsJour.objects.filter(evenement=self.groupe).exists())

    def test_liste_groupes_contient_les_effectifs_persistes(self):
        EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=date(2026, 7, 20),
            nombre=23,
            enfants_par_animateur=8,
        )

        response = self.client.get(reverse("api_groupes", args=[self.centre.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0]["effectifs_enfants"],
            [
                {
                    "date": "2026-07-20",
                    "nombre": 23,
                    "enfants_par_animateur": 8,
                    "ratio_encadrement_exceptionnel": None,
                    "heure_arrivee": "",
                    "heure_depart": "",
                }
            ],
        )

    def test_enregistre_les_horaires_de_la_journee_du_groupe(self):
        response = self.client.post(
            self.url,
            data=json.dumps(
                {
                    "horaires": [
                        {
                            "date": "2026-07-20",
                            "heure_arrivee": "08:00",
                            "heure_depart": "17:30",
                        }
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        ligne = EffectifEnfantsJour.objects.get(evenement=self.groupe, date=date(2026, 7, 20))
        self.assertEqual(ligne.heure_arrivee.strftime("%H:%M"), "08:00")
        self.assertEqual(ligne.heure_depart.strftime("%H:%M"), "17:30")

    def test_effacer_un_effectif_preserve_horaires_et_ratio_exceptionnel(self):
        ligne = EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=date(2026, 7, 20),
            nombre=18,
            enfants_par_animateur=6,
            ratio_encadrement_exceptionnel=6,
            heure_arrivee="08:00",
            heure_depart="17:30",
        )

        response = self.client.post(
            self.url,
            data=json.dumps({"effectifs": [{"date": "2026-07-20", "nombre": 0}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        ligne.refresh_from_db()
        self.assertEqual(ligne.nombre, 0)
        self.assertEqual(ligne.ratio_encadrement_exceptionnel, 6)
        self.assertEqual(ligne.heure_arrivee.strftime("%H:%M"), "08:00")
        self.assertEqual(ligne.heure_depart.strftime("%H:%M"), "17:30")

    def test_refuse_des_horaires_incomplets_ou_inverses(self):
        for arrivee, depart in (("08:00", ""), ("18:00", "08:00")):
            response = self.client.post(
                self.url,
                data=json.dumps(
                    {
                        "horaires": [
                            {
                                "date": "2026-07-20",
                                "heure_arrivee": arrivee,
                                "heure_depart": depart,
                            }
                        ]
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)

    def test_effacer_les_horaires_preserve_le_nombre_enfants(self):
        ligne = EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=date(2026, 7, 20),
            nombre=18,
            heure_arrivee="08:00",
            heure_depart="17:30",
        )

        response = self.client.post(
            self.url,
            data=json.dumps(
                {
                    "horaires": [
                        {
                            "date": "2026-07-20",
                            "heure_arrivee": "",
                            "heure_depart": "",
                        }
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        ligne.refresh_from_db()
        self.assertEqual(ligne.nombre, 18)
        self.assertIsNone(ligne.heure_arrivee)
        self.assertIsNone(ligne.heure_depart)

    def test_lecture_effectifs_interdit_la_mise_en_cache(self):
        EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=date(2026, 7, 20),
            nombre=12,
            enfants_par_animateur=8,
        )

        response = self.client.get(self.url, {"debut": "2026-07-20", "fin": "2026-07-21"})

        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("no-cache", cache_control)
        self.assertIn("no-store", cache_control)

    def test_ratio_par_defaut_du_groupe_est_utilise(self):
        self.groupe.groupe.enfants_par_animateur_defaut = 12
        self.groupe.groupe.save(update_fields=["enfants_par_animateur_defaut"])
        self.groupe.save()

        response = self.client.post(
            self.url,
            data=json.dumps({"effectifs": [{"date": "2026-07-20", "nombre": 24}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        ligne = EffectifEnfantsJour.objects.get(evenement=self.groupe, date=date(2026, 7, 20))
        self.assertEqual(ligne.ratio_encadrement_effectif, 12)
        self.assertIsNone(ligne.ratio_encadrement_exceptionnel)

    def test_liste_groupes_expose_le_ratio_par_defaut(self):
        self.groupe.groupe.enfants_par_animateur_defaut = 10
        self.groupe.groupe.save(update_fields=["enfants_par_animateur_defaut"])
        self.groupe.save()

        response = self.client.get(reverse("api_groupes", args=[self.centre.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["enfants_par_animateur_defaut"], 10)

    def test_refuse_un_nombre_invalide(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"effectifs": [{"date": "2026-07-20", "nombre": -1}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_refuse_un_ratio_exceptionnel_invalide(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"ratios_encadrement": [{"date": "2026-07-20", "ratio": 0}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_liste_plage_regroupe_tous_les_groupes_et_filtre_les_dates(self):
        autre_groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Élémentaires",
            permanent=True,
            enfants_par_animateur_defaut=12,
        )
        EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=date(2026, 7, 20),
            nombre=18,
            enfants_par_animateur=8,
        )
        EffectifEnfantsJour.objects.create(
            evenement=autre_groupe,
            date=date(2026, 7, 21),
            nombre=24,
            enfants_par_animateur=12,
        )
        EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=date(2026, 8, 3),
            nombre=10,
            enfants_par_animateur=8,
        )

        response = self.client.get(
            reverse("api_effectifs_enfants_plage"),
            {"debut": "2026-07-20", "fin": "2026-07-27"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(item["groupe_id"], item["date"], item["nombre"]) for item in response.json()],
            [
                (self.groupe.id, "2026-07-20", 18),
                (autre_groupe.id, "2026-07-21", 24),
            ],
        )
        self.assertIn("no-cache", response.headers["Cache-Control"])

    def test_liste_plage_ne_fait_pas_une_requete_par_effectif(self):
        for index in range(20):
            groupe = Evenement.objects.create(
                centre=self.centre,
                nom=f"Groupe performance {index:02d}",
                permanent=True,
                enfants_par_animateur_defaut=8 + (index % 2),
            )
            EffectifEnfantsJour.objects.create(
                evenement=groupe,
                date=date(2026, 7, 20),
                nombre=10 + index,
                enfants_par_animateur=8,
            )

        with CaptureQueriesContext(connection) as contexte:
            response = self.client.get(
                reverse("api_effectifs_enfants_plage"),
                {"debut": "2026-07-20", "fin": "2026-07-27"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 20)
        self.assertLessEqual(
            len(contexte),
            4,
            f"La lecture des effectifs a effectué {len(contexte)} requêtes.",
        )

