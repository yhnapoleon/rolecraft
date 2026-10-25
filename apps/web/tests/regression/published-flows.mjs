import { acceptEntryStory, waitFor, clickReady, submitDelivery } from './browser-support.mjs';
import { askHowToPrioritise, openEvidence, readActivity } from './activity-evidence.mjs';
/** Normal v4 UI over real HTTP/worker and the unmodified published catalog. */
import assert from 'node:assert/strict';
import { copyFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { delay, launch } from '../walkthrough/cdp.mjs';
import { connectAgentOverMcp, openMyAgent } from './mcp-connection.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output, 'BASE and OUT are required');
mkdirSync(`${output}/screenshots/attempts`, { recursive: true });
const results = [];

async function enterWorkspace(context) {
  const { browser, language, shot } = context;
  await waitFor(browser, `!!document.querySelector('.home-roles [data-role="pm"] [data-action="open-career"]')`);
  await browser.click('.home-roles [data-role="pm"] [data-action="open-career"]');
  await browser.click('.case-hero [data-action="take-case"]');
  await acceptEntryStory(browser);
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

async function restoreColleagueDrafts(context) {
  const { browser, text, shot } = context;
  const examples = [
    ['manager', 'supervisor', text('经理问题草稿，尚未发送。', 'Manager draft, not sent.')],
    ['technical', 'tech_lead', text('技术问题草稿，尚未发送。', 'Technical draft, not sent.')],
  ];
  const back = () => browser.click('[data-action="rail"][data-rail="team"]');
  for (const [role, roleId, draft] of examples) {
    await browser.click(`.person[data-role="${role}"]`);
    await waitFor(browser, `!!document.querySelector('.rc-roles--v4-history')`);
    await browser.type('#chat-input', draft);
    await waitFor(
      browser,
      `window.PracticeLive.v4Host(window.PracticeLive.engine
      .getAttempt(window.PracticeLive.state)).draft('roles', 'question:${roleId}')
      === ${JSON.stringify(draft)}`,
    );
    await back();
  }
  await browser.goto(`${base}#/work`);
  await waitFor(browser, `!!document.querySelector('.person[data-role="manager"]')`);
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
    window.releaseDraftMount = () => {
      host.reflectSelection = reflect;
      release();
    };
  })()`);
  await browser.click('.person[data-role="manager"]');
  await waitFor(browser, `!!document.querySelector('#chat-input')`);
  const changed = text('挂载等待期间的新问题。', 'New question while mounting.');
  await browser.type('#chat-input', changed);
  await browser.ev('window.releaseDraftMount()');
  await waitFor(browser, `!!document.querySelector('.rc-roles--v4-history')`);
  assert.equal(await browser.ev(`document.querySelector('#chat-input').value`), changed);
  await back();
  await browser.click('.person[data-role="manager"]');
  await waitFor(browser, `!!document.querySelector('.rc-roles--v4-history')`);
  assert.equal(await browser.ev(`document.querySelector('#chat-input').value`), changed);
  await browser.type('#chat-input', examples[0][2]);
  await back();

  for (const [role, , draft] of examples) {
    await browser.click(`.person[data-role="${role}"]`);
    await waitFor(browser, `!!document.querySelector('.rc-roles--v4-history')`);
    assert.equal(await browser.ev(`document.querySelector('#chat-input').value`), draft);
    assert.equal(await browser.ev(`document.querySelectorAll('#chat-input').length`), 1);
    assert.equal(await browser.ev(`document.querySelectorAll('.chat .composer').length`), 1);
    await shot(`${role}-draft`);
    await browser.type('#chat-input', '');
    await back();
    await browser.click(`.person[data-role="${role}"]`);
    await waitFor(browser, `!!document.querySelector('.rc-roles--v4-history')`);
    assert.equal(await browser.ev(`document.querySelector('#chat-input').value`), '');
    await back();
  }
}

/** F02: an idle practice keeps its toolbar. A press held across a poll still opens the
 * language menu, which stays open through idle polls and through a background notice. */
async function toolbarHoldsStill(context) {
  const { browser, text } = context;
  let previous = '';
  for (let sample = 0; ; sample++) {
    const current = await browser.ev(`JSON.stringify([
      window.PracticeLive.store.getSnapshot().busy, window.PracticeLive.store.active()])`);
    if (current === previous) break;
    assert.ok(sample < 30, 'The practice settles');
    previous = current;
    await delay(1000);
  }
  // Language lives in the toolbar's ⋯ since the second-round shell bar: hold ⋯, and the menu
  // that opens carries the language row.
  const point = await browser.ev(`(() => {
    const box = document.querySelector('#ws-toolbar [data-menu="more"]').getBoundingClientRect();
    return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  })()`);
  const press = { ...point, button: 'left', clickCount: 1 };
  await browser.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...point });
  await browser.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...press });
  await delay(1800);
  await browser.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...press });
  const open = `!!document.querySelector('#ws-toolbar .menu [data-menu="lang"]')`;
  await waitFor(browser, open, 3000);
  await browser.ev(`window.regressionToolbar = document.getElementById('ws-toolbar')`);
  await delay(4500);
  const kept = `document.getElementById('ws-toolbar') === window.regressionToolbar && ${open}`;
  assert.equal(await browser.ev(kept), true, 'Idle polls keep the toolbar and its open menu');
  await browser.ev(
    `window.PracticeLive.store.report({ notice: ${JSON.stringify(text('后台提示', 'Background notice'))} })`,
  );
  await delay(300);
  assert.equal(await browser.ev(kept), true, 'A notice that leaves the toolbar unchanged keeps it');
  await browser.ev(`window.PracticeLive.store.report({ notice: '' })`);
  await browser.click('#ws-toolbar [data-menu="more"]');
  await waitFor(browser, `!document.querySelector('#ws-toolbar .menu')`);
  // The held control is More; its language row opens the practice-language note, not a switch.
  await browser.click('#ws-toolbar [data-menu="more"]');
  await browser.click('#ws-toolbar .menu [data-menu="lang"]');
  await waitFor(browser, `!!document.querySelector('#ws-toolbar .menu.lang-note')`);
  assert.equal(
    await browser.ev(`document.querySelectorAll('#ws-toolbar [data-action="set-lang"]').length`),
    0,
    'The practice language note does not offer an in-practice language switch',
  );
  await browser.click('#ws-toolbar [data-menu="more"]');
  await browser.click('#ws-toolbar [data-menu="more"]');
  await waitFor(browser, `!document.querySelector('#ws-toolbar .menu')`);
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
  const { browser, question, text, shot } = context;
  const row = '[data-doc-row="brief"]';
  const title = await browser.ev(`document.querySelector('${row} .doc-row-title').textContent`);
  for (const close of ['escape', 'dim']) {
    await browser.click(row);
    await waitFor(browser, `!!document.querySelector('.mat-sheet[data-state="open"]')`);
    assert.equal(await browser.ev('location.hash'), '#/work');
    assert.equal(await browser.ev(`document.querySelector('.mat-title').textContent`), title);
    await waitFor(browser, `document.querySelector('.mat-body')?.innerText.length > 40`);
    // The reading sheet covers only the desk: the colleague rail remains usable.
    await browser.click('.person[data-role="business"]');
    const note = text('阅读时的问题草稿', 'Question drafted while reading');
    await browser.type('#chat-input', note);
    assert.equal(await browser.ev(`document.querySelector('#chat-input').value`), note);
    assert.equal(
      await browser.ev(`!!document.querySelector('.mat-sheet[data-state="open"]')`),
      true,
    );
    await shot(`material-${close}`);
    if (close === 'escape') {
      for (const type of ['keyDown', 'keyUp'])
        await browser.send('Input.dispatchKeyEvent', {
          type,
          key: 'Escape',
          code: 'Escape',
          windowsVirtualKeyCode: 27,
        });
    } else await browser.click('.mat-dim');
    await waitFor(browser, `!document.querySelector('.mat-sheet[data-state="open"]')`);
    await waitFor(browser, `document.activeElement === document.querySelector('${row}')`);
    assert.equal(await browser.ev(`document.querySelector('#chat-input').value`), note);
    await browser.type('#chat-input', '');
    await browser.click('[data-action="rail"][data-rail="team"]');
  }
  await browser.click('.product-bar [data-action="open-bench"]');
  await browser.type('#lab-q', question);
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
  await openMyAgent(browser);
  assert.equal(
    await browser.ev(`document.querySelectorAll('[data-agent-page]').length`),
    1,
    'One page owns the Agent controls',
  );
  await browser.ev('window.regressionDropNext = true');
  await browser.click('.ag-cta button');
  await waitFor(browser, 'window.regressionResponseLost === true');
  // The page says the answer never arrived and that pressing again checks the same request.
  await waitFor(
    browser,
    `document.querySelector('.ag-cta-error')?.innerText.includes(${JSON.stringify(
      text('不会多开一份', 'it will not open a second one'),
    )})`,
  );
  await browser.goto(base + context.taskRoute);
  await openMyAgent(browser);
  await browser.click('.ag-cta button');
  await waitFor(browser, `document.querySelector('.ag-rig')?.dataset.phase === 'waiting'`);
  const count = await browser.ev(`(async () => {
      const live = window.PracticeLive;
      const host = live.v4Host(live.engine.getAttempt(live.state));
      return (await host.query('delegations.list')).items.length;
    })()`);
  assert.equal(count, 1);
  assert.equal(
    await browser.ev(
      `document.querySelectorAll('.ag-connect .ag-cmd:not(.is-ask) .ag-copy').length`,
    ),
    1,
    'Recovered access shows the command through the host subscription',
  );
  await shot('recovered-access');
}

async function submitDeferral(context) {
  const { browser, text, shot } = context;
  await browser.click('[data-action="to-board"]');
  await browser.click('.ws-toolbar [data-action="submit"]');
  await waitFor(browser, `!!document.querySelector('.native-feedback input[type="checkbox"]')`);
  assert.equal(
    await browser.ev(`document.querySelector('.native-feedback input[type="checkbox"]').checked`),
    true,
    'The latest saved work is selected by default',
  );
  // The decision is one of four paper options (a radio group named "本次决定").
  await browser.click(
    '.native-feedback [data-decision-cards] .decision-card[data-decision="defer_with_conditions"] input',
  );
  await submitDelivery(browser);
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
  // The submission's own feedback is shown first; this flow never requests a review.
  const reportHeadings = JSON.stringify(
    `.native-feedback [aria-label="${text('分段反馈', 'Feedback sections')}"] > article > h2`,
  );
  await waitFor(
    browser,
    // With its feedback in, the results cover says what was delivered: the status line is empty (195).
    `document.querySelector('.native-feedback [role="status"]')?.textContent === '' && [...document.querySelectorAll(${reportHeadings})].map((node) => node.textContent)[0] === ${JSON.stringify(
      text('逐项', 'Item by item'),
    )}`,
    30000,
  );
  assert.ok(
    !(await browser.ev(
      `[...document.querySelectorAll(${reportHeadings})].some((node) => node.textContent === ${JSON.stringify(
        text('作品评审反馈', 'Artifact review feedback'),
      )})`,
    )),
    'an unrequested review report is shown',
  );
  await shot('feedback');
}

async function showFinalRubricVersion(context) {
  const { browser, text } = context;
  // The latest submission feedback names the rubric recorded in its own provenance.
  const line = JSON.stringify(
    `.native-feedback [aria-label="${text('分段反馈', 'Feedback sections')}"] > article [data-rubric-version]`,
  );
  await waitFor(browser, `!!document.querySelector(${line})`);
  assert.equal(
    await browser.ev(`document.querySelector(${line}).dataset.rubricVersion`),
    'feedback-rubric-v2-final.1',
  );
  assert.equal(
    await browser.ev(`document.querySelector(${line}).textContent`),
    text('评价标准：rubric-v2 定稿（2026-10-09）', 'Rubric: rubric-v2 final (2026-10-09)'),
  );
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

/** F24: once a work version has been open in the editor, the new-task dialog keeps its
 * fields through a dropped poll and still adds the task after a revision. */
async function addTaskAfterRevision(context) {
  const { browser, text, shot } = context;
  await browser.goto(`${base}#/work`);
  await waitFor(browser, `!!document.querySelector('.card-open')`);
  await browser.click('.card-open');
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
  await browser.click('.ol-row[data-type="work"]');
  await waitFor(browser, `!!document.querySelector('#editor-body')`);
  await browser.click('[data-action="to-board"]');
  await waitFor(browser, `!!document.querySelector('[data-action="new-task"]')`);
  const before = await browser.ev('window.PracticeLive.store.active().v2Workspace.tasks.length');
  await browser.click('[data-action="new-task"]');
  await waitFor(browser, `!!document.querySelector('#task-form [name="title"]')`);
  await browser.ev('window.regressionFailWorkbenchReads = 1');
  await waitFor(
    browser,
    `window.regressionFailedWorkbenchReads === 1
      && window.PracticeLive.store.getSnapshot().connected === true`,
  );
  assert.deepEqual(
    await browser.ev(`({
      title: !!document.querySelector('#task-form [name="title"]'),
      note: !!document.querySelector('#task-form [name="note"]'),
      priorities: document.querySelectorAll('#task-form [name="priority"]').length,
    })`),
    { title: true, note: true, priorities: 3 },
    'The new-task dialog keeps its fields after the board re-renders',
  );
  const title = text('修订后新增：核对索引滞后', 'Added after revision: check index lag');
  await browser.type('#task-form [name="title"]', title);
  await clickReady(browser, text('加入', 'Add'), '#sheet button');
  await waitFor(
    browser,
    `window.PracticeLive.store.active().v2Workspace.tasks.length === ${before + 1}
      && [...document.querySelectorAll('.card .card-title')]
        .some((node) => node.textContent === ${JSON.stringify(title)})`,
  );
  await shot('task-after-revision');
}

/** F20 (review 175 P2-2): the new task moved the practice point, so the review page reads its
 * practice again while those reads drop. The shown choices stay, and the column reads again by
 * itself once the reads return. */
async function practiceKeepsChoices(context) {
  const { browser } = context;
  const choices = `document.querySelectorAll('[data-action="practice-choose"]').length`;
  await browser.ev('window.regressionFailPracticeUntil = performance.now() + 2500');
  await browser.goto(`${base}#/review`);
  await waitFor(browser, 'window.regressionFailedPracticeReads >= 1');
  for (let sample = 0; sample < 6; sample++) {
    assert.deepEqual(
      await browser.ev(`({
        choices: ${choices},
        unavailable: !!document.querySelector('[data-practice-unavailable]'),
      })`),
      { choices: 2, unavailable: false },
      'Dropped practice reads keep the shown choices',
    );
    await delay(500);
  }
  await waitFor(
    browser,
    `performance.now() > window.regressionFailPracticeUntil
      && window.regressionPracticeReads > window.regressionFailedPracticeReads`,
  );
  assert.equal(await browser.ev(choices), 2);
}

/** F20 (review 175 P2-1): the first workbench reads of a reloading page are dropped. The page
 * shows no error, has no uncaught exception, and the next poll loads the board. */
async function reloadWithDroppedReads(context) {
  const { browser } = context;
  await browser.goto(`${base}#/work`);
  await waitFor(browser, `!!document.querySelector('.card-open')`);
  await browser.ev(`sessionStorage.setItem('regressionFailOnLoad', '2500')`);
  await browser.send('Page.reload', {});
  await waitFor(browser, 'performance.now() > 2500 && window.regressionFailedWorkbenchReads >= 2');
  await waitFor(
    browser,
    `window.PracticeLive.store.getSnapshot().connected === true
      && !!document.querySelector('.card-open')`,
  );
  assert.deepEqual(
    await browser.ev(`({
      error: window.PracticeLive.store.getSnapshot().error,
      toasts: window.regressionToasts,
    })`),
    { error: '', toasts: [] },
    'Reads dropped while the page loads are not shown as an error',
  );
}

/** The board does what its hint says: Option/Alt with the arrow keys changes a card's priority
 * and its order, dragging a card moves it to another column, and after a reload every card is
 * where it was put (the order is the server's, not the page's). */
async function boardOrderPersists(context) {
  const { browser, shot } = context;
  const lanes = ['first', 'next', 'later'];
  const board = `document.querySelectorAll('.kanban .card-open').length >= 3`;
  const ids = (lane) =>
    `[...document.querySelectorAll('.kanban .col-${lane} .card')].map((c) => c.dataset.taskId)`;
  const stored = (id) =>
    `window.PracticeLive.store.active().v2Workspace.tasks.find((t) => t.id === ${JSON.stringify(id)})`;
  const where = async () =>
    Object.fromEntries(await Promise.all(lanes.map(async (l) => [l, await browser.ev(ids(l))])));
  const reload = async (total) => {
    await browser.send('Page.reload', {});
    await waitFor(
      browser,
      `location.hash === '#/work' && document.querySelectorAll('.kanban .card').length === ${total}`,
      20000,
    );
    await delay(600);
  };
  const altKey = async (key, code, keyCode) => {
    await browser.send('Input.dispatchKeyEvent', {
      type: 'rawKeyDown',
      key,
      code,
      windowsVirtualKeyCode: keyCode,
      modifiers: 1,
    });
    await browser.send('Input.dispatchKeyEvent', {
      type: 'keyUp',
      key,
      code,
      windowsVirtualKeyCode: keyCode,
      modifiers: 1,
    });
  };
  await browser.goto(`${base}#/work`);
  await waitFor(browser, board, 20000);
  await shot('board-order-before');
  // 1. Option + Left: a card of "Up next" moves to "Do first"; the server records priority 0.
  const start = await where();
  const toFirst = start.next[0];
  assert.ok(toFirst, JSON.stringify(start));
  await browser.ev(
    `document.querySelector('.kanban .card[data-task-id=${JSON.stringify(toFirst)}] .card-open').focus()`,
  );
  await altKey('ArrowLeft', 'ArrowLeft', 37);
  await waitFor(
    browser,
    `${stored(toFirst)}?.priority === 0 && ${ids('first')}.includes(${JSON.stringify(toFirst)})`,
  );
  // 2. Option + Up: the last card of "Up next" moves to its top; the server keeps that order.
  const next = await browser.ev(ids('next'));
  assert.ok(next.length >= 2, JSON.stringify(next));
  const toTop = next.at(-1);
  await browser.ev(
    `document.querySelector('.kanban .card[data-task-id=${JSON.stringify(toTop)}] .card-open').focus()`,
  );
  for (let i = 1; i < next.length; i++) {
    await altKey('ArrowUp', 'ArrowUp', 38);
    await waitFor(
      browser,
      `${ids('next')}.indexOf(${JSON.stringify(toTop)}) === ${next.length - 1 - i}`,
    );
  }
  // 3. Drag: the last card of "Up next" is dropped on "Later"; the server records priority 2.
  const dragged = await browser.ev(`${ids('next')}.at(-1)`);
  assert.notEqual(dragged, toTop);
  await browser.ev(`(() => {
    const card = document.querySelector('.kanban .card[data-task-id=${JSON.stringify(dragged)}]');
    const lane = document.querySelector('.kanban .col-later');
    const data = new DataTransfer();
    card.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: data }));
    lane.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: data }));
    lane.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: data }));
    card.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: data }));
  })()`);
  await waitFor(browser, `${stored(dragged)}?.priority === 2`);
  // The board is drawn again from the server's records: read it once every card is back.
  const total = Object.values(start).flat().length;
  await waitFor(
    browser,
    `${ids('later')}.includes(${JSON.stringify(dragged)}) && document.querySelectorAll('.kanban .card').length === ${total}`,
  );
  await delay(400);
  const placed = await where();
  // After a reload every card is where it was put.
  await reload(total);
  assert.deepEqual(await where(), placed, 'the board keeps its new order after a reload');
  assert.ok(
    placed.first.includes(toFirst) && placed.later.includes(dragged),
    JSON.stringify(placed),
  );
  assert.equal(placed.next[0], toTop, 'the card moved up stays first in its column');
  await shot('board-order-after-reload');
  console.log(
    `board order ${context.language}: before ${JSON.stringify(start)} after reload ${JSON.stringify(placed)}`,
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
  const question = text('住宿报销上限是多少？', 'What is the hotel reimbursement limit?');
  const context = { browser, language, text, title, draft, question, shot, taskRoute: '' };
  await browser.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => {
    const original = window.fetch;
    window.regressionResponseLost = false;
    window.regressionDropNext = false;
    window.regressionFailWorkbenchReads = 0;
    window.regressionFailedWorkbenchReads = 0;
    // Milliseconds set before a reload: the loading page's workbench reads drop until then.
    const failUntil = Number(sessionStorage.getItem('regressionFailOnLoad') || 0);
    sessionStorage.removeItem('regressionFailOnLoad');
    window.regressionToasts = [];
    window.regressionFailPracticeUntil = 0;
    window.regressionPracticeReads = 0;
    window.regressionFailedPracticeReads = 0;
    document.addEventListener('DOMContentLoaded', () => {
      const toast = document.getElementById('toast');
      new MutationObserver(() => {
        if (toast.textContent.trim()) window.regressionToasts.push(toast.textContent.trim());
      }).observe(toast, { childList: true, subtree: true, characterData: true });
    });
    window.fetch = async (...args) => {
      const read = !args[1]?.method || args[1].method === 'GET';
      if (read && String(args[0]).split('?')[0].endsWith('/practice')) {
        window.regressionPracticeReads++;
        if (performance.now() < window.regressionFailPracticeUntil) {
          window.regressionFailedPracticeReads++;
          throw new TypeError('Controlled dropped read');
        }
      }
      const dropping = window.regressionFailWorkbenchReads > 0 || performance.now() < failUntil;
      if (dropping && read && String(args[0]).split('?')[0].endsWith('/workbench')) {
        window.regressionFailWorkbenchReads--;
        window.regressionFailedWorkbenchReads++;
        throw new TypeError('Controlled dropped read');
      }
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
    await step('asking how to prioritise opens that colleague with the tasks', () =>
      askHowToPrioritise(context),
    );
    await step('colleague drafts restore once and retain deliberate clearing', () =>
      restoreColleagueDrafts(context),
    );
    await step('resource dialog keeps its assigned form and controls', () =>
      inspectResourceRegion(context),
    );
    await step('idle toolbar keeps a held press and an open menu in place', () =>
      toolbarHoldsStill(context),
    );
    await step('source reading and actual assistant test', () => readAndTest(context));
    await step('unsaved draft survives route change and reload', () => restoreDraft(context));
    await step('save and share the exact work version', () => saveAndShare(context));
    await step('lost access response recovers after reload without duplicate grant', () =>
      recoverAccess(context),
    );
    await step('submit a deferral and read fixed feedback', () => submitDeferral(context));
    await step('evidence names its object and opens in view', () => openEvidence(context));
    await step('feedback names the final rubric version', () => showFinalRubricVersion(context));
    await step('revision keeps original feedback and original wording', () =>
      reviseAndReadHistory(context),
    );
    await step('activity and Agent log read as sentences', async () => {
      await browser.click('[data-action="to-board"]');
      await readActivity(context);
    });
    await step('new task dialog survives a dropped poll and adds a task after revision', () =>
      addTaskAfterRevision(context),
    );
    await step('dropped practice reads keep the choices and read again by themselves', () =>
      practiceKeepsChoices(context),
    );
    await step('a page reload with dropped reads shows no error and loads on the next poll', () =>
      reloadWithDroppedReads(context),
    );
    await step('board order: keys and dragging change it and a reload keeps it', () =>
      boardOrderPersists(context),
    );
    await step('connection card: agent returns work over MCP until revoked', async () => {
      await browser.goto(base + context.taskRoute);
      await waitFor(browser, `!!document.querySelector('#ws-stage')`);
      await connectAgentOverMcp(context);
    });
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
            focus: {
              tag: document.activeElement?.tagName,
              id: document.activeElement?.id,
              evidence: document.activeElement?.matches('[data-reference-kind]') ?? false,
            },
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
if (failures.length) throw new AggregateError(failures, 'Published flows failed');
