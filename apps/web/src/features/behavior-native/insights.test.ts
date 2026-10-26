import { describe, it, expect } from 'vitest';
import { behaviorInsights } from './insights';
import { behaviorView, behaviorHtml, type Behavior } from './view';
const data: Behavior = {
  sequence: [
    { seq: 4, symbol: 'read:policy', phase: 'test' },
    { seq: 4, symbol: 'test:policy', phase: 'test' },
  ],
  strategy: {
    nearest: 'thorough',
    distance: 0.3,
    top3: [],
    reference: {
      id: 'r',
      index: 0,
      strategy: 'thorough',
      sequence: [
        'read:policy',
        'test:policy',
        'test:normal',
        'test:normal',
        'ask:business_lead:other',
        'ask:tech_lead:ask_limit',
      ],
    },
  },
  alignment: {
    missing: ['test:normal', 'test:normal', 'ask:business_lead:other', 'ask:tech_lead:ask_limit'],
    extra: [],
    swapped: [],
  },
  phases: [{ name: 'test', from_seq: 4, to_seq: 4 }],
  anomalies: [],
  executor: { declared: 'human', predicted: null, confidence: null },
  recognizer: 'behavior-v1@weights',
  window: { from_seq: 0, to_seq: 4 },
};
describe('record-based optional practice', () => {
  it('shows at most two relevant actions with actual counts', () => {
    const p = behaviorInsights(data, 'en');
    expect(p.valid).toBe(true);
    expect(p.suggestions.map((s) => s.action)).toEqual(['test', 'business']);
    expect(p.suggestions[0].basis).toContain('Reference: 2');
  });
  it('suppresses negative claims without a window', () =>
    expect(behaviorInsights({ ...data, window: undefined }, 'en').suggestions).toEqual([]));
  it('does not use inconsistent alignment counts', () => {
    const p = behaviorInsights(
      { ...data, alignment: { ...data.alignment, missing: ['test:normal'] } },
      'en',
    );
    expect(p.valid).toBe(false);
    expect(p.suggestions).toEqual([]);
  });
  it('preserves full reference and differences after limiting suggestions', () => {
    const h = behaviorHtml(data, 'en');
    expect(h).toContain('Explore the reference and all differences');
    expect(h).toContain('Asked Daniel');
    expect(h.match(/class="br-idea"/g)).toHaveLength(2);
  });
  it('gives a known anomaly priority and never displays unknown rule advice', () => {
    const p = behaviorInsights(
      {
        ...data,
        anomalies: [
          { rule: 'unknown', score: 0.5, at_seq: 1 },
          { rule: 'repeated_submit_same_config', score: 1, at_seq: 4 },
        ],
      },
      'en',
    );
    expect(p.suggestions[0].title).toBe('Review new evidence before resubmitting');
    expect(p.suggestions).toHaveLength(2);
  });
  it('has no invented suggestion without reference', () =>
    expect(behaviorInsights({ ...data, strategy: null }, 'en').suggestions).toEqual([]));
  it('keeps duplicate business sequence numbers as distinct array positions', () => {
    expect(behaviorView(data, 'en')?.phases[0]).toMatchObject({ from: 0, to: 1, steps: 2 });
    const h = behaviorHtml(data, 'en');
    expect(h).toContain('data-seq="0"');
    expect(h).toContain('data-seq="1"');
  });
  it('does not manufacture a phase for an invalid range', () =>
    expect(
      behaviorView({ ...data, phases: [{ name: 'test', from_seq: 9, to_seq: 10 }] }, 'en')?.phases,
    ).toEqual([]));
  it('retains an honest entry when recognition is disabled', () =>
    expect(behaviorHtml({ enabled: false }, 'en')).toContain('No work review was generated'));
});
