/** The sign-off desk (plan §13.4–13.9): the engineer's own screen in a practice.
 *
 * Daniel's ticket on paper, then three steps (reproduce · fix & trial · sign off), one open at a
 * time, done ones folded to a line. Beside them, your Agent: what it can do, what it handed in.
 * Everything comes from the engineer API; nothing here applies a setting to the pilot. The element
 * is kept across the workbench's re-renders, so typing, open rows and the candidate survive;
 * ids on every control let focus come back. */
import { T } from '../../app/i18n';
import type { ConnectionHost } from '../../app/agent-connection';
import { engineerReportView, type EngineerReviewRecord } from '../engineer-report';
import { reviewViewOptions } from '../engineer-report/page';
import { AgentPanel } from './agent-activity/panel';
import { failureText, type EngineerApi } from './api';
import { engineerHatTitle } from './copy';
import { chip, countNode, key, progressMark, setBusy, setCount } from './bits';
import { el, iconNode, workLang } from './dom';
import {
  candidateChanges,
  clock,
  diffShort,
  nextAfterReview,
  reproductionVerdict,
  settingsDiff,
  signState,
  signedDraftStale,
  validateDraft,
  validateImpactNote,
  type Change,
  type EditableField,
  type Experiment,
  type ExperimentSummary,
  type JsonValue,
  type Settings,
  type TicketDetail,
  IMPACT_NOTE_LIMIT,
} from './model';
import { arrive, byKeyboard, light, move, reducedMotion } from './motion';
import { composeForm, draftInput, newDraftForm, type DraftForm } from './steps/compose';
import { fieldRow, markField, releaseFieldIslands } from './steps/fields';
import { Signature, sheetBody } from './steps/sign';
import { failedRow, pendingRow, tapeRow } from './steps/tape';
import { ticketPaper, ticketTask } from './steps/ticket';
import type { StepId } from './stage';
import { setLastTicket } from '../../shell';
import { reviewResult } from './hand-back';
import { attachDesk, deskStage, detachDesk, publishDesk, publishReview, reviewFacts } from './wire';

/** The Agent side of the practice's data host (v4-data-host): grants and the connection card. */
export interface AgentHost extends ConnectionHost {
  snapshot(): {
    session?: { sessionId: string } | null;
    available?: Readonly<Record<string, boolean>>;
    readOnly?: boolean;
  };
  subscribe(listener: () => void): () => void;
  command(
    operation: 'delegations.create',
    input: Record<string, unknown>,
  ): Promise<{ status: string }>;
}

export interface DeskContext {
  readonly doc: Document;
  readonly sessionId: string;
  readonly api: EngineerApi;
  readonly agentHost: AgentHost | null;
  navigate(route: 'engineer' | 'engineer-review' | 'work', id?: string): void;
  notify(text: string): void;
  download(data: unknown, name: string): void;
  /** Remember which ticket a review belongs to (for the report's way back). */
  remember(reviewId: string, ticketId: string): void;
  /** Hand a just-signed review to the report screen so it draws at once. */
  cacheReview(record: EngineerReviewRecord, ticket: TicketDetail): void;
  /** The tab's title: the task's short name. */
  title(short: string): void;
}

const POLL_MS = 4000;
const STEPS: readonly StepId[] = ['reproduce', 'fix', 'signoff'];
// Settings grouped by what they are about; anything new from the server joins the last group.
const GROUPS: readonly { title: () => string; fields: readonly string[] }[] = [
  {
    title: () => T('回答与资料', 'Answers and sources'),
    fields: ['freshness_guard', 'update_strategy', 'fallback'],
  },
  { title: () => T('检索', 'Retrieval'), fields: ['retrieval_limit', 'min_score', 'chunk_size'] },
  {
    title: () => T('知识范围', 'Knowledge scope'),
    fields: ['domains', 'scope_filter', 'manual_domains', 'prohibited_topics'],
  },
  { title: () => T('开发安排', 'Engineering work'), fields: ['work_items'] },
];

/** Redraw a part without losing the person's place: focus and caret come back to the same control. */
function keepingFocus(doc: Document, draw: () => void) {
  const active = doc.activeElement as
    | (HTMLElement & { selectionStart?: number | null; selectionEnd?: number | null })
    | null;
  const id = active?.id ?? '';
  const start = active && 'selectionStart' in active ? active.selectionStart : null;
  const end = active && 'selectionEnd' in active ? active.selectionEnd : null;
  draw();
  if (!id) return;
  const next = doc.getElementById(id) as
    | (HTMLElement & { setSelectionRange?: (a: number, b: number) => void })
    | null;
  if (!next || next === doc.activeElement) return;
  next.focus({ preventScroll: true });
  if (start !== null && start !== undefined && next.setSelectionRange)
    try {
      next.setSelectionRange(start, end ?? start);
    } catch {
      /* not a text field */
    }
}

const storeKey = (sid: string) => `rolecraft.engineer.experiments.${sid}`;
const isAgent = (kind: string | undefined) =>
  kind === 'external_agent' || kind === 'reference_agent';
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface StepParts {
  section: HTMLElement;
  head: HTMLButtonElement;
  body: HTMLElement;
  inner: HTMLElement;
  why: HTMLElement;
}

export class EngineerDesk {
  readonly element: HTMLElement;
  private ticket: TicketDetail | null = null;
  private values: Settings = {};
  private fieldErrors: Record<string, string> = {};
  private readonly experiments = new Map<string, Experiment>();
  private readonly expanded = new Set<string>();
  private readonly drawn = new Set<string>();
  /** Settings the person took from their Agent's draft or trial: field → where it came from. */
  private readonly agentFilled = new Map<string, string>();
  private compose: DraftForm | null = null;
  private busy: '' | 'reproduce' | 'trial' | 'draft' | 'sign' = '';
  private errors = { reproduce: '', trial: '', compose: [] as string[], load: '' };
  private signature = '';
  private open: StepId = 'reproduce';
  private chosen = false;
  private landing = '';
  private hiddenTotal: number | null = null;
  private readonly asked = new Set<string>();
  private impact: HTMLTextAreaElement | null = null;
  private sign: Signature | null = null;
  /** The draft on the sheet when the key went down: only that one is signed. */
  private heldDraft = '';
  /** The draft last drawn on the sheet, and a line at its head once a newer one replaced it. */
  private shownDraft = '';
  private draftNotice = '';
  /** A redraw of the sheet held back while the key is held. */
  private sheetPending = false;
  private panel: AgentPanel | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private observer: IntersectionObserver | null = null;
  private sheetInView = false;
  private readonly steps = {} as Record<StepId, StepParts>;
  private readonly parts: Record<string, HTMLElement> = {};
  private readonly handler = {
    sessionId: '',
    run: (action: string, id?: string) => this.run(action, id),
  };

  constructor(
    private readonly ctx: DeskContext,
    private ticketId: string | null,
    initial: TicketDetail | null = null,
  ) {
    const doc = ctx.doc;
    this.handler.sessionId = ctx.sessionId;
    this.element = el(doc, 'div', { class: 'ed', 'data-engineer-desk-root': true });
    this.restoreExperiments();
    attachDesk(this.handler);
    if (initial && (!ticketId || initial.id === ticketId)) {
      this.ticketId = initial.id;
      this.accept(initial);
      this.build();
    } else {
      this.element.append(
        el(
          doc,
          'p',
          { class: 'ed-loading', role: 'status' },
          T('正在打开委托…', 'Opening the ticket…'),
        ),
      );
      void this.load();
    }
    this.timer = setInterval(() => void this.poll(), POLL_MS);
  }

  /** Back on screen after a redraw or a report: read again (an Agent may have worked), and open
   * the step the route asks for. */
  resume(step?: StepId | null) {
    attachDesk(this.handler);
    this.panel?.attach();
    if (step) this.chosen = true;
    if (this.ticket) {
      this.publish();
      void this.refresh();
      this.ctx.title(engineerHatTitle(this.ticket));
    }
    if (step && this.ticket) this.openStep(step, { scroll: true, focus: true });
    else if (step) this.open = step;
  }

  /** Off screen (another engineer screen took its place): the shell's actions and the Agent's
   * events stop reaching it until `resume`. */
  suspend() {
    detachDesk(this.handler);
    this.panel?.detach();
  }

  destroy() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.observer?.disconnect();
    this.panel?.destroy();
    detachDesk(this.handler);
  }

  /* ---------- data ---------- */

  private accept(ticket: TicketDetail) {
    this.ticket = ticket;
    setLastTicket(this.ctx.sessionId, ticket.id);
    this.values = structuredClone(ticket.baseline_config);
    this.signature = this.signatureOf(ticket);
    for (const r of ticket.reviews) this.ctx.remember(r.review_id, ticket.id);
    for (const t of ticket.trials) this.drawn.add(t.id);
  }

  private async load() {
    try {
      if (!this.ticketId) {
        const list = await this.ctx.api.tickets();
        this.ticketId = list.at(-1)?.id ?? null;
      }
      if (!this.ticketId) {
        this.drawNoTicket();
        return;
      }
      this.accept(await this.ctx.api.ticket(this.ticketId));
      this.build();
    } catch (error) {
      this.errors.load = failureText(error);
      this.drawLoadFailure();
    }
  }

  private signatureOf(t: TicketDetail) {
    return JSON.stringify([
      t.trials,
      t.drafts,
      t.latest_draft,
      t.reviews,
      t.review_budget,
      t.experiment_budget,
    ]);
  }

  private async poll() {
    if (!this.ticket || this.busy || !this.element.isConnected || this.ctx.doc.hidden) return;
    await this.refresh();
  }

  private async refresh() {
    if (!this.ticketId) return;
    try {
      const ticket = await this.ctx.api.ticket(this.ticketId);
      const signature = this.signatureOf(ticket);
      this.ticket = ticket;
      for (const r of ticket.reviews) this.ctx.remember(r.review_id, ticket.id);
      if (signature === this.signature) return;
      this.signature = signature;
      this.drawChanged();
    } catch {
      /* A dropped read changes nothing; the next poll reads again. */
    }
  }

  /** Everything that follows from the ticket's runs, drafts and reviews. */
  private drawChanged() {
    this.drawTicketCount();
    this.drawReproduce();
    this.drawFixState();
    this.drawTape();
    this.drawSign();
    this.panel?.update(this.ticket as TicketDetail);
    this.readOutcomes();
    this.publish();
  }

  private restoreExperiments() {
    try {
      const raw = sessionStorage.getItem(storeKey(this.ctx.sessionId));
      const saved = raw ? (JSON.parse(raw) as Experiment[]) : [];
      for (const e of saved) if (e && typeof e.id === 'string') this.experiments.set(e.id, e);
    } catch {
      /* A convenience only: rows of earlier runs simply stay unavailable. */
    }
  }

  private keepExperiment(experiment: Experiment) {
    this.experiments.set(experiment.id, experiment);
    try {
      const recent = [...this.experiments.values()].slice(-20);
      sessionStorage.setItem(storeKey(this.ctx.sessionId), JSON.stringify(recent));
    } catch {
      /* Storage blocked: the rows stay for this page only. */
    }
  }

  /** How each signed review came out (for the scale, the key and the step summary). */
  private readOutcomes() {
    const t = this.ticket;
    if (!t) return;
    for (const r of t.reviews) {
      if (this.asked.has(r.review_id)) continue;
      this.asked.add(r.review_id);
      void this.ctx.api
        .review(r.review_id)
        .then((record) => {
          this.learnReview(record);
          this.drawStepHeads();
          this.drawSign();
          this.publish();
        })
        .catch(() => this.asked.delete(r.review_id));
    }
  }

  private learnReview(record: EngineerReviewRecord) {
    const language = T('zh', 'en') as 'zh' | 'en';
    const view = engineerReportView(record.report, reviewViewOptions(record, language));
    const hidden = record.report.hidden;
    this.hiddenTotal = hidden.passed + hidden.failed + hidden.errors;
    const result = reviewResult(record, language);
    publishReview(record.review_id, {
      ticketId: record.ticket_id,
      outcome: nextAfterReview(view) === 'board' ? 'clean' : 'regressed',
      newFailures: result.newFailures,
      result,
      source: this.ticket?.id === record.ticket_id ? this.ticket.source : undefined,
    });
  }

  private changes(): Settings {
    return candidateChanges((this.ticket as TicketDetail).baseline_config, this.values);
  }

  private publish() {
    const t = this.ticket;
    if (!t) return;
    publishDesk(this.ctx.sessionId, {
      ticket: t,
      candidate: this.changes(),
      blocked: Object.keys(this.fieldErrors).length
        ? ['先改正标红的设置。', 'Fix the setting marked in red first.']
        : undefined,
      // The sheet's own key takes the ink while it is in view (the top bar's key steps back).
      sheetInView: this.sheetInView && this.open === 'signoff',
    });
    this.drawStepHeads();
  }

  /* ---------- the frame ---------- */

  private drawNoTicket() {
    const doc = this.ctx.doc;
    const open = key(doc, T('开一份委托', 'Open a ticket'), 'primary', { id: 'ed-open-seeded' });
    open.addEventListener('click', async () => {
      setBusy(open, true);
      open.disabled = true;
      try {
        const { ticket } = await this.ctx.api.createTicket({ from: 'seeded' });
        this.ctx.navigate('engineer', ticket.id);
      } catch (error) {
        setBusy(open, false);
        open.disabled = false;
        this.ctx.notify(failureText(error));
      }
    });
    this.element.replaceChildren(
      el(
        doc,
        'div',
        { class: 'ed-empty-state' },
        el(
          doc,
          'h1',
          { class: 'ed-title', id: 'ed-title', tabindex: '-1' },
          T('这个练习还没有工程委托', 'This practice has no engineering ticket yet'),
        ),
        open,
      ),
    );
  }

  private drawLoadFailure() {
    const doc = this.ctx.doc;
    const retry = key(doc, T('重试', 'Try again'), 'ghost', { id: 'ed-retry' }, 'refresh');
    retry.addEventListener('click', () => {
      this.element.replaceChildren(
        el(
          doc,
          'p',
          { class: 'ed-loading', role: 'status' },
          T('正在打开委托…', 'Opening the ticket…'),
        ),
      );
      void this.load();
    });
    this.element.replaceChildren(
      el(
        doc,
        'div',
        { class: 'ed-empty-state' },
        el(doc, 'p', { role: 'alert' }, this.errors.load),
        retry,
      ),
    );
  }

  private build() {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const task = ticketTask(t);
    this.ctx.title(engineerHatTitle(t));
    const { paper, leftNode } = ticketPaper(doc, t);
    this.parts.left = leftNode;
    const head = el(
      doc,
      'header',
      { class: 'ed-head' },
      el(
        doc,
        'p',
        { class: 'ed-eyebrow' },
        T('工程委托 · 知识助手试点', 'Engineering ticket · Knowledge-assistant pilot'),
      ),
      el(doc, 'h1', { class: 'ed-title', id: 'ed-title', tabindex: '-1' }, task.title),
    );
    this.panel = new AgentPanel({
      doc,
      notify: this.ctx.notify,
      compare: () => this.run('engineer.signoff.focus', 'compare'),
      refresh: () => void this.refresh(),
    });
    const list = el(doc, 'div', { class: 'ed-steps' }, ...STEPS.map((id) => this.stepShell(id)));
    this.element.replaceChildren(
      head,
      el(
        doc,
        'div',
        { class: 'ed-layout' },
        el(doc, 'div', { class: 'ed-layout__ticket' }, paper),
        el(doc, 'aside', { class: 'ed-layout__agent' }, this.panel.element),
        el(doc, 'div', { class: 'ed-layout__steps' }, list),
      ),
    );
    this.element.lang = workLang(T('zh', 'en') as 'zh' | 'en');
    this.buildReproduce();
    this.buildFix();
    this.buildSign();
    this.panel.update(t);
    this.publish();
    const first = this.firstOpen();
    this.openStep(first, { animate: false });
    this.readOutcomes();
    this.observeSheet();
  }

  private firstOpen(): StepId {
    if (this.chosen) return this.open;
    publishDesk(this.ctx.sessionId, {
      ticket: this.ticket as TicketDetail,
      candidate: this.changes(),
    });
    const stage = deskStage(this.ctx.sessionId);
    const current = stage.steps.find((s) => s.state === 'current')?.id as StepId | undefined;
    return current ?? 'signoff';
  }

  private drawTicketCount() {
    const t = this.ticket as TicketDetail;
    setCount(this.parts.left, Math.max(0, t.review_budget.limit - t.review_budget.used));
  }

  /** The shell's actions while this desk is on screen. */
  private run(action: string, id?: string): boolean {
    // Kept for a round trip but off the page: let the shell take the person to the desk.
    if (!this.ticket || !this.element.isConnected) return false;
    switch (action) {
      case 'engineer.reproduce':
        this.openStep('reproduce', { scroll: true });
        void this.reproduce();
        return true;
      case 'engineer.trial':
        this.openStep('fix', { scroll: true });
        void this.trial();
        return true;
      case 'engineer.draft.open':
        this.openStep('signoff', { scroll: true });
        if (!this.compose) this.toggleCompose();
        return true;
      case 'engineer.signoff.focus':
        this.openStep('signoff', { scroll: true });
        requestAnimationFrame(() => {
          const target =
            id === 'compare'
              ? this.ctx.doc.getElementById('ed-actual-h')
              : this.ctx.doc.getElementById(this.impact?.value.trim() ? 'ed-sign' : 'ed-impact');
          target?.focus({ preventScroll: false });
        });
        return true;
      case 'engineer.step':
        if (id === 'reproduce' || id === 'fix' || id === 'signoff') {
          this.chosen = true;
          this.openStep(id, { scroll: true, focus: true });
        }
        return true;
      case 'engineer.fix-again':
        this.openStep('fix', { scroll: true });
        requestAnimationFrame(() =>
          (
            this.steps.fix.inner.querySelector(
              'input:checked, input, textarea',
            ) as HTMLElement | null
          )?.focus(),
        );
        return true;
      default:
        return false;
    }
  }

  /* ---------- the three steps ---------- */

  private stepShell(id: StepId): HTMLElement {
    const doc = this.ctx.doc;
    const n = STEPS.indexOf(id) + 1;
    const names: Record<StepId, string> = {
      reproduce: T('复现', 'Reproduce'),
      fix: T('修复与试跑', 'Fix & trial'),
      signoff: T('签字', 'Sign off'),
    };
    const whys: Record<StepId, string> = {
      reproduce: T(
        '先确认问题还在，不然你修的可能是别的问题。',
        'First make sure the problem is still there, or you may fix something else.',
      ),
      fix: T(
        '只改你认为是根因的地方。试跑只看得到公开的 4 条。',
        'Change only what you think is the root cause. A trial sees only the 4 public checks.',
      ),
      signoff: T(
        '签字表示你看过实际改动，想过它还会影响什么，并为它负责。',
        'Signing means you’ve seen what actually changed, thought about what else it touches, and you vouch for it.',
      ),
    };
    const head = el(
      doc,
      'button',
      {
        type: 'button',
        class: 'ed-step__head',
        id: `ed-step-${id}`,
        'aria-expanded': 'false',
        'aria-controls': `ed-step-${id}-body`,
      },
      el(doc, 'span', { class: 'ed-step__mark' }),
      el(doc, 'span', { class: 'ed-step__n', 'aria-hidden': 'true' }, `0${n}`),
      el(doc, 'span', { class: 'ed-step__name' }, names[id]),
      el(doc, 'span', { class: 'ed-step__sum' }),
      el(doc, 'span', { class: 'ed-step__chev' }, iconNode(doc, 'down', 'i-xs')),
    );
    head.addEventListener('click', () => {
      this.chosen = true;
      if (this.open === id) return;
      this.openStep(id, { animate: !byKeyboard() });
    });
    head.addEventListener('keydown', (e) => {
      const i = STEPS.indexOf(id);
      const to =
        e.key === 'ArrowDown'
          ? STEPS[(i + 1) % 3]
          : e.key === 'ArrowUp'
            ? STEPS[(i + 2) % 3]
            : e.key === 'Home'
              ? STEPS[0]
              : e.key === 'End'
                ? STEPS[2]
                : null;
      if (!to) return;
      e.preventDefault();
      this.steps[to].head.focus();
    });
    const why = el(doc, 'p', { class: 'ed-step__why', tabindex: '-1' }, whys[id]);
    const inner = el(doc, 'div', { class: 'ed-step__inner' }, why);
    const body = el(
      doc,
      'div',
      {
        class: 'ed-step__body',
        id: `ed-step-${id}-body`,
        role: 'region',
        'aria-labelledby': `ed-step-${id}`,
      },
      el(doc, 'div', { class: 'ed-step__clip' }, inner),
    );
    const section = el(
      doc,
      'section',
      { class: 'ed-step', 'data-step': id },
      el(doc, 'h2', { class: 'ed-step__h' }, head),
      body,
    );
    this.steps[id] = { section, head, body, inner, why };
    return section;
  }

  /** One step open at a time (accordion). Mouse opens animate; keys switch at once. */
  private openStep(
    id: StepId,
    opts: { animate?: boolean; scroll?: boolean; focus?: boolean } = {},
  ) {
    const changed = this.open !== id;
    this.open = id;
    const animate = opts.animate !== false && !byKeyboard() && !reducedMotion();
    for (const s of STEPS) {
      const p = this.steps[s];
      if (!p) continue;
      const on = s === id;
      p.section.classList.toggle('no-anim', !animate);
      p.section.classList.toggle('is-open', on);
      p.head.setAttribute('aria-expanded', String(on));
      p.body.toggleAttribute('inert', !on);
    }
    this.drawStepHeads();
    this.publish();
    if (opts.scroll)
      requestAnimationFrame(() =>
        this.steps[id]?.section.scrollIntoView({
          block: 'start',
          behavior: animate ? 'smooth' : 'auto',
        }),
      );
    if (opts.focus) this.steps[id]?.why.focus({ preventScroll: true });
    void changed;
  }

  private drawStepHeads() {
    const t = this.ticket;
    if (!t || !this.steps.reproduce) return;
    const stage = deskStage(this.ctx.sessionId);
    for (const step of stage.steps) {
      const id = step.id as StepId;
      const p = this.steps[id];
      const mark = p.head.querySelector('.ed-step__mark') as HTMLElement;
      const previous = p.section.dataset.state;
      if (previous !== step.state) {
        mark.replaceChildren(progressMark(this.ctx.doc, step.state));
        p.section.dataset.state = step.state;
        // The tick draws itself the first time a step is done (a few times a practice).
        if (previous && step.state === 'done' && !reducedMotion()) mark.classList.add('is-ticking');
        else mark.classList.remove('is-ticking');
      }
      const sum = p.head.querySelector('.ed-step__sum') as HTMLElement;
      const text = this.summary(id);
      if (sum.textContent !== text) sum.textContent = text;
    }
  }

  private summary(id: StepId): string {
    const t = this.ticket as TicketDetail;
    if (id === 'reproduce') {
      const run = [...t.trials].reverse().find((r) => r.kind === 'reproduce');
      if (!run) return T('还没复现', 'Not reproduced yet');
      return `${reproductionVerdict(run, t).label} · ${clock(run.created_at)}`;
    }
    if (id === 'fix') {
      const run = [...t.trials].reverse().find((r) => r.kind === 'trial');
      const edits = Object.keys(this.changes()).length;
      if (!run)
        return edits
          ? T(`改了 ${edits} 处，还没试跑`, `${edits} changed, not tried yet`)
          : T('还没试跑', 'No trial yet');
      const n = (run.changes ? Object.keys(run.changes) : (run.changed_fields ?? [])).length;
      return T(
        `改 ${n} 处 · 公开 ${run.counts.passed ?? 0}/${t.public_probes.length} 通过`,
        `${n} changed · public ${run.counts.passed ?? 0}/${t.public_probes.length} passed`,
      );
    }
    const draft = t.latest_draft;
    if (!draft) return T('还没有草稿', 'No draft yet');
    const index = t.reviews.findIndex((r) => r.draft_id === draft.id);
    if (index < 0)
      return isAgent(draft.executor.kind)
        ? T('你的 Agent 交来一份草稿', 'A draft from your agent')
        : T('有草稿待签', 'A draft to sign');
    const facts = reviewFacts(t.reviews[index].review_id);
    if (!facts) return T(`已签 · 第 ${index + 1} 次复核`, `Signed · review ${index + 1}`);
    return facts.outcome === 'clean'
      ? T(`已签 · 第 ${index + 1} 次复核全过`, `Signed · review ${index + 1} all clear`)
      : T(`已签 · 第 ${index + 1} 次复核没全过`, `Signed · review ${index + 1} not clear`);
  }

  /* ---------- ① reproduce ---------- */

  private buildReproduce() {
    const doc = this.ctx.doc;
    const run = key(
      doc,
      T('复现问题', 'Reproduce the problem'),
      'secondary',
      { id: 'ed-reproduce' },
      'refresh',
    );
    run.addEventListener('click', () => void this.reproduce());
    this.parts.reproduce = run;
    // The result is announced once, through the page's announcer (not as a live region too).
    this.parts.reproduceResult = el(doc, 'div', { class: 'ed-result' });
    this.steps.reproduce.inner.append(
      el(
        doc,
        'div',
        { class: 'ed-step__do' },
        run,
        el(
          doc,
          'span',
          { class: 'ed-meta' },
          T('用委托打包时的快照重跑一次', 'Reruns it on the ticket’s snapshot'),
        ),
      ),
      this.parts.reproduceResult,
    );
    this.drawReproduce();
  }

  private drawReproduce(fresh = false) {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const box = this.parts.reproduceResult;
    if (!box) return;
    const button = this.parts.reproduce as HTMLButtonElement;
    // While its own run is out the key stays focusable (busy, not disabled): focus stays in ①.
    button.disabled = !!this.busy && this.busy !== 'reproduce';
    setBusy(button, this.busy === 'reproduce');
    if (this.busy === 'reproduce') {
      const target = t.target_tests[0];
      box.replaceChildren(
        el(
          doc,
          'div',
          { class: 'ed-result__row is-pending' },
          el(doc, 'span', { class: 'ed-square', 'data-mark': 'unknown' }),
          el(
            doc,
            'p',
            { class: 'ed-result__q', lang: workLang(t.work_language) },
            target?.query ?? '',
          ),
          el(doc, 'span', { class: 'ed-meta' }, T('复现中…', 'Reproducing…')),
        ),
      );
      return;
    }
    if (this.errors.reproduce) {
      const retry = key(doc, T('重试', 'Try again'), 'ghost', {}, 'refresh');
      retry.addEventListener('click', () => void this.reproduce());
      box.replaceChildren(
        el(
          doc,
          'div',
          { class: 'ed-result__row is-error' },
          el(doc, 'span', { class: 'ed-square', 'data-mark': 'unknown' }),
          el(doc, 'p', { role: 'alert' }, this.errors.reproduce),
          retry,
        ),
      );
      return;
    }
    const run = [...t.trials].reverse().find((r) => r.kind === 'reproduce');
    if (!run) {
      box.replaceChildren();
      return;
    }
    const verdict = reproductionVerdict(run, t);
    const agent = isAgent(run.executor.kind);
    const full = this.experiments.get(run.id);
    const answer =
      (full?.rows?.[0] && 'reproduced' in full.rows[0]
        ? full.rows[0].reproduced.answer_summary
        : '') || (verdict.kind === 'still' ? (t.target_tests[0]?.answer_summary ?? '') : '');
    const quote = el(
      doc,
      'blockquote',
      { class: 'ed-result__quote is-clamped', lang: workLang(t.work_language) },
      answer,
    );
    const more = key(doc, T('展开', 'Show all'), 'ghost', { class: 'ed-result__more' });
    more.addEventListener('click', () => {
      const clamped = quote.classList.toggle('is-clamped');
      (more.querySelector('.ed-k__label') as HTMLElement).textContent = clamped
        ? T('展开', 'Show all')
        : T('收起', 'Show less');
    });
    const row = el(
      doc,
      'div',
      { class: 'ed-result__row', 'data-tone': verdict.tone },
      el(
        doc,
        'p',
        { class: 'ed-result__head' },
        chip(doc, verdict.label, verdict.tone),
        agent
          ? el(
              doc,
              'span',
              { class: 'ed-result__by' },
              T('你的 Agent 复现了：', 'Your agent reproduced it:'),
            )
          : null,
        el(doc, 'span', { class: 'ed-result__time' }, clock(run.created_at)),
      ),
      el(doc, 'p', { class: 'ed-result__line' }, verdict.sentence),
      answer ? quote : null,
      answer && answer.length > 60 ? more : null,
    );
    box.replaceChildren(row);
    if (fresh && !byKeyboard()) arrive(row, 4);
  }

  private announce(text: string) {
    const region = this.ctx.doc.getElementById('announcer');
    if (!region) return;
    region.textContent = '';
    setTimeout(() => {
      region.textContent = text;
    }, 30);
  }

  private async reproduce() {
    if (!this.ticket || this.busy) return;
    this.busy = 'reproduce';
    this.errors.reproduce = '';
    this.drawReproduce();
    this.drawFixState();
    this.publish();
    this.drawSign();
    try {
      const record = await this.ctx.api.reproduce(this.ticket.id);
      this.keepExperiment(record);
      this.busy = '';
      await this.refresh();
      this.drawReproduce(true);
      const verdict = reproductionVerdict(record, this.ticket as TicketDetail);
      this.announce(
        T(
          `复现完成：${verdict.label}，${verdict.sentence}`,
          `Reproduced: ${verdict.label}. ${verdict.sentence}`,
        ),
      );
      // Step ② opens on its own after a beat, unless the person is reading ①'s result.
      const step = this.steps.reproduce.section;
      setTimeout(() => {
        if (
          this.open !== 'reproduce' ||
          step.matches(':hover') ||
          step.contains(this.ctx.doc.activeElement)
        )
          return;
        this.openStep('fix');
      }, 280);
    } catch (error) {
      this.busy = '';
      this.errors.reproduce = failureText(error);
    } finally {
      this.busy = '';
      this.drawReproduce();
      this.drawFixState();
      this.drawTape();
      this.drawSign();
      this.publish();
    }
  }

  /* ---------- ② fix & trial ---------- */

  private buildFix() {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    // b. the changes bar
    const count = countNode(doc, 0);
    this.parts.changeCount = count;
    const useAgent = key(doc, '', 'secondary', { id: 'ed-use-agent', hidden: true }, 'spark');
    useAgent.addEventListener('click', () => this.useAgentSettings());
    const reset = key(
      doc,
      T('恢复基线', 'Back to baseline'),
      'ghost',
      { id: 'ed-reset' },
      'refresh',
    );
    reset.addEventListener('click', () => this.resetCandidate());
    this.parts.useAgent = useAgent;
    this.parts.reset = reset;
    const bar = el(
      doc,
      'div',
      { class: 'ed-bar' },
      el(
        doc,
        'p',
        { class: 'ed-bar__count' },
        T('本次改动 · ', 'Changes · '),
        count,
        el(doc, 'span', { class: 'ed-bar__unit' }, T(' 处', '')),
      ),
      el(doc, 'div', { class: 'ed-bar__keys' }, useAgent, reset),
    );
    // c. the instrument
    this.parts.form = el(doc, 'form', { class: 'ed-form', id: 'ed-form', novalidate: true });
    this.parts.form.addEventListener('submit', (e) => {
      e.preventDefault();
      void this.trial();
    });
    // d. the public checks (moved here from the side)
    const targets = new Set(t.target_tests.map((x) => x.query));
    const lang = workLang(t.work_language);
    this.parts.hiddenNote = el(doc, 'p', { class: 'ed-meta' });
    const checks = el(
      doc,
      'section',
      { class: 'ed-checks', 'aria-labelledby': 'ed-checks-h' },
      el(
        doc,
        'h3',
        { class: 'ed-label', id: 'ed-checks-h' },
        T(
          `试跑会检查这 ${t.public_probes.length} 个问题`,
          `A trial checks these ${t.public_probes.length} questions`,
        ),
      ),
      el(
        doc,
        'ol',
        { class: 'ed-checks__list' },
        ...t.public_probes.map((p) =>
          el(
            doc,
            'li',
            {},
            el(doc, 'code', { class: 'ed-key', lang: 'en' }, p.id),
            el(doc, 'span', { class: 'ed-checks__q', lang }, p.query),
            targets.has(p.query)
              ? chip(doc, T('要修的', 'To fix'), 'outline')
              : chip(doc, T('不能变坏', 'Must not break'), 'plain'),
          ),
        ),
      ),
      this.parts.hiddenNote,
    );
    // e. run it
    const trial = key(doc, T('试跑', 'Run a trial'), 'secondary', { id: 'ed-trial' }, 'play');
    trial.addEventListener('click', () => void this.trial());
    this.parts.trial = trial;
    this.parts.budgetCount = countNode(doc, t.experiment_budget.used);
    this.parts.budget = el(
      doc,
      'span',
      { class: 'ed-meta' },
      T('已试 ', ''),
      this.parts.budgetCount,
      `/${t.experiment_budget.limit}`,
      T(' 次', ' runs used'),
    );
    this.parts.trialNote = el(doc, 'p', { class: 'ed-meta ed-trial__note', hidden: true });
    // f. the tape
    this.parts.tape = el(doc, 'div', { class: 'ed-log' });
    this.steps.fix.inner.append(
      bar,
      this.parts.form,
      checks,
      el(doc, 'div', { class: 'ed-step__do' }, trial, this.parts.budget),
      this.parts.trialNote,
      this.parts.tape,
    );
    this.drawFields();
    this.drawTape();
  }

  private moreOpen = false;
  /** The settings of a trial that did not go through (its row stays in the log). */
  private failedTrial = '';
  private drawFields() {
    const doc = this.ctx.doc;
    // The rows are drawn anew: release the islands of the old ones first.
    releaseFieldIslands(this.parts.form);
    const t = this.ticket as TicketDetail;
    const fields = new Map(t.editable_fields.map((f) => [f.field, f]));
    const placed = new Set<string>();
    const groups = GROUPS.map((g, i) => {
      const own = g.fields.filter((f) => fields.has(f));
      for (const f of own) placed.add(f);
      const extra =
        i === GROUPS.length - 1
          ? t.editable_fields
              .map((f) => f.field)
              .filter((f) => !placed.has(f) && !g.fields.includes(f))
          : [];
      const all = [...own, ...extra];
      return all.length
        ? el(
            doc,
            'fieldset',
            { class: 'ed-group' },
            el(doc, 'legend', { class: 'ed-group__title' }, g.title()),
            ...all.map((name) => this.field(fields.get(name) as EditableField)),
          )
        : null;
    });
    const count = el(doc, 'span', { class: 'ed-more__count' });
    this.parts.moreCount = count;
    const more = el(
      doc,
      'details',
      { class: 'ed-more', open: this.moreOpen },
      el(
        doc,
        'summary',
        { id: 'ed-more' },
        el(doc, 'span', {}, T('知识范围与开发安排', 'Knowledge scope and engineering work')),
        count,
      ),
      el(doc, 'div', { class: 'ed-form__groups' }, ...groups.slice(2)),
    );
    more.addEventListener('toggle', () => {
      this.moreOpen = more.open;
    });
    this.parts.more = more;
    keepingFocus(doc, () =>
      this.parts.form.replaceChildren(
        el(
          doc,
          'div',
          { class: 'ed-instrument' },
          el(doc, 'div', { class: 'ed-form__groups' }, ...groups.slice(0, 2)),
          more,
        ),
      ),
    );
    this.drawFixState();
  }

  private field(field: EditableField): HTMLElement {
    const name = field.field;
    return fieldRow(this.ctx.doc, field, this.values[name], {
      change: (next: JsonValue) => {
        this.values[name] = next;
        delete this.fieldErrors[name];
        this.agentFilled.delete(name);
        this.drawFixState();
        this.publish();
      },
      invalid: (message) => {
        this.fieldErrors[name] = message;
        this.drawFixState();
        this.publish();
      },
      restore: () => {
        const t = this.ticket as TicketDetail;
        this.values[name] = structuredClone(t.baseline_config[name]);
        delete this.fieldErrors[name];
        this.agentFilled.delete(name);
        this.drawFields();
        this.publish();
        this.ctx.doc.getElementById(`ed-f-${name}`)?.focus?.();
        (
          this.ctx.doc.querySelector(`[data-field="${name}"] input:checked`) as HTMLElement | null
        )?.focus();
      },
    });
  }

  /** The Agent's latest settings (its newest draft, else its newest trial with values). */
  private agentSettings(): {
    changes: Readonly<Record<string, Change>>;
    title: (f: string) => string;
    draft: boolean;
  } | null {
    const t = this.ticket as TicketDetail;
    const draft = t.latest_draft;
    const trial = [...t.trials]
      .reverse()
      .find((r) => r.kind === 'trial' && isAgent(r.executor.kind) && r.changes);
    // Only what is still news: a draft not yet signed, or a trial after the last signature.
    const lastSigned = t.reviews.at(-1)?.signed_at ?? '';
    const draftOpen = !!draft && !t.reviews.some((r) => r.draft_id === draft.id);
    const trialNew = !!trial && trial.created_at > lastSigned;
    const useDraft =
      draft &&
      draftOpen &&
      isAgent(draft.executor.kind) &&
      (!trialNew || draft.created_at >= (trial?.created_at ?? ''));
    if (useDraft)
      return {
        changes: draft.changes,
        draft: true,
        title: () =>
          T(
            `你的 Agent 在 ${clock(draft.created_at)} 的草稿里改的`,
            `Your agent changed this in its ${clock(draft.created_at)} draft`,
          ),
      };
    if (trialNew && trial?.changes)
      return {
        changes: trial.changes,
        draft: false,
        title: () =>
          T(
            `你的 Agent 在 ${clock(trial.created_at)} 的试跑里改的`,
            `Your agent changed this in its ${clock(trial.created_at)} trial`,
          ),
      };
    return null;
  }

  private useAgentSettings() {
    const source = this.agentSettings();
    const t = this.ticket as TicketDetail;
    if (!source) return;
    this.values = structuredClone(t.baseline_config);
    this.fieldErrors = {};
    this.agentFilled.clear();
    for (const [field, change] of Object.entries(source.changes)) {
      this.values[field] = structuredClone(change.after);
      this.agentFilled.set(field, source.title(field));
    }
    this.drawFields();
    this.publish();
    this.ctx.notify(
      source.draft
        ? T(
            '你的 Agent 草稿里的设置已经填进来了。试跑之前什么都不会运行。',
            'Your agent’s draft settings are now in the form. Nothing runs until you run a trial.',
          )
        : T(
            '你的 Agent 试跑的设置已经填进来了。试跑之前什么都不会运行。',
            'Your agent’s trial settings are now in the form. Nothing runs until you run a trial.',
          ),
    );
  }

  private drawFixState() {
    const t = this.ticket;
    if (!t || !this.parts.form) return;
    const changes = this.changes();
    for (const row of this.parts.form.querySelectorAll<HTMLElement>('.ed-field')) {
      const name = row.dataset.field as string;
      markField(
        row,
        name in changes ? { before: t.baseline_config[name], after: changes[name] } : null,
        name in changes ? (this.agentFilled.get(name) ?? null) : null,
        this.fieldErrors[name] ?? '',
      );
    }
    const n = Object.keys(changes).length;
    setCount(this.parts.changeCount, n);
    this.parts.reset.hidden = !n && !Object.keys(this.fieldErrors).length;
    const folded = [...(this.parts.more?.querySelectorAll<HTMLElement>('.ed-field') ?? [])].filter(
      (row) => (row.dataset.field as string) in changes,
    ).length;
    if (this.parts.moreCount)
      this.parts.moreCount.textContent = folded ? T(`改了 ${folded} 项`, `${folded} changed`) : '';
    // "Use your agent's settings" when its latest differs from the candidate.
    const agent = this.agentSettings();
    const differs =
      !!agent &&
      JSON.stringify(
        Object.entries(agent.changes)
          .map(([f, c]) => [f, c.after])
          .sort(),
      ) !== JSON.stringify(Object.entries(changes).sort());
    const useAgent = this.parts.useAgent as HTMLButtonElement;
    useAgent.hidden = !differs;
    if (agent)
      (useAgent.querySelector('.ed-k__label') as HTMLElement).textContent = agent.draft
        ? T('用 Agent 草稿的设置', 'Use your agent’s draft settings')
        : T('用 Agent 试跑的设置', 'Use your agent’s trial settings');
    // The run key and its budget.
    const blocked = Object.keys(this.fieldErrors).length > 0;
    const full = t.experiment_budget.used >= t.experiment_budget.limit;
    const trial = this.parts.trial as HTMLButtonElement;
    trial.disabled = (!!this.busy && this.busy !== 'trial') || blocked || full;
    setBusy(trial, this.busy === 'trial');
    this.parts.form.toggleAttribute('aria-busy', this.busy === 'trial');
    this.parts.form.classList.toggle('is-sent', this.busy === 'trial');
    setCount(this.parts.budgetCount, t.experiment_budget.used);
    const note = this.parts.trialNote;
    note.hidden = !(blocked || full);
    note.textContent = full
      ? T(
          `这份委托已经试满 ${t.experiment_budget.limit} 次。可以直接起草签字。`,
          `This ticket has used all ${t.experiment_budget.limit} runs. You can draft a sign-off now.`,
        )
      : blocked
        ? T('先改正标红的设置，才能试跑。', 'Fix the setting marked in red before a trial.')
        : '';
    this.parts.hiddenNote.textContent =
      this.hiddenTotal === null
        ? T(
            '复核还会跑一组隐藏检查，只给计数。',
            'The review also runs hidden checks and gives only their counts.',
          )
        : T(
            `复核还会跑 ${this.hiddenTotal} 条隐藏检查，只给计数。`,
            `The review also runs ${this.hiddenTotal} hidden checks and gives only their counts.`,
          );
  }

  private resetCandidate() {
    const t = this.ticket as TicketDetail;
    this.values = structuredClone(t.baseline_config);
    this.fieldErrors = {};
    this.agentFilled.clear();
    this.drawFields();
    this.publish();
    this.ctx.doc.getElementById('ed-trial')?.focus();
    this.ctx.notify(T('候选已恢复为基线。', 'The candidate is back to the baseline.'));
  }

  private async trial() {
    if (!this.ticket || this.busy || Object.keys(this.fieldErrors).length) return;
    const t = this.ticket;
    if (t.experiment_budget.used >= t.experiment_budget.limit) return;
    const changes = this.changes();
    this.busy = 'trial';
    this.errors.trial = '';
    this.failedTrial = '';
    this.parts.tape.querySelector('.ed-line.is-failed')?.remove();
    this.drawFixState();
    this.publish();
    this.drawSign();
    // The run drops into the tape at once, its squares grey and dashed until it answers.
    const short =
      diffShort(settingsDiff(t.baseline_config, changes, t.editable_fields)) ||
      T('基线设置', 'Baseline settings');
    const pending = pendingRow(this.ctx.doc, t, short, 'trial');
    this.tapeList()?.prepend(pending);
    this.parts.tape.querySelector('.ed-log__empty')?.remove();
    if (!byKeyboard())
      move(
        pending,
        { opacity: [0, 1], transform: ['translateY(-8px)', 'translateY(0)'] },
        { ease: undefined },
      );
    try {
      const record = await this.ctx.api.trial(t.id, changes);
      this.keepExperiment(record);
      this.expanded.clear();
      this.expanded.add(record.id);
      this.landing = record.id;
      this.busy = '';
      await this.refresh();
      const passed = record.counts.passed ?? 0;
      this.announce(
        T(
          `试跑完成：公开 ${t.public_probes.length} 条通过 ${passed} 条。`,
          `Trial done: ${passed} of ${t.public_probes.length} public checks passed.`,
        ),
      );
    } catch (error) {
      // The row stays where it dropped, squares still grey and dashed, with "try again".
      this.errors.trial = failureText(error);
      this.failedTrial = short;
    } finally {
      this.busy = '';
      this.drawFixState();
      this.drawTape();
      this.drawSign();
      this.publish();
    }
  }

  private tapeList(): HTMLElement | null {
    return this.parts.tape?.querySelector('.ed-tape') ?? null;
  }

  private drawTape() {
    const doc = this.ctx.doc;
    const t = this.ticket;
    const node = this.parts.tape;
    if (!t || !node) return;
    if (this.busy === 'trial') return; // the pending row stays until the run answers
    const lines = [...t.trials].reverse();
    const tape = el(doc, 'ol', { class: 'ed-tape' });
    if (this.failedTrial) {
      const retry = key(doc, T('重试', 'Try again'), 'ghost', { id: 'ed-trial-retry' }, 'refresh');
      retry.addEventListener('click', () => void this.trial());
      tape.append(failedRow(doc, t, this.failedTrial, this.errors.trial, retry));
    }
    for (const summary of lines) tape.append(this.tapeLine(summary));
    const reproduced = t.trials.some((r) => r.kind === 'reproduce');
    keepingFocus(doc, () =>
      node.replaceChildren(
        el(
          doc,
          'h3',
          { class: 'ed-label' },
          T('试验记录', 'Trial log'),
          el(
            doc,
            'span',
            { class: 'ed-meta' },
            T(' · 你和你的 Agent 的每一次', ' · every run by you and your agent'),
          ),
        ),
        lines.length || this.failedTrial
          ? tape
          : el(
              doc,
              'p',
              { class: 'ed-tape ed-log__empty' },
              reproduced
                ? T(
                    '还没有试跑。改好设置后点试跑。',
                    'No trial yet. Change a setting, then run a trial.',
                  )
                : T('还没有试验。先复现一次。', 'Nothing run yet. Reproduce it first.'),
            ),
      ),
    );
    // A run that just answered: its squares light one by one, its tally rolls from zero.
    const landing = this.landing;
    this.landing = '';
    for (const summary of lines) {
      const row = tape.querySelector<HTMLElement>(`[data-id="${CSS.escape(summary.id)}"]`);
      if (!row) continue;
      if (summary.id === landing && !reducedMotion()) {
        row.querySelectorAll('.ed-line__head .ed-square').forEach((sq, i) => {
          light(sq, i * 0.04);
        });
        const count = row.querySelector('.ed-line__tally number-flow');
        if (count) {
          const target = summary.counts.passed ?? 0;
          setCount(count, 0);
          requestAnimationFrame(() => setCount(count, target));
        }
      } else if (!this.drawn.has(summary.id) && !byKeyboard()) arrive(row, -8, { ease: undefined });
      this.drawn.add(summary.id);
    }
  }

  private tapeLine(summary: ExperimentSummary): HTMLElement {
    return tapeRow(
      this.ctx.doc,
      this.ticket as TicketDetail,
      summary,
      this.experiments.get(summary.id),
      this.expanded.has(summary.id),
      () => {
        if (this.expanded.has(summary.id)) this.expanded.delete(summary.id);
        else this.expanded.add(summary.id);
        this.drawTape();
      },
    );
  }

  /* ---------- ③ sign off ---------- */

  private buildSign() {
    const doc = this.ctx.doc;
    this.impact = el(doc, 'textarea', {
      class: 'ed-input ed-impact__field',
      id: 'ed-impact',
      rows: 3,
      maxlength: IMPACT_NOTE_LIMIT,
      'aria-describedby': 'ed-impact-count',
      required: true,
    });
    this.parts.impactCount = countNode(doc, 0);
    this.parts.impactError = el(doc, 'p', {
      class: 'ed-error',
      id: 'ed-impact-error',
      role: 'alert',
      hidden: true,
    });
    this.impact.addEventListener('input', () => {
      const area = this.impact as HTMLTextAreaElement;
      // Grows with its text; at least three lines.
      area.style.height = 'auto';
      area.style.height = `${Math.max(area.scrollHeight, 0)}px`;
      setCount(this.parts.impactCount, [...area.value.trim()].length);
      if (area.value.trim()) this.parts.impactError.hidden = true;
    });
    this.sign = new Signature(doc, {
      precheck: () => {
        const problem = validateImpactNote(this.impact?.value ?? '');
        this.parts.impactError.hidden = !problem;
        this.parts.impactError.textContent = problem;
        if (problem) this.impact?.focus();
        else this.heldDraft = this.ticket?.latest_draft?.id ?? '';
        return problem;
      },
      sign: () => void this.signNow(),
      openReview: (id) => this.ctx.navigate('engineer-review', id),
      released: () => {
        if (this.sheetPending) this.drawSign();
      },
    });
    this.parts.sheet = el(doc, 'div', { class: 'ed-signoff' });
    this.steps.signoff.inner.append(this.parts.sheet);
    this.drawSign();
  }

  private drawSign() {
    const doc = this.ctx.doc;
    const t = this.ticket;
    const node = this.parts.sheet;
    if (!t || !node || !this.sign) return;
    if (this.busy === 'sign') return; // the sheet stays as signed while the review runs
    // Held (or the 400ms of a key press): the sheet the person is signing stays as it is.
    if (this.sign.holding()) {
      this.sheetPending = true;
      return;
    }
    this.sheetPending = false;
    const latest = t.latest_draft;
    const state = signState(t);
    const signedReview = latest ? t.reviews.find((r) => r.draft_id === latest.id) : undefined;
    // A newer draft came in while the sheet was out: say so at its head (until it is signed).
    if (latest && this.shownDraft && latest.id !== this.shownDraft && !signedReview)
      this.draftNotice = T(
        `草稿刚换成 ${clock(latest.created_at)} 那一份。签字前先看一眼。`,
        `The draft just changed to the ${clock(latest.created_at)} one. Look it over before you sign.`,
      );
    if (signedReview) this.draftNotice = '';
    this.shownDraft = latest?.id ?? '';
    // While another run is out, signing waits for it (and says why).
    const waiting =
      this.busy === 'reproduce'
        ? T('复现跑完再签。', 'Wait for the reproduction to finish.')
        : this.busy === 'trial'
          ? T('试跑跑完再签。', 'Wait for the trial to finish.')
          : this.busy === 'draft'
            ? T('草稿保存好再签。', 'Wait for the draft to save.')
            : '';
    keepingFocus(doc, () => {
      const children: (Node | null)[] = [];
      const redo = key(
        doc,
        this.compose
          ? T('收起草稿', 'Close the draft')
          : latest
            ? T('自己重新起草', 'Write your own draft')
            : T('自己起草', 'Write a draft'),
        latest || this.compose ? 'ghost' : 'secondary',
        { id: 'ed-compose', 'aria-expanded': String(!!this.compose) },
        'edit',
      );
      redo.addEventListener('click', () => this.toggleCompose());
      if (this.compose) {
        children.push(
          el(
            doc,
            'div',
            { class: 'ed-sheet is-compose' },
            el(
              doc,
              'header',
              { class: 'ed-sheet__top' },
              el(doc, 'h3', { class: 'ed-label' }, T('自己起草', 'Your own draft')),
              redo,
            ),
            composeForm({
              doc,
              ticket: t,
              form: this.compose,
              changes: this.changes(),
              latestTrial: [...t.trials]
                .reverse()
                .map((s) => this.experiments.get(s.id))
                .find((e) => e?.kind === 'trial' && e.rows),
              busy: this.busy === 'draft',
              errors: this.errors.compose,
              redraw: (focusId) => {
                this.drawSign();
                if (focusId) this.ctx.doc.getElementById(focusId)?.focus();
              },
              cancel: () => this.toggleCompose(),
              save: () => void this.saveDraft(),
            }),
          ),
        );
      } else if (!latest) {
        children.push(
          el(
            doc,
            'div',
            { class: 'ed-empty' },
            el(
              doc,
              'p',
              {},
              T(
                '还没有草稿：等你的 Agent 交来，或者自己起草。',
                'No draft yet: wait for your agent’s, or write one yourself.',
              ),
            ),
            redo,
          ),
        );
      } else {
        const sign = this.sign as Signature;
        sign.update({
          left: state.left,
          can: state.can && !waiting,
          reason: signedReview ? '' : waiting || state.reason,
          signedAt: signedReview?.signed_at,
          signedReview: signedReview?.review_id,
          exhausted: state.left <= 0 && !signedReview,
        });
        const exhausted =
          state.left <= 0 && !signedReview
            ? el(
                doc,
                'div',
                { class: 'ed-sheet__spent' },
                ...t.reviews.map((r, i) => {
                  const k = key(
                    doc,
                    T(`第 ${i + 1} 次复核`, `Review ${i + 1}`),
                    'ghost',
                    {},
                    'chev',
                  );
                  k.addEventListener('click', () =>
                    this.ctx.navigate('engineer-review', r.review_id),
                  );
                  return k;
                }),
              )
            : null;
        (this.impact as HTMLTextAreaElement).readOnly = !!signedReview;
        children.push(
          el(
            doc,
            'article',
            { class: 'ed-sheet', 'aria-labelledby': 'ed-sheet-h' },
            el(
              doc,
              'header',
              { class: 'ed-sheet__top' },
              el(
                doc,
                'h3',
                { class: 'ed-sheet__title', id: 'ed-sheet-h' },
                T('签字单', 'Sign-off sheet'),
              ),
              redo,
            ),
            this.draftNotice
              ? el(doc, 'p', { class: 'ed-sheet__notice', role: 'status' }, this.draftNotice)
              : null,
            sheetBody(doc, t),
            signedReview
              ? null
              : el(
                  doc,
                  'div',
                  { class: 'ed-impact' },
                  el(
                    doc,
                    'label',
                    { class: 'ed-label', for: 'ed-impact' },
                    T(
                      '这个改动还可能影响哪些问题？',
                      'Which other questions might this change affect?',
                    ),
                    el(doc, 'span', { class: 'ed-required' }, T('（必填）', ' (required)')),
                  ),
                  this.impact,
                  el(
                    doc,
                    'p',
                    { class: 'ed-impact__meta', id: 'ed-impact-count' },
                    this.parts.impactCount,
                    `/${IMPACT_NOTE_LIMIT}`,
                  ),
                  this.parts.impactError,
                ),
            sign.element,
            exhausted,
          ),
        );
      }
      node.replaceChildren(...children.filter((c): c is Node => !!c));
    });
  }

  private observeSheet() {
    if (typeof IntersectionObserver === 'undefined') return;
    this.observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) this.sheetInView = e.intersectionRatio >= 0.4;
        this.publish();
      },
      { threshold: [0, 0.4, 1] },
    );
    this.observer.observe(this.parts.sheet);
  }

  private async signNow() {
    const t = this.ticket;
    const sign = this.sign;
    if (!t?.latest_draft || !sign || this.busy) {
      sign?.failed('');
      return;
    }
    // The draft changed under the held key (a poll read a newer one): don't sign what wasn't seen.
    if (signedDraftStale(this.heldDraft, t)) {
      sign.failed('');
      this.drawSign();
      this.ctx.doc.querySelector<HTMLElement>('.ed-sheet__notice')?.focus?.();
      return;
    }
    const draftId = this.heldDraft;
    const note = (this.impact as HTMLTextAreaElement).value.trim();
    (this.impact as HTMLTextAreaElement).readOnly = true;
    // Signed: the note becomes plain read-only text and keeps its words until the page has gone.
    const impactBox = this.impact?.closest('.ed-impact');
    impactBox?.classList.add('is-signed');
    this.busy = 'sign';
    this.publish();
    const started = Date.now();
    const left = Math.max(0, t.review_budget.limit - t.review_budget.used - 1);
    sign.startReview(new Date().toISOString(), {
      publicCount: t.public_probes.length,
      hidden: this.hiddenTotal,
      left,
    });
    setCount(this.parts.left, left);
    this.draftNotice = '';
    try {
      const result = await this.ctx.api.sign(t.id, draftId, note);
      const reviewId = result.signoff.review_id;
      this.ctx.remember(reviewId, t.id);
      // The stamp needs its moment: at least 900ms before the page moves on (not pretending to work).
      const wait = 900 - (Date.now() - started);
      if (wait > 0) await sleep(wait);
      sign.finished();
      this.learnReview(result.review);
      const ticket = await this.ctx.api.ticket(t.id).catch(() => t);
      this.ticket = ticket;
      this.signature = '';
      this.ctx.cacheReview(result.review, ticket);
      await sleep(240);
      // The stamp becomes the report's headline mark (shared element, one moment per practice;
      // desk.css names both only while this class is on).
      this.ctx.doc.documentElement.classList.add('ed-vt-sign');
      setTimeout(() => this.ctx.doc.documentElement.classList.remove('ed-vt-sign'), 900);
      this.busy = '';
      sign.release();
      this.ctx.navigate('engineer-review', reviewId);
      this.drawChanged();
      // The next round starts with an empty note, emptied only once the sheet is off screen.
      setTimeout(() => {
        if (this.impact) this.impact.value = '';
        setCount(this.parts.impactCount, 0);
        impactBox?.classList.remove('is-signed');
      }, 700);
    } catch (error) {
      this.busy = '';
      impactBox?.classList.remove('is-signed');
      (this.impact as HTMLTextAreaElement).readOnly = false;
      setCount(this.parts.left, Math.max(0, t.review_budget.limit - t.review_budget.used));
      sign.failed(failureText(error));
      this.publish();
    }
  }

  /* ---------- drafting by hand ---------- */

  private toggleCompose() {
    if (this.compose) this.compose = null;
    else {
      this.compose = newDraftForm(this.ticket as TicketDetail, this.changes());
      this.errors.compose = [];
    }
    this.drawSign();
    this.ctx.doc.getElementById(this.compose ? 'ed-draft-explanation' : 'ed-compose')?.focus();
  }

  private async saveDraft() {
    const t = this.ticket;
    if (!t || !this.compose || this.busy) return;
    const input = draftInput(this.compose, this.changes());
    const problems = validateDraft(
      input,
      t.public_probes.map((p) => p.id),
    );
    if (problems.length) {
      this.errors.compose = problems;
      this.drawSign();
      this.ctx.doc.getElementById('ed-draft-save')?.focus();
      return;
    }
    this.busy = 'draft';
    this.errors.compose = [];
    this.drawSign();
    try {
      await this.ctx.api.draft(t.id, input);
      this.compose = null;
      this.busy = '';
      await this.refresh();
      this.drawSign();
      this.publish();
      this.impact?.focus();
    } catch (error) {
      this.busy = '';
      this.errors.compose = [failureText(error)];
      this.drawSign();
    }
  }
}
