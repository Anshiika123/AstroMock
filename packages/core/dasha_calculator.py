"""
dasha_calculator.py — Vimshottari Mahadasha / Antardasha calculation.

Derived entirely from the Moon's sidereal longitude at birth (its nakshatra
and how far through it the Moon had traveled) — no swisseph calls needed.

Conventions:
- 1 year = 365.25 days (solar year, the common convention in Vimshottari
  software; some traditions use 360-day years — dates will differ slightly).
- Balance of the first Mahadasha = (fraction of nakshatra NOT yet traversed
  at birth) x that lord's full Mahadasha duration.
- Antardasha sequence within a Mahadasha starts from the Mahadasha lord
  itself; each Antardasha = md_years * ad_planet_years / 120.
"""

from datetime import date, datetime, timedelta

from kundali_calculator import NAKSHATRAS, NAKSHATRA_SPAN

DAYS_PER_YEAR = 365.25

# Fixed Vimshottari order and durations (sums to 120 years).
DASHA_ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu",
               "Jupiter", "Saturn", "Mercury"]
DASHA_YEARS = {"Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
               "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17}
TOTAL_CYCLE_YEARS = 120


# ---------------------------------------------------------------------------
# Helpers (independently testable)
# ---------------------------------------------------------------------------

def nakshatra_position(moon_longitude: float) -> dict:
    """Nakshatra index/name and the fraction of it traversed at birth."""
    lon = moon_longitude % 360.0
    index = int(lon // NAKSHATRA_SPAN)
    traversed = (lon % NAKSHATRA_SPAN) / NAKSHATRA_SPAN
    return {
        "index": index,
        "name": NAKSHATRAS[index],
        "degrees_traversed": round(lon % NAKSHATRA_SPAN, 4),
        "fraction_traversed": traversed,
    }


def ruling_planet(nakshatra_index: int) -> str:
    """Vimshottari lord of a nakshatra: the 9-planet cycle repeats 3 times."""
    return DASHA_ORDER[nakshatra_index % 9]


def dasha_balance_years(fraction_traversed: float, planet: str) -> float:
    """Years of the first Mahadasha remaining at birth."""
    return (1.0 - fraction_traversed) * DASHA_YEARS[planet]


def years_to_ymd(years: float) -> dict:
    """Human-readable breakdown of a duration in years (12x30.4375d months)."""
    whole_years = int(years)
    rem_days = (years - whole_years) * DAYS_PER_YEAR
    months = int(rem_days // (DAYS_PER_YEAR / 12))
    days = int(rem_days % (DAYS_PER_YEAR / 12))
    return {"years": whole_years, "months": months, "days": days}


def _add_years(start: date, years: float) -> date:
    return start + timedelta(days=years * DAYS_PER_YEAR)


def mahadasha_sequence(birth_date: date, first_planet: str,
                       balance_years: float) -> list:
    """Mahadashas from birth until at least 120 years are covered.

    First entry is the partial (balance) period of the birth nakshatra's
    lord; subsequent entries carry full durations in fixed cyclic order.
    """
    # Boundaries are computed from cumulative offsets against the birth
    # date (not by chaining date additions): date + timedelta ignores the
    # fractional day, so chaining would accumulate ~1 day of drift per step.
    sequence = []
    order_index = DASHA_ORDER.index(first_planet)
    covered = 0.0
    duration = balance_years
    while covered < TOTAL_CYCLE_YEARS:
        planet = DASHA_ORDER[order_index % 9]
        sequence.append({
            "planet": planet,
            "start_date": _add_years(birth_date, covered).isoformat(),
            "end_date": _add_years(birth_date, covered + duration).isoformat(),
            "duration_years": round(duration, 4),
        })
        covered += duration
        order_index += 1
        duration = float(DASHA_YEARS[DASHA_ORDER[order_index % 9]])
    return sequence


def antardasha_breakdown(md_planet: str, md_start: date) -> list:
    """All 9 Antardashas of a full Mahadasha, with calendar dates.

    The sequence starts from the Mahadasha lord itself and follows the
    fixed cyclic order; each Antardasha lasts md_years * ad_years / 120.
    """
    # Cumulative offsets from md_start (see mahadasha_sequence for why).
    md_years = DASHA_YEARS[md_planet]
    start_index = DASHA_ORDER.index(md_planet)
    periods = []
    covered = 0.0
    for i in range(9):
        ad_planet = DASHA_ORDER[(start_index + i) % 9]
        ad_years = md_years * DASHA_YEARS[ad_planet] / TOTAL_CYCLE_YEARS
        periods.append({
            "planet": ad_planet,
            "start_date": _add_years(md_start, covered).isoformat(),
            "end_date": _add_years(md_start, covered + ad_years).isoformat(),
            "duration_years": round(ad_years, 4),
        })
        covered += ad_years
    return periods


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def calculate_vimshottari_dasha(moon_longitude: float, date_of_birth: str,
                                as_of: str | None = None) -> dict:
    """Vimshottari Dasha timeline from the Moon's sidereal longitude at birth.

    Args:
        moon_longitude: sidereal Moon longitude 0-360 (from generate_kundali).
        date_of_birth: "YYYY-MM-DD".
        as_of: reference date for "current" Mahadasha/Antardasha
            ("YYYY-MM-DD"); defaults to today. Exposed for testability.

    Returns dict with:
        moon_nakshatra, birth_dasha (lord + balance), mahadashas (>=120y),
        current_mahadasha (with antardashas + current_antardasha), as_of.
    """
    birth = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
    reference = (datetime.strptime(as_of, "%Y-%m-%d").date()
                 if as_of else date.today())

    position = nakshatra_position(moon_longitude)
    lord = ruling_planet(position["index"])
    balance = dasha_balance_years(position["fraction_traversed"], lord)
    sequence = mahadasha_sequence(birth, lord, balance)

    current_md = next(
        (md for md in sequence
         if md["start_date"] <= reference.isoformat() < md["end_date"]),
        None,
    )

    current_block = None
    if current_md is not None:
        # NOTE: for the FIRST (balance) Mahadasha the sub-periods below are
        # computed from the notional full-period start (its antardashas that
        # fell before birth simply lie before the birth date).
        md_full_start = (
            _add_years(birth, -(DASHA_YEARS[current_md["planet"]] -
                                current_md["duration_years"]))
            if current_md is sequence[0]
            else datetime.strptime(current_md["start_date"], "%Y-%m-%d").date()
        )
        antardashas = antardasha_breakdown(current_md["planet"], md_full_start)
        current_ad = next(
            (ad for ad in antardashas
             if ad["start_date"] <= reference.isoformat() < ad["end_date"]),
            None,
        )
        current_block = {
            **current_md,
            "antardashas": antardashas,
            "current_antardasha": current_ad,
        }

    return {
        "moon_nakshatra": {
            "name": position["name"],
            "degrees_traversed": position["degrees_traversed"],
            "fraction_traversed": round(position["fraction_traversed"], 6),
        },
        "birth_dasha": {
            "planet": lord,
            "balance_years": round(balance, 4),
            "balance_ymd": years_to_ymd(balance),
        },
        "mahadashas": sequence,
        "current_mahadasha": current_block,
        "as_of": reference.isoformat(),
    }


# ---------------------------------------------------------------------------
# Test — Moon 235.7022 (Scorpio -> Jyeshtha), DOB 2004-09-21
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = calculate_vimshottari_dasha(235.7022, "2004-09-21")

    nak = result["moon_nakshatra"]
    birth_dasha = result["birth_dasha"]
    print(f"Moon nakshatra : {nak['name']} "
          f"({nak['degrees_traversed']}° traversed, "
          f"{nak['fraction_traversed']:.2%})")
    bal = birth_dasha["balance_ymd"]
    print(f"Birth Mahadasha: {birth_dasha['planet']} — balance "
          f"{bal['years']}y {bal['months']}m {bal['days']}d "
          f"({birth_dasha['balance_years']} years)")
    print("-" * 64)
    for md in result["mahadashas"]:
        print(f"{md['planet']:<8} {md['start_date']}  ->  {md['end_date']} "
              f"({md['duration_years']:>7.4f} y)")
    print("-" * 64)
    cur = result["current_mahadasha"]
    print(f"As of {result['as_of']}: {cur['planet']} Mahadasha "
          f"({cur['start_date']} -> {cur['end_date']})")
    print("Antardashas:")
    for ad in cur["antardashas"]:
        marker = "  <-- current" if ad == cur["current_antardasha"] else ""
        print(f"  {cur['planet']}-{ad['planet']:<8} {ad['start_date']} -> "
              f"{ad['end_date']} ({ad['duration_years']:.4f} y){marker}")

    # --- Assertions (hand-verified numbers) ---
    # Jyeshtha index 17, lord = DASHA_ORDER[17 % 9 = 8] = Mercury
    assert nak["name"] == "Jyeshtha"
    assert birth_dasha["planet"] == "Mercury"
    # traversed = 235.7022 - 226.66667 = 9.03553°; fraction 0.677665
    # balance = (1 - 0.677665) * 17 = 5.4797 years
    assert abs(birth_dasha["balance_years"] - 5.4797) < 0.001

    seq = result["mahadashas"]
    assert [md["planet"] for md in seq[:4]] == ["Mercury", "Ketu", "Venus", "Sun"]
    # Mercury balance ends ~2010-03; Ketu 7y ends ~2017-03; Venus 20y to ~2037-03
    assert seq[1]["start_date"].startswith("2010-03")
    assert seq[2]["start_date"].startswith("2017-03")
    assert seq[2]["end_date"].startswith("2037-03")
    # coverage: at least 120 years from birth
    total = sum(md["duration_years"] for md in seq)
    assert total >= 120

    # Sanity check (user-confirmed): Venus Mahadasha active in July 2026,
    # and independently: Ve-Ve 3.33y + Ve-Su 1y + Ve-Mo 1.67y + Ve-Ma 1.17y
    # ends ~2024-05, so July 2026 falls in Venus-Rahu Antardasha (3y).
    fixed = calculate_vimshottari_dasha(235.7022, "2004-09-21", as_of="2026-07-11")
    cur_fixed = fixed["current_mahadasha"]
    assert cur_fixed["planet"] == "Venus", cur_fixed["planet"]
    assert cur_fixed["current_antardasha"]["planet"] == "Rahu"
    # antardasha durations of a Mahadasha must sum to its full duration
    # (durations are rounded to 4 dp, so allow a small tolerance)
    assert abs(sum(a["duration_years"] for a in cur_fixed["antardashas"]) - 20) < 0.01
    # last antardasha must end when the Mahadasha ends (no cumulative drift)
    assert cur_fixed["antardashas"][-1]["end_date"] == cur_fixed["end_date"]
    # consecutive mahadashas must tile perfectly (no gaps/overlaps)
    for a, b in zip(seq, seq[1:]):
        assert a["end_date"] == b["start_date"]

    # Balance-period edge: as_of inside the FIRST (partial) Mahadasha —
    # antardashas anchored to notional full start, current one must be found
    early = calculate_vimshottari_dasha(235.7022, "2004-09-21", as_of="2005-01-01")
    assert early["current_mahadasha"]["planet"] == "Mercury"
    assert early["current_mahadasha"]["current_antardasha"] is not None

    print("-" * 64)
    print("All dasha assertions passed.")
