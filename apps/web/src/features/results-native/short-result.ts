/** 063-03 short result: one primary result first, evidence and full detail on demand.
 * Plain DOM and text only. Consumers pass already-localized text and existing nodes;
 * this frame never parses markup, invents results or performs business actions. */
import './short-result.css';

export type ShortResultKind = 'reply' | 'review' | 'feedback' | 'comparison' | 'source' | 'result';
/** Tone only adds a shape next to text that already states the status. */
export type ShortResultTone = 'verified' | 'pending' | 'waiting' | 'unsupported' | 'failed';
export interface ShortResultStatus {
  readonly text: string;
  readonly tone?: ShortResultTone;
}
export interface ShortResultMore {
  /** Expand control text, e.g. "展开原文" or "展开 14 项". */
  readonly label: string;
  /** Short muted addition to the control, e.g. a source count. */
  readonly meta?: string;
  /** Existing evidence/detail nodes, appended unchanged inside the disclosure. */
  readonly body: readonly Node[];
  readonly open?: boolean;
  readonly onToggle?: (open: boolean) => void;
}
export interface ShortResultClasses {
  readonly status?: string;
  readonly lead?: string;
  readonly note?: string;
  readonly more?: string;
}
export interface ShortResultInput {
  readonly kind: ShortResultKind;
  /** Stable identity so a host can keep the disclosure state across re-renders. */
  readonly id?: string;
  readonly statusLabel?: string;
  readonly statuses?: readonly ShortResultStatus[];
  /** The primary short answer or result; a string is set as text. */
  readonly lead?: string | Node;
  /** True when the lead is a tool summary rather than words from the source. */
  readonly derivedLead?: boolean;
  /** Required limits that must stay on the first screen (permission, version, failure). */
  readonly notes?: readonly (string | Node)[];
  /** Visible supported components: a source entry, a prompt, model advice. */
  readonly actions?: readonly Node[];
  readonly more?: ShortResultMore;
  readonly classes?: ShortResultClasses;
}
export interface ShortResultView {
  readonly element: HTMLElement;
  readonly lead?: HTMLElement;
  readonly details?: HTMLDetailsElement;
  readonly summary?: HTMLElement;
}

export function renderShortResult(doc: Document, input: ShortResultInput): ShortResultView {
  const node = <K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string) => {
    const element = doc.createElement(tag);
    element.className = cls;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const element = node('div', 'short-result');
  element.dataset.shortResult = input.kind;
  if (input.id) element.dataset.shortResultId = input.id;
  const statuses = (input.statuses ?? []).filter((status) => status.text);
  if (statuses.length) {
    const list = node('ul', joined('short-result__status', input.classes?.status));
    if (input.statusLabel) list.setAttribute('aria-label', input.statusLabel);
    for (const status of statuses) {
      const item = node('li', '', status.text);
      if (status.tone) item.dataset.tone = status.tone;
      list.append(item);
    }
    element.append(list);
  }
  let lead: HTMLElement | undefined;
  if (input.lead !== undefined && input.lead !== '') {
    // Given nodes may be headings or lists, which a paragraph cannot hold.
    const tag = typeof input.lead === 'string' ? 'p' : 'div';
    lead = node(tag, joined('short-result__lead', input.classes?.lead));
    if (typeof input.lead === 'string') lead.textContent = input.lead;
    else lead.append(input.lead);
    if (input.derivedLead) lead.dataset.derived = '';
    element.append(lead);
  }
  for (const note of input.notes ?? []) {
    const paragraph = node('p', joined('short-result__note', input.classes?.note));
    if (typeof note === 'string') paragraph.textContent = note;
    else paragraph.append(note);
    element.append(paragraph);
  }
  for (const action of input.actions ?? []) element.append(action);
  if (!input.more) return { element, lead };
  const more = input.more;
  const details = node('details', joined('short-result__more', input.classes?.more));
  details.dataset.shortResultMore = input.id ?? '';
  const summary = node('summary', '', more.label);
  if (more.meta) summary.append(node('span', 'short-result__meta', more.meta));
  details.append(summary, ...more.body);
  details.open = !!more.open;
  details.addEventListener('toggle', () => more.onToggle?.(details.open));
  element.append(details);
  return { element, lead, details, summary };
}

const joined = (base: string, extra?: string) => (extra ? `${base} ${extra}` : base);
