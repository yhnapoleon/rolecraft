/** Explicit known-defect checks, separate from unchanged-behavior regression. */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { launch } from '../walkthrough/cdp.mjs';
import { waitFor } from './browser-support.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output);
mkdirSync(`${output}/screenshots`, { recursive: true });
const results = [];

for (const language of ['zh', 'en']) {
  const browser = await launch({ width: 1440, height: 1100, reduced: true });
  try {
    await browser.goto(base);
    await browser.ev(
      `localStorage.clear();
      localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
    );
    await browser.goto(base);
    await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
    await browser.click('[data-action="open-career"]');
    await browser.click('.case-hero [data-action="take-case"]');
    await waitFor(browser, `!!document.querySelector('.product-bar')`);
    await browser.click('.product-bar [data-action="config"]');
    await browser.submit('[data-form="config"]');
    await waitFor(
      browser,
      `!document.querySelector('#sheet').open && !!document.querySelector('.world-event')`,
    );
    await browser.shot(`${output}/screenshots/${language}-policy-before.jpg`);
    const before = await browser.ev('window.PracticeLive.store.active().v2Workspace.tasks.length');
    await browser.click('.world-event [data-action="situation-task"]');
    await waitFor(
      browser,
      `window.PracticeLive.store.active().v2Workspace.tasks.length === ${before + 1}`,
      6000,
    );
    await waitFor(browser, `location.hash.startsWith('#/task/')`);
    await browser.goto(`${base}#/work`);
    await waitFor(browser, `!!document.querySelector('.board')`);
    assert.equal(
      await browser.ev('window.PracticeLive.store.active().v2Workspace.tasks.length'),
      before + 1,
    );
    assert.equal(await browser.ev(`!!document.querySelector('.world-event')`), false);
    await browser.click('[data-menu="more"]');
    await browser.click('[data-action="about"]');
    const about = await browser.ev('document.querySelector("#sheet").innerText');
    assert.ok(about.includes(language === 'zh' ? '事项、作品版本' : 'Tasks, work versions'));
    assert.ok(
      !about.includes(
        language === 'zh' ? 'MCP 直连、模型评审' : 'direct MCP connection, model-based review',
      ),
    );
    await browser.shot(`${output}/screenshots/${language}-about.jpg`);
    results.push({ language, status: 'passed' });
  } catch (error) {
    results.push({ language, status: 'failed', error: String(error) });
    await browser.shot(`${output}/screenshots/${language}-failure.jpg`);
    writeFileSync(`${output}/${language}-failure.txt`, await browser.ev('document.body.innerText'));
  } finally {
    await browser.close();
  }
}
writeFileSync(`${output}/result.json`, `${JSON.stringify(results, null, 2)}\n`);
console.log(JSON.stringify(results));
process.exitCode = results.some((result) => result.status === 'failed') ? 1 : 0;
