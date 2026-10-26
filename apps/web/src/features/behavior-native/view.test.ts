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
    expect(symbolLabel('ask:tech_lead:ask_limit', 'zh')).toBe('问 Daniel · 上限');
    expect(symbolLabel('read:policy', 'en')).toBe('read policy');
    expect(symbolLabel('submit', 'zh')).toBe('提交');
  });

  it('renders strategy, alignment and anomalies', () => {
    const html = behaviorHtml(data, 'zh', { lens: true });
    expect(html).toContain('未读先申请');
    expect(html).toContain('读 technical');
    expect(html).toContain('还没读技术材料就先申请了资源');
    expect(html).not.toContain('data-fallback');
  });

  it('marks the rule fallback and escapes recognizer text', () => {
    const html = behaviorHtml(
      { ...data, strategy: null, recognizer: 'behavior-v1@rule-fallback' },
      'en',
      { lens: true },
    );
    expect(html).toContain('data-fallback');
    expect(html).toContain('The behaviour model isn’t loaded');
  });

  it('stays out of the learner’s default view, and away entirely when the layer is off', () => {
    expect(BEHAVIOR_PLACEMENT).toBe('default');
    expect(behaviorHtml(data, 'zh')).toContain('回看工作过程');
    expect(behaviorHtml(data, 'zh', { lens: false })).toContain('本次可见动作');
    expect(behaviorHtml({ enabled: false }, 'zh', { lens: true })).toBe('');
  });

  it('states what was done in the lens, without scores, verdicts or material identifiers', () => {
    const html = behaviorHtml(data, 'zh', {
      lens: true,
      materialName: (id) => ({ brief: '经理委托', technical: '技术交接' })[id] ?? id,
    });
    expect(html).toContain('读《经理委托》');
    expect(html).toContain('最接近的工作方式：未读先申请');
    expect(html).toContain('机器学习 · 无监督 · 智能感知');
    expect(html).not.toContain('值得复盘');
    expect(html).not.toContain('DTW 距离');
    expect(html).not.toMatch(/\d\.\d/);
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
    expect(view?.steps[0]).toBe('read “Brief”');
    expect(view?.nearest).toBe('Closest way of working: Requests before reading');
    expect(view?.order).toEqual(['Requested resources before reading the technical material']);
    expect(behaviorView(data, 'en')?.title).toBe('Look back at your work');
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
    expect(html).toContain('data-from="13" data-to="13"');
    expect(html).not.toContain('…');
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
  expect(h).toContain('No reference trajectory was returned');
  expect(h).not.toContain('point-by-point alignment path was computed');
});
it('uses action positions even when business sequence numbers repeat', () => {
  const h = behaviorHtml(data, 'en', { stepsOpen: true });
  expect(h).toContain('read brief');
  expect(h).toContain('ask Daniel');
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
  expect(h).toContain('普通问题测试：参考多 2 次');
  expect(h.indexOf('普通问题测试：参考多 2 次')).toBeLessThan(h.indexOf('<rc-phase-timeline>'));
  expect(h).toContain('测试密集（2 条参考）');
  expect(h).toContain('展开完整参考与差异');
  expect(h).toContain('接口没有提供逐点对齐路径');
});
