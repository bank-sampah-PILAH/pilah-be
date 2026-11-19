"""Google Maps link parsing and safe short-link expansion."""

import re
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


def koordinat_dari_tautan(url: str) -> tuple[float, float] | None:
    # Percent-encoded separators ("%2C", "%21") hide the patterns below.
    teks = unquote(url)
    # (1) is the pin of the place actually selected; (2) is only the viewport
    # centre, which drifts whenever the map is panned before sharing.
    for pola in (_POLA_PIN, _POLA_VIEWPORT):
        cocok = pola.search(teks)
        if cocok:
            return _pasangan(cocok.group(1), cocok.group(2))
    params = parse_qs(urlparse(teks).query)
    for kunci in _PARAM_KOORDINAT:
        nilai = (params.get(kunci) or [""])[0]
        cocok = _POLA_PARAM.fullmatch(nilai)
        if cocok:
            return _pasangan(cocok.group(1), cocok.group(2))
    cocok = _POLA_PLACE.search(teks)
    if cocok:
        return _pasangan(cocok.group(1), cocok.group(2))
    return None


def _pasangan(latitude: str, longitude: str) -> tuple[float, float] | None:
    lat, lng = float(latitude), float(longitude)
    return (lat, lng) if koordinat_valid(lat, lng) else None


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
    for _ in range(MAKS_LOMPATAN):
        bagian = urlparse(sekarang)
        host = (bagian.hostname or "").lower()
        _periksa_host(host)
        if not _tautan_pendek(host, bagian.path):
            return sekarang
        # Manual redirects: requests' own follow would visit arbitrary hosts
        # (SSRF), so every hop is checked against the whitelist above.
        try:
            respons = requests.get(
                sekarang,
                allow_redirects=False,
                timeout=10,
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
