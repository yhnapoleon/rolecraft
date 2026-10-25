import { describe, expect, it } from 'vitest';
import type { RecognitionRecord } from './badge';
import { closestSentence, parseReason, previewChain, recognitionChain } from './chain';

const relation = (units: Record<string, unknown>[], extra: Partial<RecognitionRecord> = {}): RecognitionRecord => ({
  recognizer_id: 'xlm-r-pair-v1',
  revision: 'd12a5d8eb826',
  task: 'relation',
  label: 'PARTIAL',
  outputs: { criterion: null, units, counts: { supported: 1, contradicted: 1, insufficient: 1, deferred: 0 } },
  fallback: false,
  ...extra,
});
const units = [
  {
    index: 0,
    quote: '首批开放给 20 人。',
    label: 'insufficient',
    confidence: 0.95,
    probabilities: { supported: 0.02, contradicted: 0.03, insufficient: 0.95 },
    evidence_ids: [],
    reason: 'pair_aggregate',
    decision: 'decide',
    expected_cost: 0.03,
  },
  {
    index: 1,
    quote: '开发需要 3 人日。',
    label: 'supported',
    confidence: 0.81,
    probabilities: { supported: 0.81, contradicted: 0.04, insufficient: 0.15 },
    evidence_ids: ['e-hand'],
    reason: 'late_fusion:0.4|same_quantity:3 pday',
    decision: 'decide',
    expected_cost: 0.19,
  },
  {
    index: 2,
    quote: '可以开放给 80 人。',
    label: 'contradicted',
    confidence: 0.55,
    probabilities: { supported: 0.1, contradicted: 0.55, insufficient: 0.35 },
    evidence_ids: ['e-cap'],
    reason: 'late_fusion:0.4|exceeds_limit:80>60 person',
    decision: 'defer',
    expected_cost: 0.9,
  },
];
const retrieval: RecognitionRecord = {
  recognizer_id: 'retrieval-c2',
  revision: 'rrf',
  task: 'retrieval',
  outputs: {
    k: 5,
    per_sentence_top: [
      { index: 1, top: [{ rank: 1, evidence_id: 'e-hand', quote: '技术交接：当前交付需要 3 人日。', bm25: 0.4, dense: 0.9 }] },
      {
        index: 2,
        top: [
          { rank: 1, evidence_id: 'e-brief', quote: '经理委托：试点首批 20 人。', bm25: 0.2, dense: 0.8 },
          { rank: 2, evidence_id: 'e-cap', quote: '资源审批规则。可审批上限为 60 人。超出须重新申请。', bm25: 0.3, dense: 0.7 },
        ],
      },
    ],
  },
};
const decision: RecognitionRecord = {
  recognizer_id: 'cost-decision-v1',
  revision: 'costs.json',
  task: 'decision',
  outputs: { deferred: 1, costs: { defer: 0.5 } },
};
const arbiter: RecognitionRecord = {
  recognizer_id: 'arbiter-v1',
  revision: 'r',
  task: 'arbiter',
  label: 'judge_undecided',
  outputs: { criterion: 'R2.support', agreement: false, judge_label: 'INSUFFICIENT', recognizer_label: 'PARTIAL', final: 'INSUFFICIENT' },
};

describe('recognition chain', () => {
  it('collects every step one sentence went through', () => {
    const chain = recognitionChain([relation(units), retrieval, decision, arbiter], 2);
    expect(chain?.unit?.quote).toBe('可以开放给 80 人。');
    expect(chain?.retrieval.map((hit) => hit.evidenceId)).toEqual(['e-brief', 'e-cap']);
    expect(chain?.relation).toEqual({ recognizerId: 'xlm-r-pair-v1', revision: 'd12a5d8eb826', fallback: false });
    expect(chain?.fusion).toEqual({
      kind: 'late_fusion',
      alpha: 0.4,
      rule: { kind: 'exceeds_limit', value: '80', limit: '60', unit: 'person' },
    });
    expect(chain?.decision).toEqual({ action: 'defer', expectedCost: 0.9, deferCost: 0.5 });
    expect(chain?.arbiter).toEqual({
      outcome: 'undecided',
      judge: 'INSUFFICIENT',
      recognizer: 'PARTIAL',
      final: 'INSUFFICIENT',
    });
    // The matched material sentence: the candidate the relation step cited, cut to its sentence.
    expect(chain?.evidence).toBe('可审批上限为 60 人。');
  });

  it('starts from the first sentence and takes the latest relation record', () => {
    const older = relation([{ ...units[0], quote: '旧版第一句。' }]);
    const chain = recognitionChain([older, relation(units)], -1);
    expect(chain?.unit?.quote).toBe('首批开放给 20 人。');
    expect(chain?.units).toHaveLength(3);
    expect(chain?.fusion).toEqual({ kind: 'model_only' });
    expect(chain?.arbiter).toBeNull();
    expect(chain?.evidence).toBeNull();
  });

  it('has nothing to show without sentence-level relation records', () => {
    expect(recognitionChain([retrieval, decision], 0)).toBeNull();
    expect(recognitionChain([{ ...relation(units), outputs: { mode: 'support_check' } }], 0)).toBeNull();
  });

  it('reads what the fusion step did from the recorded reason', () => {
    expect(parseReason('late_fusion:0.4|same_quantity:3 pday')).toEqual({
      kind: 'late_fusion',
      alpha: 0.4,
      rule: { kind: 'same_quantity', value: '3', unit: 'pday' },
    });
    expect(parseReason('late_fusion:0.4|no_comparable_evidence')).toEqual({
      kind: 'late_fusion',
      alpha: 0.4,
      rule: { kind: 'no_comparable_evidence' },
    });
    expect(parseReason('pair_aggregate')).toEqual({ kind: 'model_only' });
    expect(parseReason('different_quantity:500!=400 cny')).toEqual({
      kind: 'rule_only',
      rule: { kind: 'different_quantity', value: '500', limit: '400', unit: 'cny' },
    });
    expect(parseReason('lexical_overlap')).toEqual({ kind: 'rule_only', rule: { kind: 'lexical_overlap' } });
    expect(parseReason('')).toBeNull();
  });

  it('builds the shorter chain the pre-submission preview carries', () => {
    const chain = previewChain(
      {
        recognizer: 'relation-rule-v1@rule-fallback',
        fallback: true,
        units: [{ index: 4, quote: '住宿上限 500 元。', label: 'contradicted', confidence: 0.82, decision: 'decide', evidence: '上限为每晚 400 元。' }],
      },
      4,
    );
    expect(chain?.unit?.label).toBe('contradicted');
    expect(chain?.evidence).toBe('上限为每晚 400 元。');
    expect(chain?.retrieval).toEqual([]);
    expect(chain?.relation).toEqual({ recognizerId: 'relation-rule-v1', revision: 'rule-fallback', fallback: true });
    expect(chain?.fusion).toBeNull();
    expect(chain?.decision).toEqual({ action: 'decide', expectedCost: null, deferCost: null });
  });

  it('picks the material sentence sharing most with the claim', () => {
    expect(closestSentence('上限 60 人', '# 资源审批规则\n\n首批试点。可审批上限为 60 人。其他另议。')).toBe('可审批上限为 60 人。');
  });
});
