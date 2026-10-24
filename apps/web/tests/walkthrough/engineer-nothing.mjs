// "Nothing to fix in this practice" (189, rework r3 §1): a practice whose problem is gone (the
// index was refreshed to the new policy, or the settings warn) offers no system ticket. Here: a
// delivered demo practice whose index was refreshed, recovered by its continue code. Nothing is
// opened, no revision begins: the walk only looks and leaves.
//   1. home "take the ticket in this practice" → the "nothing to fix" sheet (#/engineer/?nothing)
//   2. the top bar's hat switch on the board → the same sheet
//   3. its secondary key → the test bench, product manager's hat
//
// BASE=http://127.0.0.1:18760 OUT=<dir> LANG_UI=zh|en CODE=<continue code> [THEME=dark] [WIDTH=390]
//   CHROME_BIN=… node apps/web/tests/walkthrough/engineer-nothing.mjs
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { delay, launch } from './cdp.mjs';

const base = process.env.BASE;
const out = process.env.OUT;
const code = process.env.CODE;
const language = process.env.LANG_UI === 'zh' ? 'zh' : 'en';
const dark = process.env.THEME === 'dark';
const width = Number(process.env.WIDTH || 1440);
assert.ok(base && out && code, 'BASE, OUT and CODE are required');
mkdirSync(out, { recursive: true });
const say = (cn, en) => (language === 'zh' ? cn : en);
const tag = `${dark ? 'dark' : 'light'}-${width}-${language}`;
// A phone recovers the practice at desktop width (the continue-code form is the entry line's, and
// at 390 it did not recover in this harness), then narrows to 390 before the first look.
const browser = await launch({ width: 1440, height: 900, dark });
async function narrow() {
  if (width >= 600) return;
  await browser.send('Emulation.setDeviceMetricsOverride', {
    width,
    height: 844,
    deviceScaleFactor: 2,
    mobile: true,
  });
  await browser.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
}
async function waitFor(expression, ms = 60000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await browser.ev(expression)) return;
    await delay(150);
  }
  throw new Error(`Timed out: ${expression}`);
}
async function shot(name) {
  const path = `${out}/after-${name}-${tag}.png`;
  const r = await browser.send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(path, Buffer.from(r.data, 'base64'));
  console.log(`ok ${path}`);
}
const press = (action, data = {}) =>
  browser.ev(`(() => { const b = document.createElement('button'); b.dataset.action = ${JSON.stringify(action)};
    Object.assign(b.dataset, ${JSON.stringify(data)}); b.hidden = true; document.body.append(b); b.click(); b.remove(); return true; })()`);
const nothingShown = `location.hash.includes('nothing') && !!document.querySelector('.ed-nothing__paper')`;
// Neither way in may open a ticket or a revision (189: judged before anything is opened).
const opened = [];
try {
  await browser.goto(base);
  await browser.ev(
    `localStorage.clear(); sessionStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)}); true`,
  );
  await browser.goto(`${base}/?load=1#/pm`);
  await waitFor(`!!document.querySelector('details[data-continue-code]')`);
  await browser.ev(`(() => { const d = document.querySelector('details[data-continue-code]'); d.open = true;
    d.dispatchEvent(new Event('toggle')); return true; })()`);
  await waitFor(`!!document.querySelector('#continue-code-input')`);
  await browser.ev(`(() => { const i = document.querySelector('#continue-code-input'); i.value = ${JSON.stringify(code)};
    i.dispatchEvent(new Event('input', { bubbles: true })); i.form.requestSubmit(); return true; })()`);
  // The recovered practice is written locally once the server answers (no route change to wait on).
  await delay(6000);
  await browser.send('Network.enable');
  browser.on('Network.requestWillBeSent', (p) => {
    if (
      p.request.method === 'POST' &&
      /\/engineer\/tickets|revisions|begin_revision/.test(p.request.url)
    )
      opened.push(p.request.url);
  });

  await narrow();
  // 1. Home: "take the ticket in this practice".
  await browser.ev(`localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)}); true`);
  await browser.goto(`${base}/?load=2#/`);
  await waitFor(`!!document.querySelector('[data-action="engineer-take"]')`);
  await browser.click('[data-action="engineer-take"]');
  await waitFor(nothingShown);
  await delay(900);
  const text = await browser.ev(`document.querySelector('.ed-nothing__paper').innerText`);
  assert.ok(text.includes(say('这一局没有要修的委托', 'Nothing to fix in this practice')), text);
  assert.ok(
    await browser.ev(`!!document.querySelector('#ws-stage .ed-nothing')`),
    'in the main screen',
  );
  assert.ok(await browser.ev(`!!document.querySelector('#ws-rail')`), 'the rail stays');
  await shot('nothing-home');

  // 2. The board's hat switch: the same sheet.
  await browser.goto(`${base}/?load=3#/work`);
  await waitFor(`!!document.querySelector('.shell-bar')`);
  await delay(1200);
  await press('hat-switch', { hat: 'engineer' });
  await waitFor(nothingShown);
  await delay(900);
  await shot('nothing-switch');

  // 3. Back to the test bench as the product manager.
  await browser.ev(`document.querySelector('#ed-nothing-bench').click(); true`);
  await waitFor(`location.hash === '#/bench'`);
  await delay(600);
  assert.equal(await browser.ev(`document.querySelector('.shell-bar').dataset.hat`), 'pm');
  await shot('nothing-bench');
  assert.deepEqual(opened, [], `opened: ${opened.join(', ')}`);
  console.log('ok no ticket and no revision opened');
} finally {
  await browser.close();
}
