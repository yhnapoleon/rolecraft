import { describe, expect, it } from 'vitest';
import { coverView, elapsedWords, phaseWords } from './result-cover';
import type { FeedbackNativeState, Report } from './index';

const ref = (kind: string, id: string, version = 1) => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
});
type Line = [criterion: string, label: string, source: string, applicability?: string];
const item = ([criterion, label, source, applicability = 'applicable']: Line) => ({
  criterion,
  label,
  source,
  applicability: applicability as 'applicable',
  explanation: '',
  citations: [],
  rule_bound:
    source === 'verified_rule' && label !== 'INSUFFICIENT' && label !== 'NOT_APPLICABLE'
      ? { lower: label, upper: label }
      : null,
});
const report = (id: string, submission: string, lines: Line[]): Report =>
  ({
    id,
    version: 1,
    subject: ref('submission', submission),
    items: [],
    rule_items: lines.map(item),
    business_response: '',
    next_options: [],
    semantic_status: 'waiting_for_model',
  }) as unknown as Report;
const delivery = (id: string, decision: string, products = [ref('product', 'p', 2)]) => ({
  ref: ref('submission', id),
  products,
  decision,
});
const first = delivery('sub-1', 'launch');
const second = delivery('sub-2', 'launch_narrow');
const firstReport = report('f-1', 'sub-1', [
  ['R3.capacity', 'MET', 'verified_rule'],
  ['R4.functional_tests', 'NOT_MET', 'verified_rule'],
  ['R4.staleness_test', 'NOT_MET', 'verified_rule'],
  ['R2.support', 'INSUFFICIENT', 'pending'],
  ['R5.impact', 'NOT_APPLICABLE', 'verified_rule', 'not_applicable'],
]);
const state = (extra: Partial<FeedbackNativeState> = {}): FeedbackNativeState => ({
  status: 'submitted',
  busy: false,
  products: [
    {
      session_id: 's',
      product_id: 'p',
      version: 2,
      title: '试点决定草稿',
      purpose: 'commitment',
      author: { kind: 'human', id: 'learner' },
    } as FeedbackNativeState['products'][number],
  ],
  submission: first,
  submissions: [first],
  reports: [firstReport],
  references: {
    materialTitles: {},
    tests: {},
    deliveries: { 'sub-1': 1, 'sub-2': 2 },
    events: {},
    products: {},
  },
  submittedAt: { 'sub-1': new Date().toISOString() },
  ...extra,
});

/** The cover, which these deliveries always have. */
const cover = (s: FeedbackNativeState, language: 'zh' | 'en' = 'zh') => {
  const view = coverView(s, language);
  if (!view) throw new Error('no cover');
  return view;
};

describe('results cover of a delivery', () => {
  it('shows nothing before anything was delivered', () => {
    expect(coverView(state({ submission: null, submissions: [] }), 'zh')).toBeNull();
  });
  it('stamps the decision in words with its delivery number and attachments', () => {
    const view = cover(state(), 'zh');
    expect(view.decision).toBe('按方案推进');
    expect(view.delivery).toBe(1);
    expect(view.when).toMatch(/^\d{2}:\d{2}$/);
    expect(view.attachments.map((a) => a.line)).toEqual(['《试点决定草稿》 · 第 2 版 · 试点决定']);
  });
  it('names a delivered version by its work after a later version replaced it in the list', () => {
    const later = state({
      products: [
        {
          session_id: 's',
          product_id: 'p',
          version: 3,
          title: 'Pilot PRD',
          purpose: 'commitment',
          author: { kind: 'human', id: 'learner' },
        } as FeedbackNativeState['products'][number],
      ],
    });
    expect(cover(later, 'en').attachments[0].product.title).toBe('Pilot PRD');
    expect(cover(later, 'en').attachments[0].line).not.toContain('Untitled');
  });
  it('sorts what holds up, what is not known with its reason, and what is unmet', () => {
    const view = cover(state(), 'zh');
    expect(view.met.map((r) => r.name)).toEqual(['人数与容量']);
    expect(view.unknown.map((r) => [r.name, r.reason])).toEqual([
      ['判断的证据支持', '需要模型核验，暂未接入'],
    ]);
    // Unmet: a retest after a change is amber, an ordinary unmet item stays ink.
    expect(view.unmet.map((r) => [r.criterion, r.tone])).toEqual([
      ['R4.functional_tests', 'ink'],
      ['R4.staleness_test', 'warn'],
    ]);
    expect(view.compare).toBeNull();
  });
  it('says a rule found no evidence in the materials in plain words', () => {
    const own = report('f-1', 'sub-1', [['R2.unknowns', 'INSUFFICIENT', 'verified_rule']]);
    expect(cover(state({ reports: [own] }), 'en').unknown[0].reason).toBe(
      'No supporting evidence was found in the materials',
    );
  });
  it('waits, without rows, until the delivery has its own feedback', () => {
    const view = cover(state({ submission: second, submissions: [first, second] }), 'zh');
    expect(view.waiting).toBe(true);
    expect([view.met, view.unknown, view.unmet]).toEqual([[], [], []]);
  });
  it('lists only the items that changed since the previous delivery', () => {
    const secondReport = report('f-2', 'sub-2', [
      ['R3.capacity', 'MET', 'verified_rule'],
      ['R4.functional_tests', 'MET', 'verified_rule'],
      ['R4.staleness_test', 'NOT_MET', 'verified_rule'],
      ['R2.support', 'INSUFFICIENT', 'pending'],
      ['R5.impact', 'MET', 'verified_rule'],
    ]);
    const view = cover(
      state({
        submission: second,
        submissions: [first, second],
        reports: [firstReport, secondReport],
      }),
      'zh',
    );
    expect(view.compare).toEqual({
      previous: 1,
      changes: [
        { criterion: 'R4.functional_tests', name: '实际测试', from: 'unmet', to: 'met' },
        { criterion: 'R5.impact', name: '变更影响', from: 'na', to: 'met' },
      ],
    });
  });
  it('says there was no change when the rule results are the same', () => {
    const again = report('f-2', 'sub-2', [
      ['R3.capacity', 'MET', 'verified_rule'],
      ['R4.functional_tests', 'NOT_MET', 'verified_rule'],
      ['R4.staleness_test', 'NOT_MET', 'verified_rule'],
      ['R2.support', 'INSUFFICIENT', 'pending'],
      ['R5.impact', 'NOT_APPLICABLE', 'verified_rule', 'not_applicable'],
    ]);
    const view = cover(
      state({ submission: second, submissions: [first, second], reports: [firstReport, again] }),
      'en',
    );
    expect(view.compare).toEqual({ previous: 1, changes: [] });
  });
});

describe('feedback wait narrative', () => {
  it('counts real seconds and never a percentage', () => {
    expect(elapsedWords(23.9, 'zh')).toBe('已用 23 秒');
    expect(elapsedWords(112, 'zh')).toBe('已用 1 分 52 秒');
    expect(elapsedWords(5, 'en')).toBe('5 s so far');
  });
  it('names only the stages the server reports', () => {
    expect(phaseWords('queued', 'zh')).toBe('排队');
    expect(phaseWords('running', 'en')).toBe('Writing');
    expect(phaseWords(undefined, 'zh')).toBe('');
  });
});

describe('the cover of a delivery just made here', () => {
  const note = {
    sessionId: 's',
    decision: 'launch_narrow',
    at: new Date().toISOString(),
    products: [{ ref: ref('product', 'p', 2), title: '首批试点方案', purpose: 'commitment' }],
  };
  it('stands in with the decision, time and versions until the record is read back', () => {
    const view = coverView(
      { status: 'submitted', busy: true, products: [], reports: [], submission: null },
      'zh',
      note,
    );
    expect(view).toMatchObject({
      decision: '缩小范围推进',
      confirming: true,
      waiting: true,
      met: [],
      unknown: [],
      unmet: [],
    });
    expect(view?.when).toMatch(/^\d{2}:\d{2}$/);
    expect(view?.attachments.map((a) => a.line)).toEqual(['《首批试点方案》 · 第 2 版 · 试点决定']);
  });
  it('gives way to the delivery record once it is read, and ignores another practice', () => {
    expect(cover(state(), 'zh').confirming).toBeUndefined();
    const other = { ...note, sessionId: 'elsewhere' };
    expect(coverView(state({ submission: null, submissions: [] }), 'zh', other)).toBeNull();
  });
});
