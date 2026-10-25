/** What this browser remembers about the engineer hat of each practice (front end only, like the
 * shell's hat): how the hat was first put on (for the intro's words), whether the intro was seen,
 * and which reviews were handed back to the product manager. Storage may be blocked: then it lives
 * for this page only. */
export type HatOrigin = 'new' | 'same' | 'handover';
export interface HandedBack {
  readonly at: string;
  readonly ticketId: string;
  readonly clean: boolean;
  readonly newFailures: number;
  /** The ticket's source ('seeded' | 'tests'): the signal's subject. */
  readonly title: string;
  /** What the review came to (absent from entries kept before it was). */
  readonly result?: {
    readonly target: 'fixed' | 'not_fixed' | 'partial' | 'unknown';
    readonly newFailures: number;
    readonly compared: boolean;
  };
  /** Set once the product manager updated the pilot from this review. */
  readonly appliedVersion?: number;
  /** The AI colleague who signed it (Daniel, in a product manager's practice); absent: the person. */
  readonly colleague?: string;
}
export interface EngineerLocal {
  origin?: HatOrigin;
  introSeen?: boolean;
  handedBack?: Record<string, HandedBack>;
}

const KEY = 'rolecraft.engineer.local.v1';
let memory: Record<string, EngineerLocal> = {};

function read(): Record<string, EngineerLocal> {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
    if (raw && typeof raw === 'object') memory = raw;
  } catch {
    /* blocked: keep this page's copy */
  }
  return memory;
}

export function engineerLocal(sessionId: string): EngineerLocal {
  return read()[sessionId] ?? {};
}

export function updateEngineerLocal(sessionId: string, change: Partial<EngineerLocal>) {
  const all = read();
  all[sessionId] = { ...(all[sessionId] ?? {}), ...change };
  memory = all;
  try {
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* page only */
  }
}

export function recordHandBack(sessionId: string, reviewId: string, entry: HandedBack) {
  const current = engineerLocal(sessionId);
  updateEngineerLocal(sessionId, {
    handedBack: { ...(current.handedBack ?? {}), [reviewId]: entry },
  });
}
