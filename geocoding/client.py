"""
geocoding/client.py

Free geocoding via OpenStreetMap Nominatim's public search API, plus a plain
haversine distance helper used by the commute hard-filter (plan section 3a).

Nominatim's usage policy (https://operations.osmfoundation.org/policies/nominatim/)
caps anonymous usage at roughly 1 request/second and requires a descriptive
`User-Agent` identifying the application. This module does exactly one
blocking HTTP call per `geocode()` call and does NOT rate-limit or cache
internally -- callers that geocode many addresses in a loop (e.g. discovery's
persist step) are responsible for spacing calls out and for caching the
result on the record (e.g. `JobPosting.location_lat/location_lng`) rather
than re-geocoding the same location on every run. See
`scraper/discovery.py:enrich_job_location` for where that caching/pacing is
expected to happen in this system.
"""
import math
from typing import Optional

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim asks for a descriptive User-Agent identifying the application
# (and ideally a contact) -- not a browser UA string.
_USER_AGENT = (
    "SmartJobSearchEngine/0.1 (personal job-hunting tool; "
    "contact: motus.haptic.suit@gmail.com)"
)
_TIMEOUT = 10.0


def geocode(address: str) -> Optional[tuple[float, float]]:
    """
    Resolve a free-text address/location string (e.g. "San Francisco, CA" or
    "Berlin, Germany") to (lat, lng) via OSM Nominatim's public API (no auth
    required).

    Returns None on empty input, no match, or any network/parsing failure --
    callers should treat None as "couldn't geocode this one" and move on
    rather than raising, since this hits a third-party free service that can
    legitimately fail or rate-limit.
    """
    if not address or not address.strip():
        return None

    params = {"q": address.strip(), "format": "json", "limit": 1}
    headers = {"User-Agent": _USER_AGENT}

    try:
        resp = httpx.get(NOMINATIM_URL, params=params, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        results = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    if not results:
        return None

    try:
        lat = float(results[0]["lat"])
        lng = float(results[0]["lon"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None

    return (lat, lng)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Great-circle distance between two lat/lng points, in kilometers.
    Pure math -- no API call, safe to call as often as needed.
    """
    earth_radius_km = 6371.0088  # mean Earth radius

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius_km * c
