"""Question context — thin adapter over astromock-core.

Core supplies topic->house mapping (topic_to_house_mapping), Whole Sign
house analysis (house_analyzer) and classical retrieval (book_retriever,
including the shared book_index.json). This module assembles them into the
MCP tool's established one-shot response.
"""

from book_retriever import get_relevant_book_context  # noqa: F401 (re-export)
from house_analyzer import SIGN_LORDS, analyze_house, sign_of_house  # noqa: F401
from kundali_calculator import generate_kundali
from topic_to_house_mapping import (  # noqa: F401  (re-exports)
    TOPIC_HOUSE_MAP,
    identify_relevant_houses,
    identify_topics,
)


def get_question_context(
    question: str,
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone_str: str,
    unknown_time: bool = False,
) -> dict:
    """Everything the interpreter needs for one life-area question.

    Returns topics, mapped houses, per-house analysis (sign, occupants,
    lord, lord placement) and classical BPHS references with page numbers.
    House analysis is skipped for unknown_time charts (no ascendant).
    """
    kundali = generate_kundali(date_of_birth, time_of_birth, latitude,
                               longitude, timezone_str, unknown_time)
    houses = identify_relevant_houses(question)
    analyses = {}
    references = []
    if kundali["ascendant"] is not None:
        for house in houses:
            analysis = analyze_house(kundali, house)
            analyses[house] = analysis
            try:
                ref = get_relevant_book_context(
                    house, analysis["planets_in_house"],
                    analysis["house_lord"], analysis["lord_placed_in_house"])
            except FileNotFoundError:
                ref = ""  # index not built — degrade gracefully
            if ref:
                references.append(
                    f"--- References for house {house} ---\n{ref}")

    return {
        "question": question,
        "topics": identify_topics(question),
        "houses": houses,
        "lagna": kundali["lagna"],
        "rashi": kundali["rashi"],
        "house_analyses": analyses,
        "book_references": "\n\n".join(references) or (
            "No matching classical references were retrieved."),
        "note": kundali.get("note"),
    }
