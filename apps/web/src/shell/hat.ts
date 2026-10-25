// Which hat a practice is worn with: product manager or engineer. Front-end only, kept per
// practice in this browser. 201 may add to this module; the signatures below stay.

export type Hat = 'pm' | 'engineer';

const KEY = 'rolecraft.hat.v1';
const listeners = new Set<(sessionKey: string, hat: Hat) => void>();
let memory: Record<string, Hat> = {};

function read(): Record<string, Hat> {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
    memory = raw && typeof raw === 'object' ? raw : {};
  } catch {
    /* storage blocked: keep what this page knows */
  }
  return memory;
}

/** The hat for this practice: its one role when it has one, else the one last worn (a practice
 * from before roles, nobody switched: a product manager's). */
export function hatOf(sessionKey: string): Hat {
  const fixed = roleOf(sessionKey);
  if (fixed) return fixed;
  return read()[sessionKey] === 'engineer' ? 'engineer' : 'pm';
}

/* ---------- the practice's one role (phase 2) ---------- */
// Chosen on the home page and kept by the server (engineer store, learner_role); this is the
// browser's copy so the bar can draw it at once. A practice from before roles has none and keeps
// the old switch between hats.
const ROLE = 'rolecraft.role.v1';
function roles(): Record<string, Hat> {
  try {
    const raw = JSON.parse(localStorage.getItem(ROLE) || '{}');
    return raw && typeof raw === 'object' ? raw : {};
  } catch {
    return roleMemory;
  }
}
let roleMemory: Record<string, Hat> = {};
export function roleOf(sessionKey: string): Hat | null {
  const r = roles()[sessionKey] ?? roleMemory[sessionKey];
  return r === 'pm' || r === 'engineer' ? r : null;
}
export function rememberRole(sessionKey: string, role: Hat): void {
  roleMemory = { ...roleMemory, [sessionKey]: role };
  try {
    localStorage.setItem(ROLE, JSON.stringify({ ...roles(), [sessionKey]: role }));
  } catch {
    /* this page only */
  }
  setHat(sessionKey, role);
}

export function setHat(sessionKey: string, hat: Hat): void {
  const all = read();
  if ((all[sessionKey] ?? 'pm') === hat) return;
  all[sessionKey] = hat;
  memory = all;
  try {
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* kept for this page only */
  }
  for (const cb of listeners) cb(sessionKey, hat);
}

/** Called with (sessionKey, hat) after every change; returns the unsubscribe. */
export function onHatChange(cb: (sessionKey: string, hat: Hat) => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** True once this practice has ever been worn as an engineer (home's continue slip, 201's intro). */
export function everEngineer(sessionKey: string): boolean {
  return hatOf(sessionKey) === 'engineer' || worn().has(sessionKey);
}

const WORN = 'rolecraft.hat.worn.v1';
function worn(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(WORN) || '[]'));
  } catch {
    return new Set();
  }
}
onHatChange((key, hat) => {
  if (hat !== 'engineer') return;
  const set = worn();
  set.add(key);
  try {
    localStorage.setItem(WORN, JSON.stringify([...set]));
  } catch {
    /* page only */
  }
});

/* ---------- the engineer's desk to come back to ---------- */

const TICKET = 'rolecraft.hat.ticket.v1';
/** The ticket last open on this practice's sign-off desk, for the hat switch. */
export function lastTicket(sessionKey: string): string | null {
  try {
    return JSON.parse(localStorage.getItem(TICKET) || '{}')[sessionKey] ?? null;
  } catch {
    return null;
  }
}
export function setLastTicket(sessionKey: string, ticketId: string): void {
  try {
    const all = JSON.parse(localStorage.getItem(TICKET) || '{}');
    all[sessionKey] = ticketId;
    localStorage.setItem(TICKET, JSON.stringify(all));
  } catch {
    /* page only */
  }
}
