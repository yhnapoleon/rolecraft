/** The optional-practice column after each read of the shown feedback's practice suggestion. */
import { retryableRead } from '../../api';

/** A dropped read is asked again on the next poll, up to this many times in a row. */
export const PRACTICE_READS_AGAIN = 3;
export type PracticeView = { state?: string; error?: string } & Record<string, unknown>;
export type PracticeRead = { view: PracticeView } | { error: unknown };

/** A read result replaces what is shown. A dropped read keeps what is shown and asks again; once
 * drops keep coming, shown choices stay and only an empty column says practice is unavailable.
 * Any other failure shows the unavailable notice; the wording is chosen when it is rendered. */
export function afterPracticeRead(
  shown: PracticeView | undefined,
  read: PracticeRead,
  dropsInARow: number,
  sealed: boolean,
): { view: PracticeView; dropsInARow: number; readAgain: boolean } {
  if ('view' in read) return { view: read.view, dropsInARow: 0, readAgain: false };
  const unavailable = { error: 'unavailable', sealed };
  if (!retryableRead(read.error)) return { view: unavailable, dropsInARow: 0, readAgain: false };
  const drops = dropsInARow + 1;
  if (drops <= PRACTICE_READS_AGAIN)
    return { view: shown ?? { state: 'loading' }, dropsInARow: drops, readAgain: true };
  const kept = shown && shown.state !== 'loading' ? shown : unavailable;
  return { view: kept, dropsInARow: 0, readAgain: false };
}
