import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import reproduction from './fixtures/reproduction.zh.json';
import seeded from './fixtures/ticket-seeded.zh.json';
import signed from './fixtures/ticket-signed.zh.json';
import overreach from './fixtures/trial-overreach.zh.json';
import overreachReview from '../../../public/engineer/sample-overreach.en.json';
import rootCause from '../../../public/engineer/sample-root-cause.en.json';
import { engineerReportView, type EngineerReviewRecord } from '../engineer-report';
import { reviewViewOptions } from '../engineer-report/page';
import {
  candidateChanges,
  claimsFromTrial,
  draftTextLength,
  experimentRows,
  handoverChoices,
  HANDOVER_LIMIT,
  nextAfterReview,
  parseField,
  signSheet,
  signState,
  ticketFacts,
  trialLine,
  validateDraft,
  validateImpactNote,
  type DraftInput,
  type EditableField,
  type Experiment,
  type TicketDetail,
} from './model';

afterEach(() => setPreference('zh'));

const SEEDED = seeded as unknown as TicketDetail;
const SIGNED = signed as unknown as TicketDetail;
const OVERREACH = overreach as unknown as Experiment;
const REPRODUCTION = reproduction as unknown as Experiment;
const field = (name: string) =>
  SEEDED.editable_fields.find((f) => f.field === name) as EditableField;

describe('engineer desk · the ticket in work words', () => {
  it('ED-20 source, lagging versions and the system’s setup read as facts', () => {
    const facts = ticketFacts(SEEDED);
    expect(facts.source).toBe('来源：委托附带');
    expect(facts.targets).toHaveLength(1);
    const target = facts.targets[0];
    expect(target.query).toBe('住宿报销上限是多少？');
    expect(target.versions).toEqual([{ text: '差旅政策 v2 / 索引 v1，索引落后', stale: true }]);
    expect(target.cited).toBe('引用 差旅政策 v1');
    expect(target.origin).toBe('委托附带的复现记录');
    expect(target.config).toBe('');
    expect(facts.setup).toBe('起始状态由系统准备，不是你的操作：试点配置已上线为 v1。');
    expect(facts.retrieval).toBe('检索：规则版（不用模型）');
    expect(facts.reviewsLeft).toBe(3);
    setPreference('en');
    const en = ticketFacts(SEEDED);
    expect(en.source).toBe('Source: attached to the ticket');
    expect(en.retrieval).toBe('Retrieval: rule-based (no model)');
    expect(en.targets[0].versions[0].text).toBe('Travel policy v2 / index v1, index behind');
    expect(en.setup).toBe(
      'The system prepared this starting state, not you: the pilot configuration went live as v1.',
    );
  });

  it('ED-21 a ticket without setup says nothing about it; a target on other settings says which', () => {
    const own = { ...SEEDED, world_setup: null, source: 'tests' as const };
    expect(ticketFacts(own).setup).toBe('');
    expect(ticketFacts(own).source).toBe('来源：产品经理交来');
    setPreference('en');
    expect(ticketFacts(own).source).toBe('Source: handed over by product');
    setPreference('zh');
    const changed = {
      ...own,
      target_tests: [
        {
          ...SEEDED.target_tests[0],
          origin_label: '产品经理的测试记录',
          config: { same_as_baseline: false, changed_fields: ['fallback'], differences: {} },
        },
      ],
    };
    expect(ticketFacts(changed).targets[0].config).toBe(
      '当时的设置与委托基线不同：答不了或不确定时',
    );
  });
});

describe('engineer desk · candidate settings', () => {
  it('ED-22 only settings that differ from the baseline go into changes; sets ignore order', () => {
    const base = SEEDED.baseline_config;
    expect(candidateChanges(base, { ...base })).toEqual({});
    expect(
      candidateChanges(base, {
        ...base,
        freshness_guard: 'warn',
        min_score: 0.2,
        domains: [...(base.domains as string[])].reverse(),
      }),
    ).toEqual({ freshness_guard: 'warn', min_score: 0.2 });
  });

  it('ED-23 typed values are checked against the field’s limits before anything is sent', () => {
    expect(parseField(field('retrieval_limit'), '3')).toEqual({ value: 3 });
    expect(parseField(field('retrieval_limit'), '0')).toEqual({ error: '填 1 到 20 之间的整数。' });
    expect(parseField(field('retrieval_limit'), '2.5')).toEqual({
      error: '填 1 到 20 之间的整数。',
    });
    expect(parseField(field('min_score'), '0.2')).toEqual({ value: 0.2 });
    expect(parseField(field('min_score'), '-1')).toEqual({ error: '填不小于 0 的数。' });
    expect(parseField(field('min_score'), '')).toEqual({ error: '填不小于 0 的数。' });
    expect(parseField(field('prohibited_topics'), '薪资\n\n 密码 ')).toEqual({
      value: ['薪资', '密码'],
    });
    expect(parseField(field('prohibited_topics'), 'https://x.example')).toEqual({
      error: '每行写一个主题，不写网址或路径。',
    });
    expect(parseField(field('prohibited_topics'), Array(11).fill('题').join('\n'))).toEqual({
      error: '最多 10 个主题，每个不超过 40 字。',
    });
    setPreference('en');
    expect(parseField(field('chunk_size'), '5000')).toEqual({
      error: 'Enter a whole number from 1 to 4000.',
    });
  });
});

describe('engineer desk · the trial log', () => {
  it('ED-24 each experiment is one line: who, what, which settings, public tally', () => {
    const [rep, trial] = SIGNED.trials;
    const repLine = trialLine(rep, 4, 'UTC');
    expect(repLine).toMatchObject({
      who: '你',
      agent: false,
      verb: '复现',
      fields: '',
      tally: '1/1 与记录一致',
      tone: 'good',
      time: '09:22',
    });
    const trialLineView = trialLine(trial, 4, 'UTC');
    expect(trialLineView).toMatchObject({
      verb: '试跑',
      fields: '过期资料保护、最低相关度',
      tally: '公开 4/4 通过',
      tone: 'good',
    });
    const agent = trialLine(
      {
        ...trial,
        executor: { id: 'agent', kind: 'external_agent' },
        counts: { ...trial.counts, passed: 3, failed: 1 },
      },
      4,
      'UTC',
    );
    expect(agent).toMatchObject({
      who: '你的 Agent',
      agent: true,
      tally: '公开 3/4 通过',
      tone: 'ink',
    });
    setPreference('en');
    expect(trialLine(trial, 4, 'UTC')).toMatchObject({
      who: 'You',
      verb: 'Trial',
      fields: 'Stale-source guard, Minimum relevance',
      tally: 'Public 4/4 passed',
    });
  });

  it('ED-25 a trial’s rows give expected and actual in words; a target without a probe is not checked', () => {
    const rows = experimentRows(OVERREACH);
    expect(rows[0]).toMatchObject({
      id: 'F01',
      target: true,
      result: 'pass',
      mark: 'good',
      verdict: '通过',
      expected: '带提醒回答',
      actual: '带提醒回答',
    });
    const withTarget = experimentRows({
      ...OVERREACH,
      rows: [
        ...(OVERREACH.rows ?? []),
        {
          id: 'target-1',
          kind: 'target',
          is_target: true,
          query: '出差住宿能报多少？',
          expected_status: null,
          actual_status: 'answered',
          error_code: null,
          answer_summary: '每晚 500 元。',
          citations: [],
          citation_count: 0,
          result: 'unchecked',
        },
      ],
    });
    expect(withTarget.at(-1)).toMatchObject({
      id: '',
      target: true,
      mark: 'unknown',
      verdict: '未核对',
      expected: '',
      actual: '直接回答',
    });
    const rep = experimentRows(REPRODUCTION);
    expect(rep[0]).toMatchObject({
      verdict: '与记录一致',
      mark: 'good',
      expected: '直接回答',
      actual: '直接回答',
    });
  });

  it('ED-26 the latest trial can fill the self-report, only when it covers every public probe', () => {
    const ids = SEEDED.public_probes.map((p) => p.id);
    expect(claimsFromTrial(OVERREACH, ids)).toEqual({
      F01: 'pass',
      F04: 'pass',
      F05: 'pass',
      F12: 'pass',
    });
    expect(claimsFromTrial({ ...OVERREACH, rows: OVERREACH.rows?.slice(1) }, ids)).toBeNull();
    expect(claimsFromTrial(REPRODUCTION, ids)).toBeNull();
  });
});

describe('engineer desk · drafting and signing', () => {
  const ids = ['F01', 'F04', 'F05', 'F12'];
  const draft = (over: Partial<DraftInput> = {}): DraftInput => ({
    changes: { freshness_guard: 'warn' },
    explanation: '加提醒',
    change_statements: [
      { field: 'freshness_guard', before: 'none', after: 'warn', reason: '索引落后时提醒' },
    ],
    claimed_results: {},
    unresolved: [],
    ...over,
  });

  it('ED-27 draft text is counted as the server counts it and limited to 2000', () => {
    // Values count as compact JSON, as the server counts them: "none" is six characters.
    expect(draftTextLength(draft())).toBe(3 + 7 + 6 + 6);
    expect(validateDraft(draft(), ids)).toEqual([]);
    expect(validateDraft(draft({ explanation: '字'.repeat(1990) }), ids)).toEqual([
      '草稿的文字合计最多 2000 字，删减一些再保存。',
    ]);
  });

  it('ED-28 a self-report covers every public probe or none; each statement needs a reason', () => {
    expect(validateDraft(draft({ claimed_results: { F01: 'pass' } }), ids)).toEqual([
      '自报要覆盖全部公开探针，或者一条都不填。',
    ]);
    expect(
      validateDraft(
        draft({
          change_statements: [
            { field: 'freshness_guard', before: 'none', after: 'warn', reason: ' ' },
          ],
        }),
        ids,
      ),
    ).toEqual(['每条变更都写一句理由。']);
    expect(validateDraft(draft({ unresolved: [{ description: '', probe_ids: [] }] }), ids)).toEqual(
      ['未修复项写清是什么问题。'],
    );
  });

  it('ED-29 the impact note is required and at most 500 characters', () => {
    expect(validateImpactNote('')).toBe('先写这个改动还可能影响哪些问题。');
    expect(validateImpactNote('   ')).toBe('先写这个改动还可能影响哪些问题。');
    expect(validateImpactNote('知识库外的问题')).toBe('');
    expect(validateImpactNote('字'.repeat(501))).toBe('影响说明最多 500 字。');
  });

  it('ED-30 the sign sheet lays the actual change beside the stated one without judging them', () => {
    const sheet = signSheet(
      {
        ...(SIGNED.latest_draft as NonNullable<TicketDetail['latest_draft']>),
        change_statements: [
          { field: 'freshness_guard', before: 'none', after: 'fallback', reason: '索引落后时提醒' },
        ],
      },
      'UTC',
    );
    expect(sheet.author).toBe('你');
    expect(sheet.actual).toEqual([
      { field: 'freshness_guard', name: '过期资料保护', before: '不处理', after: '加提醒' },
      { field: 'min_score', name: '最低相关度', before: '0.35', after: '0.2' },
    ]);
    expect(sheet.stated).toEqual([
      {
        field: 'freshness_guard',
        name: '过期资料保护',
        before: '不处理',
        after: '转人工',
        reason: '索引落后时提醒',
      },
    ]);
    expect(JSON.stringify(sheet)).not.toMatch(/mismatch|不一致|矛盾/);
    expect(sheet.claims).toEqual([
      { id: 'F01', text: '通过' },
      { id: 'F04', text: '通过' },
      { id: 'F05', text: '通过' },
      { id: 'F12', text: '通过' },
    ]);
  });

  it('ED-31 signing is open while reviews remain and the latest draft is not yet signed', () => {
    expect(signState(SEEDED)).toEqual({ can: false, left: 3, reason: '先起草一份提交，再签字。' });
    const fresh = { ...SIGNED, reviews: [], review_budget: { used: 0, limit: 3 } };
    expect(signState(fresh)).toEqual({ can: true, left: 3, reason: '' });
    expect(signState(SIGNED)).toMatchObject({
      can: false,
      left: 2,
      reason: '这份草稿已经签过，改动后再起草一份。',
      signedReview: SIGNED.reviews[0].review_id,
    });
    expect(signState({ ...fresh, review_budget: { used: 3, limit: 3 } })).toEqual({
      can: false,
      left: 0,
      reason: '这份委托的 3 次复核已经用完。',
    });
  });
});

describe('engineer desk · handing tests to engineering', () => {
  const test = (id: string, over: Record<string, unknown> = {}) => ({
    id,
    question: `问题 ${id}`,
    answer: '回答',
    stale: false,
    errorCode: null,
    ...over,
  });

  it('ED-32 tests that cite an out-of-date version come first and are chosen for you, at most ten', () => {
    const tests = [test('a'), test('b', { stale: true }), test('c', { stale: true }), test('d')];
    const choices = handoverChoices(tests);
    expect(choices.map((c) => c.id)).toEqual(['b', 'c', 'a', 'd']);
    expect(choices.map((c) => c.flag)).toEqual([
      '引用的版本已经过期',
      '引用的版本已经过期',
      '',
      '',
    ]);
    expect(choices.map((c) => c.chosen)).toEqual([true, true, false, false]);
    const many = handoverChoices(
      Array.from({ length: 14 }, (_, i) => test(`t${i}`, { stale: true })),
    );
    expect(many.filter((c) => c.chosen)).toHaveLength(HANDOVER_LIMIT);
    expect(HANDOVER_LIMIT).toBe(10);
  });
});

describe('engineer desk · after a review', () => {
  const view = (record: EngineerReviewRecord) =>
    engineerReportView(record.report, reviewViewOptions(record, 'en'));
  const ROOT = rootCause as unknown as EngineerReviewRecord;
  const OVER = overreachReview as unknown as EngineerReviewRecord;

  it('ED-43 everything holds: back to the product board leads; a new failure keeps "fix it again" first', () => {
    expect(nextAfterReview(view(ROOT))).toBe('board');
    expect(nextAfterReview(view(OVER))).toBe('again');
    // Target not fixed, even with nothing newly broken: another round is still the next step.
    const notFixed = {
      ...ROOT.report,
      findings: ROOT.report.findings.map((f) =>
        f.kind === 'target_fix' ? { ...f, status: 'fail' as const } : f,
      ),
    };
    expect(nextAfterReview(engineerReportView(notFixed, { language: 'en' }))).toBe('again');
    // A comparison that could not finish is not "everything holds".
    const unknown = {
      ...ROOT.report,
      hidden_comparison: { new_failures: 0, fixed: 2, still_failing: 0, unverified: 1 },
    };
    expect(nextAfterReview(engineerReportView(unknown, { language: 'en' }))).toBe('again');
  });
});
