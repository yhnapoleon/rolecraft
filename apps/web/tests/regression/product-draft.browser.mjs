import { waitFor } from './browser-support.mjs';
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

async function waitingEditorRefresh(context) {
  const { browser, text, taskRoute } = context;
  const unsaved = text(
    '已有未保存的长段落，必须保留。',
    'Existing long unsaved paragraph must survive.',
  );
  const unsavedTitle = text('已有未保存标题', 'Existing unsaved title');
  await browser.type('#editor-body', unsaved);
  await browser.type('#editor-title', unsavedTitle);
  await waitFor(
    browser,
    `(() => {
    const live = window.PracticeLive;
    const host = live.v4Host(live.engine.getAttempt(live.state));
    const snap = host.snapshot();
    return host.draft('workspace', snap.session.sessionId + ':product:' + snap.currentProduct.object_id)?.value.content === ${JSON.stringify(unsaved)};
  })()`,
  );
  await browser.click('[data-action="to-board"]');
  await browser.ev(`(() => {
    const live = window.PracticeLive;
    const host = live.v4Host(live.engine.getAttempt(live.state));
    const reflect = host.reflectSelection;
    let release;
    const waiting = new Promise(resolve => { release = resolve; });
    host.reflectSelection = async (...args) => {
      await waiting;
      return reflect.apply(host, args);
    };
    window.releaseWorkMount = () => { host.reflectSelection = reflect; release(); };
  })()`);
  await browser.ev(`location.hash = ${JSON.stringify(taskRoute)}`);
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
  await browser.click('.ol-row[data-type="work"]');
  await waitFor(browser, `!!document.querySelector('#editor-body')`);
  const changed = `${unsaved}x`;
  const changedTitle = `${unsavedTitle}x`;
  const beforeTyping = await browser.ev(`({
    content: document.querySelector('#editor-body').value,
    title: document.querySelector('#editor-title').value,
  })`);
  writeFileSync(
    `${output}/${context.language}-before-mount-input.json`,
    JSON.stringify(beforeTyping, null, 2),
  );
  await browser.ev(`(() => {
    for (const selector of ['#editor-body', '#editor-title']) {
      const node = document.querySelector(selector);
      node.value += 'x';
      node.dispatchEvent(new Event('input', { bubbles: true }));
    }
  })()`);
  await browser.ev(`(() => {
    const select = document.querySelector('[data-edit="purpose"]');
    select.value = '方案比较';
    select.dispatchEvent(new Event('input', { bubbles: true }));
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await delay(650);
  await browser.send('Page.reload', { ignoreCache: true });
  await waitFor(browser, `!window.releaseWorkMount && !!window.PracticeLive`);
  assert.equal(await browser.ev('typeof window.releaseWorkMount'), 'undefined');
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
  await browser.click('.ol-row[data-type="work"]');
  await waitFor(browser, `!!document.querySelector('#editor-body')`);
  await delay(500);
  const actual = await browser.ev(`document.querySelector('#editor-body').value`);
  writeFileSync(
    `${output}/${context.language}-after-refresh.json`,
    JSON.stringify({ expected: changed, actual }, null, 2),
  );
  assert.equal(actual, changed, 'The pending edit survives refresh');
  assert.equal(await browser.ev(`document.querySelector('#editor-title').value`), changedTitle);
  assert.equal(
    await browser.ev(`document.querySelector('[data-edit="purpose"]').value`),
    '方案比较',
  );
  // Mounted input/change events must have only the slot as their writer.
  await browser.ev(`(() => {
    window.purposeInputBubbles = 0;
    document.addEventListener('input', event => {
      if (event.target.matches('[data-edit="purpose"]')) window.purposeInputBubbles++;
    });
    const select = document.querySelector('[data-edit="purpose"]');
    select.value = '探索笔记';
    select.dispatchEvent(new Event('input', { bubbles: true }));
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await delay(400);
  assert.equal(
    await browser.ev(`document.querySelector('[data-edit="purpose"]').value`),
    '探索笔记',
  );
  assert.equal(await browser.ev('window.purposeInputBubbles'), 0);
  assert.equal(await browser.ev(`document.querySelectorAll('#editor-body').length`), 1);
  for (const value of [text('新输入不能被覆盖', 'Keep the new input'), '']) {
    await browser.type('#editor-body', value);
    await delay(400);
    await browser.click('[data-action="to-board"]');
    await browser.goto(base + taskRoute);
    await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
    await browser.click('.ol-row[data-type="work"]');
    await waitFor(browser, `!!document.querySelector('#editor-body')`);
    await delay(400);
    assert.equal(
      await browser.ev(`(() => {
      const live = window.PracticeLive;
      const host = live.v4Host(live.engine.getAttempt(live.state));
      const snap = host.snapshot();
      return host.draft('workspace', snap.session.sessionId + ':product:' + snap.currentProduct.object_id)?.value.content;
    })()`),
      value,
    );
    assert.equal(await browser.ev(`document.querySelector('#editor-body').value`), value);
  }
}

async function initialPermissionRead(context) {
  const { browser, text } = context;
  const probe = await browser.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => {
      const send = window.fetch.bind(window);
      let release;
      const waiting = new Promise(resolve => { release = resolve; });
      window.releaseWorkspaceRead = release;
      window.fetch = async (input, options) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url.includes('/workbench')) {
          window.workspaceReadWaiting = true;
          await waiting;
        }
        return send(input, options);
      };
    })()`,
  });
  try {
    await browser.send('Page.reload', { ignoreCache: true });
    await waitFor(
      browser,
      `window.workspaceReadWaiting && !!document.querySelector('.ol-row[data-type="work"]')`,
    );
    await browser.click('.ol-row[data-type="work"]');
    await waitFor(browser, `!!document.querySelector('#editor-title')`);
    const locked = await browser.ev(`({
      title: document.querySelector('#editor-title').readOnly,
      body: !document.querySelector('#editor-body') || document.querySelector('#editor-body').readOnly,
      purpose: document.querySelector('[data-edit="purpose"]').disabled,
    })`);
    writeFileSync(
      `${output}/${context.language}-initial-permissions.json`,
      JSON.stringify(locked, null, 2),
    );
    assert.deepEqual(locked, { title: true, body: true, purpose: true });
    await browser.ev('window.releaseWorkspaceRead()');
    await waitFor(
      browser,
      `!!document.querySelector('#editor-body') && !document.querySelector('#editor-body').readOnly && !document.querySelector('#editor-title').readOnly && !document.querySelector('[data-edit="purpose"]').disabled`,
    );
    const value = text('权限核实后的新输入', 'New input after permissions are checked');
    await browser.type('#editor-body', value);
    await waitFor(
      browser,
      `(() => {
      const live = window.PracticeLive;
      const host = live.v4Host(live.engine.getAttempt(live.state));
      const snap = host.snapshot();
      return host.draft('workspace', snap.session.sessionId + ':product:' + snap.currentProduct.object_id)?.value.content === ${JSON.stringify(value)};
    })()`,
    );
  } finally {
    await browser.ev('window.releaseWorkspaceRead?.()');
    await browser.send('Page.removeScriptToEvaluateOnNewDocument', {
      identifier: probe.identifier,
    });
  }
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
  try {
    await browser.goto(base);
    await browser.ev(
      `localStorage.clear();
      localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
    );
    await browser.goto(base);
    await step('normal entry and fixed work language', () => enterWorkspace(context));
    await step('source reading and actual assistant test', () => readAndTest(context));
    await step('unsaved draft survives leaving and reopening its route', () =>
      restoreDraft(context),
    );
    await step('save and share the exact work version', () => saveAndShare(context));
    if (process.env.DRAFT_CASE !== 'permissions')
      await step('existing unsaved work survives pre-mount input and real remounts', () =>
        waitingEditorRefresh(context),
      );
    if (process.env.DRAFT_CASE !== 'existing')
      await step('initial permission read keeps input locked until the host is ready', () =>
        initialPermissionRead(context),
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

const failures = [];
for (const language of ['zh', 'en']) {
  try {
    await runLanguage(language);
  } catch (error) {
    failures.push(error);
  }
}
if (failures.length) throw new AggregateError(failures, 'Product draft recovery failed');
