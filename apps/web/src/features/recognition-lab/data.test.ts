import { describe, expect, it } from 'vitest';
import { chainFor, createResultStore, createSessionStore } from './data';

describe('system profile data', () => {
  it('fetches each published result file once, however often the page draws', async () => {
    const calls: string[] = [];
    const store = createResultStore(async (name) => {
      calls.push(name);
      return { name };
    });
    const first = await store.load(['e1_stack', 'e11_transfer_public']);
    const second = await store.load(['e1_stack', 'e11_transfer_public']);
    expect(calls).toEqual(['e1_stack', 'e11_transfer_public']);
    expect(second).toEqual(first);
    expect(first.e11_transfer_public).toEqual({ name: 'e11_transfer_public' });
  });

  it('treats an unreadable result file as missing and does not retry it on redraw', async () => {
    let calls = 0;
    const store = createResultStore(async () => {
      calls += 1;
      throw new Error('offline');
    });
    expect((await store.load(['e15_nli_mix'])).e15_nli_mix).toBeNull();
    await store.load(['e15_nli_mix']);
    expect(calls).toBe(1);
  });

  it('reads this practice once per visit and again when the page is entered anew', async () => {
    let reads = 0;
    const loader = async () => {
      reads += 1;
      return { session_id: 's1', records: [], counts: {}, recognizers: [] };
    };
    const store = createSessionStore();
    await store.read('s1', loader, true);
    await store.read('s1', loader, false); // language switch or redraw
    expect(reads).toBe(1);
    await store.read('s1', loader, true); // left the page and came back
    expect(reads).toBe(2);
    expect(await store.read('s1', null, false)).toBeNull(); // no live practice
  });
});

const feedback = { kind: 'feedback', object_id: 'fb-2', version: 1 };
const unit = (index: number, label: string, decision = 'decide', contradicted = 0.1) => ({
  index,
  quote: `第 ${index + 1} 句`,
  label,
  confidence: 0.6,
  probabilities: { supported: 0.6, contradicted, insufficient: 0.3 },
  evidence_ids: label === 'insufficient' ? [] : ['e-1'],
  reason: 'pair_aggregate',
  decision,
  expected_cost: 0.4,
});
const practice = {
  session_id: 's1',
  counts: { scope: 4, reply_check: 2, behavior: 1 },
  recognizers: [],
  records: [
    {
      carrier: feedback,
      position: 0,
      record: {
        recognizer_id: 'xlm-r-pair-v1',
        revision: 'abc',
        task: 'relation',
        outputs: {
          candidates: 12,
          units: [
            unit(0, 'insufficient'),
            unit(1, 'supported'),
            unit(2, 'contradicted', 'defer', 0.7),
          ],
        },
      },
    },
    {
      carrier: feedback,
      position: 1,
      record: {
        recognizer_id: 'retrieval-c2',
        revision: 'rrf',
        task: 'retrieval',
        outputs: {
          per_sentence_top: [
            { index: 2, top: [{ rank: 1, quote: '# 通知\n上限 400 元。', bm25: 0.5, dense: 0.9 }] },
          ],
        },
      },
    },
    {
      carrier: feedback,
      position: 2,
      record: {
        recognizer_id: 'cost-decision-v1',
        revision: 'costs.json',
        task: 'decision',
        outputs: { costs: { defer: 0.5 } },
      },
    },
    {
      carrier: feedback,
      position: 3,
      record: {
        recognizer_id: 'arbiter-v1',
        revision: 'x',
        task: 'arbiter',
        outputs: {
          agreement: false,
          criterion: 'R2.support',
          judge_label: 'MET',
          recognizer_label: 'PARTIAL',
          final: 'PARTIAL',
        },
      },
    },
  ],
};

describe('the claim that walks the pipeline', () => {
  it('uses a marked example when this practice has no sentence-level records', () => {
    const zh = chainFor(null, 'zh');
    expect(zh.example).toBe(true);
    expect(zh.quote).toContain('400');
    expect(zh.units).toEqual([]);
    expect(chainFor(null, 'en').quote).toMatch(/CNY 400/);
    const empty = { ...practice, records: [] };
    expect(chainFor(empty, 'zh').example).toBe(true);
  });

  it('walks this practice’s most telling sentence: a contradiction sent to a person', () => {
    const chain = chainFor(practice, 'zh');
    expect(chain.example).toBe(false);
    expect(chain.index).toBe(2);
    expect(chain.total).toBe(3);
    expect(chain.candidates).toBe(12);
    expect(chain.label).toBe('contradicted');
    expect(chain.decision).toBe('defer');
    expect(chain.deferCost).toBe(0.5);
    expect(chain.top[0].quote).toBe('通知 · 上限 400 元。');
    expect(chain.arbiter).toMatchObject({ judge: 'MET', recognizer: 'PARTIAL', final: 'PARTIAL' });
    expect(chain.counts?.scope).toBe(4);
  });

  it('follows the sentence the reviewer picks', () => {
    const chain = chainFor(practice, 'zh', 1);
    expect(chain.index).toBe(1);
    expect(chain.label).toBe('supported');
    expect(chain.top).toEqual([]);
  });
});
