/** Where a practice's seven steps come from. Only L4's versioned client reads the server; until
 * it is built in, a practice shows its original page. `?aipm=fixture` alone shows explicit fake
 * progress over the real guide content, for development; it is never a fallback. */
import zh from '../../../../../scenarios/pm_pilot/aipm-phase1/public/guide.zh.json';
import en from '../../../../../scenarios/pm_pilot/aipm-phase1/public/guide.en.json';
import { IDS, type Language, type StepId } from './model';

export type GuideTransport = (path: string, body?: unknown, method?: string) => Promise<unknown>;
type Writer = (command: Record<string, unknown>) => Promise<unknown>;
/** The subset of L4's AipmClient this page uses; its own types stay in aipm/types.ts. */
export type GuideClient = {
  guide(): Promise<unknown>;
  progress(): Promise<unknown>;
  setFocus: Writer;
  saveStepLink: Writer;
  saveDesign: Writer;
  createBatch: Writer;
  updateBatch(id: string, command: Record<string, unknown>): Promise<unknown>;
  recordAssessment: Writer;
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

/** Explicit fake data: the real authored guide, a made-up snapshot, focus kept in memory. */
function fixtureClient(sessionId: string, language: Language): GuideClient {
  const guide = language === 'en' ? en : zh;
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
      suggested_step: IDS[Math.min(IDS.indexOf(focus) + 1, 6)],
      projection: { complete: true },
      steps: guide.steps.map((s) => ({
        ...s,
        work_status: s.id === focus ? 'working' : 'not_started',
        completed: false,
        quality_status: 'unverified',
        missing: [],
        open_feedback: [],
      })),
    }),
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
