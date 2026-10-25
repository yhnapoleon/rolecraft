import { describe, expect, it } from 'vitest';
import { cleanClone, DOCUMENT_DURATION, documentEase, mixBox } from './document-motion.js';

/** The Element members a flight copy touches; the unit environment has no DOM. */
class Surface {
  readonly style: Record<string, string> = {};
  inert = false;
  tagName = 'DIV';
  selectedIndex = 0;
  value = '';
  checked = false;
  private readonly attributes: Map<string, string>;
  constructor(
    attributes: Record<string, string>,
    readonly children: Surface[] = [],
  ) {
    this.attributes = new Map(Object.entries(attributes));
  }
  getAttributeNames() {
    return [...this.attributes.keys()];
  }
  getAttribute(name: string) {
    return this.attributes.get(name) ?? null;
  }
  setAttribute(name: string, value: string) {
    this.attributes.set(name, value);
  }
  removeAttribute(name: string) {
    this.attributes.delete(name);
  }
  querySelectorAll(selector: string): Surface[] {
    if (selector !== '*') throw new Error(`Unsupported selector: ${selector}`);
    return this.children.flatMap((child) => [child, ...child.querySelectorAll('*')]);
  }
  // Like the DOM: attributes copy, the live state of a control does not.
  cloneNode(): Surface {
    const copy = new Surface(
      Object.fromEntries(this.attributes),
      this.children.map((child) => child.cloneNode()),
    );
    copy.tagName = this.tagName;
    return copy;
  }
}

describe('document flight copies', () => {
  it('copy a surface without its v4 mount markers and leave the live surface owning them', () => {
    const stage = new Surface({ id: 'ws-stage', 'data-v4-region': 'workspace' }, [
      new Surface({ 'data-v4-insertion': 'sharing' }),
      new Surface({ 'data-save': '', 'data-v4-managed': 'true' }),
    ]);
    const board = new Surface({ id: 'main', class: 'stage' }, [stage]);
    const copy = cleanClone(board as unknown as HTMLElement) as unknown as Surface;
    const markers = [copy, ...copy.querySelectorAll('*')].flatMap((node) =>
      node.getAttributeNames().filter((name) => name.startsWith('data-v4-')),
    );
    expect(markers).toEqual([]);
    expect(stage.getAttribute('data-v4-region')).toBe('workspace');
  });
});

describe('document flight copies keep what controls show (164 N4)', () => {
  it('copies the chosen option, typed text and ticks into the flight copy', () => {
    const control = (tagName: string, state: Partial<Surface>) =>
      Object.assign(new Surface({}), { tagName, ...state });
    const priority = control('SELECT', { selectedIndex: 2 });
    const note = control('TEXTAREA', { value: 'typed' });
    const tick = control('INPUT', { value: 'on', checked: true });
    const board = new Surface({ id: 'main' }, [new Surface({}, [priority, note]), tick]);
    const copy = cleanClone(board as unknown as HTMLElement) as unknown as Surface;
    const [, , copiedPriority, copiedNote, copiedTick] = [copy, ...copy.querySelectorAll('*')];
    expect(copiedPriority.selectedIndex).toBe(2);
    expect(copiedNote.value).toBe('typed');
    expect(copiedTick.checked).toBe(true);
  });
});

describe('shared document geometry', () => {
  it('uses the reference timing, exact endpoints and monotonic iOS easing', () => {
    expect(DOCUMENT_DURATION).toBe(500);
    expect(documentEase(0)).toBe(0);
    expect(documentEase(1)).toBe(1);
    const samples = Array.from({ length: 101 }, (_, i) => documentEase(i / 100));
    expect(samples.every((v, i) => i === 0 || v >= samples[i - 1])).toBe(true);
    // Independent cubic-Bezier solution at x=.5: u=.6682339592265568.
    expect(documentEase(0.5)).toBeCloseTo(0.7737196918, 5);
  });
  it('retargets a partially expanded surface without snapping either endpoint', () => {
    const card = { x: 20, y: 650, width: 210, height: 112 },
      paper = { x: 42, y: 76, width: 810, height: 700 };
    const interrupted = mixBox(card, paper, documentEase(0.3));
    expect(mixBox(interrupted, card, 0)).toEqual(interrupted);
    expect(mixBox(interrupted, card, 1)).toEqual(card);
    expect(mixBox(interrupted, paper, 0)).toEqual(interrupted);
    expect(mixBox(interrupted, paper, 1)).toEqual(paper);
  });
});
