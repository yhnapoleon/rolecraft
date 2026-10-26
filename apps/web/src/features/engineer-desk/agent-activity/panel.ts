/** S5 · Your agent, on the desk (plan §13.7): who it is and whether it is connected (the agent
 * bus), the division of labour (it can read, reproduce, trial and draft; only you sign), one
 * sentence to give it, "Connect" (My agent, #/agent: access is issued only there), the shared live
 * stream (205's TransmissionStream, compact; a row opens its card), and the things it handed in:
 * reproductions, trials as a diff of settings, drafts with "actual n · stated m → compare on the
 * sign-off sheet". Your own runs live in the trial log, not here; your signatures appear as
 * dividers so the timeline reads whole. Native DOM for now; the cards become an island later. */
import { agentMark } from '../../../app/art.js';
import { T } from '../../../app/i18n';
import { agentConnection, onAgentConnection, onAgentEvent, runAction } from '../../../shell';
import { chip, codeDiff, flashDone, key, squares } from '../bits';
import { el, iconNode, workLang } from '../dom';
import {
  clock,
  listedExperiment,
  reproductionVerdict,
  settingsDiff,
  type DraftSummary,
  type ExperimentSummary,
  type Mark,
  type TicketDetail,
} from '../model';
import { arriveAll, byKeyboard, pulse } from '../motion';
import { lineRows, runMarks } from '../steps/tape';
import { go } from '../wire';
import { agentStatus, connectOffer, streamTarget } from './status';
import { mountStreamSlot } from './stream-slot';

export const AGENT_PROMPT = () =>
  T(
    '读 RoleCraft 里的工程委托，复现问题，试一个修法并起草提交；不要签字。',
    'Read the engineering ticket in RoleCraft, reproduce it, try a fix and draft a sign-off. Don’t sign.',
  );

type Item =
  | { kind: 'reproduce' | 'trial'; id: string; at: string; run: ExperimentSummary }
  | { kind: 'draft'; id: string; at: string; draft: DraftSummary }
  | { kind: 'signed'; id: string; at: string; n: number };

/** The panel on screen (one desk at a time). */
let active: AgentPanel | null = null;

/** A row of the live stream opened (205's TransmissionStream `onOpen`): the matching card opens
 * on the desk. Experiment and draft IDs are exact; a review opens its report; a ticket read
 * changes nothing on the desk. */
export function openCard(tool: string, objectId?: string) {
  const target = streamTarget(tool, objectId);
  if (target?.kind === 'review') go('engineer-review', target.id);
  else if (target && active?.element.isConnected) active.openItem(target.id);
}

type DraftItem = Extract<Item, { kind: 'draft' }>;
const isAgent = (kind: string | undefined) =>
  kind === 'external_agent' || kind === 'reference_agent';

export interface PanelContext {
  readonly doc: Document;
  notify(text: string): void;
  /** Open step ③ and put the person on the "actual change" column. */
  compare(): void;
  /** Something happened on the Agent's side: read the ticket again. */
  refresh(): void;
}

export class AgentPanel {
  readonly element: HTMLElement;
  private readonly status: HTMLElement;
  private readonly ring: HTMLElement;
  private readonly connect: HTMLElement;
  private readonly list: HTMLElement;
  private readonly more: HTMLButtonElement;
  private readonly live: HTMLElement;
  private ticket: TicketDetail | null = null;
  private readonly open = new Set<string>();
  private readonly seen = new Set<string>();
  private first = true;
  private showAll = false;
  private shown = '';
  private off: (() => void)[] = [];

  constructor(private readonly ctx: PanelContext) {
    active = this;
    const doc = ctx.doc;
    const mark = el(doc, 'span', { class: 'ed-agent__mark' });
    mark.insertAdjacentHTML('afterbegin', agentMark('sm'));
    this.ring = el(doc, 'span', { class: 'ed-agent__ring', 'aria-hidden': 'true' });
    mark.append(this.ring);
    this.status = el(doc, 'span', { class: 'ed-agent__status' });
    const copy = key(
      doc,
      T('复制给 Agent 的一句话', 'Copy a prompt for your agent'),
      'ghost',
      { id: 'ed-agent-prompt' },
      'copy',
    );
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(AGENT_PROMPT());
        flashDone(copy);
        ctx.notify(T('已复制。贴给你的 Agent。', 'Copied. Paste it to your agent.'));
      } catch {
        ctx.notify(AGENT_PROMPT());
      }
    });
    this.connect = el(doc, 'div', { class: 'ed-agent__connect' });
    // New cards are announced once, through the sr-only line below (not the list itself).
    this.list = el(doc, 'ol', { class: 'ed-cards' });
    this.more = el(doc, 'button', {
      type: 'button',
      class: 'ed-k is-ghost no-icon ed-cards__more',
      hidden: true,
    });
    this.more.addEventListener('click', () => {
      this.showAll = !this.showAll;
      this.draw();
    });
    this.live = el(doc, 'p', { class: 'sr-only', 'aria-live': 'polite' });
    this.element = el(
      doc,
      'section',
      {
        class: 'ed-agent',
        role: 'region',
        'aria-label': T('你的 Agent 做了什么', 'What your agent did'),
      },
      el(
        doc,
        'header',
        { class: 'ed-agent__head' },
        mark,
        el(
          doc,
          'div',
          { class: 'ed-agent__who' },
          el(doc, 'h2', { class: 'ed-agent__title' }, T('你的 Agent', 'Your agent')),
          this.status,
        ),
      ),
      el(
        doc,
        'div',
        { class: 'ed-agent__split' },
        el(
          doc,
          'p',
          { class: 'ed-agent__can' },
          el(doc, 'span', { class: 'ed-mini' }, T('它能', 'It can')),
          el(doc, 'span', {}, T('读委托 · 复现 · 试跑 · 起草', 'read · reproduce · trial · draft')),
        ),
        el(
          doc,
          'p',
          { class: 'ed-agent__only' },
          el(
            doc,
            'span',
            { class: 'ed-mini' },
            iconNode(doc, 'lock', 'i-xs'),
            T('只有你能', 'Only you'),
          ),
          el(doc, 'span', {}, T('签字', 'sign')),
        ),
      ),
      copy,
      this.connect,
      // 205's TransmissionStream (compact): the Agent's latest calls as they happen; a line opens
      // its card below. Hidden (label too) until there is a call.
      el(
        doc,
        'div',
        { class: 'ed-agent__live' },
        el(doc, 'h3', { class: 'ed-mini' }, T('它刚做的', 'Latest calls')),
        el(doc, 'div', {
          class: 'ed-agent__stream',
          'data-transmission-slot': 'engineer',
          'data-island': 'engineer-stream',
        }),
      ),
      el(doc, 'h3', { class: 'ed-mini ed-agent__handed' }, T('它交来的东西', 'What it handed in')),
      this.list,
      this.more,
      this.live,
    );
    this.attach();
  }

  /** On screen: the Agent's events, its connection and the grants reach this panel. */
  attach() {
    active = this;
    // The stream island follows the desk on screen (several desks may be kept off screen).
    mountStreamSlot(this.element);
    if (this.off.length) return;
    // An event that finds the panel off the page (left for a report or the board) detaches it.
    const onPage = (fn: () => void) => () => {
      if (this.element.isConnected) fn();
      else this.detach();
    };
    this.off.push(
      onAgentEvent(
        onPage(() => {
          pulse(this.ring);
          this.ctx.refresh();
        }),
      ),
      onAgentConnection(onPage(() => this.drawConnect())),
    );
    this.drawConnect();
  }

  /** Off screen: nothing reaches it until `attach`. */
  detach() {
    for (const off of this.off.splice(0)) off();
    if (active === this) active = null;
  }

  destroy() {
    this.detach();
  }

  /** Open one card (an experiment or a draft, by its ID) and bring it into view. */
  openItem(id: string): boolean {
    const items = this.items();
    const index = items.findIndex((i) => i.id === id);
    if (index < 0) return false;
    active = this;
    this.open.add(id);
    if (index >= 3) this.showAll = true;
    this.draw();
    let node = this.list.querySelector<HTMLElement>(`[data-item="${CSS.escape(id)}"]`);
    // A phone shows only the newest card: opening an older one shows them all.
    if (node && !node.getClientRects().length && !this.showAll) {
      this.showAll = true;
      this.draw();
      node = this.list.querySelector<HTMLElement>(`[data-item="${CSS.escape(id)}"]`);
    }
    node?.scrollIntoView({ block: 'nearest', behavior: byKeyboard() ? 'auto' : 'smooth' });
    node?.querySelector<HTMLElement>('.ed-card__head')?.focus({ preventScroll: true });
    return true;
  }

  update(ticket: TicketDetail) {
    this.ticket = ticket;
    this.drawStatus();
    this.drawConnect();
    this.draw();
  }

  private items(): Item[] {
    const t = this.ticket as TicketDetail;
    const items: Item[] = [];
    for (const run of t.trials)
      if (isAgent(run.executor.kind))
        items.push({ kind: run.kind, id: run.id, at: run.created_at, run });
    for (const draft of t.drafts)
      if (isAgent(draft.executor?.kind) && draft.created_at)
        items.push({ kind: 'draft', id: draft.id, at: draft.created_at, draft });
    t.reviews.forEach((r, i) => {
      items.push({ kind: 'signed', id: r.review_id, at: r.signed_at, n: i + 1 });
    });
    return items.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
  }

  /** The head says what the agent bus says (connected, idle since, waiting, not connected). */
  private drawStatus() {
    const status = agentStatus(agentConnection());
    const light = this.ctx.doc.createElement('span');
    light.className = 'rc-agent-light';
    light.dataset.state = status.state;
    light.setAttribute('aria-hidden', 'true');
    this.status.replaceChildren(light, this.ctx.doc.createTextNode(` ${status.text}`));
    this.element.dataset.connection = status.state;
  }

  /** Not connected: one sentence and "Connect", which goes to My agent (205's `open-agent`). Once
   * it has connected, nothing: its work shows up below. */
  private drawConnect() {
    this.drawStatus();
    const offer = connectOffer(agentConnection());
    const identity = JSON.stringify(offer);
    if (identity === this.shown) return;
    this.shown = identity;
    if (!offer) {
      this.connect.replaceChildren();
      return;
    }
    const doc = this.ctx.doc;
    const go = key(doc, offer.label, 'secondary', { id: 'ed-grant' }, 'spark');
    go.addEventListener('click', () => runAction(offer.action));
    this.connect.replaceChildren(el(doc, 'p', { class: 'ed-agent__invite' }, offer.lead), go);
  }

  private draw() {
    const doc = this.ctx.doc;
    const t = this.ticket;
    if (!t) return;
    const items = this.items();
    const writes = items.filter((i) => i.kind !== 'signed');
    const fresh = items.filter((i) => !this.seen.has(i.id));
    // The newest thing it handed in starts open; a new one opens itself.
    const newest = writes[0];
    if (newest && !this.seen.has(newest.id)) this.open.add(newest.id);
    if (!writes.length) {
      this.list.replaceChildren(
        el(
          doc,
          'li',
          { class: 'ed-cards__empty' },
          T(
            '还没有。它复现、试跑、起草的结果都会落在这里。',
            'Nothing yet. Its reproductions, trials and drafts land here.',
          ),
        ),
      );
      this.more.hidden = true;
    } else {
      // Wide: the latest three; a phone shows one (desk.css). "See all" opens the rest.
      const shown = this.showAll ? items : items.slice(0, 3);
      this.list.replaceChildren(...shown.map((item) => this.card_(item)));
      this.more.hidden = items.length <= 1;
      this.more.classList.toggle('is-few', items.length <= 3 && !this.showAll);
      this.more.replaceChildren(
        el(
          doc,
          'span',
          { class: 'ed-k__label' },
          this.showAll
            ? T('收起', 'Show fewer')
            : T(`看全部 ${items.length} 条`, `See all ${items.length}`),
        ),
      );
    }
    this.list.classList.toggle('is-all', this.showAll);
    if (!this.first && fresh.length && !byKeyboard()) {
      const nodes = fresh
        .map((i) => this.list.querySelector(`[data-item="${CSS.escape(i.id)}"]`))
        .filter((n): n is Element => !!n);
      arriveAll(nodes, -6);
      const write = fresh.find((i) => i.kind !== 'signed');
      if (write) this.live.textContent = this.announce(write);
    }
    for (const i of items) this.seen.add(i.id);
    this.first = false;
  }

  private announce(item: Item): string {
    const t = this.ticket as TicketDetail;
    if (item.kind === 'trial')
      return T(
        `你的 Agent 完成了试跑：公开 ${t.public_probes.length} 条通过 ${item.run.counts.passed ?? 0} 条。`,
        `Your agent ran a trial: ${item.run.counts.passed ?? 0} of ${t.public_probes.length} public checks passed.`,
      );
    if (item.kind === 'reproduce')
      return T('你的 Agent 复现了问题。', 'Your agent reproduced the problem.');
    if (item.kind === 'draft')
      return T('你的 Agent 交来一份草稿。', 'Your agent handed in a draft.');
    return '';
  }

  private card_(item: Item): HTMLElement {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    if (item.kind === 'signed')
      return el(
        doc,
        'li',
        { class: 'ed-cards__signed', 'data-item': item.id },
        el(
          doc,
          'span',
          {},
          T(
            `你签了字 · ${clock(item.at)} · 第 ${item.n} 次复核`,
            `You signed · ${clock(item.at)} · review ${item.n}`,
          ),
        ),
      );
    const open = this.open.has(item.id);
    const bodyId = `ed-card-${item.id}`;
    const verb =
      item.kind === 'trial'
        ? T('试跑', 'Trial')
        : item.kind === 'reproduce'
          ? T('复现', 'Reproduced')
          : T('起草提交', 'Drafted a sign-off');
    let summary: Node | string = '';
    if (item.kind === 'reproduce') {
      const v = reproductionVerdict(item.run, t);
      summary = chip(doc, v.label, v.tone);
    } else if (item.kind === 'trial') {
      summary = el(
        doc,
        'span',
        { class: 'ed-card__tally' },
        squares(doc, runMarks(item.run, listedExperiment(item.run, t.id), t.public_probes.length)),
        T(
          `公开 ${item.run.counts.passed ?? 0}/${t.public_probes.length}`,
          `Public ${item.run.counts.passed ?? 0}/${t.public_probes.length}`,
        ),
      );
    } else {
      const n = (item as DraftItem).draft.changed_fields?.length ?? 0;
      summary = el(
        doc,
        'span',
        { class: 'ed-meta' },
        T(`改 ${n} 处`, `${n} ${n === 1 ? 'setting' : 'settings'}`),
      );
    }
    const head = el(
      doc,
      'button',
      {
        type: 'button',
        class: 'ed-card__head',
        id: `${bodyId}-h`,
        'aria-expanded': String(open),
        'aria-controls': bodyId,
      },
      el(doc, 'time', { class: 'ed-card__time', datetime: item.at }, clock(item.at)),
      el(doc, 'span', { class: 'ed-card__verb' }, verb),
      el(doc, 'span', { class: 'ed-card__sum' }, summary),
      iconNode(doc, 'down', 'i-xs'),
    );
    head.addEventListener('click', () => {
      if (this.open.has(item.id)) this.open.delete(item.id);
      else this.open.add(item.id);
      this.draw();
      (doc.getElementById(`${bodyId}-h`) as HTMLElement | null)?.focus();
    });
    head.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      const heads = [...this.list.querySelectorAll<HTMLElement>('.ed-card__head')];
      const i = heads.indexOf(head);
      const next = heads[i + (e.key === 'ArrowDown' ? 1 : -1)];
      if (next) {
        e.preventDefault();
        next.focus();
      }
    });
    const body = el(doc, 'div', { class: 'ed-card__body', id: bodyId, hidden: !open });
    if (open) body.append(this.cardBody(item));
    return el(
      doc,
      'li',
      { class: 'ed-card', 'data-item': item.id, 'data-kind': item.kind },
      head,
      body,
    );
  }

  private cardBody(item: Exclude<Item, { kind: 'signed' }>): Node {
    const doc = this.ctx.doc;
    const t = this.ticket as TicketDetail;
    const lang = workLang(t.work_language);
    if (item.kind === 'reproduce') {
      const v = reproductionVerdict(item.run, t);
      return el(
        doc,
        'p',
        { class: 'ed-card__line' },
        T('你的 Agent 复现了：', 'Your agent reproduced it: '),
        v.sentence,
      );
    }
    if (item.kind === 'trial') {
      const rows = item.run.changes
        ? settingsDiff(t.baseline_config, item.run.changes, t.editable_fields)
        : [];
      return el(
        doc,
        'div',
        {},
        rows.length
          ? codeDiff(doc, rows)
          : (item.run.changed_fields ?? []).length
            ? el(
                doc,
                'p',
                { class: 'ed-card__line' },
                el(
                  doc,
                  'code',
                  { class: 'ed-key', lang: 'en' },
                  (item.run.changed_fields ?? []).join(' · '),
                ),
                T(' · 新值在你的 Agent 那里', ' · the new values are with your agent'),
              )
            : el(
                doc,
                'p',
                { class: 'ed-card__line' },
                T('用的是委托基线设置。', 'It ran the ticket’s baseline settings.'),
              ),
        el(
          doc,
          'p',
          { class: 'ed-card__line ed-card__result' },
          squares(
            doc,
            runMarks(item.run, listedExperiment(item.run, t.id), t.public_probes.length) as Mark[],
          ),
          T(
            `公开 ${item.run.counts.passed ?? 0}/${t.public_probes.length} 通过`,
            `Public ${item.run.counts.passed ?? 0}/${t.public_probes.length} passed`,
          ),
        ),
        lineRows(doc, t, item.run, listedExperiment(item.run, t.id), []),
      );
    }
    const draft = (item as DraftItem).draft;
    const latest = t.latest_draft?.id === item.id ? t.latest_draft : null;
    const actual = latest
      ? Object.keys(latest.changes).length
      : (draft.changed_fields?.length ?? 0);
    const stated = latest ? latest.change_statements.length : null;
    const compare = key(
      doc,
      T('去签字单对照', 'Compare on the sign-off sheet'),
      'ghost',
      { class: 'ed-card__compare' },
      'chev',
    );
    compare.addEventListener('click', () => this.ctx.compare());
    const signed = t.reviews.some((r) => r.draft_id === item.id);
    return el(
      doc,
      'div',
      {},
      el(
        doc,
        'blockquote',
        { class: 'ed-card__quote', lang },
        latest?.explanation ?? draft.explanation_summary ?? '',
      ),
      el(
        doc,
        'p',
        { class: 'ed-card__line' },
        stated === null
          ? T(`实际改动 ${actual} 处`, `Actually changes ${actual}`)
          : T(
              `实际改动 ${actual} 处 · 说明里写 ${stated} 处`,
              `Actually changes ${actual} · the description lists ${stated}`,
            ),
        signed ? el(doc, 'span', { class: 'ed-meta' }, T(' · 已签', ' · signed')) : null,
      ),
      latest && !signed ? compare : null,
    );
  }
}
