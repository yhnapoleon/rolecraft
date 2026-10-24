/** Regression report view: a pure projection of one EngineerPublicReport into localized lines.
 * Nothing here fetches, stores or judges; every status comes from the reviewer's own fields.
 * Free text never passes through: finding descriptions are replaced by the authored rule copy,
 * advice text appears only on success. Probe questions are suite text and stay as written. */
import { copyText, type Language } from '../results-native/localization';
import { ENGINEER_REPORT_COPY, MATERIAL_NAMES, type EngineerReportKey } from './copy';
import type {
  EngineerEvaluationItem,
  EngineerFinding,
  EngineerFindingKind,
  EngineerFindingStatus,
  EngineerHiddenComparison,
  EngineerProbeStatus,
  EngineerPublicProbeResult,
  EngineerPublicReport,
} from './types';

/** good = holds (green), bad = over a limit / contradicts (red), unknown = not known (grey,
 * dashed), ink = neutral fact. No other colours. */
export type EngineerTone = 'good' | 'bad' | 'unknown' | 'ink';

export interface EngineerReportOptions {
  readonly language: Language;
  /** Rubric conclusions from the engineer API; omitted → no section. */
  readonly evaluation?: readonly EngineerEvaluationItem[] | null;
  /** Wording supplied by the API, e.g. "规则版检索"; omitted → no line. Never inferred here. */
  readonly retrievalNote?: string | null;
  /** Human name of a cited material; unknown IDs fall back to the built-in names, then "资料". */
  readonly materialName?: (materialId: string) => string | undefined;
  /** For the timestamp; defaults to the viewer's zone. */
  readonly timeZone?: string;
}

export interface EngineerTagView {
  readonly text: string;
  readonly tone: EngineerTone;
}
export interface EngineerProbeRowView {
  readonly id: string;
  readonly query: string;
  readonly result: 'pass' | 'fail' | 'error';
  readonly resultText: string;
  readonly tone: EngineerTone;
  readonly target: boolean;
  readonly tags: readonly EngineerTagView[];
  /** Expected vs actual in one sentence, only for rows that did not pass. */
  readonly diff?: string;
}
export interface EngineerCountView {
  readonly key:
    | 'passed'
    | 'failed'
    | 'errors'
    | 'new_failures'
    | 'fixed'
    | 'still_failing'
    | 'unverified';
  readonly label: string;
  readonly value: number;
  readonly tone: EngineerTone;
}
export interface EngineerCheckView {
  readonly kind: 'new_regression' | 'claim_consistency';
  readonly tone: EngineerTone;
  readonly status: string;
  /** Authored rule copy for this finding kind. */
  readonly rule: string;
}
export interface EngineerEvaluationRowView {
  readonly id: string;
  readonly title: string;
  readonly labelText: string;
  readonly tone: EngineerTone;
  readonly mark: 'met' | 'partial' | 'not_met' | 'unknown' | 'not_applicable' | 'waiting';
}
export interface EngineerBasisRow {
  readonly label: string;
  readonly value: string;
  /** True for hash prefixes (shown in monospace). */
  readonly code: boolean;
}
export interface EngineerReportView {
  readonly language: Language;
  readonly id: string;
  readonly eyebrow: string;
  readonly meta: readonly string[];
  /** Language the probe questions are written in (the work language of the review). */
  readonly queryLanguage: Language;
  readonly verdict: {
    readonly tone: EngineerTone;
    readonly state: 'fixed' | 'not_fixed' | 'unknown';
    readonly title: string;
    readonly detail: string;
    /** Target questions as written in the suite. */
    readonly targets: readonly string[];
  };
  readonly publicSection: {
    readonly title: string;
    readonly tally: string;
    readonly sourceNote?: string;
    readonly empty?: string;
    readonly rows: readonly EngineerProbeRowView[];
  };
  readonly hiddenSection: {
    readonly title: string;
    readonly counts: readonly EngineerCountView[];
    readonly comparison?: readonly EngineerCountView[];
    readonly note: string;
  };
  readonly checks: { readonly title: string; readonly lines: readonly EngineerCheckView[] };
  readonly evaluation?: {
    readonly title: string;
    readonly rows: readonly EngineerEvaluationRowView[];
  };
  readonly advice: {
    readonly tone: EngineerTone;
    readonly text: string;
    readonly body?: string;
    readonly scoreNote: string;
  };
  readonly retrievalNote?: string;
  readonly basis: { readonly label: string; readonly rows: readonly EngineerBasisRow[] };
}

type Values = Readonly<Record<string, string | number>>;

/** Rule copy for a finding, mirroring `rule_finding_text` (contracts/v2/engineer.py). */
export function ruleFindingText(
  kind: EngineerFindingKind,
  status: EngineerFindingStatus,
  language: Language,
  hasProbes = true,
): string {
  const t = (key: EngineerReportKey) => copyText(ENGINEER_REPORT_COPY, language, key);
  if (kind === 'unresolved')
    return t(status === 'unverified' ? 'ruleUnresolvedError' : 'ruleUnresolved');
  if (kind === 'target_fix' && !hasProbes) return t('ruleTargetNoProbe');
  if (kind === 'claim_consistency') return t('ruleClaim');
  return t(kind === 'target_fix' ? 'ruleTarget' : 'ruleRegression');
}

const STATUS_KEY: Record<EngineerProbeStatus, EngineerReportKey> = {
  answered: 'statusAnswered',
  answered_with_warning: 'statusWarned',
  fallback: 'statusFallback',
  failed: 'statusFailed',
};
const ERROR_KEY: Record<string, EngineerReportKey> = {
  engineer_probe_execution_failed: 'errorProbe',
  engineer_baseline_execution_failed: 'errorBaseline',
  engineer_review_interrupted: 'errorInterrupted',
  engineer_verification_failed: 'errorVerification',
};
const EVALUATION_KEY: Record<string, EngineerReportKey> = {
  E1: 'evalE1',
  E2: 'evalE2',
  E3: 'evalE3',
  E4: 'evalE4',
  E5: 'evalE5',
};

const short = (hash: string | null | undefined) => (hash ? hash.slice(0, 8) : '');
const capitalize = (text: string, language: Language) =>
  language === 'en' && text ? text[0].toUpperCase() + text.slice(1) : text;
const nonNegative = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;

function stamp(iso: string, language: Language, timeZone?: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const parts = new Intl.DateTimeFormat(language === 'en' ? 'en-GB' : 'zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone,
  }).formatToParts(date);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`;
}

/** Findings for one probe, by kind. */
function findingsFor(
  findings: readonly EngineerFinding[],
  probeId: string,
  kind: EngineerFindingKind,
) {
  return findings.filter((f) => f.kind === kind && f.probe_ids.includes(probeId));
}

export function engineerReportView(
  report: EngineerPublicReport,
  options: EngineerReportOptions,
): EngineerReportView {
  const language = options.language;
  const t = (key: EngineerReportKey, values: Values = {}) =>
    copyText(ENGINEER_REPORT_COPY, language, key, values);
  const findings = (report.findings ?? []).filter((f) => f.visibility === 'public');
  const materialName = (id: string) =>
    options.materialName?.(id) ?? MATERIAL_NAMES[language][id] ?? t('materialFallback');

  /** Expected vs actual, in the viewer's language (status words and versions only). */
  const diffOf = (row: EngineerPublicProbeResult): string => {
    if (row.result === 'error') return t(ERROR_KEY[row.error_code ?? ''] ?? 'errorVerification');
    const parts: string[] = [];
    if (row.actual_status !== row.expected_status)
      parts.push(
        t('diffStatus', {
          expected: t(STATUS_KEY[row.expected_status]),
          actual: row.actual_status ? t(STATUS_KEY[row.actual_status]) : t('statusNone'),
        }),
      );
    for (const ref of row.citations ?? []) {
      const current = row.source_versions?.[ref.object_id];
      if (typeof current === 'number' && current > ref.version)
        parts.push(
          t('diffStale', { name: materialName(ref.object_id), cited: ref.version, current }),
        );
    }
    return parts.length ? parts.join(t('diffJoin')) : t('diffSame');
  };

  const targets = findings.filter((f) => f.kind === 'target_fix');
  const targetIds = new Set(targets.flatMap((f) => f.probe_ids));
  const rows: EngineerProbeRowView[] = (report.public_results ?? []).map((row) => {
    const regression = findingsFor(findings, row.probe_id, 'new_regression');
    const isNew = regression.some((f) => f.status === 'fail');
    const tags: EngineerTagView[] = [];
    const target = targetIds.has(row.probe_id);
    if (target) tags.push({ text: t('tagTarget'), tone: 'ink' });
    if (row.result === 'fail' && isNew) tags.push({ text: t('tagNewFailure'), tone: 'bad' });
    else if (row.result === 'fail' && regression.some((f) => f.status === 'pass'))
      tags.push({ text: t('tagPreexisting'), tone: 'unknown' });
    return {
      id: row.probe_id,
      query: row.query,
      result: row.result,
      resultText: t(
        row.result === 'pass' ? 'resultPass' : row.result === 'fail' ? 'resultFail' : 'resultError',
      ),
      tone: row.result === 'pass' ? 'good' : row.result === 'fail' ? 'bad' : 'unknown',
      target,
      tags,
      diff: row.result === 'pass' ? undefined : capitalize(diffOf(row), language),
    };
  });

  // Target: every target finding must pass; any fail is "not fixed"; otherwise not known.
  const byId = new Map((report.public_results ?? []).map((row) => [row.probe_id, row]));
  const targetRows = [...targetIds].map((id) => byId.get(id)).filter((r) => r !== undefined);
  const failedTargets = targets.filter((f) => f.status === 'fail');
  const state: EngineerReportView['verdict']['state'] =
    targets.length && targets.every((f) => f.status === 'pass')
      ? 'fixed'
      : failedTargets.length
        ? 'not_fixed'
        : 'unknown';
  let detail: string;
  if (state === 'fixed') detail = t('targetPassed');
  else if (state === 'not_fixed') {
    const firstFailed = byId.get(failedTargets[0].probe_ids[0] ?? '');
    detail =
      targetIds.size > 1
        ? t('targetsPartial', {
            n: targetIds.size,
            k: new Set(failedTargets.flatMap((f) => f.probe_ids)).size,
          })
        : firstFailed
          ? t('targetFailed', { diff: diffOf(firstFailed) })
          : t('targetFailedPlain');
  } else if (targets.some((f) => !f.probe_ids.length))
    detail = ruleFindingText('target_fix', 'unverified', language, false);
  else if (targetRows.some((r) => r.result === 'error')) detail = t('targetErrored');
  else detail = t('targetMissing');

  const publicRows = report.public_results ?? [];
  const tally = (p: number, f: number, e: number) =>
    e ? t('publicTallyErrors', { p, f, e }) : t('publicTally', { p, f });
  const sourceNote =
    report.work_language !== language
      ? t(report.work_language === 'zh' ? 'sourceZh' : 'sourceEn')
      : undefined;

  const hidden = report.hidden ?? { passed: 0, failed: 0, errors: 0 };
  const hiddenTotal =
    nonNegative(hidden.passed) + nonNegative(hidden.failed) + nonNegative(hidden.errors);
  const comparison: EngineerHiddenComparison | null = report.hidden_comparison ?? null;
  const count = (
    key: EngineerCountView['key'],
    label: EngineerReportKey,
    value: number,
    tone: EngineerTone,
  ) => ({
    key,
    label: t(label),
    value: nonNegative(value),
    tone,
  });

  // New regressions: public findings, plus hidden counts once the reviewer publishes them.
  const regressions = findings.filter((f) => f.kind === 'new_regression');
  const publicNew = new Set(
    regressions.filter((f) => f.status === 'fail').flatMap((f) => f.probe_ids),
  ).size;
  const hiddenNew = comparison ? nonNegative(comparison.new_failures) : 0;
  const hiddenUnknown = comparison ? nonNegative(comparison.unverified) > 0 : false;
  let regression: EngineerCheckView;
  const regressionRule = ruleFindingText('new_regression', 'pass', language);
  if (publicNew + hiddenNew > 0)
    regression = {
      kind: 'new_regression',
      tone: 'bad',
      status: comparison
        ? t('regressionSomeAll', { n: publicNew + hiddenNew, p: publicNew, h: hiddenNew })
        : t('regressionSome', { n: publicNew }),
      rule: regressionRule,
    };
  else if (regressions.some((f) => f.status === 'unverified') || hiddenUnknown)
    regression = {
      kind: 'new_regression',
      tone: 'unknown',
      status: t('regressionUnknown'),
      rule: regressionRule,
    };
  else if (regressions.length)
    regression = {
      kind: 'new_regression',
      tone: 'good',
      status: t(comparison ? 'regressionNoneAll' : 'regressionNone'),
      rule: regressionRule,
    };
  else
    regression = {
      kind: 'new_regression',
      tone: 'unknown',
      status: t('regressionEmpty'),
      rule: regressionRule,
    };

  const claimTone: Record<EngineerPublicReport['claim_check'], [EngineerTone, EngineerReportKey]> =
    {
      matched: ['good', 'claimMatched'],
      mismatch: ['bad', 'claimMismatch'],
      not_provided: ['unknown', 'claimMissing'],
      unverified: ['unknown', 'claimUnverified'],
    };
  const [claimToneValue, claimKey] = claimTone[report.claim_check] ?? [
    'unknown',
    'claimUnverified',
  ];
  const claim: EngineerCheckView = {
    kind: 'claim_consistency',
    tone: claimToneValue,
    status: t(claimKey),
    rule: ruleFindingText('claim_consistency', 'pass', language),
  };

  const evaluation = options.evaluation?.length
    ? {
        title: t('evaluationTitle'),
        rows: options.evaluation.map((item): EngineerEvaluationRowView => {
          const key = EVALUATION_KEY[item.id.split('.')[0]];
          const title = key ? t(key) : item.title?.trim() || t('evalGeneric');
          if (item.label === null && item.status === 'waiting_model')
            return {
              id: item.id,
              title,
              labelText: t('labelWaiting'),
              tone: 'unknown',
              mark: 'waiting',
            };
          const label = {
            MET: ['labelMet', 'good', 'met'],
            PARTIAL: ['labelPartial', 'ink', 'partial'],
            NOT_MET: ['labelNotMet', 'bad', 'not_met'],
            INSUFFICIENT: ['labelUnknown', 'unknown', 'unknown'],
            NOT_APPLICABLE: ['labelNotApplicable', 'unknown', 'not_applicable'],
          } as const;
          const [labelKey, tone, mark] = item.label ? label[item.label] : label.INSUFFICIENT;
          return { id: item.id, title, labelText: t(labelKey), tone, mark };
        }),
      }
    : undefined;

  const advice = report.advice;
  const adviceView: EngineerReportView['advice'] =
    advice?.status === 'success'
      ? advice.text
        ? { tone: 'ink', text: t('adviceSuccess'), body: advice.text, scoreNote: t('notScored') }
        : { tone: 'ink', text: t('adviceSuccessEmpty'), scoreNote: t('notScored') }
      : {
          tone: 'unknown',
          text: t(
            advice?.status === 'unavailable'
              ? 'adviceUnavailable'
              : advice?.status === 'invalid'
                ? 'adviceInvalid'
                : advice?.status === 'timeout'
                  ? 'adviceTimeout'
                  : 'adviceWaiting',
          ),
          scoreNote: t('notScored'),
        };

  const a = report.applicability;
  const code = (label: EngineerReportKey, hash: string | null | undefined): EngineerBasisRow => ({
    label: t(label),
    value: hash ? short(hash) : t('basisNone'),
    code: !!hash,
  });
  const basisRows: EngineerBasisRow[] = [
    code('basisScenario', a?.scenario?.sha256),
    code('basisSuite', a?.probe_suite_hash),
    code('basisBase', a?.base_config_hash),
    code('basisConfig', a?.config?.sha256),
    code('basisEffective', a?.effective_config_hash),
    code('basisSources', a?.source_versions_hash),
    code('basisIndex', a?.indexed_versions_hash),
    {
      label: t('basisSnapshot'),
      value: a?.source_as_of
        ? t('basisSnapshotValue', {
            seq: a.source_as_of.business_seq,
            rev: a.source_as_of.workspace_revision,
          })
        : t('basisNone'),
      code: false,
    },
    code('basisReviewer', a?.reviewer_version_hash),
    code('basisSubmission', report.submission?.sha256),
    code('basisInput', report.input_hash),
  ];
  if (advice?.model) basisRows.push(code('basisModel', advice.model.sha256));

  const retrievalNote = options.retrievalNote?.trim();
  return {
    language,
    queryLanguage: report.work_language === 'en' ? 'en' : 'zh',
    id: report.id,
    eyebrow: t('eyebrow'),
    meta: [
      stamp(report.created_at, language, options.timeZone),
      t(
        report.status === 'verified'
          ? 'statusVerified'
          : report.status === 'report_mismatch'
            ? 'statusMismatch'
            : 'statusIncomplete',
      ),
    ].filter(Boolean),
    verdict: {
      state,
      tone: state === 'fixed' ? 'good' : state === 'not_fixed' ? 'bad' : 'unknown',
      title: t(
        state === 'fixed'
          ? 'verdictFixed'
          : state === 'not_fixed'
            ? 'verdictNotFixed'
            : 'verdictUnknown',
      ),
      detail,
      targets: targetRows.map((r) => r.query),
    },
    publicSection: {
      title: t('publicTitle', { n: publicRows.length }),
      tally: tally(
        publicRows.filter((r) => r.result === 'pass').length,
        publicRows.filter((r) => r.result === 'fail').length,
        publicRows.filter((r) => r.result === 'error').length,
      ),
      sourceNote,
      empty: publicRows.length ? undefined : t('publicEmpty'),
      rows,
    },
    hiddenSection: {
      title: t('hiddenTitle', { n: hiddenTotal }),
      counts: [
        count('passed', 'passed', hidden.passed, 'ink'),
        count('failed', 'failed', hidden.failed, 'ink'),
        count('errors', 'errors', hidden.errors, 'ink'),
      ],
      comparison: comparison
        ? [
            count(
              'new_failures',
              'newFailures',
              comparison.new_failures,
              comparison.new_failures > 0 ? 'bad' : 'unknown',
            ),
            count('fixed', 'fixed', comparison.fixed, comparison.fixed > 0 ? 'good' : 'unknown'),
            count('still_failing', 'stillFailing', comparison.still_failing, 'unknown'),
            count('unverified', 'unverified', comparison.unverified, 'unknown'),
          ]
        : undefined,
      note: t('hiddenNote'),
    },
    checks: { title: t('checksTitle'), lines: [regression, claim] },
    evaluation,
    advice: adviceView,
    retrievalNote: retrievalNote || undefined,
    basis: { label: t('basis'), rows: basisRows },
  };
}
