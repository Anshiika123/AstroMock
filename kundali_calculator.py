"""
kundali_calculator.py — Vedic birth chart (Kundali) calculation logic.

Sidereal zodiac, Lahiri Ayanamsha, Whole Sign houses, mean node for Rahu/Ketu.
Geocoding and timezone lookup are handled elsewhere; this module expects
lat/lon and an IANA timezone string as inputs.

Dependencies: pyswisseph, pytz
"""

from datetime import datetime

import pytz
import swisseph as swe

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
    "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha",
    "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana",
    "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada",
    "Revati",
]

NAKSHATRA_SPAN = 360.0 / 27.0   # 13°20'
PADA_SPAN = NAKSHATRA_SPAN / 4.0  # 3°20'

# Planet name -> Swiss Ephemeris body ID. Rahu uses the mean lunar node;
# Ketu is derived as Rahu + 180°.
PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    "Rahu": swe.MEAN_NODE,
}


# ---------------------------------------------------------------------------
# Helpers (independently testable)
# ---------------------------------------------------------------------------

def local_to_utc(date_of_birth: str, time_of_birth: str, timezone_str: str) -> datetime:
    """Convert local birth date/time + IANA timezone to an aware UTC datetime.

    Uses pytz.localize() so historical offsets (e.g. pre-1955 India) are
    resolved from the tz database rather than assuming the current offset.
    """
    naive = datetime.strptime(f"{date_of_birth} {time_of_birth}", "%Y-%m-%d %H:%M")
    tz = pytz.timezone(timezone_str)
    local_dt = tz.localize(naive)
    return local_dt.astimezone(pytz.utc)


def julian_day(utc_dt: datetime) -> float:
    """Julian Day (UT) for an aware UTC datetime."""
    hour = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0
    return swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, hour)


def get_sign(longitude: float) -> str:
    """Zodiac sign name for a sidereal ecliptic longitude (0–360°)."""
    return SIGNS[int(longitude % 360.0 // 30)]


def degree_in_sign(longitude: float) -> float:
    """Degree within the sign (0–30°)."""
    return longitude % 30.0


def get_nakshatra(longitude: float) -> dict:
    """Nakshatra name and pada (1–4) for a sidereal longitude."""
    lon = longitude % 360.0
    index = int(lon // NAKSHATRA_SPAN)
    pada = int((lon % NAKSHATRA_SPAN) // PADA_SPAN) + 1
    return {"name": NAKSHATRAS[index], "pada": pada}


def get_house(planet_longitude: float, ascendant_longitude: float) -> int:
    """Whole Sign house (1–12): counted by sign from the Lagna sign."""
    planet_sign = int(planet_longitude % 360.0 // 30)
    lagna_sign = int(ascendant_longitude % 360.0 // 30)
    return (planet_sign - lagna_sign) % 12 + 1


def format_position(
    longitude: float, retrograde: bool, ascendant_longitude: float | None
) -> dict:
    """Full descriptor dict for a body at a given sidereal longitude.

    If ascendant_longitude is None (unknown birth time), the house key is
    omitted — houses are meaningless without a reliable ascendant.
    """
    position = {
        "longitude": round(longitude % 360.0, 4),
        "sign": get_sign(longitude),
        "degree_in_sign": round(degree_in_sign(longitude), 4),
        "nakshatra": get_nakshatra(longitude),
        "retrograde": retrograde,
    }
    if ascendant_longitude is not None:
        position["house"] = get_house(longitude, ascendant_longitude)
    return position


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def calculate_planet_positions(jd: float) -> dict:
    """Sidereal longitudes + retrograde flags for all 9 grahas.

    Returns {name: {"longitude": float, "retrograde": bool}}.
    Assumes sidereal mode is already set (see generate_kundali).
    """
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED
    positions = {}
    for name, body in PLANETS.items():
        (lon, _lat, _dist, speed_lon, *_), _retflags = swe.calc_ut(jd, body, flags)
        positions[name] = {
            "longitude": lon % 360.0,
            "retrograde": speed_lon < 0,
        }
    # Ketu: opposite point of Rahu; both nodes are always retrograde.
    positions["Rahu"]["retrograde"] = True
    positions["Ketu"] = {
        "longitude": (positions["Rahu"]["longitude"] + 180.0) % 360.0,
        "retrograde": True,
    }
    return positions


def calculate_ascendant(jd: float, latitude: float, longitude: float) -> float:
    """Sidereal ascendant (Lagna) longitude in degrees.

    Houses are computed with 'W' (Whole Sign); we only need the ascendant
    degree — house assignment itself is done by sign in get_house().
    """
    _cusps, ascmc = swe.houses_ex(jd, latitude, longitude, b"W", swe.FLG_SIDEREAL)
    return ascmc[0] % 360.0


UNKNOWN_TIME_NOTE = (
    "Birth time was marked as uncertain, so the ascendant (Lagna) and house "
    "placements are not shown — they change roughly every two hours and "
    "cannot be computed reliably without an accurate birth time. Planet "
    "positions are calculated for the time provided; note the Moon's sign "
    "and nakshatra can also shift within a day."
)


def generate_kundali(
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone_str: str,
    unknown_time: bool = False,
) -> dict:
    """Generate a Vedic birth chart (Kundali).

    Args:
        date_of_birth: "YYYY-MM-DD"
        time_of_birth: "HH:MM" (24-hour, local time at birthplace)
        latitude: birthplace latitude (positive = North)
        longitude: birthplace longitude (positive = East)
        timezone_str: IANA timezone name, e.g. "Asia/Kolkata"
        unknown_time: if True, the birth time is uncertain — skip the
            ascendant and house placements (they depend heavily on exact
            time) and include an explanatory note in the result.

    Returns:
        dict with birth details, ascendant, and per-planet positions
        (sign, degree in sign, nakshatra + pada, house, retrograde flag).
        With unknown_time=True: ascendant is None, houses are omitted,
        and a "note" field explains why.
    """
    utc_dt = local_to_utc(date_of_birth, time_of_birth, timezone_str)
    jd = julian_day(utc_dt)

    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    try:
        asc = None if unknown_time else calculate_ascendant(jd, latitude, longitude)
        raw_positions = calculate_planet_positions(jd)
        ayanamsha = swe.get_ayanamsa_ut(jd)
    finally:
        swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY, 0, 0)  # reset to library default

    planets = {
        name: format_position(pos["longitude"], pos["retrograde"], asc)
        for name, pos in raw_positions.items()
    }

    result = {
        "birth_details": {
            "date_of_birth": date_of_birth,
            "time_of_birth": time_of_birth,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": timezone_str,
            "utc_datetime": utc_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "julian_day": round(jd, 6),
            "ayanamsha": round(ayanamsha, 4),
        },
        "ascendant": None if asc is None else {
            "longitude": round(asc, 4),
            "sign": get_sign(asc),
            "degree_in_sign": round(degree_in_sign(asc), 4),
            "nakshatra": get_nakshatra(asc),
        },
        "planets": planets,
        "house_system": "Whole Sign" if not unknown_time else None,
        "ayanamsha_system": "Lahiri",
        "node_type": "mean",
    }
    if unknown_time:
        result["note"] = UNKNOWN_TIME_NOTE
    return result


# ---------------------------------------------------------------------------
# Reference test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Reference chart: 1990-01-01, 12:00 IST, New Delhi (28.6139 N, 77.2090 E).
    # Expected values (Lahiri, mean node) verified against independent
    # closed-form astronomy (Meeus): sidereal Asc 343.92° (Pisces 13.92°),
    # Sun 256.86° (Sag 16.86°), mean Rahu 294.73° (Cap 24.73°). Mercury,
    # Venus, and Jupiter were all retrograde in early January 1990.
    chart = generate_kundali(
        date_of_birth="1990-01-01",
        time_of_birth="12:00",
        latitude=28.6139,
        longitude=77.2090,
        timezone_str="Asia/Kolkata",
    )

    print(f"Ascendant: {chart['ascendant']['sign']} "
          f"{chart['ascendant']['degree_in_sign']:.2f}°  "
          f"({chart['ascendant']['nakshatra']['name']} "
          f"pada {chart['ascendant']['nakshatra']['pada']})")
    print("-" * 72)
    for name, p in chart["planets"].items():
        retro = " ℞" if p["retrograde"] else ""
        print(f"{name:<8} {p['sign']:<12} {p['degree_in_sign']:6.2f}°  "
              f"house {p['house']:>2}  {p['nakshatra']['name']:<18} "
              f"pada {p['nakshatra']['pada']}{retro}")

    # Assertions against independently verified reference values
    assert abs(chart["ascendant"]["longitude"] - 343.92) < 0.05, chart["ascendant"]
    assert chart["ascendant"]["sign"] == "Pisces"

    expected = {  # sidereal longitude, sign, retrograde
        "Sun":     (256.86, "Sagittarius", False),
        "Moon":    (306.47, "Aquarius",    False),
        "Mars":    (226.12, "Scorpio",     False),
        "Mercury": (272.01, "Capricorn",   True),
        "Jupiter": (71.46,  "Gemini",      True),
        "Venus":   (282.53, "Capricorn",   True),
        "Saturn":  (261.91, "Sagittarius", False),
        "Rahu":    (294.73, "Capricorn",   True),
        "Ketu":    (114.73, "Cancer",      True),
    }
    for name, (lon, sign, retro) in expected.items():
        p = chart["planets"][name]
        assert abs(p["longitude"] - lon) < 0.05, (name, p)
        assert p["sign"] == sign, (name, p)
        assert p["retrograde"] is retro, (name, p)

    # Nakshatra + Whole Sign house spot checks (Pisces lagna)
    assert chart["planets"]["Moon"]["nakshatra"] == {"name": "Dhanishta", "pada": 4}
    assert chart["planets"]["Sun"]["house"] == 10   # Sagittarius from Pisces
    assert chart["planets"]["Jupiter"]["house"] == 4  # Gemini from Pisces
    assert chart["planets"]["Ketu"]["house"] == 5   # Cancer from Pisces
    print("-" * 72)
    print("All reference assertions passed.")
