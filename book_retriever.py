"""
book_retriever.py — Retrieve relevant passages from the Bhava Adhyaya text.

Two parts:
1. One-time setup: `python book_retriever.py path/to/bhava_adhyaya.pdf`
   extracts the PDF paragraph-by-paragraph into book_index.json so the
   PDF is never re-parsed at request time.
   NOTE: the PDF is not in the project folder yet — drop it in and run
   the command above once. Requires: pip install pdfplumber
2. Runtime: get_relevant_book_context() scores indexed paragraphs against
   the house/planets/lord-placement in question and returns the best
   passages, most specific first, capped at ~1000 words.

Scoring (per paragraph, additive):
  +12 lord-placement scenario ("lord of the Nth ... in the Mth" or BPHS
      style "Nth lord ... in the Mth") — most specific possible match
  +5  house mention AND an occupant planet in the same paragraph
  +4  house mention (ordinal-house phrase, bare "in the Nth", or Sanskrit
      bhava name) — must outrank planet-only generic paragraphs
  +1  each occupant planet mentioned (English or Sanskrit name)
  +1  house lord mentioned at all
  -3  OCR-noisy paragraph (garbled-shloka fragments mixed into the chunk)
"""

import json
import re
import sys
from pathlib import Path

BOOK_INDEX_PATH = Path(__file__).parent / "book_index.json"
MAX_CONTEXT_WORDS = 1000
MIN_PARAGRAPH_WORDS = 8  # skip headings/page numbers while indexing

# English ordinals + Sanskrit bhava names per house.
HOUSE_TERMS = {
    1:  ["1st house", "first house", "lagna", "tanu bhava", "ascendant"],
    2:  ["2nd house", "second house", "dhana bhava"],
    3:  ["3rd house", "third house", "sahaja bhava"],
    4:  ["4th house", "fourth house", "sukha bhava", "bandhu bhava"],
    5:  ["5th house", "fifth house", "putra bhava"],
    6:  ["6th house", "sixth house", "ari bhava", "ripu bhava", "shatru bhava"],
    7:  ["7th house", "seventh house", "yuvati bhava", "kalatra bhava"],
    8:  ["8th house", "eighth house", "randhra bhava", "ayu bhava"],
    9:  ["9th house", "ninth house", "dharma bhava", "bhagya bhava"],
    10: ["10th house", "tenth house", "karma bhava", "dashama bhava"],
    11: ["11th house", "eleventh house", "labha bhava"],
    12: ["12th house", "twelfth house", "vyaya bhava"],
}

# English + common Sanskrit planet names.
PLANET_TERMS = {
    "Sun": ["sun", "surya", "ravi"],
    "Moon": ["moon", "chandra"],
    "Mars": ["mars", "mangal", "kuja"],
    "Mercury": ["mercury", "budha"],
    "Jupiter": ["jupiter", "guru", "brihaspati"],
    "Venus": ["venus", "shukra"],
    "Saturn": ["saturn", "shani"],
    "Rahu": ["rahu"],
    "Ketu": ["ketu"],
}

_ORDINALS = {1: ["1st", "first"], 2: ["2nd", "second"], 3: ["3rd", "third"],
             4: ["4th", "fourth"], 5: ["5th", "fifth"], 6: ["6th", "sixth"],
             7: ["7th", "seventh"], 8: ["8th", "eighth"], 9: ["9th", "ninth"],
             10: ["10th", "tenth"], 11: ["11th", "eleventh"],
             12: ["12th", "twelfth"]}


# ---------------------------------------------------------------------------
# One-time PDF extraction
# ---------------------------------------------------------------------------

def _extract_pages(pdf_path: str) -> list[tuple[int, str]]:
    """(page_number, text) pairs. Prefers pdftotext (fast, good with
    scanned books that carry an OCR text layer); falls back to pdfplumber."""
    import shutil
    import subprocess

    if shutil.which("pdftotext"):
        result = subprocess.run(["pdftotext", "-q", str(pdf_path), "-"],
                                capture_output=True, text=True, check=True)
        # pdftotext separates pages with form-feed characters
        return list(enumerate(result.stdout.split("\f"), start=1))

    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        return [(i, page.extract_text() or "")
                for i, page in enumerate(pdf.pages, start=1)]


def _normalize_ocr(text: str) -> str:
    """Common scanned-book OCR fixes, e.g. 'l0th' -> '10th' (letter l for 1)."""
    text = re.sub(r"\bl(\d)", r"1\1", text)          # l0th, l2th, l1th
    text = re.sub(r"\b(\d)[lI]\b", r"\g<1>1", text)  # 1l -> 11
    return text


def _is_junk_token(word: str) -> bool:
    """Heuristic for garbled-OCR tokens (mis-recognized Devanagari shlokas
    render as latin noise like 'qrt', 'fqi', 'llloll'). Keeps numbers and
    plausible English words; imperfect by design, errs on keeping."""
    core = word.strip(".,;:!?'\"()[]-–—").lower()
    if not core:
        return True
    if re.search(r"\d", core):
        return False  # verse numbers, years, degrees — keep
    if not re.fullmatch(r"[a-z'\-]+", core):
        return True   # mixed scripts / stray symbols
    if re.search(r"q(?!u)", core):
        return True   # q without u — classic Devanagari-OCR artifact
    if not re.search(r"[aeiouy]", core):
        return True   # no vowels
    if re.search(r"(.)\1\1", core):
        return True   # lll, eee — OCR stutter
    return False


def _strip_garbage_tokens(paragraph: str) -> str:
    """Remove garbled-OCR tokens so mixed shloka+translation chunks store
    only the readable translation text."""
    return " ".join(w for w in paragraph.split() if not _is_junk_token(w))


def _clean_fraction(paragraph: str) -> float:
    """Fraction of tokens that are not garbled-OCR junk."""
    words = paragraph.split()
    return sum(1 for w in words if not _is_junk_token(w)) / len(words)


def _is_mostly_english(paragraph: str) -> bool:
    """Index filter for OCR garbage (mis-recognized Sanskrit shlokas in
    scanned books): keep a paragraph only if >=65% of tokens are clean."""
    return _clean_fraction(paragraph) >= 0.65


def build_book_index(pdf_path: str, out_path: Path = BOOK_INDEX_PATH) -> int:
    """Extract the PDF into paragraph chunks and save as JSON. Run once.

    Returns the number of paragraphs indexed.
    """
    paragraphs = []
    for page_num, text in _extract_pages(pdf_path):
        # paragraphs = blocks separated by blank lines; join wrapped lines
        for block in re.split(r"\n\s*\n", _normalize_ocr(text)):
            paragraph = " ".join(line.strip() for line in block.splitlines())
            paragraph = re.sub(r"\s+", " ", paragraph).strip()
            paragraph = _strip_garbage_tokens(paragraph)
            if (len(paragraph.split()) >= MIN_PARAGRAPH_WORDS
                    and _is_mostly_english(paragraph)):
                paragraphs.append({"page": page_num, "text": paragraph})

    out_path.write_text(
        json.dumps({"source": str(pdf_path), "paragraphs": paragraphs},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return len(paragraphs)


def load_book_index(path: Path = BOOK_INDEX_PATH) -> list[dict]:
    """Load indexed paragraphs; raises with a helpful message if missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found. One-time setup required: put the "
            "Bhava Adhyaya PDF in the project folder and run "
            "`python book_retriever.py <path-to-pdf>` to build the index."
        )
    return json.loads(path.read_text(encoding="utf-8"))["paragraphs"]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _mentions_any(text_lower: str, terms: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(t)}\b", text_lower) for t in terms)


def _mentions_house(text_lower: str, house: int) -> bool:
    if _mentions_any(text_lower, HOUSE_TERMS[house]):
        return True
    # Classical translations (e.g. BPHS) usually say just "in the 10th"
    # without the word "house" — accept a bare ordinal after a preposition.
    ordinals = "|".join(_ORDINALS[house])
    return re.search(rf"\b(in|to|of|from|for) the ({ordinals})\b",
                     text_lower) is not None


def _mentions_lord_placement(text_lower: str, house: int, lord_house: int) -> bool:
    """Detect lord-placement scenarios in both common phrasings:
    'lord of the 10th ... in the 4th' and 'the 10th lord (placed) in the 4th'
    (the latter is BPHS translation style)."""
    h = "|".join(_ORDINALS[house])
    l = "|".join(_ORDINALS[lord_house])
    patterns = [
        rf"\blord of the ({h})\b.{{0,60}}?\bin the ({l})\b",
        rf"\b({h}) lord\b.{{0,60}}?\b(in|is in|be in|placed in|posited in)"
        rf" the ({l})\b",
    ]
    return any(re.search(p, text_lower) for p in patterns)


def score_paragraph(text: str, house_number: int, planets_in_house: list,
                    house_lord: str, lord_house: int) -> int:
    """Relevance score for one paragraph (see module docstring)."""
    lower = text.lower()
    score = 0
    house_hit = _mentions_house(lower, house_number)
    planet_hits = sum(
        1 for p in planets_in_house if _mentions_any(lower, PLANET_TERMS[p]))

    if _mentions_lord_placement(lower, house_number, lord_house):
        score += 12
    if house_hit and planet_hits:
        score += 5
    if house_hit:
        score += 4
    score += planet_hits
    if _mentions_any(lower, PLANET_TERMS[house_lord]):
        score += 1
    # demote chunks with garbled-OCR noise mixed in (they passed the 0.65
    # index filter but read badly); may push weak matches to exclusion
    if score > 0 and _clean_fraction(text) < 0.75:
        score -= 3
    return score


def get_relevant_book_context(house_number: int, planets_in_house: list,
                              house_lord: str, lord_house: int,
                              index_path: Path | None = None) -> str:
    """Combined relevant book text for a house analysis, best matches first.

    Empty string if the index has no relevant paragraphs. Total length is
    capped at ~MAX_CONTEXT_WORDS words; paragraphs are separated by blank
    lines and prefixed with their source page. index_path overrides the
    default index location (used by tests).
    """
    paragraphs = load_book_index(index_path or BOOK_INDEX_PATH)
    scored = []
    for i, para in enumerate(paragraphs):
        s = score_paragraph(para["text"], house_number, planets_in_house,
                            house_lord, lord_house)
        if s > 0:
            scored.append((s, i, para))
    # most specific first; stable tie-break by book order
    scored.sort(key=lambda t: (-t[0], t[1]))

    selected, words = [], 0
    for s, _i, para in scored:
        n = len(para["text"].split())
        if selected and words + n > MAX_CONTEXT_WORDS:
            break
        selected.append(f"[p.{para['page']}] {para['text']}")
        words += n
    return "\n\n".join(selected)


# ---------------------------------------------------------------------------
# CLI (one-time index build) + tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        count = build_book_index(sys.argv[1])
        print(f"Indexed {count} paragraphs -> {BOOK_INDEX_PATH.name}")
        sys.exit(0)

    # ---- Tests with a synthetic fixture (real PDF not yet available) ----
    fixture = {
        "source": "fixture",
        "paragraphs": [
            {"page": 1, "text": "The tenth house, also called Karma Bhava, "
                                "governs profession, karma and public standing "
                                "of the native in society."},
            {"page": 2, "text": "Saturn in the tenth house gives slow but "
                                "steady rise in career after initial struggle "
                                "and hard discipline in the profession."},
            {"page": 3, "text": "If the lord of the 10th is placed in the 4th, "
                                "the native earns through property, vehicles "
                                "or education near the homeland."},
            {"page": 4, "text": "The Moon in the fourth house makes the mind "
                                "attached to home comforts and the mother."},
            {"page": 5, "text": "Guru is the greatest benefic; Brihaspati "
                                "blesses wisdom, children and wealth wherever "
                                "he casts his aspect."},
            {"page": 6, "text": "Marriage matters are seen from the seventh "
                                "house and its lord, along with Venus."},
        ],
    }
    # IMPORTANT: fixture goes to its own file — never overwrite the real
    # book_index.json built from the actual book PDF.
    FIXTURE_PATH = Path("book_index_fixture.json")
    FIXTURE_PATH.write_text(json.dumps(fixture), encoding="utf-8")

    # Verified 1990 chart, house 10: Sagittarius, [Sun, Saturn], Jupiter in 4
    ctx = get_relevant_book_context(10, ["Sun", "Saturn"], "Jupiter", 4,
                                    index_path=FIXTURE_PATH)
    print(ctx)
    print("-" * 64)
    blocks = ctx.split("\n\n")
    # lord-of-10th-in-4th scenario must rank first (score 12)
    assert blocks[0].startswith("[p.3]"), blocks[0]
    # Saturn-in-tenth (house + occupant: 5+3+2=10) second
    assert blocks[1].startswith("[p.2]"), blocks[1]
    # plain tenth-house paragraph (3) before generic Jupiter mention (1)
    assert blocks[2].startswith("[p.1]") and blocks[3].startswith("[p.5]")
    # irrelevant paragraphs (4th-house Moon, 7th-house marriage) excluded
    assert "[p.4]" not in ctx and "[p.6]" not in ctx

    # empty house: no occupant planets, still retrieves house + lord text
    ctx_empty = get_relevant_book_context(7, [], "Venus", 1,
                                          index_path=FIXTURE_PATH)
    assert "[p.6]" in ctx_empty and "[p.2]" not in ctx_empty

    # no matches at all -> empty string
    assert get_relevant_book_context(8, [], "Mars", 8,
                                     index_path=FIXTURE_PATH) == ""

    # word cap respected
    assert len(ctx.split()) <= MAX_CONTEXT_WORDS + 60  # + page prefixes

    # scoring helper sanity: p.3 hits the lord-placement pattern (+12) and
    # "of the 10th" now also counts as a house mention (+4)
    assert score_paragraph(fixture["paragraphs"][2]["text"],
                           10, ["Sun", "Saturn"], "Jupiter", 4) == 16
    assert score_paragraph("nothing relevant here at all today my friend",
                           10, ["Sun"], "Jupiter", 4) == 0
    # noisy-OCR demotion: same relevant text drowned in garbled tokens
    noisy = ("qrt fqi wril " * 6) + "the 10th lord placed in the 4th house"
    clean = "If the 10th lord is placed in the 4th, gains come through land."
    assert score_paragraph(clean, 10, [], "Jupiter", 4) > \
        score_paragraph(noisy, 10, [], "Jupiter", 4)

    FIXTURE_PATH.unlink()  # tidy up
    print("All book-retriever assertions passed (synthetic fixture).")
    if not BOOK_INDEX_PATH.exists():
        print("NOTE: real index not built yet — run "
              "`python book_retriever.py <path-to-book.pdf>` once.")
