"""
transit_calculator.py — Gochar (transit) positions and Moon-sign impact.

Current sidereal planetary positions (same Lahiri/mean-node conventions as
the D-1 chart in kundali_calculator) compared against the native's Rashi
(Moon sign): which house from the Moon each planet is transiting, plus the
classic Sade Sati condition (Saturn in 12th/1st/2nd from the Moon).

Transit positions are computed for 12:00 UT of the target date — slow
planets (Saturn, Jupiter, Rahu/Ketu) don't move meaningfully within a day;
only the Moon's own transit sign can differ by time of day.
"""

from datetime import datetime, timezone

import swisseph as swe

from kundali_calculator import SIGNS, calculate_planet_positions, get_sign

SADE_SATI_HOUSES = {12, 1, 2}


def get_current_transits(target_date: str = None) -> dict:
    """Sidereal sign of each of the 9 grahas on a date (default: today).

    Args:
        target_date: "YYYY-MM-DD"; if None, uses the current UTC date.

    Returns:
        {planet_name: current_sign} for all 9 planets.
    """
    if target_date:
        moment = datetime.strptime(target_date, "%Y-%m-%d").replace(
            hour=12, tzinfo=timezone.utc)
    else:
        moment = datetime.now(timezone.utc)

    hour = moment.hour + moment.minute / 60.0
    jd = swe.julday(moment.year, moment.month, moment.day, hour)

    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    try:
        positions = calculate_planet_positions(jd)
    finally:
        swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY, 0, 0)  # library default

    return {name: get_sign(p["longitude"]) for name, p in positions.items()}


def house_from_moon(moon_sign: str, transit_sign: str) -> int:
    """Inclusive house count from the Moon sign (Whole Sign style):
    same sign = 1, next sign = 2, ... e.g. Scorpio Moon with Saturn in
    Capricorn -> 3."""
    return (SIGNS.index(transit_sign) - SIGNS.index(moon_sign)) % 12 + 1


def analyze_transit_impact(moon_sign: str, current_transits: dict) -> dict:
    """Per-planet transit houses from the natal Moon + Sade Sati flag.

    Args:
        moon_sign: natal Rashi, e.g. "Scorpio"
            (kundali_data["rashi"]["sign"]).
        current_transits: output of get_current_transits().

    Returns:
        {planet: {"transit_sign": str, "house_from_moon": int}, ...,
         "sade_sati_status": bool}
    """
    if moon_sign not in SIGNS:
        raise ValueError(f"Unknown moon_sign: {moon_sign!r}")

    result = {}
    for planet, sign in current_transits.items():
        result[planet] = {
            "transit_sign": sign,
            "house_from_moon": house_from_moon(moon_sign, sign),
        }
    result["sade_sati_status"] = (
        result["Saturn"]["house_from_moon"] in SADE_SATI_HOUSES)
    return result


if __name__ == "__main__":
    # --- Deterministic test against the independently verified 1990 chart:
    # transits on 1990-01-01 must reproduce that chart's signs (12:00 UT vs
    # 06:30 UT shifts the Moon ~3°, safely inside Aquarius).
    t1990 = get_current_transits("1990-01-01")
    expected_1990 = {
        "Sun": "Sagittarius", "Moon": "Aquarius", "Mars": "Scorpio",
        "Mercury": "Capricorn", "Jupiter": "Gemini", "Venus": "Capricorn",
        "Saturn": "Sagittarius", "Rahu": "Capricorn", "Ketu": "Cancer",
    }
    assert t1990 == expected_1990, t1990

    # house counting: Scorpio Moon, Saturn in Capricorn -> 3rd (spec example)
    assert house_from_moon("Scorpio", "Capricorn") == 3
    assert house_from_moon("Scorpio", "Scorpio") == 1
    assert house_from_moon("Scorpio", "Libra") == 12

    # Scorpio Moon vs 1990 transits: Saturn in Sagittarius = 2nd from Moon
    # -> Sade Sati condition TRUE
    impact_1990 = analyze_transit_impact("Scorpio", t1990)
    assert impact_1990["Saturn"] == {"transit_sign": "Sagittarius",
                                     "house_from_moon": 2}
    assert impact_1990["sade_sati_status"] is True
    # Aquarius Moon, same transits: Saturn 11th from Moon -> no Sade Sati
    assert analyze_transit_impact("Aquarius", t1990)["sade_sati_status"] is False

    # Sade Sati boundary sweep: exactly the 12th/1st/2nd Moon signs from
    # Saturn's transit sign must flag, all others must not
    saturn_sign = "Sagittarius"
    flagged = [m for m in SIGNS
               if analyze_transit_impact(m, t1990)["sade_sati_status"]]
    assert flagged == ["Scorpio", "Sagittarius", "Capricorn"], flagged

    # bad moon sign -> clear error
    try:
        analyze_transit_impact("Scorpion", t1990)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    print("All transit assertions passed (verified against the 1990 chart).")
    print("-" * 64)

    # --- Live output: today's Gochar for a Scorpio Moon (user's rashi)
    today = get_current_transits()
    impact = analyze_transit_impact("Scorpio", today)
    print(f"Transits today ({datetime.now(timezone.utc).date()}) "
          f"from Scorpio Moon:")
    for planet in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus",
                   "Saturn", "Rahu", "Ketu"]:
        p = impact[planet]
        print(f"  {planet:<8} {p['transit_sign']:<12} "
              f"house {p['house_from_moon']:>2} from Moon")
    print(f"Sade Sati active: {impact['sade_sati_status']}")
