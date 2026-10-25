/** Whether a practice still has something for the engineer to fix (189's decision, rework r3 §1).
 *
 * The problem in the hotel-limit ticket exists only while the travel policy is newer than the
 * assistant's index and the settings give no warning (`freshness_guard: none`). It is read from
 * this practice's own workspace (the same numbers as the board's "Index built on v1, behind"),
 * before any ticket is opened, because opening one puts the pilot live and a delivered practice
 * would have to open a revision first. Only when those facts are not there does it read the
 * ticket's first target test: whether the answer it recorded cites an older version than the
 * source with no warning. When neither can tell, the ticket opens as before. */
import type { TargetTest } from './model';

export type FixNeed = 'broken' | 'clear';
export interface PracticeFacts {
  readonly policyVersion: number | null;
  readonly indexVersion: number | null;
  /** The saved setting, or null when the practice's configuration has not been read. */
  readonly freshnessGuard: string | null;
}

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** The three facts from the workbench's practice record (`current()`); missing ones are null. */
// biome-ignore lint/suspicious/noExplicitAny: the engine's attempt is untyped JavaScript
export function practiceFacts(a: any): PracticeFacts {
  const effective = a?.effectiveConfig?.effective;
  return {
    policyVersion: num(a?.world?.policyVersion),
    indexVersion: num(a?.world?.indexVersion),
    // A saved configuration without the field has the server's default: no warning.
    freshnessGuard: effective ? String(effective.freshness_guard ?? 'none') : null,
  };
}

/** From the practice alone; null when it cannot tell (then the ticket's recorded test decides). */
export function fixNeedFromPractice(f: PracticeFacts): FixNeed | null {
  if (f.policyVersion == null || f.indexVersion == null) return null;
  if (f.indexVersion >= f.policyVersion) return 'clear';
  if (f.freshnessGuard == null) return null;
  return f.freshnessGuard === 'none' ? 'broken' : 'clear';
}

function fromTicket(test: TargetTest | undefined): FixNeed | null {
  if (!test) return null;
  // Already warned, or handed to a person: nothing stale reached the user unannounced.
  if (test.status === 'answered_with_warning' || test.status === 'fallback') return 'clear';
  if (test.status !== 'answered') return null;
  const cite = test.citations[0];
  if (cite?.object_id && cite.version != null) {
    const source = test.source_versions[cite.object_id];
    return source != null && cite.version < source ? 'broken' : 'clear';
  }
  const lag = Object.entries(test.source_versions).some(
    ([k, v]) => test.indexed_versions[k] != null && test.indexed_versions[k] < v,
  );
  return lag ? 'broken' : 'clear';
}

export function fixNeed(practice: PracticeFacts, test?: TargetTest): FixNeed {
  return fixNeedFromPractice(practice) ?? fromTicket(test) ?? 'broken';
}
