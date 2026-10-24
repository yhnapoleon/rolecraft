// The board's few choreographed moments, played once each:
// - the world's light: when a policy change arrives, the band's line draws, then the amber
//   marks it left behind hang on one after another (40ms apart);
// - the brief rolling into one line: the board below moves up by FLIP (280ms);
// - the rail pushing a chat in where the people were.
const reduce = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const seenChange = new Map<string, number>();
const ARRIVAL_MS = 1600;

/**
 * How long ago this practice first showed this change (ms), while its arrival is still
 * playing; null afterwards. A redraw during the arrival (the policy text loads a moment later)
 * passes this on as a negative delay, so the line keeps drawing from where it was.
 */
export function arrivalAge(attemptId: string, key: string): number | null {
  const k = `${attemptId}@${key}`;
  const first = seenChange.get(k);
  if (first == null) {
    seenChange.set(k, Date.now());
    return 0;
  }
  const age = Date.now() - first;
  return age < ARRIVAL_MS ? age : null;
}

// The marks a policy change leaves: the lagging index reading, the cards whose tests predate it,
// the documents with a new version. Native cards mount a moment after the board, so the
// arrival looks again shortly after and numbers the late ones on from the first.
const AMBER = '.pb-gauge.warn .pb-v, .kanban .flag-chip.warn, .doc-row .tag.new';
let amberCount = 0;
let amberUntil = 0;
let amberStart = 0;

/** After the draw that carries an arriving change: hang the amber marks one after another. */
export function staggerAmber(age = 0) {
  if (reduce()) return;
  amberCount = 0;
  amberStart = Date.now() - age;
  amberUntil = amberStart + 900;
  markAmber();
  window.setTimeout(markAmber, 160);
  window.setTimeout(markAmber, 420);
}
function markAmber() {
  if (Date.now() > amberUntil) return;
  for (const el of document.querySelectorAll<HTMLElement>(AMBER)) {
    if (el.dataset.amberDone) continue;
    el.dataset.amberDone = '1';
    el.style.setProperty('--amber-i', String(amberCount++));
    el.style.setProperty('--amber-age', `${Date.now() - amberStart}ms`);
    el.setAttribute('data-amber-arrive', '');
  }
}

let flipFrom: Map<string, number> | null = null;

/** Before a redraw that rolls or unrolls the brief: remember where each board section was. */
export function captureBoard() {
  if (reduce()) return;
  flipFrom = new Map(
    [...document.querySelectorAll<HTMLElement>('.board > [data-flip]')].map((el) => [
      el.dataset.flip as string,
      el.getBoundingClientRect().top,
    ]),
  );
}

/** After that redraw: each section starts where it was and settles into place. */
export function playBoard() {
  const from = flipFrom;
  flipFrom = null;
  if (!from) return;
  for (const el of document.querySelectorAll<HTMLElement>('.board > [data-flip]')) {
    const top = from.get(el.dataset.flip as string);
    if (top == null) continue;
    const dy = top - el.getBoundingClientRect().top;
    if (Math.abs(dy) < 1) continue;
    el.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], {
      duration: 280,
      easing: 'cubic-bezier(.23,1,.32,1)',
    });
  }
}

let push: 'in' | 'back' | null = null;
/** The rail's next draw pushes the chat in (in) or the people back (back). */
export const railPush = (dir: 'in' | 'back') => {
  push = dir;
};
export function takeRailPush() {
  const p = push;
  push = null;
  return p ? (p === 'in' ? 'rail-push-in' : 'rail-push-back') : '';
}
