/** Model flows in the normal v4 entry (143 §3.7 item 2), Chinese then English.
 *
 * Started by `python -m scripts.regression.browser --suite model-flows`, which serves one
 * synthetic registration per phase (and loopback JUDGE / ASSISTANT slots for `slots`) over
 * real HTTP, a worker and vite preview. Every registration is constructed or untrained and
 * shown as a mechanism demonstration; nothing here is a model judgement or a quality claim.
 *
 * FLOW-01 submit → feedback → the model block shows registration identity, training data,
 *         per-sentence advice with evidence buttons that open the source, and the
 *         synthetic mechanism title; the same business fact gives the same per-sentence
 *         results in both languages.
 * FLOW-02 a reload reads the stored feedback and never runs the model again.
 * FLOW-03 after a registered file changes, new feedback says the model files changed.
 * FLOW-04 the evaluation model line names the JUDGE slot (`slots` phase).
 * FLOW-05 assistant generation is labelled as generated; it came from the ASSISTANT slot
 *         (the runner checks the loopback call log after this script).
 *
 * BASE, OUT and MODEL_FLOWS_PHASE come from the runner.
 */
import assert from 'node:assert/strict';
import { mkdirSync, readdirSync, readFileSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { delay, launch } from '../walkthrough/cdp.mjs';
import { clickReady, waitFor } from './browser-support.mjs';

const BASE = process.env.BASE;
const OUT = process.env.OUT;
const PHASE = JSON.parse(process.env.MODEL_FLOWS_PHASE ?? 'null');
assert.ok(BASE && OUT && PHASE, 'BASE, OUT and MODEL_FLOWS_PHASE are required');
mkdirSync(`${OUT}/screenshots`, { recursive: true });

// One business fact in both languages. Only the keywords move the constructed linear
// weights ("有据可查"/"corroborated" support, "豁免"/"exempt" contradict); no digits are used.
const WORK = {
  zh:
    '试点先只开放给已完成人工复核的团队，审批要求有据可查。若名额超过上限，需要先申请扩容。\n\n' +
    '住宿超过每晚500元可豁免事先批准。出租车单程上限为200元。\n\n- 保留人工兜底\n- 记录未知条件',
  en:
    'Open the pilot only to teams with completed human review, as corroborated by the approval rules. ' +
    'If seats exceed the limit, request capacity first.\n\n' +
    'Hotels above CNY 500 per night are exempt from prior approval. Taxi rides are capped at CNY 200.\n\n' +
    '- Keep human fallback\n- Record unknown conditions',
};
const KEYWORD_RESULTS = [
  'SUPPORTED',
  'INSUFFICIENT',
  'CONTRADICTED',
  'INSUFFICIENT',
  'INSUFFICIENT',
  'INSUFFICIENT',
];
const COPY = {
  zh: {
    title: '合成机制演示',
    abstained: '模型未判断任何句子',
    tooLong: '超长未核',
    notice: '合成或未训练权重，不是模型判断，不计分。',
    counts: '逐句：支持 1 · 矛盾 1 · 证据不足 4',
    conclusion: '作品整体：存在矛盾',
    failed: '模型建议失败',
    drift: '模型文件或推理环境已变化，需重新核验注册。',
    notConnected: '评价模型：未接入',
    judge: '评价模型：openai_compatible · qa-loopback-judge',
    llm: '模型生成 · 回答待核验',
    question: '住宿报销上限是多少？',
    save: '保存为作品',
    submit: '提交选中的版本',
    title_input: '试点决定',
    dataset: 'rolecraft-linear-mechanism-synthetic',
  },
  en: {
    title: 'Synthetic mechanism demo',
    abstained: 'The model judged no sentence',
    tooLong: 'Too long to check',
    notice: 'Synthetic or untrained weights: not a model judgment, not scored.',
    counts: 'By sentence: supported 1 · contradicted 1 · insufficient evidence 4',
    conclusion: 'Whole work: contradiction found',
    failed: 'Model advice failed',
    drift: 'Model files or the inference environment changed; verify the registration again.',
    notConnected: 'Evaluation model: not connected',
    judge: 'Evaluation model: openai_compatible · qa-loopback-judge',
    llm: 'Model-generated · Answer awaiting verification',
    question: 'What is the hotel reimbursement limit?',
    save: 'Save as work',
    submit: 'Submit selected versions',
    title_input: 'Pilot decision',
    dataset: 'rolecraft-linear-mechanism-synthetic',
  },
};
const advice = `document.querySelector('[data-model-advice]')`;
const keyword = ['linear', 'fusion', 'slots'].includes(PHASE.name);
const results = [];

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

const text = (browser, selector) =>
  browser.ev(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? null`);
const shot = (browser, name) => browser.shot(`${OUT}/screenshots/${PHASE.name}-${name}.jpg`);
const journalEntries = () => {
  try {
    return readdirSync(PHASE.journal).length;
  } catch {
    return 0;
  }
};

async function step(language, name, run) {
  const started = Date.now();
  await run();
  results.push({ phase: PHASE.name, language, step: name, ms: Date.now() - started });
  console.log(`model-flows ${PHASE.name} ${language} PASS ${name}`);
}

/** A new practice in the chosen language, at the work board. */
async function enter(browser, language) {
  await viewport(browser, 1440, 1000, false);
  await browser.goto(BASE);
  await browser.ev(`localStorage.clear(); localStorage.setItem('rolecraft.locale', '${language}')`);
  await browser.goto(BASE);
  await waitFor(browser, `!!document.querySelector('[data-action="open-career"]')`);
  await browser.click('[data-action="open-career"]');
  await browser.click('.case-hero [data-action="take-case"]');
  await waitFor(browser, `location.hash === '#/work' && !!document.querySelector('.card-open')`);
}

/** Save the work, submit it as "defer with conditions" and wait for the model block. */
async function submitWork(browser, language) {
  const copy = COPY[language];
  await browser.goto(`${BASE}#/work`);
  await waitFor(browser, `!!document.querySelector('.card-open')`);
  await browser.click('.card-open');
  await waitFor(browser, `!!document.querySelector('#new-body')`);
  await browser.type('#new-title', copy.title_input);
  await browser.type('#new-body', WORK[language]);
  await browser.clickText(copy.save);
  await waitFor(browser, `!!document.querySelector('.ol-row[data-type="work"]')`);
  await browser.click('[data-action="to-board"]');
  await waitFor(browser, `!!document.querySelector('.ws-toolbar [data-action="submit"]')`);
  await browser.click('.ws-toolbar [data-action="submit"]');
  await waitFor(browser, `!!document.querySelector('#sheet .native-feedback input[type="checkbox"]')`);
  await browser.click('#sheet .native-feedback input[type="checkbox"]');
  await browser.select('#sheet .native-feedback select', 'defer_with_conditions');
  await clickReady(browser, copy.submit, '#sheet button');
  await waitFor(browser, `window.PracticeLive.store.active().world.status === 'submitted'`, 60000);
  await browser.ev(`document.querySelector('#sheet')?.close()`);
  await browser.goto(`${BASE}#/review`);
  for (let waited = 0; !(await browser.ev(`!!${advice}`)); waited += 2) {
    assert.ok(
      !(await browser.ev(
        `/这次反馈没有完成|This feedback did not complete/.test(document.body.innerText)`,
      )),
      'the feedback job did not complete',
    );
    assert.ok(waited < 300, 'feedback with model advice did not appear');
    await delay(2000);
    await browser.clickText(language === 'zh' ? '查看最新反馈' : 'Refresh feedback', 'button').catch(
      () => undefined,
    );
  }
  await delay(400);
}

async function readAdvice(browser) {
  await browser.ev(`${advice}.open = true`);
  await delay(200);
  return JSON.parse(
    await browser.ev(`JSON.stringify({
      title: document.querySelector('[data-model-advice-title]')?.textContent ?? null,
      notice: document.querySelector('[data-model-advice-notice]')?.textContent ?? null,
      counts: document.querySelector('[data-model-advice-counts]')?.textContent ?? null,
      conclusion: document.querySelector('[data-model-advice-conclusion]')?.textContent ?? null,
      evaluation: document.querySelector('[data-evaluation-model]')?.textContent ?? null,
      units: [...document.querySelectorAll('[data-model-unit]')].map((li) => ({
        status: li.getAttribute('data-unit-status'),
        quote: li.querySelector('blockquote')?.textContent ?? null,
        result: li.querySelector('[data-unit-result]')?.textContent ?? null,
        evidence: li.querySelectorAll('[data-model-reference]').length,
      })),
      identity: [...document.querySelectorAll('[data-model-identity] p')].map((p) => p.textContent),
      body: ${advice}.innerText,
    })`),
  );
}

/** A sentence result as its label; other outcomes keep their status. */
const LABELS = {
  支持: 'SUPPORTED',
  矛盾: 'CONTRADICTED',
  证据不足: 'INSUFFICIENT',
  Supported: 'SUPPORTED',
  Contradicted: 'CONTRADICTED',
  'Insufficient evidence': 'INSUFFICIENT',
};
const outcome = (unit) => LABELS[unit.result] ?? unit.status;

async function mainPath(browser, language) {
  const copy = COPY[language];
  await step(language, 'FLOW-01 submit to feedback with the model block', async () => {
    await enter(browser, language);
    await submitWork(browser, language);
    const folded = {
      open: await browser.ev(`${advice}.open`),
      title: await text(browser, '[data-model-advice-title]'),
      notice: await text(browser, '[data-model-advice-notice]'),
    };
    // Encoder phases: a sentence whose input passes the token limit is not cut but left
    // unjudged; when every sentence is, the block says so instead of showing labels.
    const unjudged = !keyword && folded.title === copy.abstained;
    assert.deepEqual(folded, {
      open: false,
      title: unjudged ? copy.abstained : copy.title,
      notice: copy.notice,
    });
    await browser.ev(
      `${advice}.closest('section').scrollIntoView({block: 'start'}); document.scrollingElement.scrollBy(0, -80)`,
    );
    await shot(browser, `${language}-folded-desktop-light`);
    const view = await readAdvice(browser);
    assert.ok(view.units.length > 0, 'sentences are listed');
    if (unjudged)
      assert.ok(
        view.units.every((u) => u.status === 'abstained' && u.result === copy.tooLong),
        JSON.stringify(view.units),
      );
    results.push({ phase: PHASE.name, language, unjudged });
    assert.ok(!view.body.includes('模型建议（不计分）') && !view.body.includes('Model advice (not scored)'));
    if (keyword) {
      assert.deepEqual(view.units.map(outcome), KEYWORD_RESULTS);
      assert.equal(view.counts, copy.counts);
      assert.equal(view.conclusion, copy.conclusion);
      assert.equal(view.units.length, KEYWORD_RESULTS.length);
      assert.ok(view.identity.some((line) => line.includes(copy.dataset)), view.identity.join(' | '));
    }
    const kind = PHASE.identity.kind;
    if (kind === 'probability_fusion') {
      const weights = PHASE.identity.components.map((c) => String(c.alpha));
      for (const weight of weights)
        assert.ok(view.identity.some((line) => line.includes(weight)), view.identity.join(' | '));
      assert.ok(
        view.identity.some((line) => line.includes(String(PHASE.identity.fusion.alpha))),
        view.identity.join(' | '),
      );
    }
    if (PHASE.identity.weights_stage === 'pretrained_untrained_heads')
      assert.ok(
        view.identity.some((line) => /未训练|untrained/i.test(line)),
        view.identity.join(' | '),
      );
    assert.ok(
      view.identity.some((line) => line.includes(PHASE.identity.id)),
      view.identity.join(' | '),
    );
    await shot(browser, `${language}-opened-desktop-light`);
    results.push({ phase: PHASE.name, language, view });
    // Evidence buttons open the cited source beside the feedback.
    const clicked = await browser.ev(`(() => {
      // A material has text to open (a configuration reference has none: 149 P3-9).
      const all = [...document.querySelectorAll('[data-model-unit] [data-model-reference]')];
      const b = all.find((x) => JSON.parse(x.dataset.modelReference).kind === 'material') ?? all[0];
      if (!b) return null;
      b.scrollIntoView({ block: 'center' });
      b.click();
      return b.textContent;
    })()`);
    if (keyword) assert.ok(clicked, 'a judged sentence has an evidence button');
    if (clicked) {
      await waitFor(
        browser,
        `(document.querySelector('[data-v4-reference-side]')?.innerText.length ?? 0) > 40`,
        15000,
      );
      await shot(browser, `${language}-evidence-opened-desktop-light`);
    }
    for (const [name, width, height, dark] of [
      ['390-dark', 390, 844, true],
      ['desktop-dark', 1440, 1000, true],
    ]) {
      await viewport(browser, width, height, dark);
      await browser.ev(`${advice}.open = true; ${advice}.scrollIntoView({block: 'start'})`);
      await delay(250);
      assert.equal(
        await browser.ev('document.documentElement.scrollWidth > document.documentElement.clientWidth'),
        false,
        `${name}: horizontal overflow`,
      );
      await shot(browser, `${language}-opened-${name}`);
    }
    await viewport(browser, 1440, 1000, false);
  });
  await step(language, 'FLOW-02 reload reads stored feedback without a new model run', async () => {
    const before = journalEntries();
    const counts = await text(browser, '[data-model-advice-counts]');
    await browser.goto(`${BASE}#/review`);
    await browser.ev('location.reload()');
    await waitFor(browser, `!!${advice}`, 30000);
    await delay(1500);
    assert.equal(await text(browser, '[data-model-advice-counts]'), counts);
    assert.equal(journalEntries(), before, 'a reload must not journal another model request');
  });
}

async function drift(browser, language) {
  const copy = COPY[language];
  await step(language, 'FLOW-03 a changed registered file shows in new feedback', async () => {
    const path = PHASE.drift_file;
    const original = readFileSync(path);
    const { atime, mtime } = statSync(path);
    const changed = Buffer.from(original);
    changed[changed.length - 1] ^= 1;
    writeFileSync(path, changed);
    utimesSync(path, atime, mtime);
    try {
      await enter(browser, language);
      await submitWork(browser, language);
      assert.equal(await text(browser, '[data-model-advice-title]'), copy.failed);
      const view = await readAdvice(browser);
      assert.ok(view.body.includes(copy.drift), view.body);
      assert.ok(view.units.every((unit) => unit.evidence === 0), 'no labels or evidence shown');
      await shot(browser, `${language}-drift-opened-desktop-light`);
    } finally {
      writeFileSync(path, original);
      utimesSync(path, atime, mtime);
    }
  });
}

async function slots(browser, language) {
  const copy = COPY[language];
  await step(language, 'FLOW-05 assistant generation is labelled and served by its slot', async () => {
    await enter(browser, language);
    await browser.goto(`${BASE}#/work`);
    await waitFor(browser, `!!document.querySelector('[data-action="open-bench"]')`);
    await browser.click('[data-action="open-bench"]');
    await waitFor(browser, `!!document.querySelector('#lab-q')`);
    await browser.click('.console-tools [data-action="config"]');
    await waitFor(browser, `!!document.querySelector('#config-form .generator-field')`);
    assert.equal(
      await browser.ev(`document.querySelector('#config-form input[value="llm"]').disabled`),
      false,
      'the ASSISTANT slot makes model generation selectable',
    );
    await browser.click('#config-form input[value="llm"]');
    const version = await browser.ev('window.PracticeLive.store.active().world.config_version');
    await browser.submit('#config-form');
    await waitFor(
      browser,
      `window.PracticeLive.store.active().world.config_version === ${version + 1}`,
      20000,
    );
    await browser.type('#lab-q', copy.question);
    await browser.submit('[data-form="run-test"]');
    await waitFor(
      browser,
      `!!document.querySelector('.runs .run .answer-mode[data-answer-mode="llm"]')`,
      60000,
    );
    const label = await text(browser, '.runs .run .answer-mode[data-answer-mode="llm"]');
    assert.equal(label, copy.llm);
    await shot(browser, `${language}-assistant-generated-desktop-light`);
  });
  await step(language, 'FLOW-04 feedback names the JUDGE slot model', async () => {
    await submitWork(browser, language);
    const evaluation = await text(browser, '[data-evaluation-model]');
    assert.ok(evaluation?.startsWith(copy.judge), evaluation);
    await browser.ev(
      `document.querySelector('[data-evaluation-model]').scrollIntoView({block: 'center'})`,
    );
    await shot(browser, `${language}-evaluation-model-desktop-light`);
    results.push({ phase: PHASE.name, language, evaluation });
  });
}

const browser = await launch({ width: 1440, height: 1000, reduced: true });
try {
  for (const language of ['zh', 'en']) {
    if (PHASE.slots) {
      await slots(browser, language);
      continue;
    }
    await mainPath(browser, language);
    if (PHASE.drift_file) await drift(browser, language);
  }
  if (!PHASE.slots) {
    // FLOW-01: the same business fact gives the same per-sentence results in both languages.
    const [zh, en] = ['zh', 'en'].map((language) =>
      results.find((row) => row.language === language && row.view).view.units.map(outcome),
    );
    assert.deepEqual(zh, en);
  }
  const exceptions = (browser.logs ?? []).filter((entry) => entry.level === 'exception');
  assert.deepEqual(exceptions, []);
} catch (error) {
  await browser.shot(`${OUT}/screenshots/${PHASE.name}-failure.jpg`).catch(() => {});
  throw error;
} finally {
  writeFileSync(`${OUT}/model-flows-${PHASE.name}.json`, `${JSON.stringify(results, null, 2)}\n`);
  await browser.close();
}
