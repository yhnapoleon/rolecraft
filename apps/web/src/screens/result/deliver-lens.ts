/** Decision 20: the recognition lens is open in the submission dialog by default. The lens is a
 * per-viewer switch shared by the whole page, so the dialog opens it for itself and closes it
 * again when the dialog closes — unless the person used the switch in the dialog, which is then
 * remembered for next time. Pages outside the dialog keep their own default (off). */
import { lensOn, setLens } from '../../features/recognition-native/lens';

const DECLINED = 'rolecraft.lens.deliveryOff';

export function openLensForDelivery(sheet: HTMLDialogElement) {
  let declined = false;
  try {
    declined = localStorage.getItem(DECLINED) === '1';
  } catch {
    // Storage blocked: open it, as for a first visit.
  }
  const opened = !lensOn() && !declined;
  if (opened) setLens(true);
  let touched = false;
  sheet.querySelector('[data-lens-switch]')?.addEventListener('click', () => {
    // After the shell's own handler has flipped the switch.
    setTimeout(() => {
      touched = true;
      try {
        localStorage.setItem(DECLINED, lensOn() ? '0' : '1');
      } catch {
        // Not remembered; it still applies now.
      }
    });
  });
  // Closing the dialog, or leaving the page with it open, gives the page its own setting back.
  const restore = () => {
    if (opened && !touched) setLens(false);
    window.removeEventListener('pagehide', restore);
  };
  sheet.addEventListener('close', restore, { once: true });
  window.addEventListener('pagehide', restore);
}
