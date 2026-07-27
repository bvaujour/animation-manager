"""Recherche communale et géocodage partagés par les sorties et les lieux."""

import hashlib
import json
import logging
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from django.core.cache import cache

logger = logging.getLogger(__name__)
TIMEOUT_LOCALISATION = 5


class LocalisationError(Exception):
    """Erreur présentable à l'utilisateur sans détail technique externe."""


def _json_externe(url, params):
    query = urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "AnimationManager/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_LOCALISATION) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Service officiel de localisation indisponible (%s)", type(exc).__name__)
        raise LocalisationError("Recherche de communes momentanément indisponible.") from exc


def _communes(params, cache_key):
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    raw = _json_externe("https://geo.api.gouv.fr/communes", {
        **params,
        "fields": "nom,code,codesPostaux,centre",
        "format": "json",
        "geometry": "centre",
    })
    if not isinstance(raw, list):
        raise LocalisationError("Réponse de recherche de communes invalide.")
    results = []
    for commune in raw:
        centre = commune.get("centre") or {}
        coordinates = centre.get("coordinates") or []
        latitude = longitude = None
        if len(coordinates) >= 2:
            try:
                longitude, latitude = float(coordinates[0]), float(coordinates[1])
            except (TypeError, ValueError):
                pass
        for postal_code in commune.get("codesPostaux") or []:
            results.append({
                "nom": str(commune.get("nom") or ""),
                "code_postal": str(postal_code),
                "code_insee": str(commune.get("code") or ""),
                "latitude": latitude,
                "longitude": longitude,
            })
    cache.set(cache_key, results, 7 * 86400)
    return results


def rechercher_communes_par_code_postal(code_postal):
    code_postal = str(code_postal or "").strip()
    if len(code_postal) != 5 or not code_postal.isdigit():
        raise ValueError("Le code postal doit contenir exactement 5 chiffres.")
    return _communes(
        {"codePostal": code_postal},
        f"communes:code_postal:{code_postal}",
    )


def rechercher_communes_par_nom(nom, limite=12):
    nom = str(nom or "").strip()
    if len(nom) < 3 or len(nom) > 120:
        raise ValueError("Saisissez au moins 3 caractères du nom de la commune.")
    normalized = "-".join(nom.casefold().split())
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:24]
    return _communes(
        {"nom": nom, "boost": "population", "limit": min(max(int(limite), 1), 20)},
        f"communes:nom:{digest}",
    )[:limite]


def geocoder_destination(nom, adresse, code_postal, commune):
    """Géocode sans bloquer l'enregistrement ; le service appelant gère l'échec."""

    parts = [adresse, code_postal, commune] if adresse else [nom, commune, code_postal]
    query = ", ".join(str(part).strip() for part in parts if str(part or "").strip())
    if not code_postal:
        return None
    digest = hashlib.sha256(query.casefold().encode()).hexdigest()[:32]
    key = f"geocodage:destination:{digest}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    raw = _json_externe(
        "https://data.geopf.fr/geocodage/search",
        {"q": query, "limit": 5, "postcode": code_postal},
    )
    features = raw.get("features", []) if isinstance(raw, dict) else []
    for feature in features:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        result_postal = str(props.get("postcode") or "")
        if len(coords) < 2 or (result_postal and result_postal != code_postal):
            continue
        result = {
            "longitude": float(coords[0]),
            "latitude": float(coords[1]),
            "precision": "adresse" if adresse else "commune",
        }
        cache.set(key, result, 30 * 86400)
        return result
    raise LocalisationError("Impossible de localiser précisément cette destination.")


def _normaliser(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(character for character in value if not unicodedata.combining(character)).strip()


def resoudre_localisation(nom, adresse, code_postal, commune, code_insee=""):
    """Retourne une localisation officielle cohérente, utilisable par tout modèle métier."""

    code_postal = str(code_postal or "").strip()
    code_insee = str(code_insee or "").strip().upper()
    if not code_postal:
        return {"code_insee": "", "latitude": None, "longitude": None, "precision": "non_localisee"}
    if code_insee and not re.fullmatch(r"(?:\d{5}|2[AB]\d{3})", code_insee):
        raise ValueError("Le code INSEE sélectionné est invalide.")

    communes = rechercher_communes_par_code_postal(code_postal)
    commune_normalisee = _normaliser(commune)
    candidates = [
        item for item in communes
        if (not code_insee or item["code_insee"].upper() == code_insee)
        and (not commune_normalisee or _normaliser(item["nom"]) == commune_normalisee)
    ]
    if candidates:
        candidate = candidates[0]
        result = {
            "code_insee": candidate["code_insee"],
            "latitude": candidate["latitude"],
            "longitude": candidate["longitude"],
            "precision": "commune",
        }
        if adresse:
            try:
                precise = geocoder_destination(nom, adresse, code_postal, commune)
                if precise:
                    result.update(precise)
            except LocalisationError:
                # Une adresse non reconnue ne fait pas perdre le point fiable
                # déjà obtenu pour la commune.
                pass
        return result

    # Sans commune validée, un code postal partagé reste exploitable via le
    # barycentre des communes retournées, mais est explicitement approximatif.
    coordinates = [
        (item["longitude"], item["latitude"])
        for item in communes
        if item["longitude"] is not None and item["latitude"] is not None
    ]
    if coordinates and not commune_normalisee:
        return {
            "code_insee": "",
            "longitude": sum(item[0] for item in coordinates) / len(coordinates),
            "latitude": sum(item[1] for item in coordinates) / len(coordinates),
            "precision": "code_postal",
        }
    return {"code_insee": "", "latitude": None, "longitude": None, "precision": "non_localisee"}
