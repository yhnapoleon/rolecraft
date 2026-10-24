/** The result page's entrance. Played once per arrival (a delivery just made, the review
 * arriving after a wait, or opening the page), never on a redraw.
 *
 * Exceptions to the 160/280/520 ms, transform-and-opacity rule (plan §2.4, all signed off):
 * - the stamp press animates `filter: blur()` as well, so the stamp lands sharp;
 * - the readings roll from 0 with NumberFlow, which animates its own digits.
 * With reduced motion everything fades in over 160 ms in place and the numbers do not roll. */
import { clockWords } from './result-head';
import { pressStamp } from '../../shared/stamp/stamp';

const SPRING = { type: 'spring', duration: 0.52, bounce: 0.18 } as const;
const EASE_OUT = [0.23, 1, 0.32, 1] as const;

export interface EntranceInput {
  /** Rise from below as the page takes over the desk. */
  rise: boolean;
  /** Press the stamp (a delivery just made on this page). */
  stamp: boolean;
  /** Roll the readings from 0 and settle the rows in. */
  counts: boolean;
}

const reducedMotion = (doc: Document) =>
  doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;

/** Swap the readings' plain numbers for NumberFlow, starting at 0 when they should roll. */
async function flowNumbers(paper: HTMLElement, roll: boolean) {
  const spans = [...paper.querySelectorAll<HTMLElement>('.result-reading__n[data-value]')];
  if (!spans.length) return;
  try {
    await import('number-flow');
  } catch {
    return; // plain numbers stay
  }
  const doc = paper.ownerDocument;
  const flows = spans.map((span) => {
    const flow = doc.createElement('number-flow');
    flow.className = span.className;
    flow.setAttribute('aria-hidden', 'true');
    flow.transformTiming = { duration: 900, easing: 'cubic-bezier(.23,1,.32,1)' };
    flow.spinTiming = { duration: 900, easing: 'cubic-bezier(.23,1,.32,1)' };
    flow.update(roll ? 0 : Number(span.dataset.value));
    span.replaceWith(flow);
    return { flow, value: Number(span.dataset.value) };
  });
  if (!roll) return;
  // One frame at 0, then roll to the real counts, left to right, 80 ms apart.
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  flows.forEach(({ flow, value }, i) => {
    setTimeout(() => flow.update(value), i * 80);
  });
}

export async function playEntrance(paper: HTMLElement, input: EntranceInput) {
  const doc = paper.ownerDocument;
  const reduced = reducedMotion(doc);
  const rows = [
    ...(paper.parentElement?.querySelectorAll<HTMLElement>('[data-result-detail] .fb-item') ?? []),
  ].slice(0, 12);
  if (reduced) {
    void flowNumbers(paper, false);
    const stamp = paper.querySelector<HTMLElement>('[data-stamp]');
    if (input.stamp && stamp) void pressStamp(stamp);
    if (input.rise || input.counts)
      paper.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: 'ease' });
    return;
  }
  let animate: typeof import('motion').animate;
  try {
    ({ animate } = await import('motion'));
  } catch {
    void flowNumbers(paper, false);
    return;
  }
  const jobs: Promise<unknown>[] = [];
  if (input.rise)
    jobs.push(
      animate(
        paper,
        { opacity: [0, 1], transform: ['translateY(12px)', 'translateY(0px)'] },
        SPRING,
      ).finished,
    );
  const stamp = paper.querySelector<HTMLElement>('[data-stamp]');
  if (input.stamp && stamp) jobs.push(pressStamp(stamp, { delay: input.rise ? 160 : 0 }));
  void flowNumbers(paper, input.counts);
  if (input.counts && rows.length) {
    rows.forEach((row, i) => {
      animate(
        row,
        { opacity: [0, 1], transform: ['translateY(6px)', 'translateY(0px)'] },
        { duration: 0.28, ease: EASE_OUT, delay: 0.28 + i * 0.04 },
      );
    });
  }
  await Promise.all(jobs);
}

/** Whether to play the entrance for this drawing of the result sheet. The page may redraw
 * (and its feedback surface remount) at any time; a heartbeat tells a redraw from an arrival:
 * if a result sheet was on the page within the last 1.6 s, this is the same visit. A new visit
 * plays it all; within a visit, only the review arriving after a wait rolls the readings. */
let lastSeen = 0;
let lastKey = '';
let beat: ReturnType<typeof setInterval> | undefined;
export function entranceFor(
  doc: Document,
  key: string,
  waiting: boolean,
): Omit<EntranceInput, 'stamp'> | null {
  const now = Date.now();
  const sameVisit = now - lastSeen < 1600;
  const before = lastKey;
  lastKey = key;
  lastSeen = now;
  if (!beat)
    beat = setInterval(() => {
      if (doc.querySelector('.result-paper')) lastSeen = Date.now();
      else {
        clearInterval(beat);
        beat = undefined;
      }
    }, 500);
  if (!sameVisit) return { rise: true, counts: !waiting };
  if (before !== key && before.endsWith(':waiting') && !waiting)
    return { rise: false, counts: true };
  return null;
}

/** Tick the waiting clock in place while the review is written; returns the stop function. */
export function tickClock(root: HTMLElement, since: () => number | undefined) {
  const id = setInterval(() => {
    const clock = root.querySelector<HTMLElement>('.result-wait__clock[data-elapsed]');
    const at = since();
    if (clock && at !== undefined) clock.textContent = clockWords((Date.now() - at) / 1000);
  }, 1000);
  return () => clearInterval(id);
}
