import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import {
  type ColleagueRun,
  colleagueRun,
  FIXES,
  Decision,
  FixTable,
  type HandBackView,
  notInEffectText,
  skippedText,
} from './hand-back-sheet';
import type { TicketDetail } from './model';

afterEach(() => setPreference('zh'));

const counts = (passed: number, failed: number, unchecked = 0) => ({
  passed,
  failed,
  errors: 0,
  unchecked,
  total: passed + failed + unchecked,
});

// The handover record of the 10-27 real run on the rebuilt candidate: the learner had already
// requested real-time updates without the person-days, so that candidate changed nothing and
// every trial ran with real-time not in effect.
const notInEffect = { update_strategy: 'realtime_sync_not_provisioned' };
const handover: NonNullable<TicketDetail['handover']> = {
  state: 'reported',
  actor: { name: 'Daniel', role_id: 'tech_lead', orchestration: 'rule' },
  rule: {
    id: 'freshness_warn',
    why: 'The target answers cite an older version than the source.',
    changes: { freshness_guard: { before: 'none', after: 'warn' } },
  },
  tried: [
    {
      rule: 'freshness_warn',
      trial_id: 'trial-a',
      changes: { freshness_guard: { before: 'none', after: 'warn' } },
      effective_differences: notInEffect,
      counts: counts(4, 0),
    },
    {
      rule: 'realtime_index',
      trial_id: 'trial-b',
      changes: {},
      effective_differences: notInEffect,
      counts: counts(3, 1),
    },
    {
      rule: 'freshness_fallback',
      trial_id: 'trial-c',
      changes: { freshness_guard: { before: 'none', after: 'fallback' } },
      effective_differences: notInEffect,
      counts: counts(3, 1, 1),
    },
  ],
  skipped: [{ rule: 'lower_min_score', code: 'engineer_setting_not_editable' }],
  review_status: 'verified',
} as NonNullable<TicketDetail['handover']>;

const said = (c: Readonly<Record<string, { before: unknown; after: unknown }>>) =>
  Object.entries(c)
    .map(([k, v]) => `${k} ${v.before} → ${v.after}`)
    .join('; ');

const run = (): ColleagueRun => colleagueRun(handover, { used: 1, limit: 3 }, said);

function view(patch: Partial<HandBackView>): HandBackView {
  const noop = () => {};
  return {
    open: true,
    loading: false,
    error: '',
    signedAt: '',
    fromAgent: false,
    clean: true,
    title: 'Fixed',
    caution: '',
    details: [],
    newFailures: 0,
    fixed: 1,
    publicPassed: 4,
    publicTotal: 4,
    hidden: 0,
    diff: [],
    rows: [],
    fromVersion: 1,
    submitted: false,
    confirm: false,
    applying: false,
    applyError: '',
    conflict: false,
    reloading: false,
    appliedVersion: null,
    colleague: null,
    decided: '',
    onAsk: noop,
    onReturn: noop,
    onRerun: noop,
    onOpenChange: noop,
    onConfirmChange: noop,
    onApply: noop,
    onReload: noop,
    onRetry: noop,
    ...patch,
  };
}

const decode = (html: string) =>
  html.replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&');
const text = (html: string) => decode(html.replace(/<[^>]+>/g, ' ')).replace(/\s+/g, ' ');
const tableOf = (html: string) =>
  decode(html.slice(html.indexOf('<table'), html.indexOf('</table>')));

describe('colleagueRun assembles Daniel’s record by rule id', () => {
  it('keeps each rule id, counts only public checks and structures the skipped', () => {
    const r = run();
    expect(r.tried.map((t) => [t.rule, t.passed, t.total, t.chosen])).toEqual([
      ['freshness_warn', 4, 4, true],
      ['realtime_index', 3, 4, false],
      // The unchecked row only re-asks a handed-over question; it is not a public check.
      ['freshness_fallback', 3, 4, false],
    ]);
    expect(r.tried[1].changes).toBe('');
    // Only the fix whose own setting was not in effect is marked; the others changed theirs.
    expect(r.tried.map((t) => t.notInEffect)).toEqual([
      null,
      'realtime_sync_not_provisioned',
      null,
    ]);
    expect(r.skipped).toEqual([{ rule: 'lower_min_score', code: 'engineer_setting_not_editable' }]);
    expect(r.budget).toEqual({ used: 1, limit: 3 });
  });
});

describe('the fix table', () => {
  it('lists every fix with its step, person-days, what staff see, load and trial (English)', () => {
    setPreference('en');
    const html = renderToStaticMarkup(<FixTable run={run()} />);
    const table = text(tableOf(html));
    expect(html).toContain('What Daniel tried');
    expect(html).toContain('You decide which to use.');
    expect(table).toContain('Fix Changes Person-days Staff will see Load on people Trial');
    expect(table).toContain(
      'Warn when the index lags ● Daniel\'s pick Up to date? No new work item The old answer, prefixed with "the source may have changed" Unchanged Public checks 4/4',
    );
    expect(table).toContain(
      'Rebuild the index on every source change Up to date? · offline Real-time sync, 5 person-days Same as now: this change is not in effect Unchanged Public checks 3/4 Not in effect: real-time sync needs 5 person-days',
    );
    expect(table).toContain(
      'Hand over when the index lags Up to date? → Who takes over No new work item No automatic answer; handed to a person Higher: these questions go to people while the index lags Public checks 3/4',
    );
    expect(table).toContain(
      'Lower the minimum relevance score Found No new work item Finds passages more often, including less relevant ones Fewer handovers, more risk of wrong answers Not tried: this ticket does not allow changing this setting.',
    );
    expect(html).toContain('<caption');
    expect(html).not.toMatch(/[一-鿿]/);
  });

  it('says the same in Chinese', () => {
    setPreference('zh');
    const table = text(tableOf(renderToStaticMarkup(<FixTable run={run()} />)));
    expect(table).toContain('修法 改哪一环 人日 员工会看到 人工负担 试跑');
    expect(table).toContain(
      '索引落后时提醒 ● Daniel 选这个 资料新不新 不需要新工作项 旧答案，前面加一句「资料可能已更新」 不变 公开检查 4/4',
    );
    expect(table).toContain(
      '源文件一变就重建索引 资料新不新 · 离线 实时同步 5 人日 和现在一样：这项改动还没生效 不变 公开检查 3/4 还没生效：实时同步要 5 人日',
    );
    expect(table).toContain(
      '索引落后时转人工 资料新不新 → 答不了谁接 不需要新工作项 不自动回答，转给人工 增加：索引落后期间这类问题都转人工',
    );
    expect(table).toContain('降低最低相关分 找到什么 不需要新工作项 更容易找到段落，也更可能找到不相关的 转人工可能减少，错答风险上升');
  });

  it('keeps a fix that changed nothing, with no record of what was in effect, as it was', () => {
    setPreference('en');
    const older = {
      ...handover,
      tried: handover.tried?.map(({ effective_differences: _, ...t }) => t),
    } as NonNullable<TicketDetail['handover']>;
    const table = text(
      tableOf(renderToStaticMarkup(<FixTable run={colleagueRun(older, { used: 1, limit: 3 }, said)} />)),
    );
    expect(table).toContain(
      'Answers from the latest source Unchanged Public checks 3/4 No change: the settings already request this value',
    );
    expect(table).not.toContain('Not in effect');
  });

  it('names what any other setting not in effect still needs', () => {
    setPreference('en');
    expect(notInEffectText('realtime_sync_not_provisioned')).toBe(
      'Not in effect: real-time sync needs 5 person-days',
    );
    expect(notInEffectText('scope_filter_not_provisioned')).toBe(
      'Not in effect: this setting is not approved yet',
    );
    setPreference('zh');
    expect(notInEffectText('realtime_sync_not_provisioned')).toBe('还没生效：实时同步要 5 人日');
  });

  it('marks only the chosen row and greys a skipped one', () => {
    setPreference('en');
    const table = tableOf(renderToStaticMarkup(<FixTable run={run()} />));
    expect(table.match(/Daniel's pick/g)).toHaveLength(1);
    expect(table.match(/inset_2px_0_0_var\(--ink\)/g)).toHaveLength(1);
    const skipped = table.slice(table.lastIndexOf('<tr'));
    expect(skipped).toContain('tw:text-ink-3');
    expect(skipped).toContain('Lower the minimum relevance score');
  });

  it('says why a fix was not tried, never "not allowed here"', () => {
    setPreference('en');
    expect(skippedText('engineer_setting_not_editable')).toBe(
      'Not tried: this ticket does not allow changing this setting.',
    );
    expect(skippedText('engineer_setting_value_invalid')).toBe('Not tried: this value is not valid here.');
    expect(skippedText('other_code')).toBe('Not tried: other_code');
    setPreference('zh');
    expect(skippedText('engineer_setting_not_editable')).toBe('没试：这张委托不允许改这项设置。');
    expect(skippedText('engineer_setting_value_invalid')).toBe('没试：这个取值在当前场景无效。');
    const html = renderToStaticMarkup(<FixTable run={run()} />);
    expect(html).not.toContain('这个场景不允许');
  });

  it('covers every rule Daniel can try', () => {
    expect(Object.keys(FIXES).sort()).toEqual(
      ['freshness_fallback', 'freshness_warn', 'lower_min_score', 'realtime_index'].sort(),
    );
  });
});

describe('the decision under the report', () => {
  const decision = (patch: Partial<HandBackView>) =>
    text(renderToStaticMarkup(<Decision v={view(patch)} />));

  it('for Daniel’s report says applying makes a new version, above apply, ask and return', () => {
    setPreference('en');
    const html = decision({ colleague: run(), rows: [{ field: 'freshness_guard', name: 'When outdated', current: 'none', next: 'warn', value: 'warn' }] });
    expect(html).toContain(
      'Applying creates a new configuration version. Rerun the same question on the test bench to compare. Update pilot settings from this review Ask Daniel Return it',
    );
    setPreference('zh');
    expect(decision({ colleague: run() })).toContain('应用后会生成新的配置版本；回测试台同题重测，前后对照。');
  });

  it('after applying Daniel’s report offers the rerun on the test bench', () => {
    setPreference('en');
    const html = decision({ colleague: run(), appliedVersion: 3 });
    expect(html).toContain('Pilot updated from this review · configuration v3 Rerun on the test bench');
    expect(html).not.toContain('Applying creates');
  });

  it('keeps the engineer’s own report as it was', () => {
    setPreference('en');
    expect(decision({ colleague: null })).not.toContain('Applying creates');
    expect(decision({ colleague: null })).toContain('Not now');
    expect(decision({ colleague: null, appliedVersion: 3 })).not.toContain('Rerun on the test bench');
    expect(renderToStaticMarkup(<FixTable run={run()} />)).toContain('What Daniel tried');
  });
});
