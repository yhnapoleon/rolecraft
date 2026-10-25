import { describe, expect, it } from 'vitest';
import recorded from './model-advice.fixtures.json';
import { MODEL_ADVICE_COPY } from './model-advice-copy';
import {
  adviceCountsText,
  evaluationModelText,
  readRegisteredAdvice,
  registeredAdviceSummary,
} from './model-advice';

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('149 model advice copy', () => {
  it('UI-04: both languages carry the same keys and the same placeholders', () => {
    const zh = Object.keys(MODEL_ADVICE_COPY.zh).sort();
    expect(Object.keys(MODEL_ADVICE_COPY.en).sort()).toEqual(zh);
    for (const key of zh as (keyof typeof MODEL_ADVICE_COPY.zh)[]) {
      expect(MODEL_ADVICE_COPY.zh[key].length, key).toBeGreaterThan(0);
      expect(MODEL_ADVICE_COPY.en[key].length, key).toBeGreaterThan(0);
      expect(placeholders(MODEL_ADVICE_COPY.en[key]), key).toEqual(
        placeholders(MODEL_ADVICE_COPY.zh[key]),
      );
    }
  });
  it('UI-04: English copy has no Chinese and the Chinese copy names the same states', () => {
    for (const text of Object.values(MODEL_ADVICE_COPY.en)) expect(text).not.toMatch(/[一-鿿]/u);
    expect(MODEL_ADVICE_COPY.zh.titleSynthetic).toBe('合成机制演示');
    expect(MODEL_ADVICE_COPY.zh.syntheticNotice).toBe('合成或未训练权重，不是模型判断，不计分。');
  });
});

type RawAdvice = Record<string, unknown> & {
  units: Record<string, unknown>[];
  aggregation: { policy: string; counts: Record<string, number> };
};
const recordedZh = () => structuredClone(recorded.advice.zh) as unknown as RawAdvice;
/** The recorded zh sentences: one supported, one contradicted, the rest abstained or failed,
 * with sentences skipped as too short and beyond the per-work budget. */
function mixed(): RawAdvice {
  const advice = recordedZh();
  const [supported, , contradicted, ...rest] = advice.units;
  const notJudged = (unit: Record<string, unknown>, status: string, reason: string) => ({
    ...unit,
    status,
    label: null,
    evidence_ids: [],
    citations: [],
    reason_code: reason,
  });
  advice.units = [
    supported,
    contradicted,
    notJudged(rest[0], 'abstained', 'unit_exceeds_encoder_limit'),
    notJudged(rest[1], 'abstained', 'unit_exceeds_encoder_limit'),
    notJudged(rest[2], 'abstained', 'no_candidate_evidence'),
    notJudged(advice.units[1], 'failed', 'model_timeout'),
  ];
  advice.aggregation.counts = {
    supported: 1,
    contradicted: 1,
    insufficient: 0,
    abstained: 3,
    failed: 1,
    skipped_short: 2,
    over_budget: 5,
  };
  return advice;
}
const read = (raw: unknown) => readRegisteredAdvice([raw], 'fixture') ?? [];

describe('149 sentence counts and states', () => {
  it('UI-01: the one-line result names every non-zero count in a fixed order', () => {
    const [advice] = read(mixed());
    expect(advice.status).toBe('synthetic_mechanism_only');
    expect(adviceCountsText(advice, 'zh')).toBe(
      '1 句与材料一致 · 1 句与材料矛盾 · 2 句太长，模型没有核查 · 1 句模型放弃判断 · 1 句没能判断 · 2 句太短，没有送模型 · 5 句超出句数上限，没有送模型',
    );
    expect(adviceCountsText(advice, 'en')).toBe(
      '1 matches the materials · 1 contradicts the materials · 2 were too long for the model to check · 1 the model declined to judge · 1 could not be judged · 2 were too short to send to the model · 5 were over the sentence limit',
    );
  });
  it('UI-01: the example short result reads as in the task', () => {
    const [advice] = read(recordedZh());
    expect(adviceCountsText(advice, 'zh')).toBe('1 句与材料一致 · 1 句与材料矛盾 · 4 句证据不足');
  });
  it('UI-07: states are named distinctly and the first match decides', () => {
    const [synthetic] = read(recorded.advice.zh);
    const failed = (code: string) => ({
      ...synthetic,
      status: 'failed' as const,
      label: null,
      evidence_ids: [],
      citations: [],
      error_code: code,
      units: undefined,
      aggregation: undefined,
    });
    const abstained = { ...failed('all_units_abstained'), status: 'unavailable' as const };
    const title = (advice: Parameters<typeof registeredAdviceSummary>[0]) =>
      registeredAdviceSummary(advice, 'zh', 'pending');
    expect(title([synthetic])).toBe('合成机制演示');
    expect(title([abstained, synthetic])).toBe('模型这次一句也没能判断');
    expect(title([failed('model_timeout'), abstained])).toBe('模型调用超时');
    expect(title([failed('model_timeout'), failed('model_load_failed')])).toBe('模型建议失败');
    expect(registeredAdviceSummary([failed('model_timeout')], 'en', 'pending')).toBe(
      'Model call timed out',
    );
  });
});

describe('149 evaluation model line', () => {
  it.each([
    [{ provider: 'not_configured', model: 'not_configured' }, '评价模型：未接入'],
    [{ provider: 'deepseek', model: 'deepseek-chat' }, '评价模型：deepseek · deepseek-chat'],
    [{ provider: 'local', model: 'not_recorded' }, '评价模型：未记录'],
    [{ provider: 42, model: 'x' }, '评价模型：未记录'],
    [null, '评价模型：未记录'],
    [undefined, '评价模型：未记录'],
  ])('UI-01: %j reads as %s', (provenance, text) => {
    expect(evaluationModelText(provenance, 'zh')).toBe(text);
  });
  it('UI-01: a support model is named only when it was recorded apart from the Judge', () => {
    expect(
      evaluationModelText(
        {
          provider: 'openai_compatible',
          model: 'qa-loopback-judge',
          support_model: { provider: 'openai_compatible', model: 'qa-loopback-support' },
        },
        'en',
      ),
    ).toBe(
      'Evaluation model: openai_compatible · qa-loopback-judge · Support check model: openai_compatible · qa-loopback-support',
    );
  });
});
