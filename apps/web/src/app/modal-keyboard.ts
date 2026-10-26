/** Keep modal keyboard handling ahead of workspace navigation. */
export function activeModal(doc: Document): HTMLElement | undefined {
  return [...doc.querySelectorAll<HTMLElement>('dialog[open], [role="dialog"][aria-modal="true"]')]
    .filter(node => !node.hidden).at(-1);
}

/** The browser owns Escape inside a modal. If focus escaped, deliver cancel to it. */
export function modalOwnsEscape(event: KeyboardEvent, doc: Document): boolean {
  if (event.key !== 'Escape') return false;
  const modal = activeModal(doc);
  if (!modal) return false;
  if (!modal.contains(event.target as Node)) {
    event.preventDefault();
    const cancel = new Event('cancel', { cancelable: true });
    if (modal.dispatchEvent(cancel) && modal instanceof HTMLDialogElement) modal.close();
  }
  return true;
}

/** Explicit boundaries also cover initial heading focus and a lost BODY focus. */
export function containModalTab(event: KeyboardEvent, modal: HTMLElement): void {
  if (event.key !== 'Tab') return;
  const stops = [...modal.querySelectorAll<HTMLElement>(
    'button, a[href], input, select, textarea, summary, [tabindex]',
  )].filter(node => node.tabIndex >= 0 && !node.matches(':disabled') &&
    !node.closest('[hidden], [inert]') && node.checkVisibility());
  const current = modal.ownerDocument.activeElement;
  const index = stops.indexOf(current as HTMLElement);
  if (!stops.length || index < 0 || (event.shiftKey ? index === 0 : index === stops.length - 1)) {
    event.preventDefault();
    (event.shiftKey ? stops.at(-1) : stops[0])?.focus();
  }
}
