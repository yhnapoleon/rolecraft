/** Back to the product manager (plan §7, §13.11): what a review came to, in the one sentence the
 * report headline, the board's signal and the product manager's report sheet all say; and the
 * reviewed change as an update of the pilot (`handBackChanges` listed in the confirm dialog,
 * `handBackCommand` sent through the existing `configuration.apply`). The engineer never applies
 * anything to the pilot. Pure logic. */
import { ApiError } from '../../api';
import { T } from '../../app/i18n';
import type { AssistantConfig } from '../../contracts-v2';
import type { SettingsInput } from '../../v4-host-operations';
import { engineerReportView, type EngineerReviewRecord } from '../engineer-report';
import { reviewViewOptions } from '../engineer-report/page';
import { failureText } from './api';
import { fieldName, valueText } from './copy';
import type { HandedBack } from './local-state';
import type { Change, JsonValue } from './model';

/** Why the product manager reopens a delivered practice to take the review in: their own words,
 * since the board's revision note quotes it back ("You said: '…'"). */
export const revisionReason = () =>
  T('把工程复核修好的设置更新到试点', 'put the engineering fix into the pilot');

/* ---------- what a review came to ---------- */

/** A signed review's result: whether the target is fixed, how many checks newly fail (public and
 * hidden), and whether the comparison with the baseline finished. */
export interface ReviewResult {
  readonly target: 'fixed' | 'not_fixed' | 'partial' | 'unknown';
  readonly newFailures: number;
  readonly compared: boolean;
}

export function reviewResult(record: EngineerReviewRecord, language: 'zh' | 'en'): ReviewResult {
  const view = engineerReportView(record.report, reviewViewOptions(record, language));
  const state = view.verdict?.state;
  const regression = view.checks.lines.find((l) => l.kind === 'new_regression');
  const publicNew = new Set(
    record.report.findings
      .filter((f) => f.kind === 'new_regression' && f.status === 'fail')
      .flatMap((f) => f.probe_ids),
  ).size;
  return {
    target: state === 'fixed' || state === 'not_fixed' || state === 'partial' ? state : 'unknown',
    newFailures: publicNew + Math.max(0, record.report.hidden_comparison?.new_failures ?? 0),
    compared: !!regression && regression.tone !== 'unknown',
  };
}

/** Everything holds: the target is fixed, the comparison finished, nothing newly fails. */
export const outcomeClean = (r: ReviewResult) =>
  r.target === 'fixed' && r.compared && r.newFailures === 0;

const failures = (n: number) => (n === 1 ? 'failure' : 'failures');

/** The one sentence (the report's headline says the same). */
export function outcomeSentence(r: ReviewResult): string {
  const lead = {
    fixed: T('目标修好了', 'Target fixed'),
    partial: T('目标部分修好', 'Target partly fixed'),
    not_fixed: T('目标没修好', 'Target not fixed'),
    unknown: T('还不知道目标是否修好', 'Not known yet whether the target is fixed'),
  }[r.target];
  const n = r.newFailures;
  if (n > 0)
    return r.target === 'fixed' || r.target === 'partial'
      ? T(`${lead}，但新增 ${n} 处失败`, `${lead}, but ${n} new ${failures(n)}`)
      : T(`${lead}，另有 ${n} 处新增失败`, `${lead}, and ${n} new ${failures(n)}`);
  if (r.target !== 'fixed') return lead;
  return r.compared
    ? T(`${lead}，没有新增失败`, `${lead}, nothing new fails`)
    : T(`${lead}，还不知道有没有新增失败`, `${lead}; not yet known whether anything new fails`);
}

/** Before the product manager updates the pilot from a review that is not clean: what comes with it. */
export function outcomeCaution(r: ReviewResult): string {
  if (outcomeClean(r)) return '';
  if (r.newFailures > 0)
    return T(
      `这份复核有 ${r.newFailures} 处新增失败，更新后它会带进试点。`,
      `This review has ${r.newFailures} new ${failures(r.newFailures)}; updating brings it into the pilot.`,
    );
  if (r.target === 'unknown') return T('目标是否修好仍未决；更新设置不能证明目标已修复。', 'The target is still unverified; applying settings does not prove it is fixed.');
  if (r.target !== 'fixed')
    return T(
      '这份复核里目标没修好，更新试点也修不好它。',
      'In this review the target is not fixed; updating does not fix it in the pilot.',
    );
  return T(
    '这份复核没能查完有没有新增失败。',
    'This review could not finish checking for new failures.',
  );
}

/** The product board's line for a review handed back (drawn by the board line, 204): a kicker,
 * the conclusion as short as it goes, and a tone. The subject follows the ticket's source. */
export function handBackSignal(back: HandedBack): {
  kicker: string;
  text: string;
  tone: 'good' | 'warn';
} {
  const kicker = back.colleague
    ? T(
        `工程复核 · ${back.colleague}（AI 同事）签的`,
        `Engineering review · signed by ${back.colleague} (AI colleague)`,
      )
    : T('工程复核 · 你签的', 'Engineering review · signed by you');
  if (back.appliedVersion)
    return {
      kicker,
      text: T(`试点已更新到 v${back.appliedVersion}`, `Pilot updated to v${back.appliedVersion}`),
      tone: 'good',
    };
  const subject =
    back.title === 'tests'
      ? T('交来的测试', 'The handed-over tests')
      : T('住宿上限', 'Hotel limit');
  // Kept before the result was: only "clean" and a count of new failures are known.
  const r: ReviewResult | null =
    back.result ??
    (back.clean
      ? { target: 'fixed', newFailures: 0, compared: true }
      : back.newFailures > 0
        ? { target: 'fixed', newFailures: back.newFailures, compared: true }
        : null);
  if (!r)
    return { kicker, text: T(`${subject}：没有全过`, `${subject}: not all clear`), tone: 'warn' };
  const n = r.newFailures;
  const news = T(`新增 ${n} 处失败`, `${n} new ${failures(n)}`);
  const state =
    r.target === 'fixed'
      ? T(`${subject}已修好`, `${subject} fixed`)
      : r.target === 'partial'
        ? T(`${subject}部分修好`, `${subject} partly fixed`)
        : r.target === 'not_fixed'
          ? T(`${subject}没修好`, `${subject} not fixed`)
          : '';
  let text: string;
  if (n > 0 && state) text = `${state} · ${news}`;
  else if (!state)
    text = T(`${subject}：目标是否修好仍未决`, `${subject}: target still unverified`);
  else if (!r.compared)
    text = T(`${state} · 回归比较未完成`, `${state} · regression comparison incomplete`);
  else if (r.target === 'fixed')
    text = T(`${state} · 没有新增失败`, `${state} · nothing new fails`);
  else text = state;
  return { kicker, text, tone: outcomeClean(r) ? 'good' : 'warn' };
}

/** A failed update of the pilot: a pilot changed meanwhile is read again before confirming. */
export function applyFailure(error: unknown): { conflict: boolean; text: string } {
  if (
    error instanceof ApiError &&
    error.status === 409 &&
    (error.code === 'object_version_conflict' || error.code === 'version_conflict')
  )
    return {
      conflict: true,
      text: T(
        '试点设置刚刚变过。重新读取后再确认。',
        'The pilot settings just changed. Read them again, then confirm.',
      ),
    };
  return { conflict: false, text: failureText(error) };
}

/* ---------- updating the pilot ---------- */

export interface HandBackRow {
  readonly field: string;
  readonly name: string;
  /** The pilot's value now, in words. */
  readonly current: string;
  /** The reviewed value, in words. */
  readonly next: string;
  /** The reviewed value as sent. */
  readonly value: JsonValue;
}

const same = (a: unknown, b: unknown) => {
  if (Array.isArray(a) && Array.isArray(b))
    return JSON.stringify([...a].map(String).sort()) === JSON.stringify([...b].map(String).sort());
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
};

type Pilot = Partial<AssistantConfig> & Pick<AssistantConfig, 'id' | 'session_id'>;

/** The reviewed changes that differ from the pilot as it is now. */
export function handBackChanges(
  changes: Readonly<Record<string, Change>>,
  pilot: Pilot,
): HandBackRow[] {
  const current = pilot as unknown as Record<string, JsonValue | undefined>;
  return Object.entries(changes)
    .filter(([field, change]) => !same(current[field], change.after))
    .map(([field, change]) => ({
      field,
      name: fieldName(field),
      current: valueText(field, current[field]),
      next: valueText(field, change.after),
      value: change.after,
    }));
}

/** The `configuration.apply` input: the pilot's current settings as base, the changes only. */
export function handBackCommand(pilot: Pilot, rows: readonly HandBackRow[]): SettingsInput {
  return {
    base: {
      session_id: pilot.session_id,
      kind: 'config',
      object_id: pilot.id,
      version: pilot.version ?? 1,
      config_version: pilot.config_version ?? null,
    },
    settings: Object.fromEntries(rows.map((r) => [r.field, r.value])) as SettingsInput['settings'],
  };
}

/** Read the target and two regression scopes independently; a missing comparison is not zero. */
export function reviewDetails(record: EngineerReviewRecord, language: 'zh' | 'en') {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const result = reviewResult(record, language);
  const rows = record.report.public_results;
  const publicNew = new Set(
    record.report.findings
      .filter((f) => f.kind === 'new_regression' && f.status === 'fail')
      .flatMap((f) => f.probe_ids),
  ).size;
  const hidden = record.report.hidden_comparison;
  const target = {
    fixed: t('已修好', 'Fixed'),
    partial: t('部分修好', 'Partly fixed'),
    not_fixed: t('未修好', 'Not fixed'),
    unknown: t('未决；现有复核不能确认', 'Unverified by this review'),
  }[result.target];
  return [
    { label: t('目标核验', 'Target verification'), text: target },
    {
      label: t('公开回归', 'Public regression'),
      text: t(
        `${rows.filter((r) => r.result === 'pass').length}/${rows.length} 通过；已记录新增失败 ${publicNew} 条`,
        `${rows.filter((r) => r.result === 'pass').length}/${rows.length} passed; ${publicNew} recorded new failures`,
      ),
    },
    {
      label: t('隐藏回归', 'Hidden regression'),
      text: hidden
        ? t(
            `新增失败 ${hidden.new_failures}；另修好 ${hidden.fixed}；未核验 ${hidden.unverified}`,
            `${hidden.new_failures} new failures; ${hidden.fixed} also fixed; ${hidden.unverified} unverified`,
          )
        : t('比较结果未提供', 'Comparison not provided'),
    },
    {
      label: t('是否采用', 'Adoption'),
      text: outcomeClean(result)
        ? t(
            '复核支持采用；仍由你确认更新设置',
            'Review supports adoption; you still confirm the settings update',
          )
        : t('暂不建议采用：', 'Adoption not recommended yet: ') +
          (result.target !== 'fixed'
            ? target
            : result.newFailures > 0
              ? t('存在新增失败', 'new regressions exist')
              : t('回归比较未完成', 'regression comparison incomplete')),
    },
  ];
}
