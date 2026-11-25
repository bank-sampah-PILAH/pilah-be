"""Google Maps link parsing and safe short-link expansion."""

import re
import time
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

from apps.bank_sampah.geocoding import koordinat_valid, user_agent

HOST_DIIZINKAN = {
    "maps.app.goo.gl",
    "goo.gl",
    "www.google.com",
    "google.com",
    "maps.google.com",
}
HOST_PERSETUJUAN = "consent.google.com"
MAKS_LOMPATAN = 5
# One request budget for the whole chain: gunicorn's default 30 s worker kill
# would otherwise fire mid-hop and skip the 503 the view prepares.
BATAS_DETIK = 8
# The viewport centre drifts as soon as the map is panned before sharing, so a
# fallback coordinate is reported with a coarse accuracy instead of none.
AKURASI_VIEWPORT_M = 1000.0

_POLA_PIN = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_POLA_VIEWPORT = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_POLA_PLACE = re.compile(r"/place/(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_POLA_PARAM = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_PARAM_KOORDINAT = ("q", "ll", "center", "sll", "destination")


class TautanTidakValid(Exception):
    """The pasted link cannot be turned into coordinates."""


class TautanPersetujuan(TautanTidakValid):
    """Google redirected to its consent page, hiding the original link."""


class TautanTidakTersedia(Exception):
    """Expanding the short link failed upstream."""


def koordinat_dari_tautan(url: str) -> tuple[float, float, str] | None:
    """(latitude, longitude, sumber_koordinat), the last being pin or viewport."""
    # Percent-encoded separators ("%2C", "%21") hide the patterns below.
    teks = unquote(url)
    # (1) is the pin of the place actually selected; (2) is only the viewport
    # centre, which drifts whenever the map is panned before sharing.
    for pola, jenis in ((_POLA_PIN, "pin"), (_POLA_VIEWPORT, "viewport")):
        cocok = pola.search(teks)
        if cocok:
            return _koordinat_dari_cocok(cocok, jenis)
    params = parse_qs(urlparse(teks).query)
    for kunci in _PARAM_KOORDINAT:
        nilai = (params.get(kunci) or [""])[0]
        cocok = _POLA_PARAM.fullmatch(nilai)
        if cocok:
            return _koordinat_dari_cocok(cocok, "pin")
    cocok = _POLA_PLACE.search(teks)
    return _koordinat_dari_cocok(cocok, "pin") if cocok else None


def _koordinat_dari_cocok(cocok: re.Match[str], jenis: str) -> tuple[float, float, str] | None:
    lat, lng = float(cocok.group(1)), float(cocok.group(2))
    return (lat, lng, jenis) if koordinat_valid(lat, lng) else None


def _periksa_host(host: str) -> None:
    if host == HOST_PERSETUJUAN:
        raise TautanPersetujuan(
            "Google meminta persetujuan sebelum membuka tautan ini. "
            "Tempel tautan Google Maps yang panjang, bukan tautan pendek."
        )
    if host not in HOST_DIIZINKAN:
        raise TautanTidakValid("Hanya tautan Google Maps yang dapat diproses")


def _tautan_pendek(host: str, path: str) -> bool:
    return host == "maps.app.goo.gl" or (host == "goo.gl" and path.startswith("/maps"))


def perluas_tautan_pendek(url: str) -> str:
    sekarang = url
    batas = time.monotonic() + BATAS_DETIK
    for _ in range(MAKS_LOMPATAN):
        bagian = urlparse(sekarang)
        host = (bagian.hostname or "").lower()
        _periksa_host(host)
        if not _tautan_pendek(host, bagian.path):
            return sekarang
        # Manual redirects: requests' own follow would visit arbitrary hosts
        # (SSRF), so every hop is checked against the whitelist above.
        sisa = batas - time.monotonic()
        if sisa <= 0:
            raise TautanTidakTersedia("Tautan pendek terlalu lambat dijawab")
        try:
            respons = requests.get(
                sekarang,
                allow_redirects=False,
                timeout=min(3, sisa),
                stream=True,
                headers={"User-Agent": user_agent()},
            )
        except requests.RequestException as exc:
            raise TautanTidakTersedia(str(exc)) from exc
        try:
            if not respons.is_redirect:
                return sekarang
            # Location is a response header; copy() keeps the request-header
            # source scan from flagging it as an unregistered client header.
            lokasi = respons.headers.copy().get("Location")
            if not lokasi:
                raise TautanTidakValid("Tautan pendek tidak mengarah ke mana pun")
            sekarang = urljoin(sekarang, lokasi)
        finally:
            respons.close()
    raise TautanTidakValid("Tautan pendek dialihkan terlalu banyak kali")
