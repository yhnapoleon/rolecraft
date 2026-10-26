import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { containModalTab, modalOwnsEscape } from './modal-keyboard';

afterEach(() => vi.unstubAllGlobals());
function fixture() {
  const doc = { activeElement: {} as unknown, querySelectorAll: () => [modal] };
  const stops = Array.from({ length: 4 }, () => ({
    tabIndex: 0, matches: () => false, closest: () => null, checkVisibility: () => true,
    focus() { doc.activeElement = this; },
  }));
  const excluded = [
    { ...stops[0], tabIndex: -1 },
    { ...stops[0], matches: () => true },
    { ...stops[0], closest: () => ({}) },
    { ...stops[0], checkVisibility: () => false },
  ];
  const modal = {
    hidden: false, ownerDocument: doc, querySelectorAll: () => [...stops, ...excluded],
    contains: (node: unknown) => stops.includes(node as typeof stops[0]),
    dispatchEvent: vi.fn((_event: Event) => false),
  };
  return { doc, stops, modal };
}
it.each([false, true])('contains two full Tab cycles (reverse=%s), excluding hidden and disabled controls', reverse => {
  const { doc, stops, modal } = fixture();
  doc.activeElement = reverse ? stops[0] : stops.at(-1);
  for (let i = 0; i < stops.length * 2; i++) {
    const event = { key: 'Tab', shiftKey: reverse, preventDefault: vi.fn() };
    const index = stops.indexOf(doc.activeElement as typeof stops[0]);
    containModalTab(event as unknown as KeyboardEvent, modal as unknown as HTMLElement);
    if (!event.preventDefault.mock.calls.length) {
      // Normal browser Tab movement; crossing the boundary would leave the modal.
      doc.activeElement = stops[index + (reverse ? -1 : 1)];
    }
    expect(stops).toContain(doc.activeElement);
  }
});
it.each([false, true])('recovers heading or BODY focus on Tab (reverse=%s)', reverse => {
  const { doc, stops, modal } = fixture();
  const event = { key: 'Tab', shiftKey: reverse, preventDefault: vi.fn() };
  containModalTab(event as unknown as KeyboardEvent, modal as unknown as HTMLElement);
  expect(event.preventDefault).toHaveBeenCalledOnce();
  expect(doc.activeElement).toBe(reverse ? stops.at(-1) : stops[0]);
});
it('hands BODY Escape to the active modal and never navigates underneath it', () => {
  const { doc, modal } = fixture();
  const event = { key: 'Escape', target: {}, preventDefault: vi.fn() };
  const navigate = vi.fn();
  if (!modalOwnsEscape(event as unknown as KeyboardEvent, doc as unknown as Document)) navigate();
  expect(navigate).not.toHaveBeenCalled();
  expect(event.preventDefault).toHaveBeenCalledOnce();
  expect(modal.dispatchEvent).toHaveBeenCalledOnce();
  expect(modal.dispatchEvent.mock.calls[0][0]).toMatchObject({ type: 'cancel', cancelable: true });
});
it('leaves in-modal Escape to the dialog and allows normal navigation with no modal', () => {
  const { doc, stops, modal } = fixture();
  const event = { key: 'Escape', target: stops[0], preventDefault: vi.fn() };
  expect(modalOwnsEscape(event as unknown as KeyboardEvent, doc as unknown as Document)).toBe(true);
  expect(modal.dispatchEvent).not.toHaveBeenCalled();
  expect(event.preventDefault).not.toHaveBeenCalled();
  doc.querySelectorAll = () => [];
  expect(modalOwnsEscape(event as unknown as KeyboardEvent, doc as unknown as Document)).toBe(false);
});
it('wires the workspace Escape guard and inspector capture listener to the modal handlers', () => {
  const shell = readFileSync(new URL('./ui.js', import.meta.url), 'utf8');
  const inspector = readFileSync(new URL('../features/recognition-native/record-inspector.ts', import.meta.url), 'utf8');
  expect(shell).toContain("e.key === 'Escape' && !modalOwnsEscape(e, document)");
  expect(shell).not.toContain("e.key === 'Escape' && !sheet.open");
  expect(inspector).toContain("doc.addEventListener('keydown', handleKeyboard, true)");
  expect(inspector).toContain('containModalTab(event, dialog)');
});
