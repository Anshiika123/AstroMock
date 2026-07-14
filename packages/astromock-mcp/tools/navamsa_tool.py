"""D-9 (Navamsa) chart — thin adapter over astromock-core.

Core's navamsa_calculator supplies the math (navamsa_sign + the
dict-in/dict-out helpers); this module keeps the MCP tool's self-contained
birth-data entry point and its established output shape.
"""

from kundali_calculator import generate_kundali
from navamsa_calculator import (  # noqa: F401  (re-exports)
    DUAL,
    FIXED,
    MOVABLE,
    NAVAMSA_SPAN,
    navamsa_sign,
    navamsa_start_sign_index,
    sign_modality,
)
from navamsa_calculator import calculate_navamsa as navamsa_from_kundali
from navamsa_calculator import calculate_navamsa_houses as navamsa_houses


def calculate_navamsa(
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone_str: str,
    unknown_time: bool = False,
) -> dict:
    """Calculate the Vedic D-9 (Navamsa) chart from birth data.

    Same inputs as calculate_kundali. Returns each planet's navamsa sign
    (and Whole Sign house from the navamsa lagna when birth time is known),
    plus the underlying D-1 longitude and retrograde flag for reference.
    """
    d1 = generate_kundali(
        date_of_birth, time_of_birth, latitude, longitude, timezone_str,
        unknown_time=unknown_time,
    )

    d9 = navamsa_from_kundali(d1)
    ascendant_sign = d9.pop("ascendant_navamsa_sign")
    if ascendant_sign is not None:
        d9 = navamsa_houses(d9 | {"ascendant_navamsa_sign": ascendant_sign})
        d9.pop("ascendant_navamsa_sign")

    planets = {}
    for name, value in d9.items():
        planets[name] = dict(value)
        planets[name]["d1_longitude"] = d1["planets"][name]["longitude"]
        planets[name]["retrograde"] = d1["planets"][name]["retrograde"]

    result = {
        "chart": "D-9 (Navamsa)",
        "birth_details": d1["birth_details"],
        "ascendant_navamsa_sign": ascendant_sign,
        "planets": planets,
        "house_system": "Whole Sign" if ascendant_sign is not None else None,
        "ayanamsha_system": "Lahiri",
        "node_type": "mean",
    }
    if unknown_time:
        result["note"] = d1["note"]
    return result
