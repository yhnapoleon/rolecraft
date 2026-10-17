import { describe, expect, it } from 'vitest';
import { BADGE_COPY } from './badge-copy';
import { badgeHtml, describe as describeRecord, renderBadge, summaryText } from './badge';
import { asFake, fakeDocument } from '../results-native/fake-dom';

const scope = {
  recognizer_id: 'scope-mahalanobis-v1',
  revision: 'a1b2c3d4e5f6',
  task: 'scope',
  label: 'out',
  score: 4.1,
  threshold: 2.8,
  fallback: false,
};

describe('recognition badge', () => {
  it('keeps the two languages on the same keys', () => {
    expect(Object.keys(BADGE_COPY.en).sort()).toEqual(Object.keys(BADGE_COPY.zh).sort());
  });

  it('signs a scope result with its distance and threshold', () => {
    const { name, detail } = describeRecord(scope, 'zh');
    expect(name).toBe('范围检测');
    expect(detail).toContain('域外');
    expect(detail).toContain('4.10');
    expect(detail).toContain('2.80');
  });

  it('marks rule fallback in grey with a plain-language note', () => {
    const html = badgeHtml({ ...scope, revision: 'rule-fallback', fallback: true, score: null }, 'en');
    expect(html).toContain('data-fallback');
    expect(html).toContain('rule fallback');
  });

  it('escapes recognizer output in the string form', () => {
    const html = badgeHtml({ ...scope, task: 'intent', label: '<b>x</b>' }, 'zh');
    expect(html).not.toContain('<b>');
  });

  it('renders the DOM form with the same text', () => {
    const doc = fakeDocument();
    const span = asFake(renderBadge(doc, { ...scope, task: 'reply_check', outputs: { grounded: 2, ungrounded: 1, leaks: 0 } }, 'zh'));
    expect(span.textContent).toContain('2/3 句有依据');
    expect(span.textContent).toContain('无泄露');
  });

  it('summarises session counts', () => {
    expect(summaryText({ scope: 6, relation_units: 24, arbiter: 2 }, 'zh')).toBe(
      '本次会话：范围检测 6 次 · 关系判定 24 句 · 仲裁 2 项',
    );
    expect(summaryText({}, 'en')).toBe('No recognition records in this session yet');
  });
});
