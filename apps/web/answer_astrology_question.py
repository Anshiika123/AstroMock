"""
answer_astrology_question.py — End-to-end Q&A over a kundali.

Pipeline: user question -> relevant house(s) (topic_to_house_mapping)
-> per-house chart facts (house_analyzer) -> classical reference text
(book_retriever) -> one prompt -> LLM (via llm_provider) -> conversational
answer.

Requires whichever API key llm_provider.get_interpretation() needs for
the currently selected LLM_PROVIDER (see llm_provider.py); everything
before the final call is offline.
"""

from book_retriever import get_relevant_book_context
from house_analyzer import analyze_house
from llm_provider import get_interpretation
from topic_to_house_mapping import TOPIC_HOUSE_MAP, identify_relevant_houses

_COMMON_TOPICS = ", ".join(TOPIC_HOUSE_MAP.keys())

FALLBACK_MESSAGE = (
    "Mujhe samajh nahi aaya aapka sawaal kis life-area ke baare mein hai. "
    "Thoda rephrase karke poochhiye, ya in common topics mein se kisi ke "
    f"baare mein poochhiye: {_COMMON_TOPICS}. "
    "For example: 'kya mera career acha hoga', 'meri shaadi kab hogi', "
    "'paisa kab aayega'."
)


def gather_house_analyses(kundali_data: dict, houses: list[int]) -> dict[int, dict]:
    """analyze_house() for each matched house, keyed by house number."""
    return {h: analyze_house(kundali_data, h) for h in houses}


def gather_book_context(analyses: dict[int, dict]) -> str:
    """Combined Bhava Adhyaya passages for all matched houses.

    Falls back to a placeholder note if the book index hasn't been built
    yet (see book_retriever.py one-time setup) or nothing matches.
    """
    sections = []
    for house, a in analyses.items():
        try:
            ctx = get_relevant_book_context(
                house, a["planets_in_house"], a["house_lord"],
                a["lord_placed_in_house"],
            )
        except FileNotFoundError:
            return "(reference text unavailable — book index not built yet)"
        if ctx:
            sections.append(ctx)
    return "\n\n".join(sections) or "(no directly relevant passage found)"


def build_prompt(user_question: str, analyses: dict[int, dict],
                 book_context: str) -> str:
    """Assemble the single-shot prompt sent to Claude."""
    fact_lines = []
    for house, a in analyses.items():
        planets = (", ".join(a["planets_in_house"])
                   if a["planets_in_house"] else "no planets (empty house)")
        fact_lines.append(
            f"- House {house} ({a['house_sign']}) contains: {planets}\n"
            f"- Lord of this house is {a['house_lord']}, currently placed "
            f"in house {a['lord_placed_in_house']}"
        )
    facts = "\n".join(fact_lines)

    return (
        f"User's question: {user_question}\n"
        f"\n"
        f"Relevant birth chart facts:\n"
        f"{facts}\n"
        f"\n"
        f"Reference text from classical text (Bhava Adhyaya):\n"
        f"{book_context}\n"
        f"\n"
        f"Based on the chart facts and reference text above, answer the "
        f"user's question in a warm, conversational way like an experienced "
        f"astrologer would. Explain the reasoning simply. Keep it to "
        f"150-200 words. Respond in Hinglish if the question was asked in "
        f"Hinglish."
    )


def answer_question(user_question: str, kundali_data: dict) -> str:
    """Answer a life-area question from a kundali via the configured LLM.

    Args:
        user_question: free-text question (English or Hinglish).
        kundali_data: output of generate_kundali() with known birth time.

    Returns:
        The astrologer-style answer, or a friendly fallback message when
        the question doesn't map to any known life area.

    Raises:
        ValueError: from analyze_house() if the chart has no ascendant.
        RuntimeError: from llm_provider if the configured API key is missing.
    """
    houses = identify_relevant_houses(user_question)
    if not houses:
        return FALLBACK_MESSAGE

    analyses = gather_house_analyses(kundali_data, houses)
    book_context = gather_book_context(analyses)
    prompt = build_prompt(user_question, analyses, book_context)

    return get_interpretation("", prompt)


# ---------------------------------------------------------------------------
# Test — "kya mera career acha hoga" with the reasoning chain shown
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from kundali_calculator import generate_kundali

    QUESTION = "kya mera career acha hoga"

    # Saharanpur, 2004-09-21 10:30 IST (chart verified in the app earlier).
    chart = generate_kundali("2004-09-21", "10:30",
                             29.9680, 77.5459, "Asia/Kolkata")

    # --- Intermediate values, so the reasoning chain can be verified ---
    houses = identify_relevant_houses(QUESTION)
    print(f"question            : {QUESTION!r}")
    print(f"matched houses      : {houses}")

    analyses = gather_house_analyses(chart, houses)
    for h, a in analyses.items():
        print(f"house {h:>2} sign       : {a['house_sign']}")
        print(f"house {h:>2} planets    : {a['planets_in_house'] or '(empty house)'}")
        print(f"house {h:>2} lord       : {a['house_lord']} -> "
              f"placed in house {a['lord_placed_in_house']}")

    book_context = gather_book_context(analyses)
    print("-" * 64)
    print("book context:")
    print(book_context)

    print("-" * 64)
    print("prompt sent to Claude:")
    print(build_prompt(QUESTION, analyses, book_context))

    # Fallback path must not hit the API at all
    assert answer_question("aaj mausam kaisa hai", chart) == FALLBACK_MESSAGE

    print("-" * 64)
    try:
        answer = answer_question(QUESTION, chart)
        print("LLM's answer:")
        print(answer)
    except RuntimeError as e:
        # missing/misconfigured API key for the selected LLM_PROVIDER
        print(f"SKIPPED API call: {e}")
