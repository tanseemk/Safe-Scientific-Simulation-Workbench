#!/usr/bin/env node
'use strict';
// Cross-platform Python launcher: finds Python 3.12+, sets PYTHONPATH, forwards argv.
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

function candidates() {
  const list = [];
  if (process.env.S3W_PYTHON) list.push([process.env.S3W_PYTHON, []]);
  if (process.platform === 'win32') list.push(['py', ['-3.12']], ['python', []], ['python3', []]);
  else list.push(['python3.12', []], ['python3', []], ['python', []]);
  return list;
}

function findPython() {
  for (const [cmd, pre] of candidates()) {
    const r = spawnSync(cmd, [...pre, '-c', 'import sys; print(sys.version_info >= (3, 12))'], { encoding: 'utf8' });
    if (r.status === 0 && r.stdout.trim() === 'True') return { cmd, pre };
  }
  return null;
}

function pythonEnv() {
  return { ...process.env, PYTHONPATH: path.join(ROOT, 'python') + path.delimiter + (process.env.PYTHONPATH || ''), PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' };
}

module.exports = { findPython, pythonEnv, ROOT };

if (require.main === module) {
  const py = findPython();
  if (!py) {
    console.error('Python 3.12+ not found. Install it or set S3W_PYTHON to its path.');
    process.exit(127);
  }
  const r = spawnSync(py.cmd, [...py.pre, ...process.argv.slice(2)], { stdio: 'inherit', cwd: ROOT, env: pythonEnv() });
  process.exit(r.status === null ? 1 : r.status);
}
