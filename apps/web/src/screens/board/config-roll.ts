// The product bar's readings when the pilot settings move on (Config v1 → v2, Participants
// 20 → 15, e.g. after the engineering review is applied): each figure that changed rolls to its
// new value with number-flow and glows once in green, fading back to ink in 520ms (D §4, as the
// conditions do). Reduced motion: the value is simply replaced.
import 'number-flow';
import type NumberFlow from 'number-flow';

const GLOW_MS = 520;
const shown = new Map<string, number | string>();
const changed = new Map<string, { to: number | string; at: number }>();
const keyOf = (attemptId: string, reading: string) => `${attemptId}|${reading}`;

/** The value last shown for this reading (kept while a dialog covers the bar). */
export const readingShown = (attemptId: string, reading: string) =>
  shown.get(keyOf(attemptId, reading));

/**
 * One reading's markup. The first draw after its value moved rolls the figure (numbers) or just
 * glows (words); redraws during the glow keep glowing from where it was (a negative delay).
 */
export function reading(attemptId: string, name: string, value: number | string, prefix = '') {
  const k = keyOf(attemptId, name);
  const before = shown.get(k);
  shown.set(k, value);
  if (before != null && before !== value) {
    changed.set(k, { to: value, at: Date.now() });
    return typeof value === 'number' && typeof before === 'number'
      ? `<span class="pb-lit">${prefix}<number-flow class="pb-roll" data-roll data-from="${before}" data-to="${value}">${before}</number-flow></span>`
      : `<span class="pb-lit">${prefix}${value}</span>`;
  }
  const c = changed.get(k);
  const age = c && c.to === value ? Date.now() - c.at : Number.POSITIVE_INFINITY;
  return age < GLOW_MS
    ? `<span class="pb-lit" style="--lit-age: ${age}ms">${prefix}${value}</span>`
    : `${prefix}${value}`;
}

/** After the bar is drawn: roll the figures that just changed. */
export function playReadings() {
  for (const el of document.querySelectorAll<NumberFlow & HTMLElement>('[data-roll]')) {
    const from = Number(el.dataset.from);
    const to = Number(el.dataset.to);
    el.removeAttribute('data-roll');
    el.animated = false;
    el.update(from);
    requestAnimationFrame(() => {
      el.animated = true;
      el.update(to);
    });
  }
}
