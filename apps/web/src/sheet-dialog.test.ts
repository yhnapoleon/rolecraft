import { afterEach, describe, expect, it } from 'vitest';
import type { PickerSection } from './evidence-picker';
import { evidenceSheet } from './evidence-picker';
import { setPreference } from './app/i18n';
import { sheetDialog } from './sheet-dialog';

/** Just enough of a document for the dialogs: elements, attributes, events and the page. */
class Node {
  children: Node[] = [];
  parent: Node | null = null;
  attributes = new Map<string, string>();
  listeners = new Map<string, (() => void)[]>();
  className = '';
  id = '';
  type = '';
  checked = false;
  disabled = false;
  hidden = false;
  open = false;
  tabIndex = 0;
  onclick: (() => void) | null = null;
  private text = '';
  constructor(public tagName: string) {}
  get textContent(): string {
    return this.text + this.children.map((child) => child.textContent).join('');
  }
  set textContent(value: string) {
    this.children = [];
    this.text = value;
  }
  append(...nodes: (Node | string)[]) {
    for (const node of nodes) {
      const child =
        typeof node === 'string' ? Object.assign(new Node('#text'), { text: node }) : node;
      child.parent = this;
      this.children.push(child);
    }
  }
  before(node: Node) {
    const siblings = this.parent?.children ?? [];
    node.parent = this.parent;
    siblings.splice(siblings.indexOf(this), 0, node);
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((n) => n !== this);
    this.parent = null;
  }
  setAttribute(name: string, value: string) {
    this.attributes.set(name, value);
  }
  getAttribute(name: string) {
    return this.attributes.get(name) ?? null;
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  click() {
    if (!this.disabled) this.onclick?.();
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
    for (const listener of this.listeners.get('close') ?? []) listener();
    this.listeners.delete('close');
  }
  all(): Node[] {
    return this.children.flatMap((child) => [child, ...child.all()]);
  }
  byTag(tag: string) {
    return this.all().filter((node) => node.tagName === tag);
  }
}
const page = () => {
  const body = new Node('body');
  return { body, doc: { body, createElement: (tag: string) => new Node(tag) } };
};
const asDoc = (doc: unknown) => doc as Document;
const skeleton = (dialog: Node) => {
  const [head, ...rest] = dialog.children;
  const [heading, close] = head.children;
  return {
    className: dialog.className,
    labelledBy: dialog.getAttribute('aria-labelledby') === heading.id && heading.id !== '',
    head: [head.tagName, head.className, heading.tagName, close.tagName, close.textContent],
    parts: rest.map((node) => `${node.tagName}.${node.className}`),
  };
};

afterEach(() => setPreference('zh'));

describe('the shared sheet dialog', () => {
  it('has a labelled heading with a close button, a body and a footer, on the page', () => {
    const { body, doc } = page();
    const sheet = sheetDialog('依据', { doc: asDoc(doc) });
    const dialog = sheet.element as unknown as Node;
    expect(body.children).toEqual([dialog]);
    expect(skeleton(dialog)).toEqual({
      className: 'sheet wide',
      labelledBy: true,
      head: ['header', 'sheet-head', 'h2', 'button', '关闭'],
      parts: ['div.sheet-body', 'footer.sheet-foot'],
    });
    expect(sheet.body).toBe(dialog.children[1]);
    expect(sheet.foot).toBe(dialog.children[2]);
  });

  it('is removed when it closes, and two dialogs never share a heading', () => {
    const { body, doc } = page();
    const first = sheetDialog('A', { doc: asDoc(doc), className: 'evidence-picker' });
    const second = sheetDialog('B', { doc: asDoc(doc) });
    expect(first.element.className).toBe('sheet wide evidence-picker');
    expect(first.element.getAttribute('aria-labelledby')).not.toBe(
      second.element.getAttribute('aria-labelledby'),
    );
    const close = (first.element as unknown as Node).byTag('button')[0];
    close.click();
    expect(body.children).toEqual([second.element]);
  });

  it('is the frame of the evidence picker, with its alert above the footer', async () => {
    setPreference('en');
    const { body, doc } = page();
    const sections: PickerSection[] = [
      { kind: 'test', title: 'Test runs', empty: 'No test runs yet.', groups: [{ rows: [] }] },
    ];
    const answer = evidenceSheet(asDoc(doc))(sections, async () => []);
    const dialog = body.children[0];
    expect(dialog.open).toBe(true);
    expect(skeleton(dialog)).toEqual({
      className: 'sheet wide evidence-picker',
      labelledBy: true,
      head: ['header', 'sheet-head', 'h2', 'button', 'Close'],
      parts: ['div.sheet-body', 'p.inline-alert', 'footer.sheet-foot'],
    });
    dialog.byTag('button')[0].click();
    expect(await answer).toBeNull();
    expect(body.children).toEqual([]);
  });
});
