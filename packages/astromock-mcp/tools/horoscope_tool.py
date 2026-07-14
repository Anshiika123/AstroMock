"""Horoscope context + prompt builder — thin adapter over astromock-core.

Core's horoscope_generator supplies the timeframe config, transit-fact
builder, book-context gatherer, prompt builder and the "Your Guidance"
template (single source of truth shared with the web app). This module
keeps the MCP tool's established response shape and adds
build_guidance_instructions() for the horoscope-guidance MCP prompt.

The MCP server deliberately does NOT call an LLM itself — it returns the
facts and the exact system/user prompts, and the calling client generates
the horoscope text with its own model.
"""

from horoscope_generator import (  # noqa: F401  (re-exports)
    FOCUS_AREAS,
    GUIDANCE_RULES,
    GUIDANCE_SECTIONS,
    GUIDANCE_SYSTEM_PROMPT,
    HOUSE_LIFE_AREAS,
    SYSTEM_PROMPT,
    TIMEFRAMES,
    TONES,
    build_prompt,
    build_transit_data,
    gather_book_context,
    upcoming_sign_changes,
)
from kundali_calculator import SIGNS


def _normalize_transits(transit_data: dict) -> dict:
    """Reduce any accepted transit_data shape to {planet: sign_name}.

    Accepts the full get_current_transits() result (with or without
    moon_sign analysis) or a bare {planet: sign} mapping.
    """
    transits = transit_data.get("transits", transit_data)
    return {
        planet: (value["transit_sign"] if isinstance(value, dict) else value)
        for planet, value in transits.items()
        if planet != "sade_sati_status"
    }


def generate_horoscope_tool(moon_sign: str, sade_sati_status: bool,
                            transit_data: dict, timeframe: str) -> dict:
    """Assemble everything a client LLM needs to write the horoscope.

    Args:
        moon_sign: natal Rashi, e.g. "Scorpio" (rashi.sign from
            calculate_kundali).
        sade_sati_status: whether Sade Sati is active (from
            get_current_transits with moon_sign). Echoed in the response;
            the transit-facts line itself is computed from the transits.
        transit_data: get_current_transits() output (either shape) or a
            bare {planet: sign} mapping.
        timeframe: "today", "2weeks", or "6months".

    Returns:
        dict with the filtered transit facts, classical book context, and
        ready-to-use system_prompt + suggested_prompt. No LLM is called
        here — the client generates the horoscope text.

    Raises:
        ValueError: unknown timeframe or moon_sign.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"timeframe must be one of {sorted(TIMEFRAMES)}, got {timeframe!r}"
        )
    if moon_sign not in SIGNS:
        raise ValueError(
            f"Unknown moon_sign: {moon_sign!r}. Expected one of {SIGNS}.")

    transits = _normalize_transits(transit_data)
    cfg = TIMEFRAMES[timeframe]

    transit_facts = build_transit_data(moon_sign, transits, timeframe)
    book_context = gather_book_context(moon_sign, transits, cfg["focus"])
    prompt = build_prompt(moon_sign, transit_facts, book_context, timeframe)

    return {
        "timeframe": timeframe,
        "label": cfg["label"],
        "word_target": cfg["words"],
        "moon_sign": moon_sign,
        "sade_sati_status": sade_sati_status,
        "focus_planets": cfg["focus"],
        "transit_facts": transit_facts,
        "book_context": book_context,
        "system_prompt": SYSTEM_PROMPT,
        "suggested_prompt": prompt,
        "instructions": (
            "This tool does not call an LLM. Write the horoscope yourself: "
            "adopt system_prompt as your role, then follow suggested_prompt "
            "exactly (tone, word count, grounding in the transit facts). "
            "Programmatic clients can pass system_prompt + suggested_prompt "
            "to their own LLM provider instead."
        ),
    }


def build_guidance_instructions(sign: str, timeframe: str,
                                tone: str = "gentle",
                                focus: str = "overall") -> str:
    """Instruction text for the horoscope-guidance MCP prompt.

    Tells the client model to fetch grounded facts via generate_horoscope
    first, then write the four "Your Guidance" sections using the shared
    template rules from core's horoscope_generator.

    Raises:
        ValueError: unknown sign, timeframe, tone or focus.
    """
    if sign not in SIGNS:
        raise ValueError(f"Unknown sign: {sign!r}. Expected one of {SIGNS}.")
    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"timeframe must be one of {sorted(TIMEFRAMES)}, got {timeframe!r}")
    if tone not in TONES:
        raise ValueError(f"tone must be one of {sorted(TONES)}, got {tone!r}")
    if focus not in FOCUS_AREAS:
        raise ValueError(
            f"focus must be one of {sorted(FOCUS_AREAS)}, got {focus!r}")

    cfg = TIMEFRAMES[timeframe]
    return (
        f"{GUIDANCE_SYSTEM_PROMPT}\n"
        f"\n"
        f'Write a {cfg["label"]} "Your Guidance" reading for a person '
        f"whose natal Moon sign (rashi) is {sign}.\n"
        f"\n"
        f"Step 1 — Call the generate_horoscope tool with "
        f'moon_sign="{sign}" and timeframe="{timeframe}" to fetch the '
        f"grounded transit facts. Never guess planetary positions.\n"
        f"\n"
        f"Step 2 — Using ONLY the returned transit_facts (book_context is "
        f"internal grounding — do not quote or cite it), write the "
        f"reading.\n"
        f"Tone: {TONES[tone]}.\n"
        f"Focus: {FOCUS_AREAS[focus]}. Weight the reading toward this "
        f"focus while staying honest to the facts.\n"
        f"Length: about {cfg['words']} words in total.\n"
        f"\n"
        f"{GUIDANCE_RULES}"
    )
