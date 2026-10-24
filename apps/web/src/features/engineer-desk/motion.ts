/** The engineer screens' moving parts, on Motion's native `animate()` (WAAPI under the hood):
 * three durations (160 / 280 / 520ms), the shell's spring and ease-out. Transform and opacity only,
 * except the two signature moments named below (the signature line and the stamp). Reduced motion:
 * a 160ms fade, never movement. Keyboard-started actions are not animated at all (`byKeyboard`). */
import { animate } from 'motion/mini';

export const FAST = 0.16;
export const MID = 0.28;
export const SLOW = 0.52;
export const EASE_OUT = [0.23, 1, 0.32, 1] as const;
export const EASE = [0.32, 0.72, 0, 1] as const;

// The shell's --spring (styles.css), sampled the same way; Motion turns a function into linear().
const SPRING = [
  0, 0.083, 0.245, 0.415, 0.565, 0.684, 0.775, 0.842, 0.891, 0.925, 0.949, 0.965, 0.977, 0.984,
  0.99, 0.993, 0.995, 0.997, 1,
];
export const spring = (t: number) => {
  const x = Math.min(1, Math.max(0, t)) * (SPRING.length - 1);
  const i = Math.floor(x);
  return i >= SPRING.length - 1 ? 1 : SPRING[i] + (SPRING[i + 1] - SPRING[i]) * (x - i);
};

export function reducedMotion(): boolean {
  try {
    return matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

// The last input decides: a key press starts nothing that moves (plan §13.1).
let keyboard = false;
if (typeof window !== 'undefined') {
  window.addEventListener(
    'keydown',
    (e) => {
      if (!e.metaKey && !e.ctrlKey) keyboard = true;
    },
    true,
  );
  window.addEventListener(
    'pointerdown',
    () => {
      keyboard = false;
    },
    true,
  );
}
export const byKeyboard = () => keyboard;

type Frames = Record<string, string[] | number[]>;
type Options = { duration?: number; delay?: number; ease?: unknown };

/** One animation; under reduced motion only a 160ms fade-in (when the frames fade at all). */
export function move(el: Element | null | undefined, frames: Frames, options: Options = {}) {
  if (!el) return null;
  if (reducedMotion()) {
    if (!frames.opacity) return null;
    return animate(el, { opacity: [0, 1] }, { duration: FAST });
  }
  // biome-ignore lint/suspicious/noExplicitAny: Motion's option types are wide unions
  return animate(el, frames as any, { duration: MID, ease: EASE_OUT, ...options } as any);
}

/** A row or card arriving: fades up from a few pixels below (or above with a negative y). */
export function arrive(el: Element | null | undefined, y = 4, options: Options = {}) {
  return move(el, { opacity: [0, 1], transform: [`translateY(${y}px)`, 'translateY(0)'] }, options);
}

/** Several arrivals, 40ms apart. */
export function arriveAll(els: readonly Element[], y = -6, gap = 0.04) {
  els.forEach((el, i) => {
    arrive(el, y, { ease: spring, delay: i * gap });
  });
}

/** A mark lighting up: scale .8 → 1 in 160ms. */
export function light(el: Element | null | undefined, delay = 0) {
  return move(el, { transform: ['scale(.8)', 'scale(1)'] }, { duration: FAST, delay });
}

/** One pulse of the Agent dot: a ring grows to 2.2× and fades (520ms), never looping. */
export function pulse(ring: Element | null | undefined) {
  if (!ring || reducedMotion()) return null;
  return animate(
    ring,
    { transform: ['scale(1)', 'scale(2.2)'], opacity: [0.5, 0] },
    { duration: SLOW, ease: EASE_OUT as unknown as [number, number, number, number] },
  );
}

/** Signature moment (exception, plan §13.3): a ruled line drawn left to right with clip-path. */
export function drawLine(line: Element | null | undefined, ms: number, delay = 0) {
  if (!line || reducedMotion()) return null;
  return animate(
    line,
    { clipPath: ['inset(0 100% 0 0)', 'inset(0 0% 0 0)'] },
    { duration: ms / 1000, delay, ease: EASE_OUT as unknown as [number, number, number, number] },
  );
}

/** Label swap on a key: the old words blur out, the new ones fade in (shell §2.4). */
export function swapLabel(node: HTMLElement, text: string) {
  if (node.textContent === text) return;
  if (reducedMotion() || !node.isConnected || !node.textContent) {
    node.textContent = text;
    return;
  }
  const out = animate(
    node,
    { opacity: [1, 0], filter: ['blur(0px)', 'blur(2px)'] },
    {
      duration: 0.12,
    },
  );
  out.then(() => {
    node.textContent = text;
    animate(node, { opacity: [0, 1], filter: ['blur(2px)', 'blur(0px)'] }, { duration: FAST });
  });
}
