"""
house_analyzer.py — Extract per-house information from a kundali.

For a given house number: its sign (Whole Sign from the ascendant), the
planets occupying it, the sign's traditional lord, and where that lord
itself sits — because an empty house's story is told by its lord's
placement.
"""

from kundali_calculator import SIGNS

# Traditional sign lords (Rahu/Ketu own no signs in the classical scheme).
SIGN_LORDS = {
    "Aries": "Mars",
    "Taurus": "Venus",
    "Gemini": "Mercury",
    "Cancer": "Moon",
    "Leo": "Sun",
    "Virgo": "Mercury",
    "Libra": "Venus",
    "Scorpio": "Mars",
    "Sagittarius": "Jupiter",
    "Capricorn": "Saturn",
    "Aquarius": "Saturn",
    "Pisces": "Jupiter",
}


def sign_of_house(house_number: int, ascendant_sign: str) -> str:
    """Whole Sign: house N carries the Nth sign counting from the lagna."""
    return SIGNS[(SIGNS.index(ascendant_sign) + house_number - 1) % 12]


def planets_in_house(kundali_data: dict, house_number: int) -> list[str]:
    """Names of planets occupying a house (empty list if none)."""
    return [name for name, p in kundali_data["planets"].items()
            if p["house"] == house_number]


def analyze_house(kundali_data: dict, house_number: int) -> dict:
    """Sign, occupants, lord, and lord's placement for one house.

    Args:
        kundali_data: output of generate_kundali() (known birth time).
        house_number: 1-12.

    Raises:
        ValueError: for an invalid house number, or if the chart has no
            ascendant (unknown_time=True) — houses are undefined then.
    """
    if not 1 <= house_number <= 12:
        raise ValueError(f"house_number must be 1-12, got {house_number}")
    ascendant = kundali_data.get("ascendant")
    if ascendant is None:
        raise ValueError(
            "Cannot analyze houses: chart has no ascendant "
            "(generated with unknown_time=True)."
        )

    house_sign = sign_of_house(house_number, ascendant["sign"])
    lord = SIGN_LORDS[house_sign]
    return {
        "house_sign": house_sign,
        "planets_in_house": planets_in_house(kundali_data, house_number),
        "house_lord": lord,
        "lord_placed_in_house": kundali_data["planets"][lord]["house"],
    }


if __name__ == "__main__":
    from kundali_calculator import generate_kundali

    # Verified reference chart: 1990-01-01 12:00 IST New Delhi -> Pisces lagna
    chart = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090, "Asia/Kolkata")

    # House 10 (as requested): Sagittarius from Pisces lagna
    h10 = analyze_house(chart, 10)
    print("House 10:", h10)
    assert h10 == {
        "house_sign": "Sagittarius",
        "planets_in_house": ["Sun", "Saturn"],
        "house_lord": "Jupiter",
        "lord_placed_in_house": 4,  # Jupiter sits in Gemini = 4th house
    }, h10

    # Empty house: house 2 (Aries) has no occupants; lord Mars sits in 9
    h2 = analyze_house(chart, 2)
    print("House 2 :", h2)
    assert h2 == {
        "house_sign": "Aries",
        "planets_in_house": [],
        "house_lord": "Mars",
        "lord_placed_in_house": 9,
    }, h2

    # House 11 (Capricorn): Mercury, Venus, Rahu; lord Saturn in 10
    h11 = analyze_house(chart, 11)
    print("House 11:", h11)
    assert h11["planets_in_house"] == ["Mercury", "Venus", "Rahu"]
    assert h11["house_lord"] == "Saturn" and h11["lord_placed_in_house"] == 10

    # Lagna itself: house 1 = Pisces, empty, lord Jupiter in 4
    h1 = analyze_house(chart, 1)
    assert h1 == {"house_sign": "Pisces", "planets_in_house": [],
                  "house_lord": "Jupiter", "lord_placed_in_house": 4}

    # every house's lord must itself sit in a valid house
    for h in range(1, 13):
        assert 1 <= analyze_house(chart, h)["lord_placed_in_house"] <= 12

    # error paths
    for bad in (0, 13):
        try:
            analyze_house(chart, bad)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    no_time = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090,
                               "Asia/Kolkata", unknown_time=True)
    try:
        analyze_house(no_time, 10)
        raise AssertionError("expected ValueError for unknown_time")
    except ValueError:
        pass

    print("All house-analyzer assertions passed.")
