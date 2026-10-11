import { describe, expect, it } from 'vitest';
import type { _RuleScoreCriterion, _RuleScoreRange } from '../../contracts-v2';
import { asFake, fakeDocument } from '../results-native/fake-dom';
import type { Report } from './index';
import { FEEDBACK_COPY } from './localization';
import { criterionWeightText, formatPoints, rangeEnds, scoreRangeLine } from './score-range';
import { feedbackShortResult } from './short-summary';

type Item = Report['items'][number];
const ref = (kind: string, id: string) => ({ session_id: 's', kind, object_id: id, version: 1 });
const item = (criterion: string): Item => ({
  criterion,
  label: 'INSUFFICIENT',
  applicability: 'applicable',
  source: 'pending',
  explanation: '',
  citations: [],
});
const row = (
  criterion: string,
  weight: number,
  status: _RuleScoreCriterion['status'],
  lower?: number,
  upper?: number,
): _RuleScoreCriterion => ({ criterion, weight, status, lower, upper });
// The launch case a normal user reaches (capacity and resources met, no tests, no change event).
const MIXED: _RuleScoreRange = {
  rubric_revision: 'rubric-v2-final-20261009',
  rubric_sha256: 'aa0de4302ca42368a262dc516fd3d8dab83286dd10dff7350c35b0c3772321cd',
  denominator: 75,
  lower: 20,
  upper: 65,
  criteria: [
    row('R1.target', 5, 'pending'),
    row('R1.metrics', 5, 'pending'),
    row('R2.support', 25 / 3, 'pending'),
    row('R2.unknowns', 25 / 3, 'pending'),
    row('R2.failure_analysis', 25 / 3, 'pending'),
    row('R3.capacity', 10, 'anchored', 10, 10),
    row('R3.resources', 10, 'anchored', 10, 10),
    row('R4.functional_tests', 10, 'anchored', 0, 0),
    row('R4.staleness_test', 10, 'not_applicable'),
    row('R5.impact', 7.5, 'not_applicable'),
    row('R5.adjustment', 7.5, 'not_applicable'),
    row('R6.consistency', 10 / 3, 'pending'),
    row('R6.operations', 10 / 3, 'pending'),
    row('R6.alternatives', 10 / 3, 'pending'),
  ],
};
// Same record with one rule-bounded and one undetermined criterion (same range ends).
const VARIED: _RuleScoreRange = {
  ...MIXED,
  lower: 20 + 5 / 3,
  criteria: MIXED.criteria.map((entry) =>
    entry.criterion === 'R6.consistency'
      ? row('R6.consistency', 10 / 3, 'bounded', 5 / 3, 10 / 3)
      : entry.criterion === 'R6.operations'
        ? row('R6.operations', 10 / 3, 'undetermined')
        : entry,
  ),
};
const report = (extra: Partial<Report> = {}): Report => ({
  id: 'f1',
  version: 1,
  subject: ref('submission', 's1'),
  items: MIXED.criteria.map((entry) => item(entry.criterion)),
  rule_items: MIXED.criteria.map((entry) => item(entry.criterion)),
  business_response: '',
  next_options: [],
  ...extra,
});
const firstScreen = (value: Report, language: 'zh' | 'en') => {
  const doc = fakeDocument();
  const view = feedbackShortResult(doc, {
    report: value,
    language,
    semantic: doc.createElement('section'),
    body: [],
    open: false,
    onToggle: () => {},
  });
  const root = asFake(view.element);
  const notes = root.byClass('short-result__note').map((n) => n.textContent);
  const details = asFake(view.details);
  return { root, notes, details };
};

describe('decision 5: rule-anchored range on the feedback first screen', () => {
  it.each([
    [
      'zh',
      '规则已定标部分：20–65 分（适用项共 75 分，满分 100）',
      '模型建议不计分；待核验项使区间变宽。',
    ],
    [
      'en',
      'Rule-anchored part: 20–65 of 75 (applicable items; full rubric 100)',
      'Model advice is not scored; pending items widen the range.',
    ],
  ] as const)('shows the recorded range and its caveat (%s)', (language, range, note) => {
    const { root, notes } = firstScreen(report({ score_range: MIXED }), language);
    expect(notes).toEqual([range, note]);
    // The range sits in the first screen, before the fold; there is never a single total.
    expect(root.children.indexOf(root.byClass('short-result__note')[0])).toBeLessThan(
      root.children.indexOf(root.byTag('details')[0]),
    );
    expect(root.textContent).not.toMatch(/总分|单一|total|overall/i);
    const span = root.byClass('short-result__note')[0].children[0];
    expect(asFake(span as never).dataset.scoreRange).toBe('range');
  });

  it.each([
    ['zh', '规则已定标部分：100–100 分（满分 100）'],
    ['en', 'Rule-anchored part: 100–100 of 100'],
  ] as const)('all met gives a narrow range, never one number (%s)', (language, text) => {
    const narrow: _RuleScoreRange = {
      ...MIXED,
      denominator: 100,
      lower: 100,
      upper: 100,
      criteria: MIXED.criteria.map((entry) => ({
        ...entry,
        status: 'anchored',
        lower: entry.weight,
        upper: entry.weight,
      })),
    };
    expect(scoreRangeLine(report({ score_range: narrow }), language)?.text).toBe(text);
  });

  it.each([
    ['zh', '规则已定标部分：0–100 分（满分 100）'],
    ['en', 'Rule-anchored part: 0–100 of 100'],
  ] as const)('all pending spans the full width (%s)', (language, text) => {
    const pending: _RuleScoreRange = {
      ...MIXED,
      denominator: 100,
      lower: 0,
      upper: 100,
      criteria: MIXED.criteria.map((entry) => ({
        ...entry,
        status: 'pending',
        lower: null,
        upper: null,
      })),
    };
    expect(scoreRangeLine(report({ score_range: pending }), language)?.text).toBe(text);
  });

  it('rounds range ends outward and never shows a tighter range', () => {
    expect(formatPoints(25 / 3, 'down')).toBe('8.3');
    expect(formatPoints(25 / 3, 'up')).toBe('8.4');
    expect(formatPoints(37.5)).toBe('37.5');
    expect(formatPoints(10 / 3)).toBe('3.3');
    expect(formatPoints(19.999999999)).toBe('20');
    const odd = { ...MIXED, lower: 25 / 3, upper: 275 / 3, denominator: 275 / 3 };
    expect(scoreRangeLine(report({ score_range: odd }), 'zh')?.text).toBe(
      '规则已定标部分：8.3–91.7 分（适用项共 91.7 分，满分 100）',
    );
  });

  it.each([
    ['zh', '规则已定标部分：尚无适用项，不形成区间。'],
    ['en', 'Rule-anchored part: nothing applies yet, so there is no range.'],
  ] as const)('nothing applicable has no range (%s)', (language, text) => {
    const empty = { ...MIXED, denominator: 0, lower: null, upper: null };
    expect(scoreRangeLine(report({ score_range: empty }), language)).toEqual({
      kind: 'empty',
      text,
    });
  });

  it.each([
    ['zh', '分数区间：此评价标准版本不汇总。'],
    ['en', 'No range for this rubric version.'],
  ] as const)('candidate 2 and unrecorded versions show no range (%s)', (language, text) => {
    for (const provenance of [{ evaluation_version: 'feedback-rubric-v2-c2.1' }, null]) {
      const { notes, root } = firstScreen(report({ provenance }), language);
      expect(notes).toEqual([text]);
      expect(root.textContent).not.toMatch(/\d+\s*–\s*\d+/);
    }
  });

  it.each([
    ['zh', '分数区间：这份反馈生成时未记录。', '分数区间：当前权限下部分依据不可核验，暂不显示。'],
    [
      'en',
      'No range was recorded with this feedback.',
      'Range withheld: some evidence can’t be checked with your current access.',
    ],
  ] as const)(
    'says why a final-rubric record has no range (%s)',
    (language, unrecorded, partial) => {
      const final = { evaluation_version: 'feedback-rubric-v2-final.1' };
      expect(scoreRangeLine(report({ provenance: final }), language)?.text).toBe(unrecorded);
      expect(
        scoreRangeLine(report({ provenance: final, read_projection: 'partial' }), language)?.text,
      ).toBe(partial);
    },
  );

  it('shows nothing for a record without criteria', () => {
    expect(scoreRangeLine(report({ items: [], rule_items: [] }), 'zh')).toBeUndefined();
    expect(firstScreen(report({ items: [], rule_items: [] }), 'en').notes).toEqual([]);
  });
});

// The exact record of an exploration-note review in the normal entry (5 pending, 9 n/a).
const EXPLORATION_PENDING = [
  'R1.target',
  'R2.support',
  'R2.unknowns',
  'R2.failure_analysis',
  'R6.consistency',
];
const EXPLORATION: _RuleScoreRange = {
  ...MIXED,
  denominator: 33.333333333333336,
  lower: 0,
  upper: 33.333333333333336,
  criteria: MIXED.criteria.map((entry) =>
    row(
      entry.criterion,
      entry.weight,
      EXPLORATION_PENDING.includes(entry.criterion) ? 'pending' : 'not_applicable',
    ),
  ),
};
const TWELFTHS = Array.from({ length: 1201 }, (_, k) => k / 12);

describe('decision 5: shown bounds stay within the shown denominator and weight', () => {
  it.each([
    ['zh', '规则已定标部分：0–33.3 分（适用项共 33.3 分，满分 100）'],
    ['en', 'Rule-anchored part: 0–33.3 of 33.3 (applicable items; full rubric 100)'],
  ] as const)('an exploration-note review shows 0–33.3 of 33.3 (%s)', (language, text) => {
    const review = report({ subject: ref('review', 'r1'), score_range: EXPLORATION });
    expect(firstScreen(review, language).notes[0]).toBe(text);
  });

  it.each([
    [100 / 3, '0–33.3 分（适用项共 33.3 分'],
    [250 / 3, '0–83.3 分（适用项共 83.3 分'],
    [50 / 3, '0–16.7 分（适用项共 16.7 分'],
    [25 / 6, '0–4.2 分（适用项共 4.2 分'],
    [10 / 3, '0–3.3 分（适用项共 3.3 分'],
  ])('an upper end equal to the denominator %s is written as the denominator', (cap, text) => {
    const range = { ...MIXED, lower: 0, upper: cap, denominator: cap };
    expect(scoreRangeLine(report({ score_range: range }), 'zh')?.text).toContain(text);
  });

  it.each([
    [10 / 3, 5 / 3, '1.6–3.3'],
    [25 / 3, 25 / 6, '4.1–8.3'],
    [25 / 3, 0, '0–8.3'],
    [5, 2.5, '2.5–5'],
  ])('a rule-bounded item of weight %s never shows more than its weight', (weight, lower, ends) => {
    const range = {
      ...MIXED,
      criteria: [row('R6.consistency', weight, 'bounded', lower, weight)],
    };
    expect(criterionWeightText({ score_range: range }, 'R6.consistency', 'zh')).toContain(
      `规则限定 ${ends} 分`,
    );
    const partial = { ...MIXED, criteria: [row('R2.support', 25 / 3, 'bounded', 0, 25 / 6)] };
    expect(criterionWeightText({ score_range: partial }, 'R2.support', 'en')).toContain(
      'Rule-bounded: 0–4.2 points',
    );
  });

  it('over every reachable value: lower never tighter, upper never past the shown cap', () => {
    for (const cap of TWELFTHS.slice(1)) {
      const shownCap = Number(formatPoints(cap));
      for (let step = 0; step <= 24 && step / 12 <= cap + 1e-9; step++) {
        const upper = cap - step / 12;
        for (const lower of [0, upper / 2, upper]) {
          const shown = rangeEnds(lower, upper, cap);
          expect(Number(shown.lower)).toBeLessThanOrEqual(lower + 1e-9);
          expect(Number(shown.upper)).toBeLessThanOrEqual(shownCap);
          expect(Number(shown.lower)).toBeLessThanOrEqual(Number(shown.upper));
          // Rounded up unless that would pass the shown cap; equal to the cap reads as the cap.
          if (step === 0) expect(shown.upper).toBe(formatPoints(cap));
          else
            expect(Number(shown.upper) >= upper - 1e-9 || Number(shown.upper) === shownCap).toBe(
              true,
            );
        }
      }
    }
  });
});

describe('decision 5: per-criterion weight and anchoring', () => {
  it.each([
    [
      'zh',
      {
        'R3.capacity': '权重 10 分（满分 100）· 规则已定标：计 10 分',
        'R4.functional_tests': '权重 10 分（满分 100）· 规则已定标：计 0 分',
        'R6.consistency': '权重 3.3 分（满分 100）· 规则限定 1.6–3.3 分，其余待核验',
        'R2.support': '权重 8.3 分（满分 100）· 待核验：不计分，区间因此加宽 8.3 分',
        'R6.operations': '权重 3.3 分（满分 100）· 适用性待确认：不计分，区间因此加宽 3.3 分',
        'R5.impact': '权重 7.5 分（满分 100）· 本次不适用：不计入分母',
      },
    ],
    [
      'en',
      {
        'R3.capacity': 'Weight 10 of 100 · Rule-anchored: 10 points',
        'R4.functional_tests': 'Weight 10 of 100 · Rule-anchored: 0 points',
        'R6.consistency': 'Weight 3.3 of 100 · Rule-bounded: 1.6–3.3 points; the rest is pending',
        'R2.support': 'Weight 8.3 of 100 · Pending: not scored; widens the range by 8.3',
        'R6.operations':
          'Weight 3.3 of 100 · Applicability undetermined: not scored; widens the range by 3.3',
        'R5.impact': 'Weight 7.5 of 100 · Not applicable: left out of the denominator',
      },
    ],
  ] as const)(
    'names weight share and status, points only for rule results (%s)',
    (language, expected) => {
      for (const [criterion, text] of Object.entries(expected))
        expect(criterionWeightText({ score_range: VARIED }, criterion, language)).toBe(text);
      for (const criterion of ['R2.support', 'R6.operations', 'R5.impact'])
        expect(criterionWeightText({ score_range: VARIED }, criterion, language)).not.toMatch(
          /计 \d|: \d+ points/,
        );
    },
  );

  it('adds nothing when the record has no range', () => {
    expect(criterionWeightText({}, 'R3.capacity', 'zh')).toBeUndefined();
    expect(criterionWeightText({ score_range: MIXED }, 'R9.unknown', 'en')).toBeUndefined();
  });
});

it('keeps the range copy in both languages', () => {
  const keys = Object.keys(FEEDBACK_COPY.zh).filter((k) => /^(range|weight)/.test(k));
  expect(keys).toHaveLength(12);
  expect(Object.keys(FEEDBACK_COPY.en).sort()).toEqual(Object.keys(FEEDBACK_COPY.zh).sort());
});
