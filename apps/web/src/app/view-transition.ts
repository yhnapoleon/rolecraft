/** Owns the page transition lifecycle; DOM updates still run when animation is skipped. */
export function createPageTransition(
  document: Document,
  reduceMotion: Pick<MediaQueryList, 'matches'>,
) {
  let activeTransition: ViewTransition | null = null;
  const skip = () => {
    if (activeTransition) {
      activeTransition.skipTransition();
      activeTransition = null;
    }
  };
  // Resolves once the new page is drawn (and, inside a practice, speaks its language).
  const run = (update: () => void): Promise<void> => {
    skip();
    if (
      !document.startViewTransition ||
      reduceMotion.matches ||
      document.visibilityState === 'hidden'
    ) {
      update();
      return Promise.resolve();
    }
    const transition = document.startViewTransition(update);
    activeTransition = transition;
    const clear = () => {
      if (activeTransition === transition) activeTransition = null;
    };
    // A skipped/invalid snapshot rejects ready even when the DOM update succeeds.
    void transition.ready.catch(() => {});
    // Keep real rendering failures observable, once, independently of animation failures.
    void transition.updateCallbackDone.catch((error) => reportError(error));
    // finally() would leave its own rejected promise unhandled on a failed update.
    void transition.finished.then(clear, clear);
    return transition.updateCallbackDone.catch(() => {});
  };
  const afterFinished = (callback: () => void) => {
    if (activeTransition)
      void activeTransition.finished.then(callback, callback).catch((error) => reportError(error));
    else callback();
  };
  const afterUpdate = (callback: () => void) => {
    if (activeTransition)
      void activeTransition.updateCallbackDone
        .then(callback, () => {})
        .catch((error) => reportError(error));
    else callback();
  };
  return { run, skip, afterFinished, afterUpdate };
}
