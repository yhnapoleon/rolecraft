// The person's record of their own Agent, read from GET /sessions/{id}/agent-activity: one row per
// MCP connection or tool call, plus whether a client is connected now. One feed per practice polls
// it; rows that arrive after the first read are live calls and go out on the agent bus (the top-bar
// light, the board tray and the page's conduit react to them). History never replays as motion.
import type { AgentActivity, AgentActivityPage, AgentConnection } from '../../contracts-v2';
import { locale } from '../../app/i18n';
import type { AgentEvent } from '../../shell/agent-bus';
import { clientName, listObject, verbOf } from './verbs';

export type { AgentEvent };
type AgentConnectionState = import('../../shell/agent-bus').AgentConnection;
export type FeedSnapshot = {
  loaded: boolean;
  rows: readonly AgentActivity[];
  events: readonly AgentEvent[];
  connection: AgentConnection;
  /** seq of the first row that arrived live; rows before it were already there. */
  liveFrom: number;
};

const KINDS: Record<string, NonNullable<AgentEvent['object']>['kind']> = {
  material: 'material',
  test: 'test',
  product: 'work_product',
  ticket: 'ticket',
  review: 'review',
  feedback: 'review',
  request: 'request',
  experiment: 'other',
  draft: 'other',
};
const LIST_KINDS: Record<string, NonNullable<AgentEvent['object']>['kind']> = {
  'materials.list': 'material',
  'tests.list': 'test',
  'work_products.list': 'work_product',
};

/** An engineer's experiment or draft is named by its ticket (as read earlier), a review plainly. */
function engineerTitle(kind: string, objects: readonly { kind: string; title?: string | null }[]) {
  const en = locale() === 'en';
  if (kind === 'experiment' || kind === 'draft' || kind === 'ticket')
    return (
      objects.find((o) => o.kind === 'ticket' && o.title)?.title ?? (en ? 'the ticket' : '工单')
    );
  if (kind === 'review') return en ? 'the review' : '复核';
  return undefined;
}

/** Recorded calls can predate short names. Render known tickets in the practice language;
 * unknown tickets and reviews keep a plain noun instead of exposing a backend title. */
function ticketName(kind: string, title: string | undefined) {
  const en = locale() === 'en';
  if (kind === 'review') return en ? 'the review' : '复核';
  if (!['ticket', 'experiment', 'draft'].includes(kind)) return title;
  const hotel = [
    '委托：住宿报销上限的回答需要排查',
    'Ticket: the hotel reimbursement limit answer needs investigation',
    '住宿上限委托',
    'the hotel-limit ticket',
  ].includes(title ?? '');
  return hotel ? (en ? 'the hotel-limit ticket' : '住宿上限委托') : en ? 'the ticket' : '工单';
}

export function toEvent(row: AgentActivity): AgentEvent {
  if (row.kind === 'connected') {
    return {
      id: String(row.seq),
      at: row.at,
      direction: 'to_agent',
      tool: 'initialize',
      verb: ['连上了', 'Connected'],
      object: { kind: 'other', title: clientName(row.client?.name) },
      status: 'ok',
    };
  }
  const tool = row.tool ?? '';
  const meaning = verbOf(tool);
  const first = row.objects?.[0];
  const listed = listObject(tool, row.count);
  let object: AgentEvent['object'];
  if (listed && (tool !== 'materials.list' || (row.objects?.length ?? 0) !== 1))
    object = { kind: LIST_KINDS[tool] ?? 'other', title: listed[locale() === 'en' ? 1 : 0] };
  else if (first)
    object = {
      kind: KINDS[first.kind] ?? 'other',
      id: first.id,
      version: first.version ?? undefined,
      title: ticketName(first.kind, first.title ?? engineerTitle(first.kind, row.objects ?? [])),
    };
  if (!object && tool.startsWith('engineer.')) {
    const kind = tool === 'engineer.reviews.read' ? 'review' : 'ticket';
    object = { kind, title: ticketName(kind, undefined) };
  }
  return {
    id: String(row.seq),
    at: row.at,
    direction: meaning.direction,
    tool,
    verb: meaning.verb,
    object,
    status: row.status,
    error: row.error_code ?? undefined,
  };
}

export type FeedPorts = {
  read(after: number): Promise<AgentActivityPage>;
  emit(event: AgentEvent): void;
  changed(): void;
  /** A live hand-back changed the workspace: refresh the board's data now. */
  workspaceChanged?(): void;
  schedule?(task: () => void, ms: number): unknown;
  cancel?(handle: unknown): void;
  hidden?(): boolean;
};

const EMPTY: AgentConnection = { state: 'none', client: null, last_seen: null };
const FAST = 1500;
const SLOW = 4000;
const LIMIT = 400;

/** Answers that will not change on a later read: the session is gone or not ours to read
 * (e.g. a practice id kept from an earlier server). Polling then stops instead of retrying. */
export function sessionGone(error: unknown) {
  const { status, code } = (error ?? {}) as { status?: number; code?: string };
  if (status === 401 || status === 403 || status === 404) return true;
  return status === 409 && (code === 'v2_session_required' || code === 'session_binding_mismatch');
}

export function createAgentFeed(ports: FeedPorts) {
  let rows: AgentActivity[] = [];
  let events: AgentEvent[] = [];
  let connection: AgentConnection = EMPTY;
  let cursor = 0;
  let loaded = false;
  let liveFrom = Number.POSITIVE_INFINITY;
  let snap: FeedSnapshot | null = null;
  let timer: unknown;
  let running = false;
  let inFlight: Promise<void> | null = null;
  let eager = false;
  const schedule = ports.schedule ?? ((task, ms) => setTimeout(task, ms));
  const cancel = ports.cancel ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>));

  async function readOnce() {
    let page: AgentActivityPage;
    try {
      page = await ports.read(cursor);
    } catch (error) {
      if (sessionGone(error)) running = false;
      return;
    }
    const fresh = page.items.filter((r) => r.seq > cursor);
    const before = JSON.stringify(connection);
    if (before !== JSON.stringify(page.connection)) connection = page.connection;
    let changed = before !== JSON.stringify(connection) || !loaded;
    if (fresh.length) {
      const first = !loaded;
      if (!first && liveFrom === Number.POSITIVE_INFINITY) liveFrom = fresh[0].seq;
      rows = [...rows, ...fresh].slice(-LIMIT);
      const next = fresh.map(toEvent);
      events = [...events, ...next].slice(-LIMIT);
      cursor = fresh[fresh.length - 1].seq;
      changed = true;
      if (!first) {
        for (const e of next) ports.emit(e);
        if (next.some((e) => e.direction === 'to_workspace' && e.status === 'ok'))
          ports.workspaceChanged?.();
      }
    }
    loaded = true;
    if (changed) ports.changed();
    if (!page.complete) await readOnce();
  }

  function poll() {
    inFlight ??= readOnce().finally(() => {
      inFlight = null;
    });
    return inFlight;
  }

  function loop() {
    if (!running) return;
    const go = async () => {
      if (!ports.hidden?.()) await poll();
      if (running) timer = schedule(loop, eager || connection.state === 'connected' ? FAST : SLOW);
    };
    void go();
  }

  return {
    start() {
      if (running) return;
      running = true;
      loop();
    },
    stop() {
      running = false;
      if (timer !== undefined) cancel(timer);
      timer = undefined;
    },
    /** Poll fast while someone is watching for the first connection. */
    watch(on: boolean) {
      eager = on;
    },
    poll,
    /** Same object until something changes (useSyncExternalStore compares by identity). */
    snapshot(): FeedSnapshot {
      if (
        !snap ||
        snap.loaded !== loaded ||
        snap.rows !== rows ||
        snap.connection !== connection ||
        snap.liveFrom !== liveFrom
      )
        snap = { loaded, rows, events, connection, liveFrom };
      return snap;
    },
    state(): AgentConnectionState {
      return {
        state: connection.state,
        client: connection.client ? clientName(connection.client) : undefined,
        lastSeen: connection.last_seen ?? undefined,
      };
    },
  };
}
export type AgentFeed = ReturnType<typeof createAgentFeed>;
