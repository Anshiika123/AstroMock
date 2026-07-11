"""
navamsa_calculator.py — Navamsa (D-9) chart derived from Rasi (D-1) longitudes.

Pure arithmetic on the sidereal longitudes already present in the
generate_kundali() output — no swisseph calls needed.

Navamsa rule (Parashara): each 30° sign is divided into 9 parts of 3°20'.
The 9 divisions of a sign start from:
  - movable (chara) sign  -> the sign itself
  - fixed (sthira) sign   -> the 9th sign from it
  - dual (dvisvabhava)    -> the 5th sign from it
Equivalent element shortcut: fire signs start from Aries, earth from
Capricorn, air from Libra, water from Cancer. Both are mathematically
identical to counting 3°20' navamsas continuously from 0° Aries:
    navamsa_sign_index = floor(longitude / (30/9)) % 12
which is used as an independent cross-check in the tests below.

NOTE: a commonly repeated (but incorrect) variant says movable signs start
from Aries, fixed from Sagittarius, dual from Leo. That gives wrong results
for every sign except Aries itself — do not "fix" this module to match it.
"""

from kundali_calculator import SIGNS

NAVAMSA_SPAN = 30.0 / 9.0  # 3°20'

MOVABLE = {"Aries", "Cancer", "Libra", "Capricorn"}
FIXED = {"Taurus", "Leo", "Scorpio", "Aquarius"}
DUAL = {"Gemini", "Virgo", "Sagittarius", "Pisces"}


# ---------------------------------------------------------------------------
# Helpers (independently testable)
# ---------------------------------------------------------------------------

def sign_modality(sign: str) -> str:
    """Classify a sign as 'movable', 'fixed', or 'dual'."""
    if sign in MOVABLE:
        return "movable"
    if sign in FIXED:
        return "fixed"
    if sign in DUAL:
        return "dual"
    raise ValueError(f"Unknown sign: {sign!r}")

def navamsa_start_sign_index(sign_index: int) -> int:
    """Index of the sign the 9 navamsa divisions start from (Parashara).

    movable -> the sign itself; fixed -> 9th from it (+8);
    dual -> 5th from it (+4).
    """
    modality = sign_modality(SIGNS[sign_index])
    offset = {"movable": 0, "fixed": 8, "dual": 4}[modality]
    return (sign_index + offset) % 12


def navamsa_sign(longitude: float) -> str:
    """Navamsa (D-9) sign name for a sidereal longitude (0–360°)."""
    lon = longitude % 360.0
    sign_index = int(lon // 30)
    degree_in_sign = lon % 30.0
    part = min(int(degree_in_sign // NAVAMSA_SPAN), 8)  # 0..8; clamp fp edge
    return SIGNS[(navamsa_start_sign_index(sign_index) + part) % 12]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def calculate_navamsa(kundali_data: dict) -> dict:
    """Navamsa signs for every planet and the ascendant of a kundali.

    Args:
        kundali_data: output of generate_kundali(); needs each planet's
            "longitude" and (if available) ascendant "longitude".

    Returns:
        {planet_name: {"navamsa_sign": str}, ...,
         "ascendant_navamsa_sign": str | None}
        ascendant_navamsa_sign is None for unknown_time charts.
    """
    result = {
        name: {"navamsa_sign": navamsa_sign(p["longitude"])}
        for name, p in kundali_data["planets"].items()
    }
    ascendant = kundali_data.get("ascendant")
    result["ascendant_navamsa_sign"] = (
        navamsa_sign(ascendant["longitude"]) if ascendant else None
    )
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Independent cross-check: Parashara rule must equal continuous counting
    # from 0° Aries at every one of the 108 navamsa boundaries (+ midpoints).
    for i in range(108):
        for lon in (i * NAVAMSA_SPAN + 0.01, i * NAVAMSA_SPAN + NAVAMSA_SPAN / 2):
            continuous = SIGNS[int(lon // NAVAMSA_SPAN) % 12]
            assert navamsa_sign(lon) == continuous, (lon, navamsa_sign(lon), continuous)
    print("Parashara rule == continuous-count formula at all 108 navamsas ✔")

    # Requested manual-verification cases (D-9 is pure math on longitude,
    # so these work standalone; note these longitudes are NOT from our
    # verified 1990 reference chart):
    #   Asc 145.3755  = Leo 25.3755°   -> part 7, Leo is fixed -> start
    #                   9th from Leo = Aries -> Aries+7 = Scorpio
    #   Moon 235.7022 = Scorpio 25.7022° -> part 7, start 9th from
    #                   Scorpio = Cancer -> Cancer+7 = Aquarius
    print(f"Asc  145.3755 (Leo 25.3755°)      -> {navamsa_sign(145.3755)}")
    print(f"Moon 235.7022 (Scorpio 25.7022°)  -> {navamsa_sign(235.7022)}")
    assert navamsa_sign(145.3755) == "Scorpio"
    assert navamsa_sign(235.7022) == "Aquarius"

    # Full-dict pipeline test with the verified 1990-01-01 Delhi chart
    from kundali_calculator import generate_kundali

    chart = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090, "Asia/Kolkata")
    d9 = calculate_navamsa(chart)
    # Sun 256.856 -> continuous: floor(256.856/3.3333)=77 -> 77%12=5 -> Virgo
    assert d9["Sun"]["navamsa_sign"] == "Virgo", d9["Sun"]
    # Asc 343.9226 -> floor(...)=103 -> 103%12=7 -> Scorpio
    assert d9["ascendant_navamsa_sign"] == "Scorpio", d9
    assert set(d9) == set(chart["planets"]) | {"ascendant_navamsa_sign"}
    print("1990 Delhi chart D-9:",
          {k: v["navamsa_sign"] for k, v in d9.items() if isinstance(v, dict)},
          "| Asc:", d9["ascendant_navamsa_sign"])

    # unknown_time chart -> ascendant_navamsa_sign is None, planets still work
    no_time = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090,
                               "Asia/Kolkata", unknown_time=True)
    d9_nt = calculate_navamsa(no_time)
    assert d9_nt["ascendant_navamsa_sign"] is None
    assert d9_nt["Moon"]["navamsa_sign"] == d9["Moon"]["navamsa_sign"]
    print("unknown_time handling ✔")
    print("All navamsa assertions passed.")
