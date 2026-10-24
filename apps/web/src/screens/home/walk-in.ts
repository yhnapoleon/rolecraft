/** The way in: on "Take this on" the brief's three task slips lift off the paper and the key waits
 * (loading). The person stays on the brief while the practice opens: the board is drawn
 * underneath a still copy of the brief until its three cards exist, then the copy fades and each
 * slip flies to its card, 40ms apart, and hands over to it. Plays once, on the way in.
 *
 * - Nothing on the board ever shows dimmed with slips hanging over it.
 * - Over budget (the practice took longer than ~2.5s to open, or the cards did not come): no
 *   flight; the board fades in as itself.
 * - Reduced motion: no lift, no flight; the board fades in over 160ms.
 * - Targets are found by text: any element with a task id whose text starts with the slip's.
 * (Exception noted, 199 §2.4: a signature move; it travels further than 6px on purpose.) */

const BUDGET_MS = 2500;
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)';
const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const norm = (s: string | null | undefined) => (s || '').replace(/\s+/g, ' ').trim();
const frame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));
function spring(): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue('--spring').trim();
  return v && CSS.supports('animation-timing-function', v) ? v : EASE_OUT;
}
function prepareCopy(node: HTMLElement) {
  // Copies never own the live page's identities, including its transition snapshots.
  // A task can open while the entrance cover still carries the old case-title.
  for (const n of [node, ...node.querySelectorAll<HTMLElement>('*')]) {
    n.removeAttribute('id');
    n.style.viewTransitionName = 'none';
  }
}
const fade = (el: Element, from: number, to: number, delay = 0) =>
  el
    .animate([{ opacity: from }, { opacity: to }], {
      duration: 160,
      delay,
      easing: 'ease',
      fill: 'forwards',
    })
    .finished.catch(() => {});

/** Fade the new page in over 160ms, without moving (reduced motion, and the fallbacks). */
export function fadeIn() {
  const main = document.getElementById('main');
  if (main && typeof main.animate === 'function')
    main.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: 'ease' });
}

export async function walkIn(o: {
  /** The "Take this on" key inside the brief. */
  trigger: HTMLElement;
  /** Turn the brief's held state on or off (key loading, slips lifted, no "existing" footer). */
  hold: (on: boolean) => void;
  /** Open the practice. */
  open: () => Promise<void>;
  /** Draw the board. */
  show: () => void;
}): Promise<void> {
  const brief = o.trigger.closest('.hm-brief');
  const slips = brief ? [...brief.querySelectorAll<HTMLElement>('.hm-seed')] : [];
  const flying = !reduced() && typeof document.body.animate === 'function' && slips.length > 0;
  const t0 = performance.now();

  // Lift: copies of the slips go into a layer above the page; the page itself holds.
  const layer = document.createElement('div');
  layer.className = 'hm-flight';
  layer.setAttribute('aria-hidden', 'true');
  const ghosts = flying
    ? slips.map((source, i) => {
        const from = source.getBoundingClientRect();
        const el = source.cloneNode(true) as HTMLElement;
        el.removeAttribute('style');
        prepareCopy(el);
        el.inert = true;
        Object.assign(el.style, {
          left: `${from.left}px`,
          top: `${from.top}px`,
          width: `${from.width}px`,
          height: `${from.height}px`,
        });
        layer.append(el);
        el.animate([{ transform: 'none' }, { transform: 'translateY(-4px) scale(1.015)' }], {
          duration: 280,
          delay: i * 40,
          easing: EASE_OUT,
          fill: 'forwards',
        });
        el.classList.add('is-lifted');
        return { el, from, text: norm(source.querySelector('.hm-seed__text')?.textContent) };
      })
    : [];
  if (flying) {
    document.body.append(layer);
    document.body.classList.add('hm-lifting');
  }
  const end = () => {
    layer.remove();
    document.body.classList.remove('hm-lifting');
  };
  o.hold(true);

  try {
    await o.open();
  } catch (err) {
    end();
    o.hold(false);
    throw err;
  }

  const giveUp = async () => {
    o.hold(false);
    o.show();
    fadeIn();
    await Promise.all([...layer.children].map((n) => fade(n, 1, 0)));
    end();
  };
  if (!flying || performance.now() - t0 > BUDGET_MS) return giveUp();

  // The cover: a still copy of the brief as it is now, so the board can load underneath.
  const app = document.getElementById('app');
  const cover = document.createElement('div');
  cover.className = 'hm-cover';
  if (app) {
    const copy = app.cloneNode(true) as HTMLElement;
    prepareCopy(copy);
    copy.style.transform = `translateY(${-window.scrollY}px)`;
    cover.append(copy);
  }
  layer.prepend(cover);
  o.hold(false);
  o.show();

  // The board's task area (204: [data-board-tasks]); before that lands, the whole page.
  const find = () =>
    ghosts.map(
      (g) =>
        [
          ...(
            document.querySelector('[data-board-tasks]') ?? document
          ).querySelectorAll<HTMLElement>('[data-task-id]'),
        ].find(
          (n) =>
            !layer.contains(n) &&
            norm(n.querySelector('.card-title')?.textContent || n.textContent).startsWith(g.text),
        ) || null,
    );
  let to = find();
  while (to.some((t) => !t) && performance.now() - t0 < BUDGET_MS) {
    await frame();
    to = find();
  }
  if (to.some((t) => !t)) {
    // The cards did not come in time: the board shows as itself.
    await Promise.all([...layer.children].map((n) => fade(n, 1, 0)));
    end();
    return;
  }

  // All three cards must land inside the viewport, 24px clear of its bottom edge: bring the last
  // one in, under the cover, so the slips fly to cards that no longer move. The board scrolls in
  // #main, which scrollIntoView finds by itself. It stays there afterwards (agreed with 204).
  const last = to.at(-1) as HTMLElement;
  last.style.scrollMarginBottom = '24px';
  last.scrollIntoView({ block: 'nearest' });
  last.style.scrollMarginBottom = '';
  const first = to[0] as HTMLElement;
  if (first.getBoundingClientRect().top < 64) first.scrollIntoView({ block: 'center' });
  await frame();

  const ease = spring();
  // The cover blurs as it fades, so the brief and the board do not read as two sharp pages.
  cover
    .animate(
      [
        { opacity: 1, filter: 'blur(0)' },
        { opacity: 0, filter: 'blur(2px)' },
      ],
      { duration: 160, easing: 'ease', fill: 'forwards' },
    )
    .finished.catch(() => {});
  const flights = ghosts.map((g, i) => {
    const t = to[i] as HTMLElement;
    const r = t.getBoundingClientRect();
    const s = r.width / g.from.width;
    t.style.opacity = '0';
    const fly = g.el.animate(
      [
        { transform: 'translateY(-4px) scale(1.015)' },
        { transform: `translate(${r.left - g.from.left}px, ${r.top - g.from.top}px) scale(${s})` },
      ],
      { duration: 520, delay: i * 40, easing: ease, fill: 'forwards' },
    );
    // Hand over in the last stretch: the slip blurs away as the card takes its place.
    const hand = g.el.animate(
      [
        { opacity: 1, filter: 'blur(0)' },
        { opacity: 0, filter: 'blur(2px)' },
      ],
      { duration: 160, delay: i * 40 + 400, easing: 'ease', fill: 'forwards' },
    );
    const show = t.animate([{ opacity: 0 }, { opacity: 1 }], {
      duration: 160,
      delay: i * 40 + 400,
      easing: 'ease',
      fill: 'backwards',
    });
    return Promise.all([fly.finished, hand.finished, show.finished]).finally(() => {
      t.style.opacity = '';
    });
  });
  await Promise.allSettled(flights);
  end();
}
