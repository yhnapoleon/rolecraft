import { describe, expect, it } from 'vitest';
import { behaviorHtml, symbolLabel, type Behavior } from './view';

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
    expect(symbolLabel('ask:tech_lead:ask_limit', 'zh')).toBe('问技术负责人 · limit');
    expect(symbolLabel('read:policy', 'en')).toBe('read policy');
    expect(symbolLabel('submit', 'zh')).toBe('提交');
  });

  it('renders strategy, alignment and anomalies', () => {
    const html = behaviorHtml(data, 'zh');
    expect(html).toContain('未读先申请');
    expect(html).toContain('读 technical');
    expect(html).toContain('还没读技术材料就先申请了资源');
    expect(html).not.toContain('data-fallback');
  });

  it('marks the rule fallback and escapes recognizer text', () => {
    const html = behaviorHtml({ ...data, strategy: null, recognizer: 'behavior-v1@rule-fallback' }, 'en');
    expect(html).toContain('data-fallback');
    expect(html).toContain('trajectory recognizer not loaded');
  });
});
