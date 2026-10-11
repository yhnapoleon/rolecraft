/** Decision 5 (2026-10-11) in the normal v4 entry, zh and en: the feedback first screen shows
 * the rule-anchored range (never a single total) on a launch with mixed rule outcomes, each
 * expanded item names its weight share and status, and an old candidate-2 session says its
 * rubric version has no range. Desktop and 390px, light and dark.
 * PHASE=old runs on a server whose catalog still installs candidate 2; PHASE=after runs on the
 * installed final rubric with the same database. Writes screenshots and results to OUT. */
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { delay, launch } from '../../../tests/walkthrough/cdp.mjs';
import { clickReady, waitFor } from '../../../tests/regression/browser-support.mjs';

const base = process.env.BASE;
const out = process.env.OUT;
const phase = process.env.PHASE;
assert.ok(base && out && ['old', 'after'].includes(phase), 'BASE, OUT and PHASE are required');
mkdirSync(out, { recursive: true });
const results = [];
const block = `document.querySelector('[data-short-result="feedback"]')`;

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
const toFeedback = (browser) =>
  browser.ev(
    `${block}.closest('article').scrollIntoView({block:'start'}); document.scrollingElement.scrollBy(0, -96)`,
  );

/** A new practice from the normal entry: save one work, submit it as a launch. */
async function submitLaunch(browser, language, t) {
  await browser.goto(base);
  await browser.ev(`localStorage.clear(); localStorage.setItem('rolecraft.locale', '${language}')`);
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
  await browser.type('#new-title', t('139 试点决定', '139 pilot decision'));
  await browser.type(
    '#new-body',
    t(
      '按当前配置推进试点，保留人工兜底。',
      'Proceed with the pilot on the current settings; keep a human fallback.',
    ),
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
  await browser.select('#sheet .native-feedback select', 'launch');
  await clickReady(browser, t('提交选中的版本', 'Submit selected versions'), '#sheet button');
  await waitFor(browser, `window.PracticeLive.store.active().world.status === 'submitted'`, 60000);
  await browser.ev(`document.querySelector('#sheet')?.close()`);
  await openFeedback(browser, t);
}

/** Feedback is a worker job; use the page's own controls while waiting, as a learner would. */
async function openFeedback(browser, t) {
  await browser.goto(`${base}#/review`);
  let retried = 0;
  for (let waited = 0; !(await browser.ev(`!!${block}`)); waited += 5) {
    assert.ok(waited < 600, 'submission feedback did not appear');
    await delay(5000);
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
  await delay(500);
  return retried;
}

const firstScreen = (browser) =>
  browser.ev(`(() => {
    const b = ${block};
    const range = b.querySelector(':scope > .short-result__note [data-score-range]');
    return {
      version: b.closest('article').querySelector('[data-rubric-version]')?.dataset.rubricVersion,
      versionText: b.closest('article').querySelector('[data-rubric-version]')?.textContent,
      kind: range?.dataset.scoreRange ?? null,
      range: range?.textContent ?? null,
      notes: [...b.querySelectorAll(':scope > .short-result__note')].map((n) => n.textContent),
      statuses: [...b.querySelectorAll(':scope > .short-result__status li')].map((n) => n.textContent),
      folded: !b.querySelector(':scope > details').open,
      rangeBeforeFold:
        !!range &&
        !!(range.compareDocumentPosition(b.querySelector(':scope > details')) &
          Node.DOCUMENT_POSITION_FOLLOWING),
      weights: document.querySelectorAll('[data-criterion-weight]').length,
      text: b.innerText,
    };
  })()`);

async function shot(browser, language, name) {
  await toFeedback(browser);
  await browser.shot(`${out}/${language}-${name}.jpg`);
}

async function runOld(language, t) {
  const browser = await launch({ width: 1440, height: 1000, reduced: true });
  try {
    const retried = await submitLaunch(browser, language, t);
    const screen = await firstScreen(browser);
    assert.equal(screen.version, 'feedback-rubric-v2-c2.1');
    assert.equal(screen.kind, 'version');
    assert.equal(
      screen.range,
      t('分数区间：此评价标准版本不汇总。', 'No range for this rubric version.'),
    );
    assert.equal(screen.weights, 0);
    await shot(browser, language, 'old-before-switch-desktop');
    const session = JSON.parse(
      await browser.ev(`JSON.stringify((() => { const s = window.PracticeLive.store.active();
        return { id: s.id, token: s.token, binding: s.v2Binding }; })())`),
    );
    writeFileSync(`${out}/${language}-old-session.json`, JSON.stringify(session, null, 2));
    writeFileSync(
      `${out}/${language}-old-storage.json`,
      await browser.ev('JSON.stringify(Object.assign({}, localStorage))'),
    );
    results.push({
      language,
      phase,
      check: 'candidate-2 session before the switch',
      retried,
      screen,
    });
  } catch (error) {
    await browser.shot(`${out}/${language}-${phase}-failure.jpg`).catch(() => {});
    throw error;
  } finally {
    await browser.close();
  }
}

async function runAfter(language, t) {
  const browser = await launch({ width: 1440, height: 1000, reduced: true });
  try {
    // 1. The old candidate-2 session after the switch: version line kept, no range.
    const stored = JSON.parse(readFileSync(`${out}/${language}-old-storage.json`, 'utf8'));
    const old = JSON.parse(readFileSync(`${out}/${language}-old-session.json`, 'utf8'));
    await browser.goto(base);
    await browser.ev(`(() => { localStorage.clear(); const s = ${JSON.stringify(stored)};
      for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); })()`);
    await browser.goto(base);
    await waitFor(browser, `!!window.PracticeLive?.store?.active?.()`, 20000);
    assert.equal(await browser.ev(`window.PracticeLive.store.active().id`), old.id);
    await openFeedback(browser, t);
    const sealed = await firstScreen(browser);
    assert.equal(sealed.version, 'feedback-rubric-v2-c2.1');
    assert.equal(
      sealed.versionText,
      t('评价标准：rubric-v2 候选 2（定稿前）', 'Rubric: rubric-v2 candidate 2 (pre-final)'),
    );
    assert.equal(sealed.kind, 'version');
    assert.equal(
      sealed.range,
      t('分数区间：此评价标准版本不汇总。', 'No range for this rubric version.'),
    );
    assert.ok(sealed.rangeBeforeFold && sealed.folded);
    assert.equal(sealed.weights, 0);
    assert.ok(!/\d+(\.\d)?–\d+(\.\d)?/.test(sealed.text), 'no range numbers on candidate 2');
    await shot(browser, language, 'old-c2-desktop-light');
    await viewport(browser, 390, 844, true);
    assert.equal(await noOverflow(browser), true);
    await shot(browser, language, 'old-c2-390-dark');
    results.push({ language, phase, check: 'old candidate-2 session shows no range', sealed });

    // 2. A new session on the final rubric: launch with mixed rule outcomes.
    await viewport(browser, 1440, 1000, false);
    const retried = await submitLaunch(browser, language, t);
    const screen = await firstScreen(browser);
    const range = t(
      '规则已定标部分：20–65 分（适用项共 75 分，满分 100）',
      'Rule-anchored part: 20–65 of 75 (applicable items; full rubric 100)',
    );
    const note = t(
      '模型建议不计分；待核验项使区间变宽。',
      'Model advice is not scored; pending items widen the range.',
    );
    assert.equal(screen.version, 'feedback-rubric-v2-final.1');
    assert.equal(screen.kind, 'range');
    assert.deepEqual(screen.notes, [range, note]);
    assert.ok(screen.rangeBeforeFold && screen.folded, 'range on the first screen, items folded');
    assert.ok(!/总分|single total|overall score/i.test(screen.text));
    assert.ok(
      screen.statuses.includes(t('规则核实 3 项', 'Verified by rules: 3')),
      JSON.stringify(screen.statuses),
    );
    for (const [width, height, dark, name] of [
      [1440, 1000, false, 'new-range-desktop-light'],
      [1440, 1000, true, 'new-range-desktop-dark'],
      [390, 844, false, 'new-range-390-light'],
      [390, 844, true, 'new-range-390-dark'],
    ]) {
      await viewport(browser, width, height, dark);
      if (width < 500) assert.equal(await noOverflow(browser), true, name);
      assert.equal((await firstScreen(browser)).range, range);
      await shot(browser, language, name);
    }

    // 3. Expanded items: weight share and status; points only where rules set them.
    await viewport(browser, 1440, 1000, false);
    await browser.ev(`${block}.querySelector(':scope > details').open = true`);
    await browser.ev(
      `for (const d of ${block}.querySelectorAll('details:not([data-response-id]):not([data-model-advice])')) d.open = true`,
    );
    await delay(300);
    const weights = JSON.parse(
      await browser.ev(`JSON.stringify(Object.fromEntries([...document.querySelectorAll('[data-criterion-weight]')]
        .map((n) => [n.dataset.criterionWeight, n.textContent])))`),
    );
    assert.equal(Object.keys(weights).length, 14);
    assert.equal(
      weights['R3.capacity'],
      t(
        '权重 10 分（满分 100）· 规则已定标：计 10 分',
        'Weight 10 of 100 · Rule-anchored: 10 points',
      ),
    );
    assert.equal(
      weights['R4.functional_tests'],
      t(
        '权重 10 分（满分 100）· 规则已定标：计 0 分',
        'Weight 10 of 100 · Rule-anchored: 0 points',
      ),
    );
    assert.equal(
      weights['R2.support'],
      t(
        '权重 8.3 分（满分 100）· 待核验：不计分，区间因此加宽 8.3 分',
        'Weight 8.3 of 100 · Pending: not scored; widens the range by 8.3',
      ),
    );
    assert.equal(
      weights['R5.impact'],
      t(
        '权重 7.5 分（满分 100）· 本次不适用：不计入分母',
        'Weight 7.5 of 100 · Not applicable: left out of the denominator',
      ),
    );
    await browser.ev(
      `document.querySelector('[data-criterion-weight="R3.capacity"]').closest('section').scrollIntoView({block:'start'}); document.scrollingElement.scrollBy(0, -96)`,
    );
    await browser.shot(`${out}/${language}-new-items-desktop-light.jpg`);
    await viewport(browser, 390, 844, true);
    assert.equal(await noOverflow(browser), true);
    await browser.ev(
      `document.querySelector('[data-criterion-weight="R2.support"]').closest('section').scrollIntoView({block:'start'}); document.scrollingElement.scrollBy(0, -96)`,
    );
    await browser.shot(`${out}/${language}-new-items-390-dark.jpg`);
    const session = JSON.parse(
      await browser.ev(`JSON.stringify((() => { const s = window.PracticeLive.store.active();
        return { id: s.id, token: s.token, binding: s.v2Binding }; })())`),
    );
    writeFileSync(`${out}/${language}-new-session.json`, JSON.stringify(session, null, 2));
    writeFileSync(`${out}/${language}-new-page.txt`, await browser.ev('document.body.innerText'));
    assert.notEqual(session.binding.scenarioHash, old.binding.scenarioHash);
    assert.deepEqual(
      browser.logs.filter((entry) => entry.level === 'exception'),
      [],
    );
    results.push({
      language,
      phase,
      check: 'final-rubric range and items',
      retried,
      screen,
      weights,
    });
  } catch (error) {
    await browser.shot(`${out}/${language}-${phase}-failure.jpg`).catch(() => {});
    throw error;
  } finally {
    await browser.close();
  }
}

for (const language of ['zh', 'en']) {
  const t = (zh, en) => (language === 'en' ? en : zh);
  try {
    await (phase === 'old' ? runOld : runAfter)(language, t);
    console.log(`PASS ${phase} ${language}`);
  } catch (error) {
    writeFileSync(
      `${out}/${phase}-results.json`,
      JSON.stringify([...results, { language, phase, error: String(error) }], null, 2),
    );
    throw error;
  }
}
writeFileSync(`${out}/${phase}-results.json`, `${JSON.stringify(results, null, 2)}\n`);
