"""Gochar (transits) — thin adapter over astromock-core.

Core's transit_calculator supplies the math; this module keeps the MCP
tool's response shape (date + transits, optional Moon-sign analysis).
"""

from datetime import datetime, timezone

from kundali_calculator import SIGNS
from transit_calculator import SADE_SATI_HOUSES  # noqa: F401  (re-export)
from transit_calculator import get_current_transits as current_transit_signs
from transit_calculator import analyze_transit_impact, house_from_moon


def get_current_transits(
    moon_sign: str | None = None,
    target_date: str | None = None,
) -> dict:
    """MCP entry point: transits, optionally analyzed from a natal Moon sign.

    Returns {"date", "transits": {planet: sign}} without moon_sign, or
    {"date", "moon_sign", "transits": {planet: {"transit_sign",
    "house_from_moon"}}, "sade_sati_status": bool} with it.
    """
    signs = current_transit_signs(target_date)
    resolved_date = target_date or datetime.now(timezone.utc).date().isoformat()

    if moon_sign is None:
        return {"date": resolved_date, "transits": signs}

    if moon_sign not in SIGNS:
        raise ValueError(
            f"Unknown moon_sign: {moon_sign!r}. Expected one of {SIGNS}.")

    impact = analyze_transit_impact(moon_sign, signs)
    sade_sati = impact.pop("sade_sati_status")
    return {
        "date": resolved_date,
        "moon_sign": moon_sign,
        "transits": impact,
        "sade_sati_status": sade_sati,
    }
