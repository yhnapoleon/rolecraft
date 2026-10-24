/** Normal-entry steps for asking how to prioritise, reading cited evidence, the activity tab and
 * the Agent log. Each step takes the published-flows context and asserts what a person sees. */
import assert from 'node:assert/strict';
import { waitFor } from './browser-support.mjs';
import { openMyAgent } from './mcp-connection.mjs';

const attempt = 'window.PracticeLive.engine.getAttempt(window.PracticeLive.state)';
const host = `window.PracticeLive.v4Host(${attempt})`;

/** "Ask how to prioritise" → a colleague: their chat opens with the current tasks and the
 * question already written, kept as that colleague's draft until sent. */
export async function askHowToPrioritise(context) {
  const { browser, text, shot } = context;
  await browser.click('[data-action="menu"][data-menu="rank"]');
  await browser.click('[data-action="ask-priority"][data-role="business"]');
  await waitFor(
    browser,
    `(document.querySelector('.chat.who-business #chat-input')?.value ?? '') !== ''`,
  );
  const question = await browser.ev(`document.querySelector('#chat-input').value`);
  const titles = await browser.text('.kanban .card-title');
  assert.ok(titles.length > 0, 'the board shows tasks');
  for (const title of titles) assert.ok(question.includes(title), `asks about “${title}”`);
  assert.ok(question.includes(text('先弄清哪件，为什么', 'tackle first, and why')), question);
  assert.equal(await browser.ev('document.activeElement?.id'), 'chat-input');
  assert.equal(await browser.ev(`!!document.querySelector('[data-action="ask-priority"]')`), false);
  await waitFor(
    browser,
    `${host}.draft('roles', 'question:business_lead') === ${JSON.stringify(question)}`,
  );
  await shot('ask-priority');
  // Nothing is sent; clear the draft so later steps start from an empty conversation.
  await browser.type('#chat-input', '');
  await browser.click('[data-action="rail"][data-rail="team"]');
}

/** On the feedback page: a cited document says which document and version it is, and opening
 * it shows the original in view with focus on its title; closing returns to the button. Checked
 * on a short desktop window and at phone width, where the reader sits below the feedback. */
export async function openEvidence(context) {
  const { browser, text, shot } = context;
  const selector = JSON.stringify('.native-feedback button[data-reference-kind="material"]');
  await waitFor(browser, `!!document.querySelector(${selector})`, 30000);
  const named = await browser.ev(`(() => {
    const button = document.querySelector(${selector});
    return { text: button.textContent.trim(), label: button.getAttribute('aria-label') ?? '' };
  })()`);
  assert.match(named.text, / · v\d+$/, named.text);
  assert.doesNotMatch(named.text, /^(材料|资料|Material|Document) · /, named.text);
  const action = text('打开依据：', 'Open evidence: ');
  assert.ok(named.label.startsWith(action), named.label);
  const original = await browser.ev('({ width: innerWidth, height: innerHeight })');
  for (const [name, width, height] of [
    ['desktop', 1440, 760],
    ['phone', 390, 844],
  ]) {
    await viewport(browser, width, height);
    await browser.ev(`(() => {
      window.scrollTo(0, 0);
      const button = document.querySelector(${selector});
      // Cited evidence sits in folded detail (a feedback row's basis, 195); a person unfolds it first.
      for (let node = button.parentElement; node; node = node.parentElement) {
        if (node.tagName === 'DETAILS') node.open = true;
        if (node.hidden && node.id)
          document.querySelector('[aria-controls="' + node.id + '"][aria-expanded="false"]')?.click();
      }
      button.scrollIntoView({ block: 'center' });
      button.focus();
      button.click();
    })()`);
    await waitFor(
      browser,
      `document.activeElement?.tagName === 'H2' &&
        !!document.activeElement.closest('[data-v4-reference-side]')`,
    );
    assert.equal(
      await browser.ev('document.activeElement.textContent'),
      named.label.slice(action.length),
      'the reader names what was opened',
    );
    // Smooth scrolling may still be settling; the title must come to rest in view.
    await waitFor(
      browser,
      `(() => {
        const r = document.activeElement.getBoundingClientRect();
        return r.top >= 0 && r.bottom <= window.innerHeight;
      })()`,
      5000,
    );
    assert.ok(
      (await browser.ev(`document.querySelector('[data-v4-reference-side]').innerText.length`)) >
        40,
      'the original text is shown',
    );
    // The reader shares the column with the practice choices: on a short desktop window the
    // first choice stays in view, and a choice reached by keyboard comes into view.
    const choices = JSON.stringify('[data-v4-practice] [data-action="practice-choose"]');
    await waitFor(browser, `document.querySelectorAll(${choices}).length > 0`, 30000);
    if (name === 'desktop')
      assert.ok(
        await browser.ev(seen(`document.querySelector(${choices})`)),
        'a practice choice is in view beside the reader',
      );
    await browser.ev(`[...document.querySelectorAll(${choices})].at(-1).focus()`);
    await waitFor(browser, seen('document.activeElement'), 5000);
    await shot(`evidence-${name}`);
    // Refreshing the feedback rebuilds its sections while the reader is open: the evidence
    // button is replaced and its section folds again. Closing still returns focus to it.
    await browser.ev(`document.querySelector(${selector}).dataset.beforeRefresh = 'true'`);
    await browser.clickText(text('刷新', 'Refresh'), '.native-feedback button');
    await waitFor(
      browser,
      `!document.querySelector(${selector}).dataset.beforeRefresh &&
        !!document.querySelector('[data-reference-reader]')`,
    );
    await browser.clickText(text('关闭', 'Close'), '[data-v4-reference-side] button');
    await waitFor(browser, `document.activeElement === document.querySelector(${selector})`);
  }
  await viewport(browser, original.width, original.height);
}

/** An expression: the element is in the window and on top at its centre (not under the bar). */
const seen = (element) => `(() => {
  const node = ${element};
  if (!node) return false;
  const r = node.getBoundingClientRect();
  if (r.width === 0 || r.top < 0 || r.bottom > window.innerHeight) return false;
  const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return !!top && (top === node || node.contains(top));
})()`;

async function viewport(browser, width, height) {
  await browser.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 2,
    mobile: false,
  });
  await waitFor(browser, `window.innerWidth === ${width}`);
}

/** Back on the board: the activity tab reads as sentences that open what they name, and the
 * Agent log lists only Agent records. */
export async function readActivity(context) {
  const { browser, text, shot, question } = context;
  await browser.click('.rail-tabs [data-tab="activity"]');
  await waitFor(browser, `document.querySelectorAll('.activity .act-item').length > 0`);
  const lines = await browser.text('.activity .act-item .grow');
  assert.deepEqual(
    lines.filter((line) => /[a-z]+_[a-z_]+/.test(line)),
    [],
    'no event codes in the activity',
  );
  for (const expected of [
    text('测试：', 'Test: ') + question,
    text('第 1 次交付已提交', 'Delivery 1 submitted'),
    text('开始修订', 'Started a revision'),
  ])
    assert.ok(lines.includes(expected), `“${expected}” in ${lines.join(' | ')}`);
  assert.equal(
    await browser.ev(`[...document.querySelectorAll('.activity .act-open')]
      .find((button) => button.textContent.includes(${JSON.stringify(question)}))
      ?.dataset.action`),
    'open-run',
  );
  await shot('activity');
  // The Agent log is the My agent page's transmission stream: sentences, tool names apart.
  await openMyAgent(browser);
  const written = await browser.ev(`document.querySelector('[data-agent-page]').innerText`);
  for (const noise of ['工作记录', 'Work record', '查看依据', 'View source', '你 · ', 'You · '])
    assert.ok(!written.includes(noise), `the Agent log lists “${noise}”`);
  const said = await browser.text('.ag-line .ag-say');
  assert.deepEqual(
    said.filter((line) => /[a-z]+_[a-z_]+/.test(line)),
    [],
    'no tool or event codes in the Agent sentences',
  );
  await shot('agent-log');
  await browser.ev(`location.hash = '#/work'`);
  await waitFor(browser, `!!document.querySelector('.card-open')`);
}
