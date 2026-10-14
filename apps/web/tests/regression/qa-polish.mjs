/** Walk-through polish checks in the normal v4 entry over real HTTP and workers, zh and en.
 *
 * Each check names the walk-through item it covers and fails on the code before its fix.
 * Run through the harness, which starts and stops the services on the given ports:
 *
 *   CHROME_BIN=... uv run --locked python -m scripts.regression.browser --suite qa-polish \
 *     --web-port <port> --api-port <port> --output <new dir>
 *
 * QA_CHECKS=F03,F04 limits the run to the named checks.
 */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { launch } from '../walkthrough/cdp.mjs';
import { waitFor } from './browser-support.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output, 'BASE and OUT are required');
mkdirSync(`${output}/screenshots`, { recursive: true });
const only = new Set((process.env.QA_CHECKS || '').split(',').filter(Boolean));
const results = [];

async function openEntry(context) {
  const { browser, language } = context;
  await browser.goto(base);
  await browser.ev(
    `localStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
  );
  await browser.goto(base);
  await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
  await browser.click('[data-action="open-career"]');
  await waitFor(browser, `!!document.querySelector('.case-hero select[data-change="triage"]')`);
}

/** F03: a ranked starting task keeps its own name as the label, never the option list. */
async function priorityLabel(context) {
  const { browser, text, shot } = context;
  const seed = `document.querySelectorAll('.case-hero .seed')[0]`;
  const title = await browser.ev(`${seed}.querySelector(':scope > span').textContent`);
  await browser.select('.case-hero select[data-change="triage"]', 'first', 0);
  const label = await browser.ev(`${seed}.querySelector('select').getAttribute('aria-label')`);
  const chosen = await browser.ev(`${seed}.querySelector('select').selectedOptions[0].textContent`);
  assert.equal(
    label,
    text(`「${title}」的优先级：${chosen}`, `Priority for “${title}”: ${chosen}`),
  );
  await shot('F03-priority');
}

/** F04: an unmatched description offers the reviewed situation directly. */
async function intakeFallback(context) {
  const { browser, text, shot } = context;
  await browser.ev(`document.querySelector('[data-intake]').open = true`);
  await browser.type(
    '#intake-text',
    text('我们想给外部顾客做商品推荐。', 'We want product recommendations for shoppers.'),
  );
  await browser.submit('[data-form="intake"]');
  await waitFor(browser, `!!document.querySelector('.intake-result')`);
  const before = await browser.ev('window.PracticeLive.state.attempts.length');
  const label = text('改练内部知识助手上线决定', 'Practise the knowledge assistant launch instead');
  const offered = await browser.ev(
    `[...document.querySelectorAll('.intake-result button')].map((b) => b.textContent.trim())`,
  );
  assert.deepEqual(offered, [label]);
  await shot('F04-intake');
  await browser.clickText(label, '.intake-result button');
  await waitFor(browser, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
  assert.equal(await browser.ev('window.PracticeLive.state.attempts.length'), before + 1);
  assert.equal(
    await browser.ev('window.PracticeLive.engine.getAttempt(window.PracticeLive.state).scenarioId'),
    'pilot',
  );
}

const CHECKS = [
  ['F03', 'priority label keeps the task name', priorityLabel],
  ['F04', 'unmatched intake starts the reviewed situation', intakeFallback],
];

async function runLanguage(language) {
  const browser = await launch({ width: 1440, height: 1100, reduced: true });
  const text = (zh, en) => (language === 'en' ? en : zh);
  const shot = (name) => browser.shot(`${output}/screenshots/${language}-${name}.jpg`);
  const context = { browser, language, text, shot };
  try {
    await openEntry(context);
    for (const [id, name, check] of CHECKS) {
      if (only.size && !only.has(id)) continue;
      await check(context);
      results.push({ language, id, name, status: 'passed' });
      console.log(`PASS ${language}: ${id} ${name}`);
    }
    assert.deepEqual(
      browser.logs.filter((item) => item.level === 'exception'),
      [],
    );
  } catch (error) {
    results.push({ language, status: 'failed', error: String(error) });
    await shot('failure');
    writeFileSync(`${output}/${language}-failure.txt`, await browser.ev('document.body.innerText'));
    throw error;
  } finally {
    await browser.close();
    writeFileSync(`${output}/result.json`, `${JSON.stringify(results, null, 2)}\n`);
  }
}

for (const language of ['zh', 'en']) await runLanguage(language);
