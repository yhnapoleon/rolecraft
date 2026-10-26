import {
  currentModeNotice,
  presentReply,
  type GenerationMode,
  type RoleMode,
} from './reply-presentation';
/** Native v4 colleague slot. The injected client owns API calls, journals and jobs. */
import { T, locale, onLocaleChange } from '../../app/i18n';
import { markdownNodes } from '../../app/markdown';
import { PERSON_OF_ROLE } from '../../app/people.js';
import { OPENER } from '../../app/vocab.js';
import type { RecognitionRecord } from '../recognition-native/badge';
import { lensOn, onLensChange } from '../recognition-native/lens';
import { renderSignals } from '../recognition-native/signals';
import {
  dropEmphasis,
  evidenceBySource,
  isLocalReply,
  localRoleLine,
  localRows,
  noticeKind,
  localGist,
  replyParts,
  splitCitations,
  type Cite,
} from './chat-model';
import {
  avatarNode,
  deliveryLine,
  glyph,
  noticeRow,
  noticeText,
  paperTag,
  peekNode,
  replyBubble,
  replyingRow,
} from './chat-view';
import { knownTurns, outgoing, outgoingListeners, threadKey } from './chat-memory';
import './roles.css';

export type RoleId = 'supervisor' | 'business_lead' | 'tech_lead';
export type WorkLanguage = 'zh' | 'en';
export type TurnStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'needs_context'
  | 'paused'
  | 'cancelled'
  | 'unknown';
export interface MaterialReference {
  id: string;
  title: string;
  version: number;
}
export interface Colleague {
  id: RoleId;
  name: string;
  available: boolean;
}
export interface ConversationTurn {
  id: string;
  roleId: RoleId;
  question: string;
  status: TurnStatus;
  reply?: string;
  materials?: readonly MaterialReference[];
  omissionCount?: number;
  receivedVersionsOnly?: boolean;
  generationMode?: GenerationMode;
  stale?: boolean;
  /** Only a learner-safe explanation already projected by the real client. */
  explanation?: string;
  canRetry?: boolean;
  canRefresh?: boolean;
  canRecordDisplay?: boolean;
  displayRecorded?: boolean; // Public server receipt, never inferred from a read.
  /** Intent and grounding-check signatures saved on the reply (recognition layer). */
  recognition?: RecognitionRecord[];
  /** Source text the reply repeats word for word, as verified by the server (`spoken_evidence`). */
  evidence?: readonly string[];
  /** Why the job ended without a reply, when the server says (only shown as plain words). */
  errorCode?: string;
}
/** Presentation data, not a new server schema. Never pass private audit objects. */
export interface RolesView {
  sessionId: string;
  workLanguage: WorkLanguage;
  mode: RoleMode;
  colleagues: readonly Colleague[];
  turns: readonly ConversationTurn[];
  canSend: boolean;
  restriction?: string;
  /** The existing durable client journal still has an unconfirmed operation. */
  unconfirmed?: boolean;
}
export interface RolesNativeAdapter {
  /** Return the current public projection for this one fixed session. */
  read(): Promise<RolesView>;
  /** Resolve only after the existing client has confirmed/journalled acceptance. */
  send(input: { roleId: RoleId; text: string }): Promise<void>;
  /** Recover the client's original request; never mint a replacement command. */
  recover(): Promise<void | { confirmed: { roleId: RoleId; text: string } }>;
  retry?(turnId: string): Promise<void>;
  refreshContext?(turnId: string): Promise<void>;
  openMaterial?(material: MaterialReference): void | Promise<void>;
  /** Map a visibly painted reply to the existing idempotent display command.
   * Supply only when authorized; journal/recovery remain with the shared client.
   */
  recordDisplay?(turnId: string): Promise<void>;
  subscribe?(changed: () => void): () => void;
  drafts?: { read(role: RoleId): string; write(role: RoleId, value: string): void };
}
export interface RolesNativeHandle {
  refresh(): Promise<void>;
  destroy(): void;
}
export interface RolesMountOptions {
  surface?: 'standalone' | 'v4-history';
  roleId?: RoleId;
  /** The practice the thread belongs to, when the host knows it before the first read. */
  sessionId?: string;
}

const ROLES: readonly RoleId[] = ['supervisor', 'business_lead', 'tech_lead'];
const roleTitle = (id: RoleId) =>
  ({
    supervisor: T('经理', 'Manager'),
    business_lead: T('业务负责人', 'Business lead'),
    tech_lead: T('技术负责人', 'Technical lead'),
  })[id];
/* What this page remembers of each thread (per practice and colleague) while the shell redraws
   the rail and the thread is mounted again: what was already shown (only later arrivals move),
   the last view (no "loading" flash), which replies are open, the passage shown, and the scroll. */
interface ThreadMemory {
  questions: Set<string>;
  replies: Set<string>;
  waiting: Set<string>;
  expanded: Set<string>;
  peek?: { turnId: string; label: string };
  view?: RolesView;
  top: number;
  atBottom: boolean;
  /** When this thread was last on screen; a remount within moments continues the same look. */
  aliveAt: number;
}
const threads = new Map<string, ThreadMemory>();
const memoryOf = (key: string) => {
  let memory = threads.get(key);
  if (!memory) {
    memory = {
      questions: new Set(),
      replies: new Set(),
      waiting: new Set(),
      expanded: new Set(),
      top: 0,
      atBottom: true,
      aliveAt: 0,
    };
    threads.set(key, memory);
  }
  return memory;
};
/** A redraw of the rail remounts the thread; within this long it is the same look continuing. */
const RESUME_MS = 4000;
/** Space under the header when following lands on a long reply's question (or the reply). */
const FOLLOW_GAP = 16;

const reducedMotion = (doc: Document) =>
  !!doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
/** A new message settles in: the colleague's from the thread, yours from the composer. */
function enter(node: HTMLElement, side: 'them' | 'mine') {
  if (typeof node.animate !== 'function') return;
  const doc = node.ownerDocument;
  if (reducedMotion(doc)) {
    node.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: 'ease' });
    return;
  }
  const ease =
    (doc.defaultView && getComputedStyle(node).getPropertyValue('--ease-out').trim()) ||
    'cubic-bezier(0.23, 1, 0.32, 1)';
  node.animate(
    side === 'them'
      ? [
          { opacity: 0, transform: 'translateY(8px) scale(0.985)' },
          { opacity: 1, transform: 'none' },
        ]
      : [
          { opacity: 0, transform: 'translateY(10px) scale(0.97)' },
          { opacity: 1, transform: 'none' },
        ],
    // The 280ms tier of frontend-style §3.5; both sides move the same length of time.
    { duration: 280, easing: ease },
  );
}

export function mount(
  container: HTMLElement,
  adapter: RolesNativeAdapter,
  options: RolesMountOptions = {},
): RolesNativeHandle {
  const historyOnly = options.surface === 'v4-history';
  if (historyOnly && (!options.roleId || !ROLES.includes(options.roleId)))
    throw new Error('A v4 colleague is required');
  const doc = container.ownerDocument;
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string) => {
    const node = doc.createElement(tag);
    if (cls) node.className = cls;
    return node;
  };
  const button = (cls?: string) => {
    const node = el('button', cls);
    node.type = 'button';
    return node;
  };
  const root = el('section', 'rc-roles');
  root.dataset.rolePanel = '';
  if (historyOnly) root.classList.add('rc-roles--v4-history');
  const header = el('header', 'rc-roles__header');
  const heading = el('h2');
  const language = el('span', 'rc-roles__language');
  const reload = button('rc-roles__text-button');
  reload.dataset.action = 'reload';
  header.append(heading, language, reload);
  const mode = el('p', 'rc-roles__mode');
  mode.setAttribute('role', 'note');
  const notice = el('p', 'rc-roles__notice');
  notice.setAttribute('role', 'status');
  notice.setAttribute('aria-live', 'polite');
  const recover = button('rc-roles__text-button');
  recover.dataset.action = 'recover';
  const layout = el('div', 'rc-roles__layout');
  const nav = el('nav', 'rc-roles__people');
  const main = el('div', 'rc-roles__main');
  const activeName = el('h3');
  const list = el('ol', 'rc-roles__conversation');
  /** A message on its way, before the conversation has it. */
  const pendingBox = el('div', 'rc-roles__outgoing');
  const empty = el('div', 'rc-roles__empty');
  const form = el('form', 'rc-roles__composer');
  const label = el('label');
  const textarea = el('textarea');
  textarea.rows = 4;
  textarea.maxLength = 12000;
  textarea.dataset.roleQuestion = '';
  const inputId = 'role-question-' + crypto.randomUUID();
  textarea.id = inputId;
  label.htmlFor = inputId;
  const actions = el('div', 'rc-roles__actions');
  const hint = el('span', 'rc-roles__hint');
  const send = el('button', 'rc-roles__send');
  send.type = 'submit';
  send.dataset.action = 'send';
  actions.append(hint, send);
  form.append(label, textarea, actions);
  if (historyOnly) {
    // v4 owns the colleague header, navigation, composer and scroll region.
    main.append(list, pendingBox, empty);
    layout.append(main);
    root.append(mode, notice, recover, reload, layout);
  } else {
    main.append(activeName, list, pendingBox, empty, form);
    layout.append(nav, main);
    root.append(header, mode, notice, recover, layout);
  }
  container.append(root);

  let selected: RoleId = options.roleId ?? 'supervisor';
  let view: RolesView | undefined;
  let sessionId: string | undefined;
  let loaded = false;
  let busy = false;
  let uncertain = false;
  let destroyed = false;
  let loadTicket = 0;
  let feedback: 'read' | 'unconfirmed' | 'action' | 'draft' | undefined;
  const drafts = new Map<RoleId, string>();
  const people = new Map<RoleId, HTMLButtonElement>();
  const displayAttempts = new Set<string>();
  // Open replies belong to the thread, not to this mount (the rail redraw remounts it).
  let expandedReplies = new Set<string>();
  const visibleReplies = new Map<HTMLElement, { turnId: string; visible: boolean }>();
  /** This mount has read the conversation itself (a remembered view is only what was on screen). */
  let readHere = false;
  const markDisplayed = (node: HTMLElement) => {
    const entry = visibleReplies.get(node);
    if (
      !adapter.recordDisplay ||
      !readHere ||
      !entry?.visible ||
      destroyed ||
      doc.visibilityState !== 'visible'
    )
      return;
    const key = sessionId + ':' + entry.turnId;
    if (displayAttempts.has(key)) return;
    requestAnimationFrame(() => {
      if (
        destroyed ||
        !node.isConnected ||
        !visibleReplies.get(node)?.visible ||
        doc.visibilityState !== 'visible' ||
        displayAttempts.has(key)
      )
        return;
      for (let parent: HTMLElement | null = node; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (
          style.display === 'none' ||
          style.visibility === 'hidden' ||
          Number(style.opacity) === 0
        )
          return;
      }
      // At most one automatic attempt in this mount. A failure is recovered via
      // the shared original request journal, never by a render/observer retry.
      displayAttempts.add(key);
      void Promise.resolve()
        .then(() => adapter.recordDisplay!(entry.turnId))
        .catch(() => {
          if (!destroyed) {
            feedback = 'action';
            render();
          }
        });
    });
  };
  const displayObserver =
    adapter.recordDisplay && typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver((entries) => {
          for (const entry of entries) {
            const node = entry.target as HTMLElement;
            const tracked = visibleReplies.get(node);
            if (!tracked) continue;
            tracked.visible = entry.isIntersecting && entry.intersectionRatio > 0;
            markDisplayed(node);
          }
        })
      : undefined;
  const onVisibility = () => {
    if (doc.visibilityState === 'visible')
      for (const node of visibleReplies.keys()) markDisplayed(node);
  };
  doc.addEventListener('visibilitychange', onVisibility);

  const draft = (id: RoleId) => {
    if (!drafts.has(id)) {
      try {
        drafts.set(id, adapter.drafts?.read(id) ?? '');
      } catch {
        drafts.set(id, '');
        feedback = 'draft';
      }
    }
    return drafts.get(id)!;
  };
  const keepDraft = (id: RoleId, value: string) => {
    drafts.set(id, value);
    try {
      adapter.drafts?.write(id, value);
      if (feedback === 'draft') feedback = undefined;
    } catch {
      feedback = 'draft';
    }
  };
  for (const id of ROLES) {
    const item = button('rc-roles__person');
    item.dataset.role = id;
    item.addEventListener('click', () => {
      selected = id;
      textarea.value = draft(id);
      // Another colleague is another thread with its own memory.
      memory = undefined;
      painted = false;
      peek = undefined;
      expandedReplies = new Set();
      render();
    });
    people.set(id, item);
    nav.append(item);
  }
  if (!historyOnly) textarea.value = draft(selected);

  function canSend() {
    return (
      loaded &&
      !busy &&
      !uncertain &&
      !view?.unconfirmed &&
      view?.canSend &&
      view.mode !== 'unavailable' &&
      view.colleagues.some((c) => c.id === selected && c.available) &&
      !!textarea.value.trim()
    );
  }

  /* ---------- the thread ---------- */
  let peek: { turnId: string; label: string } | undefined;
  let painted = false;
  let resumed = false;
  let lastCounts = '';
  let memory: ThreadMemory | undefined;
  /** Bind this mount to its thread's memory once the practice is known. */
  const remember = () => {
    if (!sessionId || memory) return memory;
    memory = memoryOf(threadKey(sessionId, selected));
    resumed = Date.now() - memory.aliveAt < RESUME_MS;
    expandedReplies = memory.expanded;
    if (resumed) peek = memory.peek;
    return memory;
  };
  const built = new Map<
    string,
    { signature: string; node: HTMLLIElement; observe?: HTMLElement }
  >();
  const scroller = () => (historyOnly ? (root.parentElement ?? root) : (list as HTMLElement));
  /** Where following the conversation lands: the end, or, when the latest reply is taller than
   * the view, its question in full just under the header with the reply's start below it. A
   * question taller than a third of the view gives way to the reply's start, scrolled fully out
   * of sight rather than left as a sliver. */
  const followTop = (box: HTMLElement) => {
    const last = list.lastElementChild;
    const reply = last?.querySelector<HTMLElement>('.rc-msg--them');
    if (!reply || last?.querySelector('.rc-typing')) return box.scrollHeight;
    if (reply.offsetHeight <= box.clientHeight - 2 * FOLLOW_GAP) return box.scrollHeight;
    const boxTop = box.getBoundingClientRect().top;
    const at = (node: HTMLElement) => box.scrollTop + node.getBoundingClientRect().top - boxTop;
    const question = last?.querySelector<HTMLElement>('.rc-msg--mine');
    if (question && question.offsetHeight <= box.clientHeight / 3)
      return Math.max(0, at(question) - FOLLOW_GAP);
    const questionEnd = question ? at(question) + question.offsetHeight : 0;
    return Math.max(0, questionEnd, at(reply) - FOLLOW_GAP);
  };
  /** Scrolls made here, so the scroll listener does not mistake them for your own reading. */
  let placingUntil = 0;
  const actionButton = (
    title: string,
    name: string,
    focus: string,
    invoke: () => Promise<void>,
  ) => {
    const control = button('rc-roles__text-button rc-sys__action');
    control.textContent = title;
    control.dataset.action = name;
    control.dataset.focus = focus;
    control.disabled = busy || !loaded || uncertain || !!view?.unconfirmed;
    control.addEventListener('click', () => {
      void perform(invoke);
    });
    return control;
  };
  const openSource = (ref: MaterialReference) => {
    Promise.resolve()
      .then(() => adapter.openMaterial!(ref))
      .catch(() => {
        if (!destroyed) {
          feedback = 'action';
          render();
        }
      });
  };
  const togglePeek = (turnId: string, label: string) => {
    peek = peek?.turnId === turnId && peek.label === label ? undefined : { turnId, label };
    render();
  };
  /** The toggle after a long reply's first paragraphs; the rest opens below them. */
  const moreToggle = (
    turn: ConversationTurn,
    rest: HTMLElement,
    open: boolean,
    count: number,
    label?: string,
  ) => {
    const toggle = button('rc-roles__more');
    toggle.dataset.focus = `more:${turn.id}`;
    rest.id = `rc-rest-${crypto.randomUUID()}`;
    toggle.setAttribute('aria-controls', rest.id);
    toggle.setAttribute('aria-expanded', String(open));
    const text = el('span');
    text.textContent = open
      ? T('收起', 'Show less')
      : label
        ? label
        : count > 0
          ? T(`展开全文 · 还有 ${count} 段`, `Show the full reply · ${count} more`)
          : T('展开全文', 'Show the full reply');
    toggle.append(text, glyph(doc, 'chevron', 12));
    toggle.addEventListener('click', () => {
      if (expandedReplies.has(turn.id)) expandedReplies.delete(turn.id);
      else expandedReplies.add(turn.id);
      render();
    });
    return toggle;
  };
  const rowText = (text: string, cls: string) => {
    const node = el('div', `${cls} rc-roles__md`);
    node.append(...markdownNodes(doc, text));
    return node;
  };

  /** One question and what came of it, as two message groups (yours, then the colleague's). */
  function buildTurn(turn: ConversationTurn, last: boolean, name: string) {
    const item = el('li', 'rc-roles__turn');
    item.dataset.turnId = turn.id;
    let observe: HTMLElement | undefined;
    const mine = el('div', 'rc-msg rc-msg--mine');
    const asked = el('div', 'rc-bubble rc-bubble--mine rc-roles__question');
    const you = el('span', 'sr-only');
    you.textContent = T('你：', 'You: ');
    asked.append(you, turn.question);
    mine.append(asked);
    item.append(mine);
    const kind =
      turn.status === 'completed' && turn.reply !== undefined
        ? 'reply'
        : noticeKind(turn.status, turn.errorCode);
    // On the server, so it was sent; nobody knows whether it was read.
    if (last && kind !== 'reply' && kind !== 'failed' && kind !== 'held')
      mine.append(deliveryLine(doc, 'sent'));
    if (kind === 'typing') {
      item.append(replyingRow(doc, selected));
      return { item, kind };
    }
    if (kind !== 'reply') {
      const action =
        (kind === 'failed' || kind === 'held') && turn.canRetry && adapter.retry
          ? actionButton(
              kind === 'held' ? T('请对方重新回答', 'Ask again') : T('再试一次', 'Try again'),
              'retry',
              `retry:${turn.id}`,
              () => adapter.retry?.(turn.id) ?? Promise.resolve(),
            )
          : kind === 'context' && turn.canRefresh && adapter.refreshContext
            ? actionButton(
                T('确认新材料并继续', 'Confirm updated materials'),
                'refresh-context',
                `refresh:${turn.id}`,
                () => adapter.refreshContext?.(turn.id) ?? Promise.resolve(),
              )
            : undefined;
      item.append(noticeRow(doc, kind, turn.explanation || noticeText(kind, selected, turn.errorCode), action));
      return { item, kind };
    }
    const reply = turn.reply ?? '';
    const presentation = presentReply(reply, {
      generationMode: turn.generationMode,
      receivedVersionsOnly: turn.receivedVersionsOnly,
      omissionCount: turn.omissionCount,
    });
    const materials = turn.materials ?? [];
    const materialOf = (cite: Cite) =>
      materials.find((m) => m.title === cite.title && m.version === cite.version);
    const open = expandedReplies.has(turn.id);
    const them = el('div', 'rc-msg rc-msg--them');
    const body = el('div', 'rc-roles__reply');
    const said = el('span', 'sr-only');
    said.textContent = name + T('：', ': ');
    body.append(said);
    const extra = el('div', 'rc-msg__extra');
    const rest = el('div', 'rc-roles__rest');
    rest.hidden = !open;
    const local = turn.generationMode === 'local' || isLocalReply(reply);
    if (local) {
      // Excerpts quoted by rules: one dashed bubble that opens with a sentence a person can read;
      // every passage, each under its own small tag, folds away as the evidence behind it.
      const bubble = el('div', 'rc-bubble rc-bubble--them rc-bubble--local is-first');
      const status = el('p', 'rc-local__status rc-roles__status');
      status.textContent = T(
        '资料摘录（未接入对话模型）',
        'Source excerpts (no conversation model connected)',
      );
      bubble.append(status);
      const rows = localRows(reply);
      const row = (r: (typeof rows)[number], first: boolean) => {
        if (r.kind === 'excerpt') {
          const line = el('div', 'rc-local__row');
          const ref = materialOf(r.cite);
          line.append(
            paperTag(doc, r.cite, {
              mini: true,
              onPress: ref && adapter.openMaterial ? () => openSource(ref) : undefined,
            }),
            rowText(r.text, `rc-local__text${first ? ' rc-roles__preview' : ''}`),
          );
          return line;
        }
        if (r.kind === 'others') {
          const line = el('div', 'rc-local__row rc-local__others');
          const lead = el('span', 'rc-local__lead');
          lead.textContent = T('其余可参考：', 'Also available:');
          line.append(lead);
          for (const cite of r.cites) {
            const ref = materialOf(cite);
            line.append(
              paperTag(doc, cite, {
                mini: true,
                onPress: ref && adapter.openMaterial ? () => openSource(ref) : undefined,
              }),
            );
          }
          return line;
        }
        const line = el('p', `rc-local__none${first ? ' rc-roles__preview' : ''}`);
        line.textContent = r.text;
        return line;
      };
      const gist = localGist(rows);
      if (gist) {
        const line = el('p', 'rc-local__gist rc-roles__preview');
        line.textContent = gist;
        bubble.append(line);
      }
      for (const r of rows) rest.append(row(r, false));
      const evidence = rows.filter((r) => r.kind === 'excerpt').length;
      const role = localRoleLine(reply);
      if (role) {
        const line = el('p', 'rc-local__role');
        line.textContent = role;
        rest.append(line);
      }
      if (rest.childElementCount) {
        bubble.append(rest);
        extra.append(
          moreToggle(
            turn,
            rest,
            open,
            evidence,
            evidence
              ? T(`依据 ${evidence} 条`, `Evidence · ${evidence}`)
              : T('展开详情', 'Show details'),
          ),
        );
      }
      body.append(bubble);
      observe = rest.childElementCount ? rest : bubble;
    } else {
      // The colleague's own words, a few messages long; source tags leave the sentences.
      const { text, cites } = splitCitations(reply, view?.workLanguage ?? 'zh');
      const parts = replyParts(dropEmphasis(text));
      parts.shown.forEach((part, i) => {
        body.append(replyBubble(doc, part, i === 0 ? 'is-first rc-roles__preview' : 'is-cont'));
      });
      for (const part of parts.folded) rest.append(replyBubble(doc, part, 'is-cont'));
      if (parts.folded.length) {
        body.append(rest);
        extra.append(moreToggle(turn, rest, open, parts.folded.length));
      }
      observe = parts.folded.length ? rest : body;
      // The source tags: each cited material once, at the end of the group.
      const tags: { cite: Cite; ref: MaterialReference }[] = [];
      for (const cite of cites) {
        const ref = materialOf(cite);
        if (ref && !tags.some((t) => t.ref === ref)) tags.push({ cite, ref });
      }
      for (const ref of materials)
        if (!tags.some((t) => t.ref === ref))
          tags.push({
            cite: {
              label: `${ref.title} · v${ref.version}`,
              title: ref.title,
              version: ref.version,
            },
            ref,
          });
      const quotes = evidenceBySource(reply, turn.evidence ?? []);
      if (tags.length) {
        const row = el('div', 'rc-tags');
        row.setAttribute('aria-label', T('引用的资料', 'Cited materials'));
        for (const { cite, ref } of tags) {
          const quote = quotes.get(cite.label);
          const expanded = peek?.turnId === turn.id && peek.label === cite.label;
          const tag = paperTag(doc, cite, {
            peek: !!quote,
            expanded,
            onPress: quote
              ? () => togglePeek(turn.id, cite.label)
              : adapter.openMaterial
                ? () => openSource(ref)
                : undefined,
          });
          tag.dataset.focus = `tag:${turn.id}:${cite.label}`;
          row.append(tag);
        }
        extra.append(row);
        const peeked = peek?.turnId === turn.id ? peek.label : undefined;
        const shown = peeked ? tags.find((t) => t.cite.label === peeked) : undefined;
        const quote = shown && quotes.get(shown.cite.label);
        if (shown && quote) {
          const id = `rc-peek-${crypto.randomUUID()}`;
          row.querySelector<HTMLElement>(`[data-peek]`)?.setAttribute('aria-controls', id);
          extra.append(
            peekNode(doc, shown.cite, quote, {
              id,
              openFull: adapter.openMaterial ? () => openSource(shown.ref) : undefined,
            }),
          );
        }
      }
    }
    // Limits that change what the reply could say, in small type after it.
    const notes = [
      presentation.versionNote,
      presentation.omissionNote,
      turn.stale
        ? T(
            '引用包含旧版本；原回复按当时记录保留。',
            'Citations include an older version; the original reply is retained.',
          )
        : undefined,
    ].filter((note): note is string => !!note);
    for (const note of notes) {
      const line = el('p', 'rc-roles__limitation');
      line.textContent = note;
      extra.append(line);
    }
    const signals = renderSignals(doc, turn.recognition, locale(), {
      context: 'reply',
      lens: lensOn(),
      cards: {},
    });
    if (signals) extra.append(signals);
    them.append(avatarNode(doc, selected), body);
    if (extra.childElementCount) them.append(extra);
    item.append(them);
    return { item, kind, observe };
  }

  /** Paint the turns, keeping unchanged ones in place so focus, scroll and motion hold still. */
  function paintThread(turns: readonly ConversationTurn[]) {
    const box = scroller();
    const fromBottom = box.scrollHeight - box.scrollTop - box.clientHeight;
    const height = box.scrollHeight;
    const active = doc.activeElement as HTMLElement | null;
    const focusKey = active && root.contains(active) ? active.dataset.focus : undefined;
    displayObserver?.disconnect();
    visibleReplies.clear();
    const name = view?.colleagues.find((c) => c.id === selected)?.name || roleTitle(selected);
    const key = sessionId ? threadKey(sessionId, selected) : undefined;
    if (key && loaded) knownTurns.set(key, turns);
    const seen = loaded ? remember() : undefined;
    // Opening a thread shows it as it is; only what arrives while you look moves in.
    const baseline = !!seen && !painted && !resumed;
    // The message on its way gives way to the real turn as soon as the conversation has it.
    const sending = key ? outgoing.get(key) : undefined;
    if (sending && key && loaded) {
      const asking = turns.filter((t) => t.question === sending.text);
      if (asking.length > sending.before) {
        outgoing.delete(key);
        const newest = asking.at(-1);
        if (sending.shown && newest) seen?.questions.add(newest.id);
      }
    }
    const animations: [HTMLElement, 'them' | 'mine'][] = [];
    const lastId = turns.at(-1)?.id;
    const nodes = turns.map((turn) => {
      const last = turn.id === lastId;
      const signature = JSON.stringify([
        turn,
        last,
        expandedReplies.has(turn.id),
        peek?.turnId === turn.id ? peek.label : '',
        busy || !loaded || uncertain || !!view?.unconfirmed,
        locale(),
        lensOn(),
        !!adapter.openMaterial,
      ]);
      const cached = built.get(turn.id);
      if (cached?.signature === signature) {
        if (cached.observe) track(cached.observe, turn);
        return cached.node;
      }
      const made = buildTurn(turn, last, name);
      built.set(turn.id, { signature, node: made.item, observe: made.observe });
      if (made.observe) track(made.observe, turn);
      if (seen && !baseline) {
        if (!seen.questions.has(turn.id)) {
          const group = made.item.querySelector<HTMLElement>('.rc-msg--mine');
          if (group) animations.push([group, 'mine']);
        }
        if (made.kind === 'reply' && !seen.replies.has(turn.id)) {
          const group = made.item.querySelector<HTMLElement>('.rc-msg--them');
          if (group) animations.push([group, 'them']);
        }
        if (made.kind === 'typing' && !seen.waiting.has(turn.id)) {
          const row = made.item.querySelector<HTMLElement>('.rc-typing');
          if (row) animations.push([row, 'them']);
        }
      }
      if (seen) {
        seen.questions.add(turn.id);
        if (made.kind === 'reply') seen.replies.add(turn.id);
        if (made.kind === 'typing') seen.waiting.add(turn.id);
      }
      return made.item;
    });
    for (const id of [...built.keys()]) if (!turns.some((t) => t.id === id)) built.delete(id);
    // Patch in place: an unchanged turn keeps its node and position.
    nodes.forEach((node, i) => {
      if (list.children[i] !== node) list.insertBefore(node, list.children[i] ?? null);
    });
    while (list.children.length > nodes.length) list.lastElementChild?.remove();
    // The message on its way.
    const pending = key ? outgoing.get(key) : undefined;
    if (pending) {
      const signature = `${pending.text}:${pending.state}`;
      if (pendingBox.dataset.signature !== signature) {
        pendingBox.dataset.signature = signature;
        const group = el('div', 'rc-msg rc-msg--mine');
        const bubble = el('div', 'rc-bubble rc-bubble--mine');
        bubble.textContent = pending.text;
        group.append(bubble, deliveryLine(doc, pending.state));
        pendingBox.replaceChildren(group);
        if (!pending.shown) {
          pending.shown = true;
          animations.push([group, 'mine']);
        }
      }
    } else if (pendingBox.childElementCount) {
      pendingBox.replaceChildren();
      delete pendingBox.dataset.signature;
    }
    if (focusKey && !root.contains(doc.activeElement))
      [...root.querySelectorAll<HTMLElement>('[data-focus]')]
        .find((n) => n.dataset.focus === focusKey)
        ?.focus({ preventScroll: true });
    // Scroll and motion wait until the rest of the panel (notices, the empty state) is set.
    return () => {
      // Follow the conversation while you are at its end, when something new arrives; opening a
      // long reply or a passage never moves you, and reading above is never pulled back down.
      const counts = [
        turns.length,
        turns.filter((t) => t.reply !== undefined).length,
        turns.filter((t) => t.status === 'queued' || t.status === 'running').length,
        pending ? 1 : 0,
      ].join(':');
      const arrived = counts !== lastCounts && box.scrollHeight > height;
      lastCounts = counts;
      // "Following" is kept in memory: being placed at a long reply's start still follows.
      const following = memory ? memory.atBottom : fromBottom < 48;
      const follow = painted
        ? (arrived && (fromBottom < 48 || following)) || !!(pending && animations.length)
        : !resumed || !memory || memory.atBottom;
      if (loaded && follow) {
        const smooth = painted && !reducedMotion(doc);
        const top = followTop(box);
        placingUntil = Date.now() + (smooth ? 800 : 100);
        if (box.scrollTo) box.scrollTo({ top, behavior: smooth ? 'smooth' : 'auto' });
        else box.scrollTop = top;
        if (memory) {
          memory.top = top;
          memory.atBottom = true;
        }
      } else if (loaded && !painted && memory) {
        box.scrollTop = memory.top;
      }
      if (loaded) {
        painted = true;
        if (memory) {
          memory.aliveAt = Date.now();
          memory.peek = peek;
          if (view) memory.view = view;
        }
      }
      for (const [node, side] of animations) enter(node, side);
    };
  }
  function track(node: HTMLElement, turn: ConversationTurn) {
    if (!displayObserver || turn.canRecordDisplay === false || turn.displayRecorded) return;
    // A reply counts as displayed only when its complete text is painted.
    visibleReplies.set(node, { turnId: turn.id, visible: false });
    displayObserver.observe(node);
  }
  function render() {
    if (destroyed) return;
    root.setAttribute('aria-busy', String(busy));
    heading.textContent = T('同事', 'Colleagues');
    nav.setAttribute('aria-label', T('选择同事', 'Choose a colleague'));
    language.textContent = view
      ? T('工作语言：', 'Working language: ') + (view.workLanguage === 'en' ? 'English' : '中文')
      : '';
    reload.textContent = T('刷新对话', 'Refresh conversation');
    reload.disabled = busy;
    // In the thread, refreshing is only offered when a read failed; it updates by itself otherwise.
    if (historyOnly) reload.hidden = feedback !== 'read';
    // The toolbar's model status already says whether colleagues use a model.
    mode.textContent =
      view && !(historyOnly && view.mode === 'model') ? currentModeNotice(view.mode) : '';
    mode.hidden = !mode.textContent;
    for (const [id, item] of people) {
      const colleague = view?.colleagues.find((c) => c.id === id);
      item.replaceChildren();
      const avatar = el('span', 'rc-roles__avatar');
      avatar.setAttribute('aria-hidden', 'true');
      avatar.textContent = (colleague?.name || roleTitle(id)).slice(0, 1);
      const name = el('span');
      name.textContent = colleague?.name || roleTitle(id);
      const title = el('small');
      title.textContent = roleTitle(id);
      name.append(title);
      item.append(avatar, name);
      item.setAttribute('aria-pressed', String(id === selected));
      // Past conversations remain selectable even while a colleague is unavailable.
    }
    const colleague = view?.colleagues.find((c) => c.id === selected);
    activeName.textContent = colleague?.name || roleTitle(selected);
    list.setAttribute('aria-label', T('对话记录', 'Conversation history'));
    const turns = view?.turns.filter((t) => t.roleId === selected) ?? [];
    const settle = paintThread(turns);
    empty.hidden = turns.length > 0 || (historyOnly && !!pendingBox.childElementCount);
    const opening = el('p');
    if (historyOnly && loaded) {
      // An empty thread introduces the colleague the way the list does.
      opening.textContent = OPENER(PERSON_OF_ROLE[selected] ?? selected);
      const face = avatarNode(doc, selected);
      face.classList.replace('av-sm', 'av-lg');
      empty.replaceChildren(face, opening);
    } else {
      opening.textContent = loaded
        ? T(
            '从一个具体问题开始。只会使用这位同事已知且获准讨论的资料。',
            'Start with a specific question. This colleague can use only information they know and may discuss.',
          )
        : T('正在读取对话…', 'Loading conversation…');
      empty.replaceChildren(opening);
    }
    empty.classList.toggle('rc-roles__empty--opening', historyOnly && loaded);
    label.textContent = T('想和这位同事讨论什么？', 'What would you like to discuss?');
    textarea.placeholder = T(
      '例如：35-45人的试点需要先确认哪些条件？',
      'For example: what should we confirm for a 35-45 person pilot?',
    );
    textarea.disabled = false; // Drafting stays available during failures and recovery.
    send.textContent = busy ? T('正在处理…', 'Working…') : T('发送问题', 'Send question');
    send.disabled = !canSend();
    hint.textContent = T('⌘ / Ctrl + Enter 发送', '⌘ / Ctrl + Enter to send');
    const needsRecovery = uncertain || !!view?.unconfirmed;
    recover.hidden = !needsRecovery;
    recover.textContent = T('恢复原请求', 'Recover original request');
    recover.disabled = busy;
    notice.textContent = needsRecovery
      ? T(
          '结果尚未确认。输入已保留，请恢复原请求。',
          'The result is unconfirmed. Your input is retained; recover the original request.',
        )
      : feedback === 'read'
        ? T(
            '暂时无法读取对话。已有记录与输入保留，请刷新。',
            'Conversation could not be read. Existing records and input are retained; refresh to continue.',
          )
        : feedback === 'action'
          ? T(
              '这次操作未完成，已有记录与输入保留。',
              'This action was not completed. Records and input are retained.',
            )
          : feedback === 'draft'
            ? T(
                '输入尚未保存到本机，请保留文字。',
                'Input has not been saved locally; keep your text.',
              )
            : view?.restriction || '';
    notice.hidden = !notice.textContent;
    settle();
  }
  async function refresh() {
    const ticket = ++loadTicket;
    try {
      const next = await adapter.read();
      if (destroyed || ticket !== loadTicket) return;
      if (
        !next.sessionId ||
        (sessionId && sessionId !== next.sessionId) ||
        !['zh', 'en'].includes(next.workLanguage) ||
        !['local_reference', 'model', 'unavailable'].includes(next.mode) ||
        !Array.isArray(next.colleagues) ||
        !Array.isArray(next.turns)
      )
        throw new Error('Invalid session projection');
      if (view && view.workLanguage !== next.workLanguage)
        throw new Error('Working language changed');
      sessionId = next.sessionId;
      view = next;
      loaded = true;
      readHere = true;
      if (feedback === 'read') feedback = undefined;
    } catch {
      if (destroyed || ticket !== loadTicket) return;
      loaded = false;
      feedback = 'read';
    }
    render();
  }
  async function perform(action: () => Promise<void>, recovery = false) {
    if (busy || destroyed) return;
    busy = true;
    feedback = undefined;
    render();
    try {
      await action();
      if (destroyed) return;
      if (recovery) uncertain = false;
      await refresh();
    } catch {
      if (!destroyed) {
        uncertain = true;
        feedback = 'unconfirmed';
      }
    } finally {
      busy = false;
      render();
    }
  }
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!canSend()) return;
    const roleId = selected;
    const text = textarea.value;
    void perform(async () => {
      await adapter.send({ roleId, text });
      if (destroyed) return;
      if (draft(roleId) === text) {
        keepDraft(roleId, '');
        if (selected === roleId) textarea.value = '';
      }
    });
  });
  textarea.addEventListener('input', () => {
    const before = feedback;
    keepDraft(selected, textarea.value);
    if (before !== feedback) render();
    else send.disabled = !canSend();
  });
  textarea.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  reload.addEventListener('click', () => {
    void refresh();
  });
  // Escape folds the passage back into its tag, before anything else on the page reacts.
  root.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !peek) return;
    const shown = peek;
    peek = undefined;
    event.stopPropagation();
    render();
    [...root.querySelectorAll<HTMLElement>('[data-focus]')]
      .find((n) => n.dataset.focus === `tag:${shown.turnId}:${shown.label}`)
      ?.focus({ preventScroll: true });
  });
  const onOutgoing = () => render();
  outgoingListeners.add(onOutgoing);
  // Where you were reading, kept for the next mount of this thread.
  const scrollBox = scroller();
  const onScroll = () => {
    if (!memory || !painted || Date.now() < placingUntil) return;
    memory.top = scrollBox.scrollTop;
    memory.atBottom = scrollBox.scrollHeight - scrollBox.scrollTop - scrollBox.clientHeight < 48;
  };
  scrollBox.addEventListener('scroll', onScroll, { passive: true });
  recover.addEventListener('click', () => {
    void perform(async () => {
      const result = await adapter.recover();
      if (destroyed) return;
      const confirmed = result?.confirmed;
      if (confirmed && draft(confirmed.roleId) === confirmed.text) {
        keepDraft(confirmed.roleId, '');
        if (selected === confirmed.roleId) textarea.value = '';
      }
    }, true);
  });
  const unsubscribe = adapter.subscribe?.(() => {
    void refresh();
  });
  const unlocale = onLocaleChange(render);
  const unlens = onLensChange(render);
  // The rail redraw remounts this thread; start from what was just on screen, then read.
  if (historyOnly && options.sessionId) {
    const known = threads.get(threadKey(options.sessionId, selected))?.view;
    if (known?.sessionId === options.sessionId) {
      sessionId = known.sessionId;
      view = known;
      loaded = true;
    }
  }
  render();
  void refresh();
  return {
    refresh,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      ++loadTicket;
      unsubscribe?.();
      outgoingListeners.delete(onOutgoing);
      scrollBox.removeEventListener('scroll', onScroll);
      if (memory && painted) memory.aliveAt = Date.now();
      unlocale();
      unlens();
      displayObserver?.disconnect();
      visibleReplies.clear();
      doc.removeEventListener('visibilitychange', onVisibility);
      root.remove();
    },
  };
}

/** Mount only the selected colleague's history into v4's existing thread node.
 * v4 sends through its own composer/client. Destroy/remount when its role changes.
 */
export function mountConversation(
  container: HTMLElement,
  adapter: RolesNativeAdapter,
  roleId: RoleId,
  sessionId?: string,
): RolesNativeHandle {
  return mount(container, adapter, { surface: 'v4-history', roleId, sessionId });
}
