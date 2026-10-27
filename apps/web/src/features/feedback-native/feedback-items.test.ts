import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { asFake, fakeDocument, type FakeElement } from '../results-native/fake-dom';
import { criterionChecks, criterionLabels, criterionQuestions, criterionScopes } from './criteria';
import {
  earlierSummary,
  feedbackItemsView,
  itemMark,
  renderFeedbackItems,
  type ItemsRenderHooks,
} from './feedback-items';
import { recordCounts, type Report } from './index';
import { adviceRowLine, readRegisteredAdvice } from './model-advice';

type Item = Report['items'][number];
const PREMISE = '本项仅核对明确承诺的受限范围及固定配置。';
const item = (criterion: string, explanation: string, label: string, extra: Partial<Item> = {}): Item => ({
  criterion,
  explanation,
  label,
  source: label === 'INSUFFICIENT' ? 'pending' : 'verified_rule',
  applicability: label === 'NOT_APPLICABLE' ? 'not_applicable' : 'applicable',
  rule_bound:
    label === 'INSUFFICIENT' || label === 'NOT_APPLICABLE' ? null : { lower: label, upper: label },
  citations: [],
  ...extra,
});
const items: Item[] = [
  item('R3.capacity', `${PREMISE}\n按评价时点核对：固定配置人数20，有效容量30。`, 'MET'),
  item('R3.resources', `${PREMISE}\n需要 4 人日，可用 3 人日。`, 'NOT_MET'),
  item('R4.staleness_test', `${PREMISE}\n完整记录内没有政策更新后的相关动态复测。`, 'NOT_MET'),
  item('R6.consistency', `${PREMISE}\n内容不一致。`, 'NOT_MET'),
  item(
    'R2.support',
    '核对判断与当时可知证据的关系；引用存在不代表支持成立。\n证据或语义尚未核实；保留未知，不按作品形式或未见记录判错。',
    'INSUFFICIENT',
  ),
  item(
    'R5.adjustment',
    `${PREMISE}\n已有相关配置调整；调整质量仍需核验。`,
    'PARTIAL',
    { rule_bound: { lower: 'NOT_MET', upper: 'PARTIAL' } },
  ),
  item('R5.impact', '有相关变更时核对其影响；没有相关事件时本项不适用。', 'NOT_APPLICABLE'),
];
const report = (extra: Partial<Report> = {}): Report => ({
  id: 'f-2',
  version: 1,
  subject: { session_id: 's', kind: 'submission', object_id: 'sub-2', version: 1 },
  items,
  rule_items: items,
  business_response: '',
  next_options: [],
  ...extra,
});
const hooks = (open = new Set<string>()): ItemsRenderHooks => ({
  id: 'f-2-1',
  isOpen: (key) => open.has(key),
  onToggle: (key, on) => (on ? open.add(key) : open.delete(key)),
});
const byData = (root: FakeElement, name: string, value?: string): FakeElement[] => {
  const found: FakeElement[] = [];
  const visit = (node: unknown) => {
    if (!(node && typeof node === 'object' && 'children' in node)) return;
    const el = node as FakeElement;
    if (name in el.dataset && (value === undefined || el.dataset[name] === value)) found.push(el);
    el.children.forEach(visit);
  };
  visit(root);
  return found;
};

describe('195 feedback item by item: the view', () => {
  it('groups not met, not known yet and holds up, and folds what does not apply', () => {
    const view = feedbackItemsView(report(), { language: 'zh', kind: 'submission', decision: 'launch_narrow' });
    expect(view.unmet.map((row) => row.criterion)).toEqual([
      'R3.resources',
      'R4.staleness_test',
      'R6.consistency',
    ]);
    expect(view.unknown.map((row) => row.criterion)).toEqual(['R2.support', 'R5.adjustment']);
    expect(view.met.map((row) => row.criterion)).toEqual(['R3.capacity']);
    expect(view.na.map((row) => row.criterion)).toEqual(['R5.impact']);
    // Red for a limit exceeded, amber for retesting after a change, else ink (the cover's rule).
    expect(view.unmet.map((row) => row.tone)).toEqual(['bad', 'warn', 'ink']);
    expect(itemMark(items[5])).toBe('unknown');
  });

  it('writes the rule fact on a row that holds up and the short question on one not known yet', () => {
    const view = feedbackItemsView(report(), { language: 'zh', kind: 'submission' });
    expect(view.met[0].line).toBe('按评价时点核对：固定配置人数20，有效容量30。');
    expect(view.unknown[0].line).toBe(criterionQuestions('zh')['R2.support']);
    // The basis keeps the rubric's own sentence and the stored lines without the shared premise.
    expect(view.unknown[0].checks).toBe('关键判断是否由当时可知的证据支持。');
    expect(view.met[0].found).toEqual(['按评价时点核对：固定配置人数20，有效容量30。']);
    expect(view.premises).toEqual([PREMISE]);
    expect(view.unknown[1].bound).toBe('规则只核实到一个范围：介于未满足和部分满足之间；范围内的具体判断还要核验。');
    expect(view.met[0].bound).toBe('规则判定：满足');
  });

  it('gives each unmet row a direct step to an existing tool', () => {
    const view = feedbackItemsView(report(), { language: 'en', kind: 'submission' });
    expect(view.unmet.map((row) => row.action)).toEqual([
      { tool: 'resources', label: 'Request resources' },
      { tool: 'open-bench', label: 'Retest' },
      undefined,
    ]);
  });

  it('counts by items, never a percentage, and names model advice only when there is some', () => {
    const plain = feedbackItemsView(report(), { language: 'zh', kind: 'submission' });
    // QA G-10: the rule-checked item left as a range is shown, and counted, as not known yet,
    // so the two counts add up to the total.
    expect(plain.count).toBe('规则核实 4 项／共 6 项适用 · 还不知道 2 项');
    expect(plain.met.length + plain.unmet.length).toBe(4);
    expect(plain.unknown.length).toBe(2);
    const advised = feedbackItemsView(report(), {
      language: 'en',
      kind: 'submission',
      legacyAdvice: [{ ...items[4], source: 'model_advice', label: 'SUPPORTED' }],
    });
    expect(advised.count).toBe('4 of 6 checked by rules · 2 can’t tell yet (model advice on 1)');
    expect(advised.count).not.toMatch(/%/);
  });

  it('says once what the feedback checked against, from the delivery’s decision', () => {
    const scope = (decision: string | null, kind = 'submission', language: 'zh' | 'en' = 'zh') =>
      feedbackItemsView(report(), { language, kind, decision }).scope;
    expect(scope('launch_narrow')).toBe('按你承诺的内容核对：受限范围、固定配置。');
    expect(scope('launch_narrow', 'submission', 'en')).toBe(
      'Checked against what you committed: a limited scope and a fixed configuration.',
    );
    for (const decision of ['launch', 'defer_with_conditions', 'no_go'])
      expect(scope(decision)).toMatch(/^按你承诺的内容核对：/);
    expect(scope(null)).toBe('按你交付的版本核对。');
    expect(scope(null, 'review')).toBe('按评审的作品版本核对。');
  });

  it('puts what the model said on the R2.support row, red only for a contradiction', () => {
    const view = feedbackItemsView(report(), {
      language: 'zh',
      kind: 'submission',
      adviceLine: { text: '模型建议：1 句与材料矛盾（不计分）', tone: 'bad' },
    });
    expect(view.unknown[0]).toMatchObject({
      criterion: 'R2.support',
      line: '模型建议：1 句与材料矛盾（不计分）',
      lineTone: 'bad',
    });
    // Waiting for a model: "模型建议" and the grey mark, whose readable name follows it.
    const waiting = feedbackItemsView(report(), {
      language: 'zh',
      kind: 'submission',
      adviceLine: { text: '模型建议', tone: 'ink', waiting: true },
    });
    const root = asFake(renderFeedbackItems(fakeDocument(), waiting, 'zh', hooks()));
    const [support] = byData(root, 'feedbackItem', 'R2.support');
    expect(support.byClass('fb-item__line')[0].textContent).toBe('模型建议等待模型接入');
  });

  it('sums an earlier delivery up in one line', () => {
    const view = feedbackItemsView(report(), { language: 'zh', kind: 'submission' });
    expect(earlierSummary(view, 'zh')).toBe('没站住 3 项 · 站得住 1 项 · 还不知道 2 项');
    expect(earlierSummary(view, 'en')).toBe('3 didn’t hold up · 1 holds up · 2 can’t tell yet');
  });
});

describe('195 feedback item by item: the rows', () => {
  it('draws each row as a closed disclosure that opens its basis in place', () => {
    const open = new Set<string>();
    const root = asFake(
      renderFeedbackItems(
        fakeDocument(),
        feedbackItemsView(report(), { language: 'zh', kind: 'submission', decision: 'launch_narrow' }),
        'zh',
        hooks(open),
      ),
    );
    const rows = byData(root, 'feedbackItem');
    expect(rows.map((row) => row.dataset.feedbackItem)).toEqual([
      'R3.resources',
      'R4.staleness_test',
      'R6.consistency',
      'R2.support',
      'R5.adjustment',
      'R3.capacity',
      'R5.impact',
    ]);
    const support = rows[3];
    const head = support.byClass('fb-item__head')[0];
    const body = support.byClass('fb-item__body')[0];
    expect(head.tagName).toBe('button');
    expect(head.getAttribute('aria-expanded')).toBe('false');
    expect(head.getAttribute('aria-controls')).toBe((body as unknown as { id: string }).id);
    expect(body.hidden).toBe(true);
    // The state word is for screen readers; the shape carries it on screen.
    expect(head.textContent).toBe(`?还不知道：判断的证据支持${criterionQuestions('zh')['R2.support']}›`);
    head.click();
    expect(head.getAttribute('aria-expanded')).toBe('true');
    expect(body.hidden).toBe(false);
    expect(open.has('f-2-1:R2.support')).toBe(true);
    expect(body.textContent).toContain('这一项看什么关键判断是否由当时可知的证据支持。');
    head.click();
    expect(body.hidden).toBe(true);
  });

  it('heads each group once and keeps the premise for the scope line’s basis only', () => {
    const doc = fakeDocument();
    const root = asFake(
      renderFeedbackItems(
        doc,
        feedbackItemsView(report(), { language: 'zh', kind: 'submission', decision: 'launch_narrow' }),
        'zh',
        { ...hooks(), scopeBasis: [Object.assign(doc.createElement('p'), { textContent: PREMISE })] },
      ),
    );
    expect(root.byTag('h3').map((h) => h.textContent)).toEqual([
      '没站住 · 3再次交付前先处理这些。',
      '还不知道 · 2评审还没确认这些项；这里的任何一项都不算你没做。',
      '站得住 · 1规则对照你的记录核实过。',
    ]);
    expect(root.textContent.split(PREMISE).length - 1).toBe(1);
    expect(root.textContent).not.toContain('展开');
  });

  it('opens a remembered row again after a redraw, without replaying its fade', () => {
    const open = new Set(['f-2-1:R3.capacity']);
    const root = asFake(
      renderFeedbackItems(
        fakeDocument(),
        feedbackItemsView(report(), { language: 'en', kind: 'submission' }),
        'en',
        hooks(open),
      ),
    );
    const [capacity] = byData(root, 'feedbackItem', 'R3.capacity');
    const body = capacity.byClass('fb-item__body')[0];
    expect(body.hidden).toBe(false);
    expect('opening' in body.dataset).toBe(false);
  });
});

describe('195 basis: what we found is findings only (197 E1)', () => {
  it('moves the rules’ scope under what the item checks and drops their default pending sentence', () => {
    const view = feedbackItemsView(report(), { language: 'zh', kind: 'submission' });
    const support = view.unknown.find((row) => row.criterion === 'R2.support');
    expect(support?.scope).toBe('核对判断与当时可知证据的关系；引用存在不代表支持成立。');
    expect(support?.found).toEqual(['还没核验：评审还没确认这一项。']);
    const shown = asFake(renderFeedbackItems(fakeDocument(), view, 'zh', hooks(new Set(['R2.support']))));
    const [row] = byData(shown, 'feedbackItem', 'R2.support');
    const text = row.byClass('fb-basis')[0].textContent;
    expect(text).toContain('这一项看什么关键判断是否由当时可知的证据支持。核对判断与当时可知证据的关系');
    expect(text).not.toContain('不按作品形式或未见记录判错');
  });

  it('says what the model managed for R2.support: no sentence checked, or advice to confirm', () => {
    const none = feedbackItemsView(report(), {
      language: 'zh',
      kind: 'submission',
      adviceLine: { text: '模型建议：一句也没能核查（不计分）', tone: 'ink', kind: 'abstained' },
    });
    expect(none.unknown.find((row) => row.criterion === 'R2.support')?.found).toEqual([
      '还没核验。模型没能核查你的句子，所以还不知道你的引用能不能支撑你的判断。',
    ]);
    const advised = feedbackItemsView(report(), {
      language: 'zh',
      kind: 'submission',
      adviceLine: { text: '模型建议：1 句与材料矛盾（不计分）', tone: 'bad', kind: 'advised' },
    });
    expect(advised.unknown.find((row) => row.criterion === 'R2.support')?.found).toEqual([
      '还没核验。模型对部分句子给了建议（见下方），这只是建议，评审还没确认。',
    ]);
  });

  it('keeps every scope sentence word for word from the rules', () => {
    const python = readFileSync(
      new URL('../../../../../src/career_lab/rubrics/v4/applicability.py', import.meta.url),
      'utf8',
    );
    const table = python.slice(python.indexOf('SCOPE = {'), python.indexOf('\n}\n', python.indexOf('SCOPE = {')));
    const pairs = [...table.matchAll(/"(R\d\.[a-z_]+)": \(\s*"([^"]+)",\s*"([^"]+)",\s*\)/g)];
    expect(pairs.length).toBe(14);
    for (const [, id, zh, en] of pairs) {
      expect(criterionScopes('zh')[id], id).toBe(zh);
      expect(criterionScopes('en')[id], id).toBe(en);
    }
  });
});

describe('195 rubric sentences and short questions', () => {
  const rubric = JSON.parse(
    readFileSync(
      new URL('../../../../../src/career_lab/rubrics/v4/definitions/rubric-v2-final-20261009.json', import.meta.url),
      'utf8',
    ),
  ) as { criteria: { id: string; zh: { description: string }; en: { description: string } }[] };

  it('shows each criterion’s check word for word from the final rubric', () => {
    for (const language of ['zh', 'en'] as const) {
      const checks = criterionChecks(language);
      for (const criterion of rubric.criteria)
        expect(checks[criterion.id], criterion.id).toBe(criterion[language].description.split('\n')[0]);
      expect(Object.keys(checks).sort()).toEqual(rubric.criteria.map((c) => c.id).sort());
    }
  });

  it('asks a short question for every criterion in both languages', () => {
    const names = Object.keys(criterionLabels('zh')).filter((id) => rubric.criteria.some((c) => c.id === id));
    for (const language of ['zh', 'en'] as const) {
      const questions = criterionQuestions(language);
      expect(Object.keys(questions).sort()).toEqual(names.sort());
      for (const text of Object.values(questions)) expect(text.length).toBeGreaterThan(4);
    }
    for (const text of Object.values(criterionQuestions('en'))) expect(text).not.toMatch(/[一-鿿]/u);
  });
});

describe('195 what the feedback is based on', () => {
  type Snapshot = Parameters<typeof recordCounts>[0];
  const snapshot = {
    status: 'partial' as const,
    summary: [],
    references: [
      { verified_ref: { session_id: 's', kind: 'material', object_id: 'brief', version: 1 }, valid_at_subject: true },
      { verified_ref: { session_id: 's', kind: 'material', object_id: 'policy', version: 2 }, valid_at_subject: true },
    ],
    activity_totals: {
      material_read: { status: 'unknown' as const, count: null, verified_records: 9 },
      test_run: { status: 'unknown' as const, count: null, verified_records: 5 },
      question_sent: { status: 'unknown' as const, count: null, verified_records: 3 },
      reply_received: { status: 'unknown' as const, count: null, verified_records: 1 },
      learner_displayed: { status: 'unknown' as const, count: null, verified_records: 0 },
    },
    verified_source_count: 2,
  } as unknown as Snapshot;
  it('counts verified activity and cited sources in one line, both languages', () => {
    expect(recordCounts(snapshot, 'zh')).toBe(
      '读资料 9 次 · 测试 5 次 · 问同事 3 次 · 收到回复 1 条 · 引用资料 2 份（都是当时有效版本）',
    );
    expect(recordCounts(snapshot, 'en')).toBe(
      '9 document reads · 5 test runs · 3 questions to colleagues · 1 reply · 2 sources cited, both current',
    );
  });
  it('says how many cited sources were out of date at the time', () => {
    const stale = {
      ...snapshot,
      references: [snapshot.references[0], { ...snapshot.references[1], valid_at_subject: false }],
    } as Snapshot;
    expect(recordCounts(stale, 'en')).toContain('2 sources cited, 1 out of date at the time');
    expect(recordCounts({ ...snapshot, activity_totals: {}, verified_source_count: 0 }, 'zh')).toBe('');
  });
});

describe('195 model advice on the R2.support row', () => {
  const advice = (units: { label: string | null; status: string; reason?: string }[]) =>
    readRegisteredAdvice(
      [
        {
          criterion: 'R2.support',
          status: units.some((u) => u.label) ? 'completed' : 'unavailable',
          registration: {
            id: 'external-example',
            model_revision: 'fixed',
            scope: 'external_candidate',
            quality_validated: false,
          },
          label: units.some((u) => u.label === 'CONTRADICTED')
            ? 'CONTRADICTED'
            : units.some((u) => u.label)
              ? 'INSUFFICIENT'
              : null,
          evidence_ids: [],
          citations: [],
          error_code: units.some((u) => u.label) ? null : 'all_units_abstained',
          mode: 'advisory',
          affects_score: false,
          units: units.map((u, index) => ({
            index,
            subject: { session_id: 's', kind: 'product', object_id: 'p', version: 1, span_start: index, span_end: index + 1, quote: `s${index}` },
            status: u.status,
            label: u.label,
            evidence_ids: [],
            citations: [],
            reason_code: u.reason ?? null,
          })),
          aggregation: {
            policy: 'any_contradiction',
            counts: {
              supported: 0,
              contradicted: units.filter((u) => u.label === 'CONTRADICTED').length,
              insufficient: units.filter((u) => u.label === 'INSUFFICIENT').length,
              abstained: units.filter((u) => u.status === 'abstained').length,
              failed: 0,
            },
          },
        },
      ],
      's',
    );
  it('says what the model found, red for a contradiction, never a number', () => {
    const found = adviceRowLine(
      advice([
        { label: 'CONTRADICTED', status: 'completed' },
        { label: null, status: 'abstained', reason: 'unit_exceeds_encoder_limit' },
      ]),
      'zh',
      'pending',
    );
    expect(found).toEqual({ text: '模型建议：1 句与材料矛盾（不计分）', tone: 'bad', kind: 'advised' });
    const none = adviceRowLine(
      advice([{ label: null, status: 'abstained', reason: 'unit_exceeds_encoder_limit' }]),
      'en',
      'pending',
    );
    expect(none).toEqual({
      text: 'Model advice: couldn’t check any sentence (not scored)',
      tone: 'ink',
      kind: 'abstained',
    });
    // While it waits for a model: "模型建议" and the grey mark.
    expect(adviceRowLine(undefined, 'zh', 'waiting')).toEqual({
      text: '模型建议',
      tone: 'ink',
      waiting: true,
    });
    expect(adviceRowLine(undefined, 'en', 'unavailable')).toBeUndefined();
  });
});
