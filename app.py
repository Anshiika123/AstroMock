"""
app.py — Flask API for the Kundali generator.

POST /api/kundali orchestrates location_resolver + kundali_calculator.
All calculation logic lives in those modules; this layer only validates
input, wires the calls together, and shapes HTTP responses.

Run: flask run  (or: python app.py)
"""

from datetime import datetime

from flask import Flask, jsonify, request

from kundali_calculator import generate_kundali
from location_resolver import resolve_birth_location

app = Flask(__name__)

# Geocoder error codes that are the service's fault, not the user's → 502.
_UPSTREAM_ERROR_CODES = {"GEOCODER_UNAVAILABLE", "GEOCODER_ERROR"}


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
    })


if __name__ == "__main__":
    app.run(debug=True)
