/** Minimal text-only DOM for node Vitest; it implements just what renderers here use. */
export class FakeNode {
  parent: FakeElement | null = null;
  constructor(public ownText = '') {}
  get textContent(): string {
    return this.ownText;
  }
}
export class FakeElement extends FakeNode {
  children: FakeNode[] = [];
  className = '';
  dataset: Record<string, string> = {};
  attributes = new Map<string, string>();
  open = false;
  hidden = false;
  disabled = false;
  checked = false;
  value = '';
  type = '';
  name = '';
  private listeners = new Map<string, (() => void)[]>();
  constructor(public tagName: string) {
    super();
  }
  override get textContent(): string {
    return this.ownText + this.children.map((child) => child.textContent).join('');
  }
  set textContent(value: string) {
    this.children = [];
    this.ownText = value;
  }
  append(...nodes: (FakeNode | string)[]) {
    for (const node of nodes) {
      const child = typeof node === 'string' ? new FakeNode(node) : node;
      child.parent = this;
      this.children.push(child);
    }
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
  dispatch(type: string) {
    for (const listener of this.listeners.get(type) ?? []) listener();
  }
  click() {
    if (!this.disabled) this.dispatch('click');
  }
  /** Depth-first elements whose class list contains `name`. */
  byClass(name: string): FakeElement[] {
    const found: FakeElement[] = [];
    const visit = (node: FakeNode) => {
      if (!(node instanceof FakeElement)) return;
      if (node.className.split(' ').includes(name)) found.push(node);
      node.children.forEach(visit);
    };
    this.children.forEach(visit);
    return found;
  }
  byTag(tag: string): FakeElement[] {
    const found: FakeElement[] = [];
    const visit = (node: FakeNode) => {
      if (!(node instanceof FakeElement)) return;
      if (node.tagName === tag) found.push(node);
      node.children.forEach(visit);
    };
    this.children.forEach(visit);
    return found;
  }
}
export function fakeDocument() {
  return {
    createElement: (tag: string) => new FakeElement(tag),
  } as unknown as Document;
}
export const asFake = (node: unknown) => node as FakeElement;
