import { describe, expect, it } from 'vitest';
import { signatureHtml, signatureText } from './signature';
import { retrievalHit, testAgeText, testMomentHtml, type MomentRun } from './test-moment';
const run = { id: 'r', question: 'cap?', answer: 'CNY 400', indexVersion: 2, policyVersion: 2, configVersion: 1, citations: [{ id: 'policy', title: 'Policy', version: 2 }], recognition: [{ task: 'retrieval', recognizer_id: 'retrieval-c2', revision: 'dense', fallback: false, outputs: { method: 'dense', top: [{ material_id: 'policy', rank: 2, quote: 'CNY 400 per night.' }] } }] } satisfies MomentRun;
describe('normal working moments', () => {
  it('signs actual rank and method, and never calls a fallback semantic inference', () => {
    const r = run.recognition[0];
    expect(signatureText(r, 'en')).toBe('Semantic retrieval match · rank 2');
    expect(signatureText({ ...r, fallback: true }, 'en')).toBe('Rule-based retrieval match · rank 2');
    expect(signatureText({ ...r, outputs: {} }, 'en')).toBe('Actual method not recorded');
  });
  it('attributes a numerical change to rules even with real embeddings', () => {
    const r = { task: 'drift', recognizer_id: 'drift-cosine-v1', revision: 'r', score: .02, threshold: .2, outputs: { numeric_change: true } };
    expect(signatureText(r, 'en')).toContain('Number-rule check');
  });
  it('does not present a merely old test as a model-detected change', () => {
    expect(testAgeText({ ...run, policyVersion: 1, indexVersion: 1 }, 2, 'en')).toContain('version check');
    expect(testAgeText(run, 2, 'en')).toBe('');
    expect(testMomentHtml(run, [run], 'en', x => x)).not.toContain('rc-moment-change');
  });
  it('only opens a passage with one exact cited version', () => {
    expect(retrievalHit(run)?.citation?.version).toBe(2);
    expect(retrievalHit({ ...run, citations: [...run.citations, { id: 'policy', version: 1 }] })?.citation).toBeUndefined();
    expect(retrievalHit({ ...run, citations: [] })?.citation).toBeUndefined();
  });
  it('does not invent a passage when a retrieval record has none', () => {
    expect(retrievalHit({ ...run, recognition: [] })).toBeNull();
    expect(testMomentHtml({ ...run, recognition: [] }, [], 'zh', x => x)).toContain('本次没有可用的识别记录');
  });
  it('retains raw passage and version, escaping untrusted content', () => {
    const malicious = { ...run, citations: [{ id: 'policy', title: '<img onerror=attack>', version: 2 }] };
    const html = testMomentHtml(malicious, [], 'en', x => x);
    expect(html).toContain('CNY 400 per night.');
    expect(html).toContain('v2');
    expect(html).toContain('&lt;img');
    expect(html).not.toContain('<img');
  });
  it('labels configuration differences against the recorded baseline', () => {
    const old = { ...run, id: 'old', configVersion: 0 };
    const fresh = { ...run, recognition: [{ task: 'drift', recognizer_id: 'drift', revision: 'r', outputs: { previous_test_id: 'old', numeric_change: true, numbers_before: ['500'], numbers_after: ['400'] } }] };
    const html = testMomentHtml(fresh, [old, fresh], 'en', x => x);
    expect(html).toContain('not index-only');
    expect(html).toContain('500');
    expect(html).toContain('400');
    expect(testMomentHtml(fresh, [fresh], 'en', x => x)).not.toContain('not index-only');
  });
  it('uses the existing accessible technical-card disclosure in both languages', () => {
    for (const lang of ['zh', 'en'] as const) {
      const html = signatureHtml(run.recognition[0], lang);
      expect(html).toContain('data-rc-card=');
      expect(html).toContain('aria-expanded="false"');
      expect(html).toContain('class="rc-card-slot" hidden');
      if (lang === 'en') expect(signatureText(run.recognition[0], lang)).not.toMatch(/[\u4e00-\u9fff]/);
    }
  });
});
