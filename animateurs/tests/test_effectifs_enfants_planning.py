import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
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
        self.assertTrue(EffectifEnfantsJour.objects.filter(
            evenement=self.groupe, date=date(2026, 7, 20), nombre=18
        ).exists())

        response = self.client.get(self.url, {"debut": "2026-07-20", "fin": "2026-07-21"})
        self.assertEqual(response.json(), [{
            "date": "2026-07-20",
            "nombre": 18,
            "enfants_par_animateur": 8,
            "ratio_encadrement_exceptionnel": None,
        }])

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
        self.assertEqual(response.json()[0]["effectifs_enfants"], [{
            "date": "2026-07-20",
            "nombre": 23,
            "enfants_par_animateur": 8,
            "ratio_encadrement_exceptionnel": None,
        }])

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
        self.groupe.enfants_par_animateur_defaut = 12
        self.groupe.save(update_fields=["enfants_par_animateur_defaut"])

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
        self.groupe.enfants_par_animateur_defaut = 10
        self.groupe.save(update_fields=["enfants_par_animateur_defaut"])

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
