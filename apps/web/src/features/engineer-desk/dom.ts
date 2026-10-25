/** A small element builder for the engineer screens: text is always set as text, never parsed;
 * only the workbench's own static icon markup is inserted as HTML (`iconNode`). */
import { agentMark, icon } from '../../app/art.js';

export type Child = Node | string | null | undefined | false | readonly Child[];
export type Attrs = Record<string, string | number | boolean | null | undefined>;

export function el<K extends keyof HTMLElementTagNameMap>(
  doc: Document,
  tag: K,
  attrs: Attrs = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = doc.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = String(value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  }
  append(node, ...children);
  return node;
}

export function append(parent: Node, ...children: Child[]) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) {
      append(parent, ...child);
      continue;
    }
    const doc = parent.ownerDocument ?? (parent as Document);
    parent.appendChild(typeof child === 'string' ? doc.createTextNode(child) : (child as Node));
  }
}

/** Replace a node's children (null and false entries are skipped). */
export function fill(parent: Element, ...children: Child[]) {
  parent.replaceChildren();
  append(parent, ...children);
}

/** One of the workbench's icons (art.js), hidden from screen readers. */
export function iconNode(doc: Document, name: string, size = 'i-sm'): HTMLElement {
  const span = doc.createElement('span');
  span.className = 'ed-icon';
  span.setAttribute('aria-hidden', 'true');
  span.innerHTML = icon(name, size);
  return span;
}

/** The person's own Agent mark (ink, like the person), hidden from screen readers. */
export function agentNode(doc: Document, size = 'xs'): HTMLElement {
  const span = doc.createElement('span');
  span.className = 'ed-agent-mark';
  span.setAttribute('aria-hidden', 'true');
  span.innerHTML = agentMark(size);
  return span;
}

export function button(
  doc: Document,
  label: Child | Child[],
  className = 'btn small',
  attrs: Attrs = {},
): HTMLButtonElement {
  const node = el(doc, 'button', { type: 'button', class: className, ...attrs });
  append(node, label);
  return node;
}

/** The work language of server text, so screen readers and line breaking read it right. */
export const workLang = (language: 'zh' | 'en') => (language === 'en' ? 'en' : 'zh-CN');
