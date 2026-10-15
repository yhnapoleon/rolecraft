/** Read-only references and explicit evidence selection in the existing v4 surfaces. */
import type { V4HostAdapter } from './v4-host';
import type { EvidenceRefV2, ObjectRef } from './contracts-v2';
import { T, locale } from './app/i18n';
import { describeServerEvent, type ServerEvent } from './app/event-copy';
import { markdownNodes } from './app/markdown';
import { answerEvidenceRequest, practiceChanged } from './evidence-picker';
import { outcomeTerm } from './features/workspace/native-v4/outcome-copy';
import {
  catalogLookups,
  readCatalog,
  referenceLabel,
  type ReferenceCatalog,
} from './reference-catalog';
import { sheetDialog } from './sheet-dialog';

// Documents (by their current name), test runs, deliveries and history records are named from
// the practice timeline, the same catalog the evidence buttons use.
const NAMED_FROM_TIMELINE = ['material', 'test', 'submission', 'event'];
const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') => {
  const n = document.createElement(tag);
  n.textContent = text;
  n.className = className;
  return n;
};
type ReaderView = { body: HTMLElement; heading: HTMLElement; modal: HTMLDialogElement | null };
// Evidence buttons carry a stable key, so the same button can be found again after a rebuild.
const KEYS = ['data-reference-key', 'data-model-reference-key'];
/** Finds the element that opened the reader, or the one that replaced it after a re-render. */
function locate(opener: HTMLElement | null): () => HTMLElement | null {
  const attribute = KEYS.find((name) => opener?.hasAttribute(name));
  if (!opener || !attribute) return () => (opener?.isConnected ? opener : null);
  const value = opener.getAttribute(attribute);
  const same = () =>
    [...document.querySelectorAll<HTMLElement>(`[${attribute}]`)].filter(
      (node) => node.getAttribute(attribute) === value,
    );
  const index = same().indexOf(opener);
  return () => (opener.isConnected ? opener : (same()[index] ?? null));
}
/** Without a reading column the original opens in a sheet. */
function sheetReader(title: string): ReaderView {
  const sheet = sheetDialog(title);
  return { body: sheet.body, heading: sheet.heading, modal: sheet.element };
}
/** The reader beside the feedback: placed first in the side column so it is in view, with a
 * close control that returns focus to the evidence that opened it. */
function sideReader(
  side: HTMLElement,
  title: string,
  opener: () => HTMLElement | null,
): ReaderView {
  const hint = side.querySelector<HTMLElement>('[data-reference-hint]');
  side.querySelector('[data-reference-reader]')?.remove();
  const reader = node('article', '', 'reference-reader');
  reader.dataset.referenceReader = '';
  const head = node('header', '', 'reference-reader-head');
  const heading = node('h2', title, 'section-title');
  const close = node('button', T('关闭', 'Close'), 'btn small quiet');
  close.type = 'button';
  close.onclick = () => {
    reader.remove();
    if (hint) hint.hidden = false;
    const back = opener();
    if (!back) return;
    // A rebuilt panel folds its detail again; unfold the way back to the evidence.
    for (let node = back.parentElement; node; node = node.parentElement)
      if (node instanceof HTMLDetailsElement) node.open = true;
    back.focus();
  };
  head.append(heading, close);
  reader.append(head);
  side.append(reader);
  if (hint) hint.hidden = true;
  return { body: reader, heading, modal: null };
}
/** The record itself names what the timeline cannot: a document or work title, a question. */
function withRecord(
  catalog: ReferenceCatalog,
  ref: ObjectRef,
  content: Record<string, unknown>,
): ReferenceCatalog {
  const key = `${ref.object_id}:${ref.version}`;
  const title = typeof content.title === 'string' ? content.title : '';
  const event = content.event as ServerEvent | undefined;
  return {
    ...catalog,
    materialTitles:
      ref.kind === 'material' && title && !(key in catalog.materialTitles)
        ? { ...catalog.materialTitles, [key]: title }
        : catalog.materialTitles,
    products:
      ref.kind === 'product' && title ? { ...catalog.products, [key]: title } : catalog.products,
    tests:
      ref.kind === 'test' && !catalog.tests[ref.object_id] && typeof content.query === 'string'
        ? { ...catalog.tests, [ref.object_id]: { query: content.query } }
        : catalog.tests,
    events:
      ref.kind === 'event' && event?.type
        ? { ...catalog.events, [ref.object_id]: event }
        : catalog.events,
  };
}
function textOf(content: Record<string, any>): string[] {
  const strings = [
    content.text,
    content.body,
    content.content,
    content.query,
    content.answer,
    content.reason,
    content.question,
    typeof content.decision === 'string'
      ? outcomeTerm(locale(), 'decision', content.decision)
      : undefined,
  ];
  if (Array.isArray(content.fragments)) strings.push(...content.fragments.map((f: any) => f.text));
  return strings.filter((v): v is string => typeof v === 'string' && v.length > 0);
}
export function installV4References(getHost: () => V4HostAdapter | null) {
  const open = async (event: Event) => {
    const detail = (event as CustomEvent).detail,
      host = getHost();
    if (!host || host.snapshot().session?.protocol !== 2) return;
    detail.handled = true;
    // Focus returns here when the reader beside the feedback is closed.
    const opener = locate(
      document.activeElement instanceof HTMLElement ? document.activeElement : null,
    );
    try {
      const ref = detail.ref as ObjectRef | EvidenceRefV2;
      if (ref.session_id !== host.snapshot().session?.sessionId)
        throw Error(T('引用不属于当前练习。', 'This reference belongs to another practice.'));
      const record: any = await host.query('objects.read', ref);
      if (
        record.ref?.object_id !== ref.object_id ||
        record.ref.version !== ref.version ||
        record.ref.session_id !== ref.session_id
      )
        throw Error(T('原始版本无法核对。', 'The original version could not be verified.'));
      const timeline =
        NAMED_FROM_TIMELINE.includes(ref.kind) && host.snapshot().available.timeline
          ? await host.query('timeline').catch(() => null)
          : null;
      if (getHost()?.snapshot().session?.sessionId !== ref.session_id) throw practiceChanged();
      const content: Record<string, unknown> = record.content ?? {};
      const catalog = withRecord(readCatalog(timeline), ref, content);
      const title = referenceLabel(ref, catalog, locale()).full;
      const side = document.querySelector<HTMLElement>('[data-v4-reference-side]');
      const view = side ? sideReader(side, title, opener) : sheetReader(title);
      const target = view.body;
      if ('quote' in ref && ref.quote) target.append(node('blockquote', ref.quote, 'prose'));
      // A history record has no body of its own; it opens the document version it changed.
      const recorded = ref.kind === 'event' ? catalog.events[ref.object_id] : undefined;
      const subject = recorded
        ? describeServerEvent(recorded, catalogLookups(catalog), locale()).subject
        : undefined;
      if (subject?.kind === 'material' && subject.version !== undefined) {
        const version = subject.version;
        const show = node('button', T('看这份资料', 'Open this document'), 'btn small');
        show.type = 'button';
        show.onclick = () => {
          void host
            .openReference({
              session_id: ref.session_id,
              kind: 'material',
              object_id: subject.id,
              version,
            })
            .catch(() => {});
        };
        target.append(show);
      }
      const texts = ref.kind === 'event' ? [] : textOf(content);
      for (const text of texts) {
        // Works and documents are written in Markdown: show headings and lists as such.
        const body = node('div', '', 'prose');
        body.append(...markdownNodes(document, text));
        target.append(body);
      }
      if (!texts.length && !recorded)
        target.append(
          node(
            'p',
            T(
              '已核对此版本的记录身份，暂无可展示的正文。',
              'This version is verified; no readable body is available.',
            ),
            'meta',
          ),
        );
      if (view.modal) view.modal.showModal();
      else
        target.scrollIntoView({
          block: 'nearest',
          behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
            ? 'auto'
            : 'smooth',
        });
      view.heading.tabIndex = -1;
      view.heading.focus({ preventScroll: true });
      detail.resolve();
    } catch (error) {
      detail.reject(error);
    }
  };
  // Read passages, test runs and work versions are offered by the shared picker.
  const choose = (event: Event) => answerEvidenceRequest(getHost, event);
  window.addEventListener('v4-open-reference', open);
  window.addEventListener('v4-choose-evidence', choose);
  return () => {
    window.removeEventListener('v4-open-reference', open);
    window.removeEventListener('v4-choose-evidence', choose);
  };
}
