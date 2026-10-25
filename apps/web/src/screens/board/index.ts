// The board line's entry: its actions, its "Needs you" provider, and what it hears from your
// agent. ui.js keeps the drawing functions it owns and calls into these modules; this file
// holds the state that lives beside the practice (per page, not saved).
import './board.css';
import {
  agentConnection,
  type Attempt,
  dismissSignal,
  onAgentConnection,
  onAgentEvent,
  onSignalsChange,
  recentAgentEvents,
  registerActions,
  registerSignals,
  type Signal,
} from '../../shell';
import { captureBoard, playBoard } from './motion';
import { briefJustRead, toggleBrief } from './brief';
import { returnFocus } from './material-overlay';
import { dismissDraft, draftLanded } from './tray';

export * from './brief';
export * from './config-roll';
export * from './documents';
export * from './material-overlay';
export * from './motion';
export * from './needs-you';
export * from './records';
export * from './sheets';
export * from './tray';
export * from './walk-through';
export { collectSignals } from '../../shell';

export type BoardNote = {
  role: 'manager' | 'business' | 'technical';
  key: string;
  text: string;
  at?: string;
};
export type BoardHost = {
  current(): Attempt | null;
  refresh(parts: string[]): void;
  notes(a: Attempt): BoardNote[];
  replyLabel(): string;
  closeDoc(): void;
  openRecords(open: boolean): void;
  openNeeds(): void;
  reload(): Promise<void>;
  myAgent(): void;
};

let host: BoardHost | null = null;

/* ---------- documents: "Show all", and what your agent is reading ---------- */
const allDocs = new Set<string>();
export const docsAll = (attemptId: string) => allDocs.has(attemptId);

// A document the agent read in the last few seconds shows "Your agent is reading".
const READING_MS = 12_000;
const reading = new Map<string, number>();
export const agentReading = (materialId: string) => {
  const at = reading.get(materialId);
  return at != null && Date.now() - at < READING_MS;
};
let readingTimer = 0;
function readingChanged() {
  host?.refresh(['stage']);
  window.clearTimeout(readingTimer);
  if (reading.size)
    readingTimer = window.setTimeout(() => {
      for (const [id, at] of reading) if (Date.now() - at >= READING_MS) reading.delete(id);
      host?.refresh(['stage']);
    }, READING_MS + 50);
}

/** The tray shows once your agent has connected in this page (connected, or idle since). */
export const agentConnected = () => {
  const s = agentConnection().state;
  return s === 'connected' || s === 'idle';
};

/* ---------- "Needs you": the colleagues' reminders are this line's own signals ---------- */
let notesOf: ((a: Attempt) => BoardNote[]) | null = null;
registerSignals((a): Signal[] =>
  (notesOf?.(a) || []).map((n) => ({
    id: `note:${n.key}`,
    source: 'person',
    person: n.role,
    text: n.text,
    action: { label: host?.replyLabel() || 'Reply', action: 'reply-note', id: n.key },
    dismissible: false,
    at: n.at || '',
  })),
);

// A signal seen for the first time plays its arrival once.
const shownSignals = new Set<string>();
export function freshSignals(ids: string[]) {
  const fresh = new Set(ids.filter((id) => !shownSignals.has(id)));
  // On the first draw of a page nothing "arrives": it was already there.
  const first = shownSignals.size === 0;
  for (const id of ids) shownSignals.add(id);
  return first ? new Set<string>() : fresh;
}

/* ---------- the record drawer ---------- */
let recordsOpen = false;
export const recordsShown = () => recordsOpen;
function openRecords() {
  recordsOpen = true;
  host?.openRecords(true);
}
export function closeRecords() {
  recordsOpen = false;
  host?.openRecords(false);
  document
    .querySelector<HTMLElement>('[data-action="open-records"], [data-action="records"]')
    ?.focus({ preventScroll: true });
}
/** The document sheet closes: ui.js clears its state, then focus goes back to the row. */
export function closeDoc() {
  host?.closeDoc();
  returnFocus();
}

export function installBoard(h: BoardHost) {
  host = h;
  notesOf = h.notes;
  // Where the rail is a drawer, the desk carries the "Needs you" line too.
  onSignalsChange(() =>
    host?.refresh(window.matchMedia('(max-width: 1279px)').matches ? ['rail', 'stage'] : ['rail']),
  );
  // The engineer's fix applied to the pilot (201): read the practice again now, so the product
  // bar shows the new config version (and rolls to it) without waiting for the next poll.
  window.addEventListener('rolecraft:pilot-config-applied', (e) => {
    const id = (e as CustomEvent<{ sessionId?: string }>).detail?.sessionId;
    if (id && id === host?.current()?.id) void host?.reload();
  });
  onAgentConnection(() => host?.refresh(['stage']));
  // A late page reads what the agent already did here, then follows new calls.
  for (const e of recentAgentEvents())
    if (e.direction === 'to_agent' && e.object?.kind === 'material' && e.object.id)
      reading.set(e.object.id, Date.parse(e.at) || 0);
  onAgentEvent((e) => {
    if (e.status !== 'ok') return;
    if (e.direction === 'to_agent' && e.object?.kind === 'material' && e.object.id) {
      reading.set(e.object.id, Date.now());
      readingChanged();
    } else if (e.direction === 'to_workspace' && e.object?.kind === 'work_product' && e.object.id) {
      draftLanded(e.object.id);
      host?.refresh(['stage']);
    }
  });
}

registerActions({
  'board-docs-all': () => {
    const a = host?.current();
    if (!a) return;
    if (allDocs.has(a.id)) allDocs.delete(a.id);
    else allDocs.add(a.id);
    host?.refresh(['stage']);
    document.querySelector<HTMLElement>('.doc-more')?.focus({ preventScroll: true });
  },
  'board-brief-toggle': () => {
    const a = host?.current();
    if (!a) return;
    captureBoard();
    toggleBrief(a.id);
    host?.refresh(['stage']);
    playBoard();
    document
      .querySelector<HTMLElement>('.brief-line-toggle, [data-brief-toggle]')
      ?.focus({ preventScroll: true });
  },
  'board-tray-dismiss': (el) => {
    dismissDraft(el.dataset.id || '', Number(el.dataset.version) || 0);
    host?.refresh(['stage']);
  },
  'board-signal-dismiss': (el) => dismissSignal(el.dataset.id || ''),
  'board-doc-close': () => closeDoc(),
  'board-my-agent': () => host?.myAgent(),
  'board-needs-open': () => host?.openNeeds(),
  records: () => openRecords(),
  'open-records': () => openRecords(),
  'records-close': () => closeRecords(),
});

/**
 * For the entry's landing (207): resolves with the board's task cards once the native board
 * has drawn at least `count` of them (it mounts a moment after the page). Anchors:
 * [data-board-tasks] is the task section, [data-board-lane="first|next|later"] each lane,
 * `.kanban [data-task-id]` each card. The board scrolls in #main, not the window.
 */
export function tasksDrawn(count = 1, timeout = 3000): Promise<HTMLElement[]> {
  const cards = () => [...document.querySelectorAll<HTMLElement>('.kanban [data-task-id]')];
  return new Promise((resolve) => {
    if (cards().length >= count) return resolve(cards());
    const done = () => {
      observer.disconnect();
      window.clearTimeout(timer);
      resolve(cards());
    };
    const observer = new MutationObserver(() => cards().length >= count && done());
    observer.observe(document.getElementById('app') || document.body, {
      childList: true,
      subtree: true,
    });
    const timer = window.setTimeout(done, timeout);
  });
}

/** The brief was opened from the board: when it closes, the brief rolls into one line. */
export const noteBriefRead = (attemptId: string) => briefJustRead(attemptId);
