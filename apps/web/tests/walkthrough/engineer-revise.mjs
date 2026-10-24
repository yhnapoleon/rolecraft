// The intro's delivered version (201 G5): a delivered practice, recovered by its continue code,
// puts on the engineer's hat from home ("take it in this practice"). The intro says a revision
// opens first and still shows what is to be fixed. Screenshot only; it does not press the key.
//
// MODE=handover instead hands the recovered practice's tests to engineering from the test bench
// (the "handed over" way in) and shoots that intro's slip.
//
// BASE=http://127.0.0.1:18760 OUT=<dir> LANG_UI=zh|en CODE=<continue code of a delivered practice>
//   [MODE=handover] [THEME=dark] [WIDTH=390] CHROME_BIN=… node apps/web/tests/walkthrough/engineer-revise.mjs
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
const tag = `${dark ? 'dark' : 'light'}-${width}-${language}`;
const browser = await launch({
  width,
  height: width < 600 ? 844 : 900,
  dark,
  mobile: width < 600,
});
async function waitFor(expression, ms = 30000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await browser.ev(expression)) return;
    await delay(150);
  }
  throw new Error(`Timed out: ${expression}`);
}
try {
  await browser.goto(base);
  await browser.ev(
    `localStorage.clear(); sessionStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)}); true`,
  );
  await browser.goto(`${base}/?load=1#/pm`);
  if (code === 'new') {
    // A product-manager practice with no engineering ticket yet: the slip shows the situation's words.
    await waitFor(`!!document.querySelector('[data-action="take-case"][data-case="pilot"]')`);
    await browser.click('[data-action="take-case"][data-case="pilot"]');
    await delay(1500);
    if (
      await browser.ev(
        `!!document.querySelector('[data-action="start-intake"], [data-action="start-case"]')`,
      )
    )
      await browser.click('[data-action="start-intake"], [data-action="start-case"]');
    await waitFor(`location.hash === '#/work'`, 60000);
    await delay(1500);
  } else {
    await waitFor(`!!document.querySelector('details[data-continue-code]')`);
    await browser.ev(`(() => { const d = document.querySelector('details[data-continue-code]'); d.open = true;
      d.dispatchEvent(new Event('toggle')); return true; })()`);
    await waitFor(`!!document.querySelector('#continue-code-input')`);
    await browser.ev(`(() => { const i = document.querySelector('#continue-code-input'); i.value = ${JSON.stringify(code)};
      i.dispatchEvent(new Event('input', { bubbles: true })); i.form.requestSubmit(); return true; })()`);
    await delay(4000);
  }
  // The recovered practice is current: put on the engineer's hat as the top bar's switch does for
  // a delivered practice (home's "take it in this practice" goes the same way).
  const recovered = await browser.ev('location.hash');
  console.log(`recovered at ${recovered}`);
  if (process.env.MODE === 'handover') {
    // The test bench's "Hand to engineering", pressed as its button would (same action).
    await browser.ev(`location.hash = '#/work'; true`);
    await delay(1500);
    await browser.ev(`(() => { const b = document.createElement('button'); b.dataset.action = 'engineer-handover';
      b.hidden = true; document.body.append(b); b.click(); b.remove(); return true; })()`);
    await waitFor(`!!document.querySelector('#ed-handover-submit')`);
    await browser.ev(`(() => { const boxes = [...document.querySelectorAll('.ed-handover__list input')];
      if (!boxes.some((b) => b.checked)) { boxes[0].checked = true; boxes[0].dispatchEvent(new Event('change')); }
      document.querySelector('#ed-handover-submit').click(); return true; })()`);
    await waitFor(`!!document.querySelector('.ed-intro__target .ed-intro__q')`);
    await delay(1200);
    const path = `${out}/after-intro-handover-${tag}.png`;
    const r = await browser.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(path, Buffer.from(r.data, 'base64'));
    console.log(`ok ${path}`);
    process.exit(0);
  }
  await browser.ev(`localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)}); true`);
  await browser.goto(`${base}/?load=2#/`);
  await delay(1200);
  // FORCE=1: the practice is no longer delivered (its revision was opened); draw the delivered
  // version through the same route the top bar's switch uses, to look at it.
  if (
    code !== 'new' &&
    !process.env.FORCE &&
    (await browser.ev(`!!document.querySelector('[data-action="engineer-take"]')`))
  )
    await browser.click('[data-action="engineer-take"]');
  else await browser.goto(`${base}/?load=3#/engineer/${encodeURIComponent('?intro&revise')}`);
  await waitFor(`!!document.querySelector('.ed-intro__paper')`);
  const hash = await browser.ev('location.hash');
  assert.match(hash, /revise/, `not the delivered version: ${hash}`);
  await waitFor(`!!document.querySelector('.ed-intro__target .ed-intro__q')`);
  await delay(900);
  const path = `${out}/after-intro-revise-${tag}${code === 'new' ? '-noticket' : ''}.png`;
  const r = await browser.send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(path, Buffer.from(r.data, 'base64'));
  console.log(`ok ${path}`);
} finally {
  await browser.close();
}
