import { describe, expect, it } from 'vitest';
import {
  BEHAVIOR_PLACEMENT,
  behaviorHtml,
  behaviorView,
  phaseLabelFits,
  symbolLabel,
  type Behavior,
} from './view';

const data: Behavior = {
  sequence: [
    { seq: 1, symbol: 'read:brief', phase: '探索' },
    { seq: 1, symbol: 'ask:tech_lead:ask_limit', phase: '探索' },
    { seq: 2, symbol: 'request:capacity', phase: '决策' },
    { seq: 3, symbol: 'submit', phase: '决策' },
  ],
  strategy: { nearest: 'unread_request', distance: 0.42, top3: [] },
  alignment: { missing: ['read:technical'], extra: [], swapped: [] },
  phases: [
    { name: '探索', from_seq: 1, to_seq: 1 },
    { name: '决策', from_seq: 2, to_seq: 3 },
  ],
  anomalies: [{ rule: 'request_before_technical', score: 0.7, at_seq: 2 }],
  executor: { declared: 'human', predicted: null, confidence: null },
  recognizer: 'behavior-v1@2f91ef2c1348',
};

describe('behaviour view', () => {
  it('names symbols in both languages', () => {
    expect(symbolLabel('ask:tech_lead:ask_limit', 'zh')).toBe('向 Daniel 询问限制');
    expect(symbolLabel('read:policy', 'en')).toBe('Read a source');
    expect(symbolLabel('submit', 'zh')).toBe('提交');
  });

  it('renders strategy, alignment and anomalies', () => {
    const html = behaviorHtml(data, 'zh', { lens: true });
    expect(html).toContain('先申请再补资料');
    expect(html).toContain('读了一份资料');
    expect(html).toContain('request_before_technical');
    expect(html).not.toContain('data-fallback');
  });

  it('marks the rule fallback and escapes recognizer text', () => {
    const html = behaviorHtml(
      { ...data, strategy: null, recognizer: 'behavior-v1@rule-fallback' },
      'en',
      { lens: true },
    );
    expect(html).toContain('rule fallback');
    expect(html).toContain('No reference approach is available');
  });

  it('stays out of the learner’s default view, and away entirely when the layer is off', () => {
    expect(BEHAVIOR_PLACEMENT).toBe('default');
    expect(behaviorHtml(data, 'zh')).toContain('工作回放');
    expect(behaviorHtml(data, 'zh', { lens: false })).toContain('这次做过的事');
    expect(behaviorHtml({ enabled: false }, 'zh', { lens: true })).toContain('这次未生成工作回放');
  });

  it('states what was done in the lens, without scores, verdicts or material identifiers', () => {
    const html = behaviorHtml(data, 'zh', {
      lens: true,
      materialName: (id) => ({ brief: '经理委托', technical: '技术交接' })[id] ?? id,
    });
    expect(html).toContain('读《经理委托》');
    expect(html).toContain('选中的参考做法：先申请再补资料');
    expect(html).toContain('HMM');
    expect(html).not.toContain('值得复盘');
    expect(html).not.toContain('DTW 距离');
    expect(html.replace(/<template[\s\S]*?<\/template>/g, '').replace(/<svg[\s\S]*?<\/svg>/g, '')).not.toMatch(/\d\.\d/);
    expect(html).not.toContain('behavior-v1');
    expect(html).not.toContain('读 brief');
  });

  it('describes the section as data any renderer can draw', () => {
    const view = behaviorView(data, 'en', {
      lens: true,
      materialName: (id) => (id === 'brief' ? 'Brief: pilot' : id),
    });
    expect(view?.categories.map((c) => c.text)).toEqual([
      'Machine learning · Unsupervised · Intelligent sensing',
      'DTW alignment / HMM phases',
    ]);
    expect(view?.steps[0]).toBe('Read “Brief”');
    expect(view?.nearest).toBe('Selected reference approach: Request, then read sources');
    expect(view?.order).toEqual(['Requested resources before reading the technical material']);
    expect(behaviorView(data, 'en')?.title).toBe('Work review');
  });

  it('labels only the phases wide enough and keys every phase in a legend under the bar', () => {
    const symbols = (phase: string, n: number, from: number) =>
      Array.from({ length: n }, (_, i) => ({ seq: from + i, symbol: 'submit', phase }));
    const many: Behavior = {
      ...data,
      sequence: [
        ...symbols('explore', 12, 1),
        ...symbols('test', 1, 13),
        ...symbols('decide', 1, 14),
        ...symbols('adjust', 8, 15),
      ],
      phases: [
        { name: 'explore', from_seq: 1, to_seq: 12 },
        { name: 'test', from_seq: 13, to_seq: 13 },
        { name: 'decide', from_seq: 14, to_seq: 14 },
        { name: 'adjust', from_seq: 15, to_seq: 22 },
      ],
    };
    const view = behaviorView(many, 'en', { lens: true });
    expect(view?.phases.map((p) => [p.name, p.steps, p.style])).toEqual([
      ['Exploration', 12, 0],
      ['Testing', 1, 1],
      ['Decision', 1, 2],
      ['Revision', 8, 3],
    ]);
    expect(view?.legend).toEqual([
      { name: 'Exploration', style: 0 },
      { name: 'Testing', style: 1 },
      { name: 'Decision', style: 2 },
      { name: 'Revision', style: 3 },
    ]);
    // Twelve pixels are reserved for padding; actual font measurements are supplied by the DOM.
    expect(phaseLabelFits(113, 52)).toBe(true);
    expect(phaseLabelFits(44, 52)).toBe(false);
    expect(phaseLabelFits(64, 52)).toBe(true);
    expect(phaseLabelFits(63.9, 52)).toBe(false);
    const html = behaviorHtml(many, 'en', { lens: true });
    expect(html).toContain('aria-label="2. Testing"');
    expect(html).toContain('aria-label="1. Exploration"');
    expect(html).toContain('class="rc-phase-legend"');
    expect(html).toContain('data-from="12" data-to="12"');
    expect(html).toContain('aria-label="4. Revision"');
  });
});

it('keeps the chosen disclosure state when the same behavior is redrawn', () => {
  expect(behaviorHtml(data, 'en', { lens: true })).toContain(
    '<details class="rc-behavior__steps">',
  );
  expect(behaviorHtml(data, 'en', { lens: true, stepsOpen: true })).toContain(
    '<details class="rc-behavior__steps" open>',
  );
});

it('keeps equally close references and a missing reference honest', () => {
  const d = {
    ...data,
    strategy: {
      nearest: 'test_heavy',
      distance: 0.25,
      top3: [{ strategy: 'thorough', distance: 0.25 }],
    },
  };
  const h = behaviorHtml(d, 'en', { stepsOpen: true });
  expect(h).toContain('Equally close: Test-heavy, Read, ask, then test');
  expect(h).toContain('No reference approach is available');
  expect(h).not.toContain('point-by-point alignment path was computed');
});
it('uses action positions even when business sequence numbers repeat', () => {
  const h = behaviorHtml(data, 'en', { stepsOpen: true });
  expect(h).toContain('Read a source');
  expect(h).toContain('Asked Daniel');
  expect((h.match(/Record sequence 1/g) || []).length).toBe(2);
});

it('summarises repeated differences before phases and preserves the full reference', () => {
  const d = {
    ...data,
    alignment: {
      missing: ['test:normal', 'read:technical', 'test:normal'],
      extra: [],
      swapped: [],
    },
    strategy: {
      nearest: 'thorough',
      distance: 0.1,
      top3: [
        { strategy: 'test_heavy', distance: 0.2 },
        { strategy: 'test_heavy', distance: 0.3 },
      ],
      reference: {
        id: 'one',
        index: 0,
        strategy: 'thorough',
        sequence: ['test:normal', 'test:normal'],
      },
    },
  };
  const h = behaviorHtml(d, 'zh');
  expect(h).toContain('日常问题测试：本次 0 次，参考 2 次');
  expect(h.indexOf('<rc-phase-timeline>')).toBeLessThan(h.indexOf('日常问题测试：本次 0 次，参考 2 次'));
  expect(h).toContain('差异记录待核对');
  expect(h).toContain('<th>测试密集 · 参考 1</th>');
  expect(h).toContain('<th>测试密集 · 参考 2</th>');
  expect(h).toContain('测试密集 · 参考 1 · 0.2');
  expect(h).toContain('测试密集 · 参考 2 · 0.3');
  expect(h).toContain('查看参考做法与全部差异');
  expect(h).toContain('没有逐步对应记录');
});

const productOnly = (html: string) => html.replace(/<template[\s\S]*?<\/template>/g, '');
it.each(['zh', 'en'] as const)('uses explicit actual counts and keeps original duplicate sequence IDs technical in %s', language => {
  const sample: Behavior = {
    ...data, window: { from_seq: 1, to_seq: 3, events: 3, turns: 1 },
    sequence: [...data.sequence, { seq: 3, symbol: 'configure' }],
    alignment: { missing: ['test:normal', 'test:normal'], extra: ['configure'], swapped: [] },
    strategy: { nearest: 'thorough', distance: 0.1, top3: [], reference: {
      id: 'ref', index: 0, strategy: 'thorough', sequence: [...data.sequence.map(r => r.symbol), 'test:normal', 'test:normal'],
    } },
  };
  const html = behaviorHtml(sample, language, { stepsOpen: true });
  const product = productOnly(html);
  expect(product).toContain(language === 'zh' ? '日常问题测试：本次 0 次，参考 2 次' : 'Everyday-question tests: this record 0 times, reference 2 times');
  expect(product).toContain(language === 'zh' ? '配置：本次 1 次，参考 0 次' : 'Configured the pilot: this record 1 time, reference 0 times');
  expect(product).toContain(language === 'zh' ? '本次可见的 5 个动作，来自 3 条操作记录和 1 次提问' : '5 visible actions in this record, from 3 operation records and 1 question');
  expect(product).not.toMatch(/参考多|本次多|more in the reference|more in this record|configure|1 questions|1 times|记录序号|Record sequence|Read window/);
  expect((html.match(language === 'zh' ? /记录序号 1 ·/g : /Record sequence 1 ·/g) ?? []).length).toBe(2);
  expect(html).toContain('&quot;missing&quot;');
  expect(html).toContain('&quot;extra&quot;');
});
it('formats distance to three decimals without merging references or treating rounded values as ties', () => {
  const sample: Behavior = { ...data, strategy: {
    nearest: 'thorough', distance: 0.3076923076923077,
    top3: [{strategy:'thorough', distance:0.3076923076923077}, {strategy:'test_heavy',distance:0.3077}, {strategy:'test_heavy',distance:0.3078}],
  } };
  const html = behaviorHtml(sample, 'en');
  const table = html.match(/<table class="jc-table">[\s\S]*?<\/table>/)?.[0] ?? '';
  expect((table.match(/<td>0.308<\/td>/g) ?? []).length).toBe(3);
  expect(table).toContain('<th>Test-heavy · ref 1</th>');
  expect(table).toContain('<th>Test-heavy · ref 2</th>');
  expect(html).toContain('View full distance precision');
  expect(html).toContain('0.3076923076923077');
  expect(html).toContain('0.3077');
  expect(html).toContain('0.3078');
  expect(behaviorView(sample, 'en')?.nearest).toBe('Selected reference approach: Read, ask, then test');
  expect(behaviorView(sample, 'en')?.runnersUp).toContain('Test-heavy (2 references)');
});
it('does not invent reference counts from missing/extra when the reference is unavailable', () => {
  const html = productOnly(behaviorHtml(data, 'en'));
  expect(html).toContain('reference actions were not provided, so their count cannot be checked');
  expect(html).not.toContain('reference 1 time');
});
