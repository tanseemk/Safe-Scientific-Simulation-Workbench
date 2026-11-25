'use strict';
// S3W web interface + API. Node built-ins only. Python owns all scientific behaviour.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { findPython, pythonEnv, ROOT } = require('../../scripts/py.js');

const PUBLIC = path.join(__dirname, 'public');
const RUNS = path.join(ROOT, 'runs');
const RESULTS = path.join(ROOT, 'results');
const MAX_BODY = 32 * 1024;
const PY_TIMEOUT_MS = 90_000;
const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml', '.json': 'application/json; charset=utf-8', '.ico': 'image/x-icon' };
const HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
};
const OPS = new Set(['contract', 'interpret', 'validate', 'execute', 'benchmark']); // fixed allow-list; never user-controlled

let python;
function callPython(op, payload) {
  if (!OPS.has(op)) return Promise.reject(new Error('unknown op'));
  python = python || findPython();
  if (!python) return Promise.reject(Object.assign(new Error('Python 3.12+ not found (set S3W_PYTHON)'), { status: 503 }));
  return new Promise((resolve, reject) => {
    // Fixed argv, no shell: user input only travels on stdin as JSON.
    const child = spawn(python.cmd, [...python.pre, '-m', 'scientific_core', 'bridge', op], { cwd: ROOT, env: pythonEnv(), shell: false });
    let out = '', err = '';
    const timer = setTimeout(() => { child.kill(); reject(Object.assign(new Error('python timed out'), { status: 504 })); }, PY_TIMEOUT_MS);
    child.stdout.on('data', (d) => (out += d));
    child.stderr.on('data', (d) => (err += d));
    child.on('error', (e) => { clearTimeout(timer); reject(e); });
    child.on('close', () => {
      clearTimeout(timer);
      try { resolve(JSON.parse(out)); } catch { reject(new Error('bad python response: ' + (err || out).slice(0, 300))); }
    });
    child.stdin.end(JSON.stringify(payload || {}));
  });
}

function send(res, status, body, type = 'application/json; charset=utf-8', extra = {}) {
  const data = typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', ...HEADERS, ...extra });
  res.end(data);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(Object.assign(new Error('request body too large'), { status: 413 })); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => {
      try { const v = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'); resolve(v && typeof v === 'object' && !Array.isArray(v) ? v : {}); }
      catch { reject(Object.assign(new Error('invalid JSON'), { status: 400 })); }
    });
    req.on('error', reject);
  });
}

const isBridgeError = (o) => Boolean(o && o.error && o.error.code);
const routes = [];
function route(method, pattern, handler) { routes.push({ method, pattern, handler }); }

route('GET', '/api/health', async () => {
  python = python || findPython();
  const contract = python ? await callPython('contract') : null;
  return [200, { ok: Boolean(python), python: python ? `${python.cmd} ${python.pre.join(' ')}`.trim() : null, mode: 'offline-capable',
    providers: contract && contract.providers, schema_version: contract && contract.schema_version }];
});

route('GET', '/api/contract', async () => [200, await callPython('contract')]);

route('GET', '/api/prompts', async () => {
  const f = path.join(ROOT, 'packages', 'contracts', 'prompts', 'v1.json');
  const s = JSON.parse(fs.readFileSync(f, 'utf8'));
  return [200, { suite: s.suite, version: s.version, note: s.note, prompts: s.prompts.map(({ id, type, prompt, expected }) => ({ id, type, prompt, expected })) }];
});

route('POST', '/api/interpret', async (req) => {
  const body = await readJson(req);
  const out = await callPython('interpret', { prompt: body.prompt, mode: body.mode, provider: body.provider });
  if (isBridgeError(out)) return [400, out]; // pipeline results may carry error:{class,message}; bridge errors carry error:{code,message}
  return [200, out];
});

route('POST', '/api/validate', async (req) => {
  const body = await readJson(req);
  const out = await callPython('validate', { settings: body.settings });
  if (isBridgeError(out)) return [400, out];
  return [200, out];
});

route('POST', '/api/run', async (req) => {
  const body = await readJson(req);
  const out = await callPython('execute', { settings: body.settings, provenance: body.provenance });
  if (isBridgeError(out)) return [400, out];
  if (out.status !== 'executed' && out.status !== 'checks_failed') return [422, out]; // invalid settings never reach the solver
  if (out.record && /^[A-Za-z0-9-]+$/.test(out.record.run_id)) {
    fs.mkdirSync(RUNS, { recursive: true });
    fs.writeFileSync(path.join(RUNS, out.record.run_id + '.json'), JSON.stringify({ record: out.record, validation: out.validation }, null, 2));
  }
  return [200, out];
});

route('GET', '/api/runs/:id', async (req, params) => {
  if (!/^[A-Za-z0-9-]{1,40}$/.test(params.id)) return [400, { error: { code: 'bad_id', message: 'invalid run id' } }];
  const f = path.join(RUNS, params.id + '.json');
  if (!fs.existsSync(f)) return [404, { error: { code: 'not_found', message: 'no such run' } }];
  return [200, JSON.parse(fs.readFileSync(f, 'utf8'))];
});

route('GET', '/api/evaluation', async () => {
  const f = path.join(RESULTS, 'offline', 'summary.json');
  const per = path.join(RESULTS, 'offline', 'raw.jsonl');
  if (!fs.existsSync(f)) return [200, { offline: null, live: { available: false, reason: 'Live trials not run.' } }];
  const summary = JSON.parse(fs.readFileSync(f, 'utf8'));
  const rows = fs.readFileSync(per, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
    .map(({ suite_prompt_id, type, expected, mode, status, success, attempts, retries, stop_reason, final_rule_ids }) => ({ suite_prompt_id, type, expected, mode, status, success, attempts, retries, stop_reason, final_rule_ids }));
  const live = fs.existsSync(path.join(RESULTS, 'live', 'summary.json')) ? { available: true } : { available: false, reason: 'Live trials not run.' };
  return [200, { offline: summary, per_prompt: rows, live }];
});

route('POST', '/api/evaluation/run', async () => {
  const out = await callPython('benchmark', {});
  if (isBridgeError(out)) return [500, out];
  return [200, { ok: true }];
});

function match(method, pathname) {
  for (const r of routes) {
    if (r.method !== method) continue;
    const names = [];
    const rx = new RegExp('^' + r.pattern.replace(/:(\w+)/g, (_, n) => { names.push(n); return '([^/]+)'; }) + '$');
    const m = rx.exec(pathname);
    if (m) return { handler: r.handler, params: Object.fromEntries(names.map((n, i) => [n, decodeURIComponent(m[i + 1])])) };
  }
  return null;
}

function serveStatic(res, pathname) {
  let rel = pathname === '/' ? '/index.html' : pathname;
  let file;
  try { file = path.normalize(path.join(PUBLIC, decodeURIComponent(rel))); } catch { return send(res, 400, 'bad request', 'text/plain'); }
  if (file !== PUBLIC && !file.startsWith(PUBLIC + path.sep)) return send(res, 403, 'forbidden', 'text/plain');
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) return send(res, 404, 'not found', 'text/plain');
    send(res, 200, fs.readFileSync(file), MIME[path.extname(file)] || 'application/octet-stream');
  });
}

function createServer() {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    try {
      if (url.pathname.startsWith('/api/')) {
        const hit = match(req.method, url.pathname);
        if (!hit) return send(res, 404, { error: { code: 'not_found', message: 'unknown API route' } });
        if (req.method === 'POST' && !/^application\/json/i.test(req.headers['content-type'] || '')) {
          return send(res, 415, { error: { code: 'unsupported_media_type', message: 'send application/json' } });
        }
        const [status, body] = await hit.handler(req, hit.params);
        return send(res, status, body);
      }
      if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405, 'method not allowed', 'text/plain');
      return serveStatic(res, url.pathname);
    } catch (e) {
      const status = e.status || 500;
      return send(res, status, { error: { code: status === 500 ? 'internal' : 'request_failed', message: status === 500 ? 'internal error' : e.message } });
    }
  });
}

module.exports = { createServer };

if (require.main === module) {
  const port = Number(process.env.PORT || 3000);
  const host = process.env.HOST || '127.0.0.1';
  createServer().listen(port, host, () => {
    console.log(`S3W workbench: http://${host}:${port}  (offline deterministic parser; no API key needed)`);
    if (!findPython()) console.warn('WARNING: Python 3.12+ not found; set S3W_PYTHON. The UI will load but API calls will fail.');
  });
}
