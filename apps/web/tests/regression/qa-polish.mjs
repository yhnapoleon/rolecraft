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
import { delay, launch } from '../walkthrough/cdp.mjs';
import { clickReady, waitFor } from './browser-support.mjs';

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

const active = `window.PracticeLive.engine.getAttempt(window.PracticeLive.state)`;
const status = `window.PracticeLive.store.active()?.world.status`;

/** The checks after the brief page share one practice: start it once if needed. */
async function ensurePractice(context) {
  const { browser } = context;
  if (await browser.ev(`!!${active}`)) return;
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

/** Opening the brief records its passages as read, so they can be cited as evidence. */
async function readBrief(context) {
  const { browser } = context;
  const cached = `(window.PracticeLive.v4Host(${active}).draft('workspace', 'evidence-cache') ?? []).length`;
  if (await browser.ev(`${cached} > 0`)) return;
  await toBoard(context);
  await browser.click('.doc-card[data-id="brief"]');
  await waitFor(browser, `location.hash.startsWith('#/doc/') && ${cached} > 0`);
  await toBoard(context);
}

/** A saved work version to submit, created once when no earlier check made one. */
async function ensureWork(context) {
  const { browser, text } = context;
  await ensurePractice(context);
  await readBrief(context);
  if (await browser.ev(`window.PracticeLive.store.active().v2Workspace.products.length > 0`))
    return;
  await toBoard(context);
  await browser.click('.card-open');
  await waitFor(browser, `!!document.querySelector('#new-body')`);
  await browser.type('#new-title', context.workTitle);
  await browser.type('#new-body', text('先给 20 人试点。', 'Pilot with 20 people first.'));
  await browser.clickText(text('保存为作品', 'Save as work'));
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
}

/** Opens the delivery panel, selects the first work version and submits a decision. */
async function submitOnce(context, decision) {
  const { browser, text } = context;
  await closeOverlays(browser);
  await toBoard(context);
  await browser.click('.ws-toolbar [data-action="submit"]');
  await waitFor(
    browser,
    `!!document.querySelector('#sheet .native-feedback input[type="checkbox"]')`,
  );
  await browser.ev(`(() => {
    const box = document.querySelector('#sheet .native-feedback input[type="checkbox"]');
    if (!box.checked) box.click();
  })()`);
  await browser.select('#sheet .native-feedback select', decision);
  await clickReady(browser, text('提交选中的版本', 'Submit selected versions'), '#sheet button');
  await waitFor(browser, `${status} === 'submitted'`, 20000);
}

async function ensureSubmitted(context) {
  if ((await context.browser.ev(status)) === 'submitted') return;
  await ensureWork(context);
  await submitOnce(context, 'defer_with_conditions');
}

/** The review page with the feedback of every submission so far. */
async function openReview(context, reports = 1) {
  const { browser, text } = context;
  await closeOverlays(browser);
  await browser.goto(`${base}#/review`);
  await waitFor(
    browser,
    `document.querySelectorAll('.native-feedback [aria-label="${text('分段反馈', 'Feedback sections')}"] > article').length >= ${reports}`,
    40000,
  );
}

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

/** No record id (32 hex digits) is shown anywhere in this part of the page. */
const RECORD_ID = /[0-9a-f]{32}/;

/** F13: the saved snapshot names its work; the history never shows a record id. */
async function snapshotNames(context) {
  const { browser, text, shot } = context;
  await ensureWork(context);
  await submitOnce(context, 'defer_with_conditions');
  const heading = text('已保存的提交快照', 'Saved submission snapshot');
  await waitFor(
    browser,
    `[...document.querySelectorAll('#sheet h3')].some((h) => h.textContent.startsWith(${JSON.stringify(heading)}))`,
  );
  const receipt = await browser.ev(`(() => {
    const h = [...document.querySelectorAll('#sheet h3')]
      .find((node) => node.textContent.startsWith(${JSON.stringify(heading)}));
    return h.parentElement.innerText;
  })()`);
  assert.ok(receipt.includes(context.workTitle), receipt);
  assert.doesNotMatch(receipt, RECORD_ID);
  await shot('F13-receipt');
  await openReview(context);
  const history = text('查看评审与提交历史', 'Review and submission history');
  await browser.clickText(history, '.native-feedback summary');
  const rows = await browser.ev(`(() => {
    const summary = [...document.querySelectorAll('.native-feedback summary')]
      .find((node) => node.textContent === ${JSON.stringify(history)});
    return summary.parentElement.innerText;
  })()`);
  assert.doesNotMatch(rows, RECORD_ID);
  assert.ok(
    rows.includes(text('查看第 1 次交付的快照', 'View the snapshot of submission 1')),
    rows,
  );
  await shot('F13-history');
}

/** The general response form of the latest feedback, opened; returns its selector. */
async function openResponseForm(context) {
  const { browser, text } = context;
  await ensureSubmitted(context);
  await openReview(context);
  const sections = `[aria-label="${text('分段反馈', 'Feedback sections')}"]`;
  const formId = await browser.ev(`(() => {
    const latest = document.querySelector('.native-feedback ${sections} > article');
    const form = [...latest.querySelectorAll(':scope > details[data-response-id]')].at(-1);
    form.open = true;
    return form.dataset.responseId;
  })()`);
  return {
    id: formId,
    form: `document.querySelector('details[data-response-id="${formId}"]')`,
  };
}

async function typeResponse(browser, form, words) {
  await browser.ev(`(() => {
    const box = ${form}.querySelector('textarea');
    box.focus();
    box.value = ${JSON.stringify(words)};
    box.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
}

/** F18: a confirmed supplement shows as recorded the moment its form clears. */
async function supplementEcho(context) {
  const { browser, text, shot } = context;
  const { id, form } = await openResponseForm(context);
  const words = text(
    '补充：政策更新后我复测过酒店上限。',
    'Supplement: I retested the hotel limit after the update.',
  );
  await typeResponse(browser, form, words);
  await browser.clickText(
    text('选择已获准的原始引用', 'Choose authorized original references'),
    `details[data-response-id="${id}"] button`,
  );
  await waitFor(
    browser,
    `!!document.querySelector('dialog[open]:not(#sheet) input[type="checkbox"]')`,
  );
  await browser.click('dialog[open]:not(#sheet) input[type="checkbox"]');
  await browser.clickText(
    text('使用选中的依据', 'Use selected evidence'),
    'dialog[open]:not(#sheet) button',
  );
  const recorded = text(
    '补证已记录 · 等待核验',
    'Additional evidence recorded · Awaiting verification',
  );
  await browser.ev(`${form}.querySelector('[data-response-action="supplement"]').click()`);
  // Read the form and the history in one frame: the echo must arrive with the reset.
  let seen;
  for (let n = 0; n < 200; n++) {
    seen = await browser.ev(`(() => {
      const box = ${form}?.querySelector('textarea');
      return {
        cleared: box?.value === '',
        form: !!${form}?.innerText.includes(${JSON.stringify(recorded)}),
        listed: document.querySelector('.native-feedback').innerText.includes(${JSON.stringify(words)}),
      };
    })()`);
    if (seen.cleared) break;
    await delay(25);
  }
  assert.deepEqual(seen, { cleared: true, form: true, listed: true });
  await delay(2500);
  const listed = await browser.ev(
    `document.querySelector('.native-feedback').innerText.split(${JSON.stringify(words)}).length - 1`,
  );
  assert.equal(listed, 1, 'the recorded supplement is listed once after the next refresh');
  await shot('F18-supplement');
}

/** F18: a supplement without an original reference is stopped before anything is sent. */
async function supplementNeedsReference(context) {
  const { browser, text } = context;
  const { form } = await openResponseForm(context);
  const words = text('只有文字的补证。', 'A supplement with text only.');
  await typeResponse(browser, form, words);
  const sent = await browser.ev('window.qaWrites.length');
  await browser.ev(`${form}.querySelector('[data-response-action="supplement"]').click()`);
  const message = text(
    '补证需要先选择至少一处原始引用。',
    'Choose at least one original reference before submitting evidence.',
  );
  await waitFor(
    browser,
    `[...document.querySelectorAll('.native-feedback [role="alert"]')].some((n) => !n.hidden && n.textContent === ${JSON.stringify(message)})`,
  );
  assert.equal(await browser.ev(`${form}.querySelector('textarea').value`), words);
  const requests = await browser.ev(
    `window.qaWrites.slice(${sent}).filter((url) => url.includes('/responses'))`,
  );
  assert.deepEqual(requests, []);
}

/** F19: feedback and history name each delivery by its round. */
async function deliveryRounds(context) {
  const { browser, text, shot } = context;
  await ensureSubmitted(context);
  await openReview(context);
  await browser.type(
    `textarea[aria-label="${text('这次准备怎样修订', 'What will you revise?')}"]`,
    text('补一轮测试再交付。', 'Add a round of tests, then submit again.'),
  );
  await clickReady(browser, text('开始修订', 'Start a revision'));
  await waitFor(browser, `${status} === 'active'`, 20000);
  await submitOnce(context, 'no_go');
  await openReview(context, 2);
  const sections = `[aria-label="${text('分段反馈', 'Feedback sections')}"]`;
  const labels = await browser.ev(
    `[...document.querySelectorAll('.native-feedback ${sections} > article')].map((a) => a.querySelector('button').textContent)`,
  );
  assert.deepEqual(labels, text(['第 2 次交付', '第 1 次交付'], ['Submission 2', 'Submission 1']));
  const history = text('查看评审与提交历史', 'Review and submission history');
  await browser.clickText(history, '.native-feedback summary');
  const rows = await browser.ev(`(() => {
    const summary = [...document.querySelectorAll('.native-feedback summary')]
      .find((node) => node.textContent === ${JSON.stringify(history)});
    return [...summary.parentElement.querySelectorAll('button')].map((b) => b.textContent);
  })()`);
  for (const n of [1, 2])
    assert.ok(
      rows.includes(text(`查看第 ${n} 次交付的快照`, `View the snapshot of submission ${n}`)),
      JSON.stringify(rows),
    );
  assert.ok(!rows.some((row) => RECORD_ID.test(row)), JSON.stringify(rows));
  await shot('F19-rounds');
}

const CHECKS = [
  ['F03', 'priority label keeps the task name', priorityLabel],
  ['F04', 'unmatched intake starts the reviewed situation', intakeFallback],
  ['F10', 'Markdown renders in a colleague reply', markdownReply],
  ['F10', 'Markdown renders in the version reader', markdownReader],
  ['F13', 'the snapshot names its work and hides record ids', snapshotNames],
  ['F18', 'a supplement is echoed as recorded at once', supplementEcho],
  ['F18', 'a supplement without a reference is stopped before sending', supplementNeedsReference],
  ['F19', 'feedback names each delivery by its round', deliveryRounds],
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
  // Every write request the page sends, so a check can prove that nothing was sent.
  await browser.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => {
      const send = window.fetch.bind(window);
      window.qaWrites = [];
      window.fetch = (input, options) => {
        if ((options?.method || 'GET') !== 'GET')
          window.qaWrites.push(typeof input === 'string' ? input : input.url);
        return send(input, options);
      };
    })()`,
  });
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
