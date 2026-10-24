// Engineer walkthrough over the normal entry (real HTTP, local provider): the open engineer card,
// the sign-off desk with the system's setup said plainly, a too-broad fix (warn + min score 0.2)
// drafted by hand, signed and reported (public all pass, one hidden new failure, E2 not met), a
// second round with the root-cause fix (warn only: two hidden fixed, E1 and E2 met), and the
// product side's "hand to engineering" from the test bench. Screenshots for design review.
//
// BASE=http://127.0.0.1:18583 OUT=<dir> LANG_UI=zh|en [THEME=dark] [WIDTH=390] [REDUCED=1] \
//   CHROME_BIN=… node apps/web/tests/walkthrough/engineer-desk.mjs
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { delay, launch } from './cdp.mjs';

const base = process.env.BASE;
const out = process.env.OUT;
const language = process.env.LANG_UI === 'en' ? 'en' : 'zh';
const dark = process.env.THEME === 'dark';
const width = Number(process.env.WIDTH || 1440);
const reduced = process.env.REDUCED === '1';
const full = process.env.FULL !== '0';
assert.ok(base && out, 'BASE and OUT are required');
mkdirSync(out, { recursive: true });
const tag = `${language}-${dark ? 'dark' : 'light'}-${width}${reduced ? '-reduced' : ''}`;
const zh = language === 'zh';
const say = (cn, en) => (zh ? cn : en);
const results = [];

const browser = await launch({
  width,
  height: width < 600 ? 844 : 900,
  dark,
  mobile: width < 600,
  reduced,
});

async function waitFor(expression, ms = 20000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await browser.ev(expression)) return;
    await delay(100);
  }
  throw new Error(`Timed out: ${expression}`);
}
const shots = [];
async function shot(name, fullPage = false) {
  const path = `${out}/${name}-${tag}.jpg`;
  await delay(reduced ? 150 : 450);
  await browser.shot(path, fullPage);
  shots.push(path);
}
async function step(name, fn) {
  const started = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - started });
    console.log(`ok   ${name}`);
  } catch (error) {
    results.push({ name, ok: false, error: String(error?.stack || error) });
    console.log(`FAIL ${name}\n${error?.stack || error}`);
    await shot(`fail-${name.replace(/\W+/g, '-')}`, true).catch(() => {});
    throw error;
  }
}
const text = (sel) =>
  browser.ev(
    `document.querySelector(${JSON.stringify(sel)})?.textContent.replace(/\\s+/g, ' ').trim() ?? ''`,
  );
const setValue = (sel, value) =>
  browser.ev(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return false;
    el.focus(); el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const enabled = (sel) =>
  `!!document.querySelector(${JSON.stringify(sel)}) && !document.querySelector(${JSON.stringify(sel)}).disabled`;
const lineCount = () => browser.ev(`document.querySelectorAll('.ed-line').length`);
const noRawCodes = async (where) => {
  const body = await browser.ev(`document.querySelector('main')?.innerText ?? ''`);
  for (const bad of [
    'engineer_',
    'answered_with_warning',
    '"schema_version"',
    'ticket-',
    'review-',
    'trial-',
    'draft-',
    '模拟',
    'simulat',
  ]) {
    assert.ok(!body.includes(bad), `${where}: shows ${bad}`);
  }
};

/** The connection card's own copy action, captured instead of the system clipboard. */
async function copied(action) {
  await browser.ev(`(() => { window.edCopied = null; Object.defineProperty(navigator.clipboard, 'writeText',
    { configurable: true, value: async (t) => { window.edCopied = t; } }); return true; })()`);
  await browser.click(`.ed-agent [data-connection-action="${action}"]`);
  await waitFor('typeof window.edCopied === "string"');
  return browser.ev('window.edCopied');
}
/** What the person's own Agent sends over MCP (Streamable HTTP, 2026-07-28): a scripted client. */
async function agentCall(endpoint, token, name, args) {
  const meta = {
    'io.modelcontextprotocol/protocolVersion': '2026-07-28',
    'io.modelcontextprotocol/clientCapabilities': {},
    'io.modelcontextprotocol/clientInfo': { name: 'engineer-walkthrough', version: '1' },
  };
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
      Authorization: `Bearer ${token}`,
      'MCP-Protocol-Version': '2026-07-28',
      'Mcp-Method': 'tools/call',
      'Mcp-Name': name,
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'tools/call',
      params: { name, arguments: args, _meta: meta },
    }),
  });
  const body = await response.json();
  assert.equal(response.status, 200, JSON.stringify(body));
  assert.equal(body.result.isError, false, JSON.stringify(body.result));
  return body.result.structuredContent;
}
const agentCommand = (operation, payload) => ({
  command: {
    schema_version: 2,
    request_id: `walk-${operation}-${Date.now()}`,
    operation,
    payload,
    expected_version: 0,
    expected_workspace_revision: 0,
  },
});

async function draftAndSign({ explanation, reasons, impact }) {
  await browser.click('#ed-compose');
  await waitFor(`!!document.querySelector('#ed-draft-explanation')`);
  await setValue('#ed-draft-explanation', explanation);
  for (const [i, reason] of reasons.entries()) await setValue(`#ed-st-${i}-reason`, reason);
  await browser.click('#ed-claims-on');
  await waitFor(enabled('#ed-claims-fill'));
  await browser.click('#ed-claims-fill');
  if (full) await shot('desk-compose');
  const before = await browser.ev(`document.querySelector('.ed-sheet__byline')?.textContent ?? ''`);
  await browser.click('#ed-draft-save');
  await waitFor(
    `!!document.querySelector('.ed-compare') && !document.querySelector('#ed-draft-explanation')`,
  );
  void before;
  await setValue('#ed-impact', impact);
  await waitFor(enabled('#ed-sign'));
  await browser.ev(`document.querySelector('.ed-sheet').scrollIntoView({ block: 'start' })`);
  await delay(100);
  assert.ok(
    await browser.ev(
      `document.querySelector('#ed-sheet-h').getBoundingClientRect().top >= document.querySelector('.topbar').getBoundingClientRect().bottom`,
    ),
    'the sign sheet title lands below the top bar',
  );
  await shot('desk-sign-sheet');
  await browser.click('#ed-sign');
  await waitFor(
    `location.hash.startsWith('#/engineer-review/') && !!document.querySelector('.er-report')`,
  );
}

try {
  await browser.goto(base);
  await browser.ev(
    `localStorage.clear(); sessionStorage.clear(); localStorage.setItem('rolecraft.locale', ${JSON.stringify(language)});`,
  );
  await browser.goto(base);

  await step('home: the engineer card is open, with no lock or "later"', async () => {
    await waitFor(`!!document.querySelector('[data-action="engineer-start"]')`);
    const card = await text('[data-career="engineer"]');
    assert.ok(!card.includes('稍后开放') && !card.includes('Coming later'), card);
    assert.equal(
      await browser.ev(
        `document.querySelector('[data-career="engineer"]').getAttribute('aria-disabled')`,
      ),
      null,
    );
    assert.ok(
      card.includes(
        say('复现产品经理记录的失败', 'Reproduce the failure the product manager recorded'),
      ) && !card.includes('AIPM'),
      card,
    );
    await shot('home');
  });

  await step(
    'start: a new practice opens on the sign-off desk, with the system setup said',
    async () => {
      await browser.click('[data-action="engineer-start"]');
      await waitFor(
        `location.hash.startsWith('#/engineer/') && !!document.querySelector('.ed-slip .ed-target')`,
        40000,
      );
      assert.ok((await text('.ed-hat__role')) === say('工程师', 'Engineer'));
      const setup = await text('.ed-setup');
      assert.ok(
        setup.includes(
          say(
            '起始状态由系统准备，不是你的操作',
            'The system prepared this starting state, not you',
          ),
        ),
        setup,
      );
      const stale = await text('.ed-target__facts .is-stale');
      assert.ok(stale.includes(say('索引 v1，索引落后', 'index v1, index behind')), stale);
      assert.equal(
        await text('.ed-sign__who'),
        say('只能由你签 · 还剩 3 次复核', 'Only you can sign · 3 reviews left'),
      );
      assert.equal(
        await browser.ev(`document.querySelectorAll('.ed .btn.primary').length`),
        1,
        'one ink key on the desk',
      );
      await noRawCodes('desk');
      assert.ok(
        await browser.ev('document.documentElement.scrollWidth <= window.innerWidth'),
        'no sideways scroll',
      );
      await shot('desk', true);
      await shot('desk-top');
    },
  );

  await step('reproduce: the failure is still there, logged as yours', async () => {
    await browser.click('#ed-reproduce');
    await waitFor(`document.querySelectorAll('.ed-line').length === 1`);
    const line = await text('.ed-line__head');
    assert.ok(line.includes(say('你', 'You')) && line.includes(say('复现', 'Reproduce')), line);
    assert.ok(line.includes(say('1/1 与记录一致', '1/1 match the record')), line);
  });

  await step(
    'agent: the ticket grant, then its trial and draft appear as your agent’s',
    async () => {
      await browser.click('#ed-grant');
      await waitFor(`!!document.querySelector('.ed-agent [data-connection-card]')`);
      const card = await text('.ed-agent [data-connection-card]');
      assert.ok(card.includes('claude mcp add') && card.includes('••••••'), card);
      await browser.ev(`document.querySelector('.ed-agent').scrollIntoView({ block: 'start' })`);
      await shot('desk-agent-card');
      const endpoint = await copied('copy-endpoint');
      const token = await copied('copy-token');
      const ticket = decodeURIComponent(await browser.ev(`location.hash.split('/')[2]`));
      const before = await lineCount();
      const tried = await agentCall(
        endpoint,
        token,
        'engineer.trial',
        agentCommand('engineer.trial', {
          ticket_id: ticket,
          changes: { freshness_guard: 'warn', min_score: 0.2 },
        }),
      );
      assert.equal(tried.result.trial.executor.kind, 'external_agent');
      await agentCall(
        endpoint,
        token,
        'engineer.submissions.draft',
        agentCommand('engineer.submissions.draft', {
          ticket_id: ticket,
          changes: { freshness_guard: 'warn', min_score: 0.2 },
          explanation: say(
            '索引落后时加提醒，并把阈值调低一点把新政策找回来。',
            'Warn when the index lags, and lower the threshold a little to bring the new policy back.',
          ),
          change_statements: [
            {
              field: 'freshness_guard',
              before: 'none',
              after: 'warn',
              reason: say('索引落后时提醒用户核对。', 'Tell users to check when the index lags.'),
            },
          ],
          claimed_results: { F01: 'pass', F04: 'pass', F05: 'pass', F12: 'pass' },
        }),
      );
      // The desk reads the ticket again on its own (every few seconds).
      await waitFor(
        `document.querySelectorAll('.ed-line').length === ${before + 1} && !!document.querySelector('.ed-line[data-agent="true"]')`,
        15000,
      );
      await waitFor(
        `(document.querySelector('.ed-sheet__byline')?.textContent ?? '').toLowerCase().includes('agent')`,
        15000,
      );
      // Signing without the impact note is stopped here, with one sentence and the field focused.
      await browser.click('#ed-sign');
      await waitFor(
        `(document.querySelector('.ed-sheet [role="alert"]')?.textContent ?? '') !== ''`,
      );
      assert.equal(
        await text('.ed-sheet [role="alert"]'),
        say(
          '先写这个改动还可能影响哪些问题。',
          'Write which questions this change might affect first.',
        ),
      );
      assert.equal(await browser.ev(`document.activeElement.id`), 'ed-impact');
      assert.ok((await browser.ev('location.hash')).startsWith('#/engineer/'));
      await browser.click('.ed-line[data-agent="true"] .ed-line__head');
      await waitFor(`!!document.querySelector('.ed-line[data-agent="true"] .ed-rows-note')`);
      await browser.ev(`document.querySelector('.ed-log').scrollIntoView({ block: 'start' })`);
      await shot('desk-agent-log');
      await browser.ev(`document.querySelector('.ed-sheet').scrollIntoView({ block: 'start' })`);
      await shot('desk-agent-draft');
      await browser.click('.ed-line[data-agent="true"] .ed-line__head');
    },
  );

  await step('trial: warn + min score 0.2 passes all four public probes', async () => {
    await browser.click('#ed-f-freshness_guard-warn');
    await setValue('#ed-f-min_score', '0.2');
    const diff = await text('.ed-diff');
    assert.ok(diff.includes(say('最低相关度', 'Minimum relevance')) && diff.includes('0.2'), diff);
    const before = await lineCount();
    await browser.click('#ed-trial');
    await waitFor(`document.querySelectorAll('.ed-line').length === ${before + 1}`);
    const line = await text('.ed-line:first-child .ed-line__head');
    assert.ok(line.includes(say('公开 4/4 通过', 'Public 4/4 passed')), line);
    assert.equal(
      await browser.ev(
        `document.querySelector('.ed-line:first-child .ed-line__head').getAttribute('aria-expanded')`,
      ),
      'true',
    );
    assert.equal(
      await browser.ev(`document.querySelectorAll('.ed-line:first-child .ed-row').length`),
      4,
    );
    await noRawCodes('trial');
    await browser.ev(`document.querySelector('.ed-log').scrollIntoView({ block: 'start' })`);
    await shot('desk-trial-log');
  });

  await step(
    'draft and sign the too-broad fix: hidden new failure 1 (amber), E2 not met',
    async () => {
      await draftAndSign({
        explanation: say(
          '加提醒，并把最低相关度调到 0.2，把新政策找回来。',
          'Add the warning and lower the minimum relevance to 0.2 to bring the new policy back.',
        ),
        reasons: [
          say('索引落后时提醒', 'Warn when the index lags'),
          say('多找回一些资料', 'Retrieve a little more'),
        ],
        impact: say(
          '知识库外的问题可能被回答。',
          'Questions outside the knowledge base might get answered.',
        ),
      });
      const count = (key) =>
        browser.ev(
          `(() => { const c = document.querySelector('.er-counts--comparison .er-count[data-key="${key}"]'); return c ? c.dataset.tone + ':' + c.querySelector('dd').textContent : ''; })()`,
        );
      assert.equal(await count('new_failures'), 'warn:1', 'one hidden new failure, amber');
      const evaluation = await browser.ev(
        `[...document.querySelectorAll('.er-criterion')].map(n => n.dataset.criterion + ':' + n.dataset.mark).join(' ')`,
      );
      assert.ok(/E2[^ ]*:not_met/.test(evaluation), evaluation);
      // The headline says both: the target fixed, and one new failure (amber turn and line).
      assert.equal(
        await text('.er-verdict__title'),
        say('目标修好了，但新增 1 处失败', 'Target fixed, but 1 new failure'),
      );
      assert.equal(
        await browser.ev(
          `[...document.querySelectorAll('.er-verdict, .er-verdict__turn, .er-verdict__mark')].map(n => n.dataset.tone).join(' ')`,
        ),
        'warn warn warn',
      );
      assert.equal(
        await browser.ev(
          `[...document.querySelectorAll('.er-verdict__line')].map(n => n.dataset.tone + ':' + n.textContent).join(' | ')`,
        ),
        say(
          'good:✓F01 现在给出了委托记录的预期答案 | warn:↓1 个原来通过的隐藏探针现在失败',
          'good:✓F01 now gives the expected answer recorded with the ticket. | warn:↓1 hidden probe that passed before now fails.',
        ),
      );
      // Something newly broken: another round is the one ink key.
      assert.equal(
        await browser.ev(
          `[...document.querySelectorAll('.ed .btn.primary')].map(n => n.id).join(' ')`,
        ),
        'ed-again',
      );
      assert.ok(
        !(await browser.ev(`document.querySelector('main').innerText`)).includes(
          say('发回产品经理', 'Send back to product'),
        ),
      );
      await noRawCodes('report 1');
      assert.ok(
        await browser.ev('document.documentElement.scrollWidth <= window.innerWidth'),
        'no sideways scroll on the report',
      );
      await shot('report-overreach', true);
      await shot('report-overreach-top');
    },
  );

  await step(
    'fix it again: root cause only (warn), two hidden fixed (green), E1 and E2 met',
    async () => {
      await browser.click('#ed-again');
      await waitFor(
        `location.hash.startsWith('#/engineer/') && !!document.querySelector('#ed-trial')`,
      );
      assert.equal(
        await text('.ed-sign__who'),
        say('只能由你签 · 还剩 2 次复核', 'Only you can sign · 2 reviews left'),
      );
      // Back to the baseline, then the root cause only.
      await browser.click('#ed-reset');
      await browser.click('#ed-f-freshness_guard-warn');
      await waitFor(`document.querySelectorAll('.ed-field.is-changed').length === 1`);
      const before = await lineCount();
      await browser.click('#ed-trial');
      await waitFor(`document.querySelectorAll('.ed-line').length === ${before + 1}`);
      await draftAndSign({
        explanation: say(
          '只加提醒：索引落后时提示用户核对当前政策。',
          'Warn only: when the index lags, tell the user to check the current policy.',
        ),
        reasons: [say('索引落后时提醒', 'Warn when the index lags')],
        impact: say(
          '凡是引用差旅政策的回答都会多一句提醒。',
          'Every answer citing the travel policy gets the warning line.',
        ),
      });
      const count = (key) =>
        browser.ev(
          `(() => { const c = document.querySelector('.er-counts--comparison .er-count[data-key="${key}"]'); return c ? c.dataset.tone + ':' + c.querySelector('dd').textContent : ''; })()`,
        );
      assert.equal(await count('fixed'), 'good:2', 'two hidden fixed, green');
      assert.equal(await count('new_failures'), 'ink:0');
      const evaluation = await browser.ev(
        `[...document.querySelectorAll('.er-criterion')].map(n => n.dataset.criterion + ':' + n.dataset.mark).join(' ')`,
      );
      assert.ok(/E1[^ ]*:met/.test(evaluation) && /E2[^ ]*:met/.test(evaluation), evaluation);
      assert.equal(await browser.ev(`document.querySelectorAll('.ed-review-list li').length`), 2);
      assert.equal(
        await text('.er-verdict__title'),
        say('目标问题已修好', 'Target fixed'),
      );
      assert.equal(await browser.ev(`document.querySelectorAll('.er-verdict__lines').length`), 0);
      // Everything holds: back to the product board leads; another round steps down.
      assert.equal(
        await browser.ev(
          `[...document.querySelectorAll('.ed .btn.primary')].map(n => n.id).join(' ')`,
        ),
        'ed-to-board',
      );
      assert.equal(
        await text('#ed-to-board'),
        say('回到产品经理工作板', 'Back to the product board'),
      );
      assert.ok(await browser.ev(`!!document.querySelector('#ed-again:not(.primary)')`));
      await shot('report-root-cause', true);
      await shot('report-root-cause-top');
    },
  );

  await step('back by level: report → desk → product board', async () => {
    await browser.click('a[data-engineer-back]');
    await waitFor(
      `location.hash.startsWith('#/engineer/') && !!document.querySelector('.ed-slip')`,
    );
    assert.equal(await browser.ev(`document.querySelectorAll('.ed-review-list li').length`), 2);
    await browser.click('.topbar a.back');
    await waitFor(`location.hash === '#/work' && !!document.querySelector('.product-bar')`, 30000);
    // The activity says the system, not the learner, put the pilot live for the ticket.
    if (width >= 1280) {
      await browser.click('.rail-tabs [data-tab="activity"]');
      await waitFor(
        `[...document.querySelectorAll('.activity .act-item')].some((n) => n.textContent.includes(${JSON.stringify(say('系统为工程委托准备的起始状态，不是你的操作', 'set up by the system for the engineering ticket, not by you'))}))`,
      );
      await shot('board-activity-golive');
    }
  });

  await step('product side: a bench test handed to engineering opens a desk for it', async () => {
    await browser.click('[data-action="open-bench"]');
    await waitFor(`!!document.querySelector('#lab-q')`);
    await setValue(
      '#lab-q',
      say('住宿报销上限是多少？', 'What is the hotel reimbursement limit per night?'),
    );
    await browser.submit('form[data-form="run-test"]');
    await waitFor(`!!document.querySelector('[data-action="engineer-handover"]')`, 40000);
    await browser.click('[data-action="engineer-handover"]');
    await waitFor(`!!document.querySelector('dialog.ed-handover[open]')`);
    const count = await text('.ed-handover__count');
    assert.ok(count.includes(say('最多 10 条', 'up to 10')), count);
    assert.ok(
      await browser.ev(`document.activeElement?.matches('dialog.ed-handover .sheet-head h2')`),
      'the dialog title takes the first focus',
    );
    await shot('handover-dialog');
    await browser.click('#ed-handover-submit');
    await waitFor(
      `location.hash.startsWith('#/engineer/') && !!document.querySelector('.ed-slip .ed-target')`,
      30000,
    );
    const facts = await text('.ed-facts');
    assert.ok(
      facts.includes(say('来源：产品经理交来', 'Source: handed over by product')),
      facts,
    );
    await shot('desk-from-tests');
  });

  await step(
    'home again: the same practice offers the engineer’s ticket as a second entry',
    async () => {
      await browser.goto(`${base}#/`);
      await waitFor(`!!document.querySelector('[data-action="engineer-take"]')`);
      await browser.ev(
        `document.querySelector('[data-career="engineer"]').scrollIntoView({ block: 'center' })`,
      );
      await shot('home-with-practice');
      await browser.click('[data-action="engineer-take"]');
      await waitFor(
        `location.hash.startsWith('#/engineer/') && !!document.querySelector('.ed-slip .ed-target')`,
        30000,
      );
      assert.equal(
        await text('.ed-facts .ed-fact'),
        say('来源：委托附带', 'Source: attached to the ticket'),
      );
      assert.equal(
        await browser.ev(`document.querySelectorAll('.ed-review-list li').length`),
        2,
        'the same ticket, with its reviews',
      );
    },
  );

  if (!process.env.SKIP_KEYS) {
    await step(
      'keyboard: Enter reproduces, Enter folds the new line, Tab shows the focus ring',
      async () => {
        const key = async (k, code, vk, text) => {
          await browser.send('Input.dispatchKeyEvent', {
            type: 'keyDown',
            key: k,
            code,
            windowsVirtualKeyCode: vk,
            ...(text ? { text } : {}),
          });
          await browser.send('Input.dispatchKeyEvent', {
            type: 'keyUp',
            key: k,
            code,
            windowsVirtualKeyCode: vk,
          });
          await delay(250);
        };
        const before = await lineCount();
        await browser.ev(`document.querySelector('#ed-reproduce').focus()`);
        await key('Enter', 'Enter', 13, '\r');
        await waitFor(`document.querySelectorAll('.ed-line').length === ${before + 1}`);
        await browser.ev(`document.querySelector('.ed-line__head').focus()`);
        assert.equal(
          await browser.ev(
            `document.querySelector('.ed-line__head').getAttribute('aria-expanded')`,
          ),
          'true',
        );
        await key('Enter', 'Enter', 13, '\r');
        await waitFor(
          `document.querySelector('.ed-line__head').getAttribute('aria-expanded') === 'false'`,
        );
        assert.equal(
          await browser.ev(`document.activeElement === document.querySelector('.ed-line__head')`),
          true,
          'focus stays on the line',
        );
        await key('Tab', 'Tab', 9);
        assert.equal(await browser.ev(`document.activeElement.matches(':focus-visible')`), true);
        assert.notEqual(
          await browser.ev(`getComputedStyle(document.activeElement).outlineStyle`),
          'none',
          'focus ring visible',
        );
        await browser.ev(`document.activeElement.scrollIntoView({ block: 'center' })`);
        await shot('desk-keyboard-focus');
      },
    );
  }
} finally {
  writeFileSync(
    `${out}/result-${tag}.json`,
    JSON.stringify({ tag, results, shots, logs: browser.logs }, null, 2),
  );
  await browser.close();
}
const failed = results.filter((r) => !r.ok);
console.log(`${results.length - failed.length}/${results.length} steps passed (${tag})`);
process.exit(failed.length ? 1 : 0);
