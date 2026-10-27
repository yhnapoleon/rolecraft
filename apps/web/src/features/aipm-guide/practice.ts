/** One product manager practice's seven steps: whether the practice has them, the latest server
 * snapshot, and the host the design and evaluation features are installed against. A practice
 * the server does not enrol (every old one) stays on its original page; nothing is migrated. */
import type { AipmColleague, AipmFeatureId, AipmHost, AipmScreen } from '../../aipm/host';
import { createAipmRegistry, installAipmFeatures } from '../../aipm/registry';
import type { ObjectRef, ProductCreate, ProductEdit, ReviewInput } from '../../contracts-v2';
import type { V4HostAdapter } from '../../v4-host';
import { versionMoved } from '../../v4-data-host';
import type { StackProps } from '../../shell/work-stack/stack';
import type { CompassProps } from './compass';
import { publishedContent } from './content';
import {
  IDS,
  guideView,
  matchingSnapshot,
  progressView,
  type GuideView,
  type Language,
  type ProgressView,
  type StepId,
} from './model';
import {
  sheetRows,
  sheetWords,
  stackItems,
  stackSummary,
  suggestionLine,
  orderGlyph,
} from './sheets';
import { guideSource, type GuideClient, type GuideTransport } from './source';
import { screenFromHistory } from './screen-history';

type Attempt = { id: string };
export type MentorCard = { question: string; pointer?: string; materialId?: string };
type Role = 'manager' | 'business' | 'technical';
export type PracticeDeps = {
  current(): Attempt | null;
  transport(a: Attempt): GuideTransport;
  dataHost(a: Attempt): V4HostAdapter | null;
  language(a: Attempt): Language;
  redraw(): void;
  openMaterial(id: string): void;
  openChat(role: Role, text: string): void;
  /** Sends the question to that colleague at once, through the normal conversation. */
  ask(role: Role, text: string): void;
  openWork(ref?: ObjectRef): void;
  openSettings(): void;
  submit(): void;
  /** One notice per newly arrived agent draft, with an action that opens it. */
  notifyDraft(text: string, label: string, dismiss: string, open: () => void): void;
  /** Opens the colleague's conversation with this message in the composer (not sent), and the
   * PRD attachment chip set as given. */
  prefillColleague(
    colleague: AipmColleague,
    prefill: string,
    attachPrd: boolean,
    detail?: string,
  ): void;
  /** A question asked from a review: its rule-triggered prompts for that colleague, shown under
   * a local reply as preset prompts (never as the colleague's words). */
  rememberPrompts(colleague: AipmColleague, prompts: MentorCard[]): void;
  /** Whether that colleague has been shared this exact PRD version already. */
  prdSharedWith(colleague: AipmColleague, prd: { id: string; version: number }): boolean;
  /** The main screen lives on the board: go there first when elsewhere. */
  showBoard(screen: AipmScreen): void;
  /** Opens a work product in the existing editor (the whole PRD). */
  openProduct(productId: string): void;
  /** A material's page, for the column beside a worksheet. */
  materialHtml(materialId: string): string;
  materialTitle(materialId: string): string;
  colleagueName(colleague: AipmColleague): string;
  /** Reads a material the way opening it does (a counted read), then redraws. */
  readMaterial(materialId: string): void;
  /** Quotes passages of that material into the open worksheet, each with the exact reference
   * the server returned: the given paragraphs when they match read passages, otherwise the
   * ones picked in the existing evidence picker. */
  quoteToSheet(materialId: string, paragraphs?: string[]): void;
  /** Starts a new free work product (a free sheet). */
  newFreeSheet(): void;
};
type State = {
  phase: 'loading' | 'off' | 'ready';
  client?: GuideClient;
  fixture: boolean;
  guide?: GuideView;
  progress?: ProgressView;
  /** The server's AipmProgress as read, for features that consume L4's own DTO. */
  raw?: unknown;
  asOf?: string;
  readAt?: string;
  stale: boolean;
  busy: boolean;
  error?: string;
  feature: AipmFeatureId | null;
  /** v2: what the main screen shows; the workbench unless a sheet or review is open. */
  screen: AipmScreen;
  /** Enrollment was asked for once; a refusal leaves the practice on its original page. */
  enrolled?: boolean;
  /** A read is under way; changes meanwhile are picked up by one more read after it. */
  reading?: boolean;
  again?: boolean;
};

const HINT = 'rolecraft.aipm.stack-hint.v1';
const hintSeen = () => {
  try {
    return !!localStorage.getItem(HINT);
  } catch {
    return true;
  }
};
const keepHint = () => {
  try {
    localStorage.setItem(HINT, '1');
  } catch {
    /* this page only */
  }
};
const SEEN = 'rolecraft.aipm.drafts-seen.v1';
const readSeen = (): Record<string, string[]> => {
  try {
    return JSON.parse(localStorage.getItem(SEEN) || '{}');
  } catch {
    return {};
  }
};
const writeSeen = (v: Record<string, string[]>) => {
  try {
    localStorage.setItem(SEEN, JSON.stringify(v));
  } catch {
    /* this page only */
  }
};
// The panel lists drafts once its own read returns: look for the draft for a few seconds.
function locate(root: HTMLElement, id: string, tries = 15) {
  const card =
    root.querySelector<HTMLElement>(`[data-draft-id="${CSS.escape(id)}"]`) ??
    root.querySelector<HTMLElement>('.aipm-design__draft');
  if (card) {
    card.scrollIntoView({ block: 'center' });
    card.querySelector<HTMLElement>('button')?.focus({ preventScroll: true });
  } else if (tries > 0) setTimeout(() => locate(root, id, tries - 1), 200);
}
const signature = (s: State) =>
  JSON.stringify([s.phase, s.raw ?? null, s.stale, s.error ?? null, s.busy, s.feature, s.screen]);
const reason = (e: unknown) => (e instanceof Error ? e.message : String(e));
// Not enrolled, no such route yet, or not mounted: the practice simply has no seven steps.
const absent = (e: unknown) =>
  [404, 409, 503].includes(Number((e as { status?: number })?.status)) ||
  (e as { code?: string })?.code === 'aipm_not_enabled';

/** Sends once more, with a freshly built command, only when the version point had moved. */
export async function withVersionRetry<T>(send: () => Promise<T>): Promise<T> {
  try {
    return await send();
  } catch (error) {
    if (!versionMoved(error)) throw error;
    return send();
  }
}

export function createAipmPractice(deps: PracticeDeps) {
  const states = new Map<string, State>();
  const registry = createAipmRegistry();
  let missing: AipmFeatureId[] | null = null;
  let live: { key: string; el: HTMLElement } | null = null;
  let reveal = false;
  let draftTarget: string | null = null;

  function announceDrafts(a: Attempt, s: State) {
    const guide = s.guide;
    const drafts = s.progress?.drafts ?? [];
    if (!guide || !drafts.length) return;
    const seen = readSeen();
    const known = new Set(seen[a.id] ?? []);
    const fresh = drafts.filter((d) => !known.has(d.key));
    if (!fresh.length) return;
    for (const d of fresh) known.add(d.key);
    writeSeen({ ...seen, [a.id]: [...known].slice(-50) });
    const en = guide.language === 'en';
    for (const d of fresh) {
      const where = d.steps.map((id) => guide.steps[IDS.indexOf(id)].label).join(en ? ', ' : '、');
      deps.notifyDraft(
        en
          ? `Your agent sent 1 draft${where ? `: ${where}` : ''}`
          : `你的 Agent 交来 1 份草稿${where ? `：${where}` : ''}`,
        en ? 'Review' : '去确认',
        en ? 'Dismiss' : '关闭提示',
        () => void openDraft(a, d),
      );
    }
  }

  /** Go to the draft's step, open the design panel there and bring that draft into view. */
  async function openDraft(a: Attempt, d: { id: string; steps: StepId[] }) {
    const s = stateOf(a);
    if (!s || deps.current()?.id !== a.id) return;
    const step = d.steps[0];
    draftTarget = d.id;
    host.openWorksheet(step ?? s.progress?.focus ?? 'business');
  }

  const stateOf = (a: Attempt) => states.get(a.id);
  const asOfKey = (a: Attempt) => JSON.stringify(deps.dataHost(a)?.snapshot().asOf ?? null);

  async function load(a: Attempt): Promise<void> {
    const prior = states.get(a.id);
    if (prior?.reading) {
      prior.again = true;
      return;
    }
    const s: State = prior ?? {
      phase: 'loading',
      fixture: false,
      stale: false,
      busy: false,
      feature: null,
      screen: screenFromHistory(typeof history === 'undefined' ? null : history.state, a.id),
    };
    states.set(a.id, s);
    s.reading = true;
    const seen = signature(s);
    try {
      if (!s.client) {
        const source = await guideSource(a.id, deps.transport(a), deps.language(a));
        if (!source) {
          s.phase = 'off';
          return;
        }
        s.client = source.client;
        // The page polls the session; when its version point moves (a colleague, a run, an
        // agent's draft), read progress again without waiting for the stage to redraw.
        deps.dataHost(a)?.subscribe(() => {
          if (s.phase === 'ready' && !s.busy && s.asOf !== asOfKey(a)) void load(a);
        });
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
        raw: p,
        stale: false,
        error: undefined,
        readAt: new Date().toLocaleTimeString(lang === 'en' ? 'en-GB' : 'zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
        }),
      });
      if (missing === null) missing = await installAipmFeatures(host);
      announceDrafts(a, s);
    } catch (failure) {
      let e = failure;
      // A new practice bound to the seven-step package: the person started it as a product
      // manager, so enrol it once (idempotent on the server) and read again. A restored practice
      // that is already enrolled never reaches this; an old one answers aipm_not_enabled.
      if ((e as { code?: string })?.code === 'aipm_not_enrolled' && !s.enrolled && !s.fixture) {
        s.enrolled = true;
        try {
          await command('aipm.enroll', {});
          return load(a);
        } catch (err) {
          e = err;
        }
      }
      if (s.phase === 'ready') s.stale = true;
      else s.phase = 'off';
      if (!absent(e)) s.error = reason(e);
    } finally {
      // Redraw only for a real change: a read that returns the same snapshot leaves the page
      // (and any feature mounted in it) alone.
      s.reading = false;
      if (deps.current()?.id === a.id && signature(s) !== seen) deps.redraw();
      if (s.again) {
        s.again = false;
        void load(a);
      }
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

  /** One explicit action. A version point moved by a background job (409 version_conflict: the
   * server ran nothing) is rebuilt on the current state once, quietly; content conflicts are not. */
  async function command(operation: string, payload: Record<string, unknown>) {
    return withVersionRetry(() => sendOnce(operation, payload));
  }
  async function sendOnce(operation: string, payload: Record<string, unknown>) {
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
      case 'aipm.enroll':
        return c.enroll(cmd);
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
      case 'aipm.section_review.create':
        if (!c.createSectionReview) throw new Error('AIPM section reviews are not connected');
        return c.createSectionReview(cmd);
      case 'aipm.design_drafts.resolve':
        if (!c.resolveDraft) throw new Error('AIPM agent drafts are not connected');
        return c.resolveDraft(String(payload.draft_id), cmd);
      default:
        throw new Error(`Unsupported AIPM operation: ${operation}`);
    }
  }

  const host: AipmHost<unknown, GuideClient> = {
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
      const s = stateOf(a);
      const fresh = s?.phase === 'ready' && !s.stale && s.asOf === asOfKey(a);
      if (!fresh) await load(a);
      const p = stateOf(a)?.raw;
      if (!p) throw new Error('AIPM progress unavailable');
      return p;
    },
    async readContent(id) {
      const a = deps.current(),
        g = a && stateOf(a)?.guide;
      if (!g) throw new Error('AIPM guide unavailable');
      return publishedContent(id, g.language);
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
    currentScreen() {
      const a = deps.current();
      return (a && stateOf(a)?.screen) || { kind: 'workbench' };
    },
    openWorksheet(sheet) {
      show({ kind: 'worksheet', sheet });
      // Opening a step's sheet is the person's explicit choice of what they are working on.
      const a = deps.current(),
        s = a && stateOf(a);
      if (a && s && !sheet.startsWith('free:') && s.progress?.focus !== sheet)
        void choose(a, sheet as StepId);
    },
    openMaterialSplit(materialId) {
      const a = deps.current(),
        s = a && stateOf(a);
      if (s?.screen.kind === 'worksheet' && innerWidth >= 1200) {
        show({ ...s.screen, material: materialId });
        deps.readMaterial(materialId);
      } else deps.openMaterial(materialId);
    },
    openReview(step, reviewRef) {
      show({ kind: 'review', step, ...(reviewRef ? { reviewRef } : {}) });
    },
    openWorkbench() {
      show({ kind: 'workbench' });
    },
    async askColleague({ colleague, prefill, attachPrd, detail }) {
      const a = deps.current(),
        prd = a && stateOf(a)?.progress?.prd;
      const s = a && stateOf(a);
      if (s?.screen.kind === 'review') void reviewPrompts(s, s.screen, colleague);
      const attach = attachPrd ?? (!!prd && !deps.prdSharedWith(colleague, prd));
      deps.prefillColleague(colleague, prefill, attach, detail);
    },
    // The evaluation desk keeps its own screen and saved batches beside sheet ⑥.
    openFeature(id) {
      const a = deps.current(),
        s = a && stateOf(a);
      if (!a || !s) return;
      if (id === 'evaluation') show({ kind: 'worksheet', sheet: 'assurance', feature: 'evaluation' });
      else if (id === 'review') host.openReview(s.progress?.focus ?? 'business');
      else host.openWorksheet(s.progress?.focus ?? 'business');
    },
  };

  /** The review being looked at: its prompts for this colleague (the server's mentor prompts). */
  async function reviewPrompts(
    s: State,
    screen: Extract<AipmScreen, { kind: 'review' }>,
    colleague: AipmColleague,
  ) {
    try {
      const page = (await s.client?.sectionReviews?.(screen.step)) as
        | {
            items?: {
              ref: { object_id: string; version: number };
              review: Record<string, unknown>;
            }[];
          }
        | undefined;
      const items = page?.items ?? [];
      // The model's look writes the same review again as a later version: take its newest.
      const hit = screen.reviewRef
        ? items
            .filter((i) => i.ref.object_id === screen.reviewRef?.object_id)
            .sort((x, y) => y.ref.version - x.ref.version)[0]
        : items[0];
      const wire = colleague === 'technical' ? 'tech' : colleague;
      const prompts = ((hit?.review.mentor_prompts as Record<string, unknown>[]) ?? [])
        .filter((m) => m.colleague === wire && typeof m.question === 'string')
        .map((m) => {
          const pointer = m.pointer as {
            text?: string;
            refs?: { kind: string; object_id: string }[];
          } | null;
          const material = pointer?.refs?.find((r) => r.kind === 'material');
          return {
            question: m.question as string,
            ...(pointer?.text ? { pointer: pointer.text } : {}),
            ...(material ? { materialId: material.object_id } : {}),
          };
        });
      deps.rememberPrompts(colleague, prompts);
    } catch {
      deps.rememberPrompts(colleague, []);
    }
  }

  function show(screen: AipmScreen, fromHistory = false) {
    const a = deps.current(),
      s = a && stateOf(a);
    if (!s) return;
    if (fromHistory && JSON.stringify(screen) === JSON.stringify(s.screen)) return;
    s.screen = screen;
    reveal = screen.kind !== 'workbench';
    // The existing route owner writes history and renders once. Popstate restores before render.
    if (!fromHistory) deps.showBoard(screen);
  }

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

  function openPrd(a: Attempt) {
    const s = stateOf(a);
    if (s?.progress?.prd) deps.openProduct(s.progress.prd.id);
    else host.openWorksheet(s?.progress?.suggested ?? 'business');
  }
  const sheetOpen = (s: State) =>
    s.screen.kind === 'worksheet'
      ? s.screen.sheet
      : s.screen.kind === 'review'
        ? s.screen.step
        : undefined;

  /** The compass under the toolbar, once the practice is ready. */
  function compassProps(a: Attempt): CompassProps | null {
    const s = stateOf(a);
    if (!s?.guide || !s.progress) return null;
    const rows = sheetRows(s.guide, s.progress);
    return {
      language: s.guide.language,
      rows,
      suggestion: suggestionLine(rows, s.progress, s.guide.language),
      ...(sheetOpen(s) ? { current: sheetOpen(s) } : {}),
      fixture: s.fixture,
      stale: s.stale,
      ...(s.readAt ? { updatedAt: s.readAt } : {}),
      onOpen: (id) => host.openWorksheet(id as StepId),
      onReview: (id) => host.openReview(id as StepId),
      onPrd: () => openPrd(a),
      onRefresh: () => void load(a),
    };
  }

  /** The pile of sheets in the stage's lower-left corner. */
  function stackProps(a: Attempt): StackProps | null {
    const s = stateOf(a);
    if (!s?.guide || !s.progress) return null;
    const lang = s.guide.language;
    const w = sheetWords(lang);
    const rows = sheetRows(s.guide, s.progress);
    const sum = stackSummary(rows, lang);
    // The pile's first hint waits for the walk-through to close, so it is not hidden under it.
    const first = !hintSeen() && !document.querySelector('.rc-tour');
    return {
      title: w.title,
      status: sum.status,
      ariaLabel: sum.aria,
      capsule: sum.capsule,
      items: stackItems(rows, lang),
      segments: w.segment,
      header: {
        title: w.sheets(rows.length),
        actions: [
          { label: w.openPrd, run: () => openPrd(a) },
          { label: w.newFree, plus: true, run: () => deps.newFreeSheet() },
        ],
      },
      words: { suggested: w.suggested, close: w.close, pinned: w.pinned },
      ...(first ? { hint: w.hint, onHint: keepHint } : {}),
      onOpen: (id) => host.openWorksheet(id as StepId),
    };
  }

  /** Where the main screen is, for the way back to the workbench: "③ Validate the need",
   * "③ Validate the need · Review", or null on the workbench. */
  function screenName(a: Attempt | null): string | null {
    const s = a && stateOf(a);
    if (!s?.guide || s.phase !== 'ready' || s.screen.kind === 'workbench') return null;
    const en = s.guide.language === 'en';
    const step = s.screen.kind === 'review' ? s.screen.step : s.screen.sheet;
    const row = s.guide.steps.find((x) => x.id === step);
    const name = row ? `${orderGlyph(row.order)} ${row.label}` : en ? 'Free sheet' : '自由纸';
    return s.screen.kind === 'review' ? `${name} · ${en ? 'Review' : '批改单'}` : name;
  }

  /** What the main screen shows instead of the workbench, or null for the workbench. */
  function screenOf(a: Attempt | null): AipmScreen['kind'] {
    const s = a && stateOf(a);
    return s?.phase === 'ready' ? s.screen.kind : 'workbench';
  }

  /** The main screen when it is not the workbench: breadcrumbs, then the worksheet (L2) or the
   * review (L3), and a material beside a worksheet. Until a line delivers, the phase-1 design
   * panel stands in for a worksheet (the evaluation desk for ⑥); a review says it is missing. */
  function mountMain(a: Attempt, root: HTMLElement | null) {
    const s = stateOf(a);
    if (!root || !s?.guide) return;
    const screen = s.screen;
    if (screen.kind === 'workbench') {
      root.replaceChildren();
      return;
    }
    const en = s.guide.language === 'en';
    let id: AipmFeatureId | null;
    if (screen.kind === 'review') id = registry.get('review') ? 'review' : null;
    else if (screen.feature === 'evaluation') id = registry.get('evaluation') ? 'evaluation' : null;
    else if (registry.get('worksheet')) id = 'worksheet';
    else if (screen.sheet === 'assurance' && registry.get('evaluation')) id = 'evaluation';
    else id = registry.get('design') ? 'design' : null;
    const target =
      screen.kind === 'review'
        ? `review:${screen.step}:${screen.reviewRef?.version ?? ''}`
        : `sheet:${screen.sheet}`;
    // The stand-in design panel opens on the focused section, so it follows the focus too.
    const key = `${a.id}:${id}:${target}:${id === 'design' ? (s.progress?.focus ?? '') : ''}`;
    if (live?.key !== key) {
      const el = document.createElement('div');
      el.className = 'aipm-main__body';
      const feature = id && registry.get(id);
      if (feature) {
        el.innerHTML = feature.render();
        registry.mount(id as AipmFeatureId, el);
      } else {
        el.innerHTML = `<p class="aipm-main__missing">${
          en
            ? 'This part is not in this build yet (incomplete candidate).'
            : '这一部分还没接入当前版本（候选不完整）。'
        }</p>`;
      }
      live = { key, el };
    }
    const material = screen.kind === 'worksheet' ? screen.material : undefined;
    const nav = crumbs(a, s);
    const parts: HTMLElement[] = [nav, live.el];
    root.dataset.split = material ? 'true' : 'false';
    if (material) {
      // "Side by side: SD-120 field notes ✕" closes the column from where the path is read.
      const split = document.createElement('span');
      split.className = 'aipm-main__split';
      split.innerHTML = `${en ? 'Side by side: ' : '并排：'}<b></b><button type="button" class="aipm-main__aside-quote" data-aipm-quote>${
        en ? 'Choose passages to quote' : '挑选段落引用'
      }</button><button type="button" class="aipm-main__aside-close" data-aipm-close-split aria-label="${
        en ? 'Close the side material' : '关闭并排资料'
      }">✕</button>`;
      (split.querySelector('b') as HTMLElement).textContent = deps.materialTitle(material);
      split.querySelector('[data-aipm-close-split]')?.addEventListener('click', () => {
        if (s.screen.kind === 'worksheet') show({ kind: 'worksheet', sheet: s.screen.sheet });
      });
      split
        .querySelector('[data-aipm-quote]')
        ?.addEventListener('click', () => deps.quoteToSheet(material));
      nav.append(split);
      const aside = document.createElement('aside');
      aside.className = 'aipm-main__aside';
      aside.innerHTML = deps.materialHtml(material);
      selectionPill(aside, material, en);
      parts.push(aside);
    }
    root.replaceChildren(...parts);
    // Just opened: bring it to the top of the view, where the person is about to work.
    if (reveal) {
      reveal = false;
      const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
      root.scrollIntoView({ block: 'start', behavior: still || document.documentElement.hasAttribute('data-aipm-flying') ? 'auto' : 'smooth' });
    }
    locateDraft(live.el);
  }
  /** Selecting words in the side material raises an ink pill above them: quote the paragraphs
   * they sit in straight into the sheet, or ask a colleague about them. */
  function selectionPill(aside: HTMLElement, material: string, en: boolean) {
    const pill = document.createElement('div');
    pill.className = 'aipm-quote-pill';
    pill.setAttribute('role', 'toolbar');
    pill.hidden = true;
    const colleague: AipmColleague = 'business';
    pill.innerHTML = `<button type="button" data-q>${en ? 'Quote into the sheet' : '引用到工作纸'}</button><span aria-hidden="true"></span><button type="button" data-ask></button>`;
    (pill.querySelector('[data-ask]') as HTMLElement).textContent =
      `${en ? 'Ask ' : '问 '}${deps.colleagueName(colleague)}`;
    pill.setAttribute('aria-label', en ? 'Selected words' : '选中的文字');
    aside.append(pill);
    let picked: { text: string; paragraphs: string[] } | null = null;
    const hide = () => {
      pill.hidden = true;
      picked = null;
    };
    const place = () => {
      const sel = getSelection();
      const range = sel && !sel.isCollapsed && sel.rangeCount ? sel.getRangeAt(0) : null;
      const text = sel?.toString().trim() ?? '';
      if (
        !range ||
        !text ||
        !aside.contains(range.commonAncestorContainer) ||
        pill.contains(range.commonAncestorContainer)
      )
        return hide();
      const blocks = [...aside.querySelectorAll<HTMLElement>('p, li, blockquote, td, pre')].filter(
        (el) => !el.closest('.aipm-quote-pill') && range.intersectsNode(el),
      );
      const paragraphs = blocks
        .filter((el) => !blocks.some((o) => o !== el && el.contains(o)))
        .map((el) => el.innerText.trim())
        .filter(Boolean);
      picked = { text, paragraphs: paragraphs.length ? paragraphs : [text] };
      const r = range.getBoundingClientRect(),
        box = aside.getBoundingClientRect();
      pill.hidden = false;
      const half = pill.offsetWidth / 2;
      const x = Math.min(Math.max(r.left + r.width / 2 - box.left, half + 4), box.width - half - 4);
      const above = r.top - box.top + aside.scrollTop - pill.offsetHeight - 8;
      pill.style.left = `${x}px`;
      pill.style.top = `${above < aside.scrollTop ? r.bottom - box.top + aside.scrollTop + 8 : above}px`;
    };
    aside.addEventListener('pointerup', () => requestAnimationFrame(place));
    aside.addEventListener('keyup', (e) => {
      if (e.shiftKey || e.key === 'Shift') place();
      else if (e.key === 'Escape') hide();
    });
    aside.addEventListener('scroll', hide, { passive: true });
    pill.addEventListener('pointerdown', (e) => e.preventDefault());
    pill.querySelector('[data-q]')?.addEventListener('click', () => {
      if (picked) deps.quoteToSheet(material, picked.paragraphs);
      getSelection()?.removeAllRanges();
      hide();
    });
    pill.querySelector('[data-ask]')?.addEventListener('click', () => {
      if (!picked) return;
      const title = deps.materialTitle(material);
      const line =
        [...picked.text].length > 80 ? `${[...picked.text].slice(0, 80).join('')}…` : picked.text;
      void host.askColleague({
        colleague,
        prefill: en
          ? `About this line in “${title}”: “${line}” — `
          : `关于《${title}》里这句：「${line}」——`,
      });
      getSelection()?.removeAllRanges();
      hide();
    });
  }
  function locateDraft(el: HTMLElement) {
    if (!draftTarget) return;
    const id = draftTarget;
    draftTarget = null;
    locate(el, id);
  }

  /** Workbench › Pilot PRD › ③ Validate the need (› Review). Each crumb but the last opens. */
  function crumbs(a: Attempt, s: State) {
    const g = s.guide;
    const en = g?.language === 'en';
    const nav = document.createElement('nav');
    nav.className = 'aipm-main__crumbs';
    nav.setAttribute('aria-label', en ? 'Where you are' : '当前位置');
    const add = (text: string, run?: () => void) => {
      if (nav.childElementCount) {
        const sep = document.createElement('span');
        sep.className = 'aipm-main__sep';
        sep.setAttribute('aria-hidden', 'true');
        sep.textContent = '›';
        nav.append(sep);
      }
      const el = document.createElement(run ? 'button' : 'span');
      el.textContent = text;
      if (run) {
        (el as HTMLButtonElement).type = 'button';
        el.addEventListener('click', run);
      } else el.setAttribute('aria-current', 'page');
      nav.append(el);
    };
    add(en ? 'Pilot PRD' : '试点 PRD', () => openPrd(a));
    const screen = s.screen;
    const step =
      screen.kind === 'review' ? screen.step : screen.kind === 'worksheet' ? screen.sheet : null;
    const row = g?.steps.find((x) => x.id === step);
    const name = row ? `${orderGlyph(row.order)} ${row.label}` : en ? 'Free sheet' : '自由纸';
    if (screen.kind === 'review') {
      add(name, () => host.openWorksheet(screen.step));
      add(en ? 'Review' : '批改单');
    } else add(name);
    return nav;
  }

  function restoreHistory(value: unknown) {
    const a = deps.current();
    if (a) show(screenFromHistory(value, a.id), true);
  }

  // Esc closes the open sheet or review back to the workbench, unless something else used it
  // (a dialog, an open pile, a field being typed in).
  if (typeof document !== 'undefined')
    document.addEventListener('keydown', (e) => {
      const a = deps.current(),
        s = a && stateOf(a);
      const t = e.target as HTMLElement | null;
      if (
        e.key !== 'Escape' ||
        e.defaultPrevented ||
        !s ||
        s.screen.kind === 'workbench' ||
        document.querySelector('dialog[open]') ||
        // An open pile, or a key pressed on one, belongs to the pile.
        t?.closest?.('.ws-stack, .aipm-quote-pill') ||
        document.querySelector('.ws-stack:not([data-open="closed"])') ||
        t?.closest('input, textarea, select, [contenteditable="true"]')
      )
        return;
      host.openWorkbench();
    });

  /** The pilot PRD's latest version, once the practice has one. */
  const prdOf = (a: Attempt | null) => (a && stateOf(a)?.progress?.prd) || null;

  return {
    ready,
    prdOf,
    compassProps,
    stackProps,
    screenOf,
    screenName,
    restoreHistory,
    mountMain,
    host,
    missing: () => missing,
  };
}
