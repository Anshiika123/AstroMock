"""
career_advisor.py — Career-specific Q&A: D-1 house-10 facts + D-9 support +
dasha/transit/Ashtakavarga "active periods", answered via the specialized
career advisor prompt (prompts/career_prompt.md).

Career questions always concern house 10 (profession), so unlike
astro_advisor.py this module skips topic->house keyword routing and goes
straight to house 10's analysis, D-9 support for its lord/occupants, and
the current dasha/transit/Ashtakavarga picture folded into one "active
periods" block (matching this prompt's single ACTIVE PERIODS tag).

D-10 (Dasamsha) is not yet computed by this codebase; the "D9 / D10
considerations" section of the technical-depth prompt is grounded in D-9
support only — the model is told so rather than left to invent D-10 data.

astro_advisor.build_advisor_input() routes here instead of the general
advisor prompt when the identified topic is "career".
"""

import json
from pathlib import Path

from ashtakavarga_calculator import interpret_ashtakavarga_signals
from dasha_calculator import calculate_vimshottari_dasha
from house_analyzer import analyze_house
from llm_provider import get_interpretation
from navamsa_calculator import calculate_navamsa, calculate_navamsa_houses
from transit_calculator import analyze_transit_impact, get_current_transits

PROMPT_PATH = Path(__file__).parent / "prompts" / "career_prompt.md"
DEPTHS = ("normal", "deep", "technical")
CAREER_HOUSE = 10
SLOW_MOVERS = ("Jupiter", "Saturn", "Rahu", "Ketu")


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _career_chart_facts(kundali_data: dict, navamsa_data: dict | None,
                        depth: str) -> str:
    """D-1 house-10 facts + D-9 support for its lord/occupants.

    Classical (BPHS) references are included only at depth="technical",
    per the prompt's "no classical references unless technical" rule.
    """
    if kundali_data.get("ascendant") is None:
        return ("Lagna unknown (birth time not known) — house 10 cannot be "
                "fixed reliably. Career reading is limited to Sun/Saturn/"
                "Rahu sign placements only.")

    a = analyze_house(kundali_data, CAREER_HOUSE)
    planets = (", ".join(a["planets_in_house"])
              if a["planets_in_house"] else "no planets (empty house)")
    lines = [
        f"House 10 ({a['house_sign']}): contains {planets}; "
        f"lord {a['house_lord']} placed in house {a['lord_placed_in_house']}",
    ]

    if navamsa_data is None:
        navamsa_data = calculate_navamsa_houses(calculate_navamsa(kundali_data))
    lord = a["house_lord"]
    d9_lord = navamsa_data[lord]
    lines.append(
        f"D-9: house 10 lord {lord} sits in {d9_lord['navamsa_sign']} "
        f"(D-9 house {d9_lord['house']})"
    )
    if kundali_data["planets"][lord]["sign"] == d9_lord["navamsa_sign"]:
        lines.append(f"{lord} is vargottama (same sign in D-1 and D-9) "
                     f"— extra strength")
    for planet in a["planets_in_house"]:
        d9p = navamsa_data[planet]
        lines.append(
            f"D-9: house 10 occupant {planet} sits in {d9p['navamsa_sign']} "
            f"(D-9 house {d9p['house']})"
        )
    lines.append("D-10 (Dasamsha): not computed by this system — ground "
                 "any D9/D10 discussion in the D-9 facts above only.")

    if depth == "technical" and a["planets_in_house"] is not None:
        from book_retriever import get_relevant_book_context
        try:
            refs = get_relevant_book_context(
                CAREER_HOUSE, a["planets_in_house"], a["house_lord"],
                a["lord_placed_in_house"])
        except FileNotFoundError:
            refs = ""
        if refs:
            trimmed = " ".join(refs.split()[:150])
            lines.append(f"Classical notes (Bhava Adhyaya): {trimmed}")

    return "\n".join(lines)


def _active_periods(kundali_data: dict) -> str:
    """Dasha + house-10-relevant transits + Ashtakavarga, one plain block."""
    moon_lon = kundali_data["planets"]["Moon"]["longitude"]
    moon_sign = kundali_data["planets"]["Moon"]["sign"]
    dasha = calculate_vimshottari_dasha(
        moon_lon, kundali_data["birth_details"]["date_of_birth"])
    transits = get_current_transits()
    gochar = analyze_transit_impact(moon_sign, transits)

    lines = []
    md = dasha["current_mahadasha"]
    if md is None:
        lines.append("Current mahadasha could not be determined.")
    else:
        lines.append(f"Current Mahadasha: {md['planet']} "
                     f"({md['start_date']} to {md['end_date']})")
        ad = md.get("current_antardasha")
        if ad:
            lines.append(f"Current Antardasha: {md['planet']}-{ad['planet']} "
                         f"({ad['start_date']} to {ad['end_date']})")

    for planet, info in gochar.items():
        if planet == "sade_sati_status":
            continue
        if planet in SLOW_MOVERS or info["house_from_moon"] == CAREER_HOUSE:
            lines.append(f"{planet} transiting {info['transit_sign']} — "
                         f"house {info['house_from_moon']} from the Moon")
    lines.append("Sade Sati: ACTIVE" if gochar["sade_sati_status"]
                 else "Sade Sati: not active")

    signals = interpret_ashtakavarga_signals(kundali_data, transits)
    lines.append("Ashtakavarga signal (interpreted, career-relevant): " +
                 json.dumps(signals))
    return "\n".join(lines)


def build_career_input(user_question: str, kundali_data: dict,
                       depth: str = "normal",
                       navamsa_data: dict | None = None) -> dict:
    """{system, user, context} for the career advisor LLM call."""
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {DEPTHS}, got {depth!r}")

    user_message = (
        f"QUESTION:\n{user_question}\n\n"
        f"DEPTH:\n{depth}\n\n"
        f"CHART FACTS:\n{_career_chart_facts(kundali_data, navamsa_data, depth)}\n\n"
        f"ACTIVE PERIODS:\n{_active_periods(kundali_data)}"
    )
    return {"system": load_system_prompt(), "user": user_message,
            "context": {"house": CAREER_HOUSE, "depth": depth}}


def answer_career_question(user_question: str, kundali_data: dict,
                           depth: str = "normal",
                           navamsa_data: dict | None = None,
                           llm: "callable" = None) -> str:
    """Answer a career question with the specialized career pipeline.

    Args:
        user_question: free text (English or Hinglish).
        depth: "normal" | "deep" | "technical".
        llm: callable(system, user) -> str; defaults to llm_provider's
            get_interpretation.
    """
    payload = build_career_input(user_question, kundali_data, depth,
                                 navamsa_data)
    call = llm or get_interpretation
    return call(payload["system"], payload["user"])


# ---------------------------------------------------------------------------
# Test — career question on the verified Saharanpur chart, all depths
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import time

    from kundali_calculator import generate_kundali

    chart = generate_kundali("2004-09-21", "10:30",
                             29.9680, 77.5459, "Asia/Kolkata")
    QUESTION = "kya mera career acha hoga"

    # Offline assembly checks (no LLM call)
    payload = build_career_input(QUESTION, chart, depth="normal")
    assert "House 10" in payload["user"]
    assert "D-10 (Dasamsha): not computed" in payload["user"]
    assert "Classical notes" not in payload["user"]  # not technical depth
    assert "ASTRO-MOCK" in payload["system"]
    for bad_depth in ("shallow", "max"):
        try:
            build_career_input(QUESTION, chart, depth=bad_depth)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    tech_payload = build_career_input(QUESTION, chart, depth="technical")
    print("technical-depth payload includes classical notes:",
          "Classical notes" in tech_payload["user"])

    print("=" * 70)
    print("user message sent to LLM (normal depth):")
    print(payload["user"])

    for i, depth in enumerate(DEPTHS):
        print("=" * 70)
        print(f"DEPTH: {depth}")
        print("-" * 70)
        try:
            print(answer_career_question(QUESTION, chart, depth=depth))
        except Exception as e:
            print(f"SKIPPED LLM call: {str(e)[:200]}")
        if i < len(DEPTHS) - 1:
            time.sleep(20)  # free-tier Gemini rate limit
