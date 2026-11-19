"""Nominatim geocoding for the "map may be down" fallback.

The mobile app never calls Google or a geocoder itself; this module is the
only outbound lookup, and it stays on a free provider.
"""

import math
import os
from dataclasses import dataclass

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "pilah-app/1.0 (bank sampah directory)"


class GeocoderTidakTersedia(Exception):
    """Nominatim is unreachable or answered with an error."""


@dataclass(frozen=True)
class HasilGeocode:
    latitude: float
    longitude: float
    alamat_hasil: str | None
    akurasi_m: float | None


def user_agent() -> str:
    return os.getenv("PILAH_GEOCODER_USER_AGENT", DEFAULT_USER_AGENT)


def koordinat_valid(latitude: float, longitude: float) -> bool:
    """Finite WGS84 bounds; Never let NaN/inf or a swapped pair reach a client."""
    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def geocode_alamat(query: str) -> HasilGeocode | None:
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "id"},
            headers={"User-Agent": user_agent()},
            timeout=10,
        )
        response.raise_for_status()
        results = response.json()
    except requests.RequestException as exc:
        raise GeocoderTidakTersedia(str(exc)) from exc
    if not results:
        return None
    try:
        latitude = float(results[0]["lat"])
        longitude = float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not koordinat_valid(latitude, longitude):
        return None
    # Nominatim's place_rank is an importance class, not meters, so accuracy
    # stays empty rather than becoming an invented number.
    return HasilGeocode(
        latitude=latitude,
        longitude=longitude,
        alamat_hasil=results[0].get("display_name"),
        akurasi_m=None,
    )
