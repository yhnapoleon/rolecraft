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
    run: act ? () => runAction(act.action) : undefined,
    long: !!(act || opts?.undo),
  });
}

/* ---------- for ui.js, whose undo and actions are functions ---------- */

let last: string | number | null = null;

/** A toast whose action is a callback. Replaces the toast on screen (one at a time). */
export function showToast(
  text: string,
  opts: { label?: string; run?: () => void; long?: boolean; lead?: string } = {},
): void {
  if (last != null) sonner.dismiss(last);
  const run = opts.run;
  last = sonner(text, {
    duration: opts.long || run ? LONG : SHORT,
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
}

/** Withdraws the toast on screen (an undo belongs to the page it was offered on). */
export function dismissToasts(): void {
  sonner.dismiss();
  last = null;
}
