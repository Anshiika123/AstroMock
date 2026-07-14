"""D-1 (Rashi / Kundali) chart — thin adapter over astromock-core.

The calculation engine lives in packages/core/kundali_calculator.py (the
single source of truth shared with the web app). This module only maps the
MCP tool name onto it and re-exports the shared constants/helpers other
tool modules historically imported from here.
"""

from kundali_calculator import (  # noqa: F401  (re-exports)
    NAKSHATRA_SPAN,
    NAKSHATRAS,
    PADA_SPAN,
    PLANETS,
    SIGNS,
    UNKNOWN_TIME_NOTE,
    calculate_ascendant,
    calculate_planet_positions,
    degree_in_sign,
    generate_kundali,
    get_house,
    get_nakshatra,
    get_sign,
    julian_day,
    local_to_utc,
)

# MCP tool name; identical signature and output to core's generate_kundali.
calculate_kundali = generate_kundali
