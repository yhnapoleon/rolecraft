import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FeedbackItem, SubmissionRuleCheck } from '../../contracts-v2';
import {
  createPresubmitSchedule,
  presubmitView,
  submissionFactLine,
  type PresubmitState,
} from './presubmit';

type Label = FeedbackItem['label'];
const item = (
  criterion: string,
  label: Label,
  source: FeedbackItem['source'] = 'verified_rule',
  applicability: FeedbackItem['applicability'] = 'applicable',
): FeedbackItem => ({
  criterion,
  label,
  source,
  applicability,
  explanation: `rule text for ${criterion}`,
  citations: [],
  rule_bound:
    source === 'verified_rule' && label !== 'INSUFFICIENT' && label !== 'NOT_APPLICABLE'
      ? { lower: label, upper: label }
      : null,
});
const pending = (criterion: string) => item(criterion, 'INSUFFICIENT', 'pending');
const inapplicable = (criterion: string) =>
  item(criterion, 'NOT_APPLICABLE', 'verified_rule', 'not_applicable');
const SEMANTIC = [
  'R1.target',
  'R1.metrics',
  'R2.support',
  'R2.unknowns',
  'R2.failure_analysis',
  'R5.impact',
  'R6.consistency',
  'R6.operations',
  'R6.alternatives',
].map(pending);
const ref = (kind: string, id: string, version = 1) => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
});
function check(rule_items: FeedbackItem[], facts: SubmissionRuleCheck['facts'] = {}) {
  return {
    basis: 'draft',
    mode: 'rules_only',
    session_id: 's',
    as_of: { business_seq: 9, workspace_revision: 4, storage_revision: 12 },
    decision: 'launch_narrow',
    products: [ref('product', 'p', 2)],
    config: { ...ref('config', 'cfg', 3), config_version: 2 },
    evaluation: { path: 'runtime/evaluation.json', sha256: '0'.repeat(64) },
    work_language: 'zh',
    rule_items,
    facts,
  } satisfies SubmissionRuleCheck;
}
/** 164 F17: retested on configuration v1 after the policy update, submitted with v2. */
const f17 = check(
  [
    ...SEMANTIC.slice(0, 5),
    item('R3.capacity', 'MET'),
    item('R3.resources', 'MET'),
    item('R4.functional_tests', 'NOT_MET'),
    item('R4.staleness_test', 'NOT_MET'),
    SEMANTIC[5],
    { ...item('R5.adjustment', 'PARTIAL'), rule_bound: { lower: 'PARTIAL', upper: 'MET' } },
    ...SEMANTIC.slice(6),
  ],
  {
    participants: 20,
    capacity: 30,
    required_dev_days: 2,
    available_dev_days: 3,
    requested_launch_day: 7,
    deadline_day: 7,
    unapproved_resource_excess: false,
    config_version: 2,
    policy_version: 2,
    adjustment_actions: 1,
    test_runs: [
      { config_version: 0, runs: 1, retests: 0 },
      { config_version: 1, runs: 1, retests: 1 },
    ],
  },
);
const lines = (view: ReturnType<typeof presubmitView>) =>
  view.lines.map((line) => [line.met, line.text, line.action?.label ?? null]);

describe('pre-submission preview view', () => {
  it('counts the rule-checked items met and lists each with one fact (zh)', () => {
    const view = presubmitView(f17, 'zh');
    expect(view.title).toBe('交付前预演 · 按你选的版本和决定');
    expect(view.count).toEqual({ met: 2, total: 5, text: '2/5 项已满足' });
    expect(lines(view)).toEqual([
      [true, '人数 20 ≤ 容量 30', null],
      [true, '人日 2 ≤ 3，第 7 天上线 ≤ 期限第 7 天', null],
      [false, '配置 v2 还没测过（配置 v1 测过 1 次）', '去测试'],
      [false, '政策更新后，配置 v2 还没复测（你在配置 v1 下复测过 1 次）', '去重测'],
      [false, '政策更新后已有 1 次调整，配置 v2 之后还没复测', '去重测'],
    ]);
    expect(view.waiting).toBe('9 项等待模型核验（不计入）');
    expect(view.lines.map((line) => line.action?.action ?? null)).toEqual([
      null,
      null,
      'open-bench',
      'open-bench',
      'open-bench',
    ]);
  });
  it('says the same in English', () => {
    const view = presubmitView(f17, 'en');
    expect(view.title).toBe('Pre-submission preview · for the versions and decision you chose');
    expect(view.count?.text).toBe('2/5 met');
    expect(lines(view)).toEqual([
      [true, '20 participants ≤ capacity 30', null],
      [true, 'Dev-days 2 ≤ 3; launch day 7 ≤ deadline day 7', null],
      [false, 'Config v2 not tested yet (config v1: 1 run)', 'Run a test'],
      [false, 'No retest on config v2 since the policy update (1 retest on config v1)', 'Retest'],
      [false, '1 adjustment since the policy update; config v2 not retested yet', 'Retest'],
    ]);
    expect(view.waiting).toBe('9 awaiting model verification (not counted)');
  });
  it('names what exceeds a limit and offers the matching tool', () => {
    const over = check(
      [
        item('R2.unknowns', 'NOT_MET'),
        item('R3.capacity', 'NOT_MET'),
        item('R3.resources', 'NOT_MET'),
        item('R4.functional_tests', 'NOT_MET'),
      ],
      {
        participants: 40,
        capacity: 30,
        required_dev_days: 7,
        available_dev_days: 3,
        requested_launch_day: 9,
        deadline_day: 7,
        unapproved_resource_excess: true,
        config_version: 1,
        test_runs: [],
      },
    );
    const view = presubmitView(over, 'zh');
    expect(lines(view)).toEqual([
      [false, '按这个决定会超出已批准的资源', '申请资源'],
      [false, '人数 40 > 容量 30', '调整设置'],
      [false, '需要 7 人日 > 可用 3；第 9 天上线 > 期限第 7 天', '申请资源'],
      [false, '配置 v1 还没测过', '去测试'],
    ]);
    expect(view.lines.map((line) => [line.action?.action, line.tone])).toEqual([
      ['resources', 'bad'],
      ['config', 'bad'],
      ['resources', 'bad'],
      ['open-bench', 'ink'],
    ]);
    expect(lines(presubmitView(over, 'en'))[2]).toEqual([
      false,
      'Needs 7 dev-days > 3 available; launch day 9 > deadline day 7',
      'Request resources',
    ]);
  });
  it('names the earlier configuration when a retest there does not count for this one', () => {
    const facts = { ...f17.facts, adjustment_actions: 0 };
    const view = presubmitView(check([item('R5.adjustment', 'NOT_MET')], facts), 'zh');
    expect(lines(view)).toEqual([
      [false, '政策更新后，配置 v2 还没有相关调整或复测（你在配置 v1 下复测过 1 次）', '去重测'],
    ]);
    const english = presubmitView(check([item('R5.adjustment', 'NOT_MET')], facts), 'en');
    expect(lines(english)[0][1]).toBe(
      'No relevant adjustment or retest on config v2 since the policy update (1 retest on config v1)',
    );
    const none = presubmitView(
      check([item('R5.adjustment', 'NOT_MET')], { ...facts, test_runs: [] }),
      'zh',
    );
    expect(lines(none)).toEqual([[false, '政策更新后还没有调整设置、刷新索引或复测', '调整设置']]);
  });
  it('replaces the bar with one line when the decision leaves nothing for rules to check', () => {
    const deferred = check([
      ...SEMANTIC,
      ...[
        'R3.capacity',
        'R3.resources',
        'R4.functional_tests',
        'R4.staleness_test',
        'R5.adjustment',
      ].map(inapplicable),
    ]);
    const view = presubmitView(deferred, 'zh');
    expect(view.count).toBeNull();
    expect(view.lines).toEqual([]);
    expect(view.empty).toBe('按这个决定，没有规则能核实的项（5 项不适用）');
    expect(view.waiting).toBe('9 项等待模型核验（不计入）');
  });
  it('falls back to the item and its finding when a rule has no specific wording', () => {
    const view = presubmitView(
      check([item('R6.alternatives', 'PARTIAL'), item('R9.later', 'MET')]),
      'zh',
    );
    expect(lines(view)).toEqual([
      [false, '替代方案与取舍：部分满足', null],
      [true, '验收项：满足', null],
    ]);
  });
  it('keeps every figure an item count, never a percentage', () => {
    for (const language of ['zh', 'en'] as const) {
      const view = presubmitView(f17, language);
      const text = JSON.stringify(view);
      expect(text).not.toContain('%');
      expect(view.count?.text).toMatch(/^2\/5/);
    }
  });
  it('lists the frozen rule text in the details, marking a Chinese source in English', () => {
    const view = presubmitView(f17, 'en');
    expect(view.details.basis[0]).toEqual({
      name: 'Participants and capacity',
      text: 'rule text for R3.capacity',
      chineseSource: true,
    });
    expect(view.details.waiting).toContain('Evidence supporting judgments');
    expect(presubmitView(f17, 'zh').details.basis[0].chineseSource).toBe(false);
  });
});

describe('pre-submission preview schedule', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  const choice = (decision: 'launch' | 'no_go', point = 'p1') => ({
    decision,
    products: [ref('product', 'p', 2)],
    point,
  });
  function schedule() {
    const shown: PresubmitState[] = [];
    const calls: { decision: string; resolve: (value: SubmissionRuleCheck) => void }[] = [];
    const failures: ((error: Error) => void)[] = [];
    const control = createPresubmitSchedule({
      load: (input) =>
        new Promise<SubmissionRuleCheck>((resolve, reject) => {
          calls.push({ decision: input.decision, resolve });
          failures.push(reject);
        }),
      show: (state) => shown.push(state),
    });
    return { control, shown, calls, failures };
  }
  const answer = (decision: string) => ({ ...f17, decision }) as SubmissionRuleCheck;

  it('waits for the choice to settle and loads it once', async () => {
    const { control, calls } = schedule();
    control.request(choice('launch'));
    control.request(choice('no_go'));
    await vi.advanceTimersByTimeAsync(299);
    expect(calls).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls.map((c) => c.decision)).toEqual(['no_go']);
  });
  it('keeps one request in flight and shows only the latest choice', async () => {
    const { control, calls, shown } = schedule();
    control.request(choice('launch'));
    await vi.advanceTimersByTimeAsync(300);
    control.request(choice('no_go'));
    await vi.advanceTimersByTimeAsync(300);
    expect(calls).toHaveLength(1);
    calls[0].resolve(answer('launch'));
    await vi.advanceTimersByTimeAsync(0);
    expect(calls.map((c) => c.decision)).toEqual(['launch', 'no_go']);
    calls[1].resolve(answer('no_go'));
    await vi.advanceTimersByTimeAsync(0);
    const ready = shown.filter((state) => state.kind === 'ready');
    expect(ready.map((state) => state.kind === 'ready' && state.check.decision)).toEqual(['no_go']);
  });
  it('does not load again for the same choice at the same point, but does after records change', async () => {
    const { control, calls } = schedule();
    control.request(choice('launch'));
    await vi.advanceTimersByTimeAsync(300);
    calls[0].resolve(answer('launch'));
    await vi.advanceTimersByTimeAsync(0);
    control.request(choice('launch'));
    await vi.advanceTimersByTimeAsync(300);
    expect(calls).toHaveLength(1);
    control.request(choice('launch', 'p2'));
    await vi.advanceTimersByTimeAsync(300);
    expect(calls).toHaveLength(2);
  });
  it('clears without loading when no decision or version is chosen, discarding a late answer', async () => {
    const { control, calls, shown } = schedule();
    control.request(choice('launch'));
    await vi.advanceTimersByTimeAsync(300);
    control.request(null);
    calls[0].resolve(answer('launch'));
    await vi.advanceTimersByTimeAsync(300);
    expect(shown.at(-1)).toEqual({ kind: 'idle' });
    expect(shown.some((state) => state.kind === 'ready')).toBe(false);
  });
  it('reports a failure for the current choice only', async () => {
    const { control, failures, shown } = schedule();
    control.request(choice('launch'));
    await vi.advanceTimersByTimeAsync(300);
    failures[0](Error('down'));
    await vi.advanceTimersByTimeAsync(0);
    expect(shown.at(-1)).toEqual({ kind: 'failed' });
  });
});

describe('fact line at submission on the feedback page', () => {
  const saved = { ...f17, basis: 'saved' as const, submission: ref('submission', 'sub') };
  const recorded = f17.rule_items.map((entry) =>
    // The recorded feedback comes back from storage with its keys in another order.
    Object.fromEntries(Object.entries(entry).reverse()),
  ) as FeedbackItem[];
  const at = (criterion: string) => {
    const found = f17.rule_items.find((entry) => entry.criterion === criterion);
    if (!found) throw Error(`missing ${criterion}`);
    return found;
  };
  it('names the versions behind an unmet item when the check agrees with the record', () => {
    expect(submissionFactLine(at('R4.functional_tests'), saved, recorded, 'zh')).toBe(
      '交付时：配置 v2 还没测过（配置 v1 测过 1 次）',
    );
    expect(submissionFactLine(at('R4.staleness_test'), saved, recorded, 'en')).toBe(
      'At submission: No retest on config v2 since the policy update (1 retest on config v1)',
    );
  });
  it('adds nothing for a met item', () => {
    expect(submissionFactLine(at('R3.capacity'), saved, recorded, 'zh')).toBeNull();
  });
  it('adds nothing when the recomputed items differ from the record, or the check failed', () => {
    const changed = recorded.map((entry) =>
      entry.criterion === 'R3.resources' ? { ...entry, label: 'NOT_MET' as const } : entry,
    );
    expect(submissionFactLine(at('R4.functional_tests'), saved, changed, 'zh')).toBeNull();
    expect(submissionFactLine(at('R4.functional_tests'), null, recorded, 'zh')).toBeNull();
    expect(submissionFactLine(at('R4.functional_tests'), saved, null, 'zh')).toBeNull();
  });
});
