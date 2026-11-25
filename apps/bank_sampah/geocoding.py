"""Nominatim geocoding for the "map may be down" fallback.

The mobile app never calls Google or a geocoder itself; this module is the
only outbound lookup, and it stays on a free provider. Nominatim's usage
policy (max 1 request/second, cache results) is handled here with a shared
database cache and a per-process limit on when outbound requests can start.
"""

import hashlib
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests
from django.core.cache import caches

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "pilah-app/1.0 (+https://github.com/bank-sampah-PILAH/pilah-be)"
CACHE_TTL_DETIK = 24 * 60 * 60
# Provider policy is one request per second. Overridable only so tests and
# local runs don't have to sleep the full second.
MIN_INTERVAL_DETIK = float(os.getenv("PILAH_GEOCODER_MIN_INTERVAL", "1"))
BATAS_HASIL = 5

# The database-backed alias keeps hits shared across gunicorn workers; the
# default LocMemCache would cache per process only.
_cache = caches["geocoding"]


class _PembatasPermintaan:
    """Space request starts within one process without waiting for responses."""

    def __init__(self) -> None:
        self._kunci = threading.Lock()
        self._panggilan_terakhir = 0.0

    def tunggu_slot(self) -> None:
        with self._kunci:
            jeda = self._panggilan_terakhir + MIN_INTERVAL_DETIK - time.monotonic()
            if jeda > 0:
                time.sleep(jeda)
            self._panggilan_terakhir = time.monotonic()


_pembatas = _PembatasPermintaan()


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


def _normalisasi(kueri: str) -> str:
    return " ".join(kueri.casefold().split())


def _kunci_cache(kueri: str) -> str:
    sidik = hashlib.sha256(_normalisasi(kueri).encode("utf-8")).hexdigest()
    return f"geocode:{sidik}"


def _ambil_dari_nominatim(kueri: str) -> list[dict[str, Any]]:
    """One outbound call, spaced from the previous one by the provider limit."""
    _pembatas.tunggu_slot()
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={
                "q": kueri,
                "format": "jsonv2",
                "limit": str(BATAS_HASIL),
                "countrycodes": "id",
            },
            headers={"User-Agent": user_agent()},
            timeout=10,
        )
        response.raise_for_status()
        hasil = response.json()
    except requests.RequestException as exc:
        raise GeocoderTidakTersedia(str(exc)) from exc
    return hasil if isinstance(hasil, list) else []


def _baris_ke_hasil(baris: Any) -> HasilGeocode | None:
    try:
        latitude = float(baris["lat"])
        longitude = float(baris["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not koordinat_valid(latitude, longitude):
        return None
    # Nominatim's place_rank is an importance class, not meters, so accuracy
    # stays empty rather than becoming an invented number.
    return HasilGeocode(
        latitude=latitude,
        longitude=longitude,
        alamat_hasil=baris.get("display_name"),
        akurasi_m=None,
    )


def _cari(kueri: str) -> list[HasilGeocode]:
    kunci = _kunci_cache(kueri)
    tersimpan = _cache.get(kunci)
    if tersimpan is None:
        tersimpan = _ambil_dari_nominatim(kueri)
        _cache.set(kunci, tersimpan, CACHE_TTL_DETIK)
    return [hasil for hasil in (_baris_ke_hasil(baris) for baris in tersimpan) if hasil is not None]


def geocode_alamat(query: str) -> HasilGeocode | None:
    hasil = _cari(query)
    return hasil[0] if hasil else None


def cari_tempat(kueri: str) -> list[HasilGeocode]:
    """Address search for the map picker; same cached rows, several results."""
    return _cari(kueri)
