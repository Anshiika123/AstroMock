"""
horoscope_generator.py — Transit-based daily / 2-week / 6-month horoscopes.

Pipeline: current Gochar (transit_calculator) -> timeframe-specific focus
planets and their houses from the natal Moon -> relevant Bhava Adhyaya
passages (book_retriever) -> one prompt. The generate_* wrappers call the
web app's llm_provider lazily, so this module stays importable from core
without any LLM dependency (MCP tools import only the builders).

Timeframes:
    "today"    Moon's daily transit + Sun aspect            (~100 words)
    "2weeks"   Sun/Mercury/Venus, incl. upcoming sign shifts (~200 words)
    "6months"  Jupiter/Saturn/Rahu/Ketu, incl. Sade Sati     (~300 words)
"""

from datetime import date, timedelta

from book_retriever import get_relevant_book_context
from house_analyzer import SIGN_LORDS
from transit_calculator import (analyze_transit_impact, get_current_transits,
                                house_from_moon)

TIMEFRAMES = {
    "today": {
        "focus": ["Moon", "Sun"],
        "words": 100,
        "label": "daily (today's)",
    },
    "2weeks": {
        "focus": ["Sun", "Mercury", "Venus"],
        "words": 200,
        "label": "2-week",
    },
    "6months": {
        "focus": ["Jupiter", "Saturn", "Rahu", "Ketu"],
        "words": 300,
        "label": "6-month",
    },
}

# Life areas per house-from-Moon, used to ground the 6-month prediction.
HOUSE_LIFE_AREAS = {
    1: "self, body and overall direction",
    2: "wealth, savings and family",
    3: "courage, effort and siblings",
    4: "home, property and mother",
    5: "children, studies and creativity",
    6: "health, debts and daily obstacles",
    7: "marriage, partnerships and business relations",
    8: "sudden changes and transformation",
    9: "fortune, father and dharma",
    10: "career, work and public standing",
    11: "gains, income and friendships",
    12: "expenses, sleep and foreign matters",
}

SYSTEM_PROMPT = (
    "You are an experienced Vedic astrologer with a warm, encouraging, "
    "practical style. You ground every statement in the specific transit "
    "facts given to you and never invent planetary positions."
)

_SIGN_CHANGE_SCAN_DAYS = 14


def upcoming_sign_changes(planets: list[str],
                          days: int = _SIGN_CHANGE_SCAN_DAYS) -> dict:
    """First sign change for each planet within the next `days` days.

    Returns {planet: {"from": sign, "to": sign, "on": "YYYY-MM-DD"}} for
    planets that change sign in the window; planets that stay put are
    absent from the result.
    """
    start = date.today()
    baseline = get_current_transits(start.isoformat())
    changes = {}
    pending = set(planets)
    for offset in range(1, days + 1):
        if not pending:
            break
        day = (start + timedelta(days=offset)).isoformat()
        transits = get_current_transits(day)
        for planet in list(pending):
            if transits[planet] != baseline[planet]:
                changes[planet] = {"from": baseline[planet],
                                   "to": transits[planet], "on": day}
                pending.discard(planet)
    return changes


def _transit_lines(impact: dict, focus: list[str]) -> list[str]:
    """Human-readable transit facts for the focus planets."""
    lines = []
    for planet in focus:
        p = impact[planet]
        area = HOUSE_LIFE_AREAS[p["house_from_moon"]]
        lines.append(
            f"- {planet} is transiting {p['transit_sign']} — house "
            f"{p['house_from_moon']} from the Moon sign ({area})"
        )
    return lines


def build_transit_data(moon_sign: str, transits: dict, timeframe: str) -> str:
    """Timeframe-specific transit summary passed to the LLM."""
    impact = analyze_transit_impact(moon_sign, transits)
    focus = TIMEFRAMES[timeframe]["focus"]
    lines = _transit_lines(impact, focus)

    if timeframe == "today":
        # Major Sun aspect on the transit Moon: conjunction (same sign)
        # or the full 7th aspect (opposition).
        gap = (house_from_moon(transits["Sun"], transits["Moon"]))
        if gap == 1:
            lines.append("- Major aspect: the Sun is conjunct the transit "
                         "Moon (same sign) today")
        elif gap == 7:
            lines.append("- Major aspect: the Sun casts its full 7th-house "
                         "aspect on the transit Moon today")
        else:
            lines.append("- No major Sun aspect on the transit Moon today")

    elif timeframe == "2weeks":
        changes = upcoming_sign_changes(focus)
        for planet in focus:
            if planet in changes:
                c = changes[planet]
                new_house = house_from_moon(moon_sign, c["to"])
                lines.append(
                    f"- Within the next 14 days: {planet} moves from "
                    f"{c['from']} into {c['to']} around {c['on']} — entering "
                    f"house {new_house} from the Moon "
                    f"({HOUSE_LIFE_AREAS[new_house]})"
                )
            else:
                lines.append(f"- {planet} stays in "
                             f"{transits[planet]} for the full 14-day window")

    elif timeframe == "6months":
        if impact["sade_sati_status"]:
            lines.append("- Sade Sati is ACTIVE (Saturn is transiting the "
                         "12th/1st/2nd from the natal Moon)")
        else:
            lines.append("- Sade Sati is not active")

    return "\n".join(lines)


def gather_book_context(moon_sign: str, transits: dict,
                        focus: list[str], max_words: int = 1000) -> str:
    """Bhava Adhyaya passages for the houses the focus planets transit.

    Deduplicates passages shared between planets and caps the total at
    ~max_words. Degrades to a placeholder if the index isn't built.
    """
    seen, blocks, words = set(), [], 0
    for planet in focus:
        sign = transits[planet]
        house = house_from_moon(moon_sign, sign)
        lord = SIGN_LORDS[sign]
        lord_house = house_from_moon(moon_sign, transits.get(lord, sign)) \
            if lord in transits else house
        try:
            ctx = get_relevant_book_context(house, [planet], lord, lord_house)
        except FileNotFoundError:
            return "(reference text unavailable — book index not built yet)"
        for block in ctx.split("\n\n"):
            if not block or block in seen:
                continue
            n = len(block.split())
            if blocks and words + n > max_words:
                break
            seen.add(block)
            blocks.append(block)
            words += n
    return "\n\n".join(blocks) or "(no directly relevant passage found)"


def build_prompt(moon_sign: str, transit_data: str, book_context: str,
                 timeframe: str) -> str:
    cfg = TIMEFRAMES[timeframe]
    return (
        f"User's Moon sign: {moon_sign}\n"
        f"Current transits:\n{transit_data}\n"
        f"\n"
        f"Relevant classical text:\n{book_context}\n"
        f"\n"
        f"Generate a {cfg['label']} horoscope prediction in a warm, "
        f"encouraging tone like an experienced astrologer. Keep it to "
        f"{cfg['words']} words. Mention specific planets and houses in "
        f"simple language, not just generic statements."
    )


# ---------------------------------------------------------------------------
# "Your Guidance" template — reader-friendly horoscope, no tables, no fear.
# Single source of truth: astromock-mcp's tools/horoscope_tool.py imports
# these constants for its horoscope-guidance MCP prompt.
# ---------------------------------------------------------------------------

GUIDANCE_SECTIONS = (
    "How your period looks",
    "What to lean into",
    "What to avoid",
    "Helpful note",
)

TONES = {
    "gentle": ("soft, soothing and reassuring — like a caring elder "
               "speaking kindly"),
    "practical": ("grounded and matter-of-fact — plain everyday language "
                  "centred on what to actually do"),
    "motivational": ("upbeat and confidence-building — energising without "
                     "being preachy"),
}

FOCUS_AREAS = {
    "overall": ("the period as a whole — mood, work, relationships and "
                "wellbeing in balance"),
    "career": "work, business, studies and ambition",
    "love": "relationships, romance, marriage and emotional bonds",
    "health": "energy levels, rest, routine and general wellbeing",
}

GUIDANCE_RULES = """Rules for the reading:
- Ground every statement in the transit facts you were given. Never invent planetary positions.
- Do NOT show any planet table, degrees, house numbers or technical jargon in the final answer. You may mention at most one or two planets by name, casually, if it helps ("with Saturn asking for patience...").
- No scary or fatalistic wording — never words like danger, disaster, doom, death, accident, curse, suffering. Frame every challenge gently as something to be mindful of.
- Keep sections short and readable: 1-3 sentences each, plain conversational language, second person ("you").
- "What to lean into" carries exactly one uplifting thread — the clearest strength or opportunity of the period.
- "What to avoid" carries exactly one caution, kindly framed.
- "Helpful note" carries exactly one practical suggestion the person can act on today.

Format the answer as exactly these four sections, each heading on its own line, in this order:
How your period looks
What to lean into
What to avoid
Helpful note

Example of the desired voice (a "today" reading): "Today feels mentally active but slightly heavy, so avoid overthinking small delays. Focus on one important task, keep communication calm, and your day will feel much more balanced." """

GUIDANCE_SYSTEM_PROMPT = (
    "You are an experienced Vedic astrologer with a warm voice. You ground "
    "every statement in the transit facts given to you, never invent "
    "planetary positions, and never use frightening language."
)


def build_guidance_input(kundali_data: dict, timeframe: str,
                         tone: str = "gentle",
                         focus: str = "overall") -> dict:
    """System + user prompts (and grounding context) for a guidance reading.

    Same shape as interpretation_engine.build_llm_input so app.py can use
    the get_llm() pattern and still respond when no LLM is configured.

    Raises:
        ValueError: unknown timeframe, tone or focus.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"timeframe must be one of {sorted(TIMEFRAMES)}, got {timeframe!r}")
    if tone not in TONES:
        raise ValueError(f"tone must be one of {sorted(TONES)}, got {tone!r}")
    if focus not in FOCUS_AREAS:
        raise ValueError(
            f"focus must be one of {sorted(FOCUS_AREAS)}, got {focus!r}")

    moon_sign = kundali_data["rashi"]["sign"]
    transits = get_current_transits()
    transit_data = build_transit_data(moon_sign, transits, timeframe)
    book_context = gather_book_context(moon_sign, transits,
                                       TIMEFRAMES[timeframe]["focus"])
    cfg = TIMEFRAMES[timeframe]
    user = (
        f"User's Moon sign: {moon_sign}\n"
        f"Transit facts:\n{transit_data}\n"
        f"\n"
        f"Relevant classical text (internal grounding only — do not quote "
        f"or cite it):\n{book_context}\n"
        f"\n"
        f'Write a {cfg["label"]} "Your Guidance" reading.\n'
        f"Tone: {TONES[tone]}.\n"
        f"Focus: {FOCUS_AREAS[focus]}. Weight the reading toward this focus "
        f"while staying honest to the facts.\n"
        f"Length: about {cfg['words']} words in total.\n"
        f"\n"
        f"{GUIDANCE_RULES}"
    )
    return {
        "system": GUIDANCE_SYSTEM_PROMPT,
        "user": user,
        "context": {
            "moon_sign": moon_sign,
            "timeframe": timeframe,
            "tone": tone,
            "focus": focus,
            "transit_facts": transit_data,
        },
    }


def generate_guidance(kundali_data: dict, timeframe: str,
                      tone: str = "gentle", focus: str = "overall") -> str:
    """Guidance reading text (calls the configured LLM via apps/web).

    Raises:
        ValueError: unknown timeframe, tone or focus.
        RuntimeError: from llm_provider if no API key is configured.
    """
    from llm_provider import get_interpretation  # lazy: web-app dependency
    gi = build_guidance_input(kundali_data, timeframe, tone, focus)
    return get_interpretation(gi["system"], gi["user"])


def generate_horoscope(kundali_data: dict, timeframe: str) -> str:
    """Transit-based horoscope for a kundali over a chosen timeframe.

    Raises:
        ValueError: unknown timeframe.
        RuntimeError: from llm_provider if no API key is configured.
    """
    from llm_provider import get_interpretation  # lazy: web-app dependency
    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"timeframe must be one of {sorted(TIMEFRAMES)}, got {timeframe!r}"
        )

    moon_sign = kundali_data["rashi"]["sign"]
    transits = get_current_transits()
    transit_data = build_transit_data(moon_sign, transits, timeframe)
    book_context = gather_book_context(moon_sign, transits,
                                       TIMEFRAMES[timeframe]["focus"])
    prompt = build_prompt(moon_sign, transit_data, book_context, timeframe)
    return get_interpretation(SYSTEM_PROMPT, prompt)
