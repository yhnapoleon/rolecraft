/** Walk-through polish checks in the normal v4 entry over real HTTP and workers, zh and en.
 *
 * Each check names the walk-through item it covers and fails on the code before its fix.
 * Run through the harness, which starts and stops the services on the given ports:
 *
 *   CHROME_BIN=... uv run --locked python -m scripts.regression.browser --suite qa-polish \
 *     --web-port <port> --api-port <port> --output <new dir>
 *
 * QA_CHECKS=F03,F04 limits the run to the named checks. QA_MOTION=default runs with the
 * system's default motion instead of reduced motion.
 */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { delay, launch } from '../walkthrough/cdp.mjs';
import { clickReady, waitFor, submitDelivery } from './browser-support.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output, 'BASE and OUT are required');
mkdirSync(`${output}/screenshots`, { recursive: true });
const only = new Set((process.env.QA_CHECKS || '').split(',').filter(Boolean));
const reduced = process.env.QA_MOTION !== 'default';
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

/** Opens the delivery panel, selects the work written in these checks (or the first
 * version listed) and submits a decision; returns the selected version's label. */
async function submitOnce(context, decision) {
  const { browser } = context;
  await closeOverlays(browser);
  await toBoard(context);
  await browser.click('.ws-toolbar [data-action="submit"]');
  await waitFor(
    browser,
    `!!document.querySelector('#sheet .native-feedback input[type="checkbox"]')`,
  );
  const chosen = await browser.ev(`(() => {
    const rows = [...document.querySelectorAll('#sheet .native-feedback label.field-row')]
      .filter((row) => row.querySelector('input[type="checkbox"]'));
    // Each version reads as a paper slip: its title, with the version small.
    const line = (r) => r.querySelector('.paper-slip__title')?.textContent ?? r.textContent;
    const row =
      rows.find((r) => line(r).includes(${JSON.stringify(context.workTitle)})) ?? rows[0];
    const box = row.querySelector('input[type="checkbox"]');
    if (!box.checked) box.click();
    return line(row);
  })()`);
  await browser.click(
    `#sheet .native-feedback [data-decision-cards] .decision-card[data-decision="${decision}"] input`,
  );
  await submitDelivery(browser);
  await waitFor(browser, `${status} === 'submitted'`, 20000);
  return chosen;
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

/** The pilot settings are saved once, so the assistant can answer test questions. */
async function ensureConfigured(context) {
  const { browser } = context;
  await ensurePractice(context);
  if (await browser.ev(`${active}.backend.configured`)) return;
  await toBoard(context);
  await browser.click('.product-bar [data-action="config"]');
  await browser.submit('[data-form="config"]');
  await waitFor(browser, `!document.querySelector('#sheet').open && ${active}.backend.configured`);
}

/** The Agent tab, on a task's workbench (by board order) or on the board itself. */
async function openAgent(context, taskIndex) {
  const { browser } = context;
  await ensurePractice(context);
  await closeOverlays(browser);
  await toBoard(context);
  if (taskIndex !== undefined) {
    await browser.click('.card-open', taskIndex);
    await waitFor(browser, `location.hash.startsWith('#/task/')`);
  }
  await browser.click('.rail-tabs [data-tab="agent"]');
  await waitFor(browser, `!!document.querySelector('#import-content')`);
}

/** Copy may be blocked in a headless browser; download hands the package over too. */
async function handOver(context) {
  const { browser } = context;
  const before = await browser.ev(`(${active}.exports || []).length`);
  await browser.click('[data-action="download-package"]');
  await waitFor(browser, `(${active}.exports || []).length === ${before + 1}`);
  return browser.ev(`${active}.exports.at(-1).requestId`);
}

async function previewReturn(context, data) {
  const { browser } = context;
  await browser.type('#import-content', JSON.stringify(data));
  await browser.submit('[data-form="import"]');
  await waitFor(browser, `document.querySelector('#sheet').open`);
}

const importButton = `document.querySelector('#sheet [data-action="confirm-import"]')`;
const productTask = (returnId) =>
  `window.PracticeLive.store.active().v2Workspace.products.find((p) => p.source_return_id === ${JSON.stringify(returnId)})?.task?.object_id`;

/** F29: the two Agent buttons say what each does. */
async function agentLabels(context) {
  const { browser, text, shot } = context;
  await openAgent(context, 0);
  const labels = await browser.ev(`[
    document.querySelector('[data-action="package"]').textContent.trim(),
    document.querySelector('#import-form [type="submit"]').textContent.trim(),
  ]`);
  assert.deepEqual(labels, text(['查看', '预览'], ['View package', 'Preview return']));
  await shot('F29-agent');
}

/** F28: each document in the task package carries its text once (the brief always goes). */
async function packageDocuments(context) {
  const { browser } = context;
  await openAgent(context, 0);
  await browser.click('[data-action="package"]');
  await waitFor(browser, `!!document.querySelector('#package-text')`);
  const pkg = JSON.parse(await browser.ev(`document.querySelector('#package-text').value`));
  assert.ok(pkg.materials.length >= 1);
  for (const material of pkg.materials)
    assert.deepEqual(
      Object.keys(material).filter((key) => key === 'content' || key === 'body'),
      ['content'],
      JSON.stringify(Object.keys(material)),
    );
  await closeOverlays(browser);
}

/** F31: a return naming a package that was never handed over is stopped in the preview. */
async function returnPrecheck(context) {
  const { browser, text, shot } = context;
  await openAgent(context, 0);
  const writes = await browser.ev('window.qaWrites.length');
  await previewReturn(context, {
    schemaVersion: 1,
    returnId: 'qa-return-unmatched',
    requestId: 'request-never-handed-over',
    artifact: { kind: 'text', title: 'Unmatched', purpose: '探索笔记', body: 'Text' },
  });
  const sheet = await browser.ev(`document.querySelector('#sheet').innerText`);
  assert.ok(sheet.includes(text('找不到对应的任务包', 'No matching task package')), sheet);
  assert.ok(await browser.ev(`!${importButton} || ${importButton}.disabled`));
  await shot('F31-precheck');
  await closeOverlays(browser);
  assert.deepEqual(
    await browser.ev(
      `window.qaWrites.slice(${writes}).filter((url) => url.includes('/work-products'))`,
    ),
    [],
  );
}

/** F25: a return is filed under its package's task, or where the person chooses. */
async function returnTaskChoice(context) {
  const { browser, text, shot } = context;
  await openAgent(context, 1);
  const packageTask = {
    id: await browser.ev(`decodeURIComponent(location.hash.slice('#/task/'.length))`),
    title: await browser.ev(`document.querySelector('.crumb-now').textContent`),
  };
  const requestId = await handOver(context);
  await openAgent(context);
  await previewReturn(context, {
    schemaVersion: 1,
    returnId: 'qa-return-package',
    requestId,
    artifact: { kind: 'text', title: 'For the package task', purpose: '探索笔记', body: 'Text' },
  });
  const named = text(`「${packageTask.title}」`, `“${packageTask.title}”`);
  const sheet = await browser.ev(`document.querySelector('#sheet').innerText`);
  assert.ok(sheet.includes(named), sheet);
  assert.equal(
    await browser.ev(`!!document.querySelector('#sheet select[data-change="return-task"]')`),
    false,
  );
  await shot('F25-package-task');
  await browser.click('#sheet [data-action="confirm-import"]');
  await waitFor(
    browser,
    `${productTask('qa-return-package')} === ${JSON.stringify(packageTask.id)}`,
  );
  await openAgent(context);
  await previewReturn(context, {
    schemaVersion: 1,
    returnId: 'qa-return-unlinked',
    artifact: { kind: 'text', title: 'Unlinked', purpose: '探索笔记', body: 'Text' },
  });
  const choice = `document.querySelector('#sheet select[data-change="return-task"]')`;
  assert.equal(await browser.ev(`${choice}.value`), '');
  assert.equal(await browser.ev(`${importButton}.disabled`), true);
  await shot('F25-choose-task');
  const chosen = await browser.ev(`${choice}.options[${choice}.options.length - 1].value`);
  await browser.select('#sheet select[data-change="return-task"]', chosen);
  assert.equal(await browser.ev(`${importButton}.disabled`), false);
  await browser.click('#sheet [data-action="confirm-import"]');
  await waitFor(browser, `${productTask('qa-return-unlinked')} === ${JSON.stringify(chosen)}`);
}

/** F30: running a plan's questions counts as linked tests on its lifecycle strip. */
async function planLinkedRuns(context) {
  const { browser, text, shot } = context;
  await ensureConfigured(context);
  await openAgent(context, 0);
  const requestId = await handOver(context);
  await previewReturn(context, {
    schemaVersion: 1,
    returnId: 'qa-return-plan',
    requestId,
    artifact: {
      kind: 'test_set',
      title: text('上线前检查', 'Pilot readiness checks'),
      purpose: '测试计划',
      cases: [
        {
          question: text('国内出差住宿每晚报销上限是多少？', 'What is the nightly hotel limit?'),
          intent: text('核对政策版本', 'Check the policy version'),
          refs: [],
        },
      ],
    },
  });
  await browser.click('#sheet [data-action="confirm-import"]');
  await waitFor(browser, `!!document.querySelector('.agent-strip [data-action="adopt"]')`);
  await browser.click('.agent-strip [data-action="adopt"]');
  await waitFor(browser, `!!document.querySelector('[data-action="test-run"]:not([disabled])')`);
  const plan = await browser.ev(
    `window.PracticeLive.store.active().v2Workspace.products.find((p) => p.source_return_id === 'qa-return-plan').product_id`,
  );
  await browser.click('[data-action="test-run"]');
  await waitFor(
    browser,
    `${active}.tests.some((t) => t.workId === ${JSON.stringify(plan)})`,
    20000,
  );
  const linked = text('关联测试 1 次', '1 linked test');
  await waitFor(
    browser,
    `[...document.querySelectorAll('.agent-strip li')].some((li) => li.textContent === ${JSON.stringify(linked)} && li.classList.contains('done'))`,
  );
  await shot('F30-linked');
}

/** No record id (32 hex digits) is shown anywhere in this part of the page. */
const RECORD_ID = /[0-9a-f]{32}/;

/** F13: the saved snapshot names its work; the history never shows a record id. */
async function snapshotNames(context) {
  const { browser, text, shot } = context;
  await ensureWork(context);
  const submitted = await submitOnce(context, 'defer_with_conditions');
  // A confirmed delivery is stamped and handed over to the results page, whose cover is the
  // saved snapshot: the delivery's name and the exact versions it attached.
  await waitFor(
    browser,
    `location.hash === '#/review' && !!document.querySelector('[data-result-cover] .result-cover__slip')
      && document.querySelector('[data-result-cover] .result-cover__title')?.textContent === ${JSON.stringify(text('第 1 次交付', 'Delivery 1'))}`,
    20000,
  );
  const receipt = await browser.ev(`document.querySelector('[data-result-cover]').innerText`);
  // The slip names the work; the snapshot names that work and the delivery as every evidence
  // button does.
  const title = submitted;
  assert.ok(receipt.includes(title), JSON.stringify({ receipt, submitted }));
  assert.ok(receipt.includes(text('第 1 次交付', 'Delivery 1')), receipt);
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
  assert.ok(rows.includes(text('查看第 1 次交付的快照', 'View the snapshot of Delivery 1')), rows);
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
    text('选择依据', 'Choose evidence'),
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
  assert.deepEqual(labels, text(['第 2 次交付', '第 1 次交付'], ['Delivery 2', 'Delivery 1']));
  const history = text('查看评审与提交历史', 'Review and submission history');
  await browser.clickText(history, '.native-feedback summary');
  const rows = await browser.ev(`(() => {
    const summary = [...document.querySelectorAll('.native-feedback summary')]
      .find((node) => node.textContent === ${JSON.stringify(history)});
    return [...summary.parentElement.querySelectorAll('button')].map((b) => b.textContent);
  })()`);
  for (const n of [1, 2])
    assert.ok(
      rows.includes(text(`查看第 ${n} 次交付的快照`, `View the snapshot of Delivery ${n}`)),
      JSON.stringify(rows),
    );
  assert.ok(!rows.some((row) => RECORD_ID.test(row)), JSON.stringify(rows));
  await shot('F19-rounds');
  // The delivery opens under its own name, with the decision in words, not its code.
  const latest = text('第 2 次交付', 'Delivery 2');
  await browser.clickText(latest, `.native-feedback ${sections} > article button`);
  const reader = `[...document.querySelectorAll('[data-reference-reader], dialog[open]:not(#sheet)')]`;
  await waitFor(
    browser,
    `${reader}.some((n) => n.querySelector('h2')?.textContent === ${JSON.stringify(latest)})`,
  );
  const opened = await browser.ev(`${reader}.map((n) => n.innerText).join('\\n')`);
  assert.doesNotMatch(opened, /no_go|defer_with_conditions|launch_narrow/);
  await shot('F19-reader');
}

const CHECKS = [
  ['F03', 'priority label keeps the task name', priorityLabel],
  ['F04', 'unmatched intake starts the reviewed situation', intakeFallback],
  ['F10', 'Markdown renders in a colleague reply', markdownReply],
  ['F10', 'Markdown renders in the version reader', markdownReader],
  ['F29', 'the two Agent buttons say what each does', agentLabels],
  ['F28', 'package documents carry their text once', packageDocuments],
  ['F31', 'an unmatched return is stopped in the preview', returnPrecheck],
  ['F25', 'a return is filed under its package task or a chosen one', returnTaskChoice],
  ['F30', 'running a plan counts as linked tests', planLinkedRuns],
  ['F13', 'the snapshot names its work and hides record ids', snapshotNames],
  ['F18', 'a supplement is echoed as recorded at once', supplementEcho],
  ['F18', 'a supplement without a reference is stopped before sending', supplementNeedsReference],
  ['F19', 'feedback names each delivery by its round', deliveryRounds],
];

async function runLanguage(language) {
  const browser = await launch({ width: 1440, height: 1100, reduced });
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

/** Overlap and overflow at phone width, measured from the laid-out boxes. */
const layout = `(() => {
  const box = (node) => node && node.getBoundingClientRect();
  const title = box(document.querySelector('.ws-toolbar .title-btn'));
  const team = box(document.querySelector('.ws-toolbar .team-btn'));
  const chips = [...document.querySelectorAll('.pb-state li, .console-state li')]
    .filter((li) => li.offsetParent !== null)
    .map((li) => ({
      text: li.textContent,
      clipped: li.scrollHeight > li.clientHeight + 1 || li.scrollWidth > li.clientWidth + 1,
      outside: box(li).right > box(li.parentElement).right + 1,
    }));
  return {
    titleOverlap: title && team ? Math.max(0, title.right - team.left) : 0,
    chips,
    pageScroll: document.documentElement.scrollWidth > window.innerWidth,
  };
})()`;

/** F27: at 390 px the board title is not under the team avatars and long labels fit. */
async function narrowLayout(language) {
  const browser = await launch({ width: 390, height: 844, mobile: true, reduced });
  const text = (zh, en) => (language === 'en' ? en : zh);
  const shot = (name) => browser.shot(`${output}/screenshots/${language}-${name}.jpg`);
  const context = { browser, language, text, shot };
  try {
    await openEntry(context);
    await ensurePractice(context);
    const board = await browser.ev(layout);
    assert.equal(board.titleOverlap, 0, JSON.stringify(board));
    assert.ok(board.chips.length >= 3, JSON.stringify(board));
    assert.deepEqual(
      board.chips.filter((chip) => chip.clipped || chip.outside),
      [],
      JSON.stringify(board),
    );
    assert.equal(board.pageScroll, false);
    await shot('F27-board-390');
    await browser.click('.product-bar [data-action="open-bench"]');
    await waitFor(browser, `!!document.querySelector('.console-state li')`);
    const bench = await browser.ev(layout);
    assert.deepEqual(
      bench.chips.filter((chip) => chip.clipped || chip.outside),
      [],
      JSON.stringify(bench),
    );
    assert.equal(bench.pageScroll, false);
    await shot('F27-bench-390');
    results.push({ language, id: 'F27', name: '390 px title and labels', status: 'passed' });
    console.log(`PASS ${language}: F27 390 px title and labels`);
  } catch (error) {
    results.push({ language, id: 'F27', status: 'failed', error: String(error) });
    console.log(`FAIL ${language}: F27 390 px title and labels\n${error}`);
    await shot('F27-failure');
  } finally {
    await browser.close();
    writeFileSync(`${output}/result.json`, `${JSON.stringify(results, null, 2)}\n`);
  }
}

for (const language of ['zh', 'en']) await runLanguage(language);
for (const language of ['zh', 'en'])
  if (!only.size || only.has('F27')) await narrowLayout(language);
process.exitCode = results.some((result) => result.status === 'failed') ? 1 : 0;
