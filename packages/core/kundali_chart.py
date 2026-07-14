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
# per_row: legacy horizontal-packing hint, now reused as a region-width class
#          (1 = narrow corner triangle, 3 = wider edge trapezoid) to pick a
#          text width/height budget for dynamic font sizing.
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

# Available text width/height (px) per region-width class, used to shrink
# font size when a house holds many planets. Heuristic, not pixel-exact —
# corner (triangular) regions are tighter than edge (trapezoid) regions.
WIDTH_BUDGET = {1: 74, 3: 150}
HEIGHT_BUDGET = {1: 78, 3: 92}

PLANET_FONT_MAX = 11
PLANET_FONT_MIN = 6


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


def format_degree_minute(degree_in_sign: float) -> str:
    """Format a 0-30 degree-in-sign value as "D°MM'" (degrees, minutes; no seconds).

    Example: 22.228 -> whole=22, minutes=round(0.228*60)=14 -> "22°14'".
    """
    whole = int(degree_in_sign)
    minutes = round((degree_in_sign - whole) * 60)
    if minutes == 60:  # rounding edge case, e.g. 22.999 -> 23°00'
        minutes = 0
        whole += 1
    return f"{whole}°{minutes:02d}'"


def planets_by_house(planets_data: dict) -> dict:
    """Group planet entries into {house_number: [entry, ...]}.

    planets_data: {name: {"house": int, "retrograde": bool (optional),
                           "degree_in_sign": float (optional)}, ...}
    Works for D-1 planets (which have degree_in_sign) and D-9
    (navamsa-with-houses, which does not) alike.

    Each entry: {"name": str, "retrograde": bool, "degree_in_sign": float | None}
    """
    grouped = {h: [] for h in range(1, 13)}
    for name, p in planets_data.items():
        grouped[p["house"]].append({
            "name": name,
            "retrograde": p.get("retrograde", False),
            "degree_in_sign": p.get("degree_in_sign"),
        })
    return grouped


def _row_plain_text(entry: dict) -> str:
    """Plain-text (unstyled) rendering of a planet row, for width estimation."""
    abbrev = PLANET_ABBREVIATIONS[entry["name"]]
    retro = RETROGRADE_MARK if entry["retrograde"] else ""
    if entry["degree_in_sign"] is not None:
        return f"{abbrev} {format_degree_minute(entry['degree_in_sign'])}{retro}"
    return f"{abbrev}{' ' + retro if retro else ''}"


def _fit_font_size(entries: list, max_width: int, max_height: int) -> int:
    """Largest font size (down to PLANET_FONT_MIN) that fits all rows.

    Width check uses a rough average character width (~0.55 * font size);
    height check uses row_height = font_size + 3 per stacked row. Heuristic,
    not a pixel-exact layout guarantee.
    """
    texts = [_row_plain_text(e) for e in entries]
    widest_chars = max(len(t) for t in texts)
    size = PLANET_FONT_MAX
    while size > PLANET_FONT_MIN:
        row_height = size + 3
        if widest_chars * size * 0.55 <= max_width and len(entries) * row_height <= max_height:
            break
        size -= 1
    return size


def _planet_row_svg(x: float, y: float, entry: dict, font_size: int) -> str:
    """One planet's row: abbreviation + optional smaller gray degree, ℞ on the degree.

    If degree_in_sign is unavailable (e.g. D-9 chart), ℞ attaches to the
    abbreviation instead, matching the old D-9 display convention.
    """
    abbrev = PLANET_ABBREVIATIONS[entry["name"]]
    degree = entry["degree_in_sign"]
    retro = entry["retrograde"]
    if degree is not None:
        degree_text = format_degree_minute(degree) + (RETROGRADE_MARK if retro else "")
        degree_font = max(font_size - 3, PLANET_FONT_MIN)
        content = (
            f'<tspan>{abbrev}</tspan>'
            f'<tspan fill="#888" font-size="{degree_font}"> {degree_text}</tspan>'
        )
    else:
        label = f"{abbrev} {RETROGRADE_MARK}" if retro else abbrev
        content = f'<tspan>{label}</tspan>'
    return (
        f'<text x="{x}" y="{y}" font-size="{font_size}" fill="#000" '
        f'text-anchor="middle" dominant-baseline="middle" '
        f'font-family="sans-serif">{content}</text>'
    )


def _text(x, y, content, size, fill="#000", weight="normal") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
        f'font-weight="{weight}" text-anchor="middle" '
        f'dominant-baseline="middle" font-family="sans-serif">{content}</text>'
    )


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render_north_indian_chart(
    planets_data: dict,
    ascendant_sign: str,
    chart_label: str = "D-1",
    ascendant_degree: float | None = None,
) -> str:
    """Render any Whole Sign chart (D-1, D-9, ...) as a North Indian SVG.

    Args:
        planets_data: {name: {"house": int, "retrograde": bool (optional),
            "degree_in_sign": float (optional)}} — D-1 planets from
            generate_kundali()["planets"] (has degree_in_sign), or D-9
            output of calculate_navamsa_houses() (no degree_in_sign; minus
            the ascendant_navamsa_sign key).
        ascendant_sign: sign occupying house 1 (D-1 lagna or D-9 lagna).
        chart_label: small label drawn in the top-left corner, e.g. "D-1"
            or "D-9 Navamsa", to tell charts apart.
        ascendant_degree: degree-in-sign of the ascendant (0-30), shown next
            to "Asc" as e.g. "Asc 25°23'" when provided.

    Returns the SVG document as a string. Raises ValueError if
    ascendant_sign is missing (e.g. unknown_time chart) — a North Indian
    chart is meaningless without a defined house 1.
    """
    if not ascendant_sign:
        raise ValueError(
            "Cannot render a North Indian chart without an ascendant sign: "
            "house placements are undefined (unknown_time chart?). "
            "Show planet positions as a table instead."
        )

    grouped = planets_by_house(planets_data)

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
        # Chart label, top-left corner
        f'<text x="8" y="16" font-size="10" fill="#444" font-weight="bold" '
        f'font-family="sans-serif">{chart_label}</text>',
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
            asc_text = "Asc" if ascendant_degree is None else f"Asc {format_degree_minute(ascendant_degree)}"
            parts.append(_text(200, 152, asc_text, 9, fill="#444", weight="bold"))

        # Planet rows, one planet per line, stacked and centered on the anchor
        entries = grouped[house]
        if entries:
            px, py = geometry["planets"]
            budget_class = geometry["per_row"]
            font_size = _fit_font_size(entries, WIDTH_BUDGET[budget_class], HEIGHT_BUDGET[budget_class])
            row_height = font_size + 3
            first_y = py - (len(entries) - 1) * row_height / 2
            for i, entry in enumerate(entries):
                parts.append(_planet_row_svg(px, first_y + i * row_height, entry, font_size))

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
    grouped = planets_by_house(chart["planets"])
    assert [e["name"] for e in grouped[10]] == ["Sun", "Saturn"]     # direct
    assert [e["name"] for e in grouped[12]] == ["Moon"]              # Aquarius
    assert [e["name"] for e in grouped[11]] == ["Mercury", "Venus", "Rahu"]
    assert all(e["retrograde"] for e in grouped[11])                 # all retro
    assert grouped[4][0]["name"] == "Jupiter" and grouped[4][0]["retrograde"]
    assert grouped[5][0]["name"] == "Ketu" and grouped[5][0]["retrograde"]

    # format_degree_minute spot check (from the task's own worked example)
    assert format_degree_minute(22.228) == "22°14'"

    asc_degree = chart["ascendant"]["degree_in_sign"]
    svg = render_north_indian_chart(
        chart["planets"], chart["ascendant"]["sign"], ascendant_degree=asc_degree
    )
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert ">D-1<" in svg
    assert ">Pisces<" in svg and ">Sagittarius<" in svg
    assert f"Asc {format_degree_minute(asc_degree)}" in svg
    # Jupiter (retrograde) shows its degree with the RETROGRADE_MARK attached
    jup_degree = format_degree_minute(chart["planets"]["Jupiter"]["degree_in_sign"])
    assert f"{jup_degree}{RETROGRADE_MARK}" in svg
    # Sun (direct) shows a plain degree, no retrograde mark
    sun_degree = format_degree_minute(chart["planets"]["Sun"]["degree_in_sign"])
    assert sun_degree in svg

    # missing ascendant sign (e.g. unknown_time chart) must be rejected
    try:
        render_north_indian_chart(chart["planets"], None)
        raise AssertionError("expected ValueError for missing ascendant sign")
    except ValueError:
        pass

    with open("north_chart_test.svg", "w", encoding="utf-8") as f:
        f.write(svg)

    # D-9 Navamsa chart from the same reference kundali (no degree_in_sign
    # data available for D-9, so it falls back to the abbrev(+retro) display)
    from navamsa_calculator import calculate_navamsa, calculate_navamsa_houses

    d9 = calculate_navamsa_houses(calculate_navamsa(chart))
    d9_lagna = d9.pop("ascendant_navamsa_sign")
    # carry D-1 retrograde flags onto the D-9 chart (convention)
    d9_planets = {
        name: {**data, "retrograde": chart["planets"][name]["retrograde"]}
        for name, data in d9.items()
    }
    svg_d9 = render_north_indian_chart(d9_planets, d9_lagna, "D-9 Navamsa")
    assert ">D-9 Navamsa<" in svg_d9 and ">Scorpio<" in svg_d9
    assert ">Mo<" in svg_d9 and ">Ma<" in svg_d9  # Moon + Mars in D-9 house 1

    with open("navamsa_chart_test.svg", "w", encoding="utf-8") as f:
        f.write(svg_d9)
    print("All chart assertions passed; wrote north_chart_test.svg + navamsa_chart_test.svg")
