/** One product manager practice's seven steps: whether the practice has them, the latest server
 * snapshot, and the host the design and evaluation features are installed against. A practice
 * the server does not enrol (every old one) stays on its original page; nothing is migrated. */
import type { AipmFeatureId, AipmHost } from '../../aipm/host';
import { createAipmRegistry, installAipmFeatures } from '../../aipm/registry';
import type { ObjectRef, ProductCreate, ProductEdit, ReviewInput } from '../../contracts-v2';
import type { V4HostAdapter } from '../../v4-host';
import { publishedContent } from './content';
import type { GuideProps } from './guide';
import {
  guideView,
  matchingSnapshot,
  progressView,
  type GuideView,
  type Language,
  type ProgressView,
  type StepId,
} from './model';
import { guideSource, type GuideClient, type GuideTransport } from './source';

type Attempt = { id: string };
type Role = 'manager' | 'business' | 'technical';
export type PracticeDeps = {
  current(): Attempt | null;
  transport(a: Attempt): GuideTransport;
  dataHost(a: Attempt): V4HostAdapter | null;
  language(a: Attempt): Language;
  redraw(): void;
  openMaterial(id: string): void;
  openChat(role: Role, text: string): void;
  openWork(ref?: ObjectRef): void;
  openSettings(): void;
  submit(): void;
};
type State = {
  phase: 'loading' | 'off' | 'ready';
  client?: GuideClient;
  fixture: boolean;
  guide?: GuideView;
  progress?: ProgressView;
  asOf?: string;
  readAt?: string;
  stale: boolean;
  busy: boolean;
  error?: string;
  feature: AipmFeatureId | null;
};

const OPEN = 'rolecraft.aipm.open.v1';
const folded = (id: string) => {
  try {
    return JSON.parse(localStorage.getItem(OPEN) || '{}')[id] === false;
  } catch {
    return false;
  }
};
const keepFold = (id: string, open: boolean) => {
  try {
    localStorage.setItem(
      OPEN,
      JSON.stringify({
        ...JSON.parse(localStorage.getItem(OPEN) || '{}'),
        [id]: open,
      }),
    );
  } catch {
    /* this page only */
  }
};
const reason = (e: unknown) => (e instanceof Error ? e.message : String(e));
// Not enrolled, no such route yet, or not mounted: the practice simply has no seven steps.
const absent = (e: unknown) =>
  [404, 409, 503].includes(Number((e as { status?: number })?.status)) ||
  (e as { code?: string })?.code === 'aipm_not_enabled';

export function createAipmPractice(deps: PracticeDeps) {
  const states = new Map<string, State>();
  const open = new Map<string, boolean>();
  const registry = createAipmRegistry();
  let missing: AipmFeatureId[] | null = null;

  const stateOf = (a: Attempt) => states.get(a.id);
  const asOfKey = (a: Attempt) => JSON.stringify(deps.dataHost(a)?.snapshot().asOf ?? null);

  async function load(a: Attempt) {
    const s: State = states.get(a.id) ?? {
      phase: 'loading',
      fixture: false,
      stale: false,
      busy: false,
      feature: null,
    };
    states.set(a.id, s);
    try {
      if (!s.client) {
        const source = await guideSource(a.id, deps.transport(a), deps.language(a));
        if (!source) {
          s.phase = 'off';
          return;
        }
        s.client = source.client;
        s.fixture = source.fixture;
      }
      s.asOf = asOfKey(a);
      const [g, p] = await Promise.all([s.client.guide(), s.client.progress()]);
      const guide = guideView(g),
        progress = progressView(p);
      const lang = deps.language(a);
      if (!matchingSnapshot(guide, progress, a.id, lang)) throw new Error('mismatched snapshot');
      Object.assign(s, {
        phase: 'ready',
        guide,
        progress,
        stale: false,
        error: undefined,
        readAt: new Date().toLocaleTimeString(lang === 'en' ? 'en-GB' : 'zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
        }),
      });
      if (missing === null) missing = await installAipmFeatures(host);
    } catch (e) {
      if (s.phase === 'ready') s.stale = true;
      else s.phase = 'off';
      if (!absent(e)) s.error = reason(e);
    } finally {
      if (deps.current()?.id === a.id) deps.redraw();
    }
  }

  /** The practice has seven steps. Reading starts the first load and follows server changes. */
  function ready(a: Attempt | null): boolean {
    if (!a) return false;
    const s = stateOf(a);
    if (!s) {
      void load(a);
      return false;
    }
    if (s.phase === 'ready' && !s.busy && s.asOf !== asOfKey(a)) {
      s.asOf = asOfKey(a);
      void load(a);
    }
    return s.phase === 'ready';
  }

  async function command(operation: string, payload: Record<string, unknown>) {
    const a = deps.current();
    if (!a) throw new Error('No practice');
    const s = stateOf(a);
    if (!s?.client) throw new Error('AIPM is not connected');
    // A fresh Command per explicit action; the version point is the session's current one.
    const at = s.fixture
      ? { business_seq: 0, workspace_revision: 0 }
      : (
          (await deps.transport(a)(`/sessions/${encodeURIComponent(a.id)}`)) as {
            state: { business_seq: number; workspace_revision: number };
          }
        ).state;
    const cmd = {
      schema_version: 2,
      request_id: crypto.randomUUID(),
      expected_version: at.business_seq,
      expected_workspace_revision: at.workspace_revision,
      operation,
      payload: { schema_version: 2, ...payload },
    };
    const c = s.client;
    switch (operation) {
      case 'aipm.focus.set':
        return c.setFocus(cmd);
      case 'aipm.step_links.save':
        return c.saveStepLink(cmd);
      case 'aipm.design.save':
        return c.saveDesign(cmd);
      case 'aipm.batch.create':
        return c.createBatch(cmd);
      case 'aipm.batch.update':
        return c.updateBatch(String(payload.batch_id), cmd);
      case 'aipm.assessment.record':
        return c.recordAssessment(cmd);
      default:
        throw new Error(`Unsupported AIPM operation: ${operation}`);
    }
  }

  const host: AipmHost<ProgressView, GuideClient> = {
    getSessionContext() {
      const a = deps.current();
      const snap = a ? deps.dataHost(a)?.snapshot() : null;
      if (!a || !snap) return null;
      return {
        sessionId: a.id,
        workLanguage: deps.language(a),
        scenarioHash: snap.session?.protocol === 2 ? snap.session.scenarioHash : '',
        asOf: snap.asOf,
        readOnly: snap.readOnly === true,
      };
    },
    getDataHost: () => {
      const a = deps.current();
      return a ? deps.dataHost(a) : null;
    },
    getClient: () => {
      const a = deps.current();
      return (a && stateOf(a)?.client) || null;
    },
    async readProgress() {
      const a = deps.current();
      if (!a) throw new Error('No practice');
      await load(a);
      const p = stateOf(a)?.progress;
      if (!p) throw new Error('AIPM progress unavailable');
      return p;
    },
    async readContent(id) {
      const a = deps.current(),
        g = a && stateOf(a)?.guide;
      if (!g) throw new Error('AIPM guide unavailable');
      return publishedContent(id, g.language, g.revision);
    },
    async readGuide() {
      const a = deps.current();
      return a ? stateOf(a)?.guide : undefined;
    },
    command,
    async recover(requestId) {
      return host.getDataHost()?.recover(requestId);
    },
    async sendPreparedTest(cmd) {
      const a = deps.current();
      if (!a) throw new Error('No practice');
      if (cmd.operation !== 'tests.create' || typeof cmd.request_id !== 'string')
        throw new Error('Not a prepared tests.create command');
      if (stateOf(a)?.fixture) throw new Error('Fixture data: tests are not run.');
      return deps.transport(a)(`/sessions/${encodeURIComponent(a.id)}/tests`, cmd, 'POST');
    },
    async openMaterial(id) {
      deps.openMaterial(id);
    },
    async openWork(ref) {
      deps.openWork(ref);
    },
    async openColleague(role, question = '') {
      deps.openChat(role, question);
    },
    async openSettings() {
      deps.openSettings();
    },
    async requestReview(input: ReviewInput) {
      return host.getDataHost()?.command('reviews.create', input);
    },
    async createWorkVersion(input: ProductCreate | ProductEdit) {
      const data = host.getDataHost();
      return 'product_id' in input
        ? data?.command('work_products.versions.create', input)
        : data?.command('work_products.create', input);
    },
    async refresh() {
      const a = deps.current();
      if (a) await load(a);
    },
    registerFeature: (id, feature) => registry.register(id, feature),
    openFeature(id) {
      const a = deps.current(),
        s = a && stateOf(a);
      if (!a || !s) return;
      s.feature = s.feature === id ? null : id;
      deps.redraw();
    },
  };

  async function choose(a: Attempt, step: StepId) {
    const s = stateOf(a);
    if (!s || s.busy) return;
    s.busy = true;
    s.error = undefined;
    deps.redraw();
    try {
      await command('aipm.focus.set', { step_id: step });
      s.busy = false;
      await load(a);
    } catch (e) {
      s.busy = false;
      s.error = reason(e);
      deps.redraw();
    }
  }

  /** Island props for the guide once the practice is ready. */
  function props(a: Attempt): GuideProps | null {
    const s = stateOf(a);
    if (!s?.guide || !s.progress) return null;
    const isOpen = open.get(a.id) ?? !folded(a.id);
    return {
      guide: s.guide,
      progress: s.progress,
      open: isOpen,
      fixture: s.fixture,
      stale: s.stale,
      updatedAt: s.readAt,
      busy: s.busy,
      error: s.error,
      onToggle: () => {
        open.set(a.id, !isOpen);
        keepFold(a.id, !isOpen);
        deps.redraw();
      },
      onChoose: (id) => void choose(a, id),
      onQuestion: (role, text) => deps.openChat(role, text),
      onMaterial: (id) => deps.openMaterial(id),
      onPrimary: (step) => {
        if (step.primary.id === 'open_design') host.openFeature('design');
        else if (step.primary.id === 'open_evaluation') host.openFeature('evaluation');
        else deps.submit();
      },
      onRefresh: () => void load(a),
    };
  }

  /** The opened design / evaluation feature, or a plain note that it is not in this build. */
  function mountFeature(a: Attempt, root: HTMLElement | null) {
    const s = stateOf(a);
    if (!root || !s) return;
    const id = s.feature;
    const feature = id ? registry.get(id) : undefined;
    if (root.dataset.feature === (id ?? '')) return;
    root.dataset.feature = id ?? '';
    if (!id) {
      root.innerHTML = '';
      return;
    }
    if (!feature) {
      const en = s.guide?.language === 'en';
      root.innerHTML = `<p class="aipm-feature__missing">${
        en
          ? 'This part is not in this build yet (incomplete candidate).'
          : '这一部分还没接入当前版本（候选不完整）。'
      }</p>`;
      return;
    }
    root.innerHTML = feature.render();
    registry.mount(id, root);
  }

  return { ready, props, mountFeature, host, missing: () => missing };
}
