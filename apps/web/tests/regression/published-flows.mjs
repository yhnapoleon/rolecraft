import { waitFor, clickReady } from './browser-support.mjs';
/** Normal v4 UI over real HTTP/worker and the unmodified published catalog. */
import assert from 'node:assert/strict';
import { copyFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { delay, launch } from '../walkthrough/cdp.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output, 'BASE and OUT are required');
mkdirSync(`${output}/screenshots/attempts`, { recursive: true });
const results = [];

async function enterWorkspace(context) {
  const { browser, language, shot } = context;
  await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
  await browser.click('[data-action="open-career"]');
  await browser.click('.case-hero [data-action="take-case"]');
  await waitFor(browser, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
  assert.equal(
    await browser.ev(`document.querySelectorAll('[data-v4-region="workspace"]').length`),
    1,
    'The normal entry allocates exactly one workspace owner',
  );
  await shot('board');
  assert.equal(
    await browser.ev(`window.PracticeLive.store.active().v2Binding.workLanguage`),
    language,
  );
}

async function inspectResourceRegion(context) {
  const { browser, shot } = context;
  await browser.click('.product-bar [data-action="resources"]');
  await waitFor(browser, `!!document.querySelector('#res-form [name="capacity"]')`);
  assert.equal(
    await browser.ev(`document.querySelectorAll('[data-v4-region="resource-requests"]').length`),
    1,
    'The original resource dialog has exactly one named owner',
  );
  assert.equal(
    await browser.ev(`document.querySelector('[form="res-form"][type="submit"]').form.id`),
    'res-form',
  );
  await shot('resources');
  await browser.click('#sheet [data-action="close"]');
  await waitFor(browser, `!document.querySelector('#sheet').open`);
}

async function readAndTest(context) {
  const { browser, text, shot } = context;
  await browser.click('.doc-card[data-id="brief"]');
  await waitFor(browser, `location.hash.startsWith('#/doc/')`);
  await browser.click('[data-action="to-board"]');
  await browser.click('.product-bar [data-action="open-bench"]');
  await browser.type(
    '#lab-q',
    text('住宿报销上限是多少？', 'What is the hotel reimbursement limit?'),
  );
  await browser.submit('[data-form="run-test"]');
  await waitFor(browser, `document.querySelectorAll('.run').length > 0`);
  await shot('test');
  await browser.click('[data-action="to-board"]');
}

async function restoreDraft(context) {
  const { browser, title, draft, shot } = context;
  await browser.click('.card-open');
  context.taskRoute = await browser.ev('location.hash');
  await browser.type('#new-title', title);
  await browser.type('#new-body', draft);
  await browser.click('[data-action="to-board"]');
  await browser.goto(base + context.taskRoute);
  await waitFor(browser, `!!document.querySelector('#new-body')`);
  assert.equal(await browser.ev(`document.querySelector('#new-body').value`), draft);
  await shot('draft');
}

async function saveAndShare(context) {
  const { browser, text, draft, shot } = context;
  await browser.clickText(text('保存为作品', 'Save as work'));
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
  await browser.click('.ol-row[data-type="work"]');
  await waitFor(browser, `!!document.querySelector('#editor-body')`);
  assert.equal(await browser.ev(`document.querySelector('#editor-body').value`), draft);
  await browser.clickText(text('分享已保存的这版', 'Share this saved version'));
  await waitFor(
    browser,
    `document.querySelector('[data-v4-insertion="sharing"]')
      ?.innerText.includes(${JSON.stringify(text('可见', 'Visible'))})`,
  );
  await waitFor(browser, `!!document.querySelector('.rc-roles__reply')`);
  assert.equal(
    await browser.ev(`document.querySelectorAll('[data-v4-region="roles"]').length`),
    1,
    'One named region owns the real colleague conversation',
  );
  await shot('shared');
}

async function recoverAccess(context) {
  const { browser, text, shot } = context;
  await browser.click('.rail-tabs [data-tab="agent"]');
  await waitFor(browser, `!!document.querySelector('[name="agentName"]')`);
  assert.equal(
    await browser.ev(`document.querySelectorAll('[data-v4-region="agent"]').length`),
    1,
    'One named region owns the Agent controls',
  );
  await browser.type('[name="agentName"]', 'Recovery check');
  await browser.click(
    `[aria-label="${text('授权整个工作区的可见内容', 'Allow visible content across the workspace')}"]`,
  );
  await browser.ev('window.regressionDropNext = true');
  await browser.submit('.agent-v4-grant');
  await waitFor(browser, 'window.regressionResponseLost === true');
  await browser.goto(base + context.taskRoute);
  await waitFor(browser, `!!document.querySelector('.rail-tabs [data-tab="agent"]')`);
  await browser.click('.rail-tabs [data-tab="agent"]');
  await clickReady(browser, text('核对原请求结果', 'Check original result'));
  await waitFor(browser, `document.querySelectorAll('.agent-v4-access-row').length === 1`);
  const count = await browser.ev(`(async () => {
      const live = window.PracticeLive;
      const host = live.v4Host(live.engine.getAttempt(live.state));
      return (await host.query('delegations.list')).items.length;
    })()`);
  assert.equal(count, 1);
  await waitFor(
    browser,
    `(() => {
    const input = document.querySelector('.agent-v4-grant [name="agentName"]');
    return !!input && !input.disabled;
  })()`,
  );
  assert.equal(
    await browser.ev(`document.querySelectorAll('[data-action="download-agent-config"]').length`),
    1,
    'Recovered access exposes the one-time config control through the host subscription',
  );
  await shot('recovered-access');
}

async function submitDeferral(context) {
  const { browser, text, shot } = context;
  await browser.click('[data-action="to-board"]');
  await browser.click('.ws-toolbar [data-action="submit"]');
  await waitFor(browser, `!!document.querySelector('.native-feedback input[type="checkbox"]')`);
  await browser.click('.native-feedback input[type="checkbox"]');
  await browser.select('.native-feedback select', 'defer_with_conditions');
  await clickReady(browser, text('提交选中的版本', 'Submit selected versions'), '#sheet button');
  await waitFor(browser, `window.PracticeLive.store.active().world.status === 'submitted'`);
  await browser.ev(`document.querySelector('#sheet')?.close()`);
  await browser.goto(`${base}#/review`);
  await waitFor(
    browser,
    `document.querySelector('.native-feedback')
      ?.innerText.includes(${JSON.stringify(text('等待模型接入', 'Awaiting model connection'))})`,
    30000,
  );
  await waitFor(
    browser,
    `!!document.querySelector('[data-action="practice-reload"], [data-action="practice-choose"]')`,
  );
  if (await browser.ev(`!!document.querySelector('[data-action="practice-reload"]')`)) {
    await browser.click('[data-action="practice-reload"]');
  }
  await waitFor(
    browser,
    `document.querySelectorAll('[data-action="practice-choose"]').length === 2`,
  );
  await shot('feedback');
}

async function reviseAndReadHistory(context) {
  const { browser, text, draft, shot } = context;
  await browser.type(
    `textarea[aria-label="${text('这次准备怎样修订', 'What will you revise?')}"]`,
    draft,
  );
  await clickReady(browser, text('开始修订', 'Start a revision'));
  await waitFor(browser, `window.PracticeLive.store.active().world.status === 'active'`);
  await browser.goto(`${base}#/review`);
  await waitFor(
    browser,
    `document.querySelector('.native-feedback [role="status"]')
    ?.textContent === ${JSON.stringify(
      text(
        '可以继续工作，选择准备交付的版本。',
        'Continue your work and select versions for submission.',
      ),
    )}`,
  );
  await shot('history');
  assert.equal(
    await browser.ev(`document.documentElement.scrollWidth > document.documentElement.clientWidth`),
    false,
  );
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
  const shot = async (name) => {
    await browser.ev('document.fonts.ready.then(() => true)');
    if (name !== 'failure') {
      await browser.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 0, y: 0 });
      await waitFor(browser, `!document.querySelector('#toast.visible')`);
      // Normalize the camera position only. Do not edit DOM content or saved UI state.
      await browser.ev(`(() => {
        window.scrollTo(0, 0);
        for (const node of document.querySelectorAll('*')) {
          if (/auto|scroll/.test(getComputedStyle(node).overflowY)) node.scrollTop = 0;
        }
      })()`);
    }
    if (name === 'shared') {
      await waitFor(
        browser,
        `document.querySelector('[data-v4-insertion="sharing"]')
          ?.innerText.includes(${JSON.stringify(text('可见', 'Visible'))})`,
      );
    }
    const frameState = `JSON.stringify({
      text: document.body.innerText,
      controls: [...document.querySelectorAll('button, input, select, textarea')]
        .filter(node => node.offsetParent !== null)
        .map(node => [node.id, node.disabled, node.value])
    })`;
    for (let attempt = 0; attempt < 8; attempt++) {
      await waitFor(browser, '!window.PracticeLive.store.getSnapshot().busy');
      const before = await browser.ev(frameState);
      await delay(200);
      if (before !== (await browser.ev(frameState))) continue;
      const path = `${output}/screenshots/attempts/${language}-${name}-${attempt}.jpg`;
      await browser.shot(path);
      if (before === (await browser.ev(frameState))) {
        copyFileSync(path, `${output}/screenshots/${language}-${name}.jpg`);
        return;
      }
    }
    throw new Error(`The ${language}/${name} screenshot did not reach a stable visible state`);
  };
  const title = text('回归：试点决定', 'Regression: pilot decision');
  const draft = text(
    '负责人和范围核实前暂缓，保留人工兜底。',
    'Defer until the owner and scope are verified. Keep human fallback.',
  );
  const context = { browser, language, text, title, draft, shot, taskRoute: '' };
  await browser.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => {
    const original = window.fetch;
    window.regressionResponseLost = false;
    window.regressionDropNext = false;
    window.fetch = async (...args) => {
      const response = await original(...args);
      if (window.regressionDropNext && String(args[0]).endsWith('/delegations') && args[1]?.method === 'POST') {
        window.regressionDropNext = false;
        window.regressionResponseLost = true;
        throw new TypeError('Controlled lost response');
      }
      return response;
    };
  })()`,
  });
  try {
    await browser.goto(base);
    await browser.ev(
      `localStorage.clear();
      localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
    );
    await browser.goto(base);
    await step('normal entry and fixed work language', () => enterWorkspace(context));
    await step('resource dialog keeps its assigned form and controls', () =>
      inspectResourceRegion(context),
    );
    await step('source reading and actual assistant test', () => readAndTest(context));
    await step('unsaved draft survives route change and reload', () => restoreDraft(context));
    await step('save and share the exact work version', () => saveAndShare(context));
    await step('lost access response recovers after reload without duplicate grant', () =>
      recoverAccess(context),
    );
    await step('submit a deferral and read fixed feedback', () => submitDeferral(context));
    await step('revision keeps original feedback and original wording', () =>
      reviseAndReadHistory(context),
    );
    assert.deepEqual(
      browser.logs.filter((item) => item.level === 'exception'),
      [],
    );
  } catch (error) {
    results.push({ language, status: 'failed', error: String(error) });
    await shot('failure');
    writeFileSync(`${output}/${language}-failure.txt`, await browser.ev('document.body.innerText'));
    writeFileSync(
      `${output}/${language}-controls.json`,
      JSON.stringify(
        await browser.ev(
          `({
            buttons: [...document.querySelectorAll('button')]
              .filter(button => button.offsetParent !== null)
              .map(button => ({text: button.textContent, disabled: button.disabled})),
            selects: [...document.querySelectorAll('select')].map(select => ({
              label: select.getAttribute('aria-label'),
              value: select.value,
              disabled: select.disabled,
            })),
          })`,
        ),
        null,
        2,
      ),
    );
    throw error;
  } finally {
    await browser.close();
    writeFileSync(`${output}/result.json`, `${JSON.stringify(results, null, 2)}\n`);
  }
}

for (const language of ['zh', 'en']) await runLanguage(language);
