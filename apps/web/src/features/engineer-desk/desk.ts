/** The sign-off desk: the engineer's own screen in a practice (the second hat).
 *
 * The ticket arrives as a paper slip; the candidate settings are an instrument; the trial log is a
 * recessed tape of runs by you and by your Agent; the sign sheet is paper with one signature line.
 * Only the person signs. Everything shown comes from the engineer API; nothing here applies a
 * setting to the pilot. The element is kept across the workbench's re-renders, so typing, open
 * rows and scroll survive; ids on every control let the workbench put focus back. */
import { T } from '../../app/i18n';
import { renderAgentConnection, type ConnectionHost } from '../../app/agent-connection';
import { failureText, type EngineerApi } from './api';
import { fieldName, valueText, choiceText } from './copy';
import { agentNode, button, el, fill, iconNode, workLang, type Child } from './dom';
import {
  candidateChanges,
  claimsFromTrial,
  clock,
  draftTextLength,
  DRAFT_TEXT_LIMIT,
  experimentRows,
  IMPACT_NOTE_LIMIT,
  parseField,
  signSheet,
  signState,
  ticketFacts,
  trialLine,
  UNRESOLVED_LIMIT,
  validateDraft,
  validateImpactNote,
  type DraftInput,
  type EditableField,
  type Experiment,
  type ExperimentSummary,
  type JsonValue,
  type Mark,
  type Outcome,
  type Settings,
  type TicketDetail,
} from './model';

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
  readonly caseTitle: string;
  readonly api: EngineerApi;
  readonly agentHost: AgentHost | null;
  navigate(route: 'engineer' | 'engineer-review' | 'work', id?: string): void;
  notify(text: string): void;
  download(data: unknown, name: string): void;
  /** Remember which ticket a review belongs to (for the report's way back). */
  remember(reviewId: string, ticketId: string): void;
}

/** The five engineer tools an Agent may use, plus the two reads the server asks it to start with. */
export const ENGINEER_AGENT_ACTIONS = [
  'engineer.tickets.read',
  'engineer.reproduce',
  'engineer.trial',
  'engineer.submissions.draft',
  'engineer.reviews.read',
  'observation',
  'tools',
] as const;
const GRANT_MINUTES = 60;
const POLL_MS = 4000;
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

type StatementRow = { field: string; before: JsonValue; after: JsonValue; reason: string };
interface DraftForm {
  explanation: string;
  statements: StatementRow[];
  claimsOn: boolean;
  claims: Record<string, Outcome | ''>;
  unresolved: { description: string; probes: string[] }[];
}

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

export class EngineerDesk {
  readonly element: HTMLElement;
  private ticket: TicketDetail | null = null;
  private values: Settings = {};
  private fieldErrors: Record<string, string> = {};
  private readonly experiments = new Map<string, Experiment>();
  private readonly expanded = new Set<string>();
  private readonly drawn = new Set<string>();
  private compose: DraftForm | null = null;
  private busy: '' | 'reproduce' | 'trial' | 'draft' | 'sign' | 'grant' = '';
  private errors = { bench: '', sheet: '', agent: '', compose: [] as string[], load: '' };
  private signature = '';
  private impact: HTMLTextAreaElement | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private unwatchHost: () => void = () => {};
  private readonly parts: Record<string, HTMLElement> = {};

  constructor(
    private readonly ctx: DeskContext,
    private ticketId: string | null,
  ) {
    const doc = ctx.doc;
    this.element = el(doc, 'div', { class: 'ed', 'data-engineer-desk-root': true });
    this.element.append(
      el(
        doc,
        'p',
        { class: 'ed-loading', role: 'status' },
        T('正在打开委托…', 'Opening the ticket…'),
      ),
    );
    this.restoreExperiments();
    void this.load();
    this.timer = setInterval(() => void this.poll(), POLL_MS);
  }

  /** Back on screen after a redraw or a report: read the ticket again (an Agent may have worked). */
  resume() {
    if (this.ticket) void this.refresh();
  }

  /** Stop polling and watching (the instance is dropped). */
  destroy() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.unwatchHost();
  }

  /* ---------- data ---------- */

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
      const ticket = await this.ctx.api.ticket(this.ticketId);
      this.ticket = ticket;
      this.values = structuredClone(ticket.baseline_config);
      this.signature = this.signatureOf(ticket);
      for (const r of ticket.reviews) this.ctx.remember(r.review_id, ticket.id);
      for (const t of ticket.trials) this.drawn.add(t.id);
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
      this.drawLog();
      this.drawSheet();
      this.drawReviews();
      this.drawBenchState();
    } catch {
      /* A dropped read changes nothing; the next poll reads again. */
    }
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

  /* ---------- frame ---------- */

  private drawNoTicket() {
    const doc = this.ctx.doc;
    const open = button(doc, T('开一份委托', 'Open a ticket'), 'btn primary', {
      id: 'ed-open-seeded',
    });
    open.addEventListener('click', async () => {
      open.disabled = true;
      try {
        const { ticket } = await this.ctx.api.createTicket({ from: 'seeded' });
        this.ctx.navigate('engineer', ticket.id);
      } catch (error) {
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
    const retry = button(doc, T('再读一次', 'Read again'), 'btn small', { id: 'ed-retry' });
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
    const section = (name: string, cls: string, labelId?: string) => {
      const node = el(doc, 'section', { class: cls, 'aria-labelledby': labelId ?? null });
      this.parts[name] = node;
      return node;
    };
    this.parts.head = el(doc, 'header', { class: 'ed-head' });
    // Two columns on a wide desk (the work, and beside it the Agent, the probes and the reviews);
    // one column on a phone, where the Agent comes right after the ticket (desk.css orders it).
    const grid = el(
      doc,
      'div',
      { class: 'ed-grid' },
      el(
        doc,
        'div',
        { class: 'ed-main' },
        section('slip', 'ed-slip', 'ed-slip-h'),
        section('bench', 'ed-bench', 'ed-bench-h'),
        section('log', 'ed-log', 'ed-log-h'),
        section('sheet', 'ed-sheet', 'ed-sheet-h'),
      ),
      el(
        doc,
        'div',
        { class: 'ed-side' },
        section('agent', 'ed-agent', 'ed-agent-h'),
        section('probes', 'ed-probes', 'ed-probes-h'),
        section('reviews', 'ed-reviews', 'ed-reviews-h'),
      ),
    );
    this.element.replaceChildren(this.parts.head, grid);
    this.element.lang = workLang(T('zh', 'en') as 'zh' | 'en');
    this.drawHead();
    this.drawSlip();
    this.drawAgent();
    this.drawProbes();
    this.drawBench();
    this.drawLog();
    this.drawSheet();
    this.drawReviews();
    void t;
  }

  private drawHead() {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const facts = ticketFacts(t);
    const head = this.parts.head;
    // The way back to the product hat is the page's own back key ("产品经理工作板", top left).
    fill(
      head,
      el(
        doc,
        'p',
        { class: 'ed-hat' },
        el(doc, 'span', { class: 'ed-hat__role' }, T('工程师', 'Engineer')),
        el(doc, 'span', { class: 'ed-hat__case' }, this.ctx.caseTitle),
      ),
      el(
        doc,
        'h1',
        { class: 'ed-title', id: 'ed-title', tabindex: '-1', lang: workLang(t.work_language) },
        t.title,
      ),
      el(
        doc,
        'p',
        { class: 'ed-facts' },
        el(doc, 'span', { class: 'ed-fact' }, facts.source),
        el(doc, 'span', { class: 'ed-fact', title: t.retrieval.note ?? '' }, facts.retrieval),
      ),
      facts.setup
        ? el(doc, 'p', { class: 'ed-setup' }, iconNode(doc, 'info', 'i-xs'), facts.setup)
        : null,
    );
  }

  /* ---------- the ticket slip ---------- */

  private drawSlip() {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const facts = ticketFacts(t);
    const lang = workLang(t.work_language);
    const reproduce = button(
      doc,
      [iconNode(doc, 'refresh', 'i-xs'), T('复现这个问题', 'Reproduce the problem')],
      'btn small',
      { id: 'ed-reproduce' },
    );
    reproduce.addEventListener('click', () => void this.reproduce());
    this.parts.reproduce = reproduce;
    this.parts.slip.replaceChildren(
      el(
        doc,
        'div',
        { class: 'ed-slip__paper paper' },
        el(doc, 'h2', { class: 'ed-sec', id: 'ed-slip-h' }, T('要修的问题', 'What to fix')),
        ...facts.targets.map((target) =>
          el(
            doc,
            'article',
            { class: 'ed-target' },
            el(doc, 'p', { class: 'ed-target__q', lang }, target.query),
            el(
              doc,
              'figure',
              { class: 'ed-target__a' },
              el(doc, 'figcaption', {}, T(`当时${target.said}：`, `At the time, ${target.said}:`)),
              el(doc, 'blockquote', { lang }, target.answer),
            ),
            el(
              doc,
              'ul',
              { class: 'ed-target__facts' },
              ...target.versions.map((v) =>
                el(doc, 'li', { class: 'is-stale' }, iconNode(doc, 'stale', 'i-xs'), v.text),
              ),
              el(doc, 'li', {}, target.cited),
              el(doc, 'li', { lang }, target.origin),
              target.config ? el(doc, 'li', {}, target.config) : null,
            ),
          ),
        ),
        el(
          doc,
          'div',
          { class: 'ed-slip__foot' },
          reproduce,
          el(
            doc,
            'p',
            { class: 'meta' },
            T(
              '用委托打包时的快照重跑，确认问题还在。',
              'Reruns it on the ticket’s snapshot to confirm the problem is still there.',
            ),
          ),
        ),
      ),
    );
  }

  /* ---------- the Agent ---------- */

  private drawAgent() {
    const doc = this.ctx.doc;
    const host = this.ctx.agentHost;
    const available =
      host?.snapshot().available?.['delegations.create'] === true && !host?.snapshot().readOnly;
    const grant = button(
      doc,
      T('授权 Agent 处理这份委托', 'Give your agent this ticket'),
      'btn small',
      { id: 'ed-grant', disabled: !available || this.busy === 'grant' },
    );
    grant.addEventListener('click', () => void this.grant());
    const keys = el(doc, 'div', { class: 'ed-agent__keys' }, grant);
    this.parts.agentKeys = keys;
    const card = el(doc, 'div', { class: 'ed-agent__card' });
    this.parts.agentCard = card;
    // A new card element starts empty: draw the connection into it again.
    this.connectionShown = '';
    fill(
      this.parts.agent,
      el(doc, 'h2', { class: 'ed-sec', id: 'ed-agent-h' }, T('带上你的 Agent', 'Bring your agent')),
      el(
        doc,
        'p',
        { class: 'ed-agent__line' },
        agentNode(doc, 'sm'),
        el(
          doc,
          'span',
          {},
          T(
            '它可以复现、试跑、起草；签字只能由你来。',
            'It can reproduce, run trials and draft; only you can sign.',
          ),
        ),
      ),
      keys,
      !available
        ? el(
            doc,
            'p',
            { class: 'meta' },
            T('这个练习暂时不能授权 Agent。', 'This practice can’t grant agent access right now.'),
          )
        : null,
      this.errors.agent
        ? el(doc, 'p', { class: 'ed-error', role: 'alert' }, this.errors.agent)
        : null,
      card,
    );
    this.drawConnection();
    if (host) {
      this.unwatchHost();
      this.unwatchHost = host.subscribe(() => this.drawConnection());
    }
  }

  private connectionShown = '';
  private drawConnection() {
    const host = this.ctx.agentHost;
    const card = this.parts.agentCard;
    if (!card) return;
    const issued = host?.issuedDelegation() ?? null;
    // While a grant is offered here, its card stands in for the grant key.
    if (this.parts.agentKeys) this.parts.agentKeys.hidden = !!issued;
    const identity = JSON.stringify(issued);
    if (identity === this.connectionShown && card.isConnected) return;
    this.connectionShown = identity;
    renderAgentConnection(card, host, {
      origin: location.origin,
      notify: this.ctx.notify,
      download: this.ctx.download,
      refresh: () => {
        this.connectionShown = '';
        this.drawConnection();
      },
    });
  }

  private async grant() {
    const host = this.ctx.agentHost;
    if (!host || this.busy) return;
    this.busy = 'grant';
    this.errors.agent = '';
    this.drawAgent();
    try {
      const result = await host.command('delegations.create', {
        agent_label: T('工程委托', 'Engineering ticket'),
        capabilities: ['read', 'act'],
        allowed_actions: [...ENGINEER_AGENT_ACTIONS],
        expires_at: new Date(Date.now() + GRANT_MINUTES * 60_000).toISOString(),
      });
      if (result.status !== 'confirmed')
        this.errors.agent = T(
          '授权还没确认，到产品经理工作板的 Agent 标签核对原请求。',
          'The access isn’t confirmed yet. Check the original request in the Agent tab on the product board.',
        );
    } catch (error) {
      this.errors.agent = failureText(error);
    } finally {
      this.busy = '';
      this.drawAgent();
      (
        this.ctx.doc.querySelector('[data-connection-action="copy-claude"]') as HTMLElement | null
      )?.focus();
    }
  }

  /* ---------- public probes and reviews ---------- */

  private drawProbes() {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const targets = new Set(t.target_tests.map((x) => x.query));
    const lang = workLang(t.work_language);
    this.parts.probes.replaceChildren(
      el(
        doc,
        'h2',
        { class: 'ed-sec', id: 'ed-probes-h' },
        T(`公开探针 · ${t.public_probes.length} 条`, `Public probes · ${t.public_probes.length}`),
      ),
      el(
        doc,
        'ol',
        { class: 'ed-probe-list' },
        ...t.public_probes.map((p) =>
          el(
            doc,
            'li',
            {},
            el(doc, 'span', { class: 'ed-id' }, p.id),
            el(doc, 'span', { class: 'ed-probe-list__q', lang }, p.query),
            targets.has(p.query) ? el(doc, 'span', { class: 'ed-tag' }, T('目标', 'Target')) : null,
          ),
        ),
      ),
      el(
        doc,
        'p',
        { class: 'meta' },
        T(
          '复核时另跑隐藏探针，只给计数。',
          'The review also runs hidden probes and reports only their counts.',
        ),
      ),
    );
  }

  private drawReviews() {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const node = this.parts.reviews;
    if (!t.reviews.length) {
      node.hidden = true;
      node.replaceChildren();
      return;
    }
    node.hidden = false;
    node.replaceChildren(
      el(doc, 'h2', { class: 'ed-sec', id: 'ed-reviews-h' }, T('复核记录', 'Reviews')),
      el(
        doc,
        'ol',
        { class: 'ed-review-list' },
        ...t.reviews.map((r, i) => {
          const open = button(
            doc,
            [
              el(
                doc,
                'span',
                { class: 'ed-review-list__n' },
                T(`第 ${i + 1} 次`, `Review ${i + 1}`),
              ),
              el(
                doc,
                'span',
                { class: 'ed-review-list__s' },
                r.status === 'incomplete'
                  ? T('复核未完成', 'Review incomplete')
                  : r.status === 'report_mismatch'
                    ? T('复核完成，自报不符', 'Reviewed, self-report differs')
                    : T('复核完成', 'Reviewed'),
              ),
              el(doc, 'time', { datetime: r.signed_at }, clock(r.signed_at)),
              iconNode(doc, 'chev', 'i-xs'),
            ],
            'ed-review-list__open',
            { id: `ed-review-${i}` },
          );
          open.addEventListener('click', () => this.ctx.navigate('engineer-review', r.review_id));
          return el(doc, 'li', {}, open);
        }),
      ),
    );
  }

  /* ---------- candidate settings ---------- */

  private drawBench() {
    const doc = this.ctx.doc;
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
            ...all.map((name) => this.fieldRow(fields.get(name) as EditableField)),
          )
        : null;
    });
    const trial = button(
      doc,
      [iconNode(doc, 'play', 'i-xs'), T('试跑这组设置', 'Run a trial with these')],
      'btn small',
      { id: 'ed-trial' },
    );
    trial.addEventListener('click', () => void this.trial());
    const reset = button(doc, T('恢复基线', 'Reset to baseline'), 'btn small quiet', {
      id: 'ed-reset',
    });
    reset.addEventListener('click', () => this.resetCandidate());
    this.parts.trial = trial;
    this.parts.reset = reset;
    this.parts.diff = el(doc, 'div', { class: 'ed-diff', 'aria-live': 'polite' });
    this.parts.benchMeta = el(doc, 'span', { class: 'meta ed-bench__budget' });
    this.parts.benchError = el(doc, 'p', { class: 'ed-error', role: 'alert', hidden: true });
    this.parts.bench.replaceChildren(
      el(
        doc,
        'header',
        { class: 'ed-bench__head' },
        el(doc, 'h2', { class: 'ed-sec', id: 'ed-bench-h' }, T('候选设置', 'Candidate settings')),
        el(
          doc,
          'p',
          { class: 'meta' },
          T(
            '只改候选，试跑和复核用它；不会应用到试点。',
            'Changes only the candidate for trials and review; the pilot stays as it is.',
          ),
        ),
      ),
      el(
        doc,
        'form',
        { class: 'ed-form', id: 'ed-form', novalidate: true },
        el(doc, 'div', { class: 'ed-form__main' }, ...groups.slice(0, 2)),
        this.moreSettings(groups.slice(2)),
      ),
      this.parts.diff,
      el(doc, 'div', { class: 'ed-bench__keys' }, trial, reset, this.parts.benchMeta),
      this.parts.benchError,
    );
    (this.parts.bench.querySelector('form') as HTMLFormElement).addEventListener('submit', (e) => {
      e.preventDefault();
      void this.trial();
    });
    this.drawBenchState();
  }

  /** The scope and engineering-work settings, folded: rarely the fix, still one click away.
   * The fold says how many of its settings the candidate changed, and stays open once opened. */
  private moreOpen = false;
  private moreSettings(groups: Child[]): HTMLElement {
    const doc = this.ctx.doc;
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
      el(doc, 'div', { class: 'ed-form__main' }, ...groups),
    );
    more.addEventListener('toggle', () => {
      this.moreOpen = more.open;
    });
    this.parts.more = more;
    return more;
  }

  private fieldRow(field: EditableField): HTMLElement {
    const doc = this.ctx.doc;
    const name = field.field;
    const id = `ed-f-${name}`;
    const value = this.values[name];
    let control: HTMLElement;
    const labelId = `${id}-label`;
    const update = (next: JsonValue) => {
      this.values[name] = next;
      delete this.fieldErrors[name];
      this.drawBenchState();
    };
    if (field.type === 'set' || field.type === 'choice' || field.type === 'boolean') {
      const choices: readonly (string | boolean)[] =
        field.type === 'boolean' ? [true, false] : (field.choices ?? []);
      const multiple = field.type === 'set';
      control = el(doc, 'div', {
        class: 'choices wrap ed-choices',
        role: multiple ? 'group' : 'radiogroup',
        'aria-labelledby': labelId,
      });
      for (const choice of choices) {
        const key = String(choice);
        const checked = multiple
          ? Array.isArray(value) && value.map(String).includes(key)
          : value === choice;
        const input = el(doc, 'input', {
          type: multiple ? 'checkbox' : 'radio',
          name: id,
          value: key,
          id: `${id}-${key}`,
          checked,
        });
        input.addEventListener('change', () => {
          if (multiple) {
            const picked = [...control.querySelectorAll<HTMLInputElement>('input:checked')].map(
              (x) => x.value,
            );
            update((field.choices ?? []).filter((c) => picked.includes(c)));
          } else update(field.type === 'boolean' ? key === 'true' : key);
        });
        const cost = field.costs?.[key];
        control.append(
          el(
            doc,
            'label',
            { class: 'choice' },
            input,
            el(
              doc,
              'span',
              {},
              typeof choice === 'boolean' ? valueText(name, choice) : choiceText(name, key),
              cost !== undefined ? el(doc, 'small', {}, T(`${cost} 人日`, `${cost} pd`)) : null,
            ),
          ),
        );
      }
    } else if (field.type === 'text_list') {
      const area = el(doc, 'textarea', {
        class: 'textarea ed-topics',
        id,
        rows: 2,
        'aria-labelledby': labelId,
        'aria-describedby': `${id}-error`,
        placeholder: T('每行一个主题', 'One topic per line'),
      });
      area.value = Array.isArray(value) ? value.join('\n') : '';
      area.addEventListener('input', () => {
        const parsed = parseField(field, area.value);
        if ('value' in parsed) update(parsed.value);
        else {
          this.fieldErrors[name] = parsed.error;
          this.drawBenchState();
        }
      });
      control = area;
    } else {
      const input = el(doc, 'input', {
        class: 'input ed-num',
        id,
        type: 'text',
        inputmode: field.type === 'integer' ? 'numeric' : 'decimal',
        'aria-labelledby': labelId,
        'aria-describedby': `${id}-error`,
        autocomplete: 'off',
      });
      input.value = value === null || value === undefined ? '' : String(value);
      input.addEventListener('input', () => {
        const parsed = parseField(field, input.value);
        if ('value' in parsed) update(parsed.value);
        else {
          this.fieldErrors[name] = parsed.error;
          this.drawBenchState();
        }
      });
      control = input;
    }
    return el(
      doc,
      'div',
      { class: 'ed-field', 'data-field': name },
      el(
        doc,
        'div',
        { class: 'ed-field__label', id: labelId },
        el(doc, 'span', { class: 'ed-field__name' }, fieldName(name)),
        el(doc, 'code', { class: 'ed-key', lang: 'en' }, name),
      ),
      control,
      el(doc, 'p', { class: 'ed-field__was', 'data-was': name, hidden: true }),
      el(doc, 'p', { class: 'ed-field__error', id: `${id}-error`, hidden: true }),
    );
  }

  private changes(): Settings {
    return candidateChanges((this.ticket as TicketDetail).baseline_config, this.values);
  }

  private drawBenchState() {
    const doc = this.ctx.doc;
    const t = this.ticket;
    if (!t || !this.parts.diff) return;
    const changes = this.changes();
    for (const row of this.parts.bench.querySelectorAll<HTMLElement>('.ed-field')) {
      const name = row.dataset.field as string;
      const changed = name in changes;
      row.classList.toggle('is-changed', changed);
      const was = row.querySelector<HTMLElement>('.ed-field__was') as HTMLElement;
      was.hidden = !changed;
      was.textContent = changed
        ? T(
            `基线：${valueText(name, t.baseline_config[name])}`,
            `Baseline: ${valueText(name, t.baseline_config[name])}`,
          )
        : '';
      const error = row.querySelector<HTMLElement>('.ed-field__error') as HTMLElement;
      error.hidden = !this.fieldErrors[name];
      error.textContent = this.fieldErrors[name] ?? '';
      row.classList.toggle('has-error', !!this.fieldErrors[name]);
    }
    const entries = Object.entries(changes);
    const folded = [...(this.parts.more?.querySelectorAll<HTMLElement>('.ed-field') ?? [])].filter(
      (row) => (row.dataset.field as string) in changes,
    ).length;
    if (this.parts.moreCount)
      this.parts.moreCount.textContent = folded ? T(`改了 ${folded} 项`, `${folded} changed`) : '';
    this.parts.diff.replaceChildren(
      entries.length
        ? el(
            doc,
            'p',
            {},
            el(
              doc,
              'span',
              { class: 'ed-diff__lead' },
              T('候选与基线不同：', 'Differs from the baseline: '),
            ),
            ...entries.flatMap(([name, after], i) => [
              i ? el(doc, 'span', { class: 'ed-diff__sep', 'aria-hidden': 'true' }, ' · ') : null,
              el(
                doc,
                'span',
                { class: 'ed-diff__item' },
                el(doc, 'b', {}, fieldName(name)),
                ' ',
                valueText(name, t.baseline_config[name]),
                el(doc, 'span', { class: 'ed-arrow' }, ' → '),
                valueText(name, after),
              ),
            ]),
          )
        : el(
            doc,
            'p',
            { class: 'ed-diff__same' },
            T('和委托基线相同。', 'Same as the ticket baseline.'),
          ),
    );
    const blocked = Object.keys(this.fieldErrors).length > 0;
    const trial = this.parts.trial as HTMLButtonElement;
    trial.disabled = !!this.busy || blocked;
    trial.replaceChildren(
      iconNode(doc, 'play', 'i-xs'),
      this.busy === 'trial'
        ? T('试跑中…', 'Running…')
        : T('试跑这组设置', 'Run a trial with these'),
    );
    (this.parts.reset as HTMLButtonElement).disabled = !!this.busy || (!entries.length && !blocked);
    const reproduce = this.parts.reproduce as HTMLButtonElement;
    reproduce.disabled = !!this.busy;
    reproduce.replaceChildren(
      iconNode(doc, 'refresh', 'i-xs'),
      this.busy === 'reproduce'
        ? T('复现中…', 'Reproducing…')
        : T('复现这个问题', 'Reproduce the problem'),
    );
    this.parts.benchMeta.textContent = T(
      `已试 ${t.experiment_budget.used}/${t.experiment_budget.limit} 次`,
      `${t.experiment_budget.used}/${t.experiment_budget.limit} runs used`,
    );
    this.parts.benchError.hidden = !this.errors.bench;
    this.parts.benchError.textContent = this.errors.bench;
  }

  private resetCandidate() {
    const t = this.ticket as TicketDetail;
    this.values = structuredClone(t.baseline_config);
    this.fieldErrors = {};
    const focusId = this.ctx.doc.activeElement?.id;
    this.drawBench();
    this.ctx.doc.getElementById(focusId ?? 'ed-trial')?.focus();
    this.ctx.notify(T('候选已恢复为基线。', 'The candidate is back to the baseline.'));
  }

  /** Say the run's result to screen readers, through the workbench's own live region. */
  private announceRun(record: Experiment) {
    const t = this.ticket as TicketDetail;
    const line = trialLine(record, t.public_probes.length);
    const region = this.ctx.doc.getElementById('announcer');
    if (!region) return;
    region.textContent = '';
    setTimeout(() => {
      region.textContent = `${line.verb}${T('完成：', ' done: ')}${line.tally}`;
    }, 30);
  }

  private async reproduce() {
    if (!this.ticket || this.busy) return;
    this.busy = 'reproduce';
    this.errors.bench = '';
    this.drawBenchState();
    try {
      const record = await this.ctx.api.reproduce(this.ticket.id);
      this.keepExperiment(record);
      this.expanded.add(record.id);
      await this.refresh();
      this.announceRun(record);
    } catch (error) {
      this.errors.bench = failureText(error);
    } finally {
      this.busy = '';
      this.drawBenchState();
      this.drawLog();
    }
  }

  private async trial() {
    if (!this.ticket || this.busy || Object.keys(this.fieldErrors).length) return;
    this.busy = 'trial';
    this.errors.bench = '';
    this.drawBenchState();
    try {
      const record = await this.ctx.api.trial(this.ticket.id, this.changes());
      this.keepExperiment(record);
      this.expanded.clear();
      this.expanded.add(record.id);
      await this.refresh();
      this.announceRun(record);
    } catch (error) {
      this.errors.bench = failureText(error);
    } finally {
      this.busy = '';
      this.drawBenchState();
      this.drawLog();
    }
  }

  /* ---------- the trial log ---------- */

  private drawLog() {
    const doc = this.ctx.doc;
    const t = this.ticket;
    const node = this.parts.log;
    if (!t || !node) return;
    const publicCount = t.public_probes.length;
    const lines = [...t.trials].reverse();
    const tape = el(doc, 'ol', { class: 'ed-tape' });
    for (const summary of lines) tape.append(this.logLine(summary, publicCount));
    keepingFocus(doc, () =>
      node.replaceChildren(
        el(
          doc,
          'header',
          { class: 'ed-log__head' },
          el(doc, 'h2', { class: 'ed-sec', id: 'ed-log-h' }, T('试验记录', 'Trial log')),
        ),
        lines.length
          ? tape
          : el(
              doc,
              'p',
              { class: 'ed-tape ed-tape--empty' },
              T(
                '先复现一次，确认问题还在。',
                'Reproduce the problem first to confirm it’s still there.',
              ),
            ),
      ),
    );
    for (const s of lines) this.drawn.add(s.id);
  }

  private logLine(summary: ExperimentSummary, publicCount: number): HTMLElement {
    const doc = this.ctx.doc;
    const line = trialLine(summary, publicCount);
    const full = this.experiments.get(summary.id);
    const open = this.expanded.has(summary.id);
    const fresh = !this.drawn.has(summary.id);
    const rowsId = `ed-rows-${summary.id}`;
    const head = button(
      doc,
      [
        el(doc, 'time', { class: 'ed-line__time', datetime: summary.created_at }, line.time),
        el(doc, 'span', { class: 'ed-line__who' }, line.agent ? agentNode(doc) : null, line.who),
        el(doc, 'span', { class: 'ed-line__verb' }, line.verb),
        el(
          doc,
          'span',
          { class: 'ed-line__fields' },
          line.fields || (summary.kind === 'trial' ? T('基线设置', 'Baseline settings') : ''),
        ),
        this.pips(summary, full, publicCount),
        el(doc, 'span', { class: 'ed-line__tally', 'data-tone': line.tone }, line.tally),
      ],
      'ed-line__head',
      { id: `ed-line-${summary.id}`, 'aria-expanded': String(open), 'aria-controls': rowsId },
    );
    head.addEventListener('click', () => {
      if (this.expanded.has(summary.id)) this.expanded.delete(summary.id);
      else this.expanded.add(summary.id);
      this.drawLog();
    });
    const rows = el(doc, 'div', { class: 'ed-line__rows', id: rowsId, hidden: !open });
    if (open) rows.append(this.lineRows(summary, full));
    return el(
      doc,
      'li',
      {
        class: `ed-line${fresh ? ' is-new' : ''}`,
        'data-kind': summary.kind,
        'data-agent': line.agent ? 'true' : null,
      },
      head,
      rows,
    );
  }

  private pips(
    summary: ExperimentSummary,
    full: Experiment | undefined,
    publicCount: number,
  ): HTMLElement {
    const doc = this.ctx.doc;
    const marks: { mark: Mark; label: string }[] = [];
    if (full?.rows) {
      for (const row of experimentRows(full))
        if (row.id || summary.kind === 'reproduce')
          marks.push({ mark: row.mark, label: `${row.id ? `${row.id} ` : ''}${row.verdict}` });
    } else if (summary.kind === 'trial') {
      const c = summary.counts;
      const passed = c.passed ?? 0;
      const failed = c.failed ?? 0;
      for (let i = 0; i < publicCount; i++)
        marks.push({
          mark: i < passed ? 'good' : i < passed + failed ? 'ink' : 'unknown',
          label: '',
        });
    } else {
      const c = summary.counts;
      for (let i = 0; i < (c.total ?? 0); i++)
        marks.push({ mark: i < (c.matched ?? 0) ? 'good' : 'warn', label: '' });
    }
    return el(
      doc,
      'span',
      { class: 'ed-pips', 'aria-hidden': 'true' },
      ...marks.slice(0, 12).map((m, i) =>
        el(doc, 'span', {
          class: 'ed-pip',
          'data-mark': m.mark,
          style: `--i:${i}`,
          title: m.label || null,
        }),
      ),
    );
  }

  private lineRows(summary: ExperimentSummary, full: Experiment | undefined): Node {
    const doc = this.ctx.doc;
    if (!full?.rows) {
      const own = summary.executor.kind === 'human';
      return el(
        doc,
        'p',
        { class: 'ed-rows-note' },
        own
          ? T(
              '这次试验的逐行结果不在这个页面上，这里只有计数。',
              'This run’s rows aren’t on this page; only its counts are.',
            )
          : T(
              '逐行结果在你的 Agent 那里，这里只有计数。',
              'Your agent has this run’s rows; only its counts are here.',
            ),
      );
    }
    const t = this.ticket as TicketDetail;
    const lang = workLang(t.work_language);
    const reproduction = summary.kind === 'reproduce';
    const changes = Object.entries(full.changes ?? {});
    return el(
      doc,
      'div',
      {},
      changes.length
        ? el(
            doc,
            'p',
            { class: 'ed-rows-config' },
            ...changes.flatMap(([name, change], i) => [
              i ? ' · ' : null,
              el(
                doc,
                'span',
                {},
                el(doc, 'b', {}, fieldName(name)),
                ' ',
                valueText(name, change.before),
                el(doc, 'span', { class: 'ed-arrow' }, ' → '),
                valueText(name, change.after),
              ),
            ]),
          )
        : null,
      el(
        doc,
        'ol',
        { class: 'ed-rows' },
        ...experimentRows(full).map((row) =>
          el(
            doc,
            'li',
            { class: 'ed-row', 'data-mark': row.mark },
            el(doc, 'span', { class: 'ed-row__mark', 'aria-hidden': 'true' }),
            el(doc, 'span', { class: 'ed-row__id' }, row.id),
            el(
              doc,
              'span',
              { class: 'ed-row__q', lang },
              row.query,
              row.target && !reproduction
                ? el(
                    doc,
                    'span',
                    { class: 'ed-tag', lang: workLang(T('zh', 'en') as 'zh' | 'en') },
                    T('目标', 'Target'),
                  )
                : null,
            ),
            el(
              doc,
              'span',
              { class: 'ed-row__io' },
              row.expected
                ? `${reproduction ? T('记录 ', 'Recorded: ') : T('期望 ', 'Expected: ')}${row.expected} · `
                : '',
              `${reproduction ? T('复现 ', 'Rerun: ') : T('实际 ', 'Got: ')}${row.actual}`,
            ),
            el(doc, 'span', { class: 'ed-row__verdict', 'data-mark': row.mark }, row.verdict),
            row.answer ? el(doc, 'p', { class: 'ed-row__answer', lang }, row.answer) : null,
          ),
        ),
      ),
    );
  }

  /* ---------- the sign sheet ---------- */

  private drawSheet() {
    const doc = this.ctx.doc;
    const t = this.ticket;
    const node = this.parts.sheet;
    if (!t || !node) return;
    keepingFocus(doc, () => this.drawSheetInner(t, node));
  }

  private drawSheetInner(t: TicketDetail, node: HTMLElement) {
    const doc = this.ctx.doc;
    const latest = t.latest_draft;
    const composeLabel = latest
      ? T('自己重新起草', 'Write your own draft')
      : T('自己起草', 'Write a draft');
    const compose = button(doc, [iconNode(doc, 'edit', 'i-xs'), composeLabel], 'btn small quiet', {
      id: 'ed-compose',
      'aria-expanded': String(!!this.compose),
    });
    compose.addEventListener('click', () => this.toggleCompose());
    const parts: Child[] = [];
    if (this.compose) parts.push(this.composeForm());
    else if (latest) parts.push(this.sheetBody());
    else
      parts.push(
        el(
          doc,
          'p',
          { class: 'ed-sheet__empty' },
          T(
            '还没有草稿：等你的 Agent 起草，或者自己起草。',
            'No draft yet: wait for your agent’s, or write one yourself.',
          ),
        ),
      );
    if (!this.impact) {
      this.impact = el(doc, 'textarea', {
        class: 'textarea ed-impact__field',
        id: 'ed-impact',
        rows: 3,
        maxlength: IMPACT_NOTE_LIMIT,
        'aria-describedby': 'ed-impact-count',
        required: true,
      });
      this.impact.addEventListener('input', () => this.drawSignState());
    }
    const state = signState(t);
    const sign = button(
      doc,
      T('签字提交复核', 'Sign and submit for review'),
      'btn primary ed-sign__key',
      { id: 'ed-sign' },
    );
    sign.addEventListener('click', () => void this.sign());
    this.parts.sign = sign;
    this.parts.signWho = el(doc, 'p', { class: 'ed-sign__who' });
    this.parts.signNote = el(doc, 'p', { class: 'ed-sign__note' });
    this.parts.impactCount = el(doc, 'span', { class: 'ed-impact__count', id: 'ed-impact-count' });
    this.parts.sheetError = el(
      doc,
      'p',
      { class: 'ed-error', role: 'alert', hidden: !this.errors.sheet },
      this.errors.sheet,
    );
    const signedLink =
      state.signedReview && !this.compose
        ? (() => {
            const b = button(
              doc,
              T('看这次复核的报告', 'See this review’s report'),
              'btn small quiet',
              { id: 'ed-signed-report' },
            );
            b.addEventListener('click', () =>
              this.ctx.navigate('engineer-review', state.signedReview),
            );
            return b;
          })()
        : null;
    node.replaceChildren(
      el(
        doc,
        'div',
        { class: 'ed-sheet__paper paper' },
        el(
          doc,
          'header',
          { class: 'ed-sheet__head' },
          el(doc, 'h2', { class: 'ed-sec', id: 'ed-sheet-h' }, T('签字单', 'Sign-off sheet')),
          compose,
        ),
        ...parts,
        latest && !this.compose
          ? el(
              doc,
              'div',
              { class: 'ed-impact' },
              el(
                doc,
                'label',
                { class: 'ed-impact__label', for: 'ed-impact' },
                T('这个改动还可能影响哪些问题', 'Which other questions might this change affect?'),
              ),
              this.impact,
              el(doc, 'div', { class: 'ed-impact__meta' }, this.parts.impactCount),
            )
          : null,
        this.parts.sheetError,
        el(
          doc,
          'footer',
          { class: 'ed-sign' },
          el(doc, 'div', { class: 'ed-sign__line' }, this.parts.signWho, this.parts.signNote),
          el(doc, 'div', { class: 'ed-sign__keys' }, signedLink, sign),
        ),
      ),
    );
    this.drawSignState();
  }

  private sheetBody(): HTMLElement {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const sheet = signSheet(t.latest_draft as NonNullable<TicketDetail['latest_draft']>);
    const lang = workLang(t.work_language);
    const change = (c: { name: string; before: string; after: string }) =>
      el(
        doc,
        'span',
        { class: 'ed-change' },
        el(doc, 'b', {}, c.name),
        el(
          doc,
          'span',
          { class: 'ed-change__values' },
          c.before,
          el(doc, 'span', { class: 'ed-arrow' }, ' → '),
          c.after,
        ),
      );
    return el(
      doc,
      'div',
      { class: 'ed-sheet__body' },
      el(
        doc,
        'p',
        { class: 'ed-sheet__byline' },
        sheet.agent ? agentNode(doc) : null,
        T(
          `${sheet.agent ? '你的 Agent 起草' : '你起草'} · ${sheet.time}`,
          `${sheet.agent ? 'Drafted by your agent' : 'Drafted by you'} · ${sheet.time}`,
        ),
      ),
      el(
        doc,
        'div',
        { class: 'ed-compare' },
        el(
          doc,
          'div',
          { class: 'ed-compare__col' },
          el(doc, 'h3', { class: 'ed-sub' }, T('实际改动', 'Actual change')),
          sheet.actual.length
            ? el(
                doc,
                'ul',
                { class: 'ed-compare__list' },
                ...sheet.actual.map((c) => el(doc, 'li', {}, change(c))),
              )
            : el(
                doc,
                'p',
                { class: 'meta' },
                T('和基线相同，没有改动。', 'Same as the baseline; nothing changed.'),
              ),
        ),
        el(
          doc,
          'div',
          { class: 'ed-compare__col' },
          el(doc, 'h3', { class: 'ed-sub' }, T('说明里写的改动', 'Change as stated')),
          sheet.stated.length
            ? el(
                doc,
                'ul',
                { class: 'ed-compare__list' },
                ...sheet.stated.map((c) =>
                  el(
                    doc,
                    'li',
                    {},
                    change(c),
                    el(doc, 'span', { class: 'ed-change__reason', lang }, c.reason),
                  ),
                ),
              )
            : el(doc, 'p', { class: 'meta' }, T('没有逐条写改动。', 'No change is stated.')),
        ),
      ),
      sheet.explanation
        ? el(
            doc,
            'div',
            { class: 'ed-explain' },
            el(doc, 'h3', { class: 'ed-sub' }, T('说明', 'Explanation')),
            el(doc, 'p', { class: 'ed-explain__text', lang }, sheet.explanation),
          )
        : null,
      el(
        doc,
        'div',
        { class: 'ed-claims' },
        el(doc, 'h3', { class: 'ed-sub' }, T('自报结果', 'Self-reported results')),
        sheet.claims.length
          ? el(
              doc,
              'ul',
              { class: 'ed-claims__list' },
              ...sheet.claims.map((c) =>
                el(doc, 'li', {}, el(doc, 'span', { class: 'ed-id' }, c.id), c.text),
              ),
            )
          : el(doc, 'p', { class: 'meta' }, T('没有附自报结果。', 'No self-report attached.')),
      ),
      el(
        doc,
        'div',
        { class: 'ed-unresolved' },
        el(doc, 'h3', { class: 'ed-sub' }, T('未修复项', 'Unresolved')),
        sheet.unresolved.length
          ? el(
              doc,
              'ul',
              {},
              ...sheet.unresolved.map((u) =>
                el(
                  doc,
                  'li',
                  {},
                  el(doc, 'span', { lang }, u.description),
                  u.probes ? el(doc, 'span', { class: 'ed-id' }, u.probes) : null,
                ),
              ),
            )
          : el(doc, 'p', { class: 'meta' }, T('没有写未修复项。', 'None listed.')),
      ),
    );
  }

  private drawSignState() {
    const t = this.ticket;
    if (!t || !this.parts.sign) return;
    const state = signState(t);
    const note = this.impact?.value ?? '';
    const count = [...note.trim()].length;
    if (this.parts.impactCount) {
      this.parts.impactCount.textContent = `${count}/${IMPACT_NOTE_LIMIT}`;
      this.parts.impactCount.dataset.over = String(count > IMPACT_NOTE_LIMIT);
    }
    const sign = this.parts.sign as HTMLButtonElement;
    sign.disabled = !state.can || !!this.busy || !!this.compose;
    sign.textContent =
      this.busy === 'sign'
        ? T('正在复核…', 'Reviewing…')
        : T('签字提交复核', 'Sign and submit for review');
    this.parts.signWho.textContent = T(
      `只能由你签 · 还剩 ${state.left} 次复核`,
      `Only you can sign · ${state.left} ${state.left === 1 ? 'review' : 'reviews'} left`,
    );
    this.parts.signNote.textContent = this.compose
      ? T('先保存或取消草稿。', 'Save or cancel the draft first.')
      : state.reason;
    this.parts.signNote.hidden = !this.parts.signNote.textContent;
  }

  private async sign() {
    const t = this.ticket;
    if (!t || this.busy || !t.latest_draft) return;
    const problem = validateImpactNote(this.impact?.value ?? '');
    if (problem) {
      this.errors.sheet = problem;
      this.drawSheet();
      this.impact?.focus();
      return;
    }
    this.busy = 'sign';
    this.errors.sheet = '';
    this.drawSignState();
    try {
      const result = await this.ctx.api.sign(
        t.id,
        t.latest_draft.id,
        (this.impact as HTMLTextAreaElement).value.trim(),
      );
      const reviewId = result.signoff.review_id;
      this.ctx.remember(reviewId, t.id);
      if (this.impact) this.impact.value = '';
      this.busy = '';
      await this.refresh();
      this.ctx.navigate('engineer-review', reviewId);
    } catch (error) {
      this.busy = '';
      this.errors.sheet = failureText(error);
      this.drawSheet();
    }
  }

  /* ---------- drafting by hand ---------- */

  private toggleCompose() {
    if (this.compose) this.compose = null;
    else {
      const t = this.ticket as TicketDetail;
      const changes = this.changes();
      this.compose = {
        explanation: '',
        statements: Object.entries(changes).map(([field, after]) => ({
          field,
          before: t.baseline_config[field],
          after,
          reason: '',
        })),
        claimsOn: false,
        claims: Object.fromEntries(t.public_probes.map((p) => [p.id, ''])),
        unresolved: [],
      };
      this.errors.compose = [];
    }
    this.drawSheet();
    this.ctx.doc.getElementById(this.compose ? 'ed-draft-explanation' : 'ed-compose')?.focus();
  }

  private draftInput(): DraftInput {
    const form = this.compose as DraftForm;
    return {
      changes: this.changes(),
      explanation: form.explanation.trim(),
      change_statements: form.statements.map((s) => ({ ...s, reason: s.reason.trim() })),
      claimed_results: form.claimsOn
        ? (Object.fromEntries(Object.entries(form.claims).filter(([, v]) => v)) as Record<
            string,
            Outcome
          >)
        : {},
      unresolved: form.unresolved.map((u) => ({
        description: u.description.trim(),
        probe_ids: u.probes,
      })),
    };
  }

  private composeForm(): HTMLElement {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const form = this.compose as DraftForm;
    const fields = new Map(t.editable_fields.map((f) => [f.field, f]));
    const counter = el(doc, 'span', { class: 'ed-compose__count', 'aria-live': 'polite' });
    const recount = () => {
      const n = draftTextLength(this.draftInput());
      counter.textContent = T(
        `已写 ${n}/${DRAFT_TEXT_LIMIT} 字`,
        `${n}/${DRAFT_TEXT_LIMIT} characters`,
      );
      counter.dataset.over = String(n > DRAFT_TEXT_LIMIT);
    };
    const changes = Object.entries(this.changes());
    const explanation = el(doc, 'textarea', {
      class: 'textarea',
      id: 'ed-draft-explanation',
      rows: 3,
    });
    explanation.value = form.explanation;
    explanation.addEventListener('input', () => {
      form.explanation = explanation.value;
      recount();
    });
    const statementRow = (s: StatementRow, i: number) => {
      const field = fields.get(s.field);
      const valueControl = (which: 'before' | 'after') => {
        const id = `ed-st-${i}-${which}`;
        const label = which === 'before' ? T('改前', 'Before') : T('改后', 'After');
        const set = (v: JsonValue) => {
          s[which] = v;
          recount();
        };
        if (field && (field.type === 'choice' || field.type === 'boolean')) {
          const select = el(doc, 'select', {
            class: 'select ed-st__value',
            id,
            'aria-label': `${fieldName(s.field)} · ${label}`,
          });
          const options: (string | boolean)[] =
            field.type === 'boolean' ? [true, false] : [...(field.choices ?? [])];
          for (const o of options)
            select.append(
              el(
                doc,
                'option',
                { value: String(o), selected: s[which] === o },
                typeof o === 'boolean' ? valueText(s.field, o) : choiceText(s.field, o),
              ),
            );
          select.addEventListener('change', () =>
            set(field.type === 'boolean' ? select.value === 'true' : select.value),
          );
          return select;
        }
        if (field && (field.type === 'integer' || field.type === 'number')) {
          const input = el(doc, 'input', {
            class: 'input ed-st__value',
            id,
            inputmode: 'decimal',
            'aria-label': `${fieldName(s.field)} · ${label}`,
            autocomplete: 'off',
          });
          input.value = s[which] === null || s[which] === undefined ? '' : String(s[which]);
          input.addEventListener('input', () => {
            const n = Number(input.value.trim());
            set(input.value.trim() !== '' && Number.isFinite(n) ? n : input.value);
          });
          return input;
        }
        return el(doc, 'span', { class: 'ed-st__fixed', id }, valueText(s.field, s[which]));
      };
      const reason = el(doc, 'input', {
        class: 'input',
        id: `ed-st-${i}-reason`,
        maxlength: 500,
        placeholder: T('为什么这样改', 'Why this change'),
        'aria-label': `${fieldName(s.field)} · ${T('理由', 'Reason')}`,
        autocomplete: 'off',
      });
      reason.value = s.reason;
      reason.addEventListener('input', () => {
        s.reason = reason.value;
        recount();
      });
      const remove = button(
        doc,
        [
          iconNode(doc, 'x', 'i-xs'),
          el(
            doc,
            'span',
            { class: 'sr-only' },
            T(`不写「${fieldName(s.field)}」这一条`, `Leave out “${fieldName(s.field)}”`),
          ),
        ],
        'btn icon small quiet',
        { id: `ed-st-${i}-remove` },
      );
      remove.addEventListener('click', () => {
        form.statements.splice(i, 1);
        this.drawSheet();
        this.ctx.doc
          .getElementById(
            form.statements.length
              ? `ed-st-${Math.min(i, form.statements.length - 1)}-reason`
              : 'ed-draft-explanation',
          )
          ?.focus();
      });
      return el(
        doc,
        'li',
        { class: 'ed-st' },
        el(doc, 'span', { class: 'ed-st__name' }, fieldName(s.field)),
        el(
          doc,
          'span',
          { class: 'ed-st__values' },
          valueControl('before'),
          el(doc, 'span', { class: 'ed-arrow', 'aria-hidden': 'true' }, '→'),
          valueControl('after'),
        ),
        reason,
        remove,
      );
    };
    // Self-report: every public probe or none.
    const claimsOn = el(doc, 'input', {
      type: 'checkbox',
      id: 'ed-claims-on',
      checked: form.claimsOn,
    });
    const latestTrial = [...t.trials]
      .reverse()
      .map((s) => this.experiments.get(s.id))
      .find((e) => e?.kind === 'trial' && e.rows);
    const fill = button(
      doc,
      T('用最近一次试跑结果填', 'Fill from the latest trial'),
      'btn small quiet',
      { id: 'ed-claims-fill', disabled: !latestTrial },
    );
    fill.addEventListener('click', () => {
      const claims = latestTrial
        ? claimsFromTrial(
            latestTrial,
            t.public_probes.map((p) => p.id),
          )
        : null;
      if (!claims) return;
      form.claimsOn = true;
      form.claims = claims;
      this.drawSheet();
      this.ctx.doc.getElementById('ed-claims-fill')?.focus();
    });
    claimsOn.addEventListener('change', () => {
      form.claimsOn = claimsOn.checked;
      this.drawSheet();
      this.ctx.doc.getElementById('ed-claims-on')?.focus();
    });
    const claimRows = form.claimsOn
      ? el(
          doc,
          'ul',
          { class: 'ed-claim-picks' },
          ...t.public_probes.map((p) => {
            const select = el(
              doc,
              'select',
              {
                class: 'select',
                id: `ed-claim-${p.id}`,
                'aria-label': `${p.id} · ${T('自报结果', 'Self-reported result')}`,
              },
              el(doc, 'option', { value: '', selected: !form.claims[p.id] }, T('未填', 'Not set')),
              ...(['pass', 'fail', 'error'] as const).map((o) =>
                el(
                  doc,
                  'option',
                  { value: o, selected: form.claims[p.id] === o },
                  {
                    pass: T('通过', 'Passed'),
                    fail: T('未通过', 'Did not pass'),
                    error: T('执行出错', 'Run failed'),
                  }[o],
                ),
              ),
            );
            select.addEventListener('change', () => {
              form.claims[p.id] = select.value as Outcome | '';
            });
            return el(
              doc,
              'li',
              {},
              el(doc, 'label', { class: 'ed-id', for: `ed-claim-${p.id}` }, p.id),
              select,
            );
          }),
        )
      : null;
    // Unresolved items.
    const unresolvedRows = form.unresolved.map((u, i) => {
      const text = el(doc, 'input', {
        class: 'input',
        id: `ed-un-${i}`,
        maxlength: 1000,
        placeholder: T('还没修好的问题', 'What is still not fixed'),
        'aria-label': T(`未修复项 ${i + 1}`, `Unresolved item ${i + 1}`),
        autocomplete: 'off',
      });
      text.value = u.description;
      text.addEventListener('input', () => {
        u.description = text.value;
        recount();
      });
      const probes = el(
        doc,
        'div',
        {
          class: 'choices ed-un__probes',
          role: 'group',
          'aria-label': T('涉及的公开探针', 'Public probes involved'),
        },
        ...t.public_probes.map((p) => {
          const box = el(doc, 'input', {
            type: 'checkbox',
            id: `ed-un-${i}-${p.id}`,
            value: p.id,
            checked: u.probes.includes(p.id),
          });
          box.addEventListener('change', () => {
            u.probes = t.public_probes
              .map((x) => x.id)
              .filter((id) => (id === p.id ? box.checked : u.probes.includes(id)));
          });
          return el(doc, 'label', { class: 'choice' }, box, el(doc, 'span', {}, p.id));
        }),
      );
      const remove = button(
        doc,
        [
          iconNode(doc, 'x', 'i-xs'),
          el(doc, 'span', { class: 'sr-only' }, T('删去这一条', 'Remove this item')),
        ],
        'btn icon small quiet',
        { id: `ed-un-${i}-remove` },
      );
      remove.addEventListener('click', () => {
        form.unresolved.splice(i, 1);
        this.drawSheet();
        this.ctx.doc.getElementById('ed-un-add')?.focus();
      });
      return el(doc, 'li', { class: 'ed-un' }, text, probes, remove);
    });
    const addUnresolved = button(
      doc,
      [iconNode(doc, 'plus', 'i-xs'), T('添加一条未修复项', 'Add an unresolved item')],
      'btn small quiet',
      { id: 'ed-un-add', disabled: form.unresolved.length >= UNRESOLVED_LIMIT },
    );
    addUnresolved.addEventListener('click', () => {
      form.unresolved.push({ description: '', probes: [] });
      this.drawSheet();
      this.ctx.doc.getElementById(`ed-un-${form.unresolved.length - 1}`)?.focus();
    });
    const cancel = button(doc, T('取消', 'Cancel'), 'btn small quiet', { id: 'ed-draft-cancel' });
    cancel.addEventListener('click', () => this.toggleCompose());
    const save = button(
      doc,
      this.busy === 'draft' ? T('正在保存…', 'Saving…') : T('保存草稿', 'Save the draft'),
      'btn small',
      { id: 'ed-draft-save', disabled: !!this.busy },
    );
    save.addEventListener('click', () => void this.saveDraft());
    const view = el(
      doc,
      'div',
      { class: 'ed-compose' },
      el(
        doc,
        'p',
        { class: 'ed-compose__from' },
        changes.length
          ? T(
              '草稿的设置取自上面的候选：',
              'The draft takes its settings from the candidate above: ',
            ) + changes.map(([f]) => fieldName(f)).join(T('、', ', '))
          : T(
              '候选和基线相同，草稿不会改任何设置。',
              'The candidate matches the baseline, so the draft changes nothing.',
            ),
      ),
      el(
        doc,
        'label',
        { class: 'ed-compose__label', for: 'ed-draft-explanation' },
        T('说明', 'Explanation'),
      ),
      explanation,
      el(
        doc,
        'div',
        { class: 'ed-compose__block' },
        el(doc, 'h3', { class: 'ed-sub' }, T('逐条变更', 'Changes, one by one')),
        form.statements.length
          ? el(doc, 'ol', { class: 'ed-st-list' }, ...form.statements.map(statementRow))
          : el(doc, 'p', { class: 'meta' }, T('没有要写的变更。', 'No changes to state.')),
      ),
      el(
        doc,
        'div',
        { class: 'ed-compose__block' },
        el(
          doc,
          'div',
          { class: 'ed-compose__row' },
          el(
            doc,
            'label',
            { class: 'ed-check', for: 'ed-claims-on' },
            claimsOn,
            el(doc, 'span', {}, T('附上自报结果', 'Attach a self-report')),
          ),
          fill,
        ),
        claimRows,
      ),
      el(
        doc,
        'div',
        { class: 'ed-compose__block' },
        el(doc, 'h3', { class: 'ed-sub' }, T('未修复项', 'Unresolved')),
        unresolvedRows.length ? el(doc, 'ol', { class: 'ed-un-list' }, ...unresolvedRows) : null,
        addUnresolved,
      ),
      this.errors.compose.length
        ? el(
            doc,
            'ul',
            { class: 'ed-error ed-compose__errors', role: 'alert' },
            ...this.errors.compose.map((e) => el(doc, 'li', {}, e)),
          )
        : null,
      el(doc, 'div', { class: 'ed-compose__keys' }, counter, cancel, save),
    );
    recount();
    return view;
  }

  private async saveDraft() {
    const t = this.ticket;
    if (!t || !this.compose || this.busy) return;
    const input = this.draftInput();
    const problems = validateDraft(
      input,
      t.public_probes.map((p) => p.id),
    );
    if (problems.length) {
      this.errors.compose = problems;
      this.drawSheet();
      this.ctx.doc.getElementById('ed-draft-save')?.focus();
      return;
    }
    this.busy = 'draft';
    this.errors.compose = [];
    this.drawSheet();
    try {
      await this.ctx.api.draft(t.id, input);
      this.compose = null;
      this.busy = '';
      await this.refresh();
      this.drawSheet();
      this.drawBenchState();
      this.impact?.focus();
      // The sheet itself now shows the draft and the note field has focus: that is the landing.
    } catch (error) {
      this.busy = '';
      this.errors.compose = [failureText(error)];
      this.drawSheet();
    }
  }
}
