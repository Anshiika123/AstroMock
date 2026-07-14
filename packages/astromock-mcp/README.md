# astromock-mcp

A standalone [MCP](https://modelcontextprotocol.io) server that exposes Vedic
astrology calculations as reusable tools. Any MCP client — Claude Desktop, a
chatbot, the ASTRO-MOCK web app, or future projects — can consume these tools.

Calculations use the **sidereal zodiac** with **Lahiri ayanamsha**,
**Whole Sign houses** and **mean lunar nodes**, powered by the Swiss Ephemeris
(`pyswisseph`, built-in Moshier ephemeris — no extra data files needed).

## Available tools

### `calculate_kundali`
Calculates the D-1 (Rashi) birth chart. Returns the ascendant (lagna) and all
nine grahas (Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn, Rahu, Ketu)
with sign, degree, nakshatra, pada, Whole Sign house and retrograde status.

### `calculate_navamsa`
Calculates the D-9 (Navamsa) divisional chart. Returns each planet's navamsa
sign and house from the navamsa lagna.

### `calculate_dasha`
Vimshottari Dasha timeline: Mahadashas covering 120 years from birth with
calendar dates, the birth-time balance, and the current Mahadasha's full
Antardasha breakdown (active one included). Optional `as_of` (YYYY-MM-DD)
overrides "today". Use for any timing question.

### `get_current_transits`
Gochar: sidereal transit signs of all 9 grahas for today (or optional
`target_date`). Pass the optional `moon_sign` (the `rashi.sign` from
`calculate_kundali`) to also get each planet's house counted from the Moon
and the `sade_sati_status` flag (Saturn in 12th/1st/2nd from the Moon).

### `get_question_context`
One-shot context for a life-area question (English or Hinglish): routes the
question to its Vedic houses (career/naukri → 10, marriage/shaadi → 7,
wealth/paisa → 2+11, health/sehat → 1+6, education/padhai → 4+5,
children/santan → 5, family/parivar → 4+9, personality/swabhav → 1),
analyzes each house in the native's chart (sign, occupant planets, house
lord, lord's placement) and retrieves the most relevant BPHS passages (with
page numbers) from the bundled index (`data/book_index.json`). Takes the
birth-data fields plus `question`.

### `generate_horoscope`
Everything needed to write a transit-based horoscope for a natal Moon sign,
for one of three timeframes: `today` (Moon + Sun aspect, ~100 words),
`2weeks` (Sun/Mercury/Venus with upcoming sign changes, ~200 words),
`6months` (Jupiter/Saturn/Rahu/Ketu with Sade Sati, ~300 words). Returns
the filtered transit facts, relevant BPHS passages, and a ready-to-use
`system_prompt` + `suggested_prompt`. **The server does not call an LLM** —
the client writes the horoscope text: Claude Desktop's model follows the
returned prom