import { flushSync } from 'react-dom';

let active: ViewTransition | undefined;
/** Only the clicked thumbnail and the new paper share a name; the room stays still. */
export function flySheet(source: HTMLElement, open: () => void) {
  active?.skipTransition();
  const doc = source.ownerDocument;
  if (!doc.startViewTransition || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    open();
    return;
  }
  const name = 'aipm-paper';
  let target: HTMLElement | null = null;
  source.style.viewTransitionName = name;
  doc.documentElement.dataset.aipmFlying = '';
  const transition = doc.startViewTransition(async () => {
    source.style.removeProperty('view-transition-name');
    flushSync(open);
    // The island mounts after the native stage. Wait for its paper, not its network content.
    for (let frame = 0; frame < 30; frame++) {
      target = doc.querySelector<HTMLElement>(
        '[data-aipm-main] .aipm-sheet:not(.aipm-sheet--loading)',
      );
      if (target) break;
      // Rendering (and rAF) is paused inside a view-transition update callback.
      await new Promise<void>((resolve) => setTimeout(resolve, 16));
    }
    if (target) target.style.viewTransitionName = name;
  });
  active = transition;
  const clean = () => {
    source.style.removeProperty('view-transition-name');
    target?.style.removeProperty('view-transition-name');
    if (active === transition) {
      active = undefined;
      delete doc.documentElement.dataset.aipmFlying;
    }
  };
  void transition.ready.catch(() => {});
  void transition.finished.then(clean, clean);
}
