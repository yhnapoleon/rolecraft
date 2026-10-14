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

/** The checks after the brief page share one practice: start it once if needed. */
async function ensurePractice(context) {
  const { browser } = context;
  if (await browser.ev(`!!document.querySelector('.ws-toolbar')`)) return;
  await browser.click('.case-hero [data-action="take-case"]');
  await waitFor(browser, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
}

async function toBoard(context) {
  const { browser } = context;
  if (await browser.ev(`location.hash !== '#/work'`)) {
    await browser.goto(`${base}#/work`);
    await waitFor(browser, `!!document.querySelector('.board .card-open')`);
  }
}

const closeOverlays = (browser) =>
  browser.ev(`[...document.querySelectorAll('dialog[open]')].forEach((d) => d.close())`);

/** Visible text of the reader opened by a reference button: any open dialog but the sheet. */
const readerText = `[...document.querySelectorAll('dialog[open]:not(#sheet)')].map((d) => d.innerText).join('\\n')`;

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

const markdownItems = (text) =>
  text(['先给 20 人', '保留人工兜底'], ['Start with 20 people', 'Keep human fallback']);

/** F10: Markdown headings and lists render in a colleague's reply. */
async function markdownReply(context) {
  const { browser, text, shot } = context;
  await ensurePractice(context);
  await toBoard(context);
  await browser.click('.card-open');
  await waitFor(browser, `!!document.querySelector('#new-body')`);
  const heading = text('决定', 'Decision');
  await browser.type('#new-title', context.workTitle);
  await browser.type(
    '#new-body',
    text(
      '## 决定\n- 先给 20 人\n- 保留人工兜底',
      '## Decision\n- Start with 20 people\n- Keep human fallback',
    ),
  );
  await browser.clickText(text('保存为作品', 'Save as work'));
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
  await browser.click('.ol-row[data-type="work"]');
  await waitFor(browser, `!!document.querySelector('#editor-body')`);
  context.taskRoute = await browser.ev('location.hash');
  await browser.clickText(text('分享已保存的这版', 'Share this saved version'));
  await waitFor(browser, `!!document.querySelector('.rc-roles__turn .rc-roles__reply')`, 30000);
  const items = markdownItems(text);
  const reply = await browser.ev(`(() => {
    const turn = [...document.querySelectorAll('.rc-roles__turn')].at(-1);
    return {
      text: turn.innerText,
      headings: [...turn.querySelectorAll('h3')].map((h) => h.textContent),
      items: [...turn.querySelectorAll('li')]
        .filter((li) => !li.closest('.short-result__status'))
        .map((li) => li.textContent),
    };
  })()`);
  assert.ok(reply.headings.includes(heading), JSON.stringify(reply));
  assert.deepEqual(reply.items.slice(0, 2), items, JSON.stringify(reply));
  assert.doesNotMatch(reply.text, /^(## |- )/m);
  await shot('F10-reply');
}

/** F10: the reader opened from the delivery panel shows the same structure. */
async function markdownReader(context) {
  const { browser, text, shot } = context;
  const heading = text('决定', 'Decision');
  const items = markdownItems(text);
  await toBoard(context);
  await browser.click('.ws-toolbar [data-action="submit"]');
  await waitFor(browser, `!!document.querySelector('.native-feedback input[type="checkbox"]')`);
  await browser.click('.native-feedback input[type="checkbox"]');
  await browser.clickText(text('查看', 'View'), '#sheet .native-feedback button');
  await waitFor(browser, `${readerText}.includes(${JSON.stringify(context.workTitle)})`);
  const reader = await browser.ev(`(() => {
    const open = [...document.querySelectorAll('dialog[open]:not(#sheet)')];
    return {
      text: open.map((d) => d.innerText).join('\\n'),
      headings: open.flatMap((d) => [...d.querySelectorAll('h3')].map((h) => h.textContent)),
      items: open.flatMap((d) => [...d.querySelectorAll('li')].map((li) => li.textContent)),
    };
  })()`);
  assert.ok(reader.headings.includes(heading), JSON.stringify(reader));
  assert.deepEqual(reader.items, items, JSON.stringify(reader));
  assert.doesNotMatch(reader.text, /^(## |- )/m);
  await shot('F10-reader');
  await closeOverlays(browser);
}

const CHECKS = [
  ['F03', 'priority label keeps the task name', priorityLabel],
  ['F04', 'unmatched intake starts the reviewed situation', intakeFallback],
  ['F10', 'Markdown renders in a colleague reply', markdownReply],
  ['F10', 'Markdown renders in the version reader', markdownReader],
];

async function runLanguage(language) {
  const browser = await launch({ width: 1440, height: 1100, reduced: true });
  const text = (zh, en) => (language === 'en' ? en : zh);
  const shot = (name) => browser.shot(`${output}/screenshots/${language}-${name}.jpg`);
  const context = {
    browser,
    language,
    text,
    shot,
    workTitle: text('试点决定草稿', 'Pilot decision draft'),
    taskRoute: '',
  };
  try {
    await openEntry(context);
    // Every check reports on its own, so one run shows each item's state.
    for (const [id, name, check] of CHECKS) {
      if (only.size && !only.has(id)) continue;
      try {
        await check(context);
        results.push({ language, id, name, status: 'passed' });
        console.log(`PASS ${language}: ${id} ${name}`);
      } catch (error) {
        results.push({ language, id, name, status: 'failed', error: String(error) });
        console.log(`FAIL ${language}: ${id} ${name}\n${error}`);
        await shot(`${id}-failure`);
        writeFileSync(
          `${output}/${language}-${id}-failure.txt`,
          await browser.ev('document.body.innerText'),
        );
        await closeOverlays(browser);
      }
    }
    const exceptions = browser.logs.filter((item) => item.level === 'exception');
    results.push({
      language,
      name: 'no uncaught exceptions',
      status: exceptions.length ? 'failed' : 'passed',
      ...(exceptions.length ? { error: JSON.stringify(exceptions) } : {}),
    });
  } finally {
    await browser.close();
    writeFileSync(`${output}/result.json`, `${JSON.stringify(results, null, 2)}\n`);
  }
}

for (const language of ['zh', 'en']) await runLanguage(language);
process.exitCode = results.some((result) => result.status === 'failed') ? 1 : 0;
