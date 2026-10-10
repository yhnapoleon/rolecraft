/** Normal v4 entry over real HTTP and worker: save → outcome preview → change a condition →
 * earlier preview marked → explicit actions shown beside the unchanged prediction. zh and en,
 * desktop and 390px. Needs BASE (web origin with API proxy) and OUT; CHROME_BIN for cdp. */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { waitFor } from '../../../../tests/regression/browser-support.mjs';
import { delay, launch } from '../../../../tests/walkthrough/cdp.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output, 'BASE and OUT are required');
mkdirSync(`${output}/screenshots`, { recursive: true });
const results = [];
const BLOCK = '[data-v4-insertion="outcome"] [data-outcome-preview]';
const block = `document.querySelector(${JSON.stringify(BLOCK)})`;
const host = `(() => {
  const live = window.PracticeLive;
  return live.v4Host(live.engine.getAttempt(live.state));
})()`;

async function capture(browser, language, name) {
  await browser.ev('document.fonts.ready.then(() => true)');
  await waitFor(browser, '!window.PracticeLive.store.getSnapshot().busy');
  await browser.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 0, y: 0 });
  await waitFor(browser, `!document.querySelector('#toast.visible')`, 20000);
  await browser.ev(`${block}?.scrollIntoView({ block: 'start' })`);
  await delay(300);
  await browser.shot(`${output}/screenshots/${language}-${name}.jpg`);
  await browser.send('Emulation.setDeviceMetricsOverride', {
    width: 390,
    height: 844,
    deviceScaleFactor: 2,
    mobile: true,
    screenWidth: 390,
    screenHeight: 844,
  });
  await delay(600);
  await waitFor(browser, `!!${block}`);
  assert.equal(
    await browser.ev('document.documentElement.scrollWidth > document.documentElement.clientWidth'),
    false,
    'No horizontal scroll at 390px',
  );
  await browser.ev(`${block}.scrollIntoView({ block: 'start' })`);
  await delay(300);
  await browser.shot(`${output}/screenshots/${language}-${name}-390.jpg`);
  const later = `${block}.querySelector('[data-outcome-actual], .w03-outcome-earlier')`;
  if (await browser.ev(`!!${later}`)) {
    await browser.ev(`${later}.scrollIntoView({ block: 'start' })`);
    await delay(300);
    await browser.shot(`${output}/screenshots/${language}-${name}-390-more.jpg`);
  }
  await browser.send('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 1100,
    deviceScaleFactor: 2,
    mobile: false,
    screenWidth: 1440,
    screenHeight: 1100,
  });
  await delay(600);
}

const blockState = `(() => {
  const node = ${block};
  if (!node) return null;
  const text = (selector) =>
    [...node.querySelectorAll(selector)].map((item) => item.textContent.trim());
  return {
    status: node.dataset.outcomePreview,
    badge: node.querySelector('[data-outcome-status]')?.textContent,
    meta: node.querySelector('.w03-outcome-meta')?.textContent,
    kinds: [...node.querySelectorAll(':scope > .w03-outcome-items [data-outcome-kind]')].map(
      (item) => item.dataset.outcomeKind,
    ),
    lines: text(':scope > .w03-outcome-items li'),
    question: text(':scope > [data-outcome-question] p'),
    changes: text(':scope > [data-outcome-changes] li'),
    actual: text(':scope > [data-outcome-actual] li'),
    links: [...node.querySelectorAll('.w03-outcome-links button')].map((b) => b.dataset.action),
    earlier: text('.w03-outcome-earlier-item > summary'),
  };
})()`;

async function openWork(browser) {
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
  await browser.click('.ol-row[data-type="work"]');
  await waitFor(browser, `!!document.querySelector('#editor-body')`);
}

async function runLanguage(language) {
  const browser = await launch({ width: 1440, height: 1100, reduced: true });
  const en = language === 'en';
  const text = (zh, english) => (en ? english : zh);
  const step = async (name, action) => {
    await action();
    results.push({ language, name, status: 'passed' });
    console.log(`PASS ${language}: ${name}`);
  };
  const states = {};
  try {
    await browser.goto(base);
    await browser.ev(
      `localStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
    );
    await browser.goto(base);
    await step('save a pilot decision and see its outcome preview', async () => {
      await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
      await browser.click('[data-action="open-career"]');
      await browser.click('.case-hero [data-action="take-case"]');
      await waitFor(
        browser,
        `location.hash === '#/work' && !!document.querySelector('.card-open')`,
      );
      const task = await browser.ev(
        `document.querySelector('.card-open .card-title')?.textContent`,
      );
      await browser.click('.card-open');
      await waitFor(browser, `!!document.querySelector('#new-body')`);
      await browser.type('#new-title', text('试点决定草稿', 'Pilot decision draft'));
      await browser.type(
        '#new-body',
        text('先小范围试点，保留人工兜底。', 'Start with a small pilot and keep human fallback.'),
      );
      await browser.select('[data-new="purpose"]', '试点决定');
      await browser.clickText(text('保存为作品', 'Save as work'));
      await openWork(browser);
      await waitFor(browser, `${block}?.dataset.outcomePreview === 'current'`, 20000);
      const state = await browser.ev(blockState);
      states.saved = state;
      assert.equal(state.badge, text('当前预览', 'Current preview'));
      assert.deepEqual(state.kinds, ['fact', 'conditional_prediction', 'pending_verification']);
      assert.ok(state.meta.includes(text('按第 1 版计算', 'Computed for v1')));
      assert.ok(state.meta.includes(text('等待模型接入', 'Awaiting model connection')));
      assert.equal(state.question.length, 1);
      assert.ok(task && state.question[0].includes(task), 'The question names the current task');
      for (const action of ['config', 'resources', 'submit'])
        assert.ok(state.links.includes(action), `link to ${action}`);
      // The preview itself executed nothing: configuration and resources are unchanged.
      const timeline = await browser.ev(`${host}.query('timeline')`);
      assert.equal(timeline.workspace.config.config_version, 0);
      await capture(browser, language, 'preview-saved');
    });
    await step('apply settings from the linked tool and run a test', async () => {
      await browser.click(`${BLOCK} .w03-outcome-links [data-action="config"]`);
      await waitFor(browser, `!!document.querySelector('#config-form [name="participants"]')`);
      await browser.type('#config-form [name="participants"]', '25');
      await browser.click('[form="config-form"][type="submit"]');
      await waitFor(browser, `!document.querySelector('#sheet').open`);
      await waitFor(
        browser,
        `${host}.query('timeline').then((t) => t.workspace.config.config_version === 1)`,
      );
      await waitFor(browser, `!!document.querySelector('#lab-q')`);
      await browser.type(
        '#lab-q',
        text('住宿报销上限是多少？', 'What is the hotel reimbursement limit?'),
      );
      await browser.submit('[data-form="run-test"]');
      await waitFor(browser, `document.querySelectorAll('.run').length > 0`, 20000);
    });
    await step('the earlier preview is marked and actual actions sit beside it', async () => {
      await openWork(browser);
      await waitFor(browser, `${block}?.dataset.outcomePreview === 'stale'`, 20000);
      await waitFor(browser, `${blockState}.actual.length >= 2`, 20000);
      const state = await browser.ev(blockState);
      states.stale = state;
      assert.equal(state.badge, text('旧预览，条件已变', 'Earlier preview, conditions changed'));
      assert.ok(
        state.changes.includes(text('试点配置第 0 版 → 第 1 版', 'Pilot configuration v0 → v1')),
      );
      assert.ok(state.actual.some((line) => line.includes(text('已应用第 1 版', 'v1 applied'))));
      assert.ok(state.actual.some((line) => line.includes(text('已运行测试 1 次', 'Test runs: 1'))));
      // The prediction text is the one saved before; it is not rewritten.
      assert.deepEqual(state.lines, states.saved.lines);
      await capture(browser, language, 'preview-stale');
    });
    await step('a new saved version gets its own preview; the old one stays listed', async () => {
      await browser.type(
        '#editor-body',
        text(
          '先小范围试点，人数 25，保留人工兜底。',
          'Small pilot with 25 users and human fallback.',
        ),
      );
      await delay(500);
      await browser.clickText(text('保存这版', 'Save this version'));
      await waitFor(
        browser,
        `${blockState}?.meta.includes(${JSON.stringify(text('第 2 版', 'v2'))})`,
        20000,
      );
      const state = await browser.ev(blockState);
      states.revised = state;
      assert.equal(state.status, 'current');
      assert.deepEqual(state.earlier, [
        text(
          '第 1 版的预览 · 旧预览，条件已变',
          'Preview of v1 · Earlier preview, conditions changed',
        ),
      ]);
      assert.ok(state.lines.some((line) => line.includes(text('第 1 版配置', 'configuration v1'))));
      // Open the earlier preview so the record shows it kept, unchanged and marked old.
      await browser.ev(
        `${block}.querySelectorAll('details.w03-outcome-earlier, details.w03-outcome-earlier-item').forEach((node) => { node.open = true; })`,
      );
      const earlier = await browser.ev(
        `[...${block}.querySelectorAll('.w03-outcome-earlier-item [data-outcome-changes] li')].map((li) => li.textContent)`,
      );
      assert.ok(
        earlier.includes(
          text(
            '这份作品已保存第 2 版（预览按第 1 版）',
            'This work now has v2 (the preview was for v1)',
          ),
        ),
      );
      await capture(browser, language, 'preview-revised');
    });
    assert.deepEqual(
      browser.logs.filter((item) => item.level === 'exception'),
      [],
    );
  } catch (error) {
    results.push({ language, status: 'failed', error: String(error) });
    await browser.shot(`${output}/screenshots/${language}-failure.jpg`, true);
    writeFileSync(`${output}/${language}-failure.txt`, await browser.ev('document.body.innerText'));
    throw error;
  } finally {
    writeFileSync(`${output}/${language}-states.json`, `${JSON.stringify(states, null, 2)}\n`);
    await browser.close();
    writeFileSync(`${output}/result.json`, `${JSON.stringify(results, null, 2)}\n`);
  }
}

for (const language of ['zh', 'en']) await runLanguage(language);
