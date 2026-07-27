import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from animateurs.models import Centre, Evenement, Sortie
from animateurs.services.routing import (
    GeoplateformeProvider,
    ProviderTimeout,
    RoutingError,
    RoutingLocation,
    RoutingProvider,
    estimate_sortie_route,
)
from animateurs.services.sorties import synchroniser_circuits_transport
from animateurs.tests.base import ConnexionTestCase


class FakeRoutingProvider(RoutingProvider):
    name = "fake-routing-tests"

    def __init__(self, duration=3900):
        self.duration = duration
        self.geocoded = []
        self.routes = []

    def geocode(self, location):
        self.geocoded.append(location)
        index = len(self.geocoded)
        return 3.0 + index / 10, 46.0 + index / 10

    def calculate_route(self, coordinates):
        self.routes.append(list(coordinates))
        return self.duration


class EstimationTrajetSortieTests(ConnexionTestCase):
    def setUp(self):
        cache.clear()
        self.jour = datetime.date(2026, 7, 27)
        self.centre_a = Centre.objects.create(
            nom="Saint-Martin", code="SM", adresse="1 rue du Bourg",
            code_postal="42640", commune="Saint-Martin-d'Estréaux", ordre=1,
        )
        self.centre_b = Centre.objects.create(
            nom="Saint-Forgeux", code="SF", code_postal="69490", commune="Saint-Forgeux", ordre=2,
        )
        self.groupe_a = Evenement.objects.create(
            centre=self.centre_a, nom="Maternelles", permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4], ferme_jours_feries=False,
        )
        self.groupe_b = Evenement.objects.create(
            centre=self.centre_b, nom="Élémentaires", permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4], ferme_jours_feries=False,
        )
        self.sortie = Sortie.objects.create(
            nom="Paléopolis", date=self.jour, destination="Paléopolis",
            destination_adresse="3 route de Bègues", destination_code_postal="03800",
            destination_commune="Gannat", heure_depart=datetime.time(8),
            heure_retour=datetime.time(16), temps_arret_par_site=10,
        )
        self.sortie.groupes.add(self.groupe_a, self.groupe_b)
        synchroniser_circuits_transport(self.sortie)

    def test_code_postal_francais_est_valide_cote_modele(self):
        Centre(nom="Valide", code="VA", code_postal="42640").full_clean()
        with self.assertRaises(ValidationError):
            Centre(nom="Invalide", code="IN", code_postal="4264A").full_clean()

    def test_api_lieu_enregistre_adresse_ou_code_postal_et_refuse_format_invalide(self):
        url = reverse("api_centre_detail", args=[self.centre_a.id])
        response = self.client.patch(
            url, data=json.dumps({"adresse": "12 rue Exemple", "code_postal": "42640", "commune": "Saint-Germain"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["adresse"], "12 rue Exemple")
        self.assertEqual(response.json()["code_postal"], "42640")
        invalide = self.client.patch(
            url, data=json.dumps({"code_postal": "42A40"}), content_type="application/json",
        )
        self.assertEqual(invalide.status_code, 400)

    @patch("animateurs.views_catalogue.resoudre_localisation")
    def test_api_lieu_geocode_et_stocke_localisation_structuree(self, resoudre):
        resoudre.return_value = {"code_insee": "42230", "latitude": 46.103, "longitude": 3.963, "precision": "commune"}
        response = self.client.patch(
            reverse("api_centre_detail", args=[self.centre_a.id]),
            data=json.dumps({
                "adresse": "", "code_postal": "42640", "commune": "Saint-Germain-Lespinasse",
                "code_insee": "42230", "localisation_demandee": True,
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code_insee"], "42230")
        self.assertEqual(response.json()["precision_localisation"], "commune")
        self.assertEqual(response.json()["longitude"], 3.963)

    def test_coordonnees_enregistrees_sont_reutilisees_sans_geocodage(self):
        self.centre_a.latitude, self.centre_a.longitude = 46.1, 3.1
        self.centre_b.latitude, self.centre_b.longitude = 46.2, 3.2
        self.centre_a.save(); self.centre_b.save()
        self.sortie.destination_latitude, self.sortie.destination_longitude = 46.3, 3.3
        self.sortie.save()
        provider = FakeRoutingProvider()
        estimate_sortie_route(self.sortie, "aller", provider)
        self.assertEqual(provider.geocoded, [])
        self.assertEqual(provider.routes[0], [(3.1, 46.1), (3.2, 46.2), (3.3, 46.3)])

    def test_lieu_incomplet_retourne_code_erreur_metier(self):
        self.centre_a.adresse = self.centre_a.code_postal = self.centre_a.commune = ""
        self.centre_a.latitude = self.centre_a.longitude = None
        self.centre_a.save()
        with self.assertRaises(RoutingError) as raised:
            estimate_sortie_route(self.sortie, "aller", FakeRoutingProvider())
        self.assertEqual(raised.exception.code, "LOCATION_MISSING")
        self.assertIn("Saint-Martin", str(raised.exception))
        with patch("animateurs.services.routing.get_routing_provider", return_value=FakeRoutingProvider()):
            response = self.client.post(
                reverse("api_sortie_estimation_trajet", args=[self.sortie.id]),
                data=json.dumps({"sens": "aller"}), content_type="application/json",
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "LOCATION_MISSING")

    def test_destination_incomplete_est_distinguee_du_lieu(self):
        self.sortie.destination_adresse = self.sortie.destination_code_postal = self.sortie.destination_commune = ""
        self.sortie.destination_latitude = self.sortie.destination_longitude = None
        self.sortie.save()
        with self.assertRaises(RoutingError) as raised:
            estimate_sortie_route(self.sortie, "aller", FakeRoutingProvider())
        self.assertEqual(raised.exception.code, "LOCATION_MISSING")
        self.assertIn("destination", str(raised.exception))

    def test_timeout_et_reponse_fournisseur_invalide_sont_distingues(self):
        provider = GeoplateformeProvider(1)
        with patch("animateurs.services.routing.urllib.request.urlopen", side_effect=TimeoutError):
            with self.assertRaises(ProviderTimeout) as timeout:
                provider.calculate_route([(3.1, 46.1), (3.2, 46.2)])
        self.assertEqual(timeout.exception.code, "PROVIDER_TIMEOUT")
        with patch.object(provider, "_request_json", return_value={}):
            with self.assertRaises(RoutingError) as invalid:
                provider.calculate_route([(3.1, 46.1), (3.2, 46.2)])
        self.assertEqual(invalid.exception.code, "ROUTING_FAILED")

    def test_geoplateforme_recoit_longitude_latitude_sans_authentification(self):
        provider = GeoplateformeProvider(8)
        response = MagicMock()
        response.read.return_value = json.dumps({"duration": 600}).encode()
        response.__enter__.return_value = response
        with patch("animateurs.services.routing.urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(provider.calculate_route([(3.1, 46.1), (3.2, 46.2)]), 600)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertNotIn("Authorization", request.headers)
        payload = json.loads(request.data)
        self.assertEqual(payload["resource"], "bdtopo-osrm")
        self.assertEqual(payload["profile"], "car")
        self.assertEqual(payload["start"], "3.1,46.1")
        self.assertEqual(payload["end"], "3.2,46.2")
        self.assertEqual(payload["timeUnit"], "second")

    def test_geoplateforme_additionne_les_troncons_dans_lordre(self):
        provider = GeoplateformeProvider(8)
        with patch.object(provider, "_calculate_leg", side_effect=[300, 420]) as calculate_leg:
            duration = provider.calculate_route([(3.1, 46.1), (3.2, 46.2), (3.3, 46.3)])
        self.assertEqual(duration, 720)
        self.assertEqual(calculate_leg.call_args_list[0].args, ((3.1, 46.1), (3.2, 46.2)))
        self.assertEqual(calculate_leg.call_args_list[1].args, ((3.2, 46.2), (3.3, 46.3)))

    def test_destination_structuree_est_facultative_et_validee(self):
        url = reverse("api_sortie_detail", args=[self.sortie.id])
        response = self.client.patch(
            url, data=json.dumps({"destination_adresse": "", "destination_code_postal": "42640", "destination_commune": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["destination_details"]["code_postal"], "42640")
        # La destination reste enregistrable sans géographie ; seule l'estimation sera impossible.
        response = self.client.patch(
            url, data=json.dumps({"destination_code_postal": ""}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        invalide = self.client.patch(
            url, data=json.dumps({"destination_code_postal": "0380"}), content_type="application/json",
        )
        self.assertEqual(invalide.status_code, 400)

    @patch("animateurs.views_sorties.resoudre_localisation")
    def test_selection_commune_enregistre_code_insee_coordonnees_et_precision(self, resoudre):
        resoudre.return_value = {"code_insee": "03118", "latitude": 46.18, "longitude": 3.19, "precision": "adresse"}
        response = self.client.patch(
            reverse("api_sortie_detail", args=[self.sortie.id]),
            data=json.dumps({
                "destination": "Paléopolis",
                "destination_adresse": "Route de Bègues",
                "destination_code_postal": "03800",
                "destination_commune": "Gannat",
                "destination_code_insee": "03118",
                "destination_localisation_demandee": True,
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        details = response.json()["destination_details"]
        self.assertEqual(details["code_insee"], "03118")
        self.assertEqual(details["latitude"], 46.18)
        self.assertEqual(details["precision"], "adresse")

    def test_modification_destination_invalide_coordonnees_et_meteo_associee(self):
        self.sortie.destination_latitude = 46.18
        self.sortie.destination_longitude = 3.19
        self.sortie.destination_precision = "adresse"
        self.sortie.save()
        response = self.client.patch(
            reverse("api_sortie_detail", args=[self.sortie.id]),
            data=json.dumps({"destination_commune": "Vichy"}), content_type="application/json",
        )
        details = response.json()["destination_details"]
        self.assertIsNone(details["latitude"])
        self.assertIsNone(details["longitude"])
        self.assertEqual(details["precision"], "non_localisee")
        self.assertIsNone(response.json()["meteo_lieu"]["latitude"])

    def test_geocodage_priorise_adresse_complete_et_accepte_code_postal_seul(self):
        precise = RoutingLocation("Paléopolis", "3 route de Bègues", "03800", "Gannat")
        approximatif = RoutingLocation("Salle des fêtes", postal_code="42640")
        self.assertEqual(precise.search_text(), "3 route de Bègues, 03800, Gannat, France")
        self.assertEqual(approximatif.search_text(), "42640, France")
        self.assertTrue(precise.precise)
        self.assertFalse(approximatif.precise)

    def test_aller_respecte_ordre_et_ajoute_arret_pour_chaque_site(self):
        provider = FakeRoutingProvider()
        result = estimate_sortie_route(self.sortie, "aller", provider)
        self.assertEqual(result["route_duration_minutes"], 65)
        self.assertEqual(result["stop_count"], 2)
        self.assertEqual(result["stop_duration_minutes"], 20)
        self.assertEqual(result["total_duration_minutes"], 85)
        self.assertEqual(result["estimated_arrival"], "09:25")
        self.assertEqual(provider.geocoded[0].label, "Paléopolis")
        self.assertEqual([item.label for item in provider.geocoded[1:]], ["Saint-Martin", "Saint-Forgeux"])
        # Les coordonnées de l'aller sont sites ordonnés puis destination.
        self.assertEqual(provider.routes[0], [(3.2, 46.2), (3.3, 46.3), (3.1, 46.1)])
        self.sortie.refresh_from_db()
        self.assertEqual(self.sortie.source_heure_arrivee, "automatique")

    def test_retour_part_de_destination_et_compte_toutes_les_deposes(self):
        provider = FakeRoutingProvider(duration=3600)
        result = estimate_sortie_route(self.sortie, "retour", provider)
        self.assertEqual(result["estimated_arrival"], "17:20")
        self.assertEqual(provider.routes[0][0], (3.1, 46.1))
        self.assertEqual(result["stop_count"], 2)

    def test_cache_itineraire_evite_un_second_appel_fournisseur(self):
        provider = FakeRoutingProvider()
        estimate_sortie_route(self.sortie, "aller", provider)
        estimate_sortie_route(self.sortie, "aller", provider)
        self.assertEqual(len(provider.routes), 1)

    def test_erreur_externe_nefface_pas_heure_manuelle(self):
        class BrokenProvider(FakeRoutingProvider):
            def calculate_route(self, coordinates):
                raise RoutingError("Service indisponible")

        self.sortie.heure_arrivee = datetime.time(9, 45)
        self.sortie.source_heure_arrivee = "manuelle"
        self.sortie.save(update_fields=["heure_arrivee", "source_heure_arrivee"])
        with self.assertRaisesMessage(RoutingError, "Service indisponible"):
            estimate_sortie_route(self.sortie, "aller", BrokenProvider())
        self.sortie.refresh_from_db()
        self.assertEqual(self.sortie.heure_arrivee, datetime.time(9, 45))
        self.assertEqual(self.sortie.source_heure_arrivee, "manuelle")

    @override_settings(ROUTING_PROVIDER="")
    def test_fournisseur_desactive_ne_casse_pas_page_et_endpoint_reste_explicite(self):
        self.assertEqual(self.client.get(reverse("sortie_detail", args=[self.sortie.id])).status_code, 200)
        response = self.client.post(
            reverse("api_sortie_estimation_trajet", args=[self.sortie.id]),
            data=json.dumps({"sens": "aller"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("configuré", response.json()["error"])
        self.assertEqual(response.json()["code"], "ROUTING_NOT_CONFIGURED")
        self.assertFalse(response.json()["success"])

    def test_endpoint_utilise_le_service_cote_serveur(self):
        with patch("animateurs.services.routing.get_routing_provider", return_value=FakeRoutingProvider()):
            response = self.client.post(
                reverse("api_sortie_estimation_trajet", args=[self.sortie.id]),
                data=json.dumps({"sens": "aller"}), content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estimated_arrival"], "09:25")

    def test_utilisateur_non_direction_ne_peut_pas_estimer(self):
        utilisateur = get_user_model().objects.create_user(username="sans-droit", password="secret-test")
        self.client.force_login(utilisateur)
        response = self.client.post(
            reverse("api_sortie_estimation_trajet", args=[self.sortie.id]),
            data=json.dumps({"sens": "aller"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_utilisateur_non_direction_ne_peut_pas_modifier_destination(self):
        utilisateur = get_user_model().objects.create_user(username="sans-droit-destination", password="secret-test")
        self.client.force_login(utilisateur)
        response = self.client.patch(
            reverse("api_sortie_detail", args=[self.sortie.id]),
            data=json.dumps({"destination_commune": "Vichy"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_changement_circuit_invalide_estimation_automatique_mais_pas_manuelle(self):
        estimate_sortie_route(self.sortie, "aller", FakeRoutingProvider())
        url = reverse("api_sortie_detail", args=[self.sortie.id])
        response = self.client.patch(
            url,
            data=json.dumps({
                "circuit_aller": [self.centre_b.id, self.centre_a.id],
                "circuit_retour": [self.centre_a.id, self.centre_b.id],
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transport"]["heure_arrivee"], "")

        self.client.patch(
            url, data=json.dumps({"heure_arrivee": "09:50"}), content_type="application/json",
        )
        response = self.client.patch(
            url,
            data=json.dumps({
                "circuit_aller": [self.centre_a.id, self.centre_b.id],
                "circuit_retour": [self.centre_b.id, self.centre_a.id],
            }), content_type="application/json",
        )
        self.assertEqual(response.json()["transport"]["heure_arrivee"], "09:50")
        self.assertEqual(response.json()["transport"]["source_heure_arrivee"], "manuelle")

    def test_formulaire_ne_reference_plus_depart_vers_destination(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        self.assertNotIn("heure_depart_site", javascript)
        self.assertNotIn("Départ vers la destination", javascript)
        self.assertIn("Temps d’arrêt par site", javascript)
        self.assertIn("Estimer l’heure d’arrivée", javascript)
