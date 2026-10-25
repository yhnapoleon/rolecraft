// The My agent page (#/agent) and everything around the learner's own Agent: one activity feed
// per practice, the agent bus it feeds (top-bar light, board tray), the "returned a draft"
// signal and the connection. ui.js only provides data through provideAgentPage() and calls
// syncAgentFeed() after each render.
import { islandSlot, keepIsland } from '../../islands/mount';
import {
  type AgentConnection,
  emitAgentEvent,
  hatOf,
  registerActions,
  registerRoute,
  registerSignals,
  resetAgentBus,
  type Signal,
  setAgentConnection,
  showConnectionToast,
  signalsChanged,
} from '../../shell';
import { type AgentFeed, createAgentFeed, type FeedSnapshot } from './feed';
import type { GrantHost } from './grant';
import { AgentPage } from './page';
import './agent-page.css';
import { createConnectionNotice } from './connection-notice';

// biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
type Attempt = any;
export type Pair = [zh: string, en: string];
/** One workspace object row on the page's left column. */
export type WorkspaceRow = {
  key: 'documents' | 'brief' | 'tests' | 'work' | 'tasks' | 'ticket';
  label: Pair;
  value: string;
};
/** A piece of work the Agent handed back, as the board knows it. */
export type ReturnedWork = {
  id: string;
  title: string;
  excerpt: string;
  version: number;
  adopted: boolean;
  removed: boolean;
};
export type AgentHost = GrantHost & {
  query(operation: 'agent_activity', input: { after?: number }): Promise<unknown>;
  subscribe(listener: () => void): () => void;
};
export type AgentPagePorts = {
  current(): Attempt | null;
  /** The practice's data host when it runs on the server (MCP needs one), else null. */
  host(a: Attempt): AgentHost | null;
  language(): 'zh' | 'en';
  workspace(a: Attempt, hat: 'pm' | 'engineer'): WorkspaceRow[];
  /** Work handed back by an Agent (any delegated author), newest last. */
  returned(a: Attempt): ReturnedWork[];
  /** The manual hand-over (task package and paste-back), as native HTML. */
  packageHtml(a: Attempt): string;
  refresh(a: Attempt): Promise<unknown> | unknown;
  openWork(a: Attempt, id: string): void;
  adopt(id: string): void;
  notify(text: string): void;
  back(): void;
};

let ports: AgentPagePorts | null = null;
let active: { key: string; feed: AgentFeed; host: AgentHost; unhost: () => void } | null = null;
const listeners = new Set<() => void>();
const changed = () => {
  for (const cb of listeners) cb();
};

export function provideAgentPage(p: AgentPagePorts) {
  ports = p;
}

/** The connection shown everywhere: "waiting" once access is issued and nobody connected yet. */
function connection(feed: AgentFeed, host: AgentHost): AgentConnection {
  const state = feed.state();
  if (state.state === 'none' && host.issuedDelegation()) return { state: 'waiting' };
  return state;
}

/** After every render: the feed follows the practice on screen (and stops without one). */
export function syncAgentFeed() {
  const a = ports?.current();
  const host = a && ports ? ports.host(a) : null;
  const key = a && host ? String(a.id) : '';
  if (active && active.key === key && active.host === host) return;
  if (active) {
    active.feed.stop();
    active.unhost();
    active = null;
    resetAgentBus();
    changed();
  }
  if (!key || !host || !ports) return;
  const p = ports;
  let storage: Storage | undefined;
  try {
    storage = localStorage;
  } catch {
    /* browser storage may be disabled */
  }
  const notice = createConnectionNotice(key, showConnectionToast, p.language, storage);
  const feed = createAgentFeed({
    read: async (after) => (await host.query('agent_activity', { after })) as never,
    emit: emitAgentEvent,
    changed: () => {
      if (active?.feed !== feed) return;
      setAgentConnection(connection(feed, host));
      notice(feed.snapshot());
      signalsChanged();
      changed();
    },
    workspaceChanged: () => {
      const now = p.current();
      if (now && String(now.id) === key) void p.refresh(now);
    },
    hidden: () => typeof document !== 'undefined' && document.hidden,
  });
  // Issuing or withdrawing access changes "waiting" without any server row.
  const unhost = host.subscribe(() => {
    setAgentConnection(connection(feed, host));
    changed();
  });
  active = { key, feed, host, unhost };
  feed.start();
  changed();
}

const EMPTY: FeedSnapshot = {
  loaded: false,
  rows: [],
  events: [],
  connection: { state: 'none', client: null, last_seen: null },
  liveFrom: Number.POSITIVE_INFINITY,
};
export const feedStore = {
  subscribe(cb: () => void) {
    listeners.add(cb);
    return () => listeners.delete(cb);
  },
  snapshot: (): FeedSnapshot => active?.feed.snapshot() ?? EMPTY,
  watch: (on: boolean) => active?.feed.watch(on),
  poll: () => active?.feed.poll(),
};

/* ---------- the page ---------- */

const OPENERS: Record<'pm' | 'engineer', Pair> = {
  pm: [
    '读 RoleCraft 里的委托，起草第一批试点方案。',
    'Read the brief in RoleCraft and draft a first-wave pilot plan.',
  ],
  engineer: [
    '读 RoleCraft 里的工程委托，复现问题，试一个修法并起草提交；不要签字。',
    'Read the engineering ticket in RoleCraft, reproduce it, try a fix and draft a sign-off. Don’t sign.',
  ],
};

function pageProps(a: Attempt) {
  const p = ports as AgentPagePorts;
  const hat = hatOf(String(a.id));
  return {
    sessionKey: String(a.id),
    lang: p.language(),
    hat,
    host: p.host(a),
    workspace: p.workspace(a, hat),
    returned: p.returned(a),
    opener: OPENERS[hat],
    origin: typeof location === 'undefined' ? '' : location.origin,
    onReview: (id: string) => p.openWork(a, id),
    onAdopt: (id: string) => p.adopt(id),
    notify: p.notify,
  };
}
export type AgentPageProps = ReturnType<typeof pageProps>;

registerRoute(
  'agent',
  () => {
    const a = ports?.current();
    return `<section class="ag-page" data-agent-page>${islandSlot('agent-page')}${a && ports ? ports.packageHtml(a) : ''}</section>`;
  },
  (stage) => {
    const a = ports?.current();
    if (!a || !ports) return;
    keepIsland('agent-page', AgentPage, pageProps(a), { root: stage });
  },
);

registerActions({
  'open-agent': () => {
    location.hash = '#/agent';
  },
});

/** "Your agent returned a draft · Review": one per hand-back still waiting for the person. */
registerSignals((a): Signal[] => {
  if (!ports || !active || String(a?.id) !== active.key) return [];
  const lang = ports.language();
  const waiting = ports.returned(a).filter((w) => !w.adopted && !w.removed);
  return waiting.slice(-2).map((w) => ({
    id: `agent-draft:${w.id}:${w.version}`,
    source: 'agent',
    text:
      lang === 'en'
        ? `Your agent returned a draft · ${w.title}`
        : `你的 Agent 交回了一份草稿 ·《${w.title}》`,
    action: { label: lang === 'en' ? 'Review' : '去看看', action: 'agent-review', id: w.id },
    dismissible: true,
    at: returnedAt(w.id),
  }));
});
function returnedAt(id: string) {
  const rows = active?.feed.snapshot().rows ?? [];
  for (let i = rows.length - 1; i >= 0; i--)
    if (rows[i].kind === 'tool_call' && rows[i].objects?.some((o) => o.id === id))
      return rows[i].at;
  return rows.at(-1)?.at ?? new Date(0).toISOString();
}
registerActions({
  'agent-review': (el) => {
    const a = ports?.current();
    if (a && el.dataset.id) ports?.openWork(a, el.dataset.id);
  },
});
