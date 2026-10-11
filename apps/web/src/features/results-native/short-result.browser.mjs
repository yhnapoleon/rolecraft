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
  // Turns asking exactly this question; the newest one is the reply under test.
  const same = `[...document.querySelectorAll('.rc-roles__turn')].filter((n) => n.querySelector('.rc-roles__question')?.textContent === ${JSON.stringify(question)})`;
  // Earlier commands (e.g. the approval) finish refreshing before the next question.
  await waitFor(browser, `${host}.snapshot().busy === false`, 30000);
  await waitFor(browser, `document.querySelector('.composer [type="submit"]')?.disabled === false`);
  const count = await browser.ev(`${same}.length`);
  await browser.type('#chat-input', question);
  await browser.submit('.composer');
  // On a loaded machine the shared SQLite store can stall a read; the composer then keeps
  // the unsent text, as it would for a learner, who sends it again.
  let resends = 0;
  for (let attempt = 0; ; attempt++) {
    try {
      await waitFor(browser, `${same}.length > ${count}`, 30000);
      break;
    } catch (error) {
      const unsent = await browser.ev(
        `document.querySelector('#chat-input')?.value === ${JSON.stringify(question)}`,
      );
      if (attempt > 1 || !unsent) throw error;
      await waitFor(browser, `${host}.snapshot().busy === false`, 60000);
      await browser.submit('.composer');
      resends++;
    }
  }
  await waitFor(browser, `!!${same}.at(-1)?.querySelector('.rc-roles__reply')`, 60000);
  await delay(300);
  await waitFor(browser, `!!${same}.at(-1)?.querySelector('.rc-roles__reply')`, 15000);
  const shown = await browser.ev(`(() => {
    const turn = ${same}.at(-1);
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
  // Resends are recorded so a run that needed them can be looked at again.
  return { ...shown, resends };
}
/** A new practice from the normal entry, in a clean browser store. */
async function enterFresh(browser, language) {
  await browser.goto(base);
  await browser.ev(`localStorage.clear(); localStorage.setItem('rolecraft.locale', '${language}')`);
  await browser.goto(base);
  await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
  await browser.click('[data-action="open-career"]');
  await browser.click('.case-hero [data-action="take-case"]');
  await waitFor(browser, `!!document.querySelector('.card-open')`);
  await browser.click('.card-open');
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
    await enterFresh(browser, language);
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
    // A recalled earlier question never leads (the learner's own words are not an answer).
    const notEcho = (reply) =>
      !reply.lead.startsWith(t('此前你问', 'Earlier you asked')) &&
      !reply.source.includes(t('对话记录', 'Conversation'));
    // P1-2: a follow-up shares words with the first question; it still leads with a source.
    const judgementQuestion = t(
      '我们应该现在就把试点开放给所有人吗？',
      'Should we open the pilot to everyone now?',
    );
    const judgement = await ask(browser, judgementQuestion);
    assert.ok(notEcho(judgement), JSON.stringify(judgement));
    await shot('colleague-follow-up-desktop');
    results.push({ language, check: 'follow-up never echoes', ...judgement, full: undefined });
    // P1-A: a keyword the material itself contains leads with that material, and a later
    // question never changes an earlier reply's first screen.
    const keyword = t('试点期限', 'pilot deadline');
    const keywordReply = await ask(browser, keyword);
    assert.ok(keywordReply.lead.toLowerCase().includes(keyword), JSON.stringify(keywordReply));
    assert.equal(keywordReply.derived, false);
    const earlier = await browser.ev(
      `document.querySelector('[data-turn-id="${fact.id}"] .short-result__lead')?.innerText ?? ''`,
    );
    assert.equal(earlier, fact.lead, 'an earlier first screen is unchanged by later questions');
    await shot('colleague-keyword-desktop');
    results.push({
      language,
      check: 'keyword question',
      ...keywordReply,
      earlier,
      full: undefined,
    });

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
    // Reopen the conversation from the normal route so the page reads the new state.
    const route = await browser.ev('location.hash');
    await browser.goto(base + route);
    // Open the manager from the team list, as after any reload, so the composer is bound.
    const team = `document.querySelector('[data-action="rail"][data-rail="team"]')`;
    await waitFor(
      browser,
      `!!${team} || !!document.querySelector('.person[data-role="manager"]')`,
      30000,
    );
    if (await browser.ev(`!!${team}`))
      await browser.click('[data-action="rail"][data-rail="team"]');
    await waitFor(browser, `!!document.querySelector('.person[data-role="manager"]')`, 30000);
    await browser.click('.person[data-role="manager"]');
    await waitFor(browser, `document.querySelectorAll('.rc-roles__reply').length >= 2`, 30000);
    // P1-1: the natural question and the explicit one lead with the committed decision;
    // the initial brief figure is never the first-screen answer.
    const afterApproval = [
      ['current-capacity', factQuestion],
      ['approved', t('目前已批准的容量是多少？', 'What capacity has been approved?')],
    ];
    for (const [name, question] of afterApproval) {
      const reply = await ask(browser, question);
      assert.ok(reply.lead.includes('50'), `${name}: ${reply.lead}`);
      assert.ok(reply.lead.includes(t('已批准', 'approved')), `${name}: ${reply.lead}`);
      assert.ok(!reply.lead.includes('30'), `${name}: stale brief figure on the first screen`);
      assert.ok(reply.source.includes(t('业务决定', 'Business decision')), reply.source);
      assert.ok(notEcho(reply), JSON.stringify(reply));
      await browser.ev(
        `document.querySelector('[data-turn-id="${reply.id}"]')?.scrollIntoView({block:'center'})`,
      );
      await shot(`colleague-after-approval-${name}-desktop`);
      results.push({ language, check: `approved decision: ${name}`, ...reply, full: undefined });
    }
    // A question sharing no term with the decision is not led by it, yet never by the
    // superseded initial figure either; an unrelated question is not led by it at all.
    const cover = await ask(
      browser,
      t('试点能覆盖多少人？', 'How many people can the pilot cover?'),
    );
    assert.ok(!cover.lead.includes('30'), `cover: ${cover.lead}`);
    assert.ok(notEcho(cover), JSON.stringify(cover));
    await shot('colleague-after-approval-cover-desktop');
    const policy = await ask(
      browser,
      t('政策更新后需要重新测试吗？', 'Do we need to retest after the policy update?'),
    );
    assert.ok(!policy.source.includes(t('业务决定', 'Business decision')), policy.source);
    await shot('colleague-after-approval-policy-desktop');
    // P1-B: the request moved the demo from day 5 to day 4; the newer notice leads.
    const demo = await ask(
      browser,
      t('内部演示安排在第几天？', 'Which day is the internal demonstration?'),
    );
    assert.ok(demo.lead.includes(t('第4天', 'day 4')), `demo: ${demo.lead}`);
    assert.ok(!demo.lead.includes(t('第5天', 'day 5')), `demo: ${demo.lead}`);
    await browser.ev(
      `document.querySelector('[data-turn-id="${demo.id}"]')?.scrollIntoView({block:'center'})`,
    );
    await shot('colleague-after-approval-demo-day-desktop');
    // P2-6: a cited Markdown table is never the first screen.
    const scope = await ask(
      browser,
      t('试点范围应该怎么定？', 'How should we set the pilot scope?'),
    );
    assert.ok(!scope.lead.trimStart().startsWith('|') && !scope.lead.includes('---'), scope.lead);
    await shot('colleague-after-approval-scope-desktop');
    for (const [name, reply] of [
      ['cover', cover],
      ['policy', policy],
      ['demo day', demo],
      ['scope', scope],
    ])
      results.push({ language, check: `after approval: ${name}`, ...reply, full: undefined });

    // 3. Review. P2-2: the purpose the work declares is used without asking again.
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
    const form = '.native-feedback section[aria-label] > details';
    const box = `${form} input[type="checkbox"]`;
    const purposeInput = `${form} input[list]`;
    await waitFor(
      browser,
      `!!document.querySelector('${form}[open] input[type="checkbox"]')`,
      20000,
    );
    await browser.click(box);
    assert.equal(
      await browser.ev(`document.querySelector('${purposeInput}').value`),
      t('探索笔记', 'Exploration note'),
      'the review form starts from the declared purpose',
    );
    await clickReady(browser, t('评审选中的版本', 'Review selected versions'));
    await waitFor(browser, `!!document.querySelector('[data-short-result="review"]')`, 60000);
    await delay(400);
    const cards = `[...document.querySelectorAll('[data-short-result="review"]')]`;
    const declaredCard = await browser.ev(`(() => {
      const card = ${cards}[0].closest('article');
      return { title: card.querySelector(':scope > h2 + p')?.innerText ?? '', prompts: card.querySelectorAll('[data-purpose-prompt]').length };
    })()`);
    assert.equal(declaredCard.title, t('按「探索笔记」评审', 'Reviewed as “Exploration note”'));
    assert.equal(declaredCard.prompts, 0, 'no question when the purpose is declared');
    await browser.ev(`${cards}[0].closest('article').scrollIntoView({block:'start'})`);
    await shot('review-declared-purpose-desktop');

    // D6: the learner clears the purpose; one question replaces 14 identical rows,
    // starting from the declared purpose and still editable.
    await browser.ev(`document.querySelector('${form}').open = true`);
    await waitFor(browser, `document.querySelector('${box}')?.checked === true`);
    await browser.type(purposeInput, '');
    await clickReady(browser, t('评审选中的版本', 'Review selected versions'));
    await waitFor(browser, `${cards}.length === 2`, 60000);
    // The feedback panel settles (no request in flight) before the question is answered.
    await waitFor(browser, `${host}.snapshot().busy === false`, 30000);
    await waitFor(
      browser,
      `${cards}[1].querySelector('[data-purpose-prompt] button')?.disabled === false`,
      30000,
    );
    await delay(400);
    const review = await browser.ev(`(() => {
      const block = ${cards}[1];
      const more = block.querySelector(':scope > details[data-short-result-more]');
      return {
        statuses: [...block.querySelectorAll(':scope > .short-result__status li')].map((n) => n.innerText),
        lead: block.querySelector('.short-result__lead')?.innerText ?? '',
        prompts: document.querySelectorAll('[data-purpose-prompt]').length,
        choices: [...block.querySelectorAll('[data-purpose-prompt] label')].map((n) => n.innerText.trim()),
        preselected: block.querySelector('[data-purpose-prompt] input:checked')?.value ?? null,
        submitEnabled: !block.querySelector('[data-purpose-prompt] button')?.disabled,
        summary: more.querySelector('summary').innerText,
        open: more.open,
        criteria: more.querySelectorAll('details[data-response-id*=":rule_items:"]').length,
        visibleRows: (document.querySelector('.native-feedback').innerText.match(${JSON.stringify(t('本项责任待确认', 'this responsibility is undetermined'))}, 'g') || []).length,
        waiting: block.innerText.includes(${JSON.stringify(t('等待模型接入', 'Awaiting model connection'))}),
      };
    })()`);
    assert.equal(review.prompts, 1, 'one purpose question');
    assert.equal(review.choices.length, 5);
    assert.equal(review.preselected, 'exploration', 'declared purpose is preselected');
    assert.equal(review.submitEnabled, true);
    assert.ok(review.lead.includes('14'), review.lead);
    assert.equal(review.summary, t('展开 14 项', 'Show all 14 items'));
    assert.equal(review.open, false);
    assert.equal(review.criteria, 14, 'all criteria remain reachable');
    assert.equal(review.visibleRows, 0, 'no repeated rows on the first screen');
    assert.ok(review.waiting, 'model state stays visible');
    assert.ok(!review.statuses.some((s) => /\d+\s*\/\s*\d+/.test(s)), 'no 0/0 ratios');
    await browser.ev(`${cards}[1].closest('article').scrollIntoView({block:'start'})`);
    await shot('review-desktop');
    // Keyboard: the disclosure opens and closes by Enter and keeps focus.
    const more = `${cards}[1].querySelector(':scope > details[data-short-result-more]')`;
    await browser.ev(`${more}.querySelector('summary').focus()`);
    await pressEnter(browser);
    assert.equal(await browser.ev(`${more}.open`), true);
    assert.equal(await browser.ev('document.activeElement.tagName'), 'SUMMARY');
    await shot('review-expanded-desktop');
    await pressEnter(browser);
    assert.equal(await browser.ev(`${more}.open`), false);
    // Change the preselected answer; a new review follows (P2-3 labels both cards).
    await waitFor(browser, `${host}.snapshot().busy === false`, 30000);
    await browser.click('[data-purpose-prompt] input[value="test_plan"]');
    await clickReady(
      browser,
      t('按这个用途重新评审', 'Review again for this purpose'),
      '[data-purpose-prompt] button',
    );
    await waitFor(browser, `${cards}.length === 3`, 90000).catch(async (error) => {
      const alert = await browser.ev(
        `[...document.querySelectorAll('.native-feedback [role="alert"]')].map((n) => n.textContent).join(' | ')`,
      );
      throw Error(`${error.message}; alerts: ${alert}`);
    });
    await delay(400);
    const after = await browser.ev(`(() => {
      const [, old, fresh] = ${cards};
      return {
        oldLead: old.querySelector('.short-result__lead')?.innerText ?? '',
        oldNotes: old.querySelectorAll('.short-result__note').length,
        prompts: document.querySelectorAll('[data-purpose-prompt]').length,
        freshTitle: fresh.closest('article').querySelector(':scope > h2 + p')?.innerText ?? '',
        statuses: [...fresh.querySelectorAll(':scope > .short-result__status li')].map((n) => n.innerText),
        summary: fresh.querySelector(':scope > details > summary').innerText,
        cards: ${cards}.length,
      };
    })()`);
    assert.equal(after.prompts, 0);
    assert.equal(
      after.oldLead,
      t(
        '已按「测试计划」重新评审，新的反馈另列。',
        'Reviewed again as “Test plan”; the new feedback is listed separately.',
      ),
    );
    assert.equal(after.oldNotes, 0, 'the old question sentence is replaced, not added to');
    assert.equal(after.freshTitle, t('按「测试计划」评审', 'Reviewed as “Test plan”'));
    assert.ok(
      after.statuses.some((s) => s.startsWith(t('本次不适用', 'Not applicable this time'))),
    );
    assert.equal(after.cards, 3, 'history is kept');
    await browser.ev(`${cards}[1].closest('article').scrollIntoView({block:'start'})`);
    await shot('review-after-purpose-desktop');
    results.push({ language, check: 'review purpose-first', declaredCard, review, after });

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
    results.push({ language, check: '390px dark colleague', status: 'passed' });

    // 5. Submission feedback, in a fresh practice so the feedback job is not queued behind
    // this long session: short result first, 14 items folded.
    await viewport(browser, 1440, 1000, false);
    await enterFresh(browser, language);
    await waitFor(browser, `!!document.querySelector('#new-title')`);
    await browser.type('#new-title', t('试点决定', 'Pilot decision'));
    await browser.type(
      '#new-body',
      t('负责人和范围核实前暂缓，保留人工兜底。', 'Defer until the owner and scope are verified.'),
    );
    await browser.clickText(t('保存为作品', 'Save as work'));
    await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
    await browser.click('[data-action="to-board"]');
    await waitFor(browser, `!!document.querySelector('.ws-toolbar [data-action="submit"]')`);
    await browser.click('.ws-toolbar [data-action="submit"]');
    await waitFor(
      browser,
      `!!document.querySelector('#sheet .native-feedback input[type="checkbox"]')`,
    );
    await browser.click('#sheet .native-feedback input[type="checkbox"]');
    await browser.select('#sheet .native-feedback select', 'defer_with_conditions');
    await clickReady(browser, t('提交选中的版本', 'Submit selected versions'), '#sheet button');
    await waitFor(
      browser,
      `window.PracticeLive.store.active().world.status === 'submitted'`,
      60000,
    );
    await browser.ev(`document.querySelector('#sheet')?.close()`);
    await browser.goto(`${base}#/review`);
    // Feedback is a worker job; on a loaded machine it can take minutes, and a job whose
    // lease lapsed waits for an explicit retry. Use the page's own controls, as a learner
    // would: "Request feedback again" when offered, otherwise "Refresh feedback".
    let retried = 0;
    for (
      let waited = 0;
      !(await browser.ev(`!!document.querySelector('[data-short-result="feedback"]')`));
      waited += 10
    ) {
      assert.ok(waited < 600, 'submission feedback did not appear');
      await delay(10000);
      const again = t('重新请求反馈', 'Request feedback again');
      const offered = await browser.ev(
        `[...document.querySelectorAll('button')].some((b) => b.textContent.trim() === ${JSON.stringify(again)} && b.offsetParent !== null && !b.disabled)`,
      );
      if (offered && retried < 2) {
        retried++;
        await browser.clickText(again, 'button');
      } else
        await browser
          .clickText(t('查看最新反馈', 'Refresh feedback'), 'button')
          .catch(() => undefined);
    }
    results.push({ language, check: 'submission feedback retries used', retried });
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
    results.push({ language, check: 'submission feedback', feedback });
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
const resends = results.reduce((sum, r) => sum + (r.resends ?? 0), 0);
console.log(`short results: ${results.length} checks passed; chat resends: ${resends}`);
