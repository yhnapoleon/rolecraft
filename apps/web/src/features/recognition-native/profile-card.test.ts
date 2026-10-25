import { describe, expect, it } from 'vitest';
import type { RecognitionRecord } from './badge';
import { cardHtml, runMode, TASK_ROW } from './profile-card';
import { cardsHtml } from './signals';

const scope: RecognitionRecord = {
  recognizer_id: 'scope-mahalanobis-v1',
  revision: 'f05ba8',
  task: 'scope',
  label: 'in',
  score: 1.09,
  threshold: 1.32,
  outputs: { fit_key: 'pm_pilot/zh/scope_off' },
  fallback: false,
};
const drift: RecognitionRecord = {
  recognizer_id: 'drift-cosine-v1',
  revision: 'unhashed',
  task: 'drift',
  label: 'anomaly',
  score: 0.02,
  threshold: 0.14,
  outputs: { numeric_change: true, numbers_before: ['500'], numbers_after: ['400'] },
};
const ruleScope: RecognitionRecord = {
  recognizer_id: 'scope-mahalanobis-v1',
  revision: 'rule',
  task: 'scope',
  label: 'out',
  outputs: { rule: 'no_retrieval_hit' },
  fallback: true,
};
const dense: RecognitionRecord = {
  recognizer_id: 'retrieval-c2',
  revision: 'dense',
  task: 'retrieval',
  label: 'policy',
  outputs: { method: 'dense', top: [{ rank: 1, material_id: 'policy', quote: 'cap 500' }] },
};

describe('profile card', () => {
  it('draws the threshold point only from the call’s own score and threshold', () => {
    const html = cardHtml(scope, 'zh');
    expect(html).toContain('class="rc-axis"');
    expect(html).toContain('1.09');
    expect(html).toContain('1.32');
    expect(html).toContain('在范围内');
    expect(cardHtml(ruleScope, 'zh')).not.toContain('class="rc-axis"');
  });

  it('labels the run mode from the record, and the replay from the practice', () => {
    expect(runMode(scope)).toBe('real');
    expect(runMode(ruleScope)).toBe('fallback');
    expect(cardHtml(scope, 'en')).toContain('Real inference');
    const rule = cardHtml(ruleScope, 'en');
    expect(rule).toContain('Rule fallback');
    expect(rule).toContain('not this call');
    expect(cardHtml(scope, 'en', { replay: true })).toContain('Record replay');
    expect(cardHtml(scope, 'en')).not.toContain('Record replay');
  });

  it('says when the number rule, not the vector distance, caught a drift', () => {
    const html = cardHtml(drift, 'zh');
    expect(html).toContain('<s>500</s>');
    expect(html).toContain('<b>400</b>');
    expect(html).toContain('数字校验规则');
  });

  it('names the retrieval actually used and points to the system profile entry', () => {
    const html = cardHtml(dense, 'en', { materialName: () => 'Travel policy' });
    expect(html).toContain('e5 dense');
    expect(html).toContain('Travel policy');
    expect(html).toContain('RRF fusion is used by the relation chain');
    expect(html).toContain(`href="#/lab/${TASK_ROW.retrieval}"`);
  });

  it('escapes what comes from records', () => {
    expect(cardHtml({ ...scope, recognizer_id: '<img>' }, 'zh')).not.toContain('<img>');
  });

  it('chips open their own card, hidden until pressed', () => {
    const html = cardsHtml([scope, drift], 'zh', { context: 'test', lens: true, cards: {} });
    const ids = [...html.matchAll(/data-rc-card="(rc-card-\d+)"/g)].map((m) => m[1]);
    expect(ids).toHaveLength(2);
    for (const id of ids) expect(html).toContain(`id="${id}" hidden`);
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('马氏距离单类');
  });
});
