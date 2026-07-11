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
from kundali_chart import render_north_indian_chart
from location_resolver import resolve_birth_location
from navamsa_calculator import calculate_navamsa

app = Flask(__name__)

_INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>AstroMock — Kundali Generator</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
  label { display: block; margin-top: 0.75rem; font-weight: 600; }
  input[type=text], input[type=date], input[type=time] { width: 100%; padding: 0.4rem; box-sizing: border-box; }
  button { margin-top: 1rem; padding: 0.5rem 1rem; }
  pre { background: #f4f4f4; padding: 1rem; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
</style>
</head>
<body>
  <h1>AstroMock — Kundali Generator</h1>
  <form id="kundali-form">
    <label>Date of birth <input type="date" name="date_of_birth" required></label>
    <label>Time of birth <input type="time" name="time_of_birth" required></label>
    <label>Place of birth <input type="text" name="place_of_birth" placeholder="Mumbai, India" required></label>
    <label><input type="checkbox" name="unsure_of_time"> Unsure of exact time</label>
    <button type="submit">Generate Kundali</button>
  </form>
  <div id="chart"></div>
  <pre id="result"></pre>
  <script>
    document.getElementById('kundali-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const payload = {
        date_of_birth: form.get('date_of_birth'),
        time_of_birth: form.get('time_of_birth'),
        place_of_birth: form.get('place_of_birth'),
        unsure_of_time: form.get('unsure_of_time') === 'on',
      };
      const chartEl = document.getElementById('chart');
      const resultEl = document.getElementById('result');
      chartEl.innerHTML = '';
      resultEl.textContent = 'Loading...';
      try {
        const res = await fetch('/api/kundali', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.success && data.chart_svg) {
          chartEl.innerHTML = data.chart_svg;
        }
        resultEl.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        resultEl.textContent = 'Request failed: ' + err;
      }
    });
  </script>
</body>
</html>
"""


@app.get("/")
def index():
    return _INDEX_HTML

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

    chart_svg = None if chart.get("ascendant") is None else render_north_indian_chart(chart)

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
        "navamsa": calculate_navamsa(chart),
        "chart_svg": chart_svg,
    })


if __name__ == "__main__":
    app.run(debug=True)
