import datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Document,
    EffectifEnfantsJour,
    Evenement,
    Groupe,
    InformationAnimateur,
    PublicationPlanning,
    Sortie,
)


class ApercuPortailVisibiliteTests(TestCase):
    """Le compte direction ne doit jamais élargir les données du portail aperçu."""

    semaine = datetime.date(2026, 10, 19)

    def setUp(self):
        User = get_user_model()
        self.direction = User.objects.create_superuser("direction-visibilite", "dir@example.test", "secret")
        self.betty_user = User.objects.create_user("betty-visibilite", password="secret")
        self.betty = Animateur.objects.create(prenom="Betty", nom="Portail", utilisateur=self.betty_user)
        self.sans_affectation_user = User.objects.create_user("sans-affectation", password="secret")
        self.sans_affectation = Animateur.objects.create(
            prenom="Sans", nom="Affectation", utilisateur=self.sans_affectation_user
        )
        self.autre = Animateur.objects.create(prenom="Autre", nom="Centre")
        self.centre_betty = Centre.objects.create(nom="Centre Betty", code="BET")
        self.centre_autre = Centre.objects.create(nom="Centre Autre", code="AUT")
        self.groupe_betty = Groupe.objects.create(nom="Groupe Betty")
        self.groupe_autre = Groupe.objects.create(nom="Groupe Autre")
        self.evenement_betty = Evenement.objects.create(
            centre=self.centre_betty, groupe=self.groupe_betty, nom="Groupe Betty", jours_ouverts=[0, 1, 2, 3, 4]
        )
        self.evenement_autre = Evenement.objects.create(
            centre=self.centre_autre, groupe=self.groupe_autre, nom="Groupe Autre", jours_ouverts=[0, 1, 2, 3, 4]
        )
        debut = datetime.datetime.combine(self.semaine, datetime.time.min, tzinfo=datetime.timezone.utc)
        fin = debut + datetime.timedelta(days=5)
        Affectation.objects.create(
            animateur=self.betty, centre=self.centre_betty, evenement=self.evenement_betty, debut=debut, fin=fin
        )
        Affectation.objects.create(
            animateur=self.autre, centre=self.centre_autre, evenement=self.evenement_autre, debut=debut, fin=fin
        )
        PublicationPlanning.objects.create(semaine_debut=self.semaine, publie=True)
        EffectifEnfantsJour.objects.create(evenement=self.evenement_betty, date=self.semaine, nombre=12)
        EffectifEnfantsJour.objects.create(evenement=self.evenement_autre, date=self.semaine, nombre=18)

        information_betty = InformationAnimateur.objects.create(
            titre="Info Betty", message="Visible par Betty", date_debut=self.semaine,
            date_fin=self.semaine + datetime.timedelta(days=4), tous_animateurs=False,
        )
        information_betty.animateurs.add(self.betty)
        information_autre = InformationAnimateur.objects.create(
            titre="Info autre", message="Invisible pour Betty", date_debut=self.semaine,
            date_fin=self.semaine + datetime.timedelta(days=4), tous_animateurs=False,
        )
        information_autre.animateurs.add(self.autre)
        self.sortie_betty = Sortie.objects.create(nom="Sortie Betty", date=self.semaine, destination="Parc Betty")
        self.sortie_betty.groupes.add(self.evenement_betty)
        sortie_autre = Sortie.objects.create(nom="Sortie autre", date=self.semaine, destination="Parc autre")
        sortie_autre.groupes.add(self.evenement_autre)
        Document.objects.create(
            titre="Document publié", fichier=SimpleUploadedFile("document.txt", b"test"), permanent=True, publie=True
        )

    def _parametres_apercu(self, animateur):
        return {"apercu_portail": "1", "animateur_id": animateur.pk, "semaine": self.semaine.isoformat()}

    def _planning(self, utilisateur, **params):
        self.client.force_login(utilisateur)
        response = self.client.get(reverse("api_planning"), {
            "start": self.semaine.isoformat(),
            "end": (self.semaine + datetime.timedelta(days=7)).isoformat(),
            **params,
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _centres(self, utilisateur, **params):
        self.client.force_login(utilisateur)
        response = self.client.get(reverse("api_centres"), {
            "include_groupes": "1",
            "start": self.semaine.isoformat(),
            "end": (self.semaine + datetime.timedelta(days=7)).isoformat(),
            **params,
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _effectifs(self, utilisateur, **params):
        self.client.force_login(utilisateur)
        response = self.client.get(reverse("api_effectifs_enfants_plage"), {
            "debut": self.semaine.isoformat(),
            "fin": (self.semaine + datetime.timedelta(days=7)).isoformat(),
            **params,
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _marqueurs_sorties(self, utilisateur, **params):
        self.client.force_login(utilisateur)
        response = self.client.get(reverse("api_sorties_calendrier"), {
            "start": self.semaine.isoformat(),
            "end": (self.semaine + datetime.timedelta(days=7)).isoformat(),
            **params,
        })
        self.assertEqual(response.status_code, 200)
        return response.json()["sorties"]

    def _ids_contexte(self, utilisateur, route, cle, **params):
        self.client.force_login(utilisateur)
        response = self.client.get(reverse(route), params)
        self.assertEqual(response.status_code, 200)
        return [item.pk if hasattr(item, "pk") else item["id"] for item in response.context[cle]]

    def test_apercu_planning_reproduit_exactement_les_centres_de_betty(self):
        reel = self._planning(self.betty_user)
        apercu = self._planning(self.direction, **self._parametres_apercu(self.betty))

        self.assertEqual(apercu, reel)
        self.assertEqual({item["extendedProps"]["centre_id"] for item in apercu}, {self.centre_betty.pk})
        self.assertNotIn(self.centre_autre.pk, {item["extendedProps"]["centre_id"] for item in apercu})

    def test_apercu_planning_reproduit_aussi_la_structure_centres_groupes_et_effectifs(self):
        centres_reels = self._centres(self.betty_user)
        centres_apercu = self._centres(self.direction, **self._parametres_apercu(self.betty))
        effectifs_reels = self._effectifs(self.betty_user)
        effectifs_apercu = self._effectifs(self.direction, **self._parametres_apercu(self.betty))

        self.assertEqual(centres_apercu, centres_reels)
        self.assertEqual(effectifs_apercu, effectifs_reels)
        self.assertEqual([centre["id"] for centre in centres_apercu], [self.centre_betty.pk])
        self.assertEqual(
            [groupe["id"] for groupe in centres_apercu[0]["evenements"]], [self.evenement_betty.pk]
        )
        self.assertEqual({item["groupe_id"] for item in effectifs_apercu}, {self.evenement_betty.pk})

    def test_apercu_d_un_animateur_sans_affectation_ne_recoit_aucun_planning(self):
        reel = self._planning(self.sans_affectation_user)
        apercu = self._planning(self.direction, **self._parametres_apercu(self.sans_affectation))
        centres_reels = self._centres(self.sans_affectation_user)
        centres_apercu = self._centres(self.direction, **self._parametres_apercu(self.sans_affectation))

        self.assertEqual(reel, [])
        self.assertEqual(apercu, reel)
        self.assertEqual(centres_reels, [])
        self.assertEqual(centres_apercu, centres_reels)

    def test_marqueurs_sorties_ne_peuvent_cibler_que_les_groupes_visibles(self):
        centres_reels = self._centres(self.betty_user)
        centres_apercu = self._centres(self.direction, **self._parametres_apercu(self.betty))
        marqueurs_reels = self._marqueurs_sorties(self.betty_user)
        marqueurs_apercu = self._marqueurs_sorties(self.direction, **self._parametres_apercu(self.betty))

        groupes_visibles_reels = {
            groupe["id"] for centre in centres_reels for groupe in centre["evenements"]
        }
        groupes_visibles_apercu = {
            groupe["id"] for centre in centres_apercu for groupe in centre["evenements"]
        }
        marqueurs_rendus_reels = {
            groupe_id for sortie in marqueurs_reels for groupe_id in sortie["groupe_ids"]
            if groupe_id in groupes_visibles_reels
        }
        marqueurs_rendus_apercu = {
            groupe_id for sortie in marqueurs_apercu for groupe_id in sortie["groupe_ids"]
            if groupe_id in groupes_visibles_apercu
        }

        self.assertEqual(groupes_visibles_apercu, groupes_visibles_reels)
        self.assertEqual(marqueurs_rendus_apercu, marqueurs_rendus_reels)
        self.assertEqual(marqueurs_rendus_apercu, {self.evenement_betty.pk})
        self.assertNotIn(self.evenement_autre.pk, marqueurs_rendus_apercu)

    def test_infos_sorties_et_documents_sont_identiques_en_reel_et_apercu(self):
        for route, cle in (
            ("infos_animateur", "informations"),
            ("sorties_animateur", "sorties"),
            ("documents_animateur", "documents"),
        ):
            with self.subTest(route=route):
                reel = self._ids_contexte(self.betty_user, route, cle, semaine=self.semaine.isoformat())
                apercu = self._ids_contexte(self.direction, route, cle, **self._parametres_apercu(self.betty))
                self.assertEqual(apercu, reel)

    def test_accueil_materiel_et_profil_utilisent_l_animateur_previsualise(self):
        self.client.force_login(self.betty_user)
        accueil_reel = self.client.get(reverse("accueil"), {"semaine": self.semaine.isoformat()})
        materiel_reel = self.client.get(reverse("demandes_materiel"), {"semaine": self.semaine.isoformat()})
        profil_reel = self.client.get(reverse("mon_profil"))

        self.client.force_login(self.direction)
        params = self._parametres_apercu(self.betty)
        accueil_apercu = self.client.get(reverse("apercu_portail_animateur"), params)
        materiel_apercu = self.client.get(reverse("demandes_materiel"), params)
        profil_apercu = self.client.get(reverse("mon_profil"), params)

        self.assertEqual(
            [jour.get("centre") for jour in accueil_apercu.context["jours"]],
            [jour.get("centre") for jour in accueil_reel.context["jours"]],
        )
        self.assertEqual(
            [demande.pk for demande in materiel_apercu.context["demandes"]],
            [demande.pk for demande in materiel_reel.context["demandes"]],
        )
        self.assertEqual(profil_apercu.context["animateur"].pk, profil_reel.context["animateur"].pk)
