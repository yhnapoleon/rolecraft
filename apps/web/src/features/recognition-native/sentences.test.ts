import { describe, expect, it } from 'vitest';
import { asFake, fakeDocument, type FakeElement } from '../results-native/fake-dom';
import type { RecognitionRecord } from './badge';
import { previewQuiet, renderSentenceLens } from './sentences';

const records: RecognitionRecord[] = [
  {
    recognizer_id: 'xlm-r-pair-v1',
    revision: 'd12a5d8eb826',
    task: 'relation',
    outputs: {
      units: [
        {
          index: 0,
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
          index: 1,
          quote: '可以开放给 80 人。',
          label: 'contradicted',
          confidence: 0.9,
          probabilities: { supported: 0.05, contradicted: 0.9, insufficient: 0.05 },
          evidence_ids: ['e-cap'],
          reason: 'pair_aggregate',
          decision: 'decide',
          expected_cost: 0.15,
        },
        {
          index: 2,
          quote: '人工兜底已经落实。',
          label: 'insufficient',
          confidence: 0.96,
          probabilities: { supported: 0.02, contradicted: 0.02, insufficient: 0.96 },
          evidence_ids: [],
          reason: 'pair_aggregate',
          decision: 'defer',
          expected_cost: 0.6,
        },
      ],
      counts: { supported: 1, contradicted: 1, insufficient: 0, deferred: 1 },
    },
  },
  {
    recognizer_id: 'retrieval-c2',
    revision: 'rrf',
    task: 'retrieval',
    outputs: {
      per_sentence_top: [
        { index: 0, top: [{ rank: 1, evidence_id: 'e-hand', quote: '技术交接。开发需要 3 人日。', bm25: 0.4, dense: 0.9 }] },
        { index: 1, top: [{ rank: 1, evidence_id: 'e-cap', quote: '审批规则。可审批上限为 60 人。', bm25: 0.3, dense: 0.8 }] },
      ],
    },
  },
  { recognizer_id: 'cost-decision-v1', revision: 'costs.json', task: 'decision', outputs: { costs: { defer: 0.5 } } },
  {
    recognizer_id: 'arbiter-v1',
    revision: 'r',
    task: 'arbiter',
    label: 'judge_undecided',
    outputs: { agreement: false, judge_label: 'INSUFFICIENT', recognizer_label: 'PARTIAL', final: 'INSUFFICIENT' },
  },
];

const rows = (root: FakeElement) => root.byClass('rc-srow');
const visibleText = (node: FakeElement): string =>
  node.hidden ? '' : node.ownText + node.children.map((c) => (c instanceof Object && 'hidden' in c ? visibleText(c as FakeElement) : c.textContent)).join('');

describe('work sentences in the lens', () => {
  it('underlines each sentence by what the recognizers found', () => {
    const root = asFake(renderSentenceLens(fakeDocument(), { records, language: 'zh' }));
    const tones = rows(root).map((row) => row.dataset.tone);
    expect(tones).toEqual(['supported', 'contradicted', 'deferred']);
    expect(root.textContent).toContain('作品逐句');
    // Course categories of the block's signals.
    expect(root.textContent).toContain('监督 · 深度学习');
    expect(root.textContent).toContain('集成 · 混合');
    expect(root.textContent).toContain('混合');
  });

  it('ties a contradicting sentence to the material sentence it hit', () => {
    const root = asFake(renderSentenceLens(fakeDocument(), { records, language: 'zh' }));
    const contradicted = rows(root)[1];
    const match = contradicted.byClass('rc-s__match')[0];
    expect(match.textContent).toContain('可审批上限为 60 人。');
    expect(match.textContent).toContain('与你这句矛盾');
    expect(match.hidden).toBe(false);
    // A supported sentence's source waits until that sentence is opened.
    const supported = rows(root)[0].byClass('rc-s__match')[0];
    expect(supported.hidden).toBe(true);
    rows(root)[0].byClass('rc-s')[0].click();
    expect(supported.hidden).toBe(false);
    expect(supported.textContent).toContain('支持你这句');
  });

  it('opens a sentence’s recognition chain on demand, five steps with categories', () => {
    const root = asFake(renderSentenceLens(fakeDocument(), { records, language: 'zh' }));
    const row = rows(root)[1];
    const toggle = row.byClass('rc-s')[0];
    const chain = row.byClass('rc-chain')[0];
    expect(chain.hidden).toBe(true);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    toggle.click();
    expect(chain.hidden).toBe(false);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const steps = chain.byClass('rc-step');
    expect(steps.map((s) => s.dataset.step)).toEqual(['retrieval', 'relation', 'fusion', 'decision', 'arbiter']);
    expect(chain.textContent).toContain('规则没有可比的数值');
    expect(chain.textContent).toContain('保留评审结论');
    // One sentence open at a time.
    rows(root)[0].byClass('rc-s')[0].click();
    expect(chain.hidden).toBe(true);
    expect(chain.textContent).toContain('统计决策 · 混合');
    expect(visibleText(chain)).not.toMatch(/\d\.\d/);
  });

  it('keeps chains open across redraws when given the same memory', () => {
    const open = new Set<number>([2]);
    const root = asFake(renderSentenceLens(fakeDocument(), { records, language: 'en', open }));
    expect(rows(root)[2].byClass('rc-chain')[0].hidden).toBe(false);
    expect(root.textContent).toContain('Not known yet · to a person');
  });

  it('builds the same view from the pre-submission preview', () => {
    const root = asFake(
      renderSentenceLens(fakeDocument(), {
        preview: {
          recognizer: 'relation-rule-v1@rule-fallback',
          fallback: true,
          counts: { supported: 0, contradicted: 1, insufficient: 1, deferred: 0 },
          units: [
            { index: 0, quote: '住宿上限 500 元。', label: 'contradicted', confidence: 0.82, decision: 'decide', evidence: '上限为每晚 400 元。' },
            { index: 1, quote: '第 3 天复核。', label: 'insufficient', confidence: 0.6, decision: 'decide', evidence: null },
          ],
        },
        language: 'zh',
      }),
    );
    expect(rows(root).map((row) => row.dataset.tone)).toEqual(['contradicted', 'insufficient']);
    expect(rows(root)[0].byClass('rc-s__match')[0].textContent).toContain('上限为每晚 400 元。');
    expect(rows(root)[0].byClass('rc-num')).toHaveLength(0);
    expect(root.textContent).toContain('规则回退');
    expect(root.textContent).not.toContain('rule-fallback');
  });

  it('says the preview in one quiet line with the lens closed', () => {
    expect(
      previewQuiet({ counts: { supported: 2, contradicted: 1, insufficient: 6, deferred: 1 }, units: new Array(10).fill(null) }, 'zh'),
    ).toBe('与材料一致 2/10 句 · 1 句与材料矛盾');
    expect(previewQuiet({ counts: { supported: 3, contradicted: 0 }, units: new Array(6).fill(null) }, 'en')).toBe(
      '3/6 sentences match the materials',
    );
    expect(previewQuiet({ units: [] }, 'zh')).toBeNull();
  });

  it('keeps every step to five lines and puts the long parts in one Details under the chain', () => {
    const root = asFake(renderSentenceLens(fakeDocument(), { records, language: 'zh' }));
    rows(root)[1].byClass('rc-s')[0].click();
    const chain = rows(root)[1].byClass('rc-chain')[0];
    for (const step of chain.byClass('rc-step'))
      expect(step.children.map((c) => (c as FakeElement).className)).toEqual([
        'rc-step__name',
        'rc-step__result',
        'rc-cells',
        'rc-step__method',
        'rc-step__cat',
      ]);
    expect(chain.byClass('rc-chain__details')).toHaveLength(1);
    expect(chain.byClass('rc-chain__details')[0].textContent).toContain('详情');
    expect(chain.byClass('rc-step__result').map((e) => e.textContent)).toContain('现在就给你看');
  });

  it('can leave Replay to its host and drop its own paper frame', () => {
    const own = asFake(renderSentenceLens(fakeDocument(), { records, language: 'en' }));
    expect(own.byClass('rc-replay')).toHaveLength(1);
    expect(own.dataset.frame).toBe('paper');
    const hosted = asFake(renderSentenceLens(fakeDocument(), { records, language: 'en', replay: false, frame: 'flat' }));
    expect(hosted.byClass('rc-replay')).toHaveLength(0);
    expect(hosted.dataset.frame).toBe('flat');
  });
});
