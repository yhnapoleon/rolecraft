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

/** The hat for this practice; a practice nobody switched is a product manager's. */
export function hatOf(sessionKey: string): Hat {
  return read()[sessionKey] === 'engineer' ? 'engineer' : 'pm';
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
