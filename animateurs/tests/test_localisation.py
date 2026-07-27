from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase

from animateurs.services.localisation import (
    LocalisationError,
    geocoder_destination,
    rechercher_communes_par_code_postal,
    rechercher_communes_par_nom,
    resoudre_localisation,
)


COMMUNES = [
    {
        "nom": "Saint-Germain-Lespinasse",
        "code": "42230",
        "codesPostaux": ["42640"],
        "centre": {"coordinates": [3.963, 46.103]},
    },
    {
        "nom": "Noailly",
        "code": "42156",
        "codesPostaux": ["42640"],
        "centre": {"coordinates": [4.014, 46.137]},
    },
]


class LocalisationServiceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("animateurs.services.localisation._json_externe", return_value=COMMUNES)
    def test_recherche_par_code_postal_retourne_communes_codes_insee_et_coordonnees(self, external):
        results = rechercher_communes_par_code_postal("42640")
        self.assertEqual([item["nom"] for item in results], ["Saint-Germain-Lespinasse", "Noailly"])
        self.assertEqual(results[0]["code_insee"], "42230")
        self.assertEqual(results[0]["latitude"], 46.103)
        self.assertEqual(rechercher_communes_par_code_postal("42640"), results)
        external.assert_called_once()

    @patch("animateurs.services.localisation._json_externe", return_value=COMMUNES[:1])
    def test_recherche_par_nom_est_mise_en_cache(self, external):
        results = rechercher_communes_par_nom("Saint-For")
        self.assertEqual(results[0]["code_postal"], "42640")
        rechercher_communes_par_nom("Saint-For")
        external.assert_called_once()

    def test_recherches_invalides_sont_refusees(self):
        with self.assertRaises(ValueError):
            rechercher_communes_par_code_postal("42A40")
        with self.assertRaises(ValueError):
            rechercher_communes_par_nom("St")

    @patch("animateurs.services.localisation.geocoder_destination")
    @patch("animateurs.services.localisation.rechercher_communes_par_code_postal")
    def test_resolution_commune_et_adresse_complete(self, communes, geocoder):
        communes.return_value = [{"nom": "Gannat", "code_postal": "03800", "code_insee": "03118", "latitude": 46.1, "longitude": 3.2}]
        geocoder.return_value = {"latitude": 46.18, "longitude": 3.19, "precision": "adresse"}
        precise = resoudre_localisation("Paléopolis", "Route de Bègues", "03800", "Gannat", "03118")
        self.assertEqual(precise["precision"], "adresse")
        self.assertEqual(precise["longitude"], 3.19)
        geocoder.side_effect = LocalisationError("Adresse inconnue")
        commune = resoudre_localisation("Paléopolis", "Route inconnue", "03800", "Gannat", "03118")
        self.assertEqual(commune["precision"], "commune")
        self.assertEqual(commune["longitude"], 3.2)

    @patch("animateurs.services.localisation._json_externe")
    def test_geocodage_adresse_est_prioritaire_et_mis_en_cache(self, external):
        external.return_value = {"features": [{
            "geometry": {"coordinates": [3.19, 46.18]},
            "properties": {"postcode": "03800"},
        }]}
        result = geocoder_destination("Paléopolis", "Route de Bègues", "03800", "Gannat")
        self.assertEqual(result["precision"], "adresse")
        self.assertEqual(result["latitude"], 46.18)
        geocoder_destination("Paléopolis", "Route de Bègues", "03800", "Gannat")
        external.assert_called_once()
        self.assertIn("Route de Bègues", external.call_args.args[1]["q"])

    @patch("animateurs.services.localisation._json_externe", side_effect=LocalisationError)
    def test_panne_service_est_encapsulee(self, external):
        with self.assertRaises(LocalisationError):
            rechercher_communes_par_code_postal("42640")

    def test_composant_est_reutilisable_bidirectionnel_et_sans_boucle(self):
        javascript = Path(settings.BASE_DIR, "static/js/common/location-autocomplete.js").read_text()
        gestion = Path(settings.BASE_DIR, "static/js/gestion.js").read_text()
        sortie = Path(settings.BASE_DIR, "templates/sorties.html").read_text()
        self.assertIn("function initLocationAutocomplete", javascript)
        self.assertIn("params.code_postal", javascript)
        self.assertIn("{nom:value}", javascript)
        self.assertIn("if(automatic)return", javascript)
        self.assertIn("response.resultats.length===1", javascript)
        self.assertIn("render(response.resultats)", javascript)
        self.assertIn('event.key==="Escape"', javascript)
        self.assertIn('event.key==="ArrowDown"', javascript)
        self.assertIn("initLocationAutocomplete", gestion)
        self.assertIn("data-location-autocomplete", gestion)
        self.assertIn("data-location-autocomplete", sortie)

    def test_changement_code_postal_actualise_meteo_et_trajets_sans_rechargement(self):
        javascript = Path(settings.BASE_DIR, "static/js/sortie-detail.js").read_text()
        self.assertIn("refreshDestinationCalculations", javascript)
        self.assertIn('meteo/?forcer=1', javascript)
        self.assertIn('["aller","heure_depart"', javascript)
        self.assertIn('["retour","heure_retour"', javascript)
        self.assertIn("postalCodeChanged", javascript)
        self.assertNotIn("location.reload", javascript)
