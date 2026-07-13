"""
topic_to_house_mapping.py — Map life-area questions to Vedic houses.

Standard house significations used for question routing: a user question
("kya mera career acha hoga?") is scanned for topic keywords (English +
Hinglish) and mapped to the house(s) that govern that life area.

Matching is case-insensitive and word-boundary based, so "kaam" matches
"kaam" but not "kaamyabi". Multiple topics in one question return the
union of their houses.
"""

import re

# topic -> (keywords, houses). Houses follow standard Vedic significations.
TOPIC_HOUSE_MAP = {
    "career":      (["career", "job", "profession", "naukri", "kaam"], [10]),
    "marriage":    (["marriage", "shaadi", "spouse", "life partner"], [7]),
    "wealth":      (["money", "wealth", "paisa", "finance"], [2, 11]),
    "health":      (["health", "sehat", "illness", "bimari"], [6, 1]),
    "education":   (["education", "padhai", "studies"], [4, 5]),
    "children":    (["children", "santan", "kids"], [5]),
    "family":      (["family", "parivar", "mother", "father"], [4, 9]),
    "nature_self": (["personality", "nature", "swabhav"], [1]),
}


def identify_topics(user_question: str) -> list[str]:
    """Topic names whose keywords appear in the question (word-boundary)."""
    text = user_question.lower()
    matched = []
    for topic, (keywords, _houses) in TOPIC_HOUSE_MAP.items():
        if any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in keywords):
            matched.append(topic)
    return matched


def identify_relevant_houses(user_question: str) -> list[int]:
    """House numbers relevant to a life-area question.

    Case-insensitive, English + Hinglish keywords. Returns sorted unique
    house numbers; empty list if nothing matches (caller handles fallback).
    """
    houses = set()
    for topic in identify_topics(user_question):
        houses.update(TOPIC_HOUSE_MAP[topic][1])
    return sorted(houses)


if __name__ == "__main__":
    # Requested primary test
    result = identify_relevant_houses("kya mera career acha hoga")
    print(f'"kya mera career acha hoga" -> {result}')
    assert result == [10]

    # English, case-insensitive
    assert identify_relevant_houses("Will my MARRIAGE be happy?") == [7]
    # Hinglish
    assert identify_relevant_houses("meri shaadi kab hogi") == [7]
    assert identify_relevant_houses("paisa kab aayega") == [2, 11]
    assert identify_relevant_houses("meri sehat kaisi rahegi") == [1, 6]
    assert identify_relevant_houses("bachon ki padhai") == [4, 5]
    # multiple topics -> union
    assert identify_relevant_houses("job aur paisa dono ke bare mein batao") == [2, 10, 11]
    # word-boundary: "kaam" must not match inside "kaamyabi"
    assert identify_relevant_houses("kaamyabi milegi?") == []
    assert identify_relevant_houses("mera kaam kaisa chalega") == [10]
    # multi-word keyword
    assert identify_relevant_houses("when will I meet my life partner") == [7]
    # no match -> empty (fallback handled by caller)
    assert identify_relevant_houses("aaj mausam kaisa hai") == []
    # topics helper
    assert identify_topics("career aur santan") == ["career", "children"]

    print("All topic-mapping assertions passed.")
