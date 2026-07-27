"""Géocodage et prévisions des sorties, sans persistance des données météo."""

import datetime
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from animateurs.services.localisation import LocalisationError, geocoder_destination

logger = logging.getLogger(__name__)
TIMEOUT_EXTERNE = 5
SEUILS_VIGILANCE = {"rafales": 50, "uv": 6, "chaleur": 30, "froid": 5, "pluie": 3}

METEO_CODES = {
    0: ("Ciel dégagé", "☀", "clair"), 1: ("Éclaircies", "🌤", "eclaircies"),
    2: ("Partiellement nuageux", "⛅", "nuageux"), 3: ("Couvert", "☁", "couvert"),
    45: ("Brouillard", "🌫", "brouillard"), 48: ("Brouillard", "🌫", "brouillard"),
    51: ("Bruine", "🌦", "pluie"), 53: ("Bruine", "🌦", "pluie"), 55: ("Bruine", "🌧", "pluie"),
    61: ("Pluie", "🌧", "pluie"), 63: ("Pluie", "🌧", "pluie"), 65: ("Forte pluie", "🌧", "pluie"),
    71: ("Neige", "🌨", "neige"), 73: ("Neige", "🌨", "neige"), 75: ("Neige", "❄", "neige"),
    80: ("Averses", "🌦", "averses"), 81: ("Averses", "🌧", "averses"), 82: ("Fortes averses", "🌧", "averses"),
    95: ("Orage", "⛈", "orage"), 96: ("Orage", "⛈", "orage"), 99: ("Orage", "⛈", "orage"),
}


def code_meteo(code):
    libelle, pictogramme, classe = METEO_CODES.get(int(code or 0), ("Conditions variables", "◌", "variable"))
    return {"weather_code": int(code or 0), "libelle": libelle, "pictogramme": pictogramme, "classe": classe}


def _json_externe(url, params):
    requete = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params, doseq=True)}", headers={"User-Agent": "AnimationManager/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=TIMEOUT_EXTERNE) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON externe invalide")
            return data
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Service météo indisponible: %s", type(exc).__name__)
        raise RuntimeError("Service externe momentanément indisponible.") from exc


def _arrondi(value, digits=1):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0


def _indisponible(sortie, message, statut="indisponible"):
    return {"statut": statut, "message": message, "lieu": {"libelle": sortie.destination, "adresse": " ".join(filter(None, (sortie.destination_adresse, sortie.destination_code_postal, sortie.destination_commune)))}, "date": sortie.date.isoformat(), "vigilance_officielle": "non_configuree" if not settings.METEOFRANCE_VIGILANCE_API_KEY else "a_integrer"}


def prevision_sortie(sortie, forcer=False):
    if sortie.destination_latitude is None or sortie.destination_longitude is None:
        try:
            coordinates = geocoder_destination(
                sortie.destination,
                sortie.destination_adresse,
                sortie.destination_code_postal,
                sortie.destination_commune,
            )
            if coordinates:
                sortie.destination_latitude = coordinates["latitude"]
                sortie.destination_longitude = coordinates["longitude"]
                sortie.destination_precision = coordinates["precision"]
                sortie.save(update_fields=[
                    "destination_latitude", "destination_longitude", "destination_precision"
                ])
        except (LocalisationError, ValueError, TypeError):
            pass
    if sortie.destination_latitude is None or sortie.destination_longitude is None:
        return _indisponible(sortie, "Localisation de la destination à compléter", "sans_lieu")
    latitude, longitude = float(sortie.destination_latitude), float(sortie.destination_longitude)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return _indisponible(sortie, "Localisation météo invalide", "sans_lieu")
    ecart = (sortie.date - timezone.localdate()).days
    if ecart < 0:
        return _indisponible(sortie, "Sortie passée — prévision non actualisée")
    if ecart > 16:
        disponible = sortie.date - datetime.timedelta(days=16)
        return _indisponible(sortie, f"Prévision disponible à partir du {disponible.strftime('%d/%m/%Y')}")
    source = "meteo_france" if ecart <= 4 else "tendance"
    endpoint = "https://api.open-meteo.com/v1/meteofrance" if source == "meteo_france" else "https://api.open-meteo.com/v1/forecast"
    debut = (sortie.heure_depart or datetime.time(8)).strftime("%H:%M")
    fin = (sortie.heure_retour or datetime.time(18)).strftime("%H:%M")
    cle = f"sorties:meteo:{source}:{latitude:.5f}:{longitude:.5f}:{sortie.date}:{debut}:{fin}"
    if forcer:
        verrou = f"{cle}:actualisation"
        if not cache.add(verrou, True, 60):
            return _indisponible(sortie, "Actualisation déjà effectuée récemment", "limite")
        cache.delete(cle)
    cached = cache.get(cle)
    if cached is not None:
        return cached
    variables = ["temperature_2m", "apparent_temperature", "precipitation", "weather_code", "wind_speed_10m", "wind_gusts_10m"]
    daily = ["weather_code", "temperature_2m_min", "temperature_2m_max", "precipitation_sum", "wind_gusts_10m_max", "uv_index_max"]
    try:
        raw = _json_externe(endpoint, {"latitude": latitude, "longitude": longitude, "timezone": "Europe/Paris", "start_date": sortie.date.isoformat(), "end_date": sortie.date.isoformat(), "hourly": ",".join(variables), "daily": ",".join(daily)})
        hourly = raw.get("hourly") or {}
        times = hourly.get("time") or []
        heures = []
        for index, instant in enumerate(times):
            heure = str(instant)[11:16]
            if str(instant)[:10] != sortie.date.isoformat() or not (debut <= heure <= fin):
                continue
            item = {"heure": heure}
            for cle_api, cle_interne in (("temperature_2m", "temperature"), ("apparent_temperature", "temperature_ressentie"), ("precipitation", "precipitations_mm"), ("weather_code", "weather_code"), ("wind_speed_10m", "vent_kmh"), ("wind_gusts_10m", "rafales_kmh")):
                valeurs = hourly.get(cle_api) or []
                item[cle_interne] = _arrondi(valeurs[index] if index < len(valeurs) else 0, 1)
            item.update(code_meteo(item["weather_code"]))
            heures.append(item)
        if not heures:
            raise ValueError("Aucune donnée horaire")
        daily_data = raw.get("daily") or {}
        principal = (daily_data.get("weather_code") or [Counter(item["weather_code"] for item in heures).most_common(1)[0][0]])[0]
        resume = {"weather_code": int(principal), "temperature_min": min(item["temperature"] for item in heures), "temperature_max": max(item["temperature"] for item in heures), "temperature_ressentie_min": min(item["temperature_ressentie"] for item in heures), "temperature_ressentie_max": max(item["temperature_ressentie"] for item in heures), "precipitations_mm": round(sum(item["precipitations_mm"] for item in heures), 1), "vent_max_kmh": max(item["vent_kmh"] for item in heures), "rafales_max_kmh": max(item["rafales_kmh"] for item in heures), "uv_max": _arrondi((daily_data.get("uv_index_max") or [0])[0], 1)}
        alertes = []
        if 95 <= resume["weather_code"] <= 99:
            alertes.append("Risque d’orage")
        if resume["rafales_max_kmh"] >= SEUILS_VIGILANCE["rafales"]:
            alertes.append("Fortes rafales")
        if resume["uv_max"] >= SEUILS_VIGILANCE["uv"]:
            alertes.append("UV élevé")
        if resume["temperature_max"] >= SEUILS_VIGILANCE["chaleur"]:
            alertes.append("Chaleur importante")
        if resume["temperature_min"] <= SEUILS_VIGILANCE["froid"]:
            alertes.append("Froid")
        if resume["precipitations_mm"] >= SEUILS_VIGILANCE["pluie"]:
            alertes.append("Pluie notable pendant la sortie")
        resultat = {"statut": "prevision", "niveau_fiabilite": source, "source_libelle": "Météo-France — AROME / ARPEGE" if source == "meteo_france" else "Tendance à confirmer", "lieu": {"libelle": sortie.destination, "adresse": " ".join(filter(None, (sortie.destination_adresse, sortie.destination_code_postal, sortie.destination_commune)))}, "date": sortie.date.isoformat(), "plage": {"debut": debut, "fin": fin}, "resume": resume, "conditions": code_meteo(principal), "heures": heures, "alertes": alertes, "mis_a_jour_le": timezone.localtime().isoformat(), "vigilance_officielle": "non_configuree" if not settings.METEOFRANCE_VIGILANCE_API_KEY else "a_integrer"}
        cache.set(cle, resultat, 1800 if ecart == 0 else 3600 if source == "meteo_france" else 10800)
        return resultat
    except (RuntimeError, ValueError, TypeError, IndexError):
        return _indisponible(sortie, "Météo momentanément indisponible", "erreur")
