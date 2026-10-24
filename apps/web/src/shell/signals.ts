// "Needs you" in the right rail: what asks the person for a response. Every line that has
// something to say registers one provider; the board line draws the merged list (at most 3).

// The practice record from the local engine (ui.js `current()`); its shape lives in the engine.
// biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
export type Attempt = any;

export type Signal = {
  id: string;
  source: 'person' | 'agent' | 'system';
  person?: 'manager' | 'business' | 'technical';
  text: string;
  action?: { label: string; action: string; id?: string };
  dismissible?: boolean;
  at: string;
};

type Provider = (attempt: Attempt) => Signal[];
const providers: Provider[] = [];
const listeners = new Set<() => void>();
const DISMISSED = 'rolecraft.signals.dismissed.v1';

/** Adds a source of signals. Providers are pulled on every rail render; keep them cheap and pure. */
export function registerSignals(provider: (attempt: Attempt) => Signal[]): void {
  providers.push(provider);
}

/* ---------- used by the rail (board line) and by providers ---------- */

function dismissedSet(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(DISMISSED) || '[]'));
  } catch {
    return new Set();
  }
}

/**
 * Every provider's signals for this practice, newest first, without the ones the person
 * dismissed. A provider that throws is skipped, never the whole list.
 */
export function collectSignals(attempt: Attempt): Signal[] {
  if (!attempt) return [];
  const gone = dismissedSet();
  const all: Signal[] = [];
  for (const p of providers) {
    try {
      for (const s of p(attempt) || []) if (!gone.has(s.id)) all.push(s);
    } catch (err) {
      console.warn('signal provider failed', err);
    }
  }
  return all.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
}

/** Hides a dismissible signal for good (per browser). */
export function dismissSignal(id: string): void {
  const set = dismissedSet();
  set.add(id);
  try {
    localStorage.setItem(DISMISSED, JSON.stringify([...set].slice(-200)));
  } catch {
    /* storage blocked: the signal returns on the next load */
  }
  signalsChanged();
}

/** A provider whose answer changed outside a render (a poll, an agent event) calls this. */
export function signalsChanged(): void {
  for (const cb of listeners) cb();
}

export function onSignalsChange(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
