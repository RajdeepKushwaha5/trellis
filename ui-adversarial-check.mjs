// Adversarial live-app checks in the spirit of a strict QA reviewer: rapid clicks, keyboard only, hostile input,
// tablet and laptop widths, navigation abuse, rapid hints. Records every finding; exits non-zero if any.
// Run with the backend at :8020: node ui-adversarial-check.mjs
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
const findings = [], passes = [];
const fail = (m) => { findings.push(m); console.log('FIND ' + m); };
const pass = (m) => { passes.push(m); console.log('ok   ' + m); };
const b = await puppeteer.launch({executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true});
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function fresh(width = 1440) {
  const ctx = await b.createBrowserContext(), p = await ctx.newPage();
  p.errors = []; p.http = [];
  p.on('pageerror', e => p.errors.push(e.message));
  p.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) p.errors.push(m.text()); });
  p.on('response', r => { if (r.status() >= 400) p.http.push(`${r.status()} ${r.url().split('8020')[1]}`); });
  await p.setViewport({width, height: 1000});
  await p.goto('http://127.0.0.1:8020/#curriculum', {waitUntil: 'networkidle0'});
  return p;
}
const notice = p => p.$eval('#notice', e => e.hidden ? '' : e.textContent);
const waitTask = p => p.waitForFunction(() => document.querySelector('#check-answer') && !document.querySelector('#stop-investigation'), {timeout: 60000});
const observations = p => p.evaluate(async () => (await (await fetch('/api/notebook')).json()).observations.length);
const decisions = p => p.evaluate(async () => (await (await fetch('/api/notebook')).json()).role_decisions.length);
async function answerAny(p) {
  if (await p.$('#fraction-work [data-choice]')) await p.click('#fraction-work [data-choice="0"]');
  else if (await p.$('#fraction-work .part')) await (await p.$$('#fraction-work .part'))[0].click();
  else await (await p.$$('#fraction-work .tick'))[1].click();
}

// ---------- 1. rapid and double clicks ----------
let p = await fresh();
await p.click('nav [data-tab="lab"]'); await p.waitForFunction(() => document.querySelector('.role-strip'));
await p.evaluate(() => { const b = document.querySelector('#manual'); b.click(); b.click(); b.click(); });
await waitTask(p); await sleep(800);
const d1 = await decisions(p), n1 = await notice(p);
d1 === 1 ? pass('triple-click "run without a model": one role decision') : fail(`triple-click "run without a model" produced ${d1} role decisions`);
/already|409|error/i.test(n1) ? fail('triple-click showed an error notice: ' + n1) : pass('no error notice after triple-click');
await answerAny(p);
await p.evaluate(() => { const b = document.querySelector('#check-answer'); b.click(); b.click(); b.click(); });
await p.waitForSelector('#feedback .feedback'); await sleep(800);
const o1 = await observations(p);
o1 === 1 ? pass('triple-click "check my answer": one observation recorded') : fail(`triple-click "check my answer" recorded ${o1} observations`);
(await notice(p)) ? fail('notice after triple-click answer: ' + await notice(p)) : pass('no notice after triple-click answer');
const cont = await p.$('#continue');
if (cont) {
  await p.evaluate(() => { const b = document.querySelector('#continue'); b.click(); b.click(); });
  await p.waitForFunction(() => !document.querySelector('#feedback .feedback') && document.querySelector('#check-answer') && !document.querySelector('#stop-investigation'), {timeout: 90000}); await sleep(800);
  const d2 = await decisions(p);
  d2 === 2 ? pass('double-click "continue": exactly one more role decision') : fail(`double-click "continue" made ${d2 - 1} decisions`);
  if (await p.$('#hint')) {
    await p.evaluate(() => { const b = document.querySelector('#hint'); for (let i = 0; i < 6; i++) b.click(); });
    await sleep(1500);
    const shown = await p.$$eval('#hint-list .hint', h => h.length), label = await p.$eval('#hint', e => e.textContent);
    const m = label.match(/\((\d+) of (\d+)/);
    m && shown === Number(m[1]) && shown <= Number(m[2]) ? pass(`six rapid hint clicks: ${shown} hints shown, label "${label.trim()}"`) : fail(`rapid hint clicks: ${shown} shown vs label "${label}"`);
    const n = await notice(p); n ? fail('notice after rapid hint clicks: ' + n) : pass('no error notice after rapid hint clicks');
  }
}
p.errors.length ? fail('page errors during click tests: ' + p.errors.join(' | ')) : pass('no page errors during click tests');
pass('HTTP errors seen (expected 409 refusals are fine): ' + (p.http.join(', ') || 'none'));
await p.close();

// Compare page: rapid "open the two notebooks".
p = await fresh();
await p.click('nav [data-tab="compare"]'); await sleep(300);
await p.evaluate(() => { const b = document.querySelector('#compare-start'); b.click(); b.click(); b.click(); });
await p.waitForFunction(() => document.querySelectorAll('.comparison-card .compare-moves .trail-step').length >= 2, {timeout: 60000}); await sleep(1500);
const cards = await p.$$eval('.comparison-card', c => c.length);
cards === 2 ? pass('triple-click "open the two notebooks": two cards shown') : fail(`compare triple-click shows ${cards} cards`);
const comps = await p.evaluate(async () => { const r = await fetch('/api/notebook'); return r.ok; });
p.errors.length ? fail('page errors on compare: ' + p.errors.join(' | ')) : pass('no page errors on compare rapid clicks');
await p.close();

// ---------- 2. keyboard only ----------
p = await fresh();
await p.focus('[data-expedition]'); await p.keyboard.press('Enter');
await p.waitForFunction(() => document.querySelector('.role-strip'));
await p.focus('#manual'); await p.keyboard.press('Enter');
try { await waitTask(p); } catch (e) { fail('keyboard: no task 60 s after Enter on "run without a model": ' + JSON.stringify(await p.evaluate(() => ({notice: document.querySelector('#notice').textContent, status: document.querySelector('#agent-status').textContent, task: document.querySelector('#task').textContent.slice(0, 120)})))); }
const kind = await p.evaluate(() => document.querySelector('#fraction-work [data-choice]') ? 'choice' : document.querySelector('#fraction-work .part') ? 'part' : 'tick');
if (kind === 'choice') { await p.focus('#fraction-work [data-choice="1"]'); await p.keyboard.press('Enter'); }
else if (kind === 'part') { await p.focus('#fraction-work .part'); await p.keyboard.press('Space'); }
else { await p.focus('#fraction-work .tick'); await p.keyboard.press('ArrowRight'); await p.keyboard.press('ArrowRight'); }
const enabled = await p.$eval('#check-answer', b => !b.disabled);
enabled ? pass(`keyboard: answered a ${kind} task without the mouse`) : fail(`keyboard: ${kind} task could not be answered with the keyboard`);
if (enabled) { await p.focus('#check-answer'); await p.keyboard.press('Enter'); await p.waitForSelector('#feedback .feedback'); pass('keyboard: submitted with Enter, feedback shown'); }
const outline = await p.evaluate(() => { const b = document.querySelector('nav .nav'); b.focus(); return getComputedStyle(b, ':focus-visible').outlineStyle || getComputedStyle(b).outlineStyle; });
pass('focus style on nav buttons: ' + outline);
// Tab order reaches the main actions.
// Check Tab order from a fresh notebook, where the main actions are enabled (disabled buttons are rightly skipped).
await p.close(); p = await fresh(); await p.click('nav [data-tab="lab"]');
await p.waitForFunction(() => document.querySelector('.role-strip') && !document.querySelector('#manual').disabled);
const reached = new Set();
for (let i = 0; i < 40; i++) { await p.keyboard.press('Tab'); reached.add(await p.evaluate(() => document.activeElement?.id || document.activeElement?.className || document.activeElement?.tagName)); }
['agent', 'manual'].every(id => reached.has(id)) ? pass('Tab reaches "Start the expedition" and "Run without a model"') : fail('Tab did not reach the main actions: ' + [...reached].slice(0, 15).join(', '));
p.errors.length ? fail('page errors in keyboard test: ' + p.errors.join(' | ')) : pass('no page errors in keyboard test');
await p.close();

// ---------- 3. hostile input ----------
p = await fresh();
const inputs = ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>', '🍕 fractions 🍕', 'x'.repeat(500), `"quotes' and \\ backslash`, '.*+?[](){}|^$', '   ', 'OR AND NOT -fractions*', '%%%', '@fractions:{x}'];
let dialogs = 0; p.on('dialog', async d => { dialogs++; await d.dismiss(); });
for (const q of inputs) {
  await p.click('nav [data-tab="curriculum"]');
  await p.$eval('#curriculum-search', e => { e.value = ''; });
  await p.type('#curriculum-search', q); await sleep(900); await p.waitForNetworkIdle({idleTime: 400}).catch(() => {});
  const c = await p.$eval('#curriculum-count', e => e.textContent), n = await notice(p);
  const injected = await p.evaluate(() => !!document.querySelector('#curriculum-grid script, #curriculum-grid img'));
  const symbolsOnly = q.trim().length >= 2 && !/[a-z0-9]/i.test(q.replace(/[^\x00-\x7f]/g, ''));
  if (symbolsOnly && !c.startsWith('0 matching')) fail(`symbol-only search ${JSON.stringify(q)} should match nothing, got: ${c.split('.')[0]}`);
  if (n || injected) fail(`curriculum search ${JSON.stringify(q.slice(0, 30))}: notice="${n}" injected=${injected}`);
  else pass(`curriculum search ${JSON.stringify(q.slice(0, 30))} -> ${c.split('.')[0]}`);
}
await p.$eval('#curriculum-search', e => { e.value = ''; e.dispatchEvent(new Event('input')); }); await sleep(800);
await p.click('nav [data-tab="map"]');
for (const q of inputs) {
  await p.$eval('#search', e => { e.value = ''; });
  await p.type('#search', q); await sleep(900); await p.waitForNetworkIdle({idleTime: 400}).catch(() => {});
  const n = await notice(p), injected = await p.evaluate(() => !!document.querySelector('#search-results script, #search-results img'));
  (n || injected) ? fail(`map search ${JSON.stringify(q.slice(0, 30))}: notice="${n}" injected=${injected}`) : null;
}
pass('map search: all ' + inputs.length + ' hostile inputs handled without notices or injected HTML');
dialogs ? fail(`${dialogs} script dialogs fired (XSS)`) : pass('no script dialogs fired (no XSS)');
// Malformed answers and oversized payloads sent straight to the API.
const api = await p.evaluate(async () => {
  const post = async (path, body) => { const r = await fetch('/api/' + path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: typeof body === 'string' ? body : JSON.stringify(body)}); return r.status; };
  return {
    bad_task_id: await post('tutor/answer', {task: 'nothex', response: {choice: 0}}),
    unknown_task: await post('tutor/answer', {task: 'a'.repeat(32), response: {choice: 0}}),
    huge_response: await post('tutor/answer', {task: 'a'.repeat(32), response: {shaded: Array(5000).fill(1)}}),
    not_json: await post('tutor/answer', '{oops'),
    explain_arbitrary: await post('explain', {cypher: 'MATCH (n) DETACH DELETE n'}),
    goal_unknown: await post('goal', {concept_id: 'nope'}),
    goal_injection: await post('goal', {concept_id: "x'}) DETACH DELETE n //"}),
    search_long: (await fetch('/api/search?q=' + encodeURIComponent('<b>'.repeat(300)))).status,
  };
});
const expected = {bad_task_id: 422, unknown_task: 409, huge_response: 413, not_json: 422, explain_arbitrary: 400, goal_unknown: 409, goal_injection: 409, search_long: 200};
for (const [k, v] of Object.entries(api)) v === expected[k] ? pass(`API ${k}: ${v}`) : fail(`API ${k}: got ${v}, expected ${expected[k]}`);
const alive = await p.evaluate(async () => (await (await fetch('/api/overview')).json()).concepts);
alive === 1590 ? pass('graph intact after hostile requests (1,590 concepts)') : fail('graph changed after hostile requests: ' + alive);
p.errors.length ? fail('page errors in hostile input test: ' + p.errors.join(' | ')) : pass('no page errors in hostile input test');
await p.close();

// ---------- 4. tablet and laptop widths ----------
for (const w of [768, 1024]) {
  p = await fresh(w);
  for (const t of ['curriculum', 'lab', 'map', 'compare', 'notes']) {
    await p.click(`nav [data-tab="${t}"]`); await sleep(700); await p.waitForNetworkIdle({idleTime: 400}).catch(() => {});
    const o = await p.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    o ? fail(`${w}px ${t}: horizontal overflow`) : null;
    await p.screenshot({path: `artifacts/width-${w}-${t}.png`, fullPage: true});
  }
  pass(`${w}px: all five pages checked for overflow`);
  await p.close();
}

// ---------- 5. navigation abuse ----------
p = await fresh();
for (let i = 0; i < 15; i++) await p.click(`nav [data-tab="${['curriculum', 'lab', 'map', 'compare', 'notes'][i % 5]}"]`);
await sleep(1500);
const visible = await p.evaluate(() => [...document.querySelectorAll('.tab')].filter(t => !t.hidden).map(t => t.id));
visible.length === 1 && visible[0] === 'notes' ? pass('15 rapid tab switches: exactly one page visible, the last clicked') : fail('after rapid tab switches visible: ' + visible.join(','));
for (let i = 0; i < 6; i++) { await p.goBack().catch(() => {}); await sleep(150); }
await sleep(800);
const afterBack = await p.evaluate(() => ({hash: location.hash, shown: [...document.querySelectorAll('.tab')].filter(t => !t.hidden).map(t => t.id)}));
afterBack.shown.length === 1 && ('#' + afterBack.shown[0] === afterBack.hash || (!afterBack.hash && afterBack.shown[0] === 'curriculum')) ? pass(`repeated Back: page matches URL (${afterBack.hash})`) : fail('after repeated Back: ' + JSON.stringify(afterBack));
p.errors.length ? fail('page errors in navigation test: ' + p.errors.join(' | ')) : pass('no page errors in navigation test');
await b.close();
// ---------- 6. rapid hint clicks in a lesson (synthetic fixture) ----------
const python = process.cwd() + '/.venv/Scripts/python.exe';
const fx = JSON.parse(execFileSync(python, ['-m', 'backend.tutor.ui_fixture', 'create'], {encoding: 'utf8'}));
try {
  const b2 = await puppeteer.launch({executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true});
  const ctx = await b2.createBrowserContext(), q = await ctx.newPage(), hints = [];
  q.on('response', r => { if (r.url().includes('/hint')) hints.push(r.status()); });
  await q.setCookie({name: 'trellis_session', value: fx.strategy, url: 'http://127.0.0.1:8020', httpOnly: true, sameSite: 'Strict'});
  await q.goto('http://127.0.0.1:8020/#lab', {waitUntil: 'networkidle0'}); await q.waitForSelector('#hint');
  await q.evaluate(() => { const h = document.querySelector('#hint'); for (let i = 0; i < 6; i++) h.click(); });
  await sleep(1500);
  const shown = await q.$$eval('#hint-list .hint', h => h.length), n = await q.$eval('#notice', e => e.hidden ? '' : e.textContent);
  hints.length === 1 && shown === 1 && !n ? pass('six rapid hint clicks: one request, one hint, no error notice') : fail(`rapid hint clicks: ${hints.length} requests, ${shown} hints, notice "${n}"`);
  await b2.close();
} finally { execFileSync(python, ['-m', 'backend.tutor.ui_fixture', 'delete', JSON.stringify(fx)]); }

if (process.argv[2]) fs.writeFileSync(process.argv[2], JSON.stringify({findings, passes}, null, 2));
console.log(findings.length ? `FAILED: ${findings.length} findings, ${passes.length} passes` : `PASS: adversarial checks, ${passes.length} passed, 0 findings`);
process.exit(findings.length ? 1 : 0);
