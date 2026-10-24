// Toasts, through one global Sonner toaster (shell/toaster.tsx), at the bottom centre of the
// main screen, clear of the right rail's input. A plain note stays 3.2s; one that can be undone
// or acted on stays 6.5s. At most one action.
import { createElement } from 'react';
import { toast as sonner } from 'sonner';
import { runAction } from './registry';

const SHORT = 3200;
const LONG = 6500;

export function toast(
  text: string,
  opts?: { action?: { label: string; action: string }; undo?: boolean },
): void {
  const act = opts?.action;
  showToast(text, {
    label: act?.label,
    run: act
      ? () => {
          runAction(act.action).catch((err: unknown) =>
            showToast(err instanceof Error ? err.message : String(err)),
          );
        }
      : undefined,
    long: !!(act || opts?.undo),
  });
}

/* ---------- for ui.js, whose undo and actions are functions ---------- */

let last: string | number | null = null;

/*
 * The page's old #toast element stays as an invisible mirror of the toast on screen: its text,
 * and the class "visible" while the toast is up. Browser regression suites read it; people never
 * see it, and screen readers hear the toast once (aria-hidden here).
 */
function mirror(): HTMLElement | null {
  const el = document.getElementById('toast');
  if (el && !el.dataset.mirror) {
    el.dataset.mirror = '1';
    el.className = 'toast-mirror';
    el.removeAttribute('role');
    el.setAttribute('aria-hidden', 'true');
  }
  return el;
}
function mirrorShow(id: string | number, text: string, label?: string) {
  const el = mirror();
  if (!el) return;
  el.dataset.toastId = String(id);
  el.textContent = label ? `${text} ${label}` : text;
  el.classList.add('visible');
}
function mirrorHide(id: string | number) {
  const el = mirror();
  if (el && el.dataset.toastId === String(id)) el.classList.remove('visible');
}

/** A toast whose action is a callback. Replaces the toast on screen (one at a time). */
export function showToast(
  text: string,
  opts: { label?: string; run?: () => void; long?: boolean; lead?: string } = {},
): void {
  if (last != null) sonner.dismiss(last);
  const run = opts.run;
  const id = `t${Date.now()}${Math.random().toString(36).slice(2, 6)}`;
  last = sonner(text, {
    id,
    duration: opts.long || run ? LONG : SHORT,
    onDismiss: () => mirrorHide(id),
    onAutoClose: () => mirrorHide(id),
    // lead: trusted markup from our own templates (an avatar, an icon).
    icon: opts.lead
      ? createElement('span', {
          className: 'rc-toast-lead',
          ref: (node: HTMLSpanElement | null) => {
            if (node) node.innerHTML = opts.lead ?? '';
          },
        })
      : undefined,
    action:
      run && opts.label
        ? {
            label: opts.label,
            onClick: () => {
              run();
            },
          }
        : undefined,
  });
  mirrorShow(id, text, run ? opts.label : undefined);
}

/** Withdraws the toast on screen (an undo belongs to the page it was offered on). */
export function dismissToasts(): void {
  sonner.dismiss();
  last = null;
  mirror()?.classList.remove('visible');
}
