// Loading and done for native keys (.btn), the two states CSS cannot reach on its own.
// Loading: the icon's place turns into a spinning dot; the width and the words stay.
// Done: the icon blurs into a check, which holds 1.6s and then blurs back.

const SPIN =
  '<svg class="key-spin" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-opacity=".25" stroke-width="2"/><path d="M14 8a6 6 0 0 0-6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
const CHECK =
  '<svg class="i i-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
const HOLD = 1600;
const EASE = 'cubic-bezier(.23,1,.32,1)';

const saved = new WeakMap<HTMLElement, { glyph: string; timer?: number }>();
const reduce = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function glyphOf(key: HTMLElement): HTMLElement {
  let g = key.querySelector<HTMLElement>(':scope > .key-glyph');
  if (g) return g;
  g = document.createElement('span');
  g.className = 'key-glyph';
  const icon = key.querySelector(':scope > svg');
  if (icon) icon.replaceWith(g);
  else key.prepend(g);
  if (icon) g.append(icon);
  return g;
}

function swap(g: HTMLElement, html: string) {
  const blur = !reduce();
  const old = [...g.children] as HTMLElement[];
  g.insertAdjacentHTML('beforeend', html);
  const next = html ? (g.lastElementChild as HTMLElement) : null;
  const out = blur
    ? [
        { opacity: 1, filter: 'blur(0px)' },
        { opacity: 0, filter: 'blur(2px)' },
      ]
    : [{ opacity: 1 }, { opacity: 0 }];
  for (const el of old)
    el.animate(out, { duration: 160, easing: EASE }).finished.then(() => el.remove());
  next?.animate([...out].reverse(), { duration: 160, easing: EASE });
}

export function setKeyState(key: HTMLElement, state: 'idle' | 'loading' | 'done'): void {
  const g = glyphOf(key);
  let s = saved.get(key);
  if (!s) {
    s = { glyph: g.innerHTML };
    saved.set(key, s);
  }
  clearTimeout(s.timer);
  if (state === 'loading') key.setAttribute('aria-busy', 'true');
  else key.removeAttribute('aria-busy');
  if (state === 'loading') swap(g, SPIN);
  else if (state === 'done') {
    swap(g, CHECK);
    s.timer = window.setTimeout(() => setKeyState(key, 'idle'), HOLD);
  } else {
    swap(g, s.glyph || '');
    saved.delete(key);
  }
}
