/** Evaluation desk state that does not touch the network: drafts, buckets and counts.
 * The server owns batches and their summary; this module only presents them. */
import type {
  AipmBatch,
  AipmDesign,
  BatchCase,
  MonitoringPlan,
  ObjectRef,
  TriageRow,
} from '../../aipm/types';

export type Language = 'zh' | 'en';
export type Route = TriageRow['route'];
export const ROUTES: readonly Route[] = [
  'deterministic',
  'retrieval_generation',
  'agent_confirmation',
  'human',
];
export const MAX_CASES = 20;

export const text = (language: Language, zh: string, en: string) => (language === 'zh' ? zh : en);
export const esc = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
export const sameRef = (a?: ObjectRef | null, b?: ObjectRef | null) =>
  !!a &&
  !!b &&
  a.session_id === b.session_id &&
  a.kind === b.kind &&
  a.object_id === b.object_id &&
  a.version === b.version;

/** Public scenario content, `public/evaluation.{zh,en}.json`. */
export type CaseType = { id: string; label: string; query_hint: string; expected_hint: string };
export type EvaluationContent = {
  schema_version: 1;
  content_revision: string;
  language: Language;
  title: string;
  intro: string;
  routes: { id: Route; label: string; boundary: string; case_types: CaseType[] }[];
  regression: {
    id: string;
    route: Route;
    case_type: string;
    label: string;
    query: string;
    expected_hint: string;
    note: string;
  };
  run: { explain: string; changed: string };
  monitoring: {
    intro: string;
    fields: { id: keyof MonitoringPlan; label: string; hint: string }[];
    starter_metrics: {
      metric: string;
      source: 'evaluation' | 'to_collect';
      definition_hint: string;
    }[];
    rollback_note: string;
  };
};

/** L3 extension fields returned by `aipm.batch.read`; the shared base stays L4's. */
export type EvaluationCase = BatchCase & {
  case_revision: number;
  route: Route;
  coverage: 'assistant_answer' | 'plan_only';
  /** Originals the server never received, set aside after conditions moved; never counted. */
  abandoned?: { request_id: string }[];
};
export type EvaluationBatch = Omit<AipmBatch, 'cases'> & { cases: EvaluationCase[] };
export type Assessment = {
  case_id: string;
  result: 'satisfied' | 'not_satisfied' | 'unknown' | 'unsupported';
  reason: string;
  assessed_by: string;
};
export type RouteCount = {
  total: number;
  runnable: number;
  completed: number;
  assessed: number;
  satisfied: number;
  unknown: number;
  unsupported: number;
  execution_failed: number;
  completion_rate: number | null;
  assessment_rate: number | null;
  satisfaction_rate: number | null;
  judge: 'learner_assessment';
};
export type Summary = Record<'all' | Route, RouteCount>;
/** Server-derived per read for prepared cases: received, safe to send again, or must reprepare. */
export type Recovery = 'in_progress' | 'send_again' | 'reprepare';
export type BatchView = {
  batch: EvaluationBatch;
  assessments: Assessment[];
  summary: Summary;
  recovery?: Record<string, Recovery>;
};

/** One editable case before it is saved into a test plan. Expected text is required. */
export type CaseDraft = {
  key: string;
  rowId: string;
  route: Route;
  caseType: string;
  query: string;
  expected: string;
  /** Agent rows may run only their retrieval answer; deterministic rows never run. */
  answerOnly: boolean;
};

export function rowsByRoute(design: AipmDesign | null) {
  const rows = (design?.rows ?? []).filter((row) => row.need_ref);
  return ROUTES.map((route) => ({ route, rows: rows.filter((row) => row.route === route) }));
}

/** A starter is an editable suggestion: the query is empty and the expectation is the learner's. */
export function starterDraft(row: TriageRow, content: EvaluationContent, key: string): CaseDraft {
  const type = content.routes.find((r) => r.id === row.route)?.case_types[0];
  return {
    key,
    rowId: row.id,
    route: row.route,
    caseType: type?.id ?? '',
    query: '',
    expected: '',
    answerOnly: row.route === 'retrieval_generation' || row.route === 'human',
  };
}

export function regressionDraft(
  design: AipmDesign | null,
  content: EvaluationContent,
  key: string,
): CaseDraft | null {
  const row = (design?.rows ?? []).find((r) => r.need_ref && r.route === content.regression.route);
  if (!row) return null;
  return {
    key,
    rowId: row.id,
    route: row.route,
    caseType: content.regression.case_type,
    query: content.regression.query,
    expected: '',
    answerOnly: true,
  };
}

export const draftReady = (draft: CaseDraft) => !!draft.query.trim() && !!draft.expected.trim();

/** Runs only through the existing knowledge-answer executor, as the server decides on create. */
export const coverageOf = (draft: CaseDraft): 'assistant_answer' | 'plan_only' =>
  draft.route !== 'deterministic' && draft.answerOnly ? 'assistant_answer' : 'plan_only';

export function planPayload(drafts: CaseDraft[]) {
  return {
    type: 'test_plan' as const,
    cases: drafts.filter(draftReady).map((draft) => ({
      id: draft.key,
      query: draft.query.trim(),
      declared_expected: draft.expected.trim(),
      intent: draft.caseType,
    })),
  };
}

/** The plan service assigns case identities; saved order follows the payload. */
export function selections(drafts: CaseDraft[], savedCaseIds: string[]) {
  const ready = drafts.filter(draftReady);
  if (ready.length !== savedCaseIds.length) throw new Error('evaluation_plan_mismatch');
  return ready.map((draft, index) => ({
    case_id: savedCaseIds[index],
    triage_row_id: draft.rowId,
    coverage: coverageOf(draft),
  }));
}

export type Buckets = {
  waiting: EvaluationCase[];
  awaitingJudgement: EvaluationCase[];
  judged: EvaluationCase[];
  failed: EvaluationCase[];
  unsupported: EvaluationCase[];
  cancelled: EvaluationCase[];
};

/** Running and judging are separate: a completed run is not a satisfied case. */
export function buckets(view: BatchView): Buckets {
  const latest = latestAssessments(view.assessments);
  const out: Buckets = {
    waiting: [],
    awaitingJudgement: [],
    judged: [],
    failed: [],
    unsupported: [],
    cancelled: [],
  };
  for (const row of view.batch.cases) {
    const status = row.status ?? 'pending';
    if (status === 'pending') out.waiting.push(row);
    else if (status === 'execution_failed') out.failed.push(row);
    else if (status === 'unsupported') out.unsupported.push(row);
    else if (status === 'cancelled') out.cancelled.push(row);
    else {
      const result = latest.get(row.id)?.result;
      (result === 'satisfied' || result === 'not_satisfied'
        ? out.judged
        : out.awaitingJudgement
      ).push(row);
    }
  }
  return out;
}

export function latestAssessments(items: Assessment[]) {
  const latest = new Map<string, Assessment>();
  for (const item of items) latest.set(item.case_id, item);
  return latest;
}

/** “a of b” with its denominator; a zero denominator shows no percentage. */
export function ratio(language: Language, numerator: number, denominator: number) {
  if (!denominator) return text(language, '暂无可计算的分母', 'No denominator yet');
  const percent = Math.round((numerator / denominator) * 100);
  return text(
    language,
    `${numerator} / ${denominator}（${percent}%）`,
    `${numerator} of ${denominator} (${percent}%)`,
  );
}

export function summaryLines(language: Language, count: RouteCount) {
  const t = (zh: string, en: string) => text(language, zh, en);
  return [
    {
      id: 'completion',
      label: t('运行完成', 'Runs completed'),
      value: ratio(language, count.completed, count.runnable),
      note: count.unsupported
        ? t(
            `分母是可运行的题；${count.unsupported} 道计划用例不计入。`,
            `Out of runnable cases; ${count.unsupported} plan-only not counted.`,
          )
        : t('分母是可运行的题。', 'Out of runnable cases.'),
    },
    {
      id: 'assessment',
      label: t('已判定', 'Judged'),
      value: ratio(language, count.assessed, count.completed),
      note: t('分母是已运行完成的题。', 'Out of completed runs.'),
    },
    {
      id: 'satisfaction',
      label: t('判定为满足', 'Judged satisfied'),
      value: ratio(language, count.satisfied, count.assessed),
      note: t(
        '分母是你已判定的题。判定人：你本人。',
        'Out of the cases you judged. Judged by: you.',
      ),
    },
  ];
}

export function emptyMonitoring(metric = '', definition = ''): MonitoringPlan {
  return {
    metric,
    definition,
    observation_window: '',
    owner: '',
    trigger: '',
    response: '',
    rollback_target: '',
    verification_plan: '',
  };
}

/** A plan is saved only with every field filled; otherwise it says what is missing. */
export function monitoringGaps(plan: MonitoringPlan) {
  return (Object.keys(plan) as (keyof MonitoringPlan)[]).filter((key) => !plan[key].trim());
}

export function pausedMessage(
  language: Language,
  reason: string | null | undefined,
  content: EvaluationContent,
) {
  if (!reason) return null;
  if (reason === 'conditions_changed') return content.run.changed;
  if (reason === 'user_paused')
    return text(
      language,
      '已暂停。重新开始前不会发起新题。',
      'Paused. No new case starts until you continue.',
    );
  return text(language, '已暂停。', 'Paused.');
}

/** The answer executor's actual mode, shown on the run button; never an assumed paid model. */
export function modeLabel(language: Language, mode: string) {
  if (mode === 'extractive')
    return text(language, '摘录模式（不调用模型）', 'Extractive mode (no model call)');
  return text(language, `生成模式：${mode}`, `Generation mode: ${mode}`);
}

/** The folded block's one line: how many cases, what ran, what is judged, how many plans. */
export function blockSummary(view: BatchView | null, language: Language) {
  if (!view) return text(language, '还没有评测批次', 'No evaluation batch yet');
  const all = view.summary.all;
  const plans = view.batch.monitoring?.length ?? 0;
  return text(
    language,
    `${all.total} 题 · 运行 ${all.completed}/${all.runnable} · 已判定 ${all.assessed} · 观察计划 ${plans} 条`,
    `${all.total} cases · ran ${all.completed}/${all.runnable} · judged ${all.assessed} · ${plans} observation plan${plans === 1 ? '' : 's'}`,
  );
}
