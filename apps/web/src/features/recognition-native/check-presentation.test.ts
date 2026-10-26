import { describe, it, expect } from 'vitest';
import {
  checkPresentation,
  validDistribution,
  leadingProbability,
  businessSentenceState,
} from './check-presentation';
import { evidenceCheckHtml } from './evidence-check';
import { businessSentencesHtml } from './business-sentences';
import type { ChainUnit } from './chain';
const unit: ChainUnit = {
  index: 0,
  quote: 'Limit 800 CNY.',
  label: 'contradicted',
  decision: 'defer',
  confidence: 0.9,
  branches: {
    stack: { supported: 0.0456, contradicted: 0.0456, insufficient: 0.9088 },
    rule: { supported: 0.05, contradicted: 0.9, insufficient: 0.05 },
  },
  reason: 'late_fusion:0.4|exceeds_limit:800>500 cny',
};
describe('product check projection', () => {
  it('keeps backend deferral separate from disagreement and the winning relation', () => {
    const p = checkPresentation(unit, {}, 'en');
    expect(p.state).toBe('deferred');
    expect(p.agreement).toBe('disagree');
    expect(p.status).toBe('Needs your review');
  });
  it.each([
    {},
    { supported: 1 },
    { supported: 1, contradicted: 0, insufficient: NaN },
    { supported: 1.1, contradicted: 0, insufficient: -0.1 },
    { supported: 0.3, contradicted: 0.3, insufficient: 0.3 },
    { supported: 1, contradicted: 0, insufficient: 0, extra: 0 },
  ])('rejects incomplete or illegal distribution %j', (p) => {
    expect(validDistribution(p as Record<string, number>)).toBe(false);
    expect(leadingProbability(p as Record<string, number>)).toBeNull();
  });
  it('keeps raw ties and does not tie values merely because they round equally', () => {
    expect(
      leadingProbability({ supported: 0.5, contradicted: 0.5, insufficient: 0 })?.labels,
    ).toEqual(['supported', 'contradicted']);
    expect(
      leadingProbability({ supported: 0.50001, contradicted: 0.49999, insufficient: 0 })?.labels,
    ).toEqual(['supported']);
  });
  it('accepts a rounded complete distribution without normalising', () => {
    const p = { supported: 0.333, contradicted: 0.333, insufficient: 0.333 };
    expect(validDistribution(p)).toBe(true);
    expect(leadingProbability(p)?.value).toBe(0.333);
  });
  it('shows all relationship bands from actual records', () => {
    expect(
      checkPresentation(
        { ...unit, branches: { stack: { supported: 0.5, contradicted: 0.5, insufficient: 0 } } },
        {},
        'en',
      ).agreement,
    ).toBe('tie');
    expect(
      checkPresentation(
        { ...unit, branches: { stack: unit.branches?.rule, rule: unit.branches?.rule } },
        {},
        'en',
      ).agreement,
    ).toBe('agree');
    expect(
      checkPresentation(
        { ...unit, branches: { stack: unit.branches?.stack, rule: null } },
        {},
        'en',
      ).agreement,
    ).toBe('single');
    expect(checkPresentation({ ...unit, branches: {} }, {}, 'en').agreement).toBe('incomplete');
    expect(
      checkPresentation(unit, { fallback: true, recognizer: 'relation-v1@rule-fallback' }, 'en')
        .agreement,
    ).toBe('rule');
  });
  it.each(['', 'future-action'])(
    'does not infer a final decision from a valid label: %s',
    (decision) =>
      expect(businessSentenceState({ ...unit, label: 'supported', decision })).toBe('unknown'),
  );
  it('never uses the first candidate as selected evidence', () => {
    const h = evidenceCheckHtml(
      {
        ...unit,
        top: [
          { quote: 'First candidate', evidence_id: 'first' },
          { quote: 'Selected passage', evidence_id: 'chosen' },
        ],
        evidence_ids: ['chosen'],
      },
      {},
      'en',
    );
    expect(h.indexOf('Selected passage')).toBeLessThan(h.indexOf('First candidate'));
  });
  it('retains source mismatches as attached metadata instead of repairing them', () => {
    const h = evidenceCheckHtml(
      {
        ...unit,
        evidence: 'Exact wrong passage',
        source: { title: 'Unverified title', version: 1 },
      },
      {},
      'en',
    );
    expect(h).toContain('Exact wrong passage');
    expect(h).toContain('Source information attached to the record');
    expect(h).not.toContain('latest');
  });
  it('only translates known number-rule reasons and preserves quote characters', () => {
    expect(
      checkPresentation({ ...unit, reason: 'made_up:800>500 cny' }, {}, 'en').comparison,
    ).toBeNull();
    const h = evidenceCheckHtml({ ...unit, evidence: 'Limit 500 CNY.' }, {}, 'en');
    expect(h).toContain('ec-number--claim');
    expect(h).toContain('ec-number--source');
    expect(h).toContain('>800</mark> CNY.');
  });
  it('deduplicates indices and starts with no disclosure open', () => {
    const h = businessSentencesHtml({ units: [unit, unit] }, 'en', 'saved');
    expect(h).toContain('Showing 1 claims');
    expect(h.match(/data-index=/g)).toHaveLength(1);
    expect(h).not.toContain(' open');
  });
});
