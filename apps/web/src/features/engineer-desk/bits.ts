/** Small drawn pieces shared by the engineer screens: the progress circle, status chips, result
 * squares, counting numbers and a settings diff. Text is set as text; only fixed SVG is markup. */
import 'number-flow';
import { T } from '../../app/i18n';
import { agentNode, el, iconNode, type Child } from './dom';
import type { DiffRow, Mark } from './model';
import type { StepState } from './stage';

const SVG = 'http://www.w3.org/2000/svg';
function svg(doc: Document, tag: string, attrs: Record<string, string>) {
  const node = doc.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

/** Progress by shape (style §2.3): hollow to do, half while current, a tick when done. */
export function progressMark(doc: Document, state: StepState): HTMLElement {
  const wrap = el(doc, 'span', {
    class: 'ed-progress',
    'data-state': state,
    'aria-hidden': 'true',
  });
  const box = svg(doc, 'svg', { viewBox: '0 0 20 20', width: '20', height: '20' });
  box.append(svg(doc, 'circle', { cx: '10', cy: '10', r: '8', class: 'ed-progress__ring' }));
  if (state === 'current')
    box.append(svg(doc, 'path', { d: 'M10 2a8 8 0 0 1 0 16z', class: 'ed-progress__half' }));
  if (state === 'done') {
    box.append(svg(doc, 'circle', { cx: '10', cy: '10', r: '8', class: 'ed-progress__fill' }));
    box.append(
      svg(doc, 'path', {
        d: 'm6.4 10.3 2.4 2.4 4.8-5.1',
        class: 'ed-progress__tick',
        pathLength: '1',
      }),
    );
  }
  wrap.append(box);
  return wrap;
}

/** A status chip; tone is one of the five meanings. */
export function chip(doc: Document, text: Child, tone: Mark | 'outline' | 'plain', extra = '') {
  return el(doc, 'span', { class: `ed-chip ${extra}`.trim(), 'data-tone': tone }, text);
}

/** Result squares (one per check), coloured by meaning; grey dashed while not known. */
export function squares(doc: Document, marks: readonly Mark[], label = '') {
  return el(
    doc,
    'span',
    {
      class: 'ed-squares',
      role: label ? 'img' : null,
      'aria-label': label || null,
      'aria-hidden': label ? null : 'true',
    },
    ...marks.map((m) => el(doc, 'span', { class: 'ed-square', 'data-mark': m })),
  );
}

/** A number that rolls when it changes (NumberFlow); tabular figures. */
export function countNode(doc: Document, value: number, className = 'ed-count') {
  const node = doc.createElement('number-flow') as HTMLElement & { update(v: number): void };
  node.className = className;
  node.update(value);
  return node;
}
export function setCount(node: Element | null | undefined, value: number) {
  const flow = node as (HTMLElement & { update?: (v: number) => void; value?: number }) | null;
  if (flow?.update && flow.value !== value) flow.update(value);
}

/** Settings as a diff: name, the old value struck through in grey, an arrow, the new value in ink
 * (never red and green: a change is not good or bad in itself). */
export function diffList(
  doc: Document,
  rows: readonly DiffRow[],
  opts: { keys?: boolean; className?: string; agent?: (field: string) => string | null } = {},
) {
  return el(
    doc,
    'ul',
    { class: `ed-diff ${opts.className ?? ''}`.trim() },
    ...rows.map((r) => {
      const by = opts.agent?.(r.field) ?? null;
      return el(
        doc,
        'li',
        { class: 'ed-diff__row', 'data-field': r.field },
        el(
          doc,
          'span',
          { class: 'ed-diff__name' },
          opts.keys ? el(doc, 'code', { class: 'ed-key', lang: 'en' }, r.field) : r.name,
        ),
        el(
          doc,
          'span',
          { class: 'ed-diff__values' },
          el(doc, 'del', { class: 'ed-diff__was' }, r.before),
          el(doc, 'span', { class: 'ed-diff__arrow', 'aria-hidden': 'true' }, '→'),
          el(doc, 'span', { class: 'sr-only' }, T('改为', 'to')),
          el(doc, 'b', { class: 'ed-diff__now' }, r.after),
          by
            ? el(
                doc,
                'span',
                { class: 'ed-by-agent', title: by },
                agentNode(doc),
                el(doc, 'span', { class: 'sr-only' }, by),
              )
            : null,
        ),
      );
    }),
  );
}

/** A code-style diff (− old / + new per setting) for the Agent's cards. */
export function codeDiff(doc: Document, rows: readonly DiffRow[]) {
  return el(
    doc,
    'div',
    { class: 'ed-code-diff', role: 'list' },
    ...rows.flatMap((r) => [
      el(
        doc,
        'p',
        { class: 'ed-code-diff__line', 'data-sign': '-', role: 'listitem' },
        el(doc, 'span', { class: 'ed-code-diff__sign', 'aria-label': T('原值', 'was') }, '−'),
        el(doc, 'code', { lang: 'en' }, r.field),
        el(doc, 'del', {}, r.before),
      ),
      el(
        doc,
        'p',
        { class: 'ed-code-diff__line', 'data-sign': '+', role: 'listitem' },
        el(doc, 'span', { class: 'ed-code-diff__sign', 'aria-label': T('新值', 'now') }, '+'),
        el(doc, 'code', { lang: 'en' }, r.field),
        el(doc, 'b', {}, r.after),
      ),
    ]),
  );
}

/** The person's Agent mark with an accessible name. */
export function agentBadge(doc: Document, title: string) {
  return el(
    doc,
    'span',
    { class: 'ed-by-agent', title },
    agentNode(doc),
    el(doc, 'span', { class: 'sr-only' }, title),
  );
}

export type KeyLevel = 'primary' | 'secondary' | 'ghost';
/** A key in the four levels (plan §13.1): ink primary (one per screen), instrument secondary,
 * ghost. The icon slot turns into a spinner while busy; the words and width stay. */
export function key(
  doc: Document,
  label: string,
  level: KeyLevel,
  attrs: Record<string, string | boolean | null | undefined> = {},
  icon?: string,
) {
  const { class: extra, ...rest } = attrs;
  const node = el(
    doc,
    'button',
    { type: 'button', ...rest },
    el(doc, 'span', { class: 'ed-k__icon', 'aria-hidden': 'true' }),
    el(doc, 'span', { class: 'ed-k__label' }, label),
  );
  node.className = `ed-k is-${level}${extra ? ` ${extra}` : ''}`;
  if (icon) (node.firstChild as HTMLElement).append(iconNode(doc, icon, 'i-xs'));
  else node.classList.add('no-icon');
  return node;
}
/** Loading: icon → spinner, disabled, aria-busy; words unchanged. */
export function setBusy(node: HTMLButtonElement | null | undefined, busy: boolean) {
  if (!node) return;
  node.toggleAttribute('aria-busy', busy);
  if (busy) node.setAttribute('aria-busy', 'true');
  node.classList.toggle('is-busy', busy);
}
/** Done: the icon blurs into a tick for 1.6s, then back. */
export function flashDone(node: HTMLElement) {
  node.classList.add('is-done');
  setTimeout(() => node.classList.remove('is-done'), 1600);
}
