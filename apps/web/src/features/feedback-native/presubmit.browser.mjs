/** Pre-submission preview in the normal v4 entry, zh and en, reduced motion. The card sits right
 * above "Submit selected versions", counts rule-met items without any percentage, phrases one fact
 * per item, follows the decision, opens the tool that fixes an unmet item, names configuration
 * versions after a retest on an earlier one (164 F17), remembers the choice when the panel is
 * reopened, and agrees with the formal feedback once submitted. Desktop, 390px and dark shots.
 * BASE is the web origin, OUT the screenshot and result directory; CHROME_BIN as elsewhere. */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { clickReady, waitFor } from '../../../tests/regression/browser-support.mjs';
import { delay, launch } from '../../../tests/walkthrough/cdp.mjs';

const base = process.env.BASE;
const out = process.env.OUT;
assert.ok(base && out, 'BASE and OUT are required');
mkdirSync(out, { recursive: true });
const languages = (process.env.LANGS ?? 'zh en').split(' ');
const results = [];
const card = `document.querySelector('#sheet [data-presubmit]')`;

const read = (browser) =>
  browser.ev(`(() => {
    const c = ${card};
    if (!c) return null;
    const meter = c.querySelector('[role="meter"]');
    return {
      hidden: c.hidden,
      busy: c.getAttribute('aria-busy'),
      text: c.innerText,
      count: c.querySelector('.presubmit__count')?.textContent ?? null,
      meter: meter ? meter.getAttribute('aria-valuetext') : null,
      lines: [...c.querySelectorAll('.presubmit__items li')].map((li) => ({
        criterion: li.dataset.criterion,
        met: li.dataset.met === 'true',
        text: li.querySelector('.presubmit__text').textContent,
        action: li.querySelector('button')?.textContent ?? null,
      })),
      waiting: c.querySelector('.presubmit__waiting')?.textContent ?? null,
      aboveSubmit: c.nextElementSibling?.textContent.trim(),
    };
  })()`);

async function settled(browser, predicate) {
  await waitFor(
    browser,
    `(() => { const c = ${card}; return !!c && c.getAttribute('aria-busy') === 'false' && (${predicate}); })()`,
    30000,
  );
  return read(browser);
}

async function openDelivery(browser) {
  await browser.click('[data-action="to-board"]').catch(() => undefined);
  await waitFor(browser, `!!document.querySelector('.ws-toolbar [data-action="submit"]')`);
  await browser.click('.ws-toolbar [data-action="submit"]');
  await waitFor(
    browser,
    `!!${card} && !!document.querySelector('#sheet .native-feedback input[type="checkbox"]')`,
  );
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

/** Recorded test runs of this practice, from its own API (the bench groups repeated questions). */
const recordedTests = `(async () => {
  const s = window.PracticeLive.store.active();
  const r = await fetch('/api/sessions/' + s.id + '/tests', { headers: { Authorization: 'Bearer ' + s.token } });
  return (await r.json()).result.result.tests.length;
})()`;

async function runTest(browser, t) {
  await browser.click('[data-action="to-board"]').catch(() => undefined);
  await waitFor(browser, `!!document.querySelector('.product-bar [data-action="open-bench"]')`);
  const before = await browser.ev(recordedTests);
  await browser.click('.product-bar [data-action="open-bench"]');
  await waitFor(browser, `!!document.querySelector('#lab-q')`);
  await browser.type(
    '#lab-q',
    t('住宿报销上限是多少？', 'What is the hotel reimbursement limit per night?'),
  );
  await browser.submit('[data-form="run-test"]');
  await waitFor(browser, `${recordedTests}.then((n) => n > ${before})`, 30000);
  await browser.click('[data-action="to-board"]');
}

async function saveSettings(browser, change) {
  await waitFor(browser, `!!document.querySelector('.product-bar [data-action="config"]')`);
  await browser.click('.product-bar [data-action="config"]');
  await waitFor(browser, `!!document.querySelector('#config-form')`);
  if (change) await browser.ev(change);
  await browser.click('button[form="config-form"][type="submit"]');
  await waitFor(browser, `!document.querySelector('#sheet').open`, 30000);
  await delay(800);
}

async function runLanguage(language) {
  const t = (zh, en) => (language === 'en' ? en : zh);
  const browser = await launch({ width: 1440, height: 1000, reduced: true });
  const shot = (name) => browser.shot(`${out}/${language}-${name}.jpg`);
  try {
    await browser.goto(base);
    await browser.ev(
      `localStorage.clear(); localStorage.setItem('rolecraft.locale', '${language}')`,
    );
    await browser.goto(base);
    await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
    await browser.click('[data-action="open-career"]');
    await browser.click('.case-hero [data-action="take-case"]');
    await waitFor(browser, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
    assert.equal(
      await browser.ev(`window.PracticeLive.store.active().v2Binding.workLanguage`),
      language,
    );
    await browser.click('.card-open');
    await browser.type('#new-title', t('试点决定', 'Pilot decision'));
    await browser.type(
      '#new-body',
      t(
        '先向首批 20 人受限开放，保留人工兜底。',
        'Open to the first 20 people with a human fallback.',
      ),
    );
    await browser.clickText(t('保存为作品', 'Save as work'));
    await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);

    // 1. Placement and the empty state.
    await openDelivery(browser);
    let seen = await read(browser);
    assert.equal(seen.aboveSubmit, t('提交选中的版本', 'Submit selected versions'));
    assert.ok(
      seen.text.includes(t('选好作品版本和决定后', 'Choose versions and a decision')),
      'the card asks for a choice before computing',
    );

    // 2. A fresh launch: two limits met, configuration v0 untested, everything else waits.
    await browser.click('#sheet .native-feedback input[type="checkbox"]');
    await browser.select('#sheet .native-feedback select', 'launch');
    seen = await settled(browser, `!!c.querySelector('.presubmit__count')`);
    assert.equal(seen.count, t('2/3 项已满足', '2/3 met'));
    assert.equal(seen.meter, seen.count);
    assert.deepEqual(
      seen.lines.map((line) => [line.met, line.text, line.action]),
      [
        [true, t('人数 20 ≤ 容量 30', '20 participants ≤ capacity 30'), null],
        [
          true,
          t(
            '人日 2 ≤ 3，第 7 天上线 ≤ 期限第 7 天',
            'Dev-days 2 ≤ 3; launch day 7 ≤ deadline day 7',
          ),
          null,
        ],
        [false, t('配置 v0 还没测过', 'Config v0 not tested yet'), t('去测试', 'Run a test')],
      ],
    );
    assert.match(
      seen.waiting,
      t(/^\d+ 项等待模型核验（不计入）$/, /^\d+ awaiting model verification \(not counted\)$/),
    );
    assert.ok(!seen.text.includes('%'), 'no percentage is shown');
    await shot('card-launch');

    // 3. A deferral leaves nothing for rules to check.
    await browser.select('#sheet .native-feedback select', 'defer_with_conditions');
    seen = await settled(browser, `!c.querySelector('.presubmit__count')`);
    assert.equal(seen.lines.length, 0);
    assert.match(
      seen.text,
      t(
        /按这个决定，没有规则能核实的项（\d+ 项不适用）/,
        /No rule-checkable items for this decision \(\d+ not applicable\)/,
      ),
    );
    await shot('card-defer');

    // 4. "Run a test" opens the bench and closes the panel.
    await browser.select('#sheet .native-feedback select', 'launch');
    await settled(browser, `!!c.querySelector('.presubmit__items button')`);
    await browser.click('#sheet [data-presubmit] .presubmit__items button');
    await waitFor(
      browser,
      `!document.querySelector('#sheet').open && !!document.querySelector('#lab-q')`,
    );

    // 5. 164 F17: test before the policy update, settle the settings (the update arrives),
    // retest on v1, then change the fallback to v2.
    await browser.click('[data-action="to-board"]');
    await runTest(browser, t);
    await saveSettings(browser);
    await runTest(browser, t);
    await saveSettings(
      browser,
      `document.querySelector('#config-form input[name="fallback"][value="none"]').click()`,
    );

    // 6. Reopening remembers the choice and names the versions.
    await openDelivery(browser);
    seen = await settled(browser, `!!c.querySelector('.presubmit__count')`);
    assert.equal(
      await browser.ev(`document.querySelector('#sheet .native-feedback select').value`),
      'launch',
    );
    await browser.select('#sheet .native-feedback select', 'launch_narrow');
    seen = await settled(browser, `!!c.querySelector('[data-criterion="R5.adjustment"]')`);
    assert.equal(seen.count, t('2/5 项已满足', '2/5 met'));
    assert.deepEqual(
      seen.lines.slice(2).map((line) => [line.criterion, line.text, line.action]),
      [
        [
          'R4.functional_tests',
          t('配置 v2 还没测过（配置 v1 测过 1 次）', 'Config v2 not tested yet (config v1: 1 run)'),
          t('去测试', 'Run a test'),
        ],
        [
          'R4.staleness_test',
          t(
            '政策更新后，配置 v2 还没复测（你在配置 v1 下复测过 1 次）',
            'No retest on config v2 since the policy update (1 retest on config v1)',
          ),
          t('去重测', 'Retest'),
        ],
        [
          'R5.adjustment',
          t(
            '政策更新后已有 1 次调整，配置 v2 之后还没复测',
            '1 adjustment since the policy update; config v2 not retested yet',
          ),
          t('去重测', 'Retest'),
        ],
      ],
    );
    const lastPreview = seen;
    await shot('card-f17');
    await browser.ev(`${card}.querySelector('details').open = true`);
    await shot('card-f17-basis');
    await browser.ev(`${card}.querySelector('details').open = false`);
    await viewport(browser, 390, 844, false);
    await browser.ev(`${card}.scrollIntoView({block: 'start'})`);
    assert.ok(
      await browser.ev(
        'document.documentElement.scrollWidth <= document.documentElement.clientWidth',
      ),
      'no horizontal scroll at 390px',
    );
    await shot('card-f17-390');
    await viewport(browser, 1440, 1000, true);
    await browser.ev(`${card}.scrollIntoView({block: 'start'})`);
    await shot('card-f17-dark');
    await viewport(browser, 1440, 1000, false);

    // 7. Submit the same choice: the formal feedback decides each item as the preview did.
    await clickReady(browser, t('提交选中的版本', 'Submit selected versions'), '#sheet button');
    await waitFor(
      browser,
      `window.PracticeLive.store.active().world.status === 'submitted'`,
      60000,
    );
    const formal = await browser.ev(`(async () => {
      const s = window.PracticeLive.store.active();
      const headers = { Authorization: 'Bearer ' + s.token };
      const subs = await (await fetch('/api/sessions/' + s.id + '/submissions', { headers })).json();
      const sub = subs.result.result.items.at(-1);
      for (let i = 0; i < 120; i++) {
        const body = await (await fetch('/api/sessions/' + s.id + '/feedback/' + sub.id, { headers })).json();
        const report = body.result?.result?.items?.[0];
        if (report?.rule_items) return report.rule_items.map((r) => [r.criterion, r.label, r.source, r.applicability]);
        await new Promise((r) => setTimeout(r, 500));
      }
      return null;
    })()`);
    assert.ok(formal, 'formal feedback arrived');
    const decided = formal.filter(
      ([, label, source, applicability]) =>
        source === 'verified_rule' && label !== 'INSUFFICIENT' && applicability === 'applicable',
    );
    assert.deepEqual(
      decided.map(([criterion, label]) => [criterion, label === 'MET']),
      lastPreview.lines.map((line) => [line.criterion, line.met]),
    );
    // 8. The feedback page names the versions behind each unmet item, "at submission".
    await browser.ev(`document.querySelector('#sheet')?.close()`);
    await browser.goto(`${base}#/review`);
    await waitFor(browser, `!!document.querySelector('[data-short-result="feedback"]')`, 60000);
    await browser.ev(
      `document.querySelector('[data-short-result="feedback"] > details').open = true`,
    );
    await waitFor(browser, `document.querySelectorAll('[data-rule-fact]').length >= 3`, 30000);
    const facts = await browser.ev(
      `[...document.querySelectorAll('[data-rule-fact]')].map((n) => [n.dataset.ruleFact, n.textContent])`,
    );
    assert.deepEqual(facts, [
      [
        'R4.functional_tests',
        t(
          '交付时：配置 v2 还没测过（配置 v1 测过 1 次）',
          'At submission: Config v2 not tested yet (config v1: 1 run)',
        ),
      ],
      [
        'R4.staleness_test',
        t(
          '交付时：政策更新后，配置 v2 还没复测（你在配置 v1 下复测过 1 次）',
          'At submission: No retest on config v2 since the policy update (1 retest on config v1)',
        ),
      ],
      [
        'R5.adjustment',
        t(
          '交付时：政策更新后已有 1 次调整，配置 v2 之后还没复测',
          'At submission: 1 adjustment since the policy update; config v2 not retested yet',
        ),
      ],
    ]);
    await browser.ev(
      `document.querySelector('[data-rule-fact="R4.functional_tests"]').closest('section').scrollIntoView({block: 'start'})`,
    );
    await shot('feedback-fact');
    results.push({
      language,
      status: 'passed',
      preview: lastPreview.lines,
      formal: decided,
      facts,
    });
  } catch (error) {
    await shot('failure').catch(() => undefined);
    results.push({ language, status: 'failed', error: String(error?.stack ?? error) });
    throw error;
  } finally {
    writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 2));
    await browser.close();
  }
}

for (const language of languages) await runLanguage(language);
console.log(JSON.stringify(results.map(({ language, status }) => ({ language, status }))));
