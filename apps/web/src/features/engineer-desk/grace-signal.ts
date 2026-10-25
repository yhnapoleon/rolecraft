/** Grace's replies in an engineer's practice (phase 2, step 3): kept per practice in this browser
 * and shown in Needs you as her note. Loaded with the engineer entry, so the note is there before
 * the desk's screens load. */
import { type Attempt, registerSignals, type Signal } from '../../shell';

const KEY = 'rolecraft.grace.replies.v1';
type Reply = { at: string; ticketId: string; text: string; result: string; reviewId?: string };
function replies(): Record<string, Reply[]> {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}') || {};
  } catch {
    return {};
  }
}
export function keepGraceReply(sessionId: string, reply: Reply) {
  const all = replies();
  all[sessionId] = [...(all[sessionId] ?? []), reply].slice(-5);
  try {
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* this page only */
  }
}

// Grace's latest reply stays in Needs you as her note (an engineer's practice only).
registerSignals((attempt: Attempt): Signal[] => {
  const id: string | undefined = attempt?.id;
  if (!id) return [];
  const last = (replies()[id] ?? []).at(-1);
  if (!last?.text) return [];
  return [
    {
      id: `grace-reply:${last.ticketId}:${last.at}`,
      source: 'person',
      person: 'manager',
      text: last.text,
      dismissible: true,
      at: last.at,
      tone: last.result === 'applied' ? 'good' : 'warn',
    },
  ];
});

/** Whether this review was already handed to Grace (her decision is in): the desk's key says so. */
export function handedToGrace(sessionId: string, reviewId: string): Reply | null {
  return (replies()[sessionId] ?? []).filter((r) => r.reviewId === reviewId).at(-1) ?? null;
}
