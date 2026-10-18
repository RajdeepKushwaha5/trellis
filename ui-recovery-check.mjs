// Browser check of controller-enforced investigation and recovery, using synthetic controller fixtures (no model).
import puppeteer from 'puppeteer-core';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
fs.mkdirSync('artifacts', {recursive: true});
const python = process.cwd() + '/.venv/Scripts/python.exe';
const fixtures = JSON.parse(execFileSync(python, ['-m', 'backend.tutor.ui_fixture', 'create-recovery'], {encoding: 'utf8'}));
const browser = await puppeteer.launch({executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true});
const assert = (v, m) => { if (!v) throw Error(m); };
const open = async (p, token) => {
  await p.setCookie({name: 'trellis_session', value: token, url: 'http://127.0.0.1:8020', httpOnly: true, sameSite: 'Strict'});
  await p.goto('http://127.0.0.1:8020/#lab', {waitUntil: 'networkidle0'});
  await p.waitForSelector('#investigation-panel .investigation-card');
};
const step = async p => {
  await p.click('#manual');
  await p.waitForFunction(() => document.querySelector('#check-answer') && !document.querySelector('#stop-investigation'), {timeout: 60000});
};
const errors = [];
const page = async () => {
  // A separate browser context per learner, as two real users would have.
  const ctx = await browser.createBrowserContext(), p = await ctx.newPage();
  p.on('pageerror', e => errors.push(e.message));
  await p.setViewport({width: 1440, height: 1100});
  return p;
};
try {
  let p = await page();

  // 1. Ambiguous mistake: the panel says investigation is required, and Tinker's move is a distinguishing check.
  await open(p, fixtures.required);
  assert(await p.$eval('#investigation-panel', e => e.textContent.includes('Investigation required by the controller')), 'Required investigation not shown');
  assert(await p.$eval('#investigation-panel details', e => e.open), 'Panel should open when investigation is required');
  await step(p);
  assert(await p.$eval('#task', e => e.textContent.includes('DISTINGUISHING CHECK')), 'Tinker taught before investigating');
  await p.screenshot({path: 'artifacts/recovery-required.png', fullPage: true});

  // 2. After a failed transfer: the tried strategy is excluded with its reason, and the next lesson uses another.
  p = await page();
  await open(p, fixtures.recovery);
  const panel = await p.$eval('#investigation-panel', e => e.textContent);
  assert(panel.includes('Not repeated') && panel.includes('Walk the gaps from zero'), 'Excluded strategy not shown');
  assert(panel.includes('The check narrowed it down'), 'Probe outcome not shown');
  assert(await p.$$eval('#investigation-panel .episode li', l => l.length) === 4, 'Episode timeline should list four steps');
  await step(p);
  const strategy = await p.$eval('.strategy-card h3', e => e.textContent);
  assert(await p.$eval('#investigation-panel details', e => e.open && e.textContent.includes('Not repeated')), 'Episode should stay visible during the new lesson');
  assert(strategy !== 'Walk the gaps from zero', 'Failed strategy was repeated: ' + strategy);
  await p.screenshot({path: 'artifacts/recovery-new-strategy.png', fullPage: true});
  await p.click('nav [data-tab="notes"]');
  await p.waitForSelector('#episode-notes:not([hidden]) .episode li');
  assert(await p.$eval('#episode-notes', e => e.textContent.includes('Walk the gaps from zero')), 'Field notes missing the episode');
  await p.setViewport({width: 390, height: 844, isMobile: true});
  await p.waitForSelector('#goal-title');
  assert(!await p.evaluate(() => document.documentElement.scrollWidth > innerWidth), 'Mobile overflow');
  assert(!errors.length, errors.join('; '));
  console.log(`PASS: ambiguity forced a distinguishing check; after a failed transfer the next lesson used "${strategy}" instead of repeating "Walk the gaps from zero"; episode shown in the lab and field notes; mobile fits; no browser errors.`);
} finally {
  await browser.close();
  execFileSync(python, ['-m', 'backend.tutor.ui_fixture', 'delete', JSON.stringify(fixtures)]);
}
