import { describe, expect, it } from 'vitest';
import { asFake, fakeDocument, type FakeElement } from '../results-native/fake-dom';
import { feedbackCoverageText } from './coverage';
import type { Report, ReviewRecord } from './index';
import { FEEDBACK_COPY } from './localization';
import {
  declaredPurpose,
  feedbackCounts,
  feedbackShortResult,
  laterPurpose,
  PURPOSE_CHOICES,
  purposeChoiceOf,
  purposeUnknown,
  reviewedAs,
} from './short-summary';

const ref = (kind: string, id: string, version = 1) => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
});
const CRITERIA = [
  'R1.target',
  'R1.metrics',
  'R2.support',
  'R2.unknowns',
  'R2.failure_analysis',
  'R3.capacity',
  'R3.resources',
  'R4.functional_tests',
  'R4.staleness_test',
  'R5.impact',
  'R5.adjustment',
  'R6.consistency',
  'R6.operations',
  'R6.alternatives',
];
type Item = Report['items'][number];
const unknownPurpose = (criterion: string): Item => ({
  criterion,
  label: 'INSUFFICIENT',
  applicability: 'undetermined',
  source: 'pending',
  explanation: '作品用途未明确，本项责任待确认。',
  citations: [],
});
const review = (id: string, purpose: string): ReviewRecord => ({
  id,
  version: 1,
  session_id: 's',
  subjects: [ref('product', 'note')],
  purpose,
  question: '',
  decision: null,
  followup_of: [],
});
const report = (items: Item[], subject = ref('review', 'r1')): Report => ({
  id: 'feedback-1',
  version: 1,
  subject,
  items,
  rule_items: items,
  verified_facts: [
    { status: 'partial', summary: ['记录显示，你已经向同事提问。'], references: [] },
  ],
  business_response: '当前没有可核验的业务决定记录。',
  next_options: [],
});
const render = (input: Partial<Parameters<typeof feedbackShortResult>[1]> & { report: Report }) => {
  const doc = fakeDocument();
  const semantic = doc.createElement('section');
  semantic.textContent = 'model';
  const detail = doc.createElement('section');
  const calls: string[] = [];
  const view = feedbackShortResult(doc, {
    language: 'zh',
    semantic,
    body: [detail],
    open: false,
    onToggle: () => {},
    ...input,
  });
  return { root: asFake(view.element), view, calls, semantic, detail };
};
const statuses = (root: FakeElement) => root.byTag('li').map((n) => n.textContent);

describe('D6: purpose-first review feedback', () => {
  const items = CRITERIA.map(unknownPurpose);

  it('replaces 14 identical rows with one purpose question and a folded list', () => {
    const chosen: string[] = [];
    const { root, view, semantic, detail } = render({
      report: report(items),
      review: review('r1', 'undetermined'),
      reviews: [review('r1', 'undetermined')],
      prompt: {
        name: 'purpose-feedback-1:1',
        disabled: false,
        select: () => {},
        submit: (purpose) => chosen.push(purpose),
      },
    });
    expect(statuses(root)).toEqual(['事实记录部分核实', '规则核实 0 项', '待确认适用 14 项']);
    expect(asFake(view.lead).textContent).toBe(
      '作品用途未明确，14 项责任都待确认。先说明这份作品现在用来做什么。',
    );
    expect(asFake(view.summary).textContent).toBe('展开 14 项');
    expect(asFake(view.details).open).toBe(false);
    expect(asFake(view.details).children).toContain(detail);
    expect(root.children).toContain(semantic);
    const prompt = root.byTag('fieldset')[0];
    const radios = prompt.byTag('input');
    expect(radios.map((r) => r.value)).toEqual([...PURPOSE_CHOICES]);
    expect(prompt.byTag('label').map((l) => l.textContent)).toEqual([
      '探索笔记',
      '方案比较',
      '测试计划',
      '试点决定',
      '结果报告',
    ]);
    const submit = prompt.byTag('button')[0];
    expect(submit.disabled).toBe(true);
    submit.click();
    expect(chosen).toEqual([]);
    radios[2].dispatch('change');
    expect(submit.disabled).toBe(false);
    submit.click();
    expect(chosen).toEqual(['test_plan']);
  });

  it('asks nothing when the purpose was recognised or the review cannot be requested', () => {
    expect(purposeUnknown(report(items), review('r1', 'exploration'))).toBe(false);
    expect(purposeUnknown(report(items, ref('submission', 's1')), undefined)).toBe(false);
    const { root } = render({ report: report(items), review: review('r1', 'undetermined') });
    expect(root.byTag('fieldset')).toHaveLength(0);
  });

  it('P2-3: an answered question becomes one line naming the purpose', () => {
    const reviews = [review('r1', 'undetermined'), review('r2', 'test_plan')];
    expect(laterPurpose(reviews[0], reviews)).toBe('test_plan');
    const { root, view } = render({
      report: report(items),
      review: reviews[0],
      reviews,
      prompt: { name: 'p', disabled: false, select: () => {}, submit: () => {} },
    });
    expect(root.byTag('fieldset')).toHaveLength(0);
    expect(asFake(view.lead).textContent).toBe('已按「测试计划」重新评审，新的反馈另列。');
    expect(root.byClass('short-result__lead')).toHaveLength(1);
    expect(root.textContent).not.toContain('先说明这份作品现在用来做什么');
    expect(asFake(view.summary).textContent).toBe('展开 14 项');
    expect(reviewedAs(reviews[1], 'zh')).toBe('按「测试计划」评审');
    expect(reviewedAs(reviews[1], 'en')).toBe('Reviewed as “Test plan”');
    expect(reviewedAs(reviews[0], 'zh')).toBeUndefined();
  });

  it('P2-2: starts from the purpose the work already declares, still editable', () => {
    const products = [
      {
        session_id: 's',
        product_id: 'note',
        version: 1,
        title: 'Note',
        removed_at: null,
        author: { kind: 'human', id: 'learner' },
        purpose: 'exploration',
      },
    ] as Parameters<typeof declaredPurpose>[1];
    expect(declaredPurpose([ref('product', 'note')], products)).toBe('exploration');
    expect(declaredPurpose([ref('product', 'note', 2)], products)).toBeUndefined();
    const chosen: string[] = [];
    const { root } = render({
      report: report(items),
      review: review('r1', 'undetermined'),
      reviews: [review('r1', 'undetermined')],
      prompt: {
        name: 'p',
        selected: declaredPurpose([ref('product', 'note')], products),
        disabled: false,
        select: () => {},
        submit: (purpose) => chosen.push(purpose),
      },
    });
    const radios = root.byTag('fieldset')[0].byTag('input');
    expect(radios.filter((r) => r.checked).map((r) => r.value)).toEqual(['exploration']);
    const submit = root.byTag('fieldset')[0].byTag('button')[0];
    expect(submit.disabled).toBe(false);
    radios[3].dispatch('change');
    submit.click();
    expect(chosen).toEqual(['commitment']);
  });

  it.each([
    ['exploration', 'exploration'],
    ['freeform', 'exploration'],
    ['自由作品', 'exploration'],
    ['测试计划', 'test_plan'],
    ['plan', 'test_plan'],
    ['Pilot decision', 'commitment'],
    ['  result  ', 'result'],
    ['我的想法', undefined],
    ['', undefined],
  ])('maps stored or typed purpose %s', (value, expected) => {
    expect(purposeChoiceOf(value)).toBe(expected);
  });
});

describe('short submission feedback', () => {
  const mixed: Item[] = [
    {
      ...unknownPurpose('R1.target'),
      applicability: 'applicable',
      source: 'verified_rule',
      label: 'MET',
    },
    { ...unknownPurpose('R2.support'), applicability: 'applicable' },
    { ...unknownPurpose('R3.capacity'), applicability: 'not_applicable', label: 'NOT_APPLICABLE' },
  ];
  it.each([
    ['zh', ['事实记录部分核实', '规则核实 1 项', '待核验 1 项', '本次不适用 1 项'], '展开 3 项'],
    [
      'en',
      [
        'Fact records partly verified',
        'Verified by rules: 1',
        'Pending verification: 1',
        'Not applicable this time: 1',
      ],
      'Show all 3 items',
    ],
  ] as const)('counts without scoring (%s)', (language, expected, label) => {
    const { root, view } = render({ report: report(mixed, ref('submission', 's1')), language });
    expect(statuses(root)).toEqual(expected);
    expect(view.lead).toBeUndefined();
    expect(asFake(view.summary).textContent).toBe(label);
    expect(root.textContent).not.toMatch(/\d+\s*\/\s*\d+|%|得分|总分|score/i);
    expect(feedbackCounts(mixed)).toEqual({
      total: 3,
      verified: 1,
      pending: 1,
      undetermined: 0,
      notApplicable: 1,
    });
  });

  it('shows one line per rule-checked item before the model advice', () => {
    const lines = fakeDocument().createElement('div');
    lines.textContent = 'rule lines';
    const { root, semantic } = render({ report: report(mixed, ref('submission', 's1')), lines });
    const at = (node: Node) => root.children.indexOf(asFake(node as HTMLElement));
    expect(at(lines)).toBeGreaterThan(-1);
    expect(at(lines)).toBeLessThan(at(semantic));
  });

  it.each([
    ['zh', '尚无适用项', '尚无适用项。', '查看记录与依据'],
    ['en', 'No applicable items yet', 'No applicable items yet.', 'Show records and evidence'],
  ] as const)(
    'D14: says plainly that nothing applies yet (%s)',
    (language, coverage, lead, label) => {
      const empty = report([], ref('submission', 's1'));
      expect(feedbackCoverageText(empty, [], language)).toBe(coverage);
      const { view } = render({ report: empty, language });
      expect(asFake(view.lead).textContent).toBe(lead);
      expect(asFake(view.summary).textContent).toBe(label);
    },
  );
});

it('keeps identical feedback copy keys in both languages', () => {
  expect(Object.keys(FEEDBACK_COPY.en).sort()).toEqual(Object.keys(FEEDBACK_COPY.zh).sort());
});
