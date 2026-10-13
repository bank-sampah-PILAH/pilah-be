"""Geodesy helpers for the bank-sampah directory (PIL-314).

Stdlib-only on purpose: the directory computes distance per candidate row in
Python anyway, so a PostGIS dependency would be pure weight here.
"""

import math

R_BUMI_KM = 6371.0088  # IUGG mean Earth radius.


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometers between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * R_BUMI_KM * math.asin(math.sqrt(a))