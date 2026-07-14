"""
ashtakavarga_calculator.py — Bhinnashtakavarga / Sarvashtakavarga + signals.

Computes classical Ashtakavarga bindus (Parashara/B.V. Raman scheme) from a
kundali, then — because the UI never exposes raw score sheets — distills
them into the compact interpreted-signals object that astro_advisor.py
feeds to the LLM:

    {"overall_transit_support": "moderate", "career_house_support": "high",
     ..., "notes": [...]}

Bindu conventions:
- Each of 7 planets has a Bhinnashtakavarga (BAV): 8 contributors (the 7
  planets + Lagna) each donate one bindu into fixed house offsets counted
  from the contributor's own natal sign.
- Fixed per-planet totals (any chart): Sun 48, Moon 49, Mars 39,
  Mercury 54, Jupiter 56, Venus 52, Saturn 39 — SAV total 337.
- Transit reading: a planet transiting a sign where its own BAV holds
  >=5 bindus gives strong results, 4 average, <=3 weak.
- SAV per sign: >=30 strong house, 25-29 average, <=24 weak
  (mean is 337/12 ~ 28).

Unknown-time charts: the Lagna contributor falls back to the Moon sign
(Chandra lagna), the standard substitute when birth time is unknown.
"""

from kundali_calculator import SIGNS

BAV_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

# BENEFIC_PLACES[planet][contributor] = house offsets (1 = contributor's own
# sign) where the contributor donates a bindu into `planet`'s BAV.
BENEFIC_PLACES = {
    "Sun": {
        "Sun": [1, 2, 4, 7, 8, 9, 10, 11],
        "Moon": [3, 6, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [5, 6, 9, 11],
        "Venus": [6, 7, 12],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Lagna": [3, 4, 6, 10, 11, 12],
    },
    "Moon": {
        "Sun": [3, 6, 7, 8, 10, 11],
        "Moon": [1, 3, 6, 7, 10, 11],
        "Mars": [2, 3, 5, 6, 9, 10, 11],
        "Mercury": [1, 3, 4, 5, 7, 8, 10, 11],
        "Jupiter": [1, 4, 7, 8, 10, 11, 12],
        "Venus": [3, 4, 5, 7, 9, 10, 11],
        "Saturn": [3, 5, 6, 11],
        "Lagna": [3, 6, 10, 11],
    },
    "Mars": {
        "Sun": [3, 5, 6, 10, 11],
        "Moon": [3, 6, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [3, 5, 6, 11],
        "Jupiter": [6, 10, 11, 12],
        "Venus": [6, 8, 11, 12],
        "Saturn": [1, 4, 7, 8, 9, 10, 11],
        "Lagna": [1, 3, 6, 10, 11],
    },
    "Mercury": {
        "Sun": [5, 6, 9, 11, 12],
        "Moon": [2, 4, 6, 8, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [1, 3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [6, 8, 11, 12],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 11],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Lagna": [1, 2, 4, 6, 8, 10, 11],
    },
    "Jupiter": {
        "Sun": [1, 2, 3, 4, 7, 8, 9, 10, 11],
        "Moon": [2, 5, 7, 9, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [1, 2, 4, 5, 6, 9, 10, 11],
        "Jupiter": [1, 2, 3, 4, 7, 8, 10, 11],
        "Venus": [2, 5, 6, 9, 10, 11],
        "Saturn": [3, 5, 6, 12],
        "Lagna": [1, 2, 4, 5, 6, 7, 9, 10, 11],
    },
    "Venus": {
        "Sun": [8, 11, 12],
        "Moon": [1, 2, 3, 4, 5, 8, 9, 11, 12],
        "Mars": [3, 5, 6, 9, 11, 12],
        "Mercury": [3, 5, 6, 9, 11],
        "Jupiter": [5, 8, 9, 10, 11],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 10, 11],
        "Saturn": [3, 4, 5, 8, 9, 10, 11],
        "Lagna": [1, 2, 3, 4, 5, 8, 9, 11],
    },
    "Saturn": {
        "Sun": [1, 2, 4, 7, 8, 10, 11],
        "Moon": [3, 6, 11],
        "Mars": [3, 5, 6, 10, 11, 12],
        "Mercury": [6, 8, 9, 10, 11, 12],
        "Jupiter": [5, 6, 11, 12],
        "Venus": [6, 11, 12],
        "Saturn": [3, 5, 6, 11],
        "Lagna": [1, 3, 4, 6, 10, 11],
    },
}

EXPECTED_BAV_TOTALS = {"Sun": 48, "Moon": 49, "Mars": 39, "Mercury": 54,
                       "Jupiter": 56, "Venus": 52, "Saturn": 39}
SAV_TOTAL = 337


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _reference_signs(kundali_data: dict) -> dict:
    """Natal sign of each contributor; Lagna falls back to the Moon sign."""
    refs = {p: kundali_data["planets"][p]["sign"] for p in BAV_PLANETS}
    ascendant = kundali_data.get("ascendant")
    refs["Lagna"] = (ascendant["sign"] if ascendant
                     else kundali_data["planets"]["Moon"]["sign"])
    return refs


def calculate_bhinnashtakavarga(kundali_data: dict) -> dict:
    """BAV bindus per planet: {planet: [12 counts, Aries..Pisces order]}."""
    refs = _reference_signs(kundali_data)
    bav = {}
    for planet, contributions in BENEFIC_PLACES.items():
        bindus = [0] * 12
        for contributor, houses in contributions.items():
            base = SIGNS.index(refs[contributor])
            for h in houses:
                bindus[(base + h - 1) % 12] += 1
        bav[planet] = bindus
    return bav


def calculate_sarvashtakavarga(bav: dict) -> list[int]:
    """SAV: per-sign totals across all seven BAVs (Aries..Pisces order)."""
    return [sum(bav[p][i] for p in BAV_PLANETS) for i in range(12)]


def bindus_in_sign(bav: dict, planet: str, sign: str) -> int:
    return bav[planet][SIGNS.index(sign)]


# ---------------------------------------------------------------------------
# Interpretation layer (what the LLM sees — never the raw tables)
# ---------------------------------------------------------------------------

def _sav_level(sav_value: int) -> str:
    return "high" if sav_value >= 30 else "medium" if sav_value >= 25 else "low"


def _transit_level(bindu_count: int) -> str:
    return ("supportive" if bindu_count >= 5
            else "mixed" if bindu_count == 4 else "challenging")


def _house_sign(base_sign: str, house_number: int) -> str:
    return SIGNS[(SIGNS.index(base_sign) + house_number - 1) % 12]


def interpret_ashtakavarga_signals(kundali_data: dict,
                                   current_transits: dict) -> dict:
    """Compact plain-language Ashtakavarga signals for the advisor prompt.

    Args:
        kundali_data: output of generate_kundali().
        current_transits: output of get_current_transits()
            ({planet: transit_sign}).

    Returns the interpreted-signals object (no raw bindu tables):
        overall_transit_support, career/relationship/finance house support,
        saturn/jupiter transit support, timing_quality, pressure_level,
        notes[].
    """
    bav = calculate_bhinnashtakavarga(kundali_data)
    sav = calculate_sarvashtakavarga(bav)
    ascendant = kundali_data.get("ascendant")
    base_sign = (ascendant["sign"] if ascendant
                 else kundali_data["planets"]["Moon"]["sign"])

    def sav_of_house(house: int) -> int:
        return sav[SIGNS.index(_house_sign(base_sign, house))]

    career_sav = sav_of_house(10)
    relationship_sav = sav_of_house(7)
    finance_sav = round((sav_of_house(2) + sav_of_house(11)) / 2)

    transit_bindus = {p: bindus_in_sign(bav, p, current_transits[p])
                      for p in BAV_PLANETS}
    mean_transit = sum(transit_bindus.values()) / len(transit_bindus)
    overall = ("supportive" if mean_transit >= 4.5
               else "moderate" if mean_transit >= 3.8 else "low")

    saturn_level = _transit_level(transit_bindus["Saturn"])
    jupiter_level = _transit_level(transit_bindus["Jupiter"])
    slow_avg = (transit_bindus["Saturn"] + transit_bindus["Jupiter"]) / 2
    timing = ("favorable" if slow_avg >= 5
              else "mixed" if slow_avg >= 4 else "slow")

    moon_sign = kundali_data["planets"]["Moon"]["sign"]
    saturn_from_moon = (SIGNS.index(current_transits["Saturn"])
                        - SIGNS.index(moon_sign)) % 12 + 1
    sade_sati = saturn_from_moon in {12, 1, 2}
    pressure = ("high" if sade_sati or transit_bindus["Saturn"] <= 2
                else "medium" if transit_bindus["Saturn"] <= 4 else "low")

    notes = []
    if career_sav >= relationship_sav + 3:
        notes.append("Career-related zones are better supported than "
                     "relationship zones right now")
    elif relationship_sav >= career_sav + 3:
        notes.append("Relationship zones are better supported than "
                     "career zones right now")
    else:
        notes.append("Career and relationship zones carry similar levels "
                     "of support right now")
    if timing == "favorable":
        notes.append("Slow-moving transits are well placed — timing looks "
                     "more favorable than average")
    elif timing == "mixed":
        notes.append("Results improve with patience rather than speed")
    else:
        notes.append("Slow-moving transits are under-supported — expect "
                     "slower outcomes and plan extra buffer time")
    if sade_sati:
        notes.append("Saturn is close to the natal Moon (Sade Sati zone), "
                     "which adds background pressure")
    notes.append("Current period is not blocked, but uneven"
                 if overall == "moderate" else
                 "Current period carries above-average ease" if overall ==
                 "supportive" else
                 "Current period needs steady effort for average results")

    return {
        "overall_transit_support": overall,
        "career_house_support": _sav_level(career_sav),
        "relationship_house_support": _sav_level(relationship_sav),
        "finance_house_support": _sav_level(finance_sav),
        "saturn_transit_support": saturn_level,
        "jupiter_transit_support": jupiter_level,
        "timing_quality": timing,
        "pressure_level": pressure,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Structural invariants of the classical tables themselves
    for planet, total in EXPECTED_BAV_TOTALS.items():
        table_total = sum(len(v) for v in BENEFIC_PLACES[planet].values())
        assert table_total == total, (planet, table_total)
    assert sum(EXPECTED_BAV_TOTALS.values()) == SAV_TOTAL

    # Synthetic chart: every contributor in Aries -> bindus of sign X equal
    # the number of contributors listing house (index of X + 1).
    synthetic = {
        "ascendant": {"sign": "Aries"},
        "planets": {p: {"sign": "Aries"} for p in BAV_PLANETS},
    }
    bav = calculate_bhinnashtakavarga(synthetic)
    # Sun BAV, house 1 (Aries): only Sun, Mars, Saturn list house 1 -> 3
    assert bav["Sun"][SIGNS.index("Aries")] == 3, bav["Sun"]
    # Sun BAV, house 11 (Aquarius): everyone except Venus lists 11 -> 7
    assert bav["Sun"][SIGNS.index("Aquarius")] == 7, bav["Sun"]
    # Moon BAV, house 1: Moon, Mercury, Jupiter list house 1 -> 3
    assert bav["Moon"][SIGNS.index("Aries")] == 3, bav["Moon"]
    # per-planet totals are chart-independent
    for planet, total in EXPECTED_BAV_TOTALS.items():
        assert sum(bav[planet]) == total, (planet, sum(bav[planet]))
    assert sum(calculate_sarvashtakavarga(bav)) == SAV_TOTAL

    # Real chart: totals must hold for an arbitrary chart too
    from kundali_calculator import generate_kundali
    from transit_calculator import get_current_transits

    chart = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090,
                             "Asia/Kolkata")
    bav_1990 = calculate_bhinnashtakavarga(chart)
    for planet, total in EXPECTED_BAV_TOTALS.items():
        assert sum(bav_1990[planet]) == total, (planet, sum(bav_1990[planet]))
    sav_1990 = calculate_sarvashtakavarga(bav_1990)
    assert sum(sav_1990) == SAV_TOTAL
    assert all(0 <= b <= 8 for row in bav_1990.values() for b in row)

    # Signals object: right keys, labels from the allowed vocabulary
    signals = interpret_ashtakavarga_signals(chart, get_current_transits())
    assert signals["overall_transit_support"] in {"supportive", "moderate", "low"}
    for key in ("career_house_support", "relationship_house_support",
                "finance_house_support"):
        assert signals[key] in {"high", "medium", "low"}, (key, signals[key])
    for key in ("saturn_transit_support", "jupiter_transit_support"):
        assert signals[key] in {"supportive", "mixed", "challenging"}
    assert signals["timing_quality"] in {"favorable", "mixed", "slow"}
    assert signals["pressure_level"] in {"high", "medium", "low"}
    assert signals["notes"]

    # Unknown-time chart degrades to Chandra lagna instead of crashing
    nt = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090,
                          "Asia/Kolkata", unknown_time=True)
    nt_signals = interpret_ashtakavarga_signals(nt, get_current_transits())
    assert nt_signals["notes"]

    print("All Ashtakavarga assertions passed.")
    import json
    print(json.dumps(signals, indent=1))
