/** 063-03 short results in the normal v4 entry: colleague reply, work review and
 * submission feedback, zh and en, desktop light and 390px dark, keyboard disclosure.
 * Runs against a real API/worker (BASE) and writes screenshots and results to OUT. */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { launch, delay } from '../../../tests/walkthrough/cdp.mjs';
import { waitFor, clickReady } from '../../../tests/regression/browser-support.mjs';

const base = process.env.BASE;
const out = process.env.OUT;
assert.ok(base && out, 'BASE and OUT are required');
mkdirSync(out, { recursive: true });
const results = [];
const OLD_META = [
  '回复包含完整条件与来源，请展开原文核对。',
  'Open the original reply to check its full conditions and sources.',
];
const host = `window.PracticeLive.v4Host(window.PracticeLive.engine.getAttempt(window.PracticeLive.state))`;
const unwrap = `(value) => { while (value && value.result && typeof value.result === 'object') value = value.result; return value; }`;

async function pressEnter(browser) {
  for (const type of ['keyDown', 'keyUp'])
    await browser.send('Input.dispatchKeyEvent', {
      type,
      key: 'Enter',
      code: 'Enter',
      windowsVirtualKeyCode: 13,
      nativeVirtualKeyCode: 13,
      ...(type === 'keyDown' ? { text: '\r', unmodifiedText: '\r' } : {}),
    });
  await delay(200);
}
async function viewport(browser, width, height, dark) {
  await browser.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: width < 500 ? 2 : 1.5,
    mobile: false,
  });
  await browser.send('Emulation.setEmulatedMedia', {
    features: [
      { name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' },
      { name: 'prefers-reduced-motion', value: 'reduce' },
    ],
  });
  await delay(300);
}
const noOverflow = (browser) =>
  browser.ev('document.documentElement.scrollWidth <= document.documentElement.clientWidth');

async function ask(browser, question) {
  const count = await browser.ev(`document.querySelectorAll('.rc-roles__turn').length`);
  await waitFor(browser, `document.querySelector('.composer [type="submit"]')?.disabled === false`);
  await browser.type('#chat-input', question);
  await browser.submit('.composer');
  await waitFor(browser, `document.querySelectorAll('.rc-roles__reply').length > ${count}`, 60000);
  await delay(300);
  return browser.ev(`(() => {
    const turn = [...document.querySelectorAll('.rc-roles__turn')].at(-1);
    const lead = turn.querySelector('.short-result__lead');
    return {
      id: turn.dataset.turnId,
      status: turn.querySelector('.rc-roles__reply-status')?.innerText ?? '',
      lead: lead?.innerText ?? '',
      derived: lead?.hasAttribute('data-derived') ?? true,
      source: turn.querySelector('.short-result > .rc-roles__materials')?.innerText ?? '',
      open: turn.querySelector('details.rc-roles__details').open,
      summary: turn.querySelector('details.rc-roles__details > summary').innerText,
      full: turn.querySelector('.rc-roles__reply').textContent,
    };
  })()`);
}
async function storedReply(browser, question) {
  return browser.ev(`(async () => {
    const data = (${unwrap})(await ${host}.query('timeline'));
    return data.objects.filter((row) => row.ref.kind === 'role_reply' && row.content.question === ${JSON.stringify(question)}).at(-1).content.text;
  })()`);
}

for (const language of ['zh', 'en']) {
  const t = (zh, en) => (language === 'en' ? en : zh);
  const shot = (name) => browser.shot(`${out}/${language}-${name}.jpg`);
  const browser = await launch({ width: 1440, height: 1000, reduced: true });
  try {
    await browser.send('Emulation.setFocusEmulationEnabled', { enabled: true });
    await browser.goto(base);
    await browser.ev(
      `localStorage.clear(); localStorage.setItem('rolecraft.locale', '${language}')`,
    );
    await browser.goto(base);
    await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
    await browser.click('[data-action="open-career"]');
    await browser.click('.case-hero [data-action="take-case"]');
    await waitFor(browser, `!!document.querySelector('.card-open')`);
    await browser.click('.card-open');
    await waitFor(browser, `!!document.querySelector('[data-action="chat"][data-role="manager"]')`);
    await browser.click('[data-action="chat"][data-role="manager"]');

    // 1. A fact question: one quoted, rule-checked fact with its source first.
    const factQuestion = t('当前试点容量是多少？', 'What is the current pilot capacity?');
    const fact = await ask(browser, factQuestion);
    assert.ok(fact.lead && !OLD_META.includes(fact.lead), 'first screen shows the reply itself');
    assert.equal(fact.derived, false, 'first screen quotes the reply, not a tool sentence');
    assert.ok(fact.source, 'the quoted fact names its source on the first screen');
    assert.ok(fact.status.includes(t('等待模型接入', 'waiting for model connection')));
    assert.equal(fact.open, false);
    assert.ok(fact.summary.startsWith(t('展开原文', 'Show full reply')));
    assert.equal(fact.full, await storedReply(browser, factQuestion), 'full reply unchanged');
    assert.ok(fact.full.includes(fact.lead.split('\n')[0]), 'first screen is verbatim');
    await shot('colleague-desktop');
    results.push({ language, check: 'colleague fact first screen', ...fact, full: undefined });

    // 2. N1: a committed approval is stated first. Setup uses the page's own v4 host
    // client (same journal as the sheets); the question and reading are normal UI.
    const setup = await browser.ev(`(async () => {
      const host = ${host};
      const unwrap = ${unwrap};
      const config = unwrap(await host.query('timeline')).workspace.config;
      const base = { session_id: config.session_id, kind: 'config', object_id: config.id, version: config.version, config_version: config.config_version };
      const applied = await host.command('configuration.apply', { base, settings: { participants: 50, work_items: ['scope_filter', 'human_fallback'], fallback: 'human' } });
      const asked = await host.command('actions', { tool: 'request_business', terms: { capacity: 50 }, reason: ${JSON.stringify(t('试点需要覆盖 50 人。', 'The pilot needs 50 users.'))} });
      const request = unwrap(asked.result).request;
      const decided = await host.command('approvals.resolve', { request, expected_request_revision: 1 });
      return [applied.status, asked.status, decided.status, unwrap(decided.result).decision?.status];
    })()`);
    assert.deepEqual(setup, ['confirmed', 'confirmed', 'confirmed', 'approved'], String(setup));
    const approvedQuestion = t('目前已批准的容量是多少？', 'What capacity has been approved?');
    const approved = await ask(browser, approvedQuestion);
    assert.ok(approved.lead.includes('50'), approved.lead);
    assert.ok(approved.lead.includes(t('已批准', 'approved')), approved.lead);
    assert.ok(approved.source.includes(t('业务决定', 'Business decision')), approved.source);
    await browser.ev(
      `[...document.querySelectorAll('.rc-roles__turn')].at(-1).scrollIntoView({block:'center'})`,
    );
    await shot('colleague-approved-desktop');
    results.push({
      language,
      check: 'approved decision first screen',
      ...approved,
      full: undefined,
    });

    // 3. Review with no purpose: one question instead of 14 identical rows.
    await browser.type('#new-title', t('探索笔记', 'Exploration note'));
    await browser.type(
      '#new-body',
      t(
        '先看容量与政策更新的影响，再决定试点范围。',
        'Check capacity and policy impact first, then decide the scope.',
      ),
    );
    await browser.clickText(t('保存为作品', 'Save as work'));
    await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
    await browser.click('.ol-row[data-type="work"]');
    await waitFor(browser, `!!document.querySelector('#editor-body')`);
    await browser.click('[data-action="request-review"]');
    await waitFor(
      browser,
      `!!document.querySelector('.native-feedback section[aria-label] details[open] input[type="checkbox"]')`,
      20000,
    );
    await browser.click(
      '.native-feedback section[aria-label] details[open] input[type="checkbox"]',
    );
    await clickReady(browser, t('评审选中的版本', 'Review selected versions'));
    await waitFor(browser, `!!document.querySelector('[data-short-result="review"]')`, 60000);
    await delay(400);
    const review = await browser.ev(`(() => {
      const block = document.querySelector('[data-short-result="review"]');
      const more = block.querySelector(':scope > details[data-short-result-more]');
      return {
        statuses: [...block.querySelectorAll(':scope > .short-result__status li')].map((n) => n.innerText),
        lead: block.querySelector('.short-result__lead')?.innerText ?? '',
        prompts: document.querySelectorAll('[data-purpose-prompt]').length,
        choices: [...block.querySelectorAll('[data-purpose-prompt] label')].map((n) => n.innerText.trim()),
        summary: more.querySelector('summary').innerText,
        open: more.open,
        criteria: more.querySelectorAll('details[data-response-id*=":rule_items:"]').length,
        visibleRows: (document.querySelector('.native-feedback').innerText.match(${JSON.stringify(t('本项责任待确认', 'this responsibility is undetermined'))}, 'g') || []).length,
        waiting: block.innerText.includes(${JSON.stringify(t('等待模型接入', 'Awaiting model connection'))}),
      };
    })()`);
    assert.equal(review.prompts, 1, 'one purpose question');
    assert.equal(review.choices.length, 5);
    assert.ok(review.lead.includes('14'), review.lead);
    assert.equal(review.summary, t('展开 14 项', 'Show all 14 items'));
    assert.equal(review.open, false);
    assert.equal(review.criteria, 14, 'all criteria remain reachable');
    assert.equal(review.visibleRows, 0, 'no repeated rows on the first screen');
    assert.ok(review.waiting, 'model state stays visible');
    assert.ok(!review.statuses.some((s) => /\d+\s*\/\s*\d+/.test(s)), 'no 0/0 ratios');
    await browser.ev(
      `document.querySelector('[data-short-result="review"]').scrollIntoView({block:'start'})`,
    );
    await shot('review-desktop');
    // Keyboard: the disclosure opens and closes by Enter and keeps focus.
    await browser.ev(
      `document.querySelector('[data-short-result="review"] > details[data-short-result-more] > summary').focus()`,
    );
    await pressEnter(browser);
    assert.equal(
      await browser.ev(
        `document.querySelector('[data-short-result="review"] > details[data-short-result-more]').open`,
      ),
      true,
    );
    assert.equal(await browser.ev('document.activeElement.tagName'), 'SUMMARY');
    await shot('review-expanded-desktop');
    await pressEnter(browser);
    assert.equal(
      await browser.ev(
        `document.querySelector('[data-short-result="review"] > details[data-short-result-more]').open`,
      ),
      false,
    );
    // Answer the question by keyboard-reachable controls; a new review follows.
    await browser.click('[data-purpose-prompt] input[value="test_plan"]');
    await clickReady(
      browser,
      t('按这个用途重新评审', 'Review again for this purpose'),
      '[data-purpose-prompt] button',
    );
    await waitFor(
      browser,
      `document.querySelectorAll('[data-short-result="review"]').length === 2`,
      60000,
    );
    await delay(400);
    const after = await browser.ev(`(() => {
      const [old, fresh] = document.querySelectorAll('[data-short-result="review"]');
      return {
        oldNote: old.querySelector('.short-result__note')?.innerText ?? '',
        prompts: document.querySelectorAll('[data-purpose-prompt]').length,
        statuses: [...fresh.querySelectorAll(':scope > .short-result__status li')].map((n) => n.innerText),
        summary: fresh.querySelector(':scope > details > summary').innerText,
      };
    })()`);
    assert.equal(after.prompts, 0);
    assert.ok(after.oldNote.includes(t('测试计划', 'Test plan')), after.oldNote);
    assert.ok(
      after.statuses.some((s) => s.startsWith(t('本次不适用', 'Not applicable this time'))),
    );
    await browser.ev(
      `document.querySelectorAll('[data-short-result="review"]')[1].scrollIntoView({block:'start'})`,
    );
    await shot('review-after-purpose-desktop');
    results.push({ language, check: 'review purpose-first', review, after });

    // 4. 390px, dark: colleague and review in the rail drawer, no horizontal scroll.
    await viewport(browser, 390, 844, true);
    await browser.click('[data-action="open-rail"]');
    await waitFor(browser, `!!document.querySelector('.rail-tabs [data-tab="feedback"]')`);
    await browser.click('.rail-tabs [data-tab="feedback"]');
    await waitFor(browser, `!!document.querySelector('[data-short-result="review"]')`, 20000);
    await browser.ev(
      `document.querySelector('[data-short-result="review"]').scrollIntoView({block:'start'})`,
    );
    assert.equal(await noOverflow(browser), true);
    await shot('review-390-dark');
    await browser
      .click('.rail-tabs [data-tab="team"]')
      .catch(() => browser.click('[data-action="rail"][data-rail="team"]'));
    await delay(300);
    results.push({ language, check: '390px dark review', status: 'passed' });

    // 5. Submission feedback: short result first, 14 items folded.
    await viewport(browser, 1440, 1000, false);
    await browser.goto(`${base}#/work`);
    await waitFor(browser, `!!document.querySelector('.ws-toolbar [data-action="submit"]')`);
    await browser.click('.ws-toolbar [data-action="submit"]');
    await waitFor(
      browser,
      `!!document.querySelector('#sheet .native-feedback input[type="checkbox"]')`,
    );
    await browser.click('#sheet .native-feedback input[type="checkbox"]');
    await browser.select('#sheet .native-feedback select', 'defer_with_conditions');
    await clickReady(browser, t('提交选中的版本', 'Submit selected versions'), '#sheet button');
    await waitFor(browser, `window.PracticeLive.store.active().world.status === 'submitted'`);
    await browser.ev(`document.querySelector('#sheet')?.close()`);
    await browser.goto(`${base}#/review`);
    await waitFor(browser, `!!document.querySelector('[data-short-result="feedback"]')`, 60000);
    await delay(500);
    const feedback = await browser.ev(`(() => {
      const block = document.querySelector('[data-short-result="feedback"]');
      return {
        heading: block.closest('article').querySelector(':scope > h2').innerText,
        statuses: [...block.querySelectorAll(':scope > .short-result__status li')].map((n) => n.innerText),
        summary: block.querySelector(':scope > details > summary').innerText,
        open: block.querySelector(':scope > details').open,
        waiting: block.innerText.includes(${JSON.stringify(t('等待模型接入', 'Awaiting model connection'))}),
        coverage: document.querySelector('[data-feedback-coverage]').textContent,
      };
    })()`);
    assert.equal(feedback.heading, t('最近提交的反馈', 'Latest submission feedback'));
    assert.equal(feedback.summary, t('展开 14 项', 'Show all 14 items'));
    assert.equal(feedback.open, false);
    assert.ok(feedback.waiting);
    assert.ok(feedback.statuses.some((s) => s.startsWith(t('待核验', 'Pending verification'))));
    await browser.ev(
      `document.querySelector('[data-short-result="feedback"]').closest('article').scrollIntoView({block:'start'}); document.scrollingElement.scrollBy(0, -96)`,
    );
    await shot('feedback-desktop');
    await viewport(browser, 390, 844, true);
    await browser.ev(
      `document.querySelector('[data-short-result="feedback"]').closest('article').scrollIntoView({block:'start'}); document.scrollingElement.scrollBy(0, -96)`,
    );
    assert.equal(await noOverflow(browser), true);
    await shot('feedback-390-dark');
    // Colleague history at 390px, dark, still leads with the quoted fact.
    await browser.goto(`${base}#/work`);
    await waitFor(browser, `!!document.querySelector('[data-action="open-rail"]')`);
    await browser.click('[data-action="open-rail"]');
    await delay(300);
    if (await browser.ev(`!!document.querySelector('.person[data-role="manager"]')`))
      await browser.click('.person[data-role="manager"]');
    await waitFor(
      browser,
      `!!document.querySelector('.rc-roles__turn .short-result__lead')`,
      20000,
    );
    assert.equal(await noOverflow(browser), true);
    await shot('colleague-390-dark');
    results.push({ language, check: 'submission feedback and 390px dark colleague', feedback });
  } catch (error) {
    await shot('failure').catch(() => {});
    writeFileSync(
      `${out}/results.json`,
      JSON.stringify([...results, { language, error: String(error) }], null, 2),
    );
    throw error;
  } finally {
    await browser.close();
  }
}
writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 2));
console.log(`short results: ${results.length} checks passed`);
