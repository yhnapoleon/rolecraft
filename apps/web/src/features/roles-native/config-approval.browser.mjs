/**
 * Normal v4 entry over a real API and worker: saved vs used configuration, the real-time
 * strategy's work item, the request form's terms and the approval decision card.
 *
 * Usage: CHROME_BIN=… node config-approval.browser.mjs <base URL> <evidence dir> <zh|en> [default]
 * The fourth argument runs with default motion and covers settings and requests only
 * (no document cards). Without it the whole path runs with reduced motion.
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
const closeSheet = async () => {
  await browser.ev(
    `document.querySelector('#sheet')?.open && document.querySelector('#sheet').close()`,
  );
  await waitFor(browser, `!document.querySelector('#sheet')?.open`);
};
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

  await step('the rejection card cites the ceiling and offers the capped request', async () => {
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
    await shot('decision-rejected');
    await viewport(390, 844, true);
    await delay(300);
    await focusShot('[data-decision-card]', 'decision-rejected-390');
    await viewport(1440, 1100);
    const rows = await browser.ev(`document.querySelectorAll('[data-request-id]').length`);
    await clickReady(browser, text('按上限改申请', 'Re-apply at the ceiling'));
    assert.equal(
      await browser.ev(`document.querySelector('#res-form [name="dev_days"]').value`),
      '6',
    );
    assert.equal(await browser.ev(`document.querySelectorAll('[data-request-id]').length`), rows);
    await closeSheet();
  });

  if (full) {
    await step(
      'a plan within the ceiling is approved and the card shows the covered term',
      async () => {
        await openSettings();
        await browser.click('#config-form input[name="workItems"][value="scope"]');
        assert.ok(
          (await innerText('[data-checks]')).includes(text('开发 6 人日', '6 person-days')),
        );
        await browser.submit('#config-form');
        await waitFor(browser, `!document.querySelector('#sheet')?.open`);
        await openRequests();
        assert.equal(
          await browser.ev(`document.querySelector('#res-form [name="dev_days"]').value`),
          '6',
        );
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
          (await innerText('.product-bar .pb-state')).startsWith(text('配置 v2', 'Config v2')),
        );
        await shot('bar-funded');
        const answer = await runTest();
        assert.ok(answer.includes('400'), answer);
        await shot('bench-funded');
      },
    );
  }
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
