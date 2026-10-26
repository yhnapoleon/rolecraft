/** Where a practice's seven steps come from. Only L4's versioned client reads the server; until
 * it is built in, a practice shows its original page. `?aipm=fixture` alone shows explicit fake
 * progress over the real guide content, for development; it is never a fallback. */
import zh from '../../../../../scenarios/pm_pilot/aipm-phase1/public/guide.zh.json';
import en from '../../../../../scenarios/pm_pilot/aipm-phase1/public/guide.en.json';
import type { Language, StepId } from './model';

export type GuideTransport = (path: string, body?: unknown, method?: string) => Promise<unknown>;
type Writer = (command: Record<string, unknown>) => Promise<unknown>;
/** The subset of L4's AipmClient this page uses; its own types stay in aipm/types.ts. */
export type GuideClient = {
  guide(): Promise<unknown>;
  progress(): Promise<unknown>;
  enroll: Writer;
  setFocus: Writer;
  saveStepLink: Writer;
  saveDesign: Writer;
  createBatch: Writer;
  updateBatch(id: string, command: Record<string, unknown>): Promise<unknown>;
  recordAssessment: Writer;
  /** Adopt or dismiss an agent's design draft (L4); absent until that client is built in. */
  resolveDraft?(id: string, command: Record<string, unknown>): Promise<unknown>;
  /** A section review of one PRD version (L4, v2). */
  createSectionReview?(command: Record<string, unknown>): Promise<unknown>;
  sectionReviews?(stepId?: StepId): Promise<unknown>;
};
export type GuideSource = { client: GuideClient; fixture: boolean };

// Present once L4's client is merged in; an empty match leaves every practice as it was.
const l4 = import.meta.glob<{
  createAipmClient(sessionId: string, transport: GuideTransport): GuideClient;
}>('../../aipm/client.ts');

export const fixtureRequested = () => {
  try {
    return new URLSearchParams(location.search).get('aipm') === 'fixture';
  } catch {
    return false;
  }
};

export async function guideSource(
  sessionId: string,
  transport: GuideTransport,
  language: Language,
): Promise<GuideSource | null> {
  if (fixtureRequested()) return { client: fixtureClient(sessionId, language), fixture: true };
  const load = Object.values(l4)[0];
  if (!load) return null;
  return {
    client: (await load()).createAipmClient(sessionId, transport),
    fixture: false,
  };
}

const fixtureSheets = (en: boolean): Partial<Record<StepId, Record<string, unknown>>> => ({
  business: { status: 'solid', edited_since_review: false, agent_draft_pending: false },
  stakeholders: { status: 'based', edited_since_review: false, agent_draft_pending: false },
  need: {
    status: 'draft',
    edited_since_review: false,
    agent_draft_pending: false,
    gap_hint: en ? 'a fact that would make us not do it' : '一个会让我们不做的事实',
  },
  boundary: {
    status: 'recheck',
    recheck_reason: en ? 'expense policy updated to v2' : '报销政策更新到 v2',
    edited_since_review: false,
    agent_draft_pending: false,
  },
});
/** Explicit fake data: the real authored guide, a made-up snapshot, focus kept in memory. */
function fixtureClient(sessionId: string, language: Language): GuideClient {
  const guide = language === 'en' ? en : zh;
  const sheets = fixtureSheets(language === 'en');
  let focus: StepId = 'business';
  let seq = 0;
  const refused = () => Promise.reject(new Error('Fixture data: this write is not connected.'));
  return {
    guide: async () => guide,
    progress: async () => ({
      ...guide,
      session_id: sessionId,
      as_of: {
        business_seq: seq,
        workspace_revision: seq,
        storage_revision: seq,
      },
      focus_step: focus,
      suggested_step: 'need',
      projection: { complete: true },
      // Every sheet state once, so the compass and the pile can be looked at as a whole.
      steps: guide.steps.map((s) => ({
        ...s,
        work_status: s.id === focus ? 'working' : 'not_started',
        completed: false,
        quality_status: 'unverified',
        missing: [],
        open_feedback: [],
        ...(sheets[s.id as StepId] ? { sheet: sheets[s.id as StepId] } : {}),
      })),
      pending_agent_drafts: [
        {
          ref: {
            session_id: sessionId,
            kind: 'aipm_design_draft',
            object_id: 'fixture-draft',
            version: 1,
          },
          author_kind: 'external_agent',
          steps: ['solution'],
        },
      ],
    }),
    enroll: async () => ({}),
    setFocus: async (command) => {
      focus = (command.payload as { step_id: StepId }).step_id;
      seq += 1;
      return {};
    },
    saveStepLink: refused,
    saveDesign: refused,
    createBatch: refused,
    updateBatch: refused,
    recordAssessment: refused,
  };
}
