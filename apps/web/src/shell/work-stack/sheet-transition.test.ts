import { afterEach, expect, it, vi } from 'vitest';
import { flySheet } from './sheet-transition';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
it('waits for the island without requestAnimationFrame while rendering is paused', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('matchMedia', () => ({ matches: false }));
  const sourceStyle = { viewTransitionName: '', removeProperty: vi.fn() };
  const target = { style: { viewTransitionName: '', removeProperty: vi.fn() } };
  let mounted = false;
  let update: Promise<void> = Promise.resolve();
  let finish = () => {};
  const finished = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const doc = {
    documentElement: { dataset: {} },
    querySelector: () => (mounted ? target : null),
    startViewTransition: (callback: () => Promise<void>) => {
      update = callback();
      return { ready: update, updateCallbackDone: update, finished, skipTransition: finish };
    },
  };
  flySheet({ ownerDocument: doc, style: sourceStyle } as unknown as HTMLElement, () => {
    setTimeout(() => {
      mounted = true;
    }, 20);
  });
  await vi.advanceTimersByTimeAsync(48);
  await update;
  expect(target.style.viewTransitionName).toBe('aipm-paper');
  finish();
  await finished;
  expect(target.style.removeProperty).toHaveBeenCalledWith('view-transition-name');
});
it('switches directly with reduced motion or without browser support', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true }));
  const startViewTransition = vi.fn();
  const open = vi.fn();
  flySheet({ ownerDocument: { startViewTransition } } as unknown as HTMLElement, open);
  expect(startViewTransition).not.toHaveBeenCalled();
  flySheet({ ownerDocument: {} } as HTMLElement, open);
  expect(open).toHaveBeenCalledTimes(2);
});
