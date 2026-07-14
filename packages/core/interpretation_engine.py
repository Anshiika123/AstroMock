"""
interpretation_engine.py — Assemble LLM-ready input for chart interpretation.

The interpretation itself is done by an LLM using the system prompt in
prompts/interpretation_prompt.md. This module does everything BEFORE that
call: route the user's question to houses, analyze those houses from the
kundali, pull classical references from the indexed book, and package it
all into {system, user} messages. The LLM call itself is pluggable — pass
any callable(system_prompt, user_message) -> str.

Pipeline:
  question -> identify_relevant_houses() -> analyze_house() per house
           -> get_relevant_book_context() per house
           -> build_llm_input() -> your LLM
"""

import json
from pathlib import Path

from book_retriever import get_relevant_book_context
from dasha_calculator import calculate_vimshottari_dasha
from house_analyzer import analyze_house
from topic_to_house_mapping import identify_relevant_houses, identify_topics
from transit_calculator import analyze_transit_impact, get_current_transits

PROMPT_PATH = Path(__file__).parent / "prompts" / "interpretation_prompt.md"


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def gather_question_context(user_question: str, kundali_data: dict,
                            navamsa_data: dict | None = None) -> dict:
    """Collect every backend fact relevant to the question.

    Returns {"topics", "houses", "gochar", "house_analyses",
    "book_references", "dasha", "navamsa"} — the raw material for the LLM
    input. Empty "houses" means the question didn't match any known
    life-area (caller may fall back to a general reading).
    """
    houses = identify_relevant_houses(user_question)
    analyses = {}
    references = []
    if kundali_data.get("ascendant") is not None:
        for house in houses:
            analysis = analyze_house(kundali_data, house)
            analyses[house] = analysis
            try:
                ref = get_relevant_book_context(
                    house,
                    analysis["planets_in_house"],
                    analysis["house_lord"],
                    analysis["lord_placed_in_house"],
                )
            except FileNotFoundError:
                # book index not built on this machine — degrade gracefully;
                # the LLM prompt handles missing references explicitly
                ref = ""
            if ref:
                references.append(f"--- References for house {house} ---\n{ref}")

    moon_lon = kundali_data["planets"]["Moon"]["longitude"]
    dasha = calculate_vimshottari_dasha(
        moon_lon, kundali_data["birth_details"]["date_of_birth"])
    gochar = analyze_transit_impact(
        kundali_data["planets"]["Moon"]["sign"], get_current_transits())

    return {
        "topics": identify_topics(user_question),
        "houses": houses,
        "gochar": gochar,
        "house_analyses": analyses,
        "book_references": "\n\n".join(references),
        "dasha": {
            "current_mahadasha": (
                {k: dasha["current_mahadasha"][k]
                 for k in ("planet", "start_date", "end_date")}
                if dasha["current_mahadasha"] else None),
            "current_antardasha": (
                dasha["current_mahadasha"]["current_antardasha"]
                if dasha["current_mahadasha"] else None),
            "birth_dasha_balance": dasha["birth_dasha"],
        },
        "navamsa": navamsa_data,
    }


def build_llm_input(user_question: str, kundali_data: dict,
                    navamsa_data: dict | None = None) -> dict:
    """Full {system, user} message pair for the interpretation LLM."""
    context = gather_question_context(user_question, kundali_data, navamsa_data)

    kundli_summary = {
        "lagna": kundali_data.get("ascendant"),
        "planets": kundali_data["planets"],
        "relevant_house_analyses": context["house_analyses"],
        "navamsa": context["navamsa"],
        "dasha": context["dasha"],
        "current_transits_from_moon": context["gochar"],
        "house_system": kundali_data.get("house_system"),
        "ayanamsha": kundali_data.get("ayanamsha_system"),
    }
    if kundali_data.get("note"):
        kundli_summary["note"] = kundali_data["note"]

    references = context["book_references"] or (
        "No matching classical references were retrieved for this question.")

    user_message = (
        f"USER QUESTION:\n{user_question}\n\n"
        f"KUNDLI DATA:\n{json.dumps(kundli_summary, indent=1, default=str)}\n\n"
        f"RETRIEVED CLASSICAL REFERENCES (BPHS Vol 1, with page numbers):\n"
        f"{references}"
    )
    return {"system": load_system_prompt(), "user": user_message,
            "context": context}


def interpret(user_question: str, kundali_data: dict,
              llm: "callable" = None, navamsa_data: dict | None = None) -> str:
    """End-to-end: assemble input and call the provided LLM.

    llm: callable(system_prompt: str, user_message: str) -> str.
    Kept pluggable so the API provider (Claude API, etc.) is a deployment
    choice, not a code dependency.
    """
    payload = build_llm_input(user_question, kundali_data, navamsa_data)
    if llm is None:
        raise ValueError(
            "No LLM callable provided. Pass llm=fn where "
            "fn(system_prompt, user_message) -> str (e.g. a Claude API call).")
    return llm(payload["system"], payload["user"])


if __name__ == "__main__":
    from kundali_calculator import generate_kundali
    from navamsa_calculator import calculate_navamsa, calculate_navamsa_houses

    chart = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090,
                             "Asia/Kolkata")
    d9 = calculate_navamsa_houses(calculate_navamsa(chart))

    payload = build_llm_input("kya mera career acha hoga", chart, d9)

    ctx = payload["context"]
    assert ctx["topics"] == ["career"] and ctx["houses"] == [10]
    h10 = ctx["house_analyses"][10]
    assert h10["house_sign"] == "Sagittarius"
    assert h10["planets_in_house"] == ["Sun", "Saturn"]
    assert h10["house_lord"] == "Jupiter" and h10["lord_placed_in_house"] == 4
    assert ctx["dasha"]["current_mahadasha"] is not None
    assert "sade_sati_status" in ctx["gochar"]
    assert "Interpretation Engine" in payload["system"]
    assert "USER QUESTION" in payload["user"]
    assert "RETRIEVED CLASSICAL REFERENCES" in payload["user"]

    print("topics:", ctx["topics"], "| houses:", ctx["houses"])
    print("house 10 analysis:", h10)
    print("current mahadasha:", ctx["dasha"]["current_mahadasha"])

    nt = generate_kundali("1990-01-01", "12:00", 28.6139, 77.2090,
                          "Asia/Kolkata", unknown_time=True)
    p2 = build_llm_input("kya mera career acha hoga", nt)
    assert p2["context"]["house_analyses"] == {}

    try:
        interpret("kya mera career acha hoga", chart)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    print("All interpretation-engine assertions passed.")
