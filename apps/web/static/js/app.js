// AstroMock — dashboard, ask-your-chart, and explore/technical panels.

const esc = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function fmtDeg(d) {
  const deg = Math.floor(d);
  const min = Math.round((d - deg) * 60);
  return deg + '°' + String(min).padStart(2, '0') + '′';
}

let lastBirthPayload = null;
let displayName = '';
let currentDepth = 'normal';
let currentTimeframe = 'today';

// ---------------------------------------------------------------------
// Answer-section splitting — mirrors the {system, user} prompts' section
// headings (prompts/advisor_prompt.md, career_prompt.md, deepen_prompt.md)
// so free-text LLM answers render as labeled cards instead of one block.
// ---------------------------------------------------------------------

const GENERAL_SECTIONS = {
  normal: ['Summary', 'Why this is indicated', 'Practical takeaway', 'Precision note'],
  deep: ['Direct answer', 'Core chart factors', 'Dasha / current period',
         'Divisional chart support', 'Practical interpretation', 'What would improve precision'],
  technical: ['Direct answer', 'D1 factors', 'D9 / D10 support',
              'Dasha / transit logic', 'Synthesis', 'Limitations'],
};
const CAREER_SECTIONS = {
  normal: ['Career outlook', 'Why this is showing up', 'Practical direction', 'Precision note'],
  deep: ['Career outlook', 'Main chart factors', 'Current timing',
         'Work style that suits you', 'Challenges to manage', 'What would make this more precise'],
  technical: ['Career outlook', 'D1 analysis', 'D9 / D10 considerations',
              'Dasha timing', 'Technical synthesis', 'Caution about over-precision'],
};
const DEEPEN_SECTIONS = ['Deeper reading', 'Key chart evidence', 'Timing factors',
                         'Supporting chart layers', 'Practical meaning', 'What remains uncertain'];

function trySectionSet(text, headings) {
  const positions = [];
  for (const h of headings) {
    const escaped = h.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp('^[#*\\s]*' + escaped + '[:*\\s]*$', 'im');
    const m = re.exec(text);
    if (!m) return null;
    positions.push([m.index, m.index + m[0].length, h]);
  }
  const sorted = [...positions].sort((a, b) => a[0] - b[0]);
  for (let i = 0; i < positions.length; i++) {
    if (sorted[i] !== positions[i]) return null;
  }
  const sections = {};
  for (let i = 0; i < positions.length; i++) {
    const [, end, heading] = positions[i];
    const next = i + 1 < positions.length ? positions[i + 1][0] : text.length;
    sections[heading] = text.slice(end, next).trim().replace(/^\*+|\*+$/g, '').trim();
  }
  return Object.values(sections).every((v) => v) ? sections : null;
}

function genericMarkdownSplit(text) {
  const matches = [...text.matchAll(/^#{1,3}\s+(.+)$/gm)];
  if (matches.length < 2) return null;
  const sections = {};
  for (let i = 0; i < matches.length; i++) {
    const heading = matches[i][1].trim();
    const start = matches[i].index + matches[i][0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index : text.length;
    sections[heading] = text.slice(start, end).trim();
  }
  return sections;
}

function splitAnswerSections(text, depth) {
  const candidates = [CAREER_SECTIONS[depth], GENERAL_SECTIONS[depth], DEEPEN_SECTIONS];
  for (const set of candidates) {
    if (!set) continue;
    const result = trySectionSet(text, set);
    if (result) return result;
  }
  return genericMarkdownSplit(text) || { Answer: text.trim() };
}

// ---------------------------------------------------------------------
// Plain-language labels
// ---------------------------------------------------------------------

function badgeClass(word) {
  const good = new Set(['high', 'supportive', 'favorable']);
  const care = new Set(['low', 'challenging', 'slow', 'needs care']);
  if (good.has(word)) return 'badge-good';
  if (care.has(word)) return 'badge-care';
  return 'badge-mixed';
}

function transitLabel(houseFromMoon) {
  const supportive = new Set([1, 3, 5, 9, 10, 11]);
  const needsCare = new Set([6, 8, 12]);
  if (supportive.has(houseFromMoon)) return 'supportive';
  if (needsCare.has(houseFromMoon)) return 'needs care';
  return 'mixed';
}

// ---------------------------------------------------------------------
// "Why this answer?" — plain-language render of the context/signals the
// backend actually used, so the reasoning is inspectable, not a black box.
// ---------------------------------------------------------------------

function buildWhyHtml(context, signals) {
  const lines = [];
  if (context) {
    if (context.topics && context.topics.length) {
      lines.push(`Matched topic${context.topics.length > 1 ? 's' : ''}: ${context.topics.join(', ')}`);
    }
    if (context.houses && context.houses.length) {
      lines.push(`Chart houses considered: ${context.houses.join(', ')}`);
    }
    if (context.house) {
      lines.push(`Chart house considered: ${context.house} (career)`);
    }
    if (context.dasha && context.dasha.current_mahadasha) {
      const md = context.dasha.current_mahadasha;
      lines.push(`Current Mahadasha: ${md.planet} (${md.start_date} to ${md.end_date})`);
    }
    if (context.gochar && context.gochar.sade_sati_status) {
      lines.push('Saturn is currently in a Sade Sati position from your Moon');
    }
  }
  if (signals) {
    lines.push(`Overall transit support: ${signals.overall_transit_support}`);
    (signals.notes || []).forEach((n) => lines.push(n));
  }
  if (!lines.length) return '<p>Grounded in your chart facts and current transits.</p>';
  return '<ul>' + lines.map((l) => `<li>${esc(l)}</li>`).join('') + '</ul>';
}

// ---------------------------------------------------------------------
// Ask Your Chart
// ---------------------------------------------------------------------

const SUGGESTED_QUESTIONS = [
  'Kya mera career acha hoga?',
  'How do my relationships look right now?',
  'What should I focus on this month?',
  'Kab tak paisa aayega?',
];

function renderSuggestedQuestions() {
  const wrap = document.getElementById('suggested-questions');
  wrap.innerHTML = '';
  SUGGESTED_QUESTIONS.forEach((q) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = q;
    chip.addEventListener('click', () => {
      document.getElementById('question-input').value = q;
      askQuestion(q);
    });
    wrap.appendChild(chip);
  });
}

function appendStatusNote(container, text) {
  const p = document.createElement('p');
  p.className = 'muted';
  p.textContent = text;
  container.prepend(p);
  return p;
}

function showError(container, messages) {
  const div = document.createElement('div');
  div.className = 'warning';
  div.textContent = messages.join('; ');
  container.prepend(div);
}

const DEPTH_LABELS = { normal: 'Quick', deep: 'Deep', technical: 'Technical' };

function renderAnswerCard(container, opts) {
  const { question, depth, answer, note, context, signals, allowDeepen } = opts;
  const card = document.createElement('div');
  card.className = 'card answer-card';

  let bodyHtml;
  if (answer) {
    const sections = splitAnswerSections(answer, depth);
    bodyHtml = Object.entries(sections).map(([heading, body]) =>
      `<div class="guidance-section"><span class="label">${esc(heading)}</span><p>${esc(body)}</p></div>`
    ).join('');
  } else {
    bodyHtml = `<div class="warning">${esc(note || 'No answer available.')}</div>`;
  }

  let actionsHtml = '';
  if (answer && allowDeepen) {
    actionsHtml = '<div class="answer-actions">' +
      '<button type="button" class="link-btn" data-action="deepen" data-depth="deep">Go deeper</button>' +
      '<button type="button" class="link-btn" data-action="deepen" data-depth="technical">Technical view</button>' +
      '</div>';
  }

  card.innerHTML =
    `<p class="answer-question">${esc(question)}<span class="depth-tag">${esc(DEPTH_LABELS[depth] || depth)}</span></p>` +
    bodyHtml + actionsHtml +
    `<details class="why"><summary>Why this answer?</summary><div class="why-body">${buildWhyHtml(context, signals)}</div></details>`;

  container.prepend(card);

  if (answer && allowDeepen) {
    card.querySelectorAll('[data-action="deepen"]').forEach((btn) => {
      btn.addEventListener('click', () => requestDeepen(question, answer, btn.dataset.depth));
    });
  }
}

async function askQuestion(question) {
  if (!question || !lastBirthPayload) return;
  const area = document.getElementById('answer-area');
  const status = appendStatusNote(area, 'Consulting the chart…');
  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...lastBirthPayload, question, depth: currentDepth }),
    });
    const data = await res.json();
    status.remove();
    if (!data.success) {
      showError(area, data.errors || [data.error && data.error.message || 'Unknown error']);
      return;
    }
    renderAnswerCard(area, {
      question, depth: data.depth, answer: data.answer, note: data.note,
      context: data.context, signals: data.signals, allowDeepen: data.depth === 'normal',
    });
  } catch (err) {
    status.remove();
    showError(area, ['Request failed: ' + err]);
  }
}

async function requestDeepen(question, previousAnswer, requestedDepth) {
  const area = document.getElementById('answer-area');
  const status = appendStatusNote(area, 'Going deeper…');
  try {
    const res = await fetch('/api/deepen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...lastBirthPayload, question, previous_answer: previousAnswer,
        requested_depth: requestedDepth,
      }),
    });
    const data = await res.json();
    status.remove();
    if (!data.success) {
      showError(area, data.errors || [data.error && data.error.message || 'Unknown error']);
      return;
    }
    renderAnswerCard(area, {
      question, depth: data.requested_depth, answer: data.answer, note: data.note,
      context: data.context, signals: null, allowDeepen: false,
    });
  } catch (err) {
    status.remove();
    showError(area, ['Request failed: ' + err]);
  }
}

// ---------------------------------------------------------------------
// Prediction horizon (Today / 2 Weeks / 6 Months)
// ---------------------------------------------------------------------

const HORIZON_LABELS = {
  'How your period looks': 'Summary',
  'What to lean into': 'Lean into',
  'What to avoid': 'Be mindful of',
  'Helpful note': 'Try this',
};

async function loadHorizon(timeframe) {
  currentTimeframe = timeframe;
  const statusEl = document.getElementById('horizon-status');
  const contentEl = document.getElementById('horizon-content');
  statusEl.textContent = 'Reading the sky…';
  contentEl.innerHTML = '';
  try {
    const res = await fetch('/api/horoscope', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...lastBirthPayload, timeframe, focus: 'overall' }),
    });
    const data = await res.json();
    if (!data.success) {
      statusEl.textContent = '';
      const messages = data.errors || [data.error && data.error.message || 'Unknown error'];
      contentEl.innerHTML = `<div class="warning">${esc(messages.join('; '))}</div>`;
      return;
    }
    statusEl.textContent = '';
    if (data.sections) {
      const order = ['How your period looks', 'What to lean into', 'What to avoid', 'Helpful note'];
      contentEl.innerHTML = order.filter((h) => data.sections[h]).map((h) =>
        `<div class="guidance-section"><span class="label">${esc(HORIZON_LABELS[h] || h)}</span><p>${esc(data.sections[h])}</p></div>`
      ).join('');
    } else if (data.guidance) {
      contentEl.innerHTML = `<div class="guidance-section"><p>${esc(data.guidance)}</p></div>`;
    } else {
      contentEl.innerHTML = `<div class="warning">${esc(data.note || 'No reading available.')}</div>`;
    }
  } catch (err) {
    statusEl.textContent = '';
    contentEl.innerHTML = `<div class="warning">Request failed: ${esc(err)}</div>`;
  }
}

// ---------------------------------------------------------------------
// Top insights
// ---------------------------------------------------------------------

const LEVEL_TEXT = {
  career: {
    high: 'Career houses are well supported right now — a good time to push initiatives.',
    medium: 'Career houses carry average support right now — steady effort will show results.',
    low: 'Career houses need extra patience right now — keep it steady, avoid big leaps.',
  },
  relationship: {
    high: 'Relationship houses are well supported right now.',
    medium: 'Relationship houses carry average support right now.',
    low: 'Relationship houses need gentler pacing right now.',
  },
};

function renderInsights(signals) {
  const grid = document.getElementById('insight-grid');
  if (!signals) {
    grid.innerHTML = '<p class="muted">Insights unavailable.</p>';
    return;
  }
  const cards = [
    { title: 'Career pattern', level: signals.career_house_support,
      text: LEVEL_TEXT.career[signals.career_house_support] },
    { title: 'Relationships & emotions', level: signals.relationship_house_support,
      text: LEVEL_TEXT.relationship[signals.relationship_house_support] },
    { title: 'Current period', level: signals.timing_quality,
      text: (signals.notes || []).join('. ') + (signals.notes && signals.notes.length ? '.' : '') },
  ];
  grid.innerHTML = cards.map((c) => `
    <div class="card insight-card">
      <h3>${esc(c.title)}</h3>
      <span class="badge ${badgeClass(c.level)}">${esc(c.level)}</span>
      <p>${esc(c.text)}</p>
    </div>`).join('');
}

// ---------------------------------------------------------------------
// Hero summary
// ---------------------------------------------------------------------

const HERO_PHRASES = {
  supportive: 'steady, supportive momentum',
  moderate: 'a mixed but workable rhythm',
  low: 'a slower period that rewards patience',
};

function renderHero(data) {
  document.getElementById('greeting').textContent = displayName ? `Hi ${displayName},` : 'Hi there,';
  const rashi = data.kundali.rashi;
  const overall = data.signals ? data.signals.overall_transit_support : null;
  const phrase = HERO_PHRASES[overall] || 'steady growth through discipline and effort';
  const moonBit = rashi ? ` — anchored by your ${rashi.sign} Moon` : '';
  document.getElementById('hero-summary').textContent = `Your chart points to ${phrase}${moonBit}.`;
}

// ---------------------------------------------------------------------
// Explore your chart
// ---------------------------------------------------------------------

function renderExplorePanels(data) {
  document.getElementById('chart-d1').innerHTML =
    data.chart_svg || '<p class="muted">Chart unavailable — birth time unknown.</p>';
  document.getElementById('chart-d9').innerHTML =
    data.navamsa_chart_svg || '<p class="muted">Chart unavailable — birth time unknown.</p>';

  const dashaEl = document.getElementById('dasha-summary');
  const dasha = data.dasha;
  if (dasha) {
    let html = `<p>Moon nakshatra: <strong>${esc(dasha.moon_nakshatra.name)}</strong></p>`;
    const cur = dasha.current_mahadasha;
    if (cur) {
      html += `<p>Current Mahadasha: <strong>${esc(cur.planet)}</strong> ` +
        `(${esc(cur.start_date)} to ${esc(cur.end_date)})</p>`;
      const ad = cur.current_antardasha;
      if (ad) {
        html += `<p>Current Antardasha: <strong>${esc(cur.planet)}–${esc(ad.planet)}</strong> ` +
          `(${esc(ad.start_date)} to ${esc(ad.end_date)})</p>`;
      }
    }
    dashaEl.innerHTML = html;
  } else {
    dashaEl.innerHTML = '<p class="muted">Dasha data unavailable.</p>';
  }

  const transitEl = document.getElementById('transit-summary');
  const gochar = data.gochar;
  if (gochar) {
    const rows = Object.entries(gochar).filter(([k]) => k !== 'sade_sati_status').map(([planet, info]) => {
      const label = transitLabel(info.house_from_moon);
      return `<div class="transit-row"><span class="planet">${esc(planet)}</span>` +
        `<span class="sign">${esc(info.transit_sign)}</span>` +
        `<span class="badge ${badgeClass(label)}">${esc(label)}</span></div>`;
    }).join('');
    const sadeSati = gochar.sade_sati_status
      ? '<div class="warning">Saturn is currently close to your natal Moon (Sade Sati) — ' +
        'this can add background pressure. Not a cause for alarm, just a period to move steadily.</div>'
      : '';
    transitEl.innerHTML = sadeSati + rows +
      '<p class="panel-caption">General house-energy read from the Moon — not a full personalized reading.</p>';
  } else {
    transitEl.innerHTML = '<p class="muted">Transit data unavailable.</p>';
  }

  document.querySelectorAll('#explore-buttons button').forEach((btn) => {
    btn.addEventListener('click', () => {
      const panel = document.getElementById('panel-' + btn.dataset.panel);
      const wasHidden = panel.classList.contains('hidden');
      document.querySelectorAll('.explore-panels .panel').forEach((p) => p.classList.add('hidden'));
      document.querySelectorAll('#explore-buttons button').forEach((b) => b.classList.remove('active'));
      if (wasHidden) {
        panel.classList.remove('hidden');
        btn.classList.add('active');
      }
    });
  });
}

// ---------------------------------------------------------------------
// Technical details (collapsed by default)
// ---------------------------------------------------------------------

function birthDetailsBlock(data) {
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
  return '<div class="tech-block"><h4>Birth details</h4><table>' +
    rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('') +
    '</table></div>';
}

function planetsBlock(data) {
  const navamsa = data.navamsa || {};
  const rows = Object.entries(data.kundali.planets).map(([name, p]) => {
    const d9 = navamsa[name] || {};
    return '<tr><td>' + esc(name) + (p.retrograde ? ' ℘' : '') + '</td>' +
      '<td>' + esc(p.sign) + '</td>' +
      '<td>' + fmtDeg(p.degree_in_sign) + '</td>' +
      '<td>' + (p.house != null ? p.house : '—') + '</td>' +
      '<td>' + esc(p.nakshatra.name) + ' (' + p.nakshatra.pada + ')</td>' +
      '<td>' + esc(d9.navamsa_sign || '—') + '</td>' +
      '<td>' + (d9.house != null ? d9.house : '—') + '</td></tr>';
  }).join('');
  return '<div class="tech-block"><h4>Planetary positions</h4><table>' +
    '<tr><th>Planet</th><th>Sign</th><th>Degree</th><th>House</th>' +
    '<th>Nakshatra (pada)</th><th>D-9 Sign</th><th>D-9 House</th></tr>' +
    rows + '</table></div>';
}

function dashaTimelineBlock(dasha) {
  if (!dasha) return '';
  const cur = dasha.current_mahadasha;
  let antardashaTable = '';
  if (cur) {
    const ad = cur.current_antardasha;
    antardashaTable = `<details class="nested" open><summary>${esc(cur.planet)} Mahadasha — Antardashas</summary>` +
      '<table><tr><th>Antardasha</th><th>Start</th><th>End</th></tr>' +
      cur.antardashas.map((a) => {
        const isCur = ad && a.planet === ad.planet && a.start_date === ad.start_date;
        return `<tr${isCur ? ' class="current"' : ''}><td>${esc(cur.planet)}–${esc(a.planet)}</td>` +
          `<td>${esc(a.start_date)}</td><td>${esc(a.end_date)}</td></tr>`;
      }).join('') + '</table></details>';
  }
  const fullTimeline = '<details class="nested"><summary>Full Mahadasha timeline</summary>' +
    '<table><tr><th>Mahadasha</th><th>Start</th><th>End</th><th>Years</th></tr>' +
    dasha.mahadashas.map((md) => {
      const isCur = cur && md.start_date === cur.start_date;
      return `<tr${isCur ? ' class="current"' : ''}><td>${esc(md.planet)}</td>` +
        `<td>${esc(md.start_date)}</td><td>${esc(md.end_date)}</td><td>${md.duration_years.toFixed(2)}</td></tr>`;
    }).join('') + '</table></details>';
  return `<div class="tech-block"><h4>Dasha timeline</h4>${antardashaTable}${fullTimeline}</div>`;
}

function renderTechnical(data) {
  document.getElementById('technical-content').innerHTML =
    birthDetailsBlock(data) + planetsBlock(data) + dashaTimelineBlock(data.dasha);
}

// ---------------------------------------------------------------------
// Dashboard assembly
// ---------------------------------------------------------------------

function renderWarnings(warnings, note) {
  const notes = [...(warnings || [])];
  if (note) notes.push(note);
  document.getElementById('warnings-area').innerHTML =
    notes.map((w) => `<div class="warning">${esc(w)}</div>`).join('');
}

function showDashboard(data) {
  document.getElementById('onboarding').classList.add('hidden');
  document.getElementById('dashboard').classList.remove('hidden');
  renderWarnings(data.warnings, data.kundali.note);
  renderHero(data);
  renderInsights(data.signals);
  renderExplorePanels(data);
  renderTechnical(data);
  renderSuggestedQuestions();
  document.getElementById('answer-area').innerHTML = '';
  currentTimeframe = 'today';
  document.querySelectorAll('#horizon-tabs button').forEach((b) =>
    b.classList.toggle('active', b.dataset.tf === 'today'));
  loadHorizon('today');
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------

document.getElementById('onboarding-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  displayName = (form.get('display_name') || '').trim();
  const payload = {
    date_of_birth: form.get('date_of_birth'),
    time_of_birth: form.get('time_of_birth'),
    place_of_birth: form.get('place_of_birth'),
    unsure_of_time: form.get('unsure_of_time') === 'on',
  };
  const statusEl = document.getElementById('onboarding-status');
  statusEl.textContent = 'Reading your chart…';
  statusEl.className = 'status';
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
      statusEl.className = 'status error';
      return;
    }
    statusEl.textContent = '';
    lastBirthPayload = payload;
    showDashboard(data);
  } catch (err) {
    statusEl.textContent = 'Request failed: ' + err;
    statusEl.className = 'status error';
  }
});

document.getElementById('edit-details').addEventListener('click', () => {
  document.getElementById('dashboard').classList.add('hidden');
  document.getElementById('onboarding').classList.remove('hidden');
});

document.querySelectorAll('#horizon-tabs button').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#horizon-tabs button').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    loadHorizon(btn.dataset.tf);
  });
});

document.querySelectorAll('#depth-tabs button').forEach((btn) => {
  btn.addEventListener('click', () => {
    currentDepth = btn.dataset.depth;
    document.querySelectorAll('#depth-tabs button').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

document.getElementById('ask-btn').addEventListener('click', () => {
  const input = document.getElementById('question-input');
  const q = input.value.trim();
  if (q) askQuestion(q);
});

document.getElementById('question-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    document.getElementById('ask-btn').click();
  }
});
