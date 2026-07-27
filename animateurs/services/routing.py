"""Abstraction de géocodage et d'itinéraire pour les sorties.

Le fournisseur ne connaît ni Django ni les modèles métier. La composition du
circuit et la règle des arrêts restent ainsi testables indépendamment de l'API.
"""

import datetime
import hashlib
import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from animateurs.models import Sortie, SortieEtapeTransport
from animateurs.models import normaliser_cle_unique

logger = logging.getLogger(__name__)


class RoutingError(Exception):
    """Erreur fonctionnelle affichable sans exposer le détail fournisseur."""

    code = "ROUTING_FAILED"
    http_status = 502

    def __init__(self, message, *, code=None, http_status=None):
        super().__init__(message)
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status


class RoutingNotConfigured(RoutingError):
    code = "ROUTING_NOT_CONFIGURED"
    http_status = 503


class ProviderTimeout(RoutingError):
    code = "PROVIDER_TIMEOUT"
    http_status = 504


@dataclass(frozen=True)
class RoutingLocation:
    label: str
    address: str = ""
    postal_code: str = ""
    city: str = ""
    latitude: float | None = None
    longitude: float | None = None

    @property
    def precise(self):
        return bool(self.address)

    def search_text(self):
        """Construit la recherche selon la priorité fonctionnelle demandée."""

        if self.address:
            parts = (self.address, self.postal_code, self.city, "France")
        elif self.label and self.city:
            parts = (self.label, self.city, self.postal_code, "France")
        elif self.city:
            parts = (self.city, self.postal_code, "France")
        else:
            parts = (self.postal_code, "France")
        return ", ".join(part for part in parts if part)


class RoutingProvider:
    name = "base"
    profile = "driving-car"

    def geocode(self, location: RoutingLocation):
        raise NotImplementedError

    def calculate_route(self, coordinates):
        raise NotImplementedError


class GeoplateformeProvider(RoutingProvider):
    """Géocodage et itinéraires publics de la Géoplateforme IGN.

    Aucun jeton n'est nécessaire. Le service d'itinéraire est interrogé par
    tronçon afin de respecter sans ambiguïté l'ordre des étapes enregistré
    dans Animation Manager.
    """

    name = "geoplateforme"
    profile = "car"

    def __init__(
        self,
        timeout=8,
        *,
        geocoding_url="https://data.geopf.fr/geocodage/search",
        routing_url="https://data.geopf.fr/navigation/itineraire",
        resource="bdtopo-osrm",
    ):
        self.timeout = timeout
        self.geocoding_url = geocoding_url.rstrip("/")
        self.routing_url = routing_url.rstrip("/")
        self.resource = resource

    def _request_json(self, url, *, data=None):
        headers = {"Accept": "application/json", "User-Agent": "AnimationManager/1.0"}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            logger.warning("Délai Géoplateforme dépassé")
            raise ProviderTimeout("Le service d’itinéraire met trop de temps à répondre.") from exc
        except urllib.error.HTTPError as exc:
            logger.warning("Erreur HTTP Géoplateforme (%s)", exc.code)
            if exc.code in {408, 429, 502, 503, 504}:
                raise ProviderTimeout("Le service d’itinéraire est momentanément indisponible.") from exc
            raise RoutingError("Le service Géoplateforme a refusé le calcul d’itinéraire.") from exc
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise ProviderTimeout("Le service d’itinéraire met trop de temps à répondre.") from exc
            logger.warning("Échec réseau Géoplateforme (%s)", type(exc).__name__)
            raise RoutingError("Impossible de joindre le service d’itinéraire.") from exc
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Réponse Géoplateforme invalide (%s)", type(exc).__name__)
            raise RoutingError("La réponse du service d’itinéraire est invalide.") from exc

    def geocode(self, location):
        query = location.search_text()
        cache_key = "routing:geopf:geocode:" + hashlib.sha256(query.casefold().encode()).hexdigest()
        cached = cache.get(cache_key)
        if cached:
            return tuple(cached)
        params = urllib.parse.urlencode({"q": query, "limit": 5})
        payload = self._request_json(f"{self.geocoding_url}?{params}")
        candidates = []
        expected_city = normaliser_cle_unique(location.city)
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            coordinates = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coordinates) < 2:
                continue
            postal_code = str(
                props.get("postcode") or props.get("postalcode") or props.get("zipCode") or ""
            )
            if location.postal_code and postal_code and postal_code != location.postal_code:
                continue
            locality = normaliser_cle_unique(
                props.get("city"), props.get("municipality"), props.get("locality"),
                props.get("name"), props.get("label")
            )
            city_match = bool(expected_city and expected_city in locality)
            candidates.append((city_match, float(coordinates[0]), float(coordinates[1])))
        if not candidates:
            raise RoutingError(
                f"Le lieu {location.label} n’a pas pu être géocodé.",
                code="GEOCODING_FAILED", http_status=422,
            )
        if expected_city and not any(candidate[0] for candidate in candidates):
            raise RoutingError(
                f"La commune ou le code postal de {location.label} est incohérent.",
                code="GEOCODING_FAILED", http_status=422,
            )
        candidates.sort(key=lambda item: item[0], reverse=True)
        result = (candidates[0][1], candidates[0][2])
        cache.set(cache_key, result, 30 * 86400)
        return result

    def _calculate_leg(self, start, end):
        payload = self._request_json(
            self.routing_url,
            data={
                "resource": self.resource,
                "profile": self.profile,
                "optimization": "fastest",
                "start": f"{float(start[0])},{float(start[1])}",
                "end": f"{float(end[0])},{float(end[1])}",
                "timeUnit": "second",
                "distanceUnit": "meter",
                "getSteps": False,
                "getBbox": False,
                "crs": "EPSG:4326",
            },
        )
        try:
            duration = float(payload["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Réponse Géoplateforme sans durée exploitable")
            raise RoutingError(
                "La réponse du service d’itinéraire ne contient aucune durée exploitable."
            ) from exc
        if duration < 0:
            raise RoutingError("La durée renvoyée par le service d’itinéraire est invalide.")
        return duration

    def calculate_route(self, coordinates):
        if len(coordinates) < 2:
            raise RoutingError("Le circuit doit contenir au moins deux points.")
        return sum(
            self._calculate_leg(coordinates[index], coordinates[index + 1])
            for index in range(len(coordinates) - 1)
        )

def get_routing_provider():
    provider = settings.ROUTING_PROVIDER.casefold().strip()
    if provider in {"geoplateforme", "ign", "geopf"}:
        return GeoplateformeProvider(
            settings.ROUTING_TIMEOUT_SECONDS,
            geocoding_url=settings.ROUTING_GEOCODING_URL,
            routing_url=settings.ROUTING_API_URL,
            resource=settings.ROUTING_RESOURCE,
        )
    raise RoutingNotConfigured("Le fournisseur d’itinéraire n’est pas configuré.")


def routing_is_configured():
    return settings.ROUTING_PROVIDER.casefold().strip() in {"geoplateforme", "ign", "geopf"}


def _coordinates(provider, location, instance, latitude_field, longitude_field):
    if location.latitude is not None and location.longitude is not None:
        return location.longitude, location.latitude
    if not any((location.address, location.postal_code, location.city)):
        raise RoutingError(
            f"Le lieu {location.label} ne possède aucune adresse ou localisation exploitable.",
            code="LOCATION_MISSING", http_status=422,
        )
    longitude, latitude = provider.geocode(location)
    setattr(instance, latitude_field, latitude)
    setattr(instance, longitude_field, longitude)
    instance.save(update_fields=[latitude_field, longitude_field])
    return longitude, latitude


def _route_duration_cached(provider, coordinates):
    canonical = json.dumps([[round(float(lon), 6), round(float(lat), 6)] for lon, lat in coordinates])
    digest = hashlib.sha256(f"{provider.name}:{provider.profile}:{canonical}".encode()).hexdigest()
    key = f"routing:route:{digest}"
    duration = cache.get(key)
    if duration is None:
        duration = provider.calculate_route(coordinates)
        cache.set(key, duration, 86400)
    return float(duration)


@transaction.atomic
def estimate_sortie_route(sortie, direction, provider=None):
    if direction not in {SortieEtapeTransport.SENS_ALLER, SortieEtapeTransport.SENS_RETOUR}:
        raise RoutingError("Le sens du trajet est invalide.", code="INVALID_ROUTE", http_status=400)
    provider = provider or get_routing_provider()
    departure = sortie.heure_depart if direction == "aller" else sortie.heure_retour
    if not departure:
        label = "premier site" if direction == "aller" else "lieu de sortie"
        raise RoutingError(f"Renseignez l’heure de départ du {label}.")

    steps = list(
        sortie.etapes_transport.filter(sens=direction)
        .select_related("centre")
        .order_by("ordre", "id")
    )
    if not steps:
        raise RoutingError("Le circuit de transport ne contient aucun site.", code="INVALID_ROUTE", http_status=422)

    destination = RoutingLocation(
        label=sortie.destination,
        address=sortie.destination_adresse,
        postal_code=sortie.destination_code_postal,
        city=sortie.destination_commune,
        latitude=float(sortie.destination_latitude) if sortie.destination_latitude is not None else None,
        longitude=float(sortie.destination_longitude) if sortie.destination_longitude is not None else None,
    )
    if (
        destination.latitude is None
        and destination.longitude is None
        and not any((destination.address, destination.postal_code, destination.city))
    ):
        raise RoutingError(
            "La destination ne possède aucune adresse ou localisation exploitable.",
            code="LOCATION_MISSING", http_status=422,
        )
    try:
        destination_coordinates = _coordinates(
            provider, destination, sortie, "destination_latitude", "destination_longitude"
        )
    except RoutingError as exc:
        if exc.code == "GEOCODING_FAILED":
            raise RoutingError(
                "La destination n’a pas pu être localisée.",
                code="GEOCODING_FAILED", http_status=422,
            ) from exc
        raise
    site_coordinates = []
    precise = sortie.destination_precision == Sortie.PRECISION_ADRESSE
    for step in steps:
        centre = step.centre
        location = RoutingLocation(
            label=centre.nom,
            address=centre.adresse,
            postal_code=centre.code_postal,
            city=centre.commune,
            latitude=float(centre.latitude) if centre.latitude is not None else None,
            longitude=float(centre.longitude) if centre.longitude is not None else None,
        )
        precise = precise and centre.precision_localisation == "adresse"
        site_coordinates.append(_coordinates(provider, location, centre, "latitude", "longitude"))

    # L'ordre transmis est strictement celui enregistré ; aucune API
    # d'optimisation n'est appelée.
    coordinates = (
        site_coordinates + [destination_coordinates]
        if direction == "aller"
        else [destination_coordinates] + site_coordinates
    )
    road_seconds = _route_duration_cached(provider, coordinates)
    road_minutes = math.ceil(road_seconds / 60)
    stop_count = len(steps)
    # Chaque site compte comme un arrêt, y compris le premier site à l'aller.
    stop_minutes = stop_count * sortie.temps_arret_par_site
    total_minutes = road_minutes + stop_minutes
    arrival = (
        datetime.datetime.combine(sortie.date, departure) + datetime.timedelta(minutes=total_minutes)
    ).time().replace(second=0, microsecond=0)

    if direction == "aller":
        sortie.heure_arrivee = arrival
        sortie.source_heure_arrivee = Sortie.SOURCE_HORAIRE_AUTOMATIQUE
        sortie.save(update_fields=["heure_arrivee", "source_heure_arrivee"])
    else:
        sortie.heure_arrivee_retour = arrival
        sortie.source_heure_arrivee_retour = Sortie.SOURCE_HORAIRE_AUTOMATIQUE
        sortie.save(update_fields=["heure_arrivee_retour", "source_heure_arrivee_retour"])

    return {
        "success": True,
        "route_duration_minutes": road_minutes,
        "stop_count": stop_count,
        "stop_minutes_per_site": sortie.temps_arret_par_site,
        "stop_duration_minutes": stop_minutes,
        "total_duration_minutes": total_minutes,
        "estimated_arrival": arrival.isoformat(timespec="minutes"),
        "precision": "precise" if precise else "approximate",
        "source": "Géoplateforme IGN · BD TOPO",
    }
