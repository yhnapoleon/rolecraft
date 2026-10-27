/** The answer chain: which of the assistant's five steps a test run passed, where it stopped and
 * why. Reads only what the saved record holds; a missing field reads "not recorded", never a guess. */
import type { RecognitionRecord } from '../recognition-native/badge';
import { actualMethod } from '../recognition-native/actual-method';
import type { Language } from '../results-native/localization';
import type * as C from '../../contracts-v2';
import {
  chainText,
  generatorText,
  guardText,
  identityName,
  methodText,
  onOff,
  STAGE_IDENTITY,
  STAGE_KEYS,
  stageName,
  updateStrategyText,
  type StageKey,
} from './copy';

export type RunStatus = 'answered' | 'answered_with_warning' | 'fallback' | 'failed';
export type AnswerMode = 'extractive' | 'llm' | 'unavailable' | 'failed';
export type ChainCitation = { id: string; version: number; title?: string };
export type ChainConfig = Partial<
  Pick<
    C.AssistantConfig,
    | 'scope_filter'
    | 'update_strategy'
    | 'freshness_guard'
    | 'fallback'
    | 'generator'
    | 'retrieval_limit'
    | 'min_score'
    | 'chunk_size'
    | 'domains'
  >
>;
export type ChainInput = {
  /** Raw result status; null on records saved before it was passed through. */
  status: RunStatus | null;
  errorCode: string | null;
  /** The answer mode recorded for this run; null when the record has none. */
  mode: AnswerMode | null;
  /** The server's own "cites an older version" flag, when it is known. */
  stale: boolean | null;
  citations: ChainCitation[];
  sourceVersions: Record<string, number>;
  indexedVersions: Record<string, number>;
  /** The configuration this run executed with. */
  config: ChainConfig | null;
  recognition: RecognitionRecord[];
};
/** passed: walked through; stop: decided the result; warn: outdated source (amber);
 * skipped: not reached; unrecorded: the record has nothing for this step. */
export type StageState = 'passed' | 'stop' | 'warn' | 'skipped' | 'unrecorded';
export type ChainStage = {
  key: StageKey;
  label: string;
  identity: string;
  state: StageState;
  /** The full sentence a screen reader hears, e.g. "In scope?: in scope". */
  sr: string;
  /** The recognition record behind "How the system judged", when this run has one. */
  inspect: 'scope' | 'retrieval' | 'drift' | null;
};
export type ChainView = {
  stages: ChainStage[];
  /** Index (0–4) of the step that decided the result. */
  stopAt: number;
  tone: 'plain' | 'warn' | 'unknown';
  reason: string;
  /** Whether "Hand to Daniel" belongs here: the run stopped at Found, or at Up to date? */
  handover: boolean;
  /** One line per step for "Show each step". */
  rows: string[];
};

const STOP_AT: Record<string, number> = {
  prohibited_topic: 0,
  outside_scope_ood: 0,
  outside_scope: 0,
  no_retrieval_hit: 1,
  manual_verification_required: 2,
  stale_source_guard: 2,
  assistant_generation_failed: 3,
  assistant_model_unavailable: 3,
  assistant_insufficient_sources: 3,
};
const STATUSES = new Set<RunStatus>(['answered', 'answered_with_warning', 'fallback', 'failed']);

const num = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const three = (value: number) => value.toFixed(3);

/** Which step decided the result, and what each step looked like. */
function walk(input: ChainInput) {
  const code = input.errorCode ?? null;
  const known = input.status !== null || code !== null;
  const outdated =
    input.citations.find(
      (c) => num(input.sourceVersions[c.id]) && c.version < input.sourceVersions[c.id],
    ) ?? (input.stale ? input.citations[0] : undefined);
  let stopAt = 4;
  let amber = false;
  if (code !== null && code in STOP_AT) stopAt = STOP_AT[code];
  else if (input.mode === 'failed' || input.mode === 'unavailable') stopAt = 3;
  if (code === 'stale_source_guard') amber = true;
  // Answered from an outdated source: not a stop, a walk-through carrying a problem.
  if (
    stopAt === 4 &&
    (input.status === 'answered_with_warning' || (known && (outdated || input.stale)))
  )
    amber = true;
  return { code, known, outdated, stopAt, amber };
}

function reasonFor(input: ChainInput, w: ReturnType<typeof walk>, language: Language) {
  const t = (key: Parameters<typeof chainText>[1], values?: Record<string, string | number>) =>
    chainText(language, key, values);
  if (!w.known) return t('reason_unrecorded');
  let reason: string;
  const { code } = w;
  if (
    code === 'assistant_generation_failed' ||
    (w.stopAt === 3 && input.mode === 'failed' && !code)
  )
    reason = t('reason_generation_failed');
  else if (
    code === 'assistant_model_unavailable' ||
    (w.stopAt === 3 && input.mode === 'unavailable')
  )
    reason = t('reason_model_unavailable');
  else if (code === 'assistant_insufficient_sources') reason = t('reason_insufficient_sources');
  else if (code && code in STOP_AT) reason = t(`reason_${code}` as Parameters<typeof chainText>[1]);
  else if (input.status === 'answered_with_warning') reason = t('reason_answered_with_warning');
  else if (w.outdated)
    reason = t('reason_answered_stale', {
      title: w.outdated.title || w.outdated.id,
      cur: input.sourceVersions[w.outdated.id] ?? '',
      n: w.outdated.version,
    });
  else if (input.citations.length)
    reason = t('reason_answered_current', {
      title: input.citations[0].title || input.citations[0].id,
      n: input.citations[0].version,
    });
  else reason = t('reason_answered_uncited');
  // A step that stopped the run before an answer, with no human to take it over.
  if (input.status === 'failed' && w.stopAt <= 2)
    reason += (language === 'zh' ? '' : ' ') + t('reason_no_fallback');
  return reason;
}

/** The short state word of each step, used in the screen-reader sentence. */
function stateWord(
  i: number,
  state: StageState,
  input: ChainInput,
  w: ReturnType<typeof walk>,
  language: Language,
) {
  const t = (key: Parameters<typeof chainText>[1]) => chainText(language, key);
  if (state === 'skipped') return t('state_not_reached');
  if (state === 'unrecorded') return t('state_unrecorded');
  const code = w.code;
  switch (STAGE_KEYS[i]) {
    case 'scope':
      if (state !== 'stop') return t('state_in_scope');
      return code === 'prohibited_topic'
        ? t('state_prohibited')
        : code === 'outside_scope'
          ? t('state_area_closed')
          : t('state_out_of_scope');
    case 'found':
      return state === 'stop' ? t('state_not_found') : t('state_found');
    case 'fresh':
      if (code === 'manual_verification_required') return t('state_manual');
      if (code === 'stale_source_guard') return t('state_stale_guard');
      if (state === 'warn') return t('state_outdated');
      return input.citations.length ? t('state_current') : t('state_no_citation');
    case 'answer':
      if (state === 'stop')
        return code === 'assistant_insufficient_sources'
          ? t('state_answer_insufficient')
          : code === 'assistant_model_unavailable' || input.mode === 'unavailable'
            ? t('state_answer_unavailable')
            : t('state_answer_failed');
      return answerWord(input, language) ?? t('state_answer_unrecorded');
    default:
      return outcomeWord(input, language);
  }
}

function answerWord(input: ChainInput, language: Language) {
  if (input.mode)
    return generatorText(input.mode === 'extractive' ? 'extractive' : 'llm', language);
  return generatorText(input.config?.generator, language);
}

function outcomeWord(input: ChainInput, language: Language) {
  const t = (key: Parameters<typeof chainText>[1]) => chainText(language, key);
  switch (input.status) {
    case 'answered':
      return t('outcome_answered');
    case 'answered_with_warning':
      return t('outcome_warned');
    case 'fallback':
      return t('outcome_handed');
    case 'failed':
      return t('outcome_failed');
    default:
      return t('outcome_unrecorded');
  }
}

const recordFor = (input: ChainInput, task: 'scope' | 'retrieval' | 'drift') =>
  input.recognition.find((r) => r.task === task);

function rowsFor(
  input: ChainInput,
  stages: ChainStage[],
  words: string[],
  w: ReturnType<typeof walk>,
  language: Language,
) {
  const t = (key: Parameters<typeof chainText>[1], values?: Record<string, string | number>) =>
    chainText(language, key, values);
  const cfg = input.config ?? {};
  const line = (i: number, parts: (string | null | undefined | false)[]) =>
    [stages[i].label, ...parts.filter((p): p is string => !!p)].join(' · ');
  const reach = (i: number, parts: () => (string | null | undefined | false)[]) =>
    stages[i].state === 'skipped'
      ? line(i, [t('state_not_reached')])
      : stages[i].state === 'unrecorded' && !w.known
        ? line(i, [t('state_unrecorded')])
        : line(i, parts());

  const scope = recordFor(input, 'scope');
  const retrieval = recordFor(input, 'retrieval');
  const scopeRow = () => {
    let detection: string;
    if (!scope) detection = t('row_scope_missing');
    else if (
      actualMethod(scope, language).mode === 'fallback' ||
      scope.outputs?.rule === 'no_retrieval_hit' ||
      !num(scope.score)
    )
      detection = t('row_scope_fallback');
    else
      detection = t('row_scope_real', {
        state: t(scope.label === 'out' ? 'state_out_of_scope' : 'state_in_scope'),
        score: three(scope.score as number),
        threshold: num(scope.threshold) ? three(scope.threshold) : '–',
      });
    return [
      w.code === 'prohibited_topic' && t('row_prohibited'),
      detection,
      typeof cfg.scope_filter === 'boolean' &&
        t('scope_filter', { state: onOff(cfg.scope_filter, language) }),
    ];
  };
  const foundRow = () => {
    if (!retrieval) return [t('row_found_missing')];
    const out = retrieval.outputs ?? {};
    const fallback = actualMethod(retrieval, language).mode === 'fallback';
    if (!['dense', 'rrf', 'bm25'].includes(String(out.method)))
      return [methodText(null, false, language)];
    return [
      t('row_found', {
        method: methodText(out.method, fallback, language),
        passing: num(out.passing) ? out.passing : '–',
        min_score: num(out.min_score)
          ? String(out.min_score)
          : num(cfg.min_score)
            ? String(cfg.min_score)
            : '–',
        limit: num(cfg.retrieval_limit) ? cfg.retrieval_limit : '–',
      }),
    ];
  };
  const freshRow = () => {
    const update = updateStrategyText(cfg.update_strategy, language);
    const guard = guardText(cfg.freshness_guard, language);
    const cited = w.outdated ?? input.citations[0];
    const versions = cited
      ? t('row_versions', {
          title: cited.title || cited.id,
          cur: input.sourceVersions[cited.id] ?? '–',
          idx: input.indexedVersions[cited.id] ?? '–',
        })
      : t('state_no_citation');
    return [
      update && t('row_update', { value: update.value }),
      guard && t('row_guard', { value: guard }),
      versions,
    ];
  };
  const answerRow = () => [words[3]];
  const resultRow = () => [
    words[4],
    (cfg.fallback === 'human' || cfg.fallback === 'none') &&
      t('human_fallback', { state: onOff(cfg.fallback === 'human', language) }),
  ];
  return [
    reach(0, scopeRow),
    reach(1, foundRow),
    reach(2, freshRow),
    reach(3, answerRow),
    reach(4, resultRow),
  ];
}

export function answerChain(input: ChainInput, language: Language): ChainView {
  const w = walk(input);
  const inspectable: ChainStage['inspect'][] = ['scope', 'retrieval', 'drift', null, null];
  const stages: ChainStage[] = STAGE_KEYS.map((key, i) => {
    let state: StageState;
    if (!w.known) state = 'unrecorded';
    else if (i === w.stopAt) state = i === 2 && w.amber ? 'warn' : 'stop';
    // The result is always the end point, even when an earlier step decided it.
    else if (i > w.stopAt) state = i === 4 ? 'passed' : 'skipped';
    else if (i === 2 && w.amber) state = 'warn';
    else if ((i === 0 && !recordFor(input, 'scope')) || (i === 1 && !recordFor(input, 'retrieval')))
      state = 'unrecorded';
    else state = 'passed';
    const label = stageName(key, language);
    const task = inspectable[i];
    return {
      key,
      label,
      identity: identityName(STAGE_IDENTITY[key], language),
      state,
      sr: '',
      inspect: task && recordFor(input, task) ? task : null,
    };
  });
  const words = stages.map((stage, i) => stateWord(i, stage.state, input, w, language));
  for (const [i, stage] of stages.entries()) {
    stage.sr = chainText(language, 'sr_sentence', {
      stage: stage.label,
      state: words[i],
    });
    if (stage.state === 'stop' || (stage.state === 'warn' && i === w.stopAt))
      stage.sr += (language === 'zh' ? '，' : ', ') + chainText(language, 'sr_stopped');
    if (stage.state === 'unrecorded' && w.known)
      stage.sr += (language === 'zh' ? '，' : ', ') + chainText(language, 'sr_unrecorded');
  }
  return {
    stages,
    stopAt: w.stopAt,
    tone: !w.known ? 'unknown' : w.amber ? 'warn' : 'plain',
    reason: reasonFor(input, w, language),
    handover: w.known && (w.stopAt === 1 || w.stopAt === 2 || w.amber),
    rows: rowsFor(input, stages, words, w, language),
  };
}

/* ---------- adapters ---------- */

const statusOf = (value: unknown): RunStatus | null =>
  STATUSES.has(value as RunStatus) ? (value as RunStatus) : null;
/** Recorded mode names → chain modes; "unknown" and anything else stay unrecorded. */
function modeOf(value: unknown): AnswerMode | null {
  if (value === 'local-extractive-v2' || value === 'extractive') return 'extractive';
  if (value === 'llm' || value === 'unavailable' || value === 'failed') return value;
  return null;
}
const versions = (value: unknown): Record<string, number> =>
  value && typeof value === 'object' ? { ...(value as Record<string, number>) } : {};

/** The fields of a run as the workbench keeps it (`a.tests[i]`, see workbench-live.ts). */
export type WorkbenchRun = {
  status?: unknown;
  errorCode?: unknown;
  mode?: unknown;
  stale?: unknown;
  citations?: { id: string; version: number; title?: string }[];
  sourceVersions?: unknown;
  indexedVersions?: unknown;
  effectiveConfig?: ChainConfig | null;
  recognition?: unknown;
};

export function fromWorkbenchRun(run: WorkbenchRun): ChainInput {
  return {
    status: statusOf(run.status),
    errorCode: typeof run.errorCode === 'string' ? run.errorCode : null,
    mode: modeOf(run.mode),
    stale: typeof run.stale === 'boolean' ? run.stale : null,
    citations: (run.citations ?? []).map((c) => ({ id: c.id, version: c.version, title: c.title })),
    sourceVersions: versions(run.sourceVersions),
    indexedVersions: versions(run.indexedVersions),
    config: run.effectiveConfig ?? null,
    recognition: Array.isArray(run.recognition) ? (run.recognition as RecognitionRecord[]) : [],
  };
}

/** A raw test result (`tests.list`). `titles` maps "id:version" (or "id") to a document title.
 * The raw record keeps no answer mode; the configured generator stands in for "how it answered". */
export function fromTestResult(
  raw: C.TestResultV2,
  titles: Record<string, string> = {},
): ChainInput {
  const r = raw as C.TestResultV2 & {
    recognition?: RecognitionRecord[] | null;
  };
  const sourceVersions = versions(r.execution?.source_versions);
  const citations = (r.citations ?? [])
    .filter((c) => c.kind === 'material')
    .map((c) => ({
      id: c.object_id,
      version: c.version,
      title: titles[`${c.object_id}:${c.version}`] || titles[c.object_id] || c.object_id,
    }));
  return {
    status: statusOf(r.status),
    errorCode: typeof r.error_code === 'string' ? r.error_code : null,
    mode: null,
    stale: citations.some((c) => num(sourceVersions[c.id]) && c.version < sourceVersions[c.id]),
    citations,
    sourceVersions,
    indexedVersions: versions(r.execution?.indexed_versions),
    config: r.config?.effective ?? null,
    recognition: Array.isArray(r.recognition) ? r.recognition : [],
  };
}
