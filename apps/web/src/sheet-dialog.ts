/** The sheet dialog of the v4 reference reader and the evidence picker: a labelled heading with a
 * close button, a body and a footer. It is added to the page and removed when it closes. */
import { T } from './app/i18n';

export type SheetDialog = {
  element: HTMLDialogElement;
  heading: HTMLHeadingElement;
  body: HTMLDivElement;
  foot: HTMLElement;
};

let opened = 0;

export function sheetDialog(
  title: string,
  options: { doc?: Document; className?: string } = {},
): SheetDialog {
  const doc = options.doc ?? document;
  const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') => {
    const n = doc.createElement(tag);
    n.textContent = text;
    n.className = className;
    return n;
  };
  const element = node('dialog', '', ['sheet wide', options.className].filter(Boolean).join(' '));
  const head = node('header', '', 'sheet-head');
  const heading = node('h2', title);
  heading.id = `sheet-dialog-${++opened}`;
  element.setAttribute('aria-labelledby', heading.id);
  const close = node('button', T('关闭', 'Close'), 'btn small quiet');
  close.type = 'button';
  close.onclick = () => element.close();
  head.append(heading, close);
  const body = node('div', '', 'sheet-body');
  const foot = node('footer', '', 'sheet-foot');
  element.append(head, body, foot);
  doc.body.append(element);
  element.addEventListener('close', () => element.remove(), { once: true });
  return { element, heading, body, foot };
}
