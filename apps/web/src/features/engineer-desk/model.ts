/** The engineer's desk as plain data: the ticket in work words, candidate settings, the trial log,
 * the draft and the sign sheet. Pure functions over what the engineer API returns
 * (`src/career_lab/engineer/session.py`); the desk draws them. Words follow the interface
 * language (T); text from the server (questions, answers, titles) stays in the work language. */
import { T } from '../../app/i18n';
import { ENGINEER_REPORT_COPY } from '../engineer-report';
import { copyText } from '../results-native/localization';
import { engineerErrorText, fieldName, valueText } from './copy';

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };
export type Settings = Record<string, JsonValue>;
export type Executor = { readonly id: string; readonly kind: string };
export type Outcome = 'pass' | 'fail' | 'error';

export interface EditableField {
  readonly field: string;
  readonly type: 'set' | 'boolean' | 'choice' | 'text_list' | 'integer' | 'number';
  readonly choices?: readonly string[];
  readonly costs?: Readonly<Record<string, number>>;
  readonly minimum?: number;
  readonly maximum?: number;
  readonly max_items?: number;
  readonly max_length?: number;
}
export interface Citation {
  readonly object_id: string | null;
  readonly version: number | null;
  readonly quote?: string | null;
}
export interface TargetTest {
  readonly test_id: string;
  readonly origin: string;
  readonly origin_label: string;
  readonly executor: Executor;
  readonly query: string;
  readonly status: string;
  readonly error_code: string | null;
  readonly answer_summary: string;
  readonly citations: readonly Citation[];
  readonly citation_count: number;
  readonly source_versions: Readonly<Record<string, number>>;
  readonly indexed_versions: Readonly<Record<string, number>>;
  readonly used_versions: Readonly<Record<string, number>>;
  readonly config_version: number | null;
  readonly config: {
    readonly same_as_baseline: boolean;
    readonly changed_fields: readonly string[];
    readonly differences: Readonly<Record<string, unknown>>;
  };
}
export interface ExperimentSummary {
  readonly id: string;
  readonly kind: 'reproduce' | 'trial';
  readonly executor: Executor;
  readonly created_at: string;
  readonly changed_fields?: readonly string[];
  readonly counts: Readonly<Record<string, number>>;
  readonly status: string;
}
export interface TrialRow {
  readonly id: string;
  readonly kind: 'public_probe' | 'target';
  readonly is_target: boolean;
  readonly query: string;
  readonly expected_status: string | null;
  readonly actual_status: string | null;
  readonly error_code: string | null;
  readonly answer_summary: string;
  readonly citations: readonly Citation[];
  readonly citation_count: number;
  readonly result: Outcome | 'unchecked';
}
interface Behavior {
  readonly status: string;
  readonly answer_summary: string;
  readonly citations: readonly Citation[];
  readonly citation_count: number;
}
export interface ReproductionRow {
  readonly test_id: string;
  readonly query: string;
  readonly matches_record: boolean;
  readonly recorded: Behavior;
  readonly reproduced: Behavior;
}
export type Change = { readonly before: JsonValue; readonly after: JsonValue };
/** A whole reproduction or trial as its POST returns it. */
export interface Experiment extends ExperimentSummary {
  readonly ticket_id: string;
  readonly changes: Readonly<Record<string, Change>>;
  readonly rows?: readonly (TrialRow | ReproductionRow)[];
}
export interface Statement {
  readonly field: string;
  readonly before: JsonValue;
  readonly after: JsonValue;
  readonly reason: string;
}
export interface Unresolved {
  readonly description: string;
  readonly probe_ids: readonly string[];
}
export interface DraftView {
  readonly id: string;
  readonly ticket_id: string;
  readonly executor: Executor;
  readonly created_at: string;
  readonly changes: Readonly<Record<string, Change>>;
  readonly explanation: string;
  readonly change_statements: readonly Statement[];
  readonly claimed_results: Readonly<Record<string, Outcome>>;
  readonly unresolved: readonly Unresolved[];
}
export interface ReviewSummary {
  readonly review_id: string;
  readonly status: string;
  readonly signed_at: string;
  readonly signed_by: Executor;
  readonly draft_id: string;
}
type Budget = { readonly used: number; readonly limit: number };
export interface TicketDetail {
  readonly id: string;
  readonly source: 'seeded' | 'tests';
  readonly title: string;
  readonly work_language: 'zh' | 'en';
  readonly created_at: string;
  readonly world_setup: { readonly config_version: number; readonly note: string } | null;
  readonly target_tests: readonly TargetTest[];
  readonly public_probes: readonly { readonly id: string; readonly query: string }[];
  readonly baseline_config: Settings;
  readonly editable_fields: readonly EditableField[];
  readonly review_budget: Budget;
  readonly experiment_budget: Budget;
  readonly draft_budget: Budget;
  readonly retrieval: { readonly mode: string; readonly note?: string | null };
  readonly trials: readonly ExperimentSummary[];
  readonly drafts: readonly { readonly id: string }[];
  readonly latest_draft: DraftView | null;
  readonly reviews: readonly ReviewSummary[];
}
/** What a draft sends (POST …/drafts), less the ticket ID. */
export interface DraftInput {
  readonly changes: Settings;
  readonly explanation: string;
  readonly change_statements: readonly Statement[];
  readonly claimed_results: Readonly<Record<string, Outcome>>;
  readonly unresolved: readonly Unresolved[];
}

const lang = () => T('zh', 'en') as 'zh' | 'en';
const list = (items: readonly string[]) => items.join(T('、', ', '));
const length = (text: string) => [...text].length;

/** Sources the assistant cites, named as the pilot settings name the knowledge. */
export function sourceName(id: string | null | undefined): string {
  switch (id) {
    case 'policy':
      return T('差旅政策', 'Travel policy');
    case 'faq':
      return T('办公 FAQ', 'Office FAQ');
    case 'meal':
      return T('餐费政策', 'Meal policy');
    case 'leave':
      return T('请假政策', 'Leave policy');
    case 'onboarding':
      return T('入职指引', 'Onboarding');
    default:
      return T('资料', 'A source');
  }
}

/** The assistant's answer types in words (the regression report's words). */
export function statusWord(status: string | null | undefined): string {
  const key = (
    {
      answered: 'statusAnswered',
      answered_with_warning: 'statusWarned',
      fallback: 'statusFallback',
      failed: 'statusFailed',
    } as const
  )[status ?? ''];
  return copyText(ENGINEER_REPORT_COPY, lang(), key ?? 'statusNone');
}

export function executorWho(executor: Executor): { who: string; agent: boolean } {
  if (executor.kind === 'human') return { who: T('你', 'You'), agent: false };
  if (executor.kind === 'external_agent' || executor.kind === 'reference_agent')
    return { who: T('你的 Agent', 'Your agent'), agent: true };
  return { who: T('系统', 'System'), agent: false };
}

export function clock(iso: string, timeZone?: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(lang() === 'en' ? 'en-GB' : 'zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    ...(timeZone ? { timeZone } : {}),
  }).format(date);
}

/* ---------- the ticket ---------- */

export interface TargetFacts {
  readonly id: string;
  readonly query: string;
  readonly answer: string;
  readonly said: string;
  readonly versions: readonly { readonly text: string; readonly stale: boolean }[];
  readonly cited: string;
  readonly origin: string;
  readonly config: string;
}
export interface TicketFacts {
  readonly source: string;
  readonly targets: readonly TargetFacts[];
  readonly setup: string;
  readonly retrieval: string;
  readonly reviewsLeft: number;
}

export function ticketFacts(ticket: TicketDetail): TicketFacts {
  const world = ticket.world_setup;
  return {
    source:
      ticket.source === 'seeded'
        ? T('委托附带', 'Came with the ticket')
        : T('产品经理交来', 'Handed over by product'),
    targets: ticket.target_tests.map(targetFacts),
    setup: world
      ? T(
          `起始状态由系统准备，不是你的操作：试点配置已上线为 v${world.config_version}。`,
          `The system prepared this starting state, not you: the pilot configuration went live as v${world.config_version}.`,
        )
      : '',
    retrieval:
      ticket.retrieval.mode === 'rule_based'
        ? T('规则版检索', 'Rule-based retrieval')
        : (ticket.retrieval.note ?? ''),
    reviewsLeft: Math.max(0, ticket.review_budget.limit - ticket.review_budget.used),
  };
}

function targetFacts(test: TargetTest): TargetFacts {
  // The server lists only the sources whose index lags behind (session.py target_view).
  const versions = Object.entries(test.source_versions).flatMap(([key, version]) => {
    const indexed = test.indexed_versions[key];
    return indexed === undefined || indexed === version
      ? []
      : [
          {
            text: T(
              `${sourceName(key)} v${version} / 索引 v${indexed}，索引落后`,
              `${sourceName(key)} v${version} / index v${indexed}, index behind`,
            ),
            stale: true,
          },
        ];
  });
  const first = test.citations[0];
  const more = test.citation_count - 1;
  const cited = first
    ? T(
        `引用 ${sourceName(first.object_id)} v${first.version}`,
        `Cites ${sourceName(first.object_id)} v${first.version}`,
      ) + (more > 0 ? T(`，另有 ${more} 条`, `, and ${more} more`) : '')
    : T('没有引用', 'No citation');
  return {
    id: test.test_id,
    query: test.query,
    answer: test.answer_summary,
    said: statusWord(test.status),
    versions,
    cited,
    origin: test.origin_label,
    config: test.config.same_as_baseline
      ? ''
      : T('当时的设置与委托基线不同：', 'Its settings differed from the ticket baseline: ') +
        list(test.config.changed_fields.map(fieldName)),
  };
}

/* ---------- candidate settings ---------- */

const sameValue = (a: JsonValue | undefined, b: JsonValue | undefined) => {
  if (Array.isArray(a) && Array.isArray(b))
    return JSON.stringify([...a].map(String).sort()) === JSON.stringify([...b].map(String).sort());
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
};

/** The candidate as the API wants it: only settings that differ from the baseline. */
export function candidateChanges(baseline: Settings, values: Settings): Settings {
  return Object.fromEntries(
    Object.entries(values).filter(([key, value]) => !sameValue(baseline[key], value)),
  );
}

// The server refuses web addresses and path-like text in topics (candidate.py).
const PATHLIKE = /:\/\/|^[/~\\]|\\|^\.{1,2}\/|^www\./i;

/** One typed value checked against its field's limits. */
export function parseField(
  field: EditableField,
  raw: string,
): { value: JsonValue } | { error: string } {
  const text = raw.trim();
  if (field.type === 'integer') {
    const min = field.minimum ?? 0;
    const max = field.maximum;
    const n = Number(text);
    const ok = /^-?\d+$/.test(text) && n >= min && (max === undefined || n <= max);
    if (ok) return { value: n };
    return {
      error:
        max === undefined
          ? T(`填不小于 ${min} 的整数。`, `Enter a whole number of ${min} or more.`)
          : T(`填 ${min} 到 ${max} 之间的整数。`, `Enter a whole number from ${min} to ${max}.`),
    };
  }
  if (field.type === 'number') {
    const min = field.minimum ?? 0;
    const max = field.maximum;
    const n = Number(text);
    if (text !== '' && Number.isFinite(n) && n >= min && (max === undefined || n <= max))
      return { value: n };
    return {
      error:
        max === undefined
          ? T(`填不小于 ${min} 的数。`, `Enter a number of ${min} or more.`)
          : T(`填 ${min} 到 ${max} 之间的数。`, `Enter a number from ${min} to ${max}.`),
    };
  }
  if (field.type === 'text_list') {
    const items = raw
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
    if (items.some((item) => PATHLIKE.test(item)))
      return {
        error: T(
          '每行写一个主题，不写网址或路径。',
          'One topic per line, with no web address or path.',
        ),
      };
    const max = field.max_items ?? 10;
    const chars = field.max_length ?? 40;
    if (items.length > max || items.some((item) => length(item) > chars))
      return {
        error: T(
          `最多 ${max} 个主题，每个不超过 ${chars} 字。`,
          `At most ${max} topics, each up to ${chars} characters.`,
        ),
      };
    return { value: items };
  }
  return { value: text };
}

/* ---------- the trial log ---------- */

export type Mark = 'good' | 'ink' | 'warn' | 'unknown';
export interface TrialLine {
  readonly id: string;
  readonly kind: 'reproduce' | 'trial';
  readonly who: string;
  readonly agent: boolean;
  readonly verb: string;
  readonly fields: string;
  readonly tally: string;
  readonly tone: Mark;
  readonly time: string;
}

/** One experiment, one line: who ran it, what, which settings changed, the public tally. */
export function trialLine(
  summary: ExperimentSummary,
  publicCount: number,
  timeZone?: string,
): TrialLine {
  const { who, agent } = executorWho(summary.executor);
  const counts = summary.counts;
  const common = {
    id: summary.id,
    kind: summary.kind,
    who,
    agent,
    fields: list((summary.changed_fields ?? []).map(fieldName)),
    time: clock(summary.created_at, timeZone),
  };
  if (summary.kind === 'reproduce') {
    const matched = counts.matched ?? 0;
    const total = counts.total ?? 0;
    return {
      ...common,
      verb: T('复现', 'Reproduce'),
      tally: T(`${matched}/${total} 与记录一致`, `${matched}/${total} match the record`),
      tone: matched === total ? 'good' : 'warn',
    };
  }
  const passed = counts.passed ?? 0;
  return {
    ...common,
    verb: T('试跑', 'Trial'),
    tally: T(`公开 ${passed}/${publicCount} 通过`, `Public ${passed}/${publicCount} passed`),
    tone: passed >= publicCount ? 'good' : (counts.failed ?? 0) > 0 ? 'ink' : 'unknown',
  };
}

export interface ExperimentRowView {
  /** A public probe's case number; empty for a target without one (never an internal row ID). */
  readonly id: string;
  readonly query: string;
  readonly target: boolean;
  readonly result: string;
  readonly mark: Mark;
  readonly verdict: string;
  readonly expected: string;
  readonly actual: string;
  readonly answer: string;
}

const isReproduction = (row: TrialRow | ReproductionRow): row is ReproductionRow =>
  'matches_record' in row;

/** A whole experiment's rows: for a trial, each public probe's expected and actual answer type
 * and any target without a probe ("not checked"); for a reproduction, the record beside the rerun. */
export function experimentRows(experiment: Experiment): ExperimentRowView[] {
  return (experiment.rows ?? []).map((row) => {
    if (isReproduction(row))
      return {
        id: '',
        query: row.query,
        target: true,
        result: row.matches_record ? 'pass' : 'changed',
        mark: row.matches_record ? 'good' : 'warn',
        verdict: row.matches_record
          ? T('与记录一致', 'Matches the record')
          : T('与记录不同', 'Differs from the record'),
        expected: statusWord(row.recorded.status),
        actual: statusWord(row.reproduced.status),
        answer: row.reproduced.answer_summary,
      };
    const verdict = {
      pass: T('通过', 'Passed'),
      fail: T('未通过', 'Did not pass'),
      error: T('执行出错', 'Run failed'),
      unchecked: T('未核对', 'Not checked'),
    }[row.result];
    const mark: Mark = row.result === 'pass' ? 'good' : row.result === 'fail' ? 'ink' : 'unknown';
    return {
      id: row.kind === 'target' ? '' : row.id,
      query: row.query,
      target: row.is_target,
      result: row.result,
      mark,
      verdict,
      expected: row.expected_status ? statusWord(row.expected_status) : '',
      actual: statusWord(row.actual_status),
      answer: row.answer_summary,
    };
  });
}

/** A self-report taken from a trial, only if the trial covers every public probe. */
export function claimsFromTrial(
  experiment: Experiment,
  publicIds: readonly string[],
): Record<string, Outcome> | null {
  if (experiment.kind !== 'trial' || !experiment.rows) return null;
  const results = new Map<string, Outcome>();
  for (const row of experiment.rows)
    if (!isReproduction(row) && row.kind === 'public_probe' && row.result !== 'unchecked')
      results.set(row.id, row.result);
  if (!publicIds.length || !publicIds.every((id) => results.has(id))) return null;
  return Object.fromEntries(publicIds.map((id) => [id, results.get(id) as Outcome]));
}

/* ---------- drafting and signing ---------- */

export const DRAFT_TEXT_LIMIT = 2000;
export const IMPACT_NOTE_LIMIT = 500;
export const UNRESOLVED_LIMIT = 10;

/** The draft's free text, counted as the server counts it (session.py draft_text): values as
 * compact JSON. */
export function draftTextLength(input: DraftInput): number {
  return (
    length(input.explanation) +
    input.change_statements.reduce(
      (n, s) =>
        n +
        length(s.reason) +
        length(JSON.stringify(s.before ?? null)) +
        length(JSON.stringify(s.after ?? null)),
      0,
    ) +
    input.unresolved.reduce((n, u) => n + length(u.description), 0)
  );
}

/** What stops a draft from being saved, in plain sentences; empty when it can be sent. */
export function validateDraft(input: DraftInput, publicIds: readonly string[]): string[] {
  const errors: string[] = [];
  if (input.change_statements.some((s) => !s.reason.trim()))
    errors.push(T('每条变更都写一句理由。', 'Give each change a one-line reason.'));
  const fields = input.change_statements.map((s) => s.field);
  if (new Set(fields).size !== fields.length)
    errors.push(engineerErrorText('engineer_change_statement_invalid'));
  const claimed = Object.keys(input.claimed_results);
  if (
    claimed.length &&
    (claimed.length !== publicIds.length || !publicIds.every((id) => claimed.includes(id)))
  )
    errors.push(engineerErrorText('engineer_claim_incomplete'));
  if (input.unresolved.some((u) => !u.description.trim()))
    errors.push(T('未修复项写清是什么问题。', 'Say what each unresolved item is.'));
  if (input.unresolved.length > UNRESOLVED_LIMIT)
    errors.push(T('未修复项最多 10 条。', 'List at most 10 unresolved items.'));
  if (draftTextLength(input) > DRAFT_TEXT_LIMIT)
    errors.push(engineerErrorText('engineer_draft_text_too_long'));
  return errors;
}

export function validateImpactNote(text: string): string {
  const note = text.trim();
  if (!note) return engineerErrorText('engineer_impact_note_required');
  if (length(note) > IMPACT_NOTE_LIMIT) return engineerErrorText('engineer_impact_note_too_long');
  return '';
}

export interface SignSheet {
  readonly id: string;
  readonly author: string;
  readonly agent: boolean;
  readonly time: string;
  readonly actual: readonly { field: string; name: string; before: string; after: string }[];
  readonly stated: readonly {
    field: string;
    name: string;
    before: string;
    after: string;
    reason: string;
  }[];
  readonly explanation: string;
  readonly claims: readonly { id: string; text: string }[];
  readonly unresolved: readonly { description: string; probes: string }[];
}

/** The latest draft as the person signs it. The actual change and the stated one are laid side by
 * side, each in its own order; whether they agree is the review's to judge (E3), not the sheet's. */
export function signSheet(draft: DraftView, timeZone?: string): SignSheet {
  const { who, agent } = executorWho(draft.executor);
  const outcome = (r: Outcome) =>
    ({
      pass: T('通过', 'Passed'),
      fail: T('未通过', 'Did not pass'),
      error: T('执行出错', 'Run failed'),
    })[r];
  return {
    id: draft.id,
    author: who,
    agent,
    time: clock(draft.created_at, timeZone),
    actual: Object.entries(draft.changes).map(([field, change]) => ({
      field,
      name: fieldName(field),
      before: valueText(field, change.before),
      after: valueText(field, change.after),
    })),
    stated: draft.change_statements.map((s) => ({
      field: s.field,
      name: fieldName(s.field),
      before: valueText(s.field, s.before),
      after: valueText(s.field, s.after),
      reason: s.reason,
    })),
    explanation: draft.explanation,
    claims: Object.entries(draft.claimed_results).map(([id, result]) => ({
      id,
      text: outcome(result),
    })),
    unresolved: draft.unresolved.map((u) => ({
      description: u.description,
      probes: u.probe_ids.join(' · '),
    })),
  };
}

export interface SignState {
  readonly can: boolean;
  readonly left: number;
  readonly reason: string;
  readonly signedReview?: string;
}

/** Whether the person can sign now, how many reviews remain, and why not. */
export function signState(ticket: TicketDetail): SignState {
  const left = Math.max(0, ticket.review_budget.limit - ticket.review_budget.used);
  const latest = ticket.latest_draft;
  if (!latest)
    return {
      can: false,
      left,
      reason: T('先起草一份提交，再签字。', 'Draft a submission first, then sign it.'),
    };
  const signed = ticket.reviews.find((r) => r.draft_id === latest.id);
  if (signed)
    return {
      can: false,
      left,
      reason: T(
        '这份草稿已经签过，改动后再起草一份。',
        'You signed this draft already. Change something and draft again.',
      ),
      signedReview: signed.review_id,
    };
  if (left <= 0)
    return { can: false, left: 0, reason: engineerErrorText('engineer_review_budget_exhausted') };
  return { can: true, left, reason: '' };
}

/* ---------- handing tests over ---------- */

export const HANDOVER_LIMIT = 10;
export interface HandoverTest {
  readonly id: string;
  readonly question: string;
  readonly answer?: string;
  readonly stale?: boolean;
}
export interface HandoverChoice {
  readonly id: string;
  readonly question: string;
  readonly answer: string;
  readonly flag: string;
  readonly chosen: boolean;
}

/** The bench's tests for "hand to engineering": those citing an out-of-date version first and
 * chosen to begin with (at most ten); the rest keep their order. */
export function handoverChoices(tests: readonly HandoverTest[]): HandoverChoice[] {
  const ordered = [...tests.filter((t) => t.stale), ...tests.filter((t) => !t.stale)];
  let chosen = 0;
  return ordered.map((test) => {
    const pick = !!test.stale && chosen < HANDOVER_LIMIT;
    if (pick) chosen += 1;
    return {
      id: test.id,
      question: test.question,
      answer: test.answer ?? '',
      flag: test.stale ? T('引用的版本已经过期', 'Cites an out-of-date version') : '',
      chosen: pick,
    };
  });
}
