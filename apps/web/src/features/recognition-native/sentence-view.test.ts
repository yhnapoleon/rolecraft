import { describe, expect, it } from 'vitest';
import type { RecognitionRecord } from './badge';
import { markNumber, sentenceLensView } from './sentence-view';

const records: RecognitionRecord[] = [
  {
    recognizer_id: 'relation-stack-v1',
    revision: 'abc',
    task: 'relation',
    outputs: {
      units: [
        {
          index: 0,
          quote: '首批开放给 80 人试点。',
          label: 'contradicted',
          confidence: 0.86,
          probabilities: { supported: 0.04, contradicted: 0.86, insufficient: 0.1 },
          evidence_ids: ['e-cap'],
          reason: 'late_fusion:0.4|exceeds_limit:80>30 person',
          decision: 'decide',
          expected_cost: 0.3,
        },
        {
          index: 1,
          quote: '人工兜底已经落实。',
          label: 'insufficient',
          confidence: 0.55,
          evidence_ids: [],
          reason: 'pair_aggregate',
          decision: 'defer',
          expected_cost: 0.7,
        },
      ],
    },
  },
  {
    recognizer_id: 'retrieval-c2',
    revision: 'rrf',
    task: 'retrieval',
    outputs: {
      per_sentence_top: [
        { index: 0, top: [{ rank: 1, evidence_id: 'e-cap', quote: '# 委托\n目前项目预留容量是 30 人。超出须申请。' }] },
      ],
    },
  },
  { recognizer_id: 'cost-decision-v1', revision: 'costs.json', task: 'decision', outputs: { costs: { defer: 0.5 } } },
];

describe('work sentences as data', () => {
  it('gives each sentence its relation, certainty, matched source, conflicting numbers and chain', () => {
    const view = sentenceLensView({ records, language: 'zh' });
    expect(view?.tally).toEqual({ s: 0, c: 1, u: 1 });
    expect(view?.categories.map((c) => c.text)).toEqual(['集成 · 混合', '混合', '统计决策 · 混合']);
    const [first, second] = view?.sentences ?? [];
    expect(first).toMatchObject({
      tone: 'contradicted',
      certain: true,
      toneLabel: '与材料矛盾',
      sure: 'high',
      shown: 'always',
      conflict: { value: '80', limit: '30', unit: 'person', unitLabel: '人' },
    });
    expect(first.parts).toEqual([{ text: '首批开放给 ' }, { text: '80', mark: 'num' }, { text: ' 人试点。' }]);
    expect(first.source).toMatchObject({
      title: '委托',
      version: null,
      quote: '目前项目预留容量是 30 人。',
      parts: [{ text: '目前项目预留容量是 ' }, { text: '30', mark: 'src' }, { text: ' 人。' }],
      relationLabel: '与你这句矛盾',
    });
    expect(first.srText).toBe('与材料矛盾，与《委托》矛盾');
    expect(first.chain.steps.map((step) => [step.step, step.category])).toEqual([
      ['retrieval', '混合'],
      ['relation', '集成 · 混合'],
      ['fusion', '集成 · 混合'],
      ['decision', '统计决策 · 混合'],
      ['arbiter', '统计决策 · 混合'],
    ]);
    expect(first.chain.steps[1]).toMatchObject({ result: '矛盾', resultTone: 'bad', cells: 4 });
    expect(first.chain.steps[2].note).toBe('数值限额规则参与融合（权重 α=0.4）：80 人超过材料里的上限 30 人');
    expect(second).toMatchObject({ tone: 'deferred', certain: false, sure: 'low', source: null, shown: null, conflict: null });
    expect(second.chain.steps[4]).toMatchObject({ result: '没有仲裁记录', muted: true });
  });

  it('marks the chain of a preview as before submission and keeps unknown steps honest', () => {
    const view = sentenceLensView({
      language: 'en',
      preview: {
        recognizer: 'relation-rule-v1@rule-fallback',
        fallback: true,
        units: [{ index: 0, quote: 'Hotel cap 500.', label: 'contradicted', confidence: 0.82, decision: 'decide', evidence: 'The cap is 400.' }],
      },
    });
    expect(view?.categories).toEqual([
      { text: 'Rule fallback', fallback: true },
      { text: 'Hybrid', fallback: false },
      { text: 'Statistical decision · Hybrid', fallback: false },
    ]);
    const steps = view?.sentences[0].chain.steps ?? [];
    expect(steps[1]).toMatchObject({ category: 'Rule fallback', method: 'Number-and-limit rule', fallback: true });
    expect(steps[2].note).toContain('nothing to fuse');
    expect(steps[4]).toMatchObject({ result: 'After you submit', muted: true });
    expect(view?.sentences[0].source?.quote).toBe('The cap is 400.');
    expect(JSON.stringify(view)).not.toContain('Deep learning');
  });

  it('has nothing to show without sentence labels', () => {
    expect(sentenceLensView({ language: 'zh', records: [] })).toBeNull();
    expect(sentenceLensView({ language: 'zh', preview: { units: [] } })).toBeNull();
  });

  it('marks a number only on number boundaries, with separators and currency allowed', () => {
    expect(markNumber('上限 1,000 元，另 10000 不算', '1000', 'src')).toEqual([
      { text: '上限 ' },
      { text: '1,000', mark: 'src' },
      { text: ' 元，另 10000 不算' },
    ]);
    expect(markNumber('Answer the hotel cap as CNY 500 a night.', '500', 'num')).toEqual([
      { text: 'Answer the hotel cap as ' },
      { text: 'CNY 500', mark: 'num' },
      { text: ' a night.' },
    ]);
    expect(markNumber('第 30 天，容量 300 人', '30', 'num')[1]).toEqual({ text: '30', mark: 'num' });
    expect(markNumber('容量 300 人', '30', 'num')).toEqual([{ text: '容量 300 人' }]);
    expect(markNumber('没有数字', undefined, 'num')).toEqual([{ text: '没有数字' }]);
  });
});
