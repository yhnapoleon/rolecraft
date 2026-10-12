/** 149 module browser check: the support section for each model-advice state, zh and en,
 * desktop light, 390px dark and keyboard. Controlled fixture page only (no real API); the
 * advice is recorded HTTP output read through the page's own reader.
 *   CHROME_BIN=... OUT=<new dir> [MODEL_ADVICE_PORT=19811] node src/features/feedback-native/model-advice.shots.mjs
 * Writes <lang>-<state>-<view>.jpg and results.json to OUT. */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { createServer } from 'vite';
import { launch } from '../../../tests/walkthrough/cdp.mjs';
import { recordedReport, scenarios } from './model-advice.scenarios.mjs';

const out = process.env.OUT;
assert.ok(out, 'OUT is required');
mkdirSync(out, { recursive: true });
const port = Number(process.env.MODEL_ADVICE_PORT || 19811);
const views = [
  { name: 'desktop-light', width: 1200, height: 900, dark: false, mobile: false },
  { name: '390-dark', width: 390, height: 844, dark: true, mobile: true },
];
const states = ['synthetic', 'external', 'fusion', 'loadFailed', 'timeout', 'abstained'];

/** Screenshot of the support section (heading, evaluation model line and advice block). */
async function shotOf(browser, path) {
  const box = await browser.ev(`(() => {
    const section = document.querySelector('[data-model-advice]').closest('section');
    section.scrollIntoView({ block: 'start' });
    const r = section.getBoundingClientRect();
    return { x: Math.max(0, r.left - 8), y: r.top + scrollY - 8, width: Math.min(innerWidth, r.width + 16), height: r.height + 16 };
  })()`);
  const r = await browser.send('Page.captureScreenshot', {
    format: 'jpeg',
    quality: 85,
    captureBeyondViewport: true,
    clip: { ...box, scale: 1 },
  });
  writeFileSync(path, Buffer.from(r.data, 'base64'));
}

const server = await createServer({ server: { port, strictPort: true }, logLevel: 'error' });
await server.listen();
const results = [];
try {
  for (const language of ['zh', 'en']) {
    for (const view of views) {
      const browser = await launch({ ...view, reduced: true });
      try {
        await browser.goto(
          `http://127.0.0.1:${port}/src/features/feedback-native/review-check.html?lang=${language}`,
        );
        // Use the v4 workbench stylesheet (the page the learner sees) instead of the fixture's.
        await browser.ev(`new Promise((done) => {
          document.querySelector('link[href="/workbench.css"]')?.remove();
          const link = Object.assign(document.createElement('link'), { rel: 'stylesheet', href: '/src/app/styles.css' });
          link.onload = done;
          document.head.append(link);
        })`);
        for (const state of states) {
          await browser.ev(`window.fixture.state.reports = [${JSON.stringify(recordedReport(language, []))}];
            window.fixture.state.reports[0].model_advice = window.fixture.read(${JSON.stringify([scenarios[state](language)])});
            window.fixture.update();`);
          const folded = await browser.ev(
            `document.querySelector('[data-model-advice] summary').innerText`,
          );
          await browser.ev(`document.querySelector('[data-model-advice]').open = true`);
          const opened = await browser.ev(
            `document.querySelector('[data-model-advice]').closest('section').innerText`,
          );
          const overflow = await browser.ev('document.documentElement.scrollWidth > innerWidth');
          assert.equal(overflow, false, `${language} ${state} ${view.name} scrolls horizontally`);
          const path = `${out}/${language}-${state}-${view.name}.jpg`;
          await shotOf(browser, path);
          results.push({ language, state, view: view.name, folded, opened, path });
        }
        if (view.name === 'desktop-light') {
          // Keyboard: Tab to the summary, Enter opens, Tab reaches the first evidence button.
          await browser.ev(`window.fixture.state.reports = [${JSON.stringify(recordedReport(language, []))}];
            window.fixture.state.reports[0].model_advice = window.fixture.read(${JSON.stringify([scenarios.synthetic(language)])});
            window.fixture.update(); document.querySelector('[data-model-advice]').open = false;
            document.querySelector('[data-model-advice] summary').focus();`);
          const key = async (code, keyCode, text) => {
            const base = { key: code, code, windowsVirtualKeyCode: keyCode };
            await browser.send('Input.dispatchKeyEvent', {
              type: 'keyDown',
              ...base,
              ...(text ? { text, unmodifiedText: text } : {}),
            });
            await browser.send('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
          };
          await key('Enter', 13, '\r');
          assert.equal(
            await browser.ev(`document.querySelector('[data-model-advice]').open`),
            true,
          );
          await key('Tab', 9);
          const focused = await browser.ev(
            `document.activeElement.matches('[data-model-reference]') && document.activeElement.textContent`,
          );
          assert.ok(focused, 'Tab from the opened summary reaches the first evidence button');
          const path = `${out}/${language}-keyboard-${view.name}.jpg`;
          await shotOf(browser, path);
          results.push({ language, state: 'keyboard', view: view.name, focused, path });
        }
        assert.deepEqual(
          browser.logs.filter((entry) => entry.level === 'exception'),
          [],
        );
        assert.deepEqual(await browser.ev('window.fixture.calls'), []);
      } finally {
        await browser.close();
      }
    }
  }
} finally {
  await server.close();
}
writeFileSync(`${out}/results.json`, `${JSON.stringify(results, null, 2)}\n`);
console.log(`${results.length} views written to ${out}`);
