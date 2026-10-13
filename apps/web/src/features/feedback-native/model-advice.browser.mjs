import { afterAll, beforeAll, expect, it } from 'vitest';
import { createServer } from 'vite';
import { launch } from '../../../tests/walkthrough/cdp.mjs';
import { recorded, recordedReport, scenarios } from './model-advice.scenarios.mjs';

// 19810 by default; a parallel worktree may pick its own port.
const port = Number(process.env.MODEL_ADVICE_PORT || 19810);
const page = (language) =>
  `http://127.0.0.1:${port}/src/features/feedback-native/review-check.html?lang=${language}`;
let server;
beforeAll(async () => {
  server = await createServer({ server: { port, strictPort: true }, logLevel: 'error' });
  await server.listen();
});
afterAll(async () => {
  await server?.close();
});

// 149 (2026-10-12 decision 2): the synthetic block is titled "Synthetic mechanism demo" and
// says it is not a model judgment and not scored; it was "Mechanism validation" before.
it('MODEL-02: synthetic feedback stays folded and identifies the mechanism demo', async () => {
  const browser = await launch({ width: 390, height: 844, mobile: true, reduced: true });
  try {
    await browser.goto(page('en'));
    await browser.ev(`window.fixture.state.reports[0].model_advice = [{
      criterion: 'R2.support', status: 'synthetic_mechanism_only',
      registration: { id: 'sample', model_revision: 'fixed', scope: 'synthetic_fixture', quality_validated: false },
      label: null, evidence_ids: [], citations: [], error_code: 'synthetic_mechanism_only',
      mode: 'advisory', affects_score: false
    }]; window.fixture.update();`);
    expect(
      await browser.ev(`document.querySelector('[data-model-advice] summary')?.textContent`),
    ).toBe(
      'Synthetic mechanism demo' +
        'Synthetic or untrained weights: not a model judgment, not scored.',
    );
    expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
    expect(await browser.ev('window.fixture.calls')).toEqual([]);
  } finally {
    await browser.close();
  }
}, 20000);

const completed = {
  criterion: 'R2.support',
  status: 'completed',
  registration: {
    id: 'external-example',
    model_revision: 'fixed-revision',
    scope: 'external_candidate',
    quality_validated: false,
  },
  label: 'SUPPORTED',
  evidence_ids: ['public-source'],
  citations: [{ session_id: 'fixture', kind: 'product', object_id: 'note', version: 2 }],
  error_code: null,
  mode: 'advisory',
  affects_score: false,
};
const item = (criterion, source = 'pending', label = 'INSUFFICIENT') => ({
  criterion,
  source,
  label,
  explanation: 'Stored original',
  citations: [],
  applicability: 'applicable',
});

it.each(['zh', 'en'])(
  'MODEL-UI-coverage: %s keeps advice and pending coverage separate',
  async (language) => {
    const browser = await launch();
    try {
      await browser.goto(page(language));
      await browser.ev(
        `Object.assign(window.fixture.state.reports[0], ${JSON.stringify({
          model_advice: [completed],
          items: [
            item('R1.target', 'verified_rule', 'MET'),
            item('R2.support'),
            item('R2.unknowns'),
            {
              ...item('R3.capacity', 'pending', 'NOT_APPLICABLE'),
              applicability: 'not_applicable',
            },
          ],
        })}); window.fixture.update();`,
      );
      const coverage = await browser.ev(
        `document.querySelector('[data-feedback-coverage]')?.textContent`,
      );
      expect(coverage).toBe(
        language === 'en'
          ? 'Verified 1 of 3 applicable items · Model advice 1 · Pending verification 1'
          : '已核实 1 项／共 3 项适用 · 模型建议 1 项 · 待核验 1 项',
      );
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
    } finally {
      await browser.close();
    }
  },
);

async function withFeedback(language, run) {
  const browser = await launch({ width: 390, height: 844, mobile: true, reduced: true });
  try {
    await browser.goto(page(language));
    await run(browser);
    expect(browser.logs.filter((entry) => entry.level === 'exception')).toEqual([]);
  } finally {
    await browser.close();
  }
}
const summaryText = (browser) =>
  browser.ev(`document.querySelector('[data-model-advice] summary')?.textContent`);
const setReport = (browser, report) =>
  browser.ev(
    `Object.assign(window.fixture.state.reports[0], ${JSON.stringify(report)}); window.fixture.update();`,
  );

it.each(['zh', 'en'])(
  'MODEL-UI-states: %s distinguishes empty, waiting, failed and completed advice',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const en = language === 'en';
      expect(await summaryText(browser)).toBe(en ? 'Awaiting model connection' : '等待模型接入');
      await setReport(browser, { semantic_status: 'pending', model_advice: [] });
      expect(await summaryText(browser)).toBe(
        en ? 'Model advice awaiting verification' : '模型建议待核验',
      );
      await setReport(browser, { semantic_status: 'waiting_for_model' });
      expect(await summaryText(browser)).toBe(en ? 'Awaiting model connection' : '等待模型接入');
      await setReport(browser, { semantic_status: 'failed' });
      expect(await summaryText(browser)).toBe(en ? 'Model advice failed' : '模型建议失败');
      await setReport(browser, { semantic_status: 'available', model_advice: [completed] });
      expect(await summaryText(browser)).toBe(
        en ? 'Model advice (not scored)' : '模型建议（不计分）',
      );
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
      await browser.click('[data-model-advice] summary');
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(true);
      await browser.ev('window.fixture.update()');
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(true);
      await browser.click('[data-model-advice] summary');
      await browser.ev('window.fixture.update()');
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
    });
  },
);

it.each(['zh', 'en'])(
  'MODEL-04: %s permission refresh removes only denied advice and retains keyboard focus',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const second = {
        ...completed,
        evidence_ids: ['other-source'],
        citations: [{ ...completed.citations[0], object_id: 'other' }],
      };
      await setReport(browser, { model_advice: [completed, second], items: [item('R2.support')] });
      await browser.click('[data-model-advice] summary');
      await browser.ev(`document.querySelector('[data-model-reference]').focus()`);
      const denied = {
        ...completed,
        status: 'unavailable',
        label: null,
        evidence_ids: [],
        citations: [],
        error_code: 'evidence_unavailable',
      };
      await setReport(browser, { model_advice: [denied, second] });
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(true);
      expect(await browser.ev(`document.activeElement.tagName`)).toBe('SUMMARY');
      expect(await browser.ev(`document.querySelectorAll('[data-model-reference]').length`)).toBe(
        1,
      );
      expect(
        await browser.ev(`document.querySelector('[data-model-advice]').innerText`),
      ).not.toContain('public-source');
      expect(
        await browser.ev(`document.querySelector('[data-feedback-coverage]').textContent`),
      ).toContain(language === 'en' ? 'Model advice 0' : '模型建议 0 项');
      await browser.click('[data-model-reference]');
      expect(await browser.ev('window.fixture.calls')).toEqual([
        { operation: 'openReference', ref: second.citations[0] },
      ]);
      await browser.ev(
        `document.querySelector('[data-model-reference]').focus(); window.fixture.state.reports = []; window.fixture.update();`,
      );
      expect(await browser.ev(`document.querySelectorAll('[data-model-reference]').length`)).toBe(
        0,
      );
      expect(await summaryText(browser)).toBe(
        language === 'en' ? 'Model advice is unavailable' : '当前模型建议不可读取',
      );
    });
  },
);

it.each(['zh', 'en'])(
  'MODEL-06: %s keeps failure states and original feedback without a replacement model',
  async (language) => {
    await withFeedback(language, async (browser) => {
      await setReport(browser, {
        model_advice: [
          {
            ...completed,
            status: 'unavailable',
            label: null,
            evidence_ids: [],
            citations: [],
            error_code: 'model_load_failed',
          },
        ],
      });
      expect(await summaryText(browser)).toBe(
        language === 'en' ? 'Model advice failed' : '模型建议失败',
      );
      await browser.click('[data-model-advice] summary');
      expect(await browser.ev(`document.querySelector('[data-model-advice]').innerText`)).toContain(
        language === 'en'
          ? 'The registered model could not be loaded; no other model was substituted.'
          : '注册模型加载失败，未切换到其他模型。',
      );
      expect(await browser.ev(`document.querySelector('.native-feedback').innerText`)).toContain(
        language === 'en' ? 'Recorded fixture; no semantic judgment.' : '受控记录，未作语义判断。',
      );
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
    });
  },
);

it.each(['zh', 'en'])(
  'MODEL-UI-layout: %s long registered identifiers wrap at 390px',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const long = {
        ...completed,
        registration: {
          ...completed.registration,
          id: 'registration'.repeat(12),
          model_revision: 'f'.repeat(128),
        },
      };
      await setReport(browser, { model_advice: [long] });
      await browser.click('[data-model-advice] summary');
      expect(await browser.ev('document.documentElement.scrollWidth > innerWidth')).toBe(false);
    });
  },
);

it.each(['zh', 'en'])(
  'MODEL-UI-keyboard: %s opens and closes by Enter with native key text',
  async (language) => {
    await withFeedback(language, async (browser) => {
      await browser.ev(`document.querySelector('[data-model-advice] summary').focus()`);
      expect(await browser.ev(`document.activeElement.tagName`)).toBe('SUMMARY');
      const press = async () => {
        await browser.send('Input.dispatchKeyEvent', {
          type: 'keyDown',
          key: 'Enter',
          code: 'Enter',
          windowsVirtualKeyCode: 13,
          text: '\r',
          unmodifiedText: '\r',
        });
        await browser.send('Input.dispatchKeyEvent', {
          type: 'keyUp',
          key: 'Enter',
          code: 'Enter',
          windowsVirtualKeyCode: 13,
        });
      };
      await press();
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(true);
      await browser.ev('window.fixture.update()');
      expect(await browser.ev(`document.activeElement.tagName`)).toBe('SUMMARY');
      await press();
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
    });
  },
);

/** Read raw HTTP advice through the page's own reader, then render it. */
const showAdvice = (browser, raw, extra = {}) =>
  browser.ev(
    `Object.assign(window.fixture.state.reports[0], ${JSON.stringify(extra)}, {
      model_advice: window.fixture.read(${JSON.stringify(raw)}),
    }); window.fixture.update();`,
  );
const visible = (browser, selector) =>
  browser.ev(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? null`);
const T = (language, zh, en) => (language === 'en' ? en : zh);

it.each(['zh', 'en'])(
  'UI-02: %s synthetic sentence advice is a folded mechanism demo, not a model judgment',
  async (language) => {
    await withFeedback(language, async (browser) => {
      await showAdvice(browser, [recorded.advice[language]]);
      expect(await visible(browser, '[data-model-advice-title]')).toBe(
        T(language, '合成机制演示', 'Synthetic mechanism demo'),
      );
      expect(await visible(browser, '[data-model-advice-notice]')).toBe(
        T(
          language,
          '合成或未训练权重，不是模型判断，不计分。',
          'Synthetic or untrained weights: not a model judgment, not scored.',
        ),
      );
      expect(await visible(browser, '[data-model-advice-conclusion]')).toBe(
        T(language, '作品整体：存在矛盾', 'Whole work: contradiction found'),
      );
      expect(await visible(browser, '[data-model-advice-counts]')).toBe(
        T(
          language,
          '逐句：支持 1 · 矛盾 1 · 证据不足 4',
          'By sentence: supported 1 · contradicted 1 · insufficient evidence 4',
        ),
      );
      expect(await browser.ev(`document.querySelector('[data-model-advice]').open`)).toBe(false);
      const block = await browser.ev(`document.querySelector('[data-model-advice]').textContent`);
      for (const judged of ['模型建议（不计分）', 'Model advice (not scored)', '机制验证'])
        expect(block).not.toContain(judged);
      await browser.click('[data-model-advice] summary');
      const rows =
        await browser.ev(`[...document.querySelectorAll('[data-model-unit]')].map((li) => ({
        quote: li.querySelector('blockquote')?.textContent,
        result: li.querySelector('[data-unit-result]')?.textContent,
        evidence: li.querySelectorAll('[data-model-reference]').length,
      }))`);
      const units = recorded.advice[language].units;
      expect(rows.map((r) => r.quote)).toEqual(units.map((u) => u.subject.quote));
      expect(rows.map((r) => r.result)).toEqual(
        language === 'en'
          ? [
              'Supported',
              'Insufficient evidence',
              'Contradicted',
              'Insufficient evidence',
              'Insufficient evidence',
              'Insufficient evidence',
            ]
          : ['支持', '证据不足', '矛盾', '证据不足', '证据不足', '证据不足'],
      );
      expect(rows.map((r) => r.evidence)).toEqual(units.map((u) => u.citations.length));
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
      await browser.click('[data-model-unit] [data-model-reference]');
      expect(await browser.ev('window.fixture.calls')).toEqual([
        {
          operation: 'openReference',
          ref: {
            session_id: 'fixture',
            kind: 'config',
            object_id: 'pilot',
            version: 1,
            config_version: 0,
          },
        },
      ]);
    });
  },
);

const showReport = (browser, language, advice) =>
  browser.ev(`window.fixture.state.reports = [${JSON.stringify(recordedReport(language, []))}];
    window.fixture.state.reports[0].model_advice = window.fixture.read(${JSON.stringify(advice)});
    window.fixture.update();`);
const verdicts = ['支持', '矛盾', '证据不足', 'Supported', 'Contradicted', 'Insufficient evidence'];

it.each(['zh', 'en'])(
  'UI-07: %s load failure, timeout and all-abstained are explicit, never adopted, and keep the work',
  async (language) => {
    await withFeedback(language, async (browser) => {
      await showReport(browser, language, []);
      const rules = await browser.ev(`document.querySelector('.native-feedback').innerText`);
      const coverage = await visible(browser, '[data-feedback-coverage]');
      await browser.click('.native-feedback article > details[data-response-id] summary');
      const draft = T(language, '我的异议原文', 'My own challenge text');
      await browser.type('.native-feedback article > details[data-response-id] textarea', draft);
      await browser.ev('document.activeElement.blur()');
      const expected = {
        loadFailed: {
          title: T(language, '模型建议失败', 'Model advice failed'),
          counts: null,
          reason: T(
            language,
            '注册模型加载失败，未切换到其他模型。',
            'The registered model could not be loaded; no other model was substituted.',
          ),
          unit: null,
        },
        timeout: {
          title: T(language, '模型调用超时', 'Model call timed out'),
          counts: T(language, '逐句：失败 6', 'By sentence: failed 6'),
          reason: T(
            language,
            '模型调用超时，没有自动重试。',
            'The model call timed out and was not retried automatically.',
          ),
          unit: T(language, '未判断', 'Not judged'),
        },
        abstained: {
          title: T(language, '模型未判断任何句子', 'The model judged no sentence'),
          counts: T(language, '逐句：超长未核 6', 'By sentence: too long to check 6'),
          reason: T(
            language,
            '每一句都超过模型输入上限或被模型弃权。',
            'Every sentence exceeded the model’s input limit or was abstained on.',
          ),
          unit: T(language, '超长未核', 'Too long to check'),
          note: T(
            language,
            '超长未核：句子超过模型输入上限，未截断、未判断。',
            'Too long to check: the sentence exceeds the model’s input limit; it was not truncated or judged.',
          ),
        },
      };
      for (const [name, want] of Object.entries(expected)) {
        await showReport(browser, language, [scenarios[name](language)]);
        expect(await visible(browser, '[data-model-advice-title]')).toBe(want.title);
        expect(await visible(browser, '[data-model-advice-counts]')).toBe(want.counts);
        expect(await visible(browser, '[data-model-advice-conclusion]')).toBe(null);
        await browser.ev(`document.querySelector('[data-model-advice]').open = true`);
        const block = await browser.ev(`document.querySelector('[data-model-advice]').innerText`);
        expect(block).toContain(want.reason);
        expect(block).toContain(
          T(
            language,
            '未采用任何模型建议；原作品与已核实的规则结果都保留。',
            'No model advice was adopted; your work and the verified rule results are retained.',
          ),
        );
        if (want.note) expect(block).toContain(want.note);
        const results = await browser.text('[data-unit-result]');
        expect(results).toEqual(want.unit ? Array(6).fill(want.unit) : []);
        for (const verdict of verdicts) expect(results).not.toContain(verdict);
        expect(await browser.ev(`document.querySelectorAll('[data-model-reference]').length`)).toBe(
          0,
        );
        expect(await visible(browser, '[data-feedback-coverage]')).toBe(coverage);
        expect(
          await browser.ev(
            `document.querySelector('.native-feedback article > details[data-response-id] textarea').value`,
          ),
        ).toBe(draft);
        const page = await browser.ev(`document.querySelector('.native-feedback').innerText`);
        const ruleLines = rules
          .split('\n')
          .filter((l) => l.includes('规则核实') || l.includes('Verified by rules'));
        expect(ruleLines.length).toBeGreaterThan(0);
        for (const line of ruleLines) expect(page).toContain(line);
      }
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
    });
  },
);

it.each(['zh', 'en'])(
  'UI-05: %s showing, opening and re-rendering advice never requests inference',
  async (language) => {
    await withFeedback(language, async (browser) => {
      await browser.ev(`performance.clearResourceTimings()`);
      for (const name of Object.keys(scenarios)) {
        await showReport(browser, language, [scenarios[name](language)]);
        await browser.click('[data-model-advice] summary');
        await browser.ev('window.fixture.update()');
        await browser.click('[data-model-advice] summary');
      }
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
      expect(
        await browser.ev(
          `performance.getEntriesByType('resource').filter((e) => ['fetch', 'xmlhttprequest', 'beacon'].includes(e.initiatorType)).map((e) => e.name)`,
        ),
      ).toEqual([]);
    });
  },
);

const strip = ({ units, aggregation, ...rest }) => rest;
it.each(['zh', 'en'])(
  'UI-06: %s range and coverage lines are the same with or without the new advice fields',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const lines = async () => ({
        range: await visible(browser, '[data-score-range]'),
        coverage: await visible(browser, '[data-feedback-coverage]'),
        weights: await browser.text('[data-criterion-weight]'),
      });
      await showReport(browser, language, []);
      const none = await lines();
      expect(none.range).toMatch(language === 'en' ? /^Rule-anchored part: / : /^规则已定标部分：/);
      // Synthetic results never count as model coverage, labelled or not.
      await showReport(browser, language, [scenarios.synthetic(language)]);
      expect(await lines()).toEqual(none);
      await showReport(browser, language, [strip(scenarios.synthetic(language))]);
      expect(await lines()).toEqual(none);
      // A completed external result counts as before 149; its sentences change nothing.
      await showReport(browser, language, [scenarios.external(language)]);
      const external = await lines();
      await showReport(browser, language, [strip(scenarios.external(language))]);
      expect(await lines()).toEqual(external);
      expect(external.range).toBe(none.range);
      expect(external.weights).toEqual(none.weights);
    });
  },
);

it.each(['zh', 'en'])(
  'UI-01: %s the support section names the recorded evaluation model, never a default',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const line = () => visible(browser, '[data-evaluation-model]');
      await showReport(browser, language, [scenarios.synthetic(language)]);
      expect(await line()).toBe(T(language, '评价模型：未接入', 'Evaluation model: not connected'));
      const judged = {
        ...recorded.reports[language].provenance,
        provider: 'openai_compatible',
        model: 'qa-loopback-judge',
        support_model: { provider: 'openai_compatible', model: 'qa-loopback-support' },
      };
      await browser.ev(
        `window.fixture.state.reports[0].provenance = ${JSON.stringify(judged)}; window.fixture.update();`,
      );
      expect(await line()).toBe(
        T(
          language,
          '评价模型：openai_compatible · qa-loopback-judge · 支持核验模型：openai_compatible · qa-loopback-support',
          'Evaluation model: openai_compatible · qa-loopback-judge · Support check model: openai_compatible · qa-loopback-support',
        ),
      );
      await browser.ev(
        `window.fixture.state.reports[0].provenance = null; window.fixture.update();`,
      );
      expect(await line()).toBe(T(language, '评价模型：未记录', 'Evaluation model: not recorded'));
    });
  },
);

it.each(['zh', 'en'])(
  'UI-01: %s names the model, its type, training data, weights stage and fusion members',
  async (language) => {
    await withFeedback(language, async (browser) => {
      const { fusion, encoder } = recorded.identities;
      const lines = () => browser.text('[data-model-identity] p');
      const quarter = {
        ...fusion,
        fusion: { ...fusion.fusion, alpha: 0.25, fusion_gain_observed: false },
        components: [
          { ...fusion.components[0], alpha: 0.75 },
          { ...fusion.components[1], alpha: 0.25 },
        ],
      };
      await showReport(browser, language, [
        { ...scenarios.synthetic(language), registration: quarter },
      ]);
      expect(await lines()).toEqual(
        language === 'en'
          ? [
              `Model: ${fusion.id}`,
              'Type: Probability fusion',
              `Revision: ${fusion.model_revision}`,
              'Training data: rolecraft-linear-mechanism-synthetic · G0 program-verified labels · dataset manifest dddddddddddd…',
              `Left member: ${fusion.components[0].id} (Linear model) · weight 0.75`,
              `Right member: ${fusion.components[1].id} (Linear model) · weight 0.25`,
              'Fusion alpha 0.25 · evidence threshold 0.5',
              'No fusion gain observed on dev',
            ]
          : [
              `模型：${fusion.id}`,
              '类型：概率融合',
              `版本：${fusion.model_revision}`,
              '训练数据：rolecraft-linear-mechanism-synthetic · G0 程序核验标签 · 数据清单 dddddddddddd…',
              `左分量：${fusion.components[0].id}（线性模型）· 权重 0.75`,
              `右分量：${fusion.components[1].id}（线性模型）· 权重 0.25`,
              '融合 alpha 0.25 · 证据阈值 0.5',
              'dev 上未观察到融合收益',
            ],
      );
      const pretrained = {
        ...encoder,
        weights_stage: 'pretrained_untrained_heads',
        dataset: { ...encoder.dataset, label_tiers: ['G2v'] },
      };
      await showReport(browser, language, [
        { ...scenarios.synthetic(language), registration: pretrained },
      ]);
      expect(await lines()).toEqual(
        language === 'en'
          ? [
              `Model: ${encoder.id}`,
              'Type: Encoder',
              `Revision: ${encoder.model_revision}`,
              'Training data: rolecraft-fixture-20261007-v2 · G2v model-reviewed labels · dataset manifest 5c8f0d5be05e…',
              'Weights: pretrained weights · classification heads untrained',
            ]
          : [
              `模型：${encoder.id}`,
              '类型：编码器',
              `版本：${encoder.model_revision}`,
              '训练数据：rolecraft-fixture-20261007-v2 · G2v 模型复核标签 · 数据清单 5c8f0d5be05e…',
              '权重阶段：预训练权重 · 分类头未训练',
            ],
      );
      const block = await browser.ev(`document.querySelector('[data-model-advice]').textContent`);
      expect(block).not.toMatch(/人工标签|human label/i);
      await showReport(browser, language, [scenarios.external(language)]);
      expect((await lines()).at(-1)).toBe(
        T(
          language,
          '外部候选；模型质量尚未验证。',
          'External candidate; model quality has not been validated.',
        ),
      );
      expect(await browser.ev('window.fixture.calls')).toEqual([]);
    });
  },
);

it.each(['zh', 'en'])(
  'UI-02: %s puts the sentence counts first and the work-level conclusion after, quieter',
  async (language) => {
    await withFeedback(language, async (browser) => {
      await showReport(browser, language, [scenarios.synthetic(language)]);
      expect(
        await browser.ev(
          `[...document.querySelector('[data-model-advice] summary').children].map((n) =>
            n.getAttributeNames().find((name) => name.startsWith('data-model-advice-')))`,
        ),
      ).toEqual([
        'data-model-advice-title',
        'data-model-advice-notice',
        'data-model-advice-counts',
        'data-model-advice-conclusion',
      ]);
      const colors = await browser.ev(`(() => {
        const rgb = (s) => getComputedStyle(document.querySelector(s)).color.match(/\\d+/g).slice(0, 3).map(Number);
        return { title: rgb('[data-model-advice-title]'), counts: rgb('[data-model-advice-counts]'), conclusion: rgb('[data-model-advice-conclusion]') };
      })()`);
      const sum = (c) => c[0] + c[1] + c[2];
      // Light theme: the counts read as strongly as the title; the conclusion is lighter.
      expect(colors.counts).toEqual(colors.title);
      expect(sum(colors.conclusion)).toBeGreaterThan(sum(colors.counts));
    });
  },
);
