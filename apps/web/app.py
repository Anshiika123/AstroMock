"""
app.py — Flask API for the Kundali generator.

POST /api/kundali orchestrates location_resolver + kundali_calculator.
All calculation logic lives in those modules; this layer only validates
input, wires the calls together, and shapes HTTP responses.

Run: flask run  (or: python app.py)
"""

import os
import re
from datetime import datetime

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from ashtakavarga_calculator import interpret_ashtakavarga_signals
from astro_advisor import DEEPEN_DEPTHS, DEPTHS, build_advisor_input, build_deepen_input
from career_advisor import build_career_input
from dasha_calculator import calculate_vimshottari_dasha
from horoscope_generator import (FOCUS_AREAS, GUIDANCE_SECTIONS, TIMEFRAMES,
                                 TONES, build_guidance_input)
from kundali_calculator import generate_kundali
from kundali_chart import render_north_indian_chart
from llm_provider import get_llm, required_key_name
from location_resolver import resolve_birth_location
from navamsa_calculator import calculate_navamsa, calculate_navamsa_houses
from topic_to_house_mapping import identify_topics
from transit_calculator import analyze_transit_impact, get_current_transits

app = Flask(__name__)


def _call_llm(llm, system_prompt: str, user_message: str) -> tuple[str | None, str | None]:
    """Call the LLM, degrading to a calm note on any failure instead of a
    raw exception (rate limit, network error, etc.) reaching the user.

    Returns (answer, note) — exactly one of the two is not None.
    """
    if llm is None:
        return None, (f"Interpretation LLM not configured — set "
                      f"{required_key_name()} to enable answers.")
    try:
        return llm(system_prompt, user_message), None
    except Exception as e:
        return None, (f"The reading service is temporarily unavailable "
                      f"({type(e).__name__}). Please try again in a moment.")


@app.get("/")
def index():
    return render_template("index.html")

# Geocoder error codes that are the service's fault, not the user's → 502.
_UPSTREAM_ERROR_CODES = {"GEOCODER_UNAVAILABLE", "GEOCODER_ERROR"}


# API routes must ALWAYS answer JSON — never Flask's HTML error pages
# (the frontend does res.json() and would show "<!doctype ... is not
# valid JSON" otherwise).
@app.errorhandler(HTTPException)
def _http_error(e):
    if request.path.startswith("/api/"):
        message = e.description
        if e.code == 404:
            message = (f"Unknown API route: {request.path}. If you just "
                       "updated app.py, restart the Flask server.")
        return jsonify({"success": False, "errors": [message]}), e.code
    return e


@app.errorhandler(Exception)
def _server_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False,
                        "errors": [f"Server error: {type(e).__name__}: {e}"]}), 500
    raise e


def _validation_errors(payload: dict) -> list[str]:
    """Validate the request payload; returns a list of problems (empty = ok)."""
    errors = []

    date_of_birth = payload.get("date_of_birth")
    if not isinstance(date_of_birth, str):
        errors.append("date_of_birth is required (string, YYYY-MM-DD).")
    else:
        try:
            datetime.strptime(date_of_birth, "%Y-%m-%d")
        except ValueError:
            errors.append(f"date_of_birth '{date_of_birth}' is not a valid YYYY-MM-DD date.")

    time_of_birth = payload.get("time_of_birth")
    if not isinstance(time_of_birth, str):
        errors.append("time_of_birth is required (string, HH:MM, 24-hour).")
    else:
        try:
            datetime.strptime(time_of_birth, "%H:%M")
        except ValueError:
            errors.append(f"time_of_birth '{time_of_birth}' is not a valid HH:MM time (24-hour).")

    place_of_birth = payload.get("place_of_birth")
    if not isinstance(place_of_birth, str) or not place_of_birth.strip():
        errors.append("place_of_birth is required (non-empty string).")

    if not isinstance(payload.get("unsure_of_time", False), bool):
        errors.append("unsure_of_time must be a boolean.")

    return errors


@app.post("/api/kundali")
def kundali():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"success": False, "errors": ["Request body must be JSON."]}), 400

    errors = _validation_errors(payload)
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    location = resolve_birth_location(
        payload["place_of_birth"], payload["date_of_birth"]
    )
    if not location["success"]:
        status = 502 if location["error"]["code"] in _UPSTREAM_ERROR_CODES else 404
        return jsonify(location), status

    chart = generate_kundali(
        date_of_birth=payload["date_of_birth"],
        time_of_birth=payload["time_of_birth"],
        latitude=location["latitude"],
        longitude=location["longitude"],
        timezone_str=location["timezone_str"],
        unknown_time=payload.get("unsure_of_time", False),
    )

    navamsa = calculate_navamsa(chart)
    dasha = calculate_vimshottari_dasha(
        chart["planets"]["Moon"]["longitude"], payload["date_of_birth"]
    )
    transits = get_current_transits()
    gochar = analyze_transit_impact(chart["rashi"]["sign"], transits)
    signals = interpret_ashtakavarga_signals(chart, transits)
    chart_svg = None
    navamsa_chart_svg = None
    if chart["ascendant"] is not None:
        chart_svg = render_north_indian_chart(
            chart["planets"], chart["ascendant"]["sign"], "D-1",
            ascendant_degree=chart["ascendant"]["degree_in_sign"],
        )
        navamsa = calculate_navamsa_houses(navamsa)
        d9_planets = {
            name: {**data, "retrograde": chart["planets"][name]["retrograde"]}
            for name, data in navamsa.items()
            if name != "ascendant_navamsa_sign"
        }
        navamsa_chart_svg = render_north_indian_chart(
            d9_planets, navamsa["ascendant_navamsa_sign"], "D-9 Navamsa"
        )

    return jsonify({
        "success": True,
        "location": {
            "resolved_address": location["resolved_address"],
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "timezone": location["timezone_str"],
        },
        "warnings": location["warnings"],
        "kundali": chart,
        "navamsa": navamsa,
        "dasha": dasha,
        "gochar": gochar,
        "signals": signals,
        "chart_svg": chart_svg,
        "navamsa_chart_svg": navamsa_chart_svg,
    })


def _split_guidance_sections(text: str) -> dict | None:
    """Split a guidance reading into its four sections by heading.

    Tolerates markdown dressing around headings (###, **, trailing colon).
    Returns None if any heading is missing, out of order, or empty — the
    frontend then falls back to showing the raw text.
    """
    positions = []
    for heading in GUIDANCE_SECTIONS:
        m = re.search(rf"(?im)^[#*\s]*{re.escape(heading)}[:*\s]*$", text)
        if not m:
            return None
        positions.append((m.start(), m.end(), heading))
    if positions != sorted(positions):
        return None
    sections = {}
    for i, (_start, end, heading) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        sections[heading] = text[end:nxt].strip().strip("*").strip()
    return sections if all(sections.values()) else None


@app.post("/api/horoscope")
def horoscope():
    """"Your Guidance" reading: birth details + timeframe/tone/focus.

    Returns the reading split into the four guidance sections (plus the
    raw text); with no LLM configured, returns the grounded transit facts
    and a note instead, so the frontend can still render something honest.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"success": False, "errors": ["Request body must be JSON."]}), 400

    errors = _validation_errors(payload)
    timeframe = payload.get("timeframe", "today")
    tone = payload.get("tone", "gentle")
    focus = payload.get("focus", "overall")
    if timeframe not in TIMEFRAMES:
        errors.append(f"timeframe must be one of {sorted(TIMEFRAMES)}.")
    if tone not in TONES:
        errors.append(f"tone must be one of {sorted(TONES)}.")
    if focus not in FOCUS_AREAS:
        errors.append(f"focus must be one of {sorted(FOCUS_AREAS)}.")
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    location = resolve_birth_location(
        payload["place_of_birth"], payload["date_of_birth"]
    )
    if not location["success"]:
        status = 502 if location["error"]["code"] in _UPSTREAM_ERROR_CODES else 404
        return jsonify(location), status

    chart = generate_kundali(
        date_of_birth=payload["date_of_birth"],
        time_of_birth=payload["time_of_birth"],
        latitude=location["latitude"],
        longitude=location["longitude"],
        timezone_str=location["timezone_str"],
        unknown_time=payload.get("unsure_of_time", False),
    )

    gi = build_guidance_input(chart, timeframe, tone, focus)
    llm = get_llm()
    guidance, note = _call_llm(llm, gi["system"], gi["user"])

    return jsonify({
        "success": True,
        "timeframe": timeframe,
        "tone": tone,
        "focus": focus,
        "rashi": chart["rashi"],
        "guidance": guidance,
        "sections": _split_guidance_sections(guidance) if guidance else None,
        "llm_configured": llm is not None,
        "note": note,
        "facts": gi["context"],
        "warnings": location["warnings"],
    })


def _build_ask_payload(question: str, chart: dict, depth: str,
                       navamsa: dict) -> dict:
    """Route to the career-specialist prompt for pure career questions,
    the general advisor prompt otherwise. Both return {system, user,
    context, signals} — signals is None for the career pipeline (its
    Ashtakavarga read is folded into context["active_periods"] instead)."""
    if identify_topics(question) == ["career"]:
        payload = build_career_input(question, chart, depth, navamsa)
        payload["signals"] = None
        return payload
    return build_advisor_input(question, chart, depth, navamsa)


def _resolve_chart(payload: dict):
    """geocode -> kundali -> navamsa, shared by /api/ask and /api/deepen.

    Returns (chart, navamsa, warnings) on success, or (error_response,
    status, None) on geocoding failure — caller checks len() == 3.
    """
    location = resolve_birth_location(
        payload["place_of_birth"], payload["date_of_birth"]
    )
    if not location["success"]:
        status = 502 if location["error"]["code"] in _UPSTREAM_ERROR_CODES else 404
        return jsonify(location), status, None

    chart = generate_kundali(
        date_of_birth=payload["date_of_birth"],
        time_of_birth=payload["time_of_birth"],
        latitude=location["latitude"],
        longitude=location["longitude"],
        timezone_str=location["timezone_str"],
        unknown_time=payload.get("unsure_of_time", False),
    )
    navamsa = calculate_navamsa(chart)
    if chart["ascendant"] is not None:
        navamsa = calculate_navamsa_houses(navamsa)
    return chart, navamsa, location["warnings"]


@app.post("/api/ask")
def ask():
    """Q&A endpoint: question + birth details -> explainable advisor answer.

    Pipeline: geocode -> kundali -> navamsa -> question routed to the
    career specialist or general advisor prompt (D-1 + D-9 support +
    dasha + transits + interpreted Ashtakavarga signals) -> LLM (if
    configured). `depth` controls how many reasoning layers come back:
    "normal" (quick), "deep", or "technical". Without an API key the
    response still carries lagna/rashi/context/signals, with answer=null.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"success": False, "errors": ["Request body must be JSON."]}), 400

    errors = _validation_errors(payload)
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        errors.append("question is required (non-empty string).")
    depth = payload.get("depth", "normal")
    if depth not in DEPTHS:
        errors.append(f"depth must be one of {DEPTHS}.")
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    chart, navamsa, warnings = _resolve_chart(payload)
    if navamsa is None:
        return chart, navamsa  # (error_response, status)

    advisor_payload = _build_ask_payload(question.strip(), chart, depth, navamsa)
    llm = get_llm()
    answer, note = _call_llm(llm, advisor_payload["system"], advisor_payload["user"])

    return jsonify({
        "success": True,
        "question": question.strip(),
        "depth": depth,
        "lagna": chart["lagna"],
        "rashi": chart["rashi"],
        "answer": answer,
        "llm_configured": llm is not None,
        "note": note,
        "context": advisor_payload.get("context"),
        "signals": advisor_payload.get("signals"),
        "warnings": warnings,
    })


@app.post("/api/deepen")
def deepen():
    """Expand a previous "normal"-depth /api/ask answer into "deep" or
    "technical" — the "Go deeper" button. Needs the original question and
    the answer text already shown to the user, so the deeper reading
    stays anchored to what the user already read."""
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"success": False, "errors": ["Request body must be JSON."]}), 400

    errors = _validation_errors(payload)
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        errors.append("question is required (non-empty string).")
    previous_answer = payload.get("previous_answer")
    if not isinstance(previous_answer, str) or not previous_answer.strip():
        errors.append("previous_answer is required (non-empty string).")
    requested_depth = payload.get("requested_depth", "deep")
    if requested_depth not in DEEPEN_DEPTHS:
        errors.append(f"requested_depth must be one of {DEEPEN_DEPTHS}.")
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    chart, navamsa, warnings = _resolve_chart(payload)
    if navamsa is None:
        return chart, navamsa  # (error_response, status)

    deepen_payload = build_deepen_input(
        question.strip(), previous_answer.strip(), chart, requested_depth, navamsa)
    llm = get_llm()
    answer, note = _call_llm(llm, deepen_payload["system"], deepen_payload["user"])

    return jsonify({
        "success": True,
        "question": question.strip(),
        "requested_depth": requested_depth,
        "answer": answer,
        "llm_configured": llm is not None,
        "note": note,
        "context": deepen_payload.get("context"),
        "warnings": warnings,
    })


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
