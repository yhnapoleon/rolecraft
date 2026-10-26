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
/** v2: the three segments the seven points hang on, and a worksheet's state (spec §2). */
export type Segment = 'clarify' | 'design' | 'verify';
export type SheetStatus = 'not_started' | 'draft' | 'based' | 'solid' | 'recheck';
export type SheetView = {
  status: SheetStatus;
  recheckReason?: string;
  gapHint?: string;
  prdVersion?: number;
  editedSinceReview: boolean;
  agentDraft: boolean;
  /** No `sheet` from the server yet: derived here from work and quality status (stub). */
  derived: boolean;
};
const SEGMENT: Record<StepId, Segment> = {
  business: 'clarify',
  stakeholders: 'clarify',
  need: 'clarify',
  boundary: 'design',
  solution: 'design',
  assurance: 'verify',
  decision: 'verify',
};
const ICON: Record<StepId, string> = {
  business: 'Building2',
  stakeholders: 'Users',
  need: 'Search',
  boundary: 'ShieldHalf',
  solution: 'Workflow',
  assurance: 'ListChecks',
  decision: 'Flag',
};
const SHEET = ['not_started', 'draft', 'based', 'solid', 'recheck'];
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
  /** Why this step matters, what saving gives back, a worked example, and a brief the
   * learner can hand to their own agent. Empty when the content does not say. */
  why: string;
  feedback: string;
  example: string;
  agentBrief: string;
  segment: Segment;
  /** A lucide icon name. */
  icon: string;
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
  /** The pilot PRD's latest version (v2: one plan product, seven sections). */
  prd?: { id: string; version: number };
  /** Drafts an agent wrote that wait for the person (never step records until adopted). */
  drafts: { id: string; key: string; steps: StepId[] }[];
  steps: {
    id: StepId;
    label: string;
    order: number;
    goal: string;
    status: 'not_started' | 'working' | 'recorded' | 'recheck' | 'uncovered';
    quality: string;
    missing: string[];
    feedback: { message: string; source: string; stale: boolean }[];
    sheet: SheetView;
    /** The server's first suggested action for this step, in the practice's language. */
    nextAction?: string;
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
const optional = (v: unknown) => (typeof v === 'string' ? v : '');
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
        why: optional(direction.why),
        feedback: optional(direction.feedback),
        example: optional(direction.example),
        agentBrief: optional(direction.agent_brief),
        segment: (['clarify', 'design', 'verify'].includes(s.segment as string)
          ? s.segment
          : SEGMENT[stepId(s.id)]) as Segment,
        icon: optional(s.icon) || ICON[stepId(s.id)],
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
  const drafts: ProgressView['drafts'] = Array.isArray(p.pending_agent_drafts)
    ? p.pending_agent_drafts.map((d) => {
        const row = object(d),
          ref = object(row.ref);
        const steps = Array.isArray(row.steps)
          ? row.steps.filter((s): s is StepId => IDS.includes(s as StepId))
          : [];
        return { id: text(ref.object_id), key: `${text(ref.object_id)}@${ref.version}`, steps };
      })
    : [];
  const prd = p.prd_ref && typeof p.prd_ref === 'object' ? object(p.prd_ref) : null;
  return {
    sessionId: text(p.session_id),
    ...(prd && Number.isSafeInteger(prd.version)
      ? { prd: { id: text(prd.object_id), version: Number(prd.version) } }
      : {}),
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
    drafts,
    steps: rows(p.steps).map((s) => {
      if (
        !['not_started', 'working', 'recorded', 'recheck', 'uncovered'].includes(
          text(s.work_status),
        )
      )
        throw new Error('Invalid work status');
      if (s.completed !== (s.work_status === 'recorded'))
        throw new Error('Inconsistent completion');
      const id = stepId(s.id);
      const agentDraft = drafts.some((d) => d.steps.includes(id));
      const actions = Array.isArray(s.next_actions) ? s.next_actions.map(object) : [];
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
        sheet: sheetOf(s, agentDraft),
        ...(typeof actions[0]?.label === 'string' ? { nextAction: actions[0].label } : {}),
      };
    }),
  };
}
function sheetOf(step: Record<string, unknown>, agentDraft: boolean): SheetView {
  if (step.sheet && typeof step.sheet === 'object') {
    const v = object(step.sheet);
    if (!SHEET.includes(text(v.status))) throw new Error('Invalid sheet status');
    return {
      status: v.status as SheetStatus,
      ...(typeof v.recheck_reason === 'string' ? { recheckReason: v.recheck_reason } : {}),
      ...(typeof v.gap_hint === 'string' ? { gapHint: v.gap_hint } : {}),
      ...(Number.isSafeInteger(v.prd_version) ? { prdVersion: Number(v.prd_version) } : {}),
      editedSinceReview: v.edited_since_review === true,
      agentDraft: v.agent_draft_pending === true || agentDraft,
      derived: false,
    };
  }
  // Until L4 projects `sheet`: the spec's mapping read backwards, cautious where it is ambiguous
  // (has_findings covers both a faulty draft and a supported one, so it stays a draft).
  const status: SheetStatus =
    step.work_status === 'recheck'
      ? 'recheck'
      : step.work_status === 'not_started'
        ? 'not_started'
        : step.quality_status === 'checked_for_declared_scope'
          ? 'solid'
          : 'draft';
  return { status, editedSinceReview: false, agentDraft, derived: true };
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
