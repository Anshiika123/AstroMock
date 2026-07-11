"""
location_resolver.py — Geocoding + timezone resolution for the Kundali feature.

Turns a free-text birthplace into the (latitude, longitude, timezone_str)
inputs that kundali_calculator.generate_kundali() expects.

Geocoder: Nominatim (OpenStreetMap) — free, no API key. Rate limit is
1 request/second per their usage policy, which is fine for a low-traffic
app; swap in Google Geocoding API later if volume demands it.

Dependencies: geopy, timezonefinder
"""

from functools import lru_cache

from geopy.exc import GeocoderServiceError, GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

# Nominatim requires a descriptive, unique user agent (not a generic browser UA).
USER_AGENT = "astro-mock-kundali-app"
GEOCODE_TIMEOUT_SECONDS = 10

# KNOWN LIMITATION — historical Indian timezones:
# The IANA tz database (via the timezone string we return) handles most
# historical offsets, but Indian birth times before 1955 are messy in ways
# tzdata does not fully capture: before 1947 many regions used local
# provincial times (Bombay Time UTC+4:51, Calcutta Time UTC+5:53:20, etc.)
# alongside IST, and adoption of IST (UTC+5:30) between 1947-1955 was
# gradual and region-dependent. tzdata's Asia/Kolkata zone is a single
# simplified history and may not match what a local clock actually read.
# For now we return the standard IANA zone and let the caller decide;
# a future version could warn the user or offer a manual offset override
# for pre-1955 Indian births. Do NOT try to solve this here yet.
HISTORICAL_TZ_CUTOFF_YEAR = 1955

# Module-level singletons: TimezoneFinder loads a large polygon dataset at
# init (~50MB), so build it once, not per request.
_geocoder = Nominatim(user_agent=USER_AGENT)
_tz_finder = TimezoneFinder()


@lru_cache(maxsize=512)
def geocode_place(place_name: str) -> dict | None:
    """Geocode a free-text place name to lat/lon via Nominatim.

    Returns {"latitude", "longitude", "resolved_address"} or None if the
    place could not be found. Raises geopy exceptions on network/service
    failure (handled by resolve_birth_location). Cached because users
    frequently re-submit the same birthplaces.
    """
    location = _geocoder.geocode(place_name, timeout=GEOCODE_TIMEOUT_SECONDS)
    if location is None:
        return None
    return {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "resolved_address": location.address,
    }


def timezone_for_coords(latitude: float, longitude: float) -> str | None:
    """IANA timezone string for coordinates, or None if not determinable.

    timezone_at() covers land; timezone_at_land() fallback handles points
    just offshore (e.g. coastal cities whose coords land in the water).
    """
    tz = _tz_finder.timezone_at(lng=longitude, lat=latitude)
    if tz is None:
        tz = _tz_finder.timezone_at_land(lng=longitude, lat=latitude)
    return tz


def _error(code: str, message: str) -> dict:
    """Uniform error shape so callers can branch on error['code']."""
    return {"success": False, "error": {"code": code, "message": message}}


def resolve_birth_location(place_name: str, date_of_birth: str) -> dict:
    """Resolve a free-text birthplace to lat/lon + IANA timezone.

    Args:
        place_name: free text, e.g. "Ghaziabad, India"
        date_of_birth: "YYYY-MM-DD" — used only to attach a warning for
            births predating reliable timezone history (see KNOWN
            LIMITATION above); no historical correction is applied.

    Returns:
        On success:
            {"success": True, "latitude": float, "longitude": float,
             "timezone_str": str, "resolved_address": str,
             "warnings": [str, ...]}
        On failure:
            {"success": False, "error": {"code": str, "message": str}}
    """
    if not place_name or not place_name.strip():
        return _error("EMPTY_PLACE", "Place of birth cannot be empty.")

    try:
        geo = geocode_place(place_name.strip())
    except (GeocoderTimedOut, GeocoderUnavailable) as exc:
        return _error(
            "GEOCODER_UNAVAILABLE",
            f"Geocoding service unreachable or timed out: {exc}",
        )
    except GeocoderServiceError as exc:
        return _error("GEOCODER_ERROR", f"Geocoding service error: {exc}")

    if geo is None:
        return _error(
            "PLACE_NOT_FOUND",
            f"Could not find a location matching '{place_name}'. "
            "Try adding more detail, e.g. 'City, State, Country'.",
        )

    timezone_str = timezone_for_coords(geo["latitude"], geo["longitude"])
    if timezone_str is None:
        return _error(
            "TIMEZONE_NOT_FOUND",
            f"Could not determine a timezone for coordinates "
            f"({geo['latitude']:.4f}, {geo['longitude']:.4f}).",
        )

    warnings = []
    try:
        birth_year = int(date_of_birth[:4])
    except (TypeError, ValueError):
        birth_year = None
        warnings.append(
            f"Could not parse birth year from '{date_of_birth}'; "
            "historical timezone check skipped."
        )
    if birth_year is not None and birth_year < HISTORICAL_TZ_CUTOFF_YEAR:
        warnings.append(
            f"Birth year {birth_year} predates {HISTORICAL_TZ_CUTOFF_YEAR}; "
            "local clock time may not match modern timezone rules "
            "(notably in India: provincial times before 1947, gradual IST "
            "adoption 1947-1955). Chart accuracy may be affected."
        )

    return {
        "success": True,
        "latitude": geo["latitude"],
        "longitude": geo["longitude"],
        "timezone_str": timezone_str,
        "resolved_address": geo["resolved_address"],
        "warnings": warnings,
    }


if __name__ == "__main__":
    # Live smoke test (requires network access to nominatim.openstreetmap.org)
    for place in ["Ghaziabad, India", "xyzzy-not-a-real-place-12345", ""]:
        result = resolve_birth_location(place, "1990-01-01")
        print(f"{place!r:>40} -> {result}")
