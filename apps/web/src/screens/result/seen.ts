/** Which results this viewer has seen on the result page (per browser), so "Your feedback is
 * ready" leaves "Needs you" once it has been read. */
import { signalsChanged } from '../../shell/signals';

const SEEN = 'rolecraft.result.seen.v1';

export function seenResults(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN) || '[]'));
  } catch {
    return new Set();
  }
}

/** The result page showed this submission's result: its signal goes. */
export function resultSeen(submissionId: string) {
  const seen = seenResults();
  if (seen.has(submissionId)) return;
  seen.add(submissionId);
  try {
    localStorage.setItem(SEEN, JSON.stringify([...seen].slice(-100)));
  } catch {
    // Not kept; the signal may return after a reload until the result is seen again.
  }
  signalsChanged();
}
