// S9 · The engineering review on the product manager's side (plan §13.11): a report sheet that
// slides in from the right over the main screen, and "Update pilot settings from this review",
// which confirms in a dialog and sends the existing configuration.apply. The engineer never applies
// anything; the product manager decides. A delivered practice first opens a revision.
import { Dialog } from 'radix-ui';
import { Fragment, type Ref, useRef } from 'react';
import { T } from '../../app/i18n';
import { Button, Sheet, SheetContent, SheetDescription, SheetTitle } from '../../ui-kit';
import { WORK_COST } from '../../app/vocab';
import type { HandBackRow } from './hand-back';
import type { DiffRow, TicketDetail } from './model';

export interface HandBackView {
  readonly open: boolean;
  readonly loading: boolean;
  readonly error: string;
  readonly signedAt: string;
  /** The signed draft came from the engineer's agent. */
  readonly fromAgent: boolean;
  /** Everything holds (the mark is green only then). */
  readonly clean: boolean;
  /** What the review came to: the report headline's sentence. */
  readonly title: string;
  /** What comes with updating from a review that is not clean ('' when clean). */
  readonly caution: string;
  readonly details?: readonly {label: string; text: string}[];
  readonly newFailures: number;
  readonly fixed: number;
  readonly publicPassed: number;
  readonly publicTotal: number;
  readonly hidden: number;
  readonly diff: readonly DiffRow[];
  /** Settings that differ from the pilot now; null until read. */
  readonly rows: readonly HandBackRow[] | null;
  readonly fromVersion: number | null;
  readonly submitted: boolean;
  readonly confirm: boolean;
  readonly applying: boolean;
  readonly applyError: string;
  /** The pilot changed meanwhile: read it again before confirming. */
  readonly conflict: boolean;
  readonly reloading: boolean;
  readonly appliedVersion: number | null;
  /** Daniel signed it (a product manager's practice): his run, shown as the log of what he did. */
  readonly colleague: ColleagueRun | null;
  /** The person's own decision on it, recorded on the server ('' until one). */
  readonly decided: string;
  onAsk(): void;
  onReturn(): void;
  /** After applying Daniel's report: close and rerun on the test bench. */
  onRerun(): void;
  onOpenChange(open: boolean): void;
  onConfirmChange(open: boolean): void;
  onApply(): void;
  onReload(): void;
  onRetry(): void;
}

export interface ColleagueRun {
  readonly name: string;
  /** Why the chosen change, in the rule's own words. */
  readonly why: string;
  /** Each candidate he tried: its rule, the settings it changed ('' when none) and its checks. */
  readonly tried: readonly {
    rule: string;
    changes: string;
    /** Why the setting this fix changes was not in effect in its trial (a server code), or null. */
    notInEffect: string | null;
    passed: number;
    total: number;
    chosen: boolean;
  }[];
  /** Candidates the rule table offered that could not be tried here, with the server's code. */
  readonly skipped: readonly { rule: string; code: string }[];
  readonly reviewStatus: string;
  readonly budget: { readonly used: number; readonly limit: number };
}

type Pair = readonly [string, string];
const t2 = (p: Pair) => T(p[0], p[1]);
const NO_WORK: Pair = ['不需要新工作项', 'No new work item'];
const SAME_LOAD: Pair = ['不变', 'Unchanged'];

/** What each of Daniel's candidate fixes costs, by rule id: the same for every practice. */
export const FIXES: Record<
  string,
  { field: string; name: Pair; step: Pair; days: () => string; staff: Pair; load: Pair }
> = {
  freshness_warn: {
    field: 'freshness_guard',
    name: ['索引落后时提醒', 'Warn when the index lags'],
    step: ['资料新不新', 'Up to date?'],
    days: () => t2(NO_WORK),
    staff: [
      '旧答案，前面加一句「资料可能已更新」',
      'The old answer, prefixed with "the source may have changed"',
    ],
    load: SAME_LOAD,
  },
  realtime_index: {
    field: 'update_strategy',
    name: ['源文件一变就重建索引', 'Rebuild the index on every source change'],
    step: ['资料新不新 · 离线', 'Up to date? · offline'],
    days: () =>
      T(`实时同步 ${WORK_COST.realtime} 人日`, `Real-time sync, ${WORK_COST.realtime} person-days`),
    staff: ['按最新资料回答', 'Answers from the latest source'],
    load: SAME_LOAD,
  },
  freshness_fallback: {
    field: 'freshness_guard',
    name: ['索引落后时转人工', 'Hand over when the index lags'],
    step: ['资料新不新 → 答不了谁接', 'Up to date? → Who takes over'],
    days: () => t2(NO_WORK),
    staff: ['不自动回答，转给人工', 'No automatic answer; handed to a person'],
    load: [
      '增加：索引落后期间这类问题都转人工',
      'Higher: these questions go to people while the index lags',
    ],
  },
  lower_min_score: {
    field: 'min_score',
    name: ['降低最低相关分', 'Lower the minimum relevance score'],
    step: ['找到什么', 'Found'],
    days: () => t2(NO_WORK),
    staff: [
      '更容易找到段落，也更可能找到不相关的',
      'Finds passages more often, including less relevant ones',
    ],
    load: ['转人工可能减少，错答风险上升', 'Fewer handovers, more risk of wrong answers'],
  },
};
export const ruleName = (id: string) => (FIXES[id] ? t2(FIXES[id].name) : id);

/** A trial whose setting was requested but not in effect: what it would take. */
export function notInEffectText(code: string): string {
  if (code === 'realtime_sync_not_provisioned')
    return T(
      `还没生效：实时同步要 ${WORK_COST.realtime} 人日`,
      `Not in effect: real-time sync needs ${WORK_COST.realtime} person-days`,
    );
  return T('还没生效：这项设置还没批到', 'Not in effect: this setting is not approved yet');
}

/** Why a candidate was not tried, from the server's error code. */
export function skippedText(code: string): string {
  if (code === 'engineer_setting_not_editable')
    return T('没试：这张委托不允许改这项设置。', 'Not tried: this ticket does not allow changing this setting.');
  if (code === 'engineer_setting_value_invalid')
    return T('没试：这个取值在当前场景无效。', 'Not tried: this value is not valid here.');
  return T(`没试：${code}`, `Not tried: ${code}`);
}

/** Daniel's run as the sheet shows it, from his ticket's handover record. Trial counts are the
 * public checks: rows that only re-ask a handed-over question are unchecked and left out. */
export function colleagueRun(
  h: NonNullable<TicketDetail['handover']>,
  budget: ColleagueRun['budget'],
  said: (c: Readonly<Record<string, { before: unknown; after: unknown }>>) => string,
): ColleagueRun {
  return {
    name: h.actor?.name ?? 'Daniel',
    why: h.rule?.why ?? '',
    tried: (h.tried ?? []).map((t) => ({
      rule: t.rule,
      changes: said(t.changes),
      notInEffect: t.effective_differences?.[FIXES[t.rule]?.field ?? ''] ?? null,
      passed: t.counts.passed,
      total: t.counts.passed + t.counts.failed + t.counts.errors,
      chosen: t.rule === h.rule?.id,
    })),
    skipped: (h.skipped ?? []).map((x) => ({ rule: x.rule, code: x.code })),
    reviewStatus: h.review_status ?? '',
    budget,
  };
}

interface FixRow {
  readonly rule: string;
  readonly chosen: boolean;
  /** The trial reading ("Public checks 3/4"), or a dash when it was not tried. */
  readonly trial: string;
  /** The line under the fix: why it was not tried, its setting not in effect, or that it changed
   * nothing because the settings already request its value. */
  readonly note: string;
  readonly skipped: boolean;
  /** Its setting was not in effect in the trial, so staff would see what they see now. */
  readonly inert: boolean;
}

function fixRows(run: ColleagueRun): FixRow[] {
  return [
    ...run.tried.map((t) => ({
      rule: t.rule,
      chosen: t.chosen,
      trial: T(`公开检查 ${t.passed}/${t.total}`, `Public checks ${t.passed}/${t.total}`),
      note: t.notInEffect
        ? notInEffectText(t.notInEffect)
        : t.changes
          ? ''
          : T('没有改动：设置里已经请求了这个值', 'No change: the settings already request this value'),
      skipped: false,
      inert: !!t.notInEffect,
    })),
    // Not tried: no reading in the trial column; why it was not tried is the line under it.
    ...run.skipped.map((x) => ({
      rule: x.rule,
      chosen: false,
      trial: '—',
      note: skippedText(x.code),
      skipped: true,
      inert: false,
    })),
  ];
}

/** Person-days never break between the amount and its unit ("5 / person-days"). */
const Days = ({ text }: { text: string }) => {
  const m = /^(.*?)(\d+ \S+)$/.exec(text);
  if (!m) return text;
  return (
    <>
      {m[1]}
      <span className="tw:whitespace-nowrap">{m[2]}</span>
    </>
  );
};

const Pick = () => (
  <span className="tw:block tw:text-[11.5px] tw:font-semibold tw:text-ink">
    <span aria-hidden="true">● </span>
    {T('Daniel 选这个', "Daniel's pick")}
  </span>
);

/** Daniel's report, opened on what he tried: each fix with the step it changes, what it costs in
 * person-days, what staff will see, the load on people and its trial. A wide panel reads it as a
 * table; a narrow one as one card per fix. The choice of fix stays with the person. */
export function FixTable({ run }: { run: ColleagueRun }) {
  const rows = fixRows(run);
  const fix = (r: FixRow) => FIXES[r.rule];
  const cell = (r: FixRow, pick: (f: (typeof FIXES)[string]) => string) => {
    const f = fix(r);
    return f ? pick(f) : '—';
  };
  // A fix whose setting was not in effect left the answers as they are now.
  const staff = (r: FixRow) =>
    r.inert ? T('和现在一样：这项改动还没生效', 'Same as now: this change is not in effect') : cell(r, (f) => t2(f.staff));
  const head = [
    T('修法', 'Fix'),
    T('改哪一环', 'Changes'),
    T('人日', 'Person-days'),
    T('员工会看到', 'Staff will see'),
    T('人工负担', 'Load on people'),
    T('试跑', 'Trial'),
  ];
  const th = 'tw:px-2 tw:pb-2 tw:text-left tw:align-bottom tw:text-[11.5px] tw:font-semibold tw:text-ink-3';
  // A row with a note keeps its bottom padding for the note line under it.
  const td = (r: FixRow) => `tw:px-2 tw:align-top ${r.note ? 'tw:pt-2.5 tw:pb-1' : 'tw:py-2.5'}`;
  const bar = 'tw:shadow-[inset_2px_0_0_var(--ink)]';
  return (
    <section className="tw:@container tw:grid tw:gap-3 tw:p-4 tw:rounded-panel tw:bg-fill">
      <header className="tw:grid tw:gap-0.5">
        <h3 className="tw:m-0 tw:text-[13px] tw:font-semibold tw:text-ink">
          {T(`${run.name} 试了这几种修法`, `What ${run.name} tried`)}
        </h3>
        <p className="tw:m-0 tw:text-[12.5px] tw:text-ink-2">
          {T(
            '用哪一个由你决定。试跑包含交出的题和公开检查。',
            'You decide which to use. Trials include the tests you handed over and public checks.',
          )}
        </p>
      </header>
      <table className="tw:@max-[720px]:hidden tw:w-full tw:border-collapse tw:text-[13px] tw:leading-snug">
        <caption className="tw:sr-only">
          {T(`${run.name} 试过的修法及各自的代价`, `The fixes ${run.name} tried and what each costs`)}
        </caption>
        <thead>
          <tr>
            {head.map((h, i) => (
              <th
                key={h}
                scope="col"
                className={i === 5 ? `${th} tw:text-right` : i === 2 ? `${th} tw:min-w-[9em]` : th}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <Fragment key={r.rule}>
              <tr
                className={`tw:h-10 tw:border-0 tw:border-t tw:border-solid tw:border-line ${r.skipped ? 'tw:text-ink-3' : 'tw:text-ink-2'}`}
              >
                <th
                  scope="row"
                  className={`${td(r)} tw:text-left tw:font-normal ${r.chosen ? `${bar} tw:font-semibold tw:text-ink` : ''}`}
                >
                  {ruleName(r.rule)}
                  {r.chosen && <Pick />}
                </th>
                <td className={td(r)}>{cell(r, (f) => t2(f.step))}</td>
                <td className={td(r)}>
                  <Days text={cell(r, (f) => f.days())} />
                </td>
                <td className={td(r)}>{staff(r)}</td>
                <td className={td(r)}>{cell(r, (f) => t2(f.load))}</td>
                <td className={`${td(r)} tw:text-right tw:tabular-nums tw:whitespace-nowrap`}>
                  {r.trial}
                </td>
              </tr>
              {r.note && (
                // The trial's note reads as a line of its own under the fix, across the row.
                <tr>
                  <td
                    colSpan={6}
                    className={`tw:px-2 tw:pt-0 tw:pb-2.5 tw:text-[13px] tw:text-ink-3 ${r.chosen ? bar : ''}`}
                  >
                    {r.note}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      <ul className="tw:hidden tw:@max-[720px]:grid tw:m-0 tw:p-0 tw:list-none tw:gap-2">
        {rows.map((r) => (
          <li
            key={r.rule}
            className={`tw:grid tw:gap-2 tw:p-3 tw:rounded-[7px] tw:bg-inst ${r.chosen ? bar : ''} ${r.skipped ? 'tw:text-ink-3' : 'tw:text-ink-2'}`}
          >
            <div className="tw:grid tw:grid-cols-[minmax(0,1fr)_auto] tw:items-start tw:gap-x-4">
              <span className={r.chosen ? 'tw:text-[13px] tw:font-semibold tw:text-ink' : 'tw:text-[13px]'}>
                {ruleName(r.rule)}
                {r.chosen && <Pick />}
              </span>
              <span className="tw:text-[12.5px] tw:tabular-nums tw:whitespace-nowrap">{r.trial}</span>
            </div>
            {r.note && <p className="tw:m-0 tw:text-[12.5px] tw:text-ink-3">{r.note}</p>}
            <dl className="tw:m-0 tw:grid tw:grid-cols-2 tw:items-start tw:gap-x-4 tw:gap-y-1.5 tw:text-[12px]">
              {(
                [
                  [head[1], cell(r, (f) => t2(f.step))],
                  [head[2], <Days key="days" text={cell(r, (f) => f.days())} />],
                  [head[3], staff(r)],
                  [head[4], cell(r, (f) => t2(f.load))],
                ] as const
              ).map(([k, v]) => (
                <div key={k} className="tw:grid tw:content-start tw:gap-0.5">
                  <dt className="tw:text-[11px] tw:text-ink-3">{k}</dt>
                  <dd className="tw:m-0">{v}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
      <p className="tw:m-0 tw:text-[12px] tw:text-ink-3">
        {T(
          `${run.name}（规则编排）先在原快照上复现交来的题，再逐个试跑，最后签字。复核第 ${run.budget.used} 次，共 ${run.budget.limit} 次。`,
          `${run.name} (rule orchestration) reproduced the handed-over tests on their original snapshot, ran each trial, then signed the review. Review ${run.budget.used} of ${run.budget.limit}.`,
        )}
      </p>
      <p className="tw:m-0 tw:text-[13px] tw:text-ink-2">
        <span className="tw:text-ink-3">{T('为什么选这个改动：', 'Why this change: ')}</span>
        {run.why}
      </p>
    </section>
  );
}

const Mark = ({ clean }: { clean: boolean }) => (
  <span
    aria-hidden="true"
    className={
      clean
        ? 'tw:grid tw:place-items-center tw:size-9 tw:rounded-full tw:border-[1.5px] tw:border-good tw:bg-good-tint tw:text-good tw:text-[16px]'
        : 'tw:grid tw:place-items-center tw:size-9 tw:rounded-full tw:border-[1.5px] tw:border-warn tw:text-warn tw:text-[16px]'
    }
  >
    {clean ? '✓' : '↓'}
  </span>
);

function Diff({ rows }: { rows: readonly { name: string; before: string; after: string }[] }) {
  return (
    <ul className="tw:m-0 tw:p-0 tw:list-none tw:grid tw:gap-1.5">
      {rows.map((r) => (
        <li
          key={r.name}
          className="tw:flex tw:flex-wrap tw:items-baseline tw:gap-x-3 tw:text-[13.5px]"
        >
          <span className="tw:text-ink-2 tw:min-w-[9rem]">{r.name}</span>
          <span className="tw:inline-flex tw:items-baseline tw:gap-1.5">
            <del className="tw:text-ink-3">{r.before}</del>
            <span aria-hidden="true" className="tw:text-ink-4">
              →
            </span>
            <b className="tw:text-ink tw:font-semibold">{r.after}</b>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The decision under the report: update from it (after confirming), or for Daniel's report ask
 * or return it; once applied, the new version and, for Daniel's, the way back to rerun. */
export function Decision({ v, trigger }: { v: HandBackView; trigger?: Ref<HTMLButtonElement> }) {
  const nothing = v.rows !== null && v.rows.length === 0;
  return (
    <footer className="tw:flex tw:flex-wrap tw:items-center tw:gap-2 tw:pt-2 tw:border-0 tw:border-t tw:border-solid tw:border-line">
      {v.colleague && v.appliedVersion === null && (
        <p className="tw:m-0 tw:basis-full tw:pb-1 tw:text-[13px] tw:text-ink-2">
          {T(
            '应用后会生成新的配置版本；回测试台同题重测，前后对照。',
            'Applying creates a new configuration version. Rerun the same question on the test bench to compare.',
          )}
        </p>
      )}
      {v.appliedVersion !== null ? (
        <>
          <p className="tw:m-0 tw:text-good tw:text-[14px] tw:font-medium">
            ✓{' '}
            {T(
              `已按这份改动更新试点 · 配置 v${v.appliedVersion}`,
              `Pilot updated from this review · configuration v${v.appliedVersion}`,
            )}
          </p>
          {v.colleague && (
            <Button variant="secondary" onClick={v.onRerun}>
              {T('回测试台重测', 'Rerun on the test bench')}
            </Button>
          )}
        </>
      ) : (
        <>
          <Button
            ref={trigger}
            variant="primary"
            disabled={v.rows === null || nothing}
            reason={
              nothing
                ? T('试点已经是这组设置', 'The pilot already has these settings')
                : undefined
            }
            onClick={() => v.onConfirmChange(true)}
          >
            {T('按这份改动更新试点设置', 'Update pilot settings from this review')}
          </Button>
          {v.colleague ? (
            <>
              <Button variant="secondary" onClick={v.onAsk}>
                {T('追问 Daniel', 'Ask Daniel')}
              </Button>
              <Button variant="ghost" disabled={v.decided === 'return'} onClick={v.onReturn}>
                {v.decided === 'return' ? T('已退回', 'Returned') : T('退回', 'Return it')}
              </Button>
            </>
          ) : (
            <Button variant="ghost" onClick={() => v.onOpenChange(false)}>
              {T('先不更新', 'Not now')}
            </Button>
          )}
        </>
      )}
    </footer>
  );
}

export function HandBackSheet(v: HandBackView) {
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const nextVersion = (v.fromVersion ?? 1) + 1;
  const title = v.title;
  return (
    <Sheet open={v.open} onOpenChange={v.onOpenChange}>
      <SheetContent
        side="right"
        // Daniel's report leads with a six-column table of fixes; it needs the wider panel.
        className={`${v.colleague ? 'tw:w-[min(880px,100%)]' : 'tw:w-[min(640px,100%)]'} tw:overflow-y-auto`}
      >
        <div className="tw:grid tw:gap-6 tw:p-8 tw:max-sm:p-5">
          <header className="tw:grid tw:gap-1">
            <SheetDescription className="tw:m-0 tw:text-[12px] tw:text-ink-3">
              {v.colleague
                ? T(
                    `工程复核报告 · 签字人：${v.colleague.name}（技术负责人 · AI 同事 · 规则编排）· ${v.signedAt}`,
                    `Engineering review · signed by ${v.colleague.name} (technical lead · AI colleague · rule orchestration) · ${v.signedAt}`,
                  )
                : T(
                    `工程复核报告 · 签字人：你（工程师）${v.fromAgent ? ' · 草稿来自你的 Agent' : ''} · ${v.signedAt}`,
                    `Engineering review · signed by you (engineer)${v.fromAgent ? ' · draft from your agent' : ''} · ${v.signedAt}`,
                  )}
            </SheetDescription>
            <div className="tw:flex tw:items-start tw:gap-3.5 tw:mt-2">
              <Mark clean={v.clean} />
              <SheetTitle className="tw:m-0 tw:font-sans tw:text-[22px] tw:leading-tight tw:font-semibold">
                {title}
              </SheetTitle>
            </div>
          </header>
          {v.loading ? (
            <p className="tw:m-0 tw:text-ink-3">{T('正在读取复核…', 'Reading the review…')}</p>
          ) : v.error ? (
            <div className="tw:flex tw:items-center tw:gap-3">
              <p className="tw:m-0 tw:text-bad tw:text-[13px]">{v.error}</p>
              <Button variant="ghost" onClick={v.onRetry}>
                {T('重试', 'Try again')}
              </Button>
            </div>
          ) : (
            <>
              {v.colleague && <FixTable run={v.colleague} />}
              <section className="tw:grid tw:gap-2">
                <h3 className="tw:m-0 tw:text-[12.5px] tw:font-semibold tw:text-ink-2">
                  {T('改动', 'The change')}
                </h3>
                <Diff rows={v.diff} />
              </section>
              <dl className="tw:m-0 tw:grid tw:gap-3">
                {(v.details ?? []).map((row) => (
                  // Labels such as "Target verification" fit on one line; a narrow screen stacks.
                  <div
                    key={row.label}
                    className="tw:grid tw:grid-cols-[160px_1fr] tw:gap-3 tw:text-[13px] tw:max-[720px]:grid-cols-1 tw:max-[720px]:gap-[3px]"
                  >
                    <dt className="tw:text-ink-2">{row.label}</dt>
                    <dd className="tw:m-0">{row.text}</dd>
                  </div>
                ))}
              </dl>
              <Decision v={v} trigger={trigger} />
            </>
          )}
        </div>
      </SheetContent>
      <Dialog.Root open={v.confirm} onOpenChange={(open) => !v.applying && v.onConfirmChange(open)}>
        <Dialog.Portal>
          <Dialog.Overlay className="rc-portal rc-sheet-scrim tw:fixed tw:inset-0 tw:z-[90] tw:bg-[var(--scrim-b)]" />
          <Dialog.Content
            // Opening reads from the top: the title takes focus (no ring), not the first key.
            onOpenAutoFocus={(e) => {
              e.preventDefault();
              heading.current?.focus({ preventScroll: true });
            }}
            onCloseAutoFocus={(e) => {
              e.preventDefault();
              trigger.current?.focus();
            }}
            className="rc-portal ed-confirm tw:fixed tw:z-[91] tw:left-1/2 tw:top-1/2 tw:w-[min(480px,calc(100%-32px))] tw:-translate-x-1/2 tw:-translate-y-1/2 tw:grid tw:gap-4 tw:p-6 tw:rounded-dialog tw:bg-inst tw:shadow-float tw:outline-none"
          >
            <Dialog.Title
              ref={heading}
              tabIndex={-1}
              className="tw:m-0 tw:font-sans tw:text-[17px] tw:font-semibold tw:outline-none"
            >
              {T('按工程复核更新试点', 'Update the pilot from the engineering review')}
            </Dialog.Title>
            {v.rows && (
              <Diff
                rows={v.rows.map((r) => ({ name: r.name, before: r.current, after: r.next }))}
              />
            )}
            <Dialog.Description className="tw:m-0 tw:text-[13.5px] tw:text-ink-2">
              {T(
                `试点配置会从 v${v.fromVersion ?? 1} 升到 v${nextVersion}，知识助手之后按新设置回答。`,
                `The pilot configuration goes from v${v.fromVersion ?? 1} to v${nextVersion}; the assistant answers with the new settings from then on.`,
              )}
            </Dialog.Description>
            {v.submitted && (
              <p className="tw:m-0 tw:text-[13.5px] tw:text-ink-2">
                {T(
                  '这一局已经交付。更新试点前先开一轮修订：交付记录和反馈都会保留。',
                  'This practice is delivered. Updating the pilot opens a revision first; your delivery and feedback stay.',
                )}
              </p>
            )}
            {v.caution && <p className="tw:m-0 tw:text-[13.5px] tw:text-warn">{v.caution}</p>}
            {v.applyError && (
              <p role="alert" className="tw:m-0 tw:text-bad tw:text-[13px]">
                {v.applyError}
              </p>
            )}
            <div className="tw:flex tw:justify-end tw:gap-2">
              <Dialog.Close asChild>
                <Button variant="ghost" disabled={v.applying || v.reloading}>
                  {T('取消', 'Cancel')}
                </Button>
              </Dialog.Close>
              {v.conflict ? (
                // The pilot changed meanwhile: read it again (the list above follows), then confirm.
                <Button
                  variant="secondary"
                  state={v.reloading ? 'loading' : 'idle'}
                  onClick={v.onReload}
                >
                  {T('重新读取', 'Read again')}
                </Button>
              ) : null}
              <Button
                variant="primary"
                state={v.applying ? 'loading' : 'idle'}
                disabled={v.conflict || v.reloading || !v.rows?.length}
                reason={
                  v.conflict
                    ? T('先重新读取试点设置', 'Read the pilot settings again first')
                    : v.rows && !v.rows.length
                      ? T('试点已经是这组设置', 'The pilot already has these settings')
                      : undefined
                }
                onClick={v.onApply}
              >
                {v.applyError && !v.conflict
                  ? T('重试', 'Try again')
                  : v.submitted
                    ? T('开始修订并更新', 'Open a revision and update')
                    : T(`更新为 v${nextVersion}`, `Update to v${nextVersion}`)}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </Sheet>
  );
}
