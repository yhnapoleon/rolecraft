/** Messages sent from this browser that the conversation does not show yet. Shared by the v4
 * composer (which sends) and the thread (which shows them), across remounts of either. */
import type { ConversationTurn, RoleId } from './index';

/** A message sent from this browser, shown at once and marked sending until the existing client
 * confirms it; it gives way to the real turn as soon as the conversation has it. */
export interface Outgoing {
  text: string;
  state: 'sending' | 'sent';
  /** Turns already asking the same words when it was sent. */
  before: number;
  shown: boolean;
}
export const outgoing = new Map<string, Outgoing>();
export const knownTurns = new Map<string, readonly ConversationTurn[]>();
export const outgoingListeners = new Set<() => void>();
export const threadKey = (session: string, role: string) => `${session}:${role}`;
/** The v4 composer sends through its own client; it tells the thread what is on the way. */
export function noteOutgoing(
  session: string,
  roleId: RoleId,
  text: string,
  sending: Promise<unknown>,
) {
  const key = threadKey(session, roleId);
  const before = (knownTurns.get(key) ?? []).filter((t) => t.question === text).length;
  const entry: Outgoing = { text, state: 'sending', before, shown: false };
  outgoing.set(key, entry);
  const changed = () => {
    for (const listener of outgoingListeners) listener();
  };
  changed();
  sending.then(
    () => {
      if (outgoing.get(key) !== entry) return;
      entry.state = 'sent';
      changed();
    },
    () => {
      // Not sent: the words stay in the composer and the host says why; no bubble remains.
      if (outgoing.get(key) === entry) outgoing.delete(key);
      changed();
    },
  );
}
