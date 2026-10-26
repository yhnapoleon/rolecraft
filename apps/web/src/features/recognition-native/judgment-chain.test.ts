import { describe, it, expect } from 'vitest';
import { judgmentChainHtml, leadingProbability, recordedSentencePreview } from './judgment-chain';
import type { ChainUnit } from './chain';
const unit: ChainUnit = {
  index: 2,
  quote: 'Claim',
  label: 'supported',
  confidence: 0.51,
  decision: 'decide',
  expected_cost: 0.12,
  probabilities: { supported: 0.51, contradicted: 0.46, insufficient: 0.03 },
  branches: {
    encoder: { supported: 0.1, contradicted: 0.7, insufficient: 0.2 },
    stack: { supported: 0.1, contradicted: 0.85, insufficient: 0.05 },
    rule: { supported: 0.9, contradicted: 0.05, insufficient: 0.05 },
    rule_window: 6,
    alpha: 0.4,
  },
  top: [{ rank: 1, quote: 'Original source', bm25: 0.8, dense: 0.9 }],
};
describe('recorded judgment chain', () => {
  it('keeps encoder, stack, rule and fused probabilities separate', () => {
    const h = judgmentChainHtml(unit, { defer_cost: 0.2 }, 'en');
    for (const v of [
      '0.700',
      '0.850',
      '0.900',
      '0.510',
      'α = 0.4',
      'Original source',
      'Retrieval method not recorded',
    ])
      expect(h).toContain(v);
    expect(h).toContain('The stacked model favours contradicted');
    expect(h).not.toContain('RRF');
    expect(h).not.toMatch(/[\u4e00-\u9fff]/);
  });
  it('does not fabricate missing model or rule branches', () => {
    const h = judgmentChainHtml({ ...unit, branches: { rule: null } }, {}, 'zh');
    expect(h).not.toContain('data-step="encoder"');
    expect(h).not.toContain('data-step="stack"');
    expect(h).toContain('本句未经堆叠复核');
    expect(h).toContain('规则未介入');
    expect(h).toContain('代价记录不完整');
  });
  it('keeps the recorded defer action even at rounded cost ties', () => {
    const h = judgmentChainHtml(
      { ...unit, decision: 'defer', expected_cost: 0.2 },
      { defer_cost: 0.2 },
      'zh',
    );
    expect(h).toContain('先暂缓');
    expect(h).toContain('=');
  });
  it('escapes exact original passages', () => {
    const h = judgmentChainHtml({ ...unit, top: [{ quote: '<script>bad</script>' }] }, {}, 'en');
    expect(h).toContain('&lt;script&gt;');
    expect(h).not.toContain('<script>');
  });
  it('does not invent a winning label for tied or invalid probabilities', () => {
    expect(leadingProbability({ supported: 0.5, contradicted: 0.5 })?.labels).toEqual([
      'supported',
      'contradicted',
    ]);
    expect(leadingProbability({ supported: NaN, contradicted: 1.1 })).toBeNull();
  });
  it('joins saved feedback hits by sentence index, not list position', () => {
    const p = recordedSentencePreview([
      { task: 'relation', recognizer_id: 'stack', revision: 'a', outputs: { units: [unit] } },
      {
        task: 'retrieval',
        recognizer_id: 'c2',
        revision: 'rrf',
        outputs: {
          per_sentence_top: [
            { index: 9, top: [{ quote: 'Wrong sentence' }] },
            { index: 2, top: [{ quote: 'Exact hit' }] },
          ],
        },
      },
      {
        task: 'decision',
        recognizer_id: 'cost',
        revision: 'a',
        outputs: { costs: { defer: 0.2 } },
      },
    ]);
    expect(p?.units?.[0].top?.[0].quote).toBe('Exact hit');
    expect(p?.defer_cost).toBe(0.2);
    expect(p?.units?.[0].retrieval_method).toBeUndefined();
    expect(recordedSentencePreview([])).toBeNull();
  });
});
