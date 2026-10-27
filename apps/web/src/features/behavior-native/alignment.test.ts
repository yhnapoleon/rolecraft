import { describe, expect, it } from 'vitest';
import { alignmentHtml, behaviorHtml, referenceLabels, symbolLabel, type Behavior } from './view';
import { methodsHtml } from '../recognition-native/record-inspector';

const base: Behavior = {
  sequence: [
    { seq: 1, symbol: 'read:brief', phase: '探索' },
    { seq: 2, symbol: 'read:policy', phase: '探索' },
    { seq: 3, symbol: 'test:normal', phase: '测试' },
    { seq: 4, symbol: 'submit', phase: '决策' },
  ],
  strategy: {
    nearest: 'thorough',
    distance: 1.5,
    top3: [{ strategy: 'thorough', distance: 1.5 }],
    reference: {
      id: 'r1',
      index: 0,
      strategy: 'thorough',
      sequence: ['read:brief', 'read:technical', 'ask:tech_lead:ask_limit', 'submit'],
    },
    // 0 same, 0.5 same kind other object, 1 different; i=1 twice, then j=2 twice.
    path: [
      { i: 0, j: 0, cost: 0 },
      { i: 1, j: 1, cost: 0.5 },
      { i: 1, j: 2, cost: 1 },
      { i: 2, j: 2, cost: 1 },
      { i: 3, j: 3, cost: 0 },
    ],
  },
  alignment: { missing: [], extra: [], swapped: [] },
  phases: [
    { name: '探索', from_seq: 1, to_seq: 2 },
    { name: '测试', from_seq: 3, to_seq: 3 },
    { name: '决策', from_seq: 4, to_seq: 4 },
  ],
  anomalies: [],
  executor: { declared: 'human', predicted: null, confidence: null },
  recognizer: 'behavior-v1@2f91ef2c1348',
};
const strategy = base.strategy as NonNullable<Behavior['strategy']>;
const rows = (html: string) =>
  [...html.matchAll(/<li class="br-align-row"[^>]*>/g)].map((m) => m[0]);

describe('alignment path in the technical record', () => {
  it.each(['zh', 'en'] as const)(
    'draws one row per pair with cost in line style and words (%s)',
    (l) => {
      const html = alignmentHtml(base, l, (s) => symbolLabel(s, l));
      const say = (zh: string, en: string) => (l === 'zh' ? zh : en);
      expect(rows(html)).toEqual([
        '<li class="br-align-row" data-cost="0">',
        '<li class="br-align-row" data-cost="0.5">',
        '<li class="br-align-row" data-cost="1" data-repeat="reference">',
        '<li class="br-align-row" data-cost="1" data-repeat="own">',
        '<li class="br-align-row" data-cost="0">',
      ]);
      for (const word of [
        say('同一动作', 'Same action'),
        say('同类动作，对象不同', 'Same kind, different object'),
        say('不同', 'Different'),
        // dtw_path: a repeated own step means the reference did several things there.
        say('参考多做了', 'Reference did more'),
        say('你多做了', 'You did more'),
        say('5 对，其中 2 对动作不同', '5 pairs, 2 with different actions'),
      ])
        expect(html).toContain(word);
      // No inner scroll box: the list scrolls with the inspector.
      expect(html).not.toContain('tabindex');
      expect(html).not.toMatch(/animation|transition/);
      if (l === 'en') expect(html).not.toMatch(/[一-鿿]/);
    },
  );

  it('marks which side repeats so the reused step reads as the same one', () => {
    const html = alignmentHtml(base, 'en', (s) => symbolLabel(s, 'en'));
    expect(html.match(/data-again="true"/g)).toHaveLength(2);
  });

  it('keeps the old sentence without a path, and draws nothing that does not fit', () => {
    const { path: _drop, ...noPath } = strategy;
    const old = behaviorHtml({ ...base, strategy: noPath }, 'en');
    expect(old).toContain('not a step-by-step alignment');
    expect(old).not.toContain('br-align');
    expect(alignmentHtml({ ...base, strategy: noPath }, 'en', String)).toBe('');
    const outOfRange = { ...strategy, path: [{ i: 0, j: 9, cost: 0 }] };
    expect(alignmentHtml({ ...base, strategy: outOfRange }, 'en', String)).toContain(
      'does not match the action records',
    );
    const backwards = {
      ...strategy,
      path: [
        { i: 1, j: 1, cost: 0 },
        { i: 0, j: 0, cost: 0 },
      ],
    };
    expect(alignmentHtml({ ...base, strategy: backwards }, 'zh', String)).toContain('对不上');
  });

  it('puts the path only in the technical record; the product layer is unchanged', () => {
    const { path: _drop, ...noPath } = strategy;
    const withPath = behaviorHtml(base, 'zh');
    const without = behaviorHtml({ ...base, strategy: noPath }, 'zh');
    const product = (html: string) => html.split('<rc-record-entry')[0];
    expect(product(withPath)).toBe(product(without));
    expect(withPath.split('<rc-record-entry')[1]).toContain('br-align');
    expect(methodsHtml('en', 'behavior')).toContain('step-by-step match');
  });

  it('tells repeated reference names apart and keeps English punctuation half-width', () => {
    const top = [{ strategy: 'test_heavy' }, { strategy: 'thorough' }, { strategy: 'test_heavy' }];
    expect(referenceLabels(top, 'en')).toEqual(['Test-heavy · ref 1', 'Read, ask, then test', 'Test-heavy · ref 2']);
    expect(referenceLabels(top, 'zh')[2]).toMatch(/· 参考 2$/);
    expect(referenceLabels([{ strategy: 'thorough' }], 'en')).toEqual(['Read, ask, then test']);
    const record = behaviorHtml(base, 'en').split('<rc-record-entry')[1];
    expect(record).toContain('Declared execution source: ');
    expect(record).not.toContain('：');
  });
});
