/** A rubber stamp pressed on paper: a small kicker ("Submitted", "Signed"), the words that were
 * decided (serif: they are the world's writing, D spec §5) and the moment. Shared by the result
 * page (206) and the engineer's sign-off (201).
 *
 * - tone: 'good' (green, a delivery that stands) or 'ink' (a signature, a neutral record).
 * - size: 'lg' result sheet, 'md' (default) cards and reports, 'sm' inline in a list.
 * - The stamp is drawn at rest. pressStamp() plays the press once; with reduced motion it is a
 *   160 ms fade in place. The press animates filter: blur() — an exception to the
 *   transform-and-opacity rule signed off in the plan (§2.4). */
import './stamp.css';

export type StampTone = 'good' | 'ink';
export type StampSize = 'sm' | 'md' | 'lg';
export interface StampInput {
  /** Small caps line above, e.g. "Submitted" / "已交付". */
  kicker: string;
  /** What was decided or signed, e.g. "Proceed with a limited scope". */
  text: string;
  /** The moment, as people read it ("21:19", "Oct 24"); omitted when unknown. */
  when?: string;
  tone?: StampTone;
  size?: StampSize;
  /** Starts invisible, for a press that follows at once (avoids a flash before it plays). */
  hidden?: boolean;
}

/** The stamp as an element. Marks: [data-stamp], data-tone, data-size. */
export function createStamp(doc: Document, input: StampInput): HTMLElement {
  const stamp = doc.createElement('div');
  stamp.className = 'rc-stamp';
  stamp.dataset.stamp = '';
  stamp.dataset.tone = input.tone ?? 'good';
  stamp.dataset.size = input.size ?? 'md';
  if (input.hidden) stamp.style.opacity = '0';
  const part = (cls: string, text: string) => {
    const node = doc.createElement('span');
    node.className = cls;
    node.textContent = text;
    stamp.append(node);
  };
  part('rc-stamp__kicker', input.kicker);
  part('rc-stamp__text', input.text);
  if (input.when) part('rc-stamp__when', input.when);
  return stamp;
}

const esc = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c);

/** The same stamp as an HTML string, for string templates (ui.js). */
export function stampHtml(input: StampInput): string {
  return `<div class="rc-stamp" data-stamp data-tone="${input.tone ?? 'good'}" data-size="${input.size ?? 'md'}"${input.hidden ? ' style="opacity:0"' : ''}><span class="rc-stamp__kicker">${esc(input.kicker)}</span><span class="rc-stamp__text">${esc(input.text)}</span>${input.when ? `<span class="rc-stamp__when">${esc(input.when)}</span>` : ''}</div>`;
}

/** Press the stamp once: from 1.15× and −4° to rest (−2°), blur to sharp, a 520 ms spring.
 * Reduced motion: a 160 ms fade, no scale, no turn. Resolves when it has landed. */
export async function pressStamp(stamp: HTMLElement, options: { delay?: number } = {}) {
  const view = stamp.ownerDocument.defaultView;
  const reduced = view?.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
  const delay = options.delay ?? 0;
  if (reduced) {
    const fade = stamp.animate([{ opacity: 0 }, { opacity: 1 }], {
      duration: 160,
      delay,
      easing: 'ease',
      fill: 'both',
    });
    await fade.finished.catch(() => {});
    stamp.style.opacity = '';
    fade.cancel();
    return;
  }
  try {
    const { animate } = await import('motion');
    await animate(
      stamp,
      {
        opacity: [0, 1],
        transform: ['rotate(-4deg) scale(1.15)', 'rotate(-2deg) scale(1)'],
        filter: ['blur(2px)', 'blur(0px)'],
      },
      { type: 'spring', duration: 0.52, bounce: 0.18, delay: delay / 1000 },
    ).finished;
  } catch {
    // Without the library the stamp simply shows at rest.
  }
  stamp.style.opacity = '';
  stamp.style.transform = '';
  stamp.style.filter = '';
}
