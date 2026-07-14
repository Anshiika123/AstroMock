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

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from dasha_calculator import calculate_vimshottari_dasha
from horoscope_generator import (FOCUS_AREAS, GUIDANCE_SECTIONS, TIMEFRAMES,
                                 TONES, build_guidance_input)
from interpretation_engine import build_llm_input
from kundali_calculator import generate_kundali
from kundali_chart import render_north_indian_chart
from llm_provider import get_llm, required_key_name
from location_resolver import resolve_birth_location
from navamsa_calculator import calculate_navamsa, calculate_navamsa_houses
from transit_calculator import analyze_transit_impact, get_current_transits

app = Flask(__name__)

_INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AstroMock — Kundali Generator</title>
<style>
  :root { color-scheme: light; }
  body { font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #222; background: #fff; }
  form { max-width: 480px; }
  label { display: block; margin-top: 0.75rem; font-weight: 600; }
  input[type=text], input[type=date], input[type=time] { width: 100%; padding: 0.4rem; box-sizing: border-box; }
  button { margin-top: 1rem; padding: 0.5rem 1.25rem; }
  #status { margin-top: 1rem; }
  .error { color: #b00020; white-space: pre-wrap; }
  .warning { background: #fff6e0; border: 1px solid #e8c96a; border-radius: 6px; padding: 0.5rem 0.75rem; margin: 0.75rem 0; }
  .charts { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 1.5rem; }
  .chart-card { flex: 1 1 320px; min-width: 280px; }
  .chart-card h2 { margin: 0 0 0.5rem; font-size: 1.1rem; text-align: center; }
  .chart-card svg { width: 100%; height: auto; display: block; border: 1px solid #e2e2e2; border-radius: 8px; }
  .card { background: #fafafa; border: 1px solid #e2e2e2; border-radius: 8px; padding: 1rem 1.25rem; margin-top: 1.5rem; }
  .card h2 { margin: 0 0 0.75rem; font-size: 1.1rem; }
  table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid #e2e2e2; }
  th { background: #f0f0f0; }
  tr.current td { background: #eaf3ea; font-weight: 600; }
  details { margin-top: 0.75rem; }
  summary { cursor: pointer; font-weight: 600; }
  .seg { display: inline-flex; border: 1px solid #c9c9d6; border-radius: 999px; overflow: hidden; margin: 0.25rem 0.75rem 0.25rem 0; }
  .seg button { margin: 0; padding: 0.35rem 0.95rem; border: none; background: #fff; cursor: pointer; font: inherit; font-size: 0.9rem; }
  .seg button + button { border-left: 1px solid #e2e2e6; }
  .seg button.active { background: #4a5fc1; color: #fff; }
  .guidance-section { margin-top: 0.9rem; }
  .guidance-section h3 { margin: 0 0 0.25rem; font-size: 0.95rem; color: #4a5fc1; }
  .guidance-section p { margin: 0; line-height: 1.5; }
  #guidance-status { color: #666; font-style: italic; }
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
  <p id="status"></p>
  <div class="card">
    <h2>Ask a Question</h2>
    <p style="margin:0 0 0.5rem">Fill your birth details above, then ask about career, marriage, wealth, health, education, children, family…</p>
    <input type="text" id="question" placeholder="kya mera career acha hoga?" style="width:100%;padding:0.4rem;box-sizing:border-box">
    <button id="ask-btn" type="button">Ask</button>
    <div id="answer"></div>
  </div>
  <div id="output"></div>
  <script>
    const esc = (s) => String(s).replace(/[&<>"']/g,
      (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

    function fmtDeg(d) {
      const deg = Math.floor(d);
      const min = Math.round((d - deg) * 60);
      return deg + '°' + String(min).padStart(2, '0') + '′';
    }

    function warningsHtml(data) {
      const notes = [...(data.warnings || [])];
      if (data.kundali && data.kundali.note) notes.push(data.kundali.note);
      return notes.map((w) => '<div class="warning">' + esc(w) + '</div>').join('');
    }

    function birthDetailsCard(data) {
      const loc = data.location;
      const bd = data.kundali.birth_details;
      const rows = [
        ['Place', loc.resolved_address],
        ['Coordinates', loc.latitude.toFixed(4) + ', ' + loc.longitude.toFixed(4)],
        ['Timezone', loc.timezone],
        ['Birth date & time', bd.date_of_birth + ' ' + bd.time_of_birth + ' (' + bd.utc_datetime + ')'],
        ['Ayanamsha', data.kundali.ayanamsha_system + ' (' + bd.ayanamsha + '°)'],
        ['House system', data.kundali.house_system || '—'],
      ];
      return '<div class="card"><h2>Birth Details</h2><table>' +
        rows.map(([k, v]) => '<tr><th>' + esc(k) + '</th><td>' + esc(v) + '</td></tr>').join('') +
        '</table></div>';
    }

    function ascendantCard(data) {
      const asc = data.kundali.ascendant;
      const rashi = data.kundali.rashi;
      const d9 = data.navamsa ? data.navamsa.ascendant_navamsa_sign : null;
      let html = '<div class="card"><h2>Lagna &amp; Rashi</h2>';
      if (asc) {
        html += '<p>Lagna (Rising sign): <strong>' + esc(asc.sign) + '</strong> ' +
          fmtDeg(asc.degree_in_sign) +
          ' · Nakshatra: ' + esc(asc.nakshatra.name) + ' (pada ' + asc.nakshatra.pada + ')' +
          (d9 ? ' · D-9 Lagna: <strong>' + esc(d9) + '</strong>' : '') + '</p>';
      } else {
        html += '<p>Lagna (Rising sign): <em>not determinable — birth time unknown</em></p>';
      }
      if (rashi) {
        html += '<p>Rashi (Moon sign): <strong>' + esc(rashi.sign) + '</strong>' +
          ' · Nakshatra: ' + esc(rashi.nakshatra.name) +
          ' (pada ' + rashi.nakshatra.pada + ')</p>';
      }
      return html + '</div>';
    }

    function planetsCard(data) {
      const navamsa = data.navamsa || {};
      const rows = Object.entries(data.kundali.planets).map(([name, p]) => {
        const d9 = navamsa[name] || {};
        return '<tr><td>' + esc(name) + (p.retrograde ? ' ℞' : '') + '</td>' +
          '<td>' + esc(p.sign) + '</td>' +
          '<td>' + fmtDeg(p.degree_in_sign) + '</td>' +
          '<td>' + (p.house != null ? p.house : '—') + '</td>' +
          '<td>' + esc(p.nakshatra.name) + ' (' + p.nakshatra.pada + ')</td>' +
          '<td>' + esc(d9.navamsa_sign || '—') + '</td>' +
          '<td>' + (d9.house != null ? d9.house : '—') + '</td></tr>';
      }).join('');
      return '<div class="card"><h2>Planetary Positions</h2><table>' +
        '<tr><th>Planet</th><th>Sign</th><th>Degree</th><th>House</th>' +
        '<th>Nakshatra (pada)</th><th>D-9 Sign</th><th>D-9 House</th></tr>' +
        rows + '</table></div>';
    }

    function dashaCard(dasha) {
      if (!dasha) return '';
      const bal = dasha.birth_dasha.balance_ymd;
      let html = '<div class="card"><h2>Vimshottari Dasha</h2>' +
        '<p>Moon nakshatra: <strong>' + esc(dasha.moon_nakshatra.name) + '</strong>' +
        ' · Birth Mahadasha: <strong>' + esc(dasha.birth_dasha.planet) + '</strong>' +
        ' (balance ' + bal.years + 'y ' + bal.months + 'm ' + bal.days + 'd)</p>';
      const cur = dasha.current_mahadasha;
      if (cur) {
        html += '<p>As of ' + esc(dasha.as_of) + ': <strong>' + esc(cur.planet) +
          '</strong> Mahadasha (' + esc(cur.start_date) + ' to ' + esc(cur.end_date) + ')';
        const ad = cur.current_antardasha;
        if (ad) {
          html += ' · <strong>' + esc(cur.planet) + '–' + esc(ad.planet) +
            '</strong> Antardasha (' + esc(ad.start_date) + ' to ' + esc(ad.end_date) + ')';
        }
        html += '</p><details open><summary>' + esc(cur.planet) +
          ' Mahadasha — Antardashas</summary><table>' +
          '<tr><th>Antardasha</th><th>Start</th><th>End</th></tr>' +
          cur.antardashas.map((a) => {
            const isCur = ad && a.planet === ad.planet && a.start_date === ad.start_date;
            return '<tr' + (isCur ? ' class="current"' : '') + '><td>' +
              esc(cur.planet) + '–' + esc(a.planet) + '</td><td>' + esc(a.start_date) +
              '</td><td>' + esc(a.end_date) + '</td></tr>';
          }).join('') + '</table></details>';
      }
      html += '<details><summary>Full Mahadasha timeline</summary><table>' +
        '<tr><th>Mahadasha</th><th>Start</th><th>End</th><th>Years</th></tr>' +
        dasha.mahadashas.map((md) => {
          const isCur = cur && md.start_date === cur.start_date;
          return '<tr' + (isCur ? ' class="current"' : '') + '><td>' + esc(md.planet) +
            '</td><td>' + esc(md.start_date) + '</td><td>' + esc(md.end_date) +
            '</td><td>' + md.duration_years.toFixed(2) + '</td></tr>';
        }).join('') + '</table></details></div>';
      return html;
    }

    // --- "Your Guidance" card (replaces the old transit table) ---
    let lastBirthPayload = null;
    const guidanceState = { timeframe: 'today', focus: 'overall' };

    function segHtml(options, stateKey) {
      return '<span class="seg">' + options.map(([value, label]) =>
        '<button type="button" data-key="' + stateKey + '" data-value="' + value + '"' +
        (guidanceState[stateKey] === value ? ' class="active"' : '') + '>' +
        label + '</button>').join('') + '</span>';
    }

    function guidanceCard(rashi) {
      if (!rashi) return '';
      return '<div class="card" id="guidance-card"><h2>Your Guidance</h2>' +
        '<p>Based on your Moon sign: <strong>' + esc(rashi.sign) + '</strong></p>' +
        '<div>' +
        segHtml([['today', 'Today'], ['2weeks', '2 Weeks'], ['6months', '6 Months']], 'timeframe') +
        segHtml([['overall', 'Overall'], ['career', 'Career'], ['love', 'Love'], ['health', 'Energy']], 'focus') +
        '</div>' +
        '<p id="guidance-status"></p><div id="guidance-content"></div></div>';
    }

    async function fetchGuidance() {
      const statusEl = document.getElementById('guidance-status');
      const contentEl = document.getElementById('guidance-content');
      if (!statusEl || !lastBirthPayload) return;
      statusEl.textContent = 'Reading the sky\\u2026';
      contentEl.innerHTML = '';
      try {
        const res = await fetch('/api/horoscope', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...lastBirthPayload,
            timeframe: guidanceState.timeframe, focus: guidanceState.focus }),
        });
        const data = await res.json();
        if (!data.success) {
          const messages = data.errors || [data.error && data.error.message || 'Unknown error'];
          statusEl.textContent = '';
          contentEl.innerHTML = '<p class="error">' + esc(messages.join('; ')) + '</p>';
          return;
        }
        statusEl.textContent = '';
        if (data.sections) {
          // Fixed order — JSON key order is not reliable (Flask sorts keys).
          const order = ['How your period looks', 'What to lean into',
                         'What to avoid', 'Helpful note'];
          contentEl.innerHTML = order.filter((h) => data.sections[h]).map((h) =>
            '<div class="guidance-section"><h3>' + esc(h) + '</h3><p>' +
            esc(data.sections[h]) + '</p></div>').join('');
        } else if (data.guidance) {
          contentEl.innerHTML = '<div style="white-space:pre-wrap">' + esc(data.guidance) + '</div>';
        } else {
          contentEl.innerHTML = '<div class="warning">' + esc(data.note || 'No reading available.') + '</div>';
        }
      } catch (err) {
        statusEl.textContent = '';
        contentEl.innerHTML = '<p class="error">Request failed: ' + esc(err) + '</p>';
      }
    }

    function initGuidance() {
      const card = document.getElementById('guidance-card');
      if (!card) return;
      card.querySelectorAll('.seg button').forEach((btn) => {
        btn.addEventListener('click', () => {
          guidanceState[btn.dataset.key] = btn.dataset.value;
          btn.closest('.seg').querySelectorAll('button')
            .forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          fetchGuidance();
        });
      });
      fetchGuidance();
    }

    function render(data) {
      const output = document.getElementById('output');
      const hasCharts = Boolean(data.chart_svg);
      output.innerHTML =
        warningsHtml(data) +
        (hasCharts
          ? '<div class="charts">' +
            '<div class="chart-card"><h2>D-1 Rasi</h2><div id="chart-d1"></div></div>' +
            '<div class="chart-card"><h2>D-9 Navamsa</h2><div id="chart-d9"></div></div>' +
            '</div>'
          : '<div class="warning">Charts are not drawn when the birth time is unknown.</div>') +
        birthDetailsCard(data) +
        ascendantCard(data) +
        planetsCard(data) +
        guidanceCard(data.kundali.rashi) +
        dashaCard(data.dasha);
      if (hasCharts) {
        document.getElementById('chart-d1').innerHTML = data.chart_svg;
        document.getElementById('chart-d9').innerHTML = data.navamsa_chart_svg || '';
      }
      initGuidance();
    }

    document.getElementById('ask-btn').addEventListener('click', async () => {
      const form = new FormData(document.getElementById('kundali-form'));
      const q = document.getElementById('question').value.trim();
      const answerEl = document.getElementById('answer');
      if (!q) { answerEl.innerHTML = '<p class="error">Please type a question.</p>'; return; }
      const payload = {
        date_of_birth: form.get('date_of_birth'),
        time_of_birth: form.get('time_of_birth'),
        place_of_birth: form.get('place_of_birth'),
        unsure_of_time: form.get('unsure_of_time') === 'on',
        question: q,
      };
      answerEl.innerHTML = '<p>Consulting the chart…</p>';
      try {
        const res = await fetch('/api/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.success) {
          const messages = data.errors || [data.error && data.error.message || 'Unknown error'];
          answerEl.innerHTML = '<p class="error">' + esc(messages.join('; ')) + '</p>';
          return;
        }
        let html = '<p>Lagna: <strong>' + esc(data.lagna || '—') + '</strong>' +
          ' · Rashi: <strong>' + esc(data.rashi.sign) + '</strong></p>';
        html += data.answer
          ? '<div style="white-space:pre-wrap">' + esc(data.answer) + '</div>'
          : '<div class="warning">' + esc(data.note || 'No answer available.') + '</div>';
        answerEl.innerHTML = html;
      } catch (err) {
        answerEl.innerHTML = '<p class="error">Request failed: ' + esc(err) + '</p>';
      }
    });

    document.getElementById('kundali-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const payload = {
        date_of_birth: form.get('date_of_birth'),
        time_of_birth: form.get('time_of_birth'),
        place_of_birth: form.get('place_of_birth'),
        unsure_of_time: form.get('unsure_of_time') === 'on',
      };
      const statusEl = document.getElementById('status');
      const output = document.getElementById('output');
      output.innerHTML = '';
      statusEl.textContent = 'Loading...';
      statusEl.className = '';
      try {
        const res = await fetch('/api/kundali', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.success) {
          const messages = data.errors || [data.error && data.error.message || 'Unknown error'];
          statusEl.textContent = messages.join('; ');
          statusEl.className = 'error';
          return;
        }
        statusEl.textContent = '';
        lastBirthPayload = payload;
        render(data);
      } catch (err) {
        statusEl.textContent = 'Request failed: ' + err;
        statusEl.className = 'error';
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
    gochar = analyze_transit_impact(chart["rashi"]["sign"],
                                    get_current_transits())
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
    guidance = llm(gi["system"], gi["user"]) if llm else None

    return jsonify({
        "success": True,
        "timeframe": timeframe,
        "tone": tone,
        "focus": focus,
        "rashi": chart["rashi"],
        "guidance": guidance,
        "sections": _split_guidance_sections(guidance) if guidance else None,
        "llm_configured": llm is not None,
        "note": (None if llm else
                 f"Guidance LLM not configured — set {required_key_name()} "
                 "to enable readings."),
        "facts": gi["context"],
        "warnings": location["warnings"],
    })


@app.post("/api/ask")
def ask():
    """Q&A endpoint: question + birth details -> interpreted answer.

    Pipeline: geocode -> kundali -> navamsa -> question routed to houses ->
    house analyses + BPHS references -> interpretation LLM (if configured).
    Without an API key the response still carries lagna/rashi and all
    computed facts, with answer=null and llm_configured=false.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"success": False, "errors": ["Request body must be JSON."]}), 400

    errors = _validation_errors(payload)
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        errors.append("question is required (non-empty string).")
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
    if chart["ascendant"] is not None:
        navamsa = calculate_navamsa_houses(navamsa)

    llm_payload = build_llm_input(question.strip(), chart, navamsa)
    llm = get_llm()
    answer = llm(llm_payload["system"], llm_payload["user"]) if llm else None

    return jsonify({
        "success": True,
        "question": question.strip(),
        "lagna": chart["lagna"],
        "rashi": chart["rashi"],
        "answer": answer,
        "llm_configured": llm is not None,
        "note": (None if llm else
                 f"Interpretation LLM not configured — set {required_key_name()} "
                 "to enable answers. Computed facts are in 'facts'."),
        "facts": llm_payload["context"],
        "warnings": location["warnings"],
    })


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
