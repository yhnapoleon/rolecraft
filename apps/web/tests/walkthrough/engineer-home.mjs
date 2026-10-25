// Role-selection home: both work scenes, then the existing practice resume strip.
// CODE restores a practice before capturing its resume entry.
//
// BASE=http://127.0.0.1:18760 OUT=<dir> LANG_UI=zh|en [CODE=…] [THEME=dark] [WIDTH=390]
//   CHROME_BIN=… node apps/web/tests/walkthrough/engineer-home.mjs
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { delay, launch } from './cdp.mjs';

const { BASE: base, OUT: out, CODE: code } = process.env;
const language = process.env.LANG_UI === 'zh' ? 'zh' : 'en';
const dark = process.env.THEME === 'dark';
const width = Number(process.env.WIDTH || 1440);
assert.ok(base && out, 'BASE and OUT are required');
mkdirSync(out, { recursive: true });
const tag = `${dark ? 'dark' : 'light'}-${width}-${language}`;
const browser = await launch({ width, height: width < 600 ? 844 : 900, dark, mobile: width < 600 });
async function waitFor(expression, ms = 60000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await browser.ev(expression)) return;
    await delay(150);
  }
  throw new Error(`Timed out: ${expression}`);
}
async function shotRow(name) {
  await browser.ev(
    `document.querySelector('.home-roles').scrollIntoView({ block: 'center' }); true`,
  );
  await delay(700);
  const path = `${out}/after-${name}-${tag}.png`;
  const r = await browser.send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(path, Buffer.from(r.data, 'base64'));
  console.log(`ok ${path}`);
}
try {
  await browser.goto(base);
  await browser.ev(
    `localStorage.clear(); sessionStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)}); true`,
  );
  await browser.goto(`${base}/?load=1#/`);
  await waitFor(
    `!!document.querySelector('[data-role="engineer"] [data-action="engineer-start"]')`,
  );
  const row = await browser.ev(`document.querySelector('[data-role="engineer"]').innerText`);
  assert.match(
    row,
    language === 'zh' ? /Grace（AI 同事，产品侧）/ : /Grace \(AI colleague, product side\)/,
  );
  await shotRow('home-jobs');
  if (code) {
    await browser.goto(`${base}/?load=2#/pm`);
    await waitFor(`!!document.querySelector('details[data-continue-code]')`);
    await browser.ev(`(() => { const d = document.querySelector('details[data-continue-code]'); d.open = true;
      d.dispatchEvent(new Event('toggle')); return true; })()`);
    await waitFor(`!!document.querySelector('#continue-code-input')`);
    await browser.ev(`(() => { const i = document.querySelector('#continue-code-input'); i.value = ${JSON.stringify(code)};
      i.dispatchEvent(new Event('input', { bubbles: true })); i.form.requestSubmit(); return true; })()`);
    // The recovered practice is written locally once the server answers (no route change to wait on).
    await delay(6000);
    await browser.ev(`localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)}); true`);
    await browser.goto(`${base}/?load=3#/`);
    await waitFor(`!!document.querySelector('.hm-cont')`);
    await shotRow('home-jobs-practice');
  }
} finally {
  await browser.close();
}
