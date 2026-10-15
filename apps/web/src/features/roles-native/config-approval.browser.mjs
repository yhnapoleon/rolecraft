/**
 * Normal v4 entry over a real API and worker: saved vs used configuration, the real-time
 * strategy's work item, the request form's terms, the approval decision card (a plan that no
 * request can pass, over the ceiling or missing its hand-off, goes to its settings) and the
 * decisions as the feedback records them after delivery, in the order they were requested.
 *
 * Usage: CHROME_BIN=… node config-approval.browser.mjs <base URL> <evidence dir> <zh|en> [default]
 * The fourth argument runs with default motion and covers settings, requests and the delivered
 * feedback only (no document cards). Without it the whole path runs with reduced motion.
 */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { clickReady, waitFor } from '../../../tests/regression/browser-support.mjs';
import { delay, launch } from '../../../tests/walkthrough/cdp.mjs';

const [base, out, language = 'zh', motion = 'reduced'] = process.argv.slice(2);
if (!base || !out) throw Error('base URL and evidence directory required');
mkdirSync(out, { recursive: true });
const en = language === 'en';
const text = (zh, english) => (en ? english : zh);
const full = motion !== 'default';
const browser = await launch({ width: 1440, height: 1100, reduced: full });
const passed = [];
const step = async (name, action) => {
  await action();
  passed.push(name);
  console.log(`PASS ${language}/${motion}: ${name}`);
};
const shot = async (name) => {
  await browser.ev('document.fonts.ready.then(() => true)');
  await delay(250);
  return browser.shot(`${out}/${language}-${motion}-${name}.jpg`);
};
/** Bring one element to the middle of the screen, once the save notice has gone. */
const focusShot = async (selector, name, last = false) => {
  await waitFor(browser, `!document.querySelector('#toast.visible')`, 8000);
  await browser.ev(
    `[...document.querySelectorAll(${JSON.stringify(selector)})].at(${last ? -1 : 0})?.scrollIntoView({ block: 'center' })`,
  );
  return shot(name);
};
const viewport = (width, height, mobile = false) =>
  browser.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 2,
    mobile,
    screenWidth: width,
    screenHeight: height,
  });
const innerText = (selector) =>
  browser.ev(
    `(document.querySelector(${JSON.stringify(selector)})?.innerText ?? '').replace(/\\s+/g, ' ').trim()`,
  );
const savedPilot = () =>
  browser.ev('JSON.parse(JSON.stringify(window.PracticeLive.store.active().world.configs.pilot))');
const realtimeBox = `document.querySelector('#config-form input[name="workItems"][value="realtime"]')`;
const gapLine = text(
  '测试实际用：每日索引 · 实时同步还没批到开发人日（已批准 3 人日）',
  "Tests actually use: Daily index · Real-time sync isn't funded yet (3 developer-days approved)",
);
const ceiling = text(
  '可审批上限：容量60人，开发资源6人日，期限第10天。',
  'Approval ceilings: capacity 60 people, 6 developer-days, and deadline day 10.',
);
const question = text('住宿报销上限是多少？', 'What is the hotel reimbursement limit per night?');
/** Labels of the buttons on a decision card, by position (-1 is the latest). */
const cardButtons = (index) =>
  browser.ev(
    `[...[...document.querySelectorAll('[data-decision-card]')].at(${index}).querySelectorAll('button')].map((b) => b.textContent.trim())`,
  );
const viewSource = text('看原文', 'View source');
const capped = text('按上限改申请', 'Re-apply at the ceiling');
const adjust = text('调整设置', 'Adjust settings');
const replan = text(
  '方案需要 7，上限 6：先把方案降到 6 以内再申请',
  'The plan needs 7, over the ceiling of 6: bring it down to 6 or less before requesting',
);

async function openSettings() {
  await browser.click('.product-bar [data-action="config"]');
  await waitFor(browser, `!!document.querySelector('#config-form')`);
}
async function openRequests() {
  await browser.click('.product-bar [data-action="resources"]');
  await waitFor(browser, `!!document.querySelector('#res-form [name="dev_days"]')`);
  await browser.click('#res-form input[name="kind"][value="request_resources"]');
  await waitFor(browser, `document.querySelector('#res-form [name="dev_days"]').value !== ''`);
}
async function sendRequest(devDays, reason) {
  await browser.type('#res-form [name="dev_days"]', String(devDays));
  await browser.type('#res-form textarea[name="reason"]', reason);
  const before = await browser.ev(`document.querySelectorAll('[data-request-id]').length`);
  await browser.submit('#res-form');
  await waitFor(browser, `document.querySelectorAll('[data-request-id]').length > ${before}`);
  await clickReady(browser, text('核实申请', 'Check request'));
  await waitFor(
    browser,
    `document.querySelectorAll('[data-decision-card]').length > ${before}`,
    20000,
  );
}
const testCount = 'window.PracticeLive.store.active().tests.length';
async function runTest() {
  await browser.click('.product-bar [data-action="open-bench"]');
  await waitFor(browser, `!!document.querySelector('#lab-q')`);
  const tests = await browser.ev(testCount);
  await browser.type('#lab-q', question);
  await browser.submit('[data-form="run-test"]');
  await waitFor(browser, `${testCount} > ${tests}`, 20000);
  // Runs of one question share a card; the newest answer is its first column.
  await waitFor(browser, `!!document.querySelector('.run')`);
  return browser.ev(`window.PracticeLive.store.active().tests.at(-1).answer`);
}

/** Save one work, submit it and open the feedback page. */
async function deliver() {
  await browser.click('[data-action="to-board"]').catch(() => undefined);
  await waitFor(browser, `!!document.querySelector('.card-open')`);
  await browser.click('.card-open');
  await waitFor(browser, `!!document.querySelector('#new-title')`);
  await browser.type('#new-title', text('试点决定', 'Pilot decision'));
  await browser.type(
    '#new-body',
    text(
      '先向首批 20 人受限开放，保留人工兜底。',
      'Open to the first 20 people with a human fallback.',
    ),
  );
  await browser.clickText(text('保存为作品', 'Save as work'));
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
  await browser.click('[data-action="to-board"]').catch(() => undefined);
  await waitFor(browser, `!!document.querySelector('.ws-toolbar [data-action="submit"]')`);
  await browser.click('.ws-toolbar [data-action="submit"]');
  await waitFor(
    browser,
    `!!document.querySelector('#sheet .native-feedback input[type="checkbox"]')`,
  );
  await browser.click('#sheet .native-feedback input[type="checkbox"]');
  await browser.select('#sheet .native-feedback select', 'launch_narrow');
  await clickReady(browser, text('提交选中的版本', 'Submit selected versions'), '#sheet button');
  await waitFor(browser, `window.PracticeLive.store.active().world.status === 'submitted'`, 60000);
  await browser.ev(`document.querySelector('#sheet')?.close()`);
  await browser.goto(new URL('#/review', base).href);
}

try {
  await browser.goto(base);
  await browser.ev(`localStorage.clear(); localStorage.setItem('rolecraft.locale', '${language}')`);
  await browser.goto(base);
  await step('enter the normal workspace', async () => {
    await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
    await browser.click('[data-action="open-career"]');
    await browser.click('.case-hero [data-action="take-case"]');
    await waitFor(browser, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
  });

  await step('real-time strategy brings its work item, locked, counted once', async () => {
    await openSettings();
    await browser.click('#config-form input[name="update"][value="realtime"]');
    assert.deepEqual(
      await browser.ev(
        `[${realtimeBox}.checked, ${realtimeBox}.disabled, ${realtimeBox}.closest('label').querySelector('.strategy-note').hidden]`,
      ),
      [true, true, false],
    );
    assert.ok((await innerText('[data-checks]')).includes(text('开发 7 人日', '7 person-days')));
    await shot('settings-realtime');
    await browser.click('#config-form input[name="update"][value="daily"]');
    assert.deepEqual(await browser.ev(`[${realtimeBox}.checked, ${realtimeBox}.disabled]`), [
      false,
      false,
    ]);
    await browser.click('#config-form input[name="update"][value="realtime"]');
  });

  await step('saving names what tests actually use', async () => {
    await browser.submit('#config-form');
    await waitFor(browser, `!document.querySelector('#sheet')?.open`);
    await waitFor(browser, `!!document.querySelector('.product-bar [data-config-use]')`);
    const notice = await innerText('#toast');
    assert.ok(notice.includes(gapLine), notice);
    assert.ok((await savedPilot()).work_items.includes('realtime_sync'));
    assert.equal(await innerText('.product-bar [data-config-use]'), gapLine);
    assert.ok(
      (await innerText('.product-bar .pb-state')).startsWith(text('已保存 v1', 'Saved v1')),
    );
    await shot('bar-gap');
    await viewport(390, 844, true);
    await delay(300);
    assert.equal(
      await browser.ev(
        'document.documentElement.scrollWidth > document.documentElement.clientWidth',
      ),
      false,
    );
    await focusShot('.product-bar', 'bar-gap-390');
    await viewport(1440, 1100);
  });

  if (full)
    await step('the test bench shows the same line and answers from the daily index', async () => {
      const answer = await runTest();
      assert.equal(await innerText('.console [data-config-use]'), gapLine);
      assert.ok(answer.includes('500'), answer);
      await shot('bench-gap');
      await browser.click('[data-action="to-board"]');
    });

  await step('the request form sends only the changed total', async () => {
    await openRequests();
    assert.deepEqual(
      await browser.ev(
        `['dev_days', 'deadline_day'].map((k) => document.querySelector('#res-form [name="' + k + '"]').value)`,
      ),
      ['3', '7'],
    );
    await sendRequest(
      7,
      text('实时同步需要更多开发人日', 'Real-time sync needs more developer-days'),
    );
    const row = await innerText('[data-request-id]');
    assert.ok(row.includes(text('开发人日: 7', 'Developer-days: 7')), row);
    assert.ok(!row.includes(text('截止日', 'Deadline day')), row);
  });

  // 164 N1: real-time sync with its default safeguards needs 7 developer-days and the ceiling
  // is 6, so no request can pass; every such card sends the plan to its settings.
  await step('an over-ceiling plan is sent to its settings, not to a capped request', async () => {
    const card = await innerText('[data-decision-card]');
    assert.ok(card.includes(ceiling), card);
    assert.ok(
      card.includes(
        text(
          '开发人日：申请 7，超出上限 6；方案需要 7，超出上限 6',
          'Developer-days: requested 7, over the ceiling of 6; the plan needs 7, over the ceiling of 6',
        ),
      ),
      card,
    );
    assert.ok(card.includes(replan), card);
    assert.deepEqual(await cardButtons(0), [viewSource, adjust]);
    await focusShot('[data-decision-card]', 'decision-rejected');
    await viewport(390, 844, true);
    await delay(300);
    await focusShot('[data-decision-card]', 'decision-rejected-390');
    await viewport(1440, 1100);
    // Asking for the ceiling anyway is declined again; that card points to the settings too.
    await sendRequest(6, text('先按上限申请', 'At the ceiling for now'));
    const again = await browser.ev(
      `[...document.querySelectorAll('[data-decision-card]')].at(-1).innerText.replace(/\\s+/g, ' ').trim()`,
    );
    assert.ok(
      again.includes(
        text(
          '开发人日：申请 6；方案需要 7，超出上限 6',
          'Developer-days: requested 6; the plan needs 7, over the ceiling of 6',
        ),
      ),
      again,
    );
    assert.ok(again.includes(replan), again);
    assert.deepEqual(await cardButtons(-1), [viewSource, adjust, viewSource]);
    await focusShot('[data-decision-card]', 'decision-rejected-again', true);
    await clickReady(browser, adjust, '[data-decision-card] button');
    await waitFor(
      browser,
      `!!document.querySelector('#config-form') && !document.querySelector('#res-form')`,
    );
    // The saved plan is what the settings open with.
    assert.ok(
      await browser.ev(
        `document.querySelector('#config-form input[name="update"][value="realtime"]').checked`,
      ),
    );
    await shot('decision-to-settings');
  });

  // The same trap from a plan that fits: real-time sync without the human hand-off needs 6
  // developer-days, but a capped request would be declined again for the missing safeguard.
  await step(
    'a plan missing its hand-off is sent to its settings, not to a capped request',
    async () => {
      // The settings are open from the decision card.
      await browser.click('#config-form input[name="workItems"][value="fallback"]');
      assert.ok((await innerText('[data-checks]')).includes(text('开发 6 人日', '6 person-days')));
      await browser.submit('#config-form');
      await waitFor(browser, `!document.querySelector('#sheet')?.open`);
      await openRequests();
      await sendRequest(
        7,
        text('实时同步需要更多开发人日', 'Real-time sync needs more developer-days'),
      );
      const card = await browser.ev(
        `[...document.querySelectorAll('[data-decision-card]')].at(-1).innerText.replace(/\\s+/g, ' ').trim()`,
      );
      assert.ok(
        card.includes(
          text(
            '方案缺少：人工入口——先在设置里补上再申请',
            'The plan is missing Human hand-off: add it in the settings before requesting',
          ),
        ),
        card,
      );
      const buttons = await cardButtons(-1);
      assert.ok(buttons.includes(adjust) && !buttons.includes(capped), buttons.join(' | '));
      await focusShot('[data-decision-card]', 'decision-missing-hand-off', true);
      await clickReady(browser, adjust, '[data-decision-card] button');
      await waitFor(
        browser,
        `!!document.querySelector('#config-form') && !document.querySelector('#res-form')`,
      );
    },
  );

  await step('dropping the scope filter leaves real-time sync as the only reason', async () => {
    // The settings are open from the decision card; the hand-off goes back in.
    await browser.click('#config-form input[name="workItems"][value="fallback"]');
    await browser.click('#config-form input[name="workItems"][value="scope"]');
    assert.ok((await innerText('[data-checks]')).includes(text('开发 6 人日', '6 person-days')));
    await browser.submit('#config-form');
    await waitFor(browser, `!document.querySelector('#sheet')?.open`);
    const v2Line = text(
      '测试实际用：每日索引、不过滤知识范围 · 实时同步还没批到开发人日（已批准 3 人日）',
      "Tests actually use: Daily index, no scope filter · Real-time sync isn't funded yet (3 developer-days approved)",
    );
    await waitFor(
      browser,
      `document.querySelector('.product-bar [data-config-use]')?.innerText.trim() === ${JSON.stringify(v2Line)}`,
    );
    await focusShot('.product-bar', 'bar-v2-before-approval');
  });

  if (full) {
    await step(
      'a plan within the ceiling is approved and the card shows the covered term',
      async () => {
        await openRequests();
        // The plan now needs 6, so the learner asks for 6 after adjusting the settings.
        await browser.type('#res-form [name="dev_days"]', '6');
        await browser.type(
          '#res-form textarea[name="reason"]',
          text('按上限申请', 'At the ceiling'),
        );
        const before = await browser.ev(`document.querySelectorAll('[data-request-id]').length`);
        await browser.submit('#res-form');
        await waitFor(browser, `document.querySelectorAll('[data-request-id]').length > ${before}`);
        await clickReady(browser, text('核实申请', 'Check request'));
        await waitFor(
          browser,
          `[...document.querySelectorAll('[data-decision-card] li.ok')].some((li) => li.innerText.includes(${JSON.stringify(text('开发人日：3 → 6（方案需要 6 · 上限 6）', 'Developer-days: 3 → 6 (plan needs 6 · ceiling 6)'))}))`,
          20000,
        );
        // No card offers a capped request; the declined over-ceiling plan still names its way out.
        assert.equal(
          await browser.ev(
            `[...document.querySelectorAll('[data-decision-card] button')].filter((b) => b.textContent.trim() === ${JSON.stringify(capped)}).length`,
          ),
          0,
        );
        assert.deepEqual(await cardButtons(0), [viewSource, adjust]);
        await focusShot('[data-decision-card]', 'decision-approved', true);
      },
    );

    await step('the rule sentence opens in its source', async () => {
      await clickReady(browser, text('看原文', 'View source'));
      await waitFor(
        browser,
        `[...document.querySelectorAll('dialog[open]')].some((d) => d.innerText.includes(${JSON.stringify(ceiling)}))`,
      );
      await shot('rule-source');
      await browser.ev(
        `[...document.querySelectorAll('dialog[open]')].reverse().forEach((d) => d.close())`,
      );
      await waitFor(browser, `!document.querySelector('dialog[open]')`);
    });

    await step(
      'approval funds the work: the line disappears and tests use the source',
      async () => {
        await waitFor(browser, `!document.querySelector('.product-bar [data-config-use]')`);
        assert.ok(
          (await innerText('.product-bar .pb-state')).startsWith(text('配置 v3', 'Config v3')),
        );
        await shot('bar-funded');
        const answer = await runTest();
        assert.ok(answer.includes('400'), answer);
        await shot('bench-funded');
      },
    );
  }

  await step('the feedback states each recorded decision in one sentence', async () => {
    await deliver();
    await waitFor(browser, `document.querySelectorAll('.business-decisions p').length > 1`, 120000);
    const lines = await browser.ev(
      `[...document.querySelectorAll('.business-decisions p')].map((p) => p.textContent)`,
    );
    // Each request once with its latest decision, in the order they were made: 7, 6 and 7
    // declined, then 6 approved.
    const declined7 = text('开发人日：申请 7 · 未批准', 'Developer-days: requested 7 · declined');
    const decided = [
      declined7,
      text('开发人日：申请 6 · 未批准', 'Developer-days: requested 6 · declined'),
      declined7,
      ...(full
        ? [text('开发人日：申请 6 · 已批准 6', 'Developer-days: requested 6 · approved 6')]
        : []),
    ];
    assert.equal(
      lines[0],
      text('已记录的业务决定（规则核实）：', 'Recorded business decisions (rule checked): '),
    );
    assert.deepEqual(lines.slice(1), decided);
    await shot('feedback');
    await focusShot('.business-decisions', 'feedback-decisions');
  });
  assert.deepEqual(
    browser.logs.filter((item) => item.level === 'exception'),
    [],
  );
  writeFileSync(`${out}/${language}-${motion}-result.json`, JSON.stringify({ passed }, null, 2));
} catch (error) {
  await shot('failure');
  writeFileSync(
    `${out}/${language}-${motion}-failure.txt`,
    `${error?.stack ?? error}\n\n${await browser.ev('document.body.innerText')}`,
  );
  throw error;
} finally {
  await browser.close();
}
