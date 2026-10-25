import { describe, expect, it, vi } from 'vitest';
import { createPageTransition } from './view-transition';

const turn = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('page transitions', () => {
  it('keeps the DOM update when the browser cannot prepare the animation, without unhandled rejections', async () => {
    const update = vi.fn();
    const document = {
      visibilityState: 'visible',
      startViewTransition: (callback: () => void) => {
        callback();
        return {
          ready: Promise.reject(
            new DOMException(
              'Transition was aborted because of invalid state',
              'InvalidStateError',
            ),
          ),
          updateCallbackDone: Promise.resolve(),
          finished: Promise.resolve(),
          skipTransition: vi.fn(),
        };
      },
    } as unknown as Document;
    createPageTransition(document, { matches: false }).run(update);
    await turn();
    expect(update).toHaveBeenCalledTimes(1);
    // Vitest fails on any unhandled rejection, including independent ready / finished promises.
  });
});

function pending() {
  let resolve!: () => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<void>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function harness() {
  const transitions: ReturnType<typeof makeTransition>[] = [];
  function makeTransition() {
    const ready = pending(),
      done = pending(),
      finished = pending();
    const transition = {
      ready: ready.promise,
      updateCallbackDone: done.promise,
      finished: finished.promise,
      skipTransition: vi.fn(() => {
        ready.reject(new DOMException('Skipped', 'AbortError'));
      }),
    };
    return { ready, done, finished, transition };
  }
  const doc = {
    visibilityState: 'visible',
    startViewTransition: vi.fn((update: () => void) => {
      const item = makeTransition();
      transitions.push(item);
      try {
        update();
        item.done.resolve();
      } catch (error) {
        item.done.reject(error);
        item.ready.reject(error);
        item.finished.reject(error);
      }
      return item.transition;
    }),
  };
  const reduced = { matches: false };
  const controller = createPageTransition(doc as unknown as Document, reduced);
  return { doc, reduced, transitions, run: controller.run, controller };
}

it('does not let an older transition clear the newer one during rapid navigation', async () => {
  const { run, transitions } = harness();
  const update = vi.fn();
  run(update);
  run(update);
  expect(transitions[0].transition.skipTransition).toHaveBeenCalledTimes(1);
  transitions[0].finished.resolve();
  await turn();
  run(update);
  expect(transitions[1].transition.skipTransition).toHaveBeenCalledTimes(1);
  transitions[1].finished.resolve();
  transitions[2].ready.resolve();
  transitions[2].finished.resolve();
  await turn();
  run(update);
  expect(transitions[2].transition.skipTransition).not.toHaveBeenCalled();
  transitions[3].ready.resolve();
  transitions[3].finished.resolve();
  expect(update).toHaveBeenCalledTimes(4);
});

it.each(['unsupported', 'reduced', 'hidden'])(
  'updates once without starting an animation when %s',
  (mode) => {
    const { doc, reduced, run } = harness();
    const start = doc.startViewTransition;
    if (mode === 'unsupported')
      Object.defineProperty(doc, 'startViewTransition', { value: undefined });
    if (mode === 'reduced') reduced.matches = true;
    if (mode === 'hidden') doc.visibilityState = 'hidden';
    const update = vi.fn();
    run(update);
    expect(update).toHaveBeenCalledTimes(1);
    expect(start).not.toHaveBeenCalled();
  },
);

it('finishes the current animation and updates immediately when the page becomes hidden', async () => {
  const { doc, run, transitions } = harness();
  const update = vi.fn();
  run(update);
  doc.visibilityState = 'hidden';
  run(update);
  transitions[0].finished.resolve();
  await turn();
  expect(update).toHaveBeenCalledTimes(2);
  expect(doc.startViewTransition).toHaveBeenCalledTimes(1);
  expect(transitions[0].transition.skipTransition).toHaveBeenCalledTimes(1);
});

it('reports an actual rendering failure once, consumes all three rejections and permits the next transition', async () => {
  const report = vi.fn();
  vi.stubGlobal('reportError', report);
  try {
    const { run, transitions } = harness();
    const error = new Error('Rendering failed');
    const update = vi.fn(() => {
      throw error;
    });
    run(update);
    await turn();
    expect(report).toHaveBeenCalledExactlyOnceWith(error);
    expect(update).toHaveBeenCalledTimes(1);
    run(() => {});
    expect(transitions[0].transition.skipTransition).not.toHaveBeenCalled();
    transitions[1].ready.resolve();
    transitions[1].finished.resolve();
  } finally {
    vi.unstubAllGlobals();
  }
});

it('runs delivery cleanup and keyboard focus immediately without an animated transition', () => {
  const { controller, reduced } = harness();
  reduced.matches = true;
  const cleanup = vi.fn(),
    focus = vi.fn();
  controller.run(() => {});
  controller.afterFinished(cleanup);
  controller.afterUpdate(focus);
  expect(cleanup).toHaveBeenCalledTimes(1);
  expect(focus).toHaveBeenCalledTimes(1);
});

it('waits for the DOM before focusing and for animation completion before delivery cleanup', async () => {
  const { controller, transitions } = harness();
  const cleanup = vi.fn(),
    focus = vi.fn();
  controller.run(() => {});
  controller.afterFinished(cleanup);
  controller.afterUpdate(focus);
  expect(focus).not.toHaveBeenCalled();
  await turn();
  expect(focus).toHaveBeenCalledTimes(1);
  expect(cleanup).not.toHaveBeenCalled();
  controller.skip();
  transitions[0].finished.resolve();
  await turn();
  expect(cleanup).toHaveBeenCalledTimes(1);
  expect(transitions[0].transition.skipTransition).toHaveBeenCalledTimes(1);
});

it('cleans up a failed delivery transition without focusing an unsuccessfully updated view', async () => {
  const { controller } = harness();
  const cleanup = vi.fn(),
    focus = vi.fn(),
    report = vi.fn();
  const error = new Error('Render failed');
  vi.stubGlobal('reportError', report);
  try {
    controller.run(() => {
      throw error;
    });
    controller.afterFinished(cleanup);
    controller.afterUpdate(focus);
    await turn();
    expect(cleanup).toHaveBeenCalledTimes(1);
    expect(focus).not.toHaveBeenCalled();
    expect(report).toHaveBeenCalledExactlyOnceWith(error);
  } finally {
    vi.unstubAllGlobals();
  }
});

it('resolves once the new page is drawn, with or without an animation, and never rejects', async () => {
  const { run, reduced } = harness();
  const drawn: string[] = [];
  await run(() => drawn.push('animated'));
  expect(drawn).toEqual(['animated']);
  reduced.matches = true;
  await run(() => drawn.push('instant'));
  expect(drawn).toEqual(['animated', 'instant']);
  reduced.matches = false;
  const report = vi.fn();
  vi.stubGlobal('reportError', report);
  try {
    const error = new Error('render failed');
    const failing = run(() => {
      throw error;
    });
    await expect(failing).resolves.toBeUndefined();
    await turn();
    expect(report).toHaveBeenCalledExactlyOnceWith(error);
  } finally {
    vi.unstubAllGlobals();
  }
});
