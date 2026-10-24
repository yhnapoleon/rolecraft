/** Hold to sign (plan §13.8): a pointer holds for a second while the signature line draws; a key
 * press needs no holding (keyboards never long-press) and draws the line in 400ms. Letting go early
 * cancels; the "keep holding" hint is offered only the first time. Timers only, no DOM: the sheet
 * draws the line from onStart and onCancel. */
export type HoldKind = 'pointer' | 'keyboard';
export type HoldState = 'idle' | 'holding' | 'signed';

export const HOLD_MS = 1000;
export const KEY_MS = 400;

export function holdToSign(handlers: {
  onStart(kind: HoldKind, ms: number): void;
  onCancel(firstTime: boolean): void;
  onComplete(): void;
}) {
  let state: HoldState = 'idle';
  let kind: HoldKind = 'pointer';
  let timer: ReturnType<typeof setTimeout> | null = null;
  let hinted = false;
  const clear = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return {
    state: () => state,
    press(how: HoldKind) {
      if (state !== 'idle') return;
      state = 'holding';
      kind = how;
      const ms = how === 'keyboard' ? KEY_MS : HOLD_MS;
      handlers.onStart(how, ms);
      timer = setTimeout(() => {
        timer = null;
        state = 'signed';
        handlers.onComplete();
      }, ms);
    },
    /** The pointer let go (or left). A key press runs to the end on its own. */
    release() {
      if (state !== 'holding' || kind === 'keyboard') return;
      clear();
      state = 'idle';
      handlers.onCancel(!hinted);
      hinted = true;
    },
    /** Back to idle after a refusal or an error, so the person can sign again. */
    reset() {
      clear();
      state = 'idle';
    },
  };
}
