"""
astro_advisor.py — Explainable Q&A: D-1 facts + D-9 support + dasha +
transits + interpreted Ashtakavarga signals, answered via the pluggable
LLM provider.

This is the v2 of the question-answering pipeline. It reuses
interpretation_engine.gather_question_context() for routing/facts and adds:
- divisional (D-9) support for the relevant house lords and occupants,
- the compact Ashtakavarga signals object (never raw bindu tables),
- the structured ASTRO-MOCK advisor prompt (prompts/advisor_prompt.md)
  with normal / deep / technical depth modes.
"""

import json
from pathlib import Path

from ashtakavarga_calculator import interpret_ashtakavarga_signals
from book_retriever import get_relevant_book_context
from career_advisor import answer_career_question
from house_analyzer import analyze_house
from interpretation_engine import gather_question_context
from kundali_calculator import SIGNS
from llm_provider import get_interpretation
from navamsa_calculator import calculate_navamsa, calculate_navamsa_houses
from topic_to_house_mapping import identify_topics
from transit_calculator import get_current_transits

PROMPT_PATH = Path(__file__).parent / "prompts" / "advisor_prompt.md"
DEEPEN_PROMPT_PATH = Path(__file__).parent / "prompts" / "deepen_prompt.md"
DEPTHS = ("normal", "deep", "technical")
DEEPEN_DEPTHS = ("deep", "technical")  # "go deeper" than an initial normal answer
SLOW_MOVERS = ("Jupiter", "Saturn", "Rahu", "Ketu")


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_deepen_prompt() -> str:
    return DEEPEN_PROMPT_PATH.read_text(encoding="utf-8")


def _chart_facts(kundali_data: dict, context: dict) -> str:
    """D-1 facts for the focus houses, plus trimmed classical notes."""
    moon = kundali_data["planets"]["Moon"]
    lines = [
        f"Lagna (ascendant): "
        f"{kundali_data['ascendant']['sign'] if kundali_data.get('ascendant') else 'unknown (birth time not known)'}",
        f"Moon sign (rashi): {moon['sign']} — nakshatra "
        f"{moon['nakshatra']['name']} (pada {moon['nakshatra']['pada']})",
    ]
    for house, a in context["house_analyses"].items():
        planets = (", ".join(a["planets_in_house"])
                   if a["planets_in_house"] else "no planets (empty house)")
        lines.append(
            f"House {house} ({a['house_sign']}): contains {planets}; "
            f"lord {a['house_lord']} placed in house "
            f"{a['lord_placed_in_house']}"
        )
    refs = context["book_references"]
    if refs:
        trimmed = " ".join(refs.split()[:150])
        lines.append(f"Classical notes (Bhava Adhyaya): {trimmed}")
    return "\n".join(lines)


def _divisional_support(kundali_data: dict, context: dict,
                        navamsa_data: dict | None) -> str:
    """D-9 placement of each focus house's lord and occupants."""
    if kundali_data.get("ascendant") is None:
        return ("D-9 unavailable: birth time unknown, navamsa lagna "
                "cannot be fixed.")
    if navamsa_data is None:
        navamsa_data = calculate_navamsa_houses(calculate_navamsa(kundali_data))

    lines = [f"D-9 (Navamsa) lagna: {navamsa_data['ascendant_navamsa_sign']}"]
    for house, a in context["house_analyses"].items():
        lord = a["house_lord"]
        d9 = navamsa_data[lord]
        lines.append(
            f"House {house} lord {lord} sits in {d9['navamsa_sign']} in D-9 "
            f"(D-9 house {d9['house']})"
        )
        for planet in a["planets_in_house"]:
            p9 = navamsa_data[planet]
            lines.append(
                f"House {house} occupant {planet} sits in "
                f"{p9['navamsa_sign']} in D-9 (D-9 house {p9['house']})"
            )
        # Vargottama (same sign in D-1 and D-9) strengthens a planet
        if kundali_data["planets"][lord]["sign"] == d9["navamsa_sign"]:
            lines.append(f"{lord} is vargottama (same sign in D-1 and D-9) "
                         f"— extra strength")
    return "\n".join(lines)


def _dasha_context(context: dict) -> str:
    dasha = context["dasha"]
    md = dasha["current_mahadasha"]
    if md is None:
        return "Current mahadasha could not be determined."
    lines = [f"Current Mahadasha: {md['planet']} "
             f"({md['start_date']} to {md['end_date']})"]
    ad = dasha["current_antardasha"]
    if ad:
        lines.append(f"Current Antardasha: {md['planet']}–{ad['planet']} "
                     f"({ad['start_date']} to {ad['end_date']})")
    return "\n".join(lines)


def _transit_context(context: dict) -> str:
    """Slow movers + anything transiting a focus house + Sade Sati."""
    gochar = context["gochar"]
    focus_houses = set(context["houses"])
    lines = []
    for planet, info in gochar.items():
        if planet == "sade_sati_status":
            continue
        relevant = planet in SLOW_MOVERS or info["house_from_moon"] in focus_houses
        if relevant:
            lines.append(
                f"{planet} transiting {info['transit_sign']} — house "
                f"{info['house_from_moon']} from the Moon"
            )
    lines.append("Sade Sati: ACTIVE" if gochar["sade_sati_status"]
                 else "Sade Sati: not active")
    return "\n".join(lines)


def _general_focus_houses(kundali_data: dict, context: dict) -> list[int]:
    """Default houses for a question that matched no life-area topic:
    house 1 (the lagna — self and overall direction) plus the natal houses
    of the current Mahadasha and Antardasha lords, since a general "how is
    my time" reading runs on what the active dasha lords activate."""
    houses = {1}
    dasha = context["dasha"]
    lords = []
    if dasha["current_mahadasha"]:
        lords.append(dasha["current_mahadasha"]["planet"])
    if dasha["current_antardasha"]:
        lords.append(dasha["current_antardasha"]["planet"])
    for lord in lords:
        house = kundali_data["planets"][lord].get("house")
        if house:
            houses.add(house)
    return sorted(houses)


def _inject_general_context(kundali_data: dict, context: dict) -> None:
    """For no-topic questions, fill house_analyses/book_references with the
    general focus houses so the prompt is as grounded as a topical one."""
    if context["houses"] or kundali_data.get("ascendant") is None:
        return
    houses = _general_focus_houses(kundali_data, context)
    analyses, references = {}, []
    for house in houses:
        analysis = analyze_house(kundali_data, house)
        analyses[house] = analysis
        try:
            ref = get_relevant_book_context(
                house, analysis["planets_in_house"],
                analysis["house_lord"], analysis["lord_placed_in_house"])
        except FileNotFoundError:
            ref = ""
        if ref:
            references.append(f"--- References for house {house} ---\n{ref}")
    context["houses"] = houses
    context["house_analyses"] = analyses
    context["book_references"] = "\n\n".join(references)


def build_advisor_input(user_question: str, kundali_data: dict,
                        depth: str = "normal",
                        navamsa_data: dict | None = None) -> dict:
    """{system, user, context, signals} for the advisor LLM call."""
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {DEPTHS}, got {depth!r}")

    context = gather_question_context(user_question, kundali_data,
                                      navamsa_data)
    is_general = not context["topics"]
    if is_general:
        _inject_general_context(kundali_data, context)
    focus_area = (
        "general (reading routed via the lagna and current dasha lords)"
        if is_general else ", ".join(context["topics"]))
    transits = get_current_transits()
    signals = interpret_ashtakavarga_signals(kundali_data, transits)

    user_message = (
        f"<user_question>\n{user_question}\n</user_question>\n\n"
        f"<focus_area>\n{focus_area}\n</focus_area>\n\n"
        f"<depth>\n{depth}\n</depth>\n\n"
        f"<chart_facts>\n{_chart_facts(kundali_data, context)}\n</chart_facts>\n\n"
        f"<divisional_support>\n"
        f"{_divisional_support(kundali_data, context, navamsa_data)}\n"
        f"</divisional_support>\n\n"
        f"<dasha_context>\n{_dasha_context(context)}\n</dasha_context>\n\n"
        f"<transit_context>\n{_transit_context(context)}\n</transit_context>\n\n"
        f"<ashtakavarga_signals>\n{json.dumps(signals, indent=1)}\n"
        f"</ashtakavarga_signals>"
    )
    return {"system": load_system_prompt(), "user": user_message,
            "context": context, "signals": signals}


def answer_question(user_question: str, kundali_data: dict,
                    depth: str = "normal",
                    navamsa_data: dict | None = None,
                    llm: "callable" = None) -> str:
    """Answer a question with the full explainable pipeline.

    Pure career questions (identify_topics() returns exactly ["career"])
    are routed to career_advisor's specialized house-10 pipeline and
    prompt (prompts/career_prompt.md) instead of the general advisor
    prompt. Multi-topic questions that happen to include career (e.g.
    "career aur marriage dono kaisi hogi") still use the general advisor,
    since the career-only pipeline can't speak to the other topics.

    Args:
        user_question: free text (English or Hinglish).
        depth: "normal" | "deep" | "technical" (controls answer sections).
        navamsa_data: optional precomputed calculate_navamsa_houses()
            output; computed on the fly when omitted.
        llm: callable(system, user) -> str; defaults to llm_provider's
            get_interpretation.
    """
    if identify_topics(user_question) == ["career"]:
        return answer_career_question(user_question, kundali_data, depth,
                                      navamsa_data, llm)

    payload = build_advisor_input(user_question, kundali_data, depth,
                                  navamsa_data)
    call = llm or get_interpretation
    return call(payload["system"], payload["user"])


def _active_periods_block(context: dict, signals: dict) -> str:
    """Dasha + transit + Ashtakavarga folded into one block.

    Unlike build_advisor_input()'s three separate tags (dasha_context,
    transit_context, ashtakavarga_signals), deepen_prompt.md has a single
    <active_periods> tag, so the three are combined here instead.
    """
    lines = [_dasha_context(context), _transit_context(context),
             "Ashtakavarga signal (interpreted): " + json.dumps(signals)]
    return "\n".join(lines)


def build_deepen_input(user_question: str, previous_answer: str,
                       kundali_data: dict, requested_depth: str = "deep",
                       navamsa_data: dict | None = None) -> dict:
    """{system, user, context} to expand a prior general-advisor answer.

    General-advisor scope only: reuses the same focus-house logic as
    build_advisor_input() (topical houses, or the lagna + dasha-lord
    houses for a general question) so the deeper reading stays grounded
    in the same facts the original short answer was based on.
    """
    if requested_depth not in DEEPEN_DEPTHS:
        raise ValueError(
            f"requested_depth must be one of {DEEPEN_DEPTHS}, got {requested_depth!r}")

    context = gather_question_context(user_question, kundali_data, navamsa_data)
    if not context["topics"]:
        _inject_general_context(kundali_data, context)

    transits = get_current_transits()
    signals = interpret_ashtakavarga_signals(kundali_data, transits)

    user_message = (
        f"<original_question>\n{user_question}\n</original_question>\n\n"
        f"<previous_answer>\n{previous_answer}\n</previous_answer>\n\n"
        f"<chart_facts>\n{_chart_facts(kundali_data, context)}\n</chart_facts>\n\n"
        f"<active_periods>\n{_active_periods_block(context, signals)}\n</active_periods>\n\n"
        f"<requested_depth>\n{requested_depth}\n</requested_depth>"
    )
    return {"system": load_deepen_prompt(), "user": user_message,
            "context": context, "signals": signals}


def deepen_answer(user_question: str, previous_answer: str,
                  kundali_data: dict, requested_depth: str = "deep",
                  navamsa_data: dict | None = None,
                  llm: "callable" = None) -> str:
    """Expand a previous general-advisor answer with deeper chart reasoning.

    Args:
        user_question: the ORIGINAL question that produced previous_answer.
        previous_answer: the answer text already shown to the user.
        requested_depth: "deep" | "technical" (deeper than the initial
            "normal" answer — there's no sense "deepening" back to normal).
        llm: callable(system, user) -> str; defaults to llm_provider's
            get_interpretation.
    """
    payload = build_deepen_input(user_question, previous_answer, kundali_data,
                                 requested_depth, navamsa_data)
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
    payload = build_advisor_input(QUESTION, chart, depth="normal")
    assert payload["context"]["houses"] == [10]
    assert "<ashtakavarga_signals>" in payload["user"]
    assert "bindu" not in payload["user"].lower().replace(
        "ashtakavarga", "")  # no raw bindu tables leak into the prompt
    assert "ASTRO-MOCK" in payload["system"]
    for bad_depth in ("shallow", "max"):
        try:
            build_advisor_input(QUESTION, chart, depth=bad_depth)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    # General question (no topic keywords): must route via lagna + dasha
    # lords instead of returning a thin, house-less prompt.
    GENERAL_QUESTION = "aane wala saal mera kaisa rahega"
    general = build_advisor_input(GENERAL_QUESTION, chart, depth="normal")
    assert general["context"]["topics"] == []
    assert 1 in general["context"]["houses"], general["context"]["houses"]
    assert general["context"]["house_analyses"], "general context is empty"
    assert "general" in general["user"]
    print("general question focus houses:", general["context"]["houses"])

    print("interpreted Ashtakavarga signals:")
    print(json.dumps(payload["signals"], indent=1))

    # --- deepen_answer(): offline assembly checks ---
    FAKE_PREVIOUS = ("Summary: your career direction looks steady. Why: "
                     "Jupiter supports house 10. Practical takeaway: keep "
                     "building skills. Precision note: exact timing needs "
                     "more chart depth.")
    deepen_payload = build_deepen_input(QUESTION, FAKE_PREVIOUS, chart,
                                        requested_depth="deep")
    assert "<previous_answer>" in deepen_payload["user"]
    assert FAKE_PREVIOUS in deepen_payload["user"]
    assert "<active_periods>" in deepen_payload["user"]
    assert "ASTRO-MOCK" in deepen_payload["system"]
    for bad_depth in ("normal", "shallow"):
        try:
            build_deepen_input(QUESTION, FAKE_PREVIOUS, chart,
                               requested_depth=bad_depth)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    print("deepen_answer() offline assembly checks passed")

    for question, depth in ((QUESTION, "normal"),
                            (GENERAL_QUESTION, "normal"),
                            (GENERAL_QUESTION, "deep")):
        print("=" * 70)
        print(f"QUESTION: {question} | DEPTH: {depth}")
        print("-" * 70)
        try:
            print(answer_question(question, chart, depth=depth))
        except Exception as e:
            print(f"SKIPPED LLM call: {str(e)[:200]}")
        time.sleep(20)  # free-tier Gemini rate limit

    print("=" * 70)
    print("DEEPEN: expanding the fake previous answer above")
    print("-" * 70)
    try:
        print(deepen_answer(QUESTION, FAKE_PREVIOUS, chart, requested_depth="deep"))
    except Exception as e:
        print(f"SKIPPED LLM call: {str(e)[:200]}")
