"""
kundali_chart.py — North Indian style Kundali chart rendered as SVG.

Layout: fixed diamond-in-square. Outer square + both corner-to-corner
diagonals + a diamond joining the four side midpoints = exactly 12 regions.
House positions NEVER move: House 1 (Lagna) is always the top-center
diamond, houses proceed counter-clockwise. Only the planets (and the sign
labels, via Whole Sign) change from chart to chart.

Depends on kundali_calculator only for the SIGNS list (single source of truth).
"""

from kundali_calculator import SIGNS

SIZE = 400  # SVG is SIZE x SIZE

PLANET_ABBREVIATIONS = {
    "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me",
    "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa", "Rahu": "Ra", "Ketu": "Ke",
}

RETROGRADE_MARK = "℞"  # ℞

# Fixed geometry per house (400x400 canvas).
# planets: anchor point around which planet rows are centered
# sign / number: label positions chosen to sit inside each region's corner
# per_row: how many planet labels fit per row in that region
HOUSE_GEOMETRY = {
    1:  {"planets": (200, 95),  "sign": (200, 172), "number": (200, 24),  "per_row": 3},
    2:  {"planets": (100, 48),  "sign": (100, 78),  "number": (100, 16),  "per_row": 3},
    3:  {"planets": (42, 100),  "sign": (30, 142),  "number": (14, 103),  "per_row": 1},
    4:  {"planets": (100, 197), "sign": (100, 268), "number": (24, 203),  "per_row": 3},
    5:  {"planets": (42, 300),  "sign": (30, 258),  "number": (14, 303),  "per_row": 1},
    6:  {"planets": (100, 358), "sign": (100, 324), "number": (100, 392), "per_row": 3},
    7:  {"planets": (200, 297), "sign": (200, 224), "number": (200, 386), "per_row": 3},
    8:  {"planets": (300, 358), "sign": (300, 324), "number": (300, 392), "per_row": 3},
    9:  {"planets": (358, 300), "sign": (370, 258), "number": (386, 303), "per_row": 1},
    10: {"planets": (300, 197), "sign": (300, 268), "number": (376, 203), "per_row": 3},
    11: {"planets": (358, 100), "sign": (370, 142), "number": (386, 103), "per_row": 1},
    12: {"planets": (300, 48),  "sign": (300, 78),  "number": (300, 16),  "per_row": 3},
}

ROW_HEIGHT = 14  # px between planet rows


# ---------------------------------------------------------------------------
# Helpers (independently testable)
# ---------------------------------------------------------------------------

def sign_for_house(house: int, ascendant_sign: str) -> str:
    """Whole Sign: house N carries the Nth sign counting from the Lagna sign."""
    lagna_index = SIGNS.index(ascendant_sign)
    return SIGNS[(lagna_index + house - 1) % 12]


def planet_label(name: str, retrograde: bool) -> str:
    """Short label for a planet, with ℞ appended when retrograde."""
    label = PLANET_ABBREVIATIONS[name]
    return f"{label} {RETROGRADE_MARK}" if retrograde else label


def planets_by_house(kundali_data: dict) -> dict:
    """Group planet labels into {house_number: [label, ...]}."""
    grouped = {h: [] for h in range(1, 13)}
    for name, p in kundali_data["planets"].items():
        grouped[p["house"]].append(planet_label(name, p["retrograde"]))
    return grouped


def _chunk(items: list, size: int) -> list:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _text(x, y, content, size, fill="#000", weight="normal") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
        f'font-weight="{weight}" text-anchor="middle" '
        f'dominant-baseline="middle" font-family="sans-serif">{content}</text>'
    )


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render_north_indian_chart(kundali_data: dict) -> str:
    """Render a kundali dict (from generate_kundali) as a North Indian SVG.

    Returns the SVG document as a string. Raises ValueError if the chart
    was generated with unknown_time=True (no ascendant → houses undefined,
    and a North Indian chart is meaningless without them).
    """
    if kundali_data.get("ascendant") is None:
        raise ValueError(
            "Cannot render a North Indian chart without an ascendant: "
            "this kundali was generated with unknown_time=True, so house "
            "placements are undefined. Show planet positions as a table instead."
        )

    ascendant_sign = kundali_data["ascendant"]["sign"]
    grouped = planets_by_house(kundali_data)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" '
        f'viewBox="0 0 {SIZE} {SIZE}">',
        f'<rect width="{SIZE}" height="{SIZE}" fill="white"/>',
        # Outer square + diagonals (X) + midpoint diamond = 12 regions
        f'<g stroke="black" stroke-width="1.5" fill="none">'
        f'<rect x="1" y="1" width="{SIZE - 2}" height="{SIZE - 2}"/>'
        f'<line x1="1" y1="1" x2="{SIZE - 1}" y2="{SIZE - 1}"/>'
        f'<line x1="{SIZE - 1}" y1="1" x2="1" y2="{SIZE - 1}"/>'
        f'<path d="M {SIZE // 2} 1 L {SIZE - 1} {SIZE // 2} L {SIZE // 2} {SIZE - 1} L 1 {SIZE // 2} Z"/>'
        f'</g>',
    ]

    for house in range(1, 13):
        geometry = HOUSE_GEOMETRY[house]

        # House number, light gray, region corner
        nx, ny = geometry["number"]
        parts.append(_text(nx, ny, house, 8, fill="#b0b0b0"))

        # Sign label, faint
        sx, sy = geometry["sign"]
        sign = sign_for_house(house, ascendant_sign)
        parts.append(_text(sx, sy, sign, 7, fill="#999"))

        # Ascendant marker in house 1 (sign name already shown via label above)
        if house == 1:
            parts.append(_text(200, 152, "Asc", 9, fill="#444", weight="bold"))

        # Planet labels, centered rows around the planet anchor
        px, py = geometry["planets"]
        rows = _chunk(grouped[house], geometry["per_row"])
        first_y = py - (len(rows) - 1) * ROW_HEIGHT / 2
        for i, row in enumerate(rows):
            parts.append(_text(px, first_y + i * ROW_HEIGHT, " ".join(row), 11))

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Test — uses the independently verified reference chart
# (1990-01-01, 12:00 IST, New Delhi → Pisces lagna; see kundali_calculator.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from kundali_calculator import generate_kundali

    chart = generate_kundali(
        date_of_birth="1990-01-01",
        time_of_birth="12:00",
        latitude=28.6139,
        longitude=77.2090,
        timezone_str="Asia/Kolkata",
    )

    # Helper-level checks (Pisces lagna)
    assert sign_for_house(1, "Pisces") == "Pisces"
    assert sign_for_house(10, "Pisces") == "Sagittarius"
    assert sign_for_house(12, "Pisces") == "Aquarius"
    grouped = planets_by_house(chart)
    assert grouped[10] == ["Su", "Sa"]                      # Sun + Saturn, direct
    assert grouped[12] == ["Mo"]                            # Moon in Aquarius
    assert grouped[11] == ["Me ℞", "Ve ℞", "Ra ℞"]  # all retro
    assert grouped[4] == ["Ju ℞"] and grouped[5] == ["Ke ℞"]

    svg = render_north_indian_chart(chart)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert ">Asc<" in svg and ">Pisces<" in svg and ">Sagittarius<" in svg
    assert "Ju ℞" in svg and ">Su Sa<" in svg

    # unknown_time charts must be rejected with a clear error
    no_time = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090,
                               "Asia/Kolkata", unknown_time=True)
    try:
        render_north_indian_chart(no_time)
        raise AssertionError("expected ValueError for unknown_time chart")
    except ValueError:
        pass

    with open("north_chart_test.svg", "w", encoding="utf-8") as f:
        f.write(svg)
    print("All chart assertions passed; wrote north_chart_test.svg")
