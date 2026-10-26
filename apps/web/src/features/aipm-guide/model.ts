/** Presentation-only parsing. All statuses, focus and suggestions come from L4. */
export const EXPERIENCE = 'aipm-phase1-v1';
export const IDS = [
  'business',
  'stakeholders',
  'need',
  'boundary',
  'solution',
  'assurance',
  'decision',
] as const;
export type StepId = (typeof IDS)[number];
export type Language = 'zh' | 'en';
export type GuideQuestion = {
  role: 'manager' | 'business' | 'technical';
  text: string;
};
export type GuideStepView = {
  id: StepId;
  order: number;
  label: string;
  goal: string;
  summary: string;
  questions: GuideQuestion[];
  explanation: string;
  materialIds: string[];
  primary: { id: string; label: string };
  outputs: string[];
};
export type GuideView = {
  language: Language;
  revision: string;
  steps: GuideStepView[];
};
export type ProgressView = {
  sessionId: string;
  revision: string;
  language: Language;
  focus: StepId;
  suggested: StepId;
  point: {
    business_seq: number;
    workspace_revision: number;
    storage_revision: number;
  };
  complete: boolean;
  steps: {
    id: StepId;
    label: string;
    order: number;
    goal: string;
    status: 'not_started' | 'working' | 'recorded' | 'recheck' | 'uncovered';
    quality: string;
    missing: string[];
    feedback: { message: string; source: string; stale: boolean }[];
  }[];
};
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('Invalid AIPM response');
  return v as Record<string, unknown>;
};
const text = (v: unknown) => {
  if (typeof v !== 'string') throw new Error('Invalid AIPM text');
  return v;
};
const strings = (v: unknown) => (Array.isArray(v) ? v.map(text) : []);
const stepId = (v: unknown): StepId => {
  if (!IDS.includes(v as StepId)) throw new Error('Invalid AIPM step');
  return v as StepId;
};
const language = (v: unknown): Language => {
  if (v !== 'zh' && v !== 'en') throw new Error('Invalid AIPM language');
  return v;
};
function rows(v: unknown) {
  if (!Array.isArray(v) || v.length !== 7) throw new Error('Incomplete AIPM steps');
  const result = v.map(object);
  if (result.some((s, i) => s.id !== IDS[i] || s.order !== i + 1))
    throw new Error('Invalid AIPM order');
  return result;
}
export function guideView(value: unknown): GuideView {
  const g = object(value);
  if (g.experience_revision !== EXPERIENCE) throw new Error('Unsupported AIPM guide');
  return {
    language: language(g.work_language),
    revision: text(g.content_revision),
    steps: rows(g.steps).map((s) => {
      const help = Array.isArray(s.help) ? s.help.map(object) : [];
      const direction = help.find((h) => h.level === 'direction') ?? {};
      const action = object(direction.primary_action);
      const questions = Array.isArray(direction.questions)
        ? direction.questions.map((q) => {
            const r = object(q);
            if (!['manager', 'business', 'technical'].includes(text(r.role)))
              throw new Error('Invalid colleague');
            return {
              role: r.role as GuideQuestion['role'],
              text: text(r.text),
            };
          })
        : [];
      if (questions.length !== 2) throw new Error('Missing guide questions');
      return {
        id: stepId(s.id),
        order: Number(s.order),
        label: text(s.label),
        goal: text(s.goal),
        summary: text(direction.summary),
        questions,
        explanation: text(help.find((h) => h.level === 'explanation')?.text),
        materialIds: strings(help.find((h) => h.level === 'source')?.material_ids),
        primary: { id: text(action.id), label: text(action.label) },
        outputs: strings(s.expected_outputs),
      };
    }),
  };
}
export function progressView(value: unknown): ProgressView {
  const p = object(value),
    at = object(p.as_of);
  if (
    p.experience_revision !== EXPERIENCE ||
    !['business_seq', 'workspace_revision', 'storage_revision'].every(
      (k) => Number.isSafeInteger(at[k]) && Number(at[k]) >= 0,
    )
  )
    throw new Error('Invalid AIPM snapshot');
  return {
    sessionId: text(p.session_id),
    revision: text(p.content_revision),
    language: language(p.work_language),
    focus: stepId(p.focus_step),
    suggested: stepId(p.suggested_step),
    point: {
      business_seq: Number(at.business_seq),
      workspace_revision: Number(at.workspace_revision),
      storage_revision: Number(at.storage_revision),
    },
    complete: object(p.projection ?? {}).complete === true,
    steps: rows(p.steps).map((s) => {
      if (
        !['not_started', 'working', 'recorded', 'recheck', 'uncovered'].includes(
          text(s.work_status),
        )
      )
        throw new Error('Invalid work status');
      if (s.completed !== (s.work_status === 'recorded'))
        throw new Error('Inconsistent completion');
      return {
        id: stepId(s.id),
        order: Number(s.order),
        label: text(s.label),
        goal: text(s.goal),
        status: s.work_status as ProgressView['steps'][number]['status'],
        quality: text(s.quality_status ?? 'unverified'),
        missing: Array.isArray(s.missing) ? s.missing.map((m) => text(object(m).message)) : [],
        feedback: Array.isArray(s.open_feedback)
          ? s.open_feedback.map((f) => {
              const row = object(f);
              return {
                message: text(row.message),
                source: text(row.source),
                stale: row.stale === true,
              };
            })
          : [],
      };
    }),
  };
}
export function matchingSnapshot(
  guide: GuideView,
  progress: ProgressView,
  sessionId: string,
  lang: Language,
) {
  return (
    guide.revision === progress.revision &&
    progress.sessionId === sessionId &&
    guide.language === lang &&
    progress.language === lang
  );
}
