// Browser check of the tutor loop in policy mode (no model): Scout check, then whatever the real responses lead to.
// The script answers by clicking, without knowing any answer, and records which payloads reached the browser.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
fs.mkdirSync('artifacts', {recursive: true});
const browser = await puppeteer.launch({executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true});
const assert = (v, m) => { if (!v) throw Error(m); };
try {
  const p = await browser.newPage(), errors = [], payloads = [];
  p.on('pageerror', e => errors.push(e.message));
  p.on('response', async r => {
    if (!r.url().includes('/api/') || r.request().method() === 'OPTIONS') return;
    try { payloads.push({url: r.url(), body: await r.text()}); } catch {}
  });
  await p.setViewport({width: 1440, height: 1050});
  await p.goto('http://127.0.0.1:8020/#curriculum', {waitUntil: 'networkidle0'});
  await p.click('#reset').catch(() => {});
  await p.click('[data-expedition]');
  await p.waitForFunction(() => !document.querySelector('#tutor-studio').hidden && document.querySelector('.role-strip'));
  assert(await p.$eval('#goal-title', e => e.textContent.includes('number line')), 'Expedition goal not opened');
  assert(await p.$$eval('.station', s => s.length) === 7, 'Expected seven lesson stations on this route');
  await p.screenshot({path: 'artifacts/tutor-start.png', fullPage: true});
  const seen = [];
  for (let turn = 0; turn < 9; turn++) {
    const button = await p.$('#continue') || (await p.$eval('#manual', b => !b.disabled) ? await p.$('#manual') : null);
    if (!button) break;
    if (await p.$('#continue')) {
      // Continue in policy mode, as the first click did.
      await p.click('#continue');
    } else await p.click('#manual');
    await p.waitForFunction(() => document.querySelector('#check-answer') && !document.querySelector('#feedback .feedback') && !document.querySelector('#stop-investigation'), {timeout: 60000}).catch(async e => { await p.screenshot({path: 'artifacts/tutor-fail.png', fullPage: true}); throw Error('No fresh task after ' + seen.join(',') + ': ' + await p.$eval('#task', x => x.textContent.slice(0, 400)) + ' / NOTICE ' + await p.$eval('#notice', x => x.textContent) + ' / STATUS ' + await p.$eval('#agent-status', x => x.textContent)); });
    const purpose = await p.$eval('#task .eyebrow', e => e.textContent);
    seen.push(purpose.split('/')[0].trim());
    assert(await p.$eval('#live-trail', e => e.textContent.includes('PERMITTED TOOLS')), 'Role tools not shown in the trail: ' + await p.$eval('#live-trail', e => e.textContent.slice(0, 300)) + ' / ' + await p.$eval('#agent-status', e => e.textContent));
    if (turn === 0) await p.screenshot({path: 'artifacts/tutor-check.png', fullPage: true});
    // Answer by interaction: first picture or first two parts or the middle mark.
    if (await p.$('#fraction-work [data-choice]')) await p.click('#fraction-work [data-choice="0"]');
    else if (await p.$('#fraction-work .part')) { const parts = await p.$$('#fraction-work .part'); await parts[0].click(); await (await p.$$('#fraction-work .part'))[1].click(); }
    else { const ticks = await p.$$('#fraction-work .tick'); await ticks[Math.floor(ticks.length / 2)].click(); }
    if (await p.$('#hint')) { await p.click('#hint'); await p.waitForSelector('.hint'); await p.screenshot({path: 'artifacts/tutor-lesson.png', fullPage: true}); }
    await p.click('#check-answer');
    await p.waitForSelector('#feedback .feedback');
    if (turn === 0) await p.screenshot({path: 'artifacts/tutor-feedback.png', fullPage: true});
  }
  assert(seen.length >= 2, 'Loop did not continue past the first check: ' + seen.join(', '));
  // Checks must not carry answers to the browser. Only a retired worked example carries a solution.
  for (const {url, body} of payloads) {
    if (!/tutor|agent\/jobs|launch/.test(url)) continue;
    let data; try { data = JSON.parse(body); } catch { continue; }
    const tasks = [data.task, data.result?.task, data].filter(t => t && t.render);
    for (const t of tasks) {
      const copy = JSON.parse(JSON.stringify(t)); delete copy.example; delete copy.result;
      assert(!/"(solution|answer|correct)"/.test(JSON.stringify(copy)), 'Answer leaked in ' + url);
    }
  }
  await p.click('nav [data-tab="map"]');
  await p.waitForSelector('#tutor-queries:not([hidden]) .native-query');
  assert(await p.$eval('#tutor-queries', e => /ms on the FalkorDB server/.test(e.textContent) && /MATCH/.test(e.textContent)), 'Tutor Cypher not shown');
  await p.screenshot({path: 'artifacts/tutor-queries.png', fullPage: true});
  await p.click('nav [data-tab="notes"]');
  await p.waitForSelector('#tutor-report:not([hidden]) .report');
  assert(await p.$eval('#tutor-report', e => e.textContent.includes('TODAY WITH THE TUTOR')), 'Parent summary missing');
  await p.waitForSelector('#observations .observation');
  assert(await p.$eval('#observations', e => /Scout check|Lens transfer|Tinker lesson/.test(e.textContent)), 'Observation purpose not shown');
  assert(await p.$eval('#trace', e => e.textContent.includes('Tools exposed to this role')), 'Role decisions missing from field notes');
  await p.screenshot({path: 'artifacts/tutor-notes.png', fullPage: true});
  await p.click('nav [data-tab="lab"]');
  await p.setViewport({width: 390, height: 844, isMobile: true});
  await p.waitForFunction(() => !document.querySelector('#tutor-studio').hidden && document.querySelector('.role-strip') && document.querySelector('#goal-title').textContent.includes('number line'), {timeout: 20000});
  assert(!await p.evaluate(() => document.documentElement.scrollWidth > innerWidth), 'Mobile overflow in the tutor room');
  await p.screenshot({path: 'artifacts/tutor-mobile.png', fullPage: true});
  assert(!errors.length, errors.join('; '));
  console.log('PASS: tutor loop in the browser, steps: ' + seen.join(' -> ') + '. No answers in check payloads, notes show roles, mobile fits, no browser errors.');
} finally { await browser.close(); }
