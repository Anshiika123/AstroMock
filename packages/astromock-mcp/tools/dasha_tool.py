"""Vimshottari Dasha — thin adapter over astromock-core.

Core's dasha_calculator works from the Moon's sidereal longitude; this
adapter keeps the MCP tool's birth-data entry point (self-contained call
for MCP clients) and re-exports the shared tables.
"""

import swisseph as swe

from dasha_calculator import (  # noqa: F401  (re-exports)
    DASHA_ORDER,
    DASHA_YEARS,
    DAYS_PER_YEAR,
    TOTAL_CYCLE_YEARS,
    antardasha_breakdown,
    calculate_vimshottari_dasha,
    dasha_balance_years,
    mahadasha_sequence,
    nakshatra_position,
    ruling_planet,
    years_to_ymd,
)
from kundali_calculator import (calculate_planet_positions, julian_day,
                                local_to_utc)


def _moon_longitude(date_of_birth: str, time_of_birth: str,
                    timezone_str: str) -> float:
    """Sidereal (Lahiri) Moon longitude at birth."""
    jd = julian_day(local_to_utc(date_of_birth, time_of_birth, timezone_str))
    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    try:
        return calculate_planet_positions(jd)["Moon"]["longitude"]
    finally:
        swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY, 0, 0)


def calculate_dasha(
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone_str: str,
    unknown_time: bool = False,
    as_of: str | None = None,
) -> dict:
    """Vimshottari Dasha timeline from birth data.

    latitude/longitude are accepted for schema parity but unused (dasha
    depends only on the Moon). unknown_time adds a caution note: the Moon
    moves ~13°/day, so an uncertain birth time can shift the nakshatra and
    the entire dasha sequence.
    """
    moon_lon = _moon_longitude(date_of_birth, time_of_birth, timezone_str)
    result = calculate_vimshottari_dasha(moon_lon, date_of_birth, as_of=as_of)
    if unknown_time:
        result["note"] = (
            "Birth time was marked uncertain: the Moon moves ~13° per day, "
            "so the nakshatra — and therefore the whole dasha timeline — "
            "may shift if the actual birth time differs substantially.")
    return result
