/** Continue codes on the normal v4 entry: Chinese with reduced motion, English with default motion.
 *
 * Browser A works on a practice and creates a continue code from ⋯. Browser B, a fresh profile,
 * is told a wrong code is wrong, then opens the practice with the real code and shows the same
 * board; the replies it brings are not announced as new. A replaces the code and browser C is
 * refused the old one. A entering its own new code is only switched to the practice it already
 * has: the selected task stays and no old reply is announced. No document card is opened.
 *
 * Started by `python -m scripts.regression.browser` after published-flows; BASE and OUT come from
 * the runner. Each round uses four exchange tries of the ten a source has per fifteen minutes.
 */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { launch } from '../walkthrough/cdp.mjs';
import { acceptEntryStory, waitFor } from './browser-support.mjs';

const base = process.env.BASE;
const output = process.env.OUT;
assert.ok(base && output, 'BASE and OUT are required');
const shots = `${output}/practice-recovery`;
mkdirSync(shots, { recursive: true });
const results = [];

/** What the person sees of the current practice; never its access. */
const board = (browser) =>
  browser.ev(`(() => {
    const live = window.PracticeLive;
    const a = live.engine.getAttempt(live.state);
    return {
      practices: live.store.getSnapshot().workspace.sessions.length,
      practice: a.id,
      selected: a.selectedTaskId,
      tasks: a.tasks.map((t) => t.title),
      works: a.artifacts.filter((w) => !w.removedAt).map((w) => w.title),
      tests: a.tests.map((t) => t.question),
      replies: Object.values(a.conversations).flat().filter((m) => m.role !== 'user').length,
    };
  })()`);

/** Every notice from now on, so a later one cannot hide what was said. */
const listen = (browser) =>
  browser.ev(`(() => {
    window.notices = [];
    if (window.noticesHeard) return;
    window.noticesHeard = true;
    const toast = document.querySelector('#toast');
    new MutationObserver(() => window.notices.push(toast.textContent)).observe(toast, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  })()`);

async function opened(language, reduced) {
  const browser = await launch({ width: 1440, height: 1000, reduced });
  await browser.goto(base);
  await browser.ev(`localStorage.setItem('rolecraft.locale', '${language}')`);
  await browser.goto(base);
  await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
  await listen(browser);
  return browser;
}

async function newCode(browser) {
  await browser.click('.ws-toolbar [data-menu="more"]');
  await browser.click('[data-action="continue-code"]');
  await waitFor(browser, `!!document.querySelector('[data-action="continue-code-create"]')`);
  await browser.click('[data-action="continue-code-create"]');
  await waitFor(browser, `!!document.querySelector('[data-continue-code-value]')`);
  const code = await browser.ev(`document.querySelector('[data-continue-code-value]').textContent`);
  assert.match(code, /^[0-9A-HJKMNP-TV-Z]{4}(-[0-9A-HJKMNP-TV-Z]{4}){4}$/);
  return code;
}

async function closeDialog(browser) {
  await browser.click('#sheet [data-action="close"]');
  await waitFor(browser, `document.querySelector('#sheet').open === false`);
  assert.equal(
    await browser.ev(`!!document.querySelector('[data-continue-code-value]')`),
    false,
    'The code stayed on the page after its dialog closed',
  );
}

async function enter(browser, typed) {
  await browser.type('#continue-code-input', typed);
  await browser.submit('[data-form="continue-code"]');
}

async function refused(browser, sentence) {
  await waitFor(
    browser,
    `document.querySelector('#continue-code-error')?.textContent.includes(${JSON.stringify(sentence)})`,
  );
}

async function round(language, reduced) {
  const text = (zh, en) => (language === 'en' ? en : zh);
  const name = `${language}-${reduced ? 'reduced' : 'default'}`;
  const shot = (browser, step) => browser.shot(`${shots}/${name}-${step}.jpg`);
  const replied = text('回复了', 'replied');
  const browsers = [];
  try {
    const a = await opened(language, reduced);
    browsers.push(a);
    await a.click('[data-action="open-career"]');
    await a.click('.case-hero [data-action="take-case"]');
    await acceptEntryStory(a);
    await waitFor(a, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
    await a.click('.card-open');
    await waitFor(a, `!!document.querySelector('[data-action="chat"][data-role="technical"]')`);
    await a.click('[data-action="chat"][data-role="technical"]');
    await waitFor(a, `document.querySelector('.composer [type="submit"]')?.disabled === false`);
    await a.type(
      '#chat-input',
      text('当前试点容量是多少？', 'What is the current pilot capacity?'),
    );
    await a.submit('.composer');
    await waitFor(a, `document.querySelectorAll('.rc-roles__reply').length > 0`, 60000);
    await a.type('#new-title', text('试点决定草稿', 'Pilot decision draft'));
    await a.type(
      '#new-body',
      text('负责人和范围核实前暂缓。', 'Defer until owner and scope are verified.'),
    );
    await a.clickText(text('保存为作品', 'Save as work'));
    await waitFor(a, `!!document.querySelector('.ol-row[data-type="work"]')`);
    await a.click('[data-action="to-board"]');
    await a.click('.product-bar [data-action="open-bench"]');
    await a.type('#lab-q', text('住宿报销上限是多少？', 'What is the hotel limit?'));
    await a.submit('[data-form="run-test"]');
    await waitFor(a, `document.querySelectorAll('.run').length > 0`, 30000);
    await a.click('[data-action="to-board"]');
    const before = await board(a);
    assert.ok(before.selected, 'A has a selected task');
    const first = await newCode(a);
    await shot(a, 'a-code');
    await closeDialog(a);
    results.push({ language, step: 'A creates a continue code from ⋯' });

    const b = await opened(language, reduced);
    browsers.push(b);
    await b.click('[data-action="continue-code-home"]');
    await waitFor(b, `document.activeElement?.id === 'continue-code-input'`);
    await enter(b, '0000-0000-0000-0000-0000');
    await refused(
      b,
      text('这个继续码不对，或已经换过新码。', 'This code is wrong or has been replaced.'),
    );
    await enter(b, first.toLowerCase().replaceAll('-', ' '));
    await waitFor(b, `location.hash === '#/work' && !!document.querySelector('.card-open')`, 30000);
    await waitFor(
      b,
      `window.notices.some((said) => said.includes(${JSON.stringify(text('已找回', 'Restored'))}))`,
    );
    const after = await board(b);
    for (const key of ['practice', 'tasks', 'works', 'tests', 'replies'])
      assert.deepEqual(after[key], before[key], `B shows a different ${key}`);
    assert.equal(
      await b.ev(`window.notices.some((said) => said.includes(${JSON.stringify(replied)}))`),
      false,
      'B announced replies from the other browser as new',
    );
    await shot(b, 'b-board');
    results.push({ language, step: 'B opens the same board; its history is not news' });

    await a.click('.ws-toolbar [data-menu="more"]');
    await a.click('[data-action="continue-code"]');
    await waitFor(a, `document.activeElement?.dataset.action === 'close'`);
    await a.click('[data-action="continue-code-create"]');
    await waitFor(a, `!!document.querySelector('[data-continue-code-value]')`);
    const second = await a.ev(`document.querySelector('[data-continue-code-value]').textContent`);
    assert.notEqual(second, first);
    await closeDialog(a);

    const c = await opened(language, reduced);
    browsers.push(c);
    await c.click('[data-action="continue-code-home"]');
    await enter(c, first);
    await refused(
      c,
      text('这个继续码不对，或已经换过新码。', 'This code is wrong or has been replaced.'),
    );
    await shot(c, 'c-old-code');
    results.push({ language, step: 'a replaced code is refused' });

    await a.goto(`${base}#/pm`);
    await waitFor(a, `!!document.querySelector('[data-continue-code] summary')`);
    await a.click('[data-continue-code] summary');
    await listen(a);
    await enter(a, second);
    await waitFor(
      a,
      `window.notices.some((said) => said.includes(${JSON.stringify(text('这是你在本机的练习', 'already on this browser'))}))`,
      30000,
    );
    const again = await board(a);
    assert.equal(again.practices, 1);
    assert.equal(again.selected, before.selected, 'A lost its selected task');
    assert.equal(
      await a.ev(`window.notices.some((said) => said.includes(${JSON.stringify(replied)}))`),
      false,
      'A announced replies it had already read',
    );
    await shot(a, 'a-own-code');
    results.push({ language, step: 'A entering its own code is only switched to it' });

    for (const browser of browsers)
      assert.deepEqual(
        browser.logs.filter((item) => item.level === 'exception'),
        [],
      );
  } finally {
    for (const browser of browsers) await browser.close();
    writeFileSync(`${output}/practice-recovery.json`, `${JSON.stringify(results, null, 2)}\n`);
  }
}

await round('zh', true);
await round('en', false);
console.log('practice-recovery: Chinese reduced and English default motion passed');
