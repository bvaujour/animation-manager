import datetime
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from animateurs.models import Sortie
from animateurs.services.meteo_sorties import code_meteo, prevision_sortie


def sortie(date, debut=None, retour=None):
    return Sortie(
        nom="Parc", destination="Parc", date=date,
        destination_adresse="Route de Bègues", destination_code_postal="03800",
        destination_commune="Gannat", destination_latitude=Decimal("46.180000"),
        destination_longitude=Decimal("3.190000"), destination_precision="adresse",
        heure_depart=debut, heure_retour=retour,
    )


def reponse_meteo(date):
    times = [f"{date.isoformat()}T{hour:02d}:00" for hour in range(24)]
    return {
        "hourly": {
            "time": times, "temperature_2m": list(range(24)),
            "apparent_temperature": [value + 1 for value in range(24)],
            "precipitation": [0.5] * 24, "weather_code": [2] * 24,
            "wind_speed_10m": [12] * 24, "wind_gusts_10m": [55] * 24,
        },
        "daily": {"weather_code": [2], "uv_index_max": [7]},
    }


class MeteoSortiesServiceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.today = datetime.date(2026, 7, 1)

    def test_sans_coordonnees(self):
        item = sortie(self.today)
        item.destination_latitude = None
        item.destination_longitude = None
        item.destination_code_postal = ""
        self.assertEqual(prevision_sortie(item)["statut"], "sans_lieu")

    def test_sortie_lointaine_et_passee_ne_font_pas_appel(self):
        with patch("animateurs.services.meteo_sorties._json_externe") as appel, patch("animateurs.services.meteo_sorties.timezone.localdate", return_value=self.today):
            self.assertEqual(prevision_sortie(sortie(self.today + datetime.timedelta(days=17)))["statut"], "indisponible")
            self.assertIn("passée", prevision_sortie(sortie(self.today - datetime.timedelta(days=1)))["message"])
            appel.assert_not_called()

    def test_sources_et_filtrage_horaire(self):
        for days, endpoint in ((2, "meteofrance"), (8, "forecast")):
            date = self.today + datetime.timedelta(days=days)
            with patch("animateurs.services.meteo_sorties.timezone.localdate", return_value=self.today), patch("animateurs.services.meteo_sorties._json_externe", return_value=reponse_meteo(date)) as appel:
                resultat = prevision_sortie(sortie(date, datetime.time(9), datetime.time(11)))
                self.assertEqual([item["heure"] for item in resultat["heures"]], ["09:00", "10:00", "11:00"])
                self.assertIn(endpoint, appel.call_args.args[0])
                self.assertEqual(resultat["resume"]["temperature_min"], 9)
                self.assertEqual(resultat["resume"]["temperature_max"], 11)
                self.assertEqual(resultat["resume"]["precipitations_mm"], 1.5)
                self.assertIn("Fortes rafales", resultat["alertes"])
                self.assertIn("UV élevé", resultat["alertes"])

    def test_plage_par_defaut_et_cache(self):
        date = self.today + datetime.timedelta(days=2)
        with patch("animateurs.services.meteo_sorties.timezone.localdate", return_value=self.today), patch("animateurs.services.meteo_sorties._json_externe", return_value=reponse_meteo(date)) as appel:
            premier = prevision_sortie(sortie(date))
            second = prevision_sortie(sortie(date))
            self.assertEqual(premier["plage"], {"debut": "08:00", "fin": "18:00"})
            self.assertEqual(premier, second)
            appel.assert_called_once()

    def test_erreur_reseau_reste_un_payload_metier(self):
        date = self.today + datetime.timedelta(days=2)
        with patch("animateurs.services.meteo_sorties.timezone.localdate", return_value=self.today), patch("animateurs.services.meteo_sorties._json_externe", side_effect=RuntimeError):
            self.assertEqual(prevision_sortie(sortie(date))["statut"], "erreur")

    def test_mapping_codes(self):
        self.assertEqual(code_meteo(0)["libelle"], "Ciel dégagé")
        self.assertEqual(code_meteo(95)["classe"], "orage")

    def test_actualisation_forcee_contourne_le_cache_et_est_limitee(self):
        date = self.today + datetime.timedelta(days=2)
        with patch("animateurs.services.meteo_sorties.timezone.localdate", return_value=self.today), patch("animateurs.services.meteo_sorties._json_externe", return_value=reponse_meteo(date)) as appel:
            item = sortie(date)
            prevision_sortie(item)
            self.assertEqual(prevision_sortie(item, forcer=True)["statut"], "prevision")
            self.assertEqual(prevision_sortie(item, forcer=True)["statut"], "limite")
            self.assertEqual(appel.call_count, 2)
