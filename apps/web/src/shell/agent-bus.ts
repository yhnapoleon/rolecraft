// The learner's own agent, as the page sees it: one event per real tool call, and the
// connection state. The agent line (L3) polls the server and emits; the topbar lamp, the
// board's tray and the transmission stream subscribe.

export type AgentEvent = {
  id: string;
  at: string;
  direction: 'to_agent' | 'to_workspace';
  tool: string;
  verb: [string, string];
  object?: {
    kind: 'material' | 'test' | 'work_product' | 'ticket' | 'review' | 'request' | 'other';
    id?: string;
    version?: number;
    title?: string;
  };
  status: 'ok' | 'error';
  error?: string;
};

export type AgentConnection = {
  state: 'none' | 'waiting' | 'connected' | 'idle';
  client?: string;
  lastSeen?: string;
};

const listeners = new Set<(e: AgentEvent) => void>();
const connectionListeners = new Set<(c: AgentConnection) => void>();
const seen = new Set<string>();
const recent: AgentEvent[] = [];
const RECENT = 200;
let connection: AgentConnection = { state: 'none' };

export function onAgentEvent(cb: (e: AgentEvent) => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Emits one tool call. An id already emitted is ignored, so a poll may resend overlapping pages. */
export function emitAgentEvent(e: AgentEvent): void {
  if (seen.has(e.id)) return;
  seen.add(e.id);
  recent.push(e);
  if (recent.length > RECENT) recent.splice(0, recent.length - RECENT);
  listeners.forEach((cb) => {
    try {
      cb(e);
    } catch (err) {
      console.warn('agent event listener failed', err);
    }
  });
}

export function agentConnection(): AgentConnection {
  return connection;
}

/* ---------- additions for the agent line and late subscribers ---------- */

/** The events emitted so far in this page (oldest first), for a view mounted after they arrived. */
export function recentAgentEvents(): readonly AgentEvent[] {
  return recent;
}

/** The agent line reports the connection; the topbar lamp follows. */
export function setAgentConnection(next: AgentConnection): void {
  if (
    next.state === connection.state &&
    next.client === connection.client &&
    next.lastSeen === connection.lastSeen
  )
    return;
  connection = { ...next };
  for (const cb of connectionListeners) cb(connection);
}

export function onAgentConnection(cb: (c: AgentConnection) => void): () => void {
  connectionListeners.add(cb);
  return () => connectionListeners.delete(cb);
}

/** Clears what this page remembers (switching to another practice). */
export function resetAgentBus(): void {
  seen.clear();
  recent.length = 0;
  setAgentConnection({ state: 'none' });
}
