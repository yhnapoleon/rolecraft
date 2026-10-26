// Observe the global feed, not a route. Persist only activity identities (never credentials).
import { type FeedSnapshot, working } from './feed';
import { clientName } from './verbs';

type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem'>;
const memory = new Map<string, string>();
export function createConnectionNotice(
  session: string,
  notify: (text: string) => void,
  language: () => 'zh' | 'en',
  storage?: Storage,
) {
  let previous: string | null = null;
  const key = `rolecraft.agent-connection-notice.v1:${session}`;
  const get = () => {
    try {
      return storage?.getItem(key) ?? memory.get(key);
    } catch {
      return memory.get(key);
    }
  };
  const remember = (id: string) => {
    memory.set(key, id);
    try {
      storage?.setItem(key, id);
    } catch {
      /* storage can be unavailable; the tab still deduplicates */
    }
  };
  return (feed: FeedSnapshot) => {
    if (!feed.loaded) return;
    // A handshake alone (setup check) is not the agent at work; the notice waits for a call.
    const state =
      feed.connection.state === 'connected' && !working(feed.rows)
        ? 'reachable'
        : feed.connection.state;
    const last = feed.rows.at(-1);
    const id = last ? `${last.delegation_id}:${last.seq}` : feed.connection.last_seen;
    const initial = previous === null;
    const connectedNow = state === 'connected' && previous !== 'connected';
    previous = state;
    if (!connectedNow || !id) return;
    const already = get() === id;
    remember(id);
    // An initial read is restored history, including a refresh. Never replay its notification.
    if (initial || already) return;
    const raw = feed.connection.client?.trim();
    const name = raw ? clientName(raw) : '';
    notify(
      language() === 'en'
        ? `Your agent is connected${name ? ` · from ${name}` : ''}`
        : `你的 Agent 已连接${name ? ` · 来自 ${name}` : ''}`,
    );
  };
}
