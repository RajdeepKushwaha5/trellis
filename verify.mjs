// One command to verify Trellis: `npm run verify` (backend at :8020 and FalkorDB must be running).
// Every check is reported as PASS, FAIL or NOT RUN. A missing model is "NOT RUN", never a pass.
// Saved evidence is reported STALE when the code it describes has changed since it was produced.
import {execFileSync, spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import fs from 'node:fs';

const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const results = [];
const record = (name, status, detail = '') => { results.push({name, status, detail}); console.log(`${status.padEnd(8)} ${name}${detail ? ' · ' + detail : ''}`); };
const reachable = async url => { try { return (await fetch(url, {signal: AbortSignal.timeout(4000)})).ok; } catch { return false; } };

function run(name, cmd, args, timeout = 600000) {
  const r = spawnSync(cmd, args, {encoding: 'utf8', timeout, maxBuffer: 64 * 1024 * 1024});
  const text = (r.stdout || '') + (r.stderr || '');
  const pass = r.status === 0 && !/\bError\b|FAILED/.test(text.split('\n').filter(l => /PASS|Error|FAILED|^OK/.test(l)).join('\n'));
  const line = text.split('\n').find(l => /PASS|Error:|FAILED|Ran \d+ tests/.test(l)) || '';
  record(name, pass ? 'PASS' : 'FAIL', line.trim().slice(0, 140));
  return pass;
}

console.log('Trellis verification\n');
if (!await reachable('http://127.0.0.1:8020/api/overview')) {
  record('backend and FalkorDB reachable', 'FAIL', 'start FalkorDB and the backend first (see README: Run locally)');
  process.exit(1);
}
record('backend and FalkorDB reachable', 'PASS');

// Software tests, then the saved report's freshness against the current source files.
run('unit and integration tests (python -m backend.evaluate)', python, ['-m', 'backend.evaluate']);
const report = JSON.parse(fs.readFileSync('artifacts/evaluation.json', 'utf8'));
const changed = Object.entries(report.source_hashes).filter(([file, hash]) =>
  !fs.existsSync(file) || createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== hash).map(([f]) => f);
const saved = JSON.parse(fs.readFileSync('evidence/evaluation.json', 'utf8'));
const savedStale = Object.entries(saved.source_hashes).filter(([file, hash]) =>
  !fs.existsSync(file) || createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== hash).length;
record('fresh test report matches current code', changed.length ? 'FAIL' : 'PASS', changed.slice(0, 3).join(', '));
record('committed evidence/evaluation.json matches current code', savedStale ? 'STALE' : 'PASS',
  savedStale ? `${savedStale} files changed since it was saved; copy artifacts/evaluation.json to evidence/` : '');

// Browser checks that need no model.
for (const s of ['ui-check.mjs', 'ui-tutor-check.mjs', 'ui-investigation-check.mjs', 'ui-recovery-check.mjs'])
  run('browser: ' + s, process.execPath, [s]);

// Model-driven checks only when the local model is reachable.
if (await reachable('http://127.0.0.1:11434/api/version')) {
  run('browser: ui-agent-check.mjs (live model)', process.execPath, ['ui-agent-check.mjs']);
  run('live tutor loop (python -m backend.tutor.live_check)', python, ['-m', 'backend.tutor.live_check']);
} else {
  record('live model checks', 'NOT RUN', 'Ollama is not reachable at 127.0.0.1:11434');
}

const failed = results.filter(r => r.status === 'FAIL').length;
const notRun = results.filter(r => r.status === 'NOT RUN').length;
const stale = results.filter(r => r.status === 'STALE').length;
console.log(`\n${results.length - failed - notRun - stale} passed · ${failed} failed · ${notRun} not run · ${stale} stale`);
process.exit(failed ? 1 : 0);
