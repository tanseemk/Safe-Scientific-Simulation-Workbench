'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const state = { contract: null, prompts: [], result: null, original: {}, prov: {}, edited: new Set(), defaulted: new Set(), play: null, series: null, health: null };

  // ---------- helpers (DOM built with textContent only: prompts/provenance are untrusted) ----------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === 'class') el.className = v; else if (k === 'text') el.textContent = v; else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const svg = (tag, attrs) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v); return el; };
  const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); };
  const num = (v) => (Number.isFinite(v) ? Number(v.toPrecision(6)).toString() : String(v));
  const pct = (n, d) => (d ? ` (${Math.round((100 * n) / d)}%)` : '');
  const frac = (o) => `${o.num}/${o.den}${pct(o.num, o.den)}`;
  async function api(path, body) {
    const opts = body === undefined ? {} : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) };
    const r = await fetch(path, opts);
    let json = null; try { json = await r.json(); } catch { /* ignore */ }
    return { status: r.status, ok: r.ok, json };
  }
  function announce(msg) { $('stage-live').textContent = msg; }
  function banner(el, kind, text) { el.className = `banner banner--${kind}`; el.textContent = text; }

  // ---------- init ----------
  async function init() {
    $('prompt').addEventListener('input', () => ($('prompt-count').textContent = `${$('prompt').value.length} / 2000`));
    $('request-form').addEventListener('submit', onInterpret);
    $('example').addEventListener('change', () => { const p = state.prompts.find((x) => x.id === $('example').value); if (p) { $('prompt').value = p.prompt; $('prompt').dispatchEvent(new Event('input')); } });
    $('provider').addEventListener('change', updatePrivacy);
    $('revalidate-btn').addEventListener('click', onRevalidate);
    $('defaults-btn').addEventListener('click', onDefaults);
    $('run-btn').addEventListener('click', onRun);
    $('play-btn').addEventListener('click', togglePlay);
    $('replay-btn').addEventListener('click', () => startPlayback(true));
    $('export-json').addEventListener('click', exportJson);
    $('export-csv').addEventListener('click', exportCsv);
    $('bench-btn').addEventListener('click', onBenchmark);
    if (reduceMotion.matches) $('motion-note').textContent = 'Reduced motion is on: animation does not start automatically. The graph and data table show the full result.';
    const [health, contract, prompts] = await Promise.all([api('/api/health'), api('/api/contract'), api('/api/prompts')]).catch(() => [null, null, null]);
    if (!health || !health.json || !health.json.ok) { banner($('privacy'), 'bad', 'API unavailable'); $('privacy').className = 'chip mono'; $('privacy').textContent = 'API UNAVAILABLE — is Python 3.12 installed? (set S3W_PYTHON)'; }
    state.health = health && health.json;
    if (contract && contract.json && contract.json.fields) {
      state.contract = contract.json;
      $('schema-ver').textContent = contract.json.schema_version;
      $('spec-solver').textContent = 'RK4 fixed step · SI units';
      $('spec-caps').textContent = `≤ ${contract.json.max_steps.toLocaleString('en-US')} steps · ≤ ${contract.json.retry_cap} retries`;
      if (contract.json.providers.live.available) { const o = $('provider').querySelector('[value=live]'); o.disabled = false; o.textContent = 'Live LLM (key configured — prompt is sent to provider)'; }
    }
    if (prompts && prompts.json && prompts.json.prompts) {
      state.prompts = prompts.json.prompts;
      for (const p of state.prompts) $('example').append(h('option', { value: p.id, text: `${p.id} · ${p.type}` }));
    }
    updatePrivacy();
    loadEvaluation();
  }

  function updatePrivacy() {
    const live = $('provider').value === 'live';
    const chip = $('privacy');
    chip.className = 'chip mono' + (live ? ' is-live' : '');
    chip.textContent = live ? 'LIVE PROVIDER · request text is sent over the network' : 'OFFLINE · deterministic parser · nothing leaves this machine';
    $('provider-note').textContent = live ? 'Live mode needs the S3W_LLM_API_KEY environment variable on the server. Results from a live model vary and depend on a remote service.' : 'The offline parser is a deterministic test fixture; it is not a language model.';
    $('spec-parser').textContent = live ? 'live LLM adapter (structured JSON only)' : 'offline deterministic stub';
  }

  // ---------- 02 → 03 ----------
  async function onInterpret(e) {
    e.preventDefault();
    const prompt = $('prompt').value.trim();
    if (!prompt) { $('prompt').focus(); $('prompt-help').textContent = 'Enter a request first.'; return; }
    const mode = document.querySelector('input[name=mode]:checked').value;
    $('interpret-btn').disabled = true; $('interpret-btn').textContent = 'Interpreting…';
    setStages({ parse: 'active' }); announce('Parsing request');
    const r = await api('/api/interpret', { prompt, mode, provider: $('provider').value });
    $('interpret-btn').disabled = false; $('interpret-btn').textContent = 'Interpret request';
    if (!r.json || (r.json.error && r.json.error.code)) { showReviewError(r.json && r.json.error ? r.json.error.message : 'Request failed'); return; }
    state.result = r.json; state.original = {}; state.edited.clear(); state.defaulted.clear(); state.prov = JSON.parse(JSON.stringify(r.json.provenance || {}));
    renderReview(r.json);
    setStages({ parse: 'done', validate: r.json.status === 'valid' ? 'done' : 'fail' });
    $('review').scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth' });
    $('review-status').focus();
  }

  function showReviewError(msg) {
    $('review-empty').hidden = true; $('review-body').hidden = false;
    banner($('review-status'), 'bad', msg); clear($('trace')); clear($('fields-body')); clear($('issues'));
    $('run-btn').disabled = true; $('revalidate-btn').disabled = true; $('defaults-btn').hidden = true;
  }

  function rawOf(cand, name) {
    const v = cand && cand[name];
    if (v == null) return { value: '', unit: '' };
    if (typeof v === 'object') return { value: v.value == null ? '' : String(v.value), unit: v.unit == null ? '' : String(v.unit) };
    return { value: String(v), unit: '' };
  }

  function renderReview(res) {
    $('review-empty').hidden = true; $('review-body').hidden = false;
    $('run-btn').disabled = false; $('revalidate-btn').disabled = false;
    const kind = { valid: 'ok', clarify: 'warn', rejected: 'bad', provider_error: 'bad' }[res.status] || 'warn';
    const msg = {
      valid: 'Settings are valid. Review the values, then run.',
      clarify: 'More information is needed. Fill in the highlighted fields (value and unit) or confirm documented defaults.',
      rejected: 'This request was rejected by validation. Nothing was executed. Edit the settings or change the request.',
      provider_error: `Provider error: ${res.error ? res.error.message : 'unknown'}. Nothing was executed.`,
    }[res.status] || res.status;
    banner($('review-status'), kind, msg + (res.flags && res.flags.length ? ` Ignored instruction-like text in the request (${res.flags.join(', ')}).` : ''));

    const trace = $('trace'); clear(trace); trace.className = 'trace' + (reduceMotion.matches ? '' : ' is-animated');
    for (const a of res.attempts) {
      const cnt = a.candidate ? Object.keys(a.candidate).length : 0;
      const txt = a.error ? `Attempt ${a.attempt}: ${a.error.class} — ${a.error.message}`
        : `Attempt ${a.attempt}: parsed ${cnt} field(s) → validation ${a.disposition}${a.issues.length ? ` (${a.issues.filter((i) => i.severity === 'error').length} error(s))` : ''}${a.feedback_in ? ' · retried with validator feedback' : ''}`;
      trace.append(h('li', { text: txt }));
    }
    trace.append(h('li', { text: `Stopped: ${res.stop_reason.replace(/_/g, ' ')} · ${res.n_attempts} attempt(s), ${res.retries} retr${res.retries === 1 ? 'y' : 'ies'} · ${num(res.timing_ms.total)} ms` }));

    // model row + field rows
    const cand = res.candidate || {};
    const body = $('fields-body'); clear(body);
    const approved = state.contract ? state.contract.approved_models : ['damped_spring'];
    const modelSel = h('select', { id: 'f-model', 'aria-label': 'Model' }, [...new Set([...(cand.model ? [cand.model] : []), ...approved])].map((m) => h('option', { value: m, text: approved.includes(m) ? m : `${m} (unsupported)` })));
    if (cand.model) modelSel.value = cand.model; else modelSel.prepend(h('option', { value: '', text: '— choose —' })), modelSel.value = '';
    body.append(h('tr', { 'data-field': 'model' }, h('th', { scope: 'row', text: 'model' }), h('td', { colspan: 2 }, modelSel), h('td', { text: 'enum' }), provCell('model'), h('td', { id: 's-model' })));
    for (const f of state.contract.fields) {
      const raw = rawOf(cand, f.name); state.original[f.name] = raw;
      const val = h('input', { type: 'text', id: `f-${f.name}`, inputmode: 'decimal', 'aria-label': `${f.label} value`, value: raw.value, autocomplete: 'off', spellcheck: 'false' });
      const unit = h('select', { id: `u-${f.name}`, 'aria-label': `${f.label} unit` }, h('option', { value: '', text: '(no unit)' }), f.units.map((u) => h('option', { value: u, text: u })));
      if (raw.unit && !f.units.includes(raw.unit)) unit.append(h('option', { value: raw.unit, text: `${raw.unit} (not allowed)` }));
      unit.value = raw.unit;
      for (const el of [val, unit]) el.addEventListener('input', () => markEdited(f.name));
      body.append(h('tr', { 'data-field': f.name },
        h('th', { scope: 'row' }, h('span', { text: `${f.label} ` }), h('span', { class: 'mono hint', text: `${f.symbol} · ${f.min}–${f.max} ${f.canonical_unit}` })),
        h('td', {}, val), h('td', {}, unit), h('td', { class: 'mono', id: `si-${f.name}`, text: '—' }), provCell(f.name), h('td', { id: `s-${f.name}` })));
    }
    paintValidation(res.validation);
  }

  function provCell(name) {
    const p = state.prov[name];
    const label = !p ? 'not found in request' : p.source === 'prompt' ? `from request: “${p.text}”` : p.source === 'inferred' ? `inferred (${p.text})` : p.source === 'llm' ? 'proposed by LLM' : p.source === 'default_confirmed' ? 'default — confirmed by you' : p.source === 'user_edit' ? 'edited by you' : p.source;
    return h('td', { class: 'mono hint', id: `p-${name}`, text: label });
  }
  function markEdited(name) { state.edited.add(name); state.defaulted.delete(name); state.prov[name] = { source: 'user_edit', text: 'edited in review', method: 'ui' }; const c = $(`p-${name}`); if (c) c.textContent = 'edited by you'; }

  function paintValidation(v) {
    const issues = v ? v.issues : [];
    const byField = {};
    for (const i of issues) { const f = i.path.split('.')[1]; (byField[f || '_'] = byField[f || '_'] || []).push(i); }
    const norm = Object.fromEntries((v ? v.normalized : []).map((n) => [n.field, n]));
    for (const f of ['model', ...state.contract.fields.map((x) => x.name)]) {
      const cell = $(`s-${f}`); if (!cell) continue;
      const errs = (byField[f] || []).filter((i) => i.severity === 'error');
      const warns = (byField[f] || []).filter((i) => i.severity === 'warning');
      cell.className = 'status ' + (errs.length ? 'status--bad' : warns.length ? 'status--warn' : 'status--ok');
      cell.textContent = errs.length ? `✕ ${errs[0].rule_id}` : warns.length ? `▲ ${warns[0].rule_id}` : '✓ ok';
      const si = $(`si-${f}`); if (si) si.textContent = norm[f] && !errs.length ? `${num(norm[f].si)} ${norm[f].si_unit}${norm[f].converted ? ' ⇐ converted' : ''}` : '—';
    }
    const ul = $('issues'); clear(ul);
    for (const i of issues) ul.append(h('li', { class: i.severity === 'warning' ? 'warn' : '' }, h('div', { text: i.message }), h('div', { class: 'rule', text: `${i.rule_id} · ${i.kind} · ${i.severity}` }), h('div', { class: 'guide', text: i.guidance })));
    const missing = issues.filter((i) => i.rule_id === 'REQUIRED_MISSING' && i.path.split('.')[1] && i.path.split('.')[1] !== 'model');
    $('defaults-btn').hidden = missing.length === 0;
    $('run-btn').disabled = !v || v.disposition !== 'valid';
    $('run-btn').title = $('run-btn').disabled ? 'Resolve validation errors first' : '';
  }

  function collect() {
    const s = {};
    const model = $('f-model').value; if (model) s.model = model;
    for (const f of state.contract.fields) {
      const text = $(`f-${f.name}`).value.trim(); const unit = $(`u-${f.name}`).value;
      if (text === '') continue;
      const n = Number(text);
      const value = text !== '' && Number.isFinite(n) && /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(text) ? n : text; // non-numeric text is sent as-is and rejected by validation
      s[f.name] = unit ? { value, unit } : value;
    }
    return s;
  }

  async function onRevalidate() {
    const r = await api('/api/validate', { settings: collect() });
    if (r.json && !r.json.error) { paintValidation(r.json); banner($('review-status'), r.json.disposition === 'valid' ? 'ok' : r.json.disposition === 'clarify' ? 'warn' : 'bad', r.json.disposition === 'valid' ? 'Settings are valid.' : `Validation: ${r.json.disposition}.`); }
  }

  function onDefaults() {
    for (const f of state.contract.fields) {
      if ($(`f-${f.name}`).value.trim() === '') {
        $(`f-${f.name}`).value = String(f.default); $(`u-${f.name}`).value = f.canonical_unit;
        state.defaulted.add(f.name); state.prov[f.name] = { source: 'default_confirmed', text: 'documented default, confirmed by user', method: 'ui' };
        $(`p-${f.name}`).textContent = 'default — confirmed by you';
      }
    }
    if (!$('f-model').value) $('f-model').value = 'damped_spring';
    onRevalidate();
  }

  // ---------- 04 run ----------
  function setStages(map) {
    for (const li of $('stages').children) { const s = map[li.dataset.stage]; li.className = s ? `is-${s}` : ''; }
  }

  async function onRun() {
    stopPlayback(); setStages({ parse: 'done', validate: 'active' }); announce('Validating settings');
    $('run-btn').disabled = true; $('run').scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth' });
    const r = await api('/api/run', { settings: collect(), provenance: state.prov });
    $('run-btn').disabled = false;
    if (!r.json || (r.json.error && r.json.error.code)) { setStages({ parse: 'done', validate: 'fail' }); announce('Run failed'); banner($('review-status'), 'bad', r.json && r.json.error ? r.json.error.message : 'Run failed'); return; }
    if (r.status === 422) { paintValidation(r.json.validation); setStages({ parse: 'done', validate: 'fail' }); announce('Validation failed; solver not called'); banner($('review-status'), r.json.status === 'clarify' ? 'warn' : 'bad', 'Validation failed. The solver was not called. See the issues above.'); $('review').scrollIntoView(); return; }
    setStages({ parse: 'done', validate: 'done', solve: 'done', check: r.json.status === 'executed' ? 'done' : 'fail' });
    announce(r.json.status === 'executed' ? 'Run complete; all checks passed' : 'Run complete; an output check failed');
    renderResults(r.json);
  }

  // ---------- 05 results ----------
  function niceTicks(lo, hi, n) {
    if (hi === lo) { hi = lo + 1; lo -= 1; }
    const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw)), norm = raw / mag;
    const step = (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * mag;
    const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    return { ticks: out, step };
  }

  function renderResults(out) {
    state.out = out;
    const ex = out.execution, rec = out.record, S = ex.series; state.series = S;
    $('results-empty').hidden = true; $('results-body').hidden = false;
    banner($('run-banner'), out.status === 'executed' ? 'ok' : 'bad', out.status === 'executed' ? `Run ${rec.run_id} complete. All blocking output checks passed.` : `Run ${rec.run_id}: an output check failed — treat the result as unreliable.`);

    const W = 720, H = 320, m = { l: 64, r: 16, t: 14, b: 44 };
    const xs = S.x, tmax = S.t[S.t.length - 1];
    let lo = Math.min(...xs), hi = Math.max(...xs); const pad = (hi - lo || 1) * 0.08; lo -= pad; hi += pad;
    const sx = (t) => m.l + (t / tmax) * (W - m.l - m.r), sy = (x) => H - m.b - ((x - lo) / (hi - lo)) * (H - m.t - m.b);
    const g = $('plot-axes'); clear(g);
    const yt = niceTicks(lo, hi, 5), xt = niceTicks(0, tmax, 6);
    for (const v of yt.ticks) { g.append(svg('line', { class: 'gridl', x1: m.l, x2: W - m.r, y1: sy(v), y2: sy(v) })); const t = svg('text', { x: m.l - 8, y: sy(v) + 4, 'text-anchor': 'end' }); t.textContent = num(v); g.append(t); }
    for (const v of xt.ticks) { g.append(svg('line', { class: 'tick', x1: sx(v), x2: sx(v), y1: H - m.b, y2: H - m.b + 5 })); const t = svg('text', { x: sx(v), y: H - m.b + 18, 'text-anchor': 'middle' }); t.textContent = num(v); g.append(t); }
    g.append(svg('line', { class: 'ax', x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }), svg('line', { class: 'ax', x1: m.l, x2: m.l, y1: m.t, y2: H - m.b }));
    const xl = svg('text', { x: (m.l + W - m.r) / 2, y: H - 6, 'text-anchor': 'middle' }); xl.textContent = 't (s)'; g.append(xl);
    const yl = svg('text', { x: 14, y: (m.t + H - m.b) / 2, 'text-anchor': 'middle', transform: `rotate(-90 14 ${(m.t + H - m.b) / 2})` }); yl.textContent = 'x (m)'; g.append(yl);
    state.map = { sx, sy };

    const sm = ex.summary;
    $('plot-summary').textContent = `Regime: ${sm.regime} (ζ = ${num(sm.zeta)}, ω₀ = ${num(sm.omega0_rad_s)} rad/s${sm.period_s ? `, damped period ≈ ${num(sm.period_s)} s` : ''}). Peak |x| = ${num(sm.max_abs_x)} m; final x = ${num(sm.final_x)} m at t = ${num(tmax)} s. Energy fell from ${num(sm.initial_energy)} J to ${num(sm.final_energy)} J.`;
    const params = $('params'); clear(params);
    const st = rec.settings;
    const rows = [['Run ID', rec.run_id], ['mass m', `${num(st.mass)} kg`], ['stiffness k', `${num(st.stiffness)} N/m`], ['damping c', `${num(st.damping)} N·s/m`], ['x₀ / v₀', `${num(st.x0)} m / ${num(st.v0)} m/s`],
      ['duration / dt', `${num(st.duration)} s / ${num(st.dt)} s`], ['steps (eff. dt)', `${ex.n_steps.toLocaleString('en-US')} (${num(ex.dt_effective)} s)`], ['solver', 'RK4 · deterministic'], ['schema', rec.schema_version],
      ['validation / solver', `${num(out.timing_ms.validation)} ms / ${num(ex.solver_ms)} ms`], ['mode / provider', `${rec.mode} / ${rec.provider}`]];
    for (const [k, v] of rows) params.append(h('div', {}, h('dt', { text: k }), h('dd', { text: v })));
    const cb = $('checks-body'); clear(cb);
    for (const c of ex.checks) cb.append(h('tr', {}, h('td', { text: c.name }), h('td', { class: `status status--${c.status === 'pass' ? 'ok' : c.status === 'warn' ? 'warn' : 'bad'}`, text: c.status === 'pass' ? '✓ pass' : c.status === 'warn' ? '▲ warning' : '✕ fail' }), h('td', { text: c.detail })));
    const rowsN = Math.min(200, S.t.length), stride = Math.max(1, Math.ceil(S.t.length / rowsN)); const db = $('data-body'); clear(db);
    for (let i = 0; i < S.t.length; i += stride) db.append(h('tr', {}, h('td', { class: 'mono', text: num(S.t[i]) }), h('td', { class: 'mono', text: num(S.x[i]) }), h('td', { class: 'mono', text: num(S.v[i]) })));
    $('table-note').textContent = `Showing ${db.children.length} of ${S.total_samples.toLocaleString('en-US')} computed samples (every ${stride * S.stride}th). Full plotted series are in the JSON/CSV exports${S.stride > 1 ? ` (decimated: every ${S.stride}th sample of the solver output)` : ''}.`;

    $('play-btn').disabled = false; $('replay-btn').disabled = false;
    drawAt(S.t.length - 1, true);
    if (reduceMotion.matches) { drawAt(S.t.length - 1, true); $('play-btn').textContent = 'Play'; $('play-btn').setAttribute('aria-pressed', 'false'); } else startPlayback(true);
    $('results').scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth' });
  }

  // ---------- playback driven by real samples ----------
  function springPath(x1, x2, y, n, amp) {
    const pts = [`M${x1} ${y}`, `L${x1 + 14} ${y}`]; const a = x1 + 14, b = x2 - 14, seg = (b - a) / n;
    for (let i = 0; i < n; i++) pts.push(`L${(a + seg * (i + 0.5)).toFixed(1)} ${y + (i % 2 ? amp : -amp)}`);
    pts.push(`L${b} ${y}`, `L${x2} ${y}`); return pts.join(' ');
  }
  function drawAt(idx, full) {
    const S = state.series; if (!S) return;
    const { sx, sy } = state.map;
    let d = ''; const last = full ? S.t.length - 1 : idx;
    for (let i = 0; i <= last; i++) d += (i ? 'L' : 'M') + sx(S.t[i]).toFixed(1) + ' ' + sy(S.x[i]).toFixed(1);
    $('plot-line').setAttribute('d', d);
    $('plot-dot').setAttribute('cx', sx(S.t[idx])); $('plot-dot').setAttribute('cy', sy(S.x[idx]));
    const peak = Math.max(...S.x.map(Math.abs)) || 1, eq = 320, scale = 140 / peak;
    const cx = eq + S.x[idx] * scale;
    $('bob').setAttribute('x', cx - 28);
    $('coil').setAttribute('d', springPath(30, cx - 28, 60, 12, 14));
  }
  function startPlayback(restart) {
    if (!state.series) return; stopPlayback();
    const S = state.series, total = 4500 / (reduceMotion.matches ? 1 : 1); let t0 = null, idx0 = restart ? 0 : (state.play && state.play.idx) || 0;
    state.play = { idx: idx0, raf: null, paused: false };
    $('play-btn').textContent = 'Pause'; $('play-btn').setAttribute('aria-pressed', 'true');
    const tick = (ts) => {
      if (state.play.paused) return; if (t0 === null) t0 = ts - (idx0 / (S.t.length - 1)) * total;
      const f = Math.min(1, (ts - t0) / total); const idx = Math.round(f * (S.t.length - 1)); state.play.idx = idx; drawAt(idx, false);
      if (f < 1) state.play.raf = requestAnimationFrame(tick); else { $('play-btn').textContent = 'Play'; $('play-btn').setAttribute('aria-pressed', 'false'); state.play.done = true; }
    };
    state.play.raf = requestAnimationFrame(tick);
  }
  function stopPlayback() { if (state.play && state.play.raf) cancelAnimationFrame(state.play.raf); if (state.play) state.play.paused = true; }
  function togglePlay() {
    if (state.play && !state.play.paused && !state.play.done) { stopPlayback(); $('play-btn').textContent = 'Play'; $('play-btn').setAttribute('aria-pressed', 'false'); }
    else startPlayback(!state.play || state.play.done || state.play.idx >= state.series.t.length - 1);
  }

  // ---------- exports (client-side from the returned data) ----------
  function download(name, text, type) { const a = h('a', { href: URL.createObjectURL(new Blob([text], { type })), download: name }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
  function exportJson() { if (state.out) download(`${state.out.record.run_id}.json`, JSON.stringify({ record: state.out.record, validation: state.out.validation, series: state.out.execution.series, checks: state.out.execution.checks }, null, 2), 'application/json'); }
  function exportCsv() {
    if (!state.out) return; const S = state.series; const lines = ['t_s,x_m,v_m_per_s,energy_J'];
    for (let i = 0; i < S.t.length; i++) lines.push([S.t[i], S.x[i], S.v[i], S.energy[i]].join(','));
    download(`${state.out.record.run_id}.csv`, lines.join('\n') + '\n', 'text/csv');
  }

  // ---------- 06 evaluation ----------
  async function loadEvaluation() {
    const r = await api('/api/evaluation'); const j = r.json;
    if (!j || !j.offline) { $('eval-caveat').textContent = 'No benchmark results yet. Press “Run offline benchmark” to generate real measurements from the fixed prompt suite. Nothing is pre-filled.'; $('eval-body').hidden = true; return; }
    $('eval-caveat').textContent = j.offline.caveat; $('eval-body').hidden = false;
    const A = j.offline.aggregate, B = A.baseline, F = A.feedback; const body = $('eval-body-rows'); clear(body);
    const row = (label, fn) => body.append(h('tr', {}, h('th', { scope: 'row', text: label }), h('td', { class: 'mono', text: fn(B) }), h('td', { class: 'mono', text: fn(F) })));
    row('Task success', (a) => frac(a.task_success)); row('Invalid candidates per parser attempt', (a) => frac(a.invalid_candidates_per_attempt));
    row('Invalid requests safely rejected', (a) => frac(a.invalid_requests_safely_rejected)); row('Clarification quality', (a) => frac(a.clarification_quality));
    row('Retries (total · mean)', (a) => `${a.retries.total} · ${num(a.retries.mean)}`); row('Retry distribution (retries: cases)', (a) => JSON.stringify(a.retries.distribution));
    row('Retry cap exhausted', (a) => frac(a.retries.cap_exhausted)); row('Solver exceptions / solver runs', (a) => frac(a.execution_errors.solver_exceptions));
    row('Provider/other errors by class', (a) => JSON.stringify(a.execution_errors.by_class)); row('Safety violations (raw; target 0)', (a) => String(a.safety_violations.count));
    row('Total time median / p95 (ms)', (a) => `${num(a.response_time_ms.total.median)} / ${num(a.response_time_ms.total.p95)}`);
    row('Validation time median / p95 (ms)', (a) => `${num(a.response_time_ms.validation.median)} / ${num(a.response_time_ms.validation.p95)}`);
    row('Solver time median / p95 (ms), runs only', (a) => (a.response_time_ms.solver.n ? `${num(a.response_time_ms.solver.median)} / ${num(a.response_time_ms.solver.p95)} (n=${a.response_time_ms.solver.n})` : 'n/a'));
    const pr = $('prompt-rows'); clear(pr);
    const ids = [...new Set(j.per_prompt.map((x) => x.suite_prompt_id))];
    for (const id of ids) {
      const b = j.per_prompt.find((x) => x.suite_prompt_id === id && x.mode === 'baseline'), f = j.per_prompt.find((x) => x.suite_prompt_id === id && x.mode === 'feedback');
      const cell = (x) => h('td', { class: 'mono', text: `${x.success ? '✓' : '✕'} ${x.status} · ${x.attempts} attempt(s)` });
      pr.append(h('tr', {}, h('th', { scope: 'row', text: id }), h('td', { text: b.type }), h('td', { text: b.expected }), cell(b), cell(f)));
    }
    const p = j.offline.protocol;
    $('eval-protocol').textContent = `Protocol: suite ${p.suite.name} v${p.suite.version} (sha256 ${p.suite.sha256.slice(0, 12)}…), ${p.suite.n_prompts} prompts × ${p.repeats} repeat, parser ${p.parser}, seed ${p.seed}, generated ${p.generated_at}. Command: ${p.command}`;
    $('live-state').textContent = j.live && j.live.available ? 'available in results/live/' : 'unavailable (not run)';
  }
  async function onBenchmark() {
    $('bench-btn').disabled = true; $('bench-status').textContent = 'Running the fixed suite in both modes…';
    const r = await api('/api/evaluation/run', {});
    $('bench-btn').disabled = false; $('bench-status').textContent = r.ok ? 'Done. Figures below were computed just now from raw records.' : 'Benchmark failed.';
    await loadEvaluation();
  }

  init().catch((e) => { console.error(e); });
})();
