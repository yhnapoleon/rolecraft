/** DOM pieces of the colleague thread: bubbles, paper source tags, the passage that hangs from
 * a tag, the replying row and the grey line for a reply that did not come through. Text is only
 * ever set as text; the few icons are fixed markup. */
import { T } from '../../app/i18n';
import { localizeConfigTerms } from '../../app/config-terms';
import { markdownNodes } from '../../app/markdown';
import { PERSON_OF_ROLE, personName } from '../../app/people.js';
import { NAME_CLOSE, NAME_OPEN, type Cite, type NoticeKind } from './chat-model';

type Make = <K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
) => HTMLElementTagNameMap[K];
export const maker =
  (doc: Document): Make =>
  (tag, cls) => {
    const node = doc.createElement(tag);
    if (cls) node.className = cls;
    return node;
  };

const SVG: Record<string, string> = {
  flask:
    '<path d="M9 3h6"/><path d="M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6A2 2 0 0 0 19 18l-5-9V3"/><path d="M7.5 15h9"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 1.5"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  held: '<path d="M12 3l7 3v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6z"/><path d="M9 12h6"/>',
  retry: '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/>',
  unknown: '<circle cx="12" cy="12" r="8.5" stroke-dasharray="2.5 2.5"/>',
  chevron: '<path d="M6 9l6 6 6-6"/>',
};
/** A fixed icon; never built from data. */
export function glyph(doc: Document, name: keyof typeof SVG, size = 14) {
  const span = doc.createElement('span');
  span.className = 'rc-glyph';
  span.setAttribute('aria-hidden', 'true');
  span.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${SVG[name]}</svg>`;
  return span;
}

/** The colleague's avatar, the same mark as the list and the header (styles.css `.av`). */
export function avatarNode(doc: Document, roleId: string, replying = false) {
  const make = maker(doc);
  const person = PERSON_OF_ROLE[roleId] ?? roleId;
  const av = make('span', `av av-sm who-${person} rc-msg__av${replying ? ' typing' : ''}`);
  av.setAttribute('aria-hidden', 'true');
  const face = make('span', 'av-face');
  face.textContent = personName(roleId).charAt(0);
  av.append(face);
  return av;
}

/** A document named inside an English sentence reads as a title. */
function setNames(doc: Document, root: Node) {
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if ((n.nodeValue ?? '').includes(NAME_OPEN)) texts.push(n as Text);
  }
  const pattern = new RegExp(`${NAME_OPEN}([^${NAME_CLOSE}]*)${NAME_CLOSE}`, 'g');
  for (const text of texts) {
    const value = text.nodeValue ?? '';
    const parts: Node[] = [];
    let last = 0;
    for (const m of value.matchAll(pattern)) {
      if (m.index > last) parts.push(doc.createTextNode(value.slice(last, m.index)));
      const cite = doc.createElement('cite');
      cite.className = 'rc-name';
      cite.textContent = m[1];
      parts.push(cite);
      last = m.index + m[0].length;
    }
    if (last < value.length) parts.push(doc.createTextNode(value.slice(last)));
    text.replaceWith(...parts);
  }
}

/** One message of a reply: its Markdown (headings, lists, bold, code) as the reply wrote it. */
export function replyBubble(doc: Document, text: string, cls = '') {
  const bubble = maker(doc)('div', `rc-bubble rc-bubble--them rc-roles__md${cls ? ` ${cls}` : ''}`);
  bubble.append(...markdownNodes(doc, text));
  setNames(doc, bubble);
  localizeConfigTerms(doc, bubble);
  return bubble;
}

/** A short form of a source title for the tag: the part before its colon, when that names it. */
export function shortTitle(title: string) {
  const head = title.split(/[:：]/)[0].trim();
  return head.length >= (/[㐀-鿿]/.test(head) ? 3 : 6) ? head : title;
}

/** A paper tag for one source: serif title, small version. A button when it opens something. */
export function paperTag(
  doc: Document,
  cite: Cite,
  options: { onPress?: () => void; expanded?: boolean; peek?: boolean; mini?: boolean },
) {
  const make = maker(doc);
  const tag = options.onPress
    ? Object.assign(make('button', 'rc-tag rc-roles__material'), { type: 'button' })
    : make('span', 'rc-tag rc-tag--static rc-roles__source');
  if (options.mini) tag.classList.add('rc-tag--mini');
  const title = make('span', 'rc-tag__title');
  title.textContent = shortTitle(cite.title);
  const version = make('small', 'rc-tag__version');
  version.textContent = ` · v${cite.version}`;
  tag.append(title, version);
  tag.title = cite.label;
  if (options.onPress) {
    const press = options.onPress;
    tag.addEventListener('click', () => press());
    if (options.peek) {
      tag.setAttribute('aria-expanded', String(!!options.expanded));
      tag.setAttribute(
        'aria-label',
        T(`看这段原文：${cite.title}`, `Show the passage from ${cite.title}`),
      );
      tag.dataset.peek = cite.label;
    } else tag.setAttribute('aria-label', T(`打开资料：${cite.title}`, `Open ${cite.title}`));
  }
  return tag;
}

/** The exact passage, hung from its tag by a short line; the cited words in the colleague's hue. */
export function peekNode(
  doc: Document,
  cite: Cite,
  quote: string,
  options: { id: string; openFull?: () => void },
) {
  const make = maker(doc);
  const wrap = make('div', 'rc-peek-wrap');
  const tether = make('span', 'rc-tether');
  tether.setAttribute('aria-hidden', 'true');
  const peek = make('div', 'rc-peek');
  peek.id = options.id;
  peek.setAttribute('role', 'region');
  peek.setAttribute('aria-label', cite.title);
  const head = make('div', 'rc-peek__head');
  const name = make('span');
  name.textContent = shortTitle(cite.title);
  const version = make('span');
  version.textContent = `v${cite.version}`;
  head.append(name, version);
  const text = make('p', 'rc-peek__text');
  const hit = make('mark', 'rc-hit');
  hit.textContent = quote;
  text.append(hit);
  peek.append(head, text);
  if (options.openFull) {
    const full = Object.assign(make('button', 'rc-peek__full'), { type: 'button' });
    full.textContent = T('看完整原文', 'Read the full text');
    const open = options.openFull;
    full.addEventListener('click', () => open());
    peek.append(full);
  }
  wrap.append(tether, peek);
  return wrap;
}

/** "Chen is replying": the avatar breathes, three dots wait in a paper bubble. */
export function replyingRow(doc: Document, roleId: string) {
  const make = maker(doc);
  const row = make('div', 'rc-msg rc-msg--them rc-typing');
  row.setAttribute('role', 'status');
  const dots = make('span', 'rc-typing__dots');
  dots.setAttribute('aria-hidden', 'true');
  dots.append(make('i'), make('i'), make('i'));
  const col = make('div', 'rc-msg__col');
  const caption = make('p', 'rc-typing__caption');
  caption.textContent = T(
    `${personName(roleId)} 正在回复，你可以继续工作。`,
    `${personName(roleId)} is replying. You can keep working.`,
  );
  col.append(dots);
  row.append(avatarNode(doc, roleId, true), col, caption);
  return row;
}

/** The grey line for a reply that did not come through: one sentence, the existing action. */
export function noticeRow(
  doc: Document,
  kind: Exclude<NoticeKind, 'typing'>,
  text: string,
  action?: HTMLElement,
) {
  const make = maker(doc);
  const row = make('div', `rc-sys rc-sys--${kind} rc-roles__turn-status`);
  row.setAttribute('role', 'status');
  const icon = glyph(doc, kind === 'held' ? 'held' : kind === 'failed' ? 'retry' : 'unknown', 16);
  icon.classList.add('rc-sys__icon');
  row.append(icon);
  const body = make('div', 'rc-sys__body');
  const line = make('p');
  line.textContent = text;
  body.append(line);
  if (action) body.append(action);
  row.append(body);
  return row;
}

/** Held by the colleague-help review (a full solution or several questions), not a fact check. */
const HELP_REVIEW = new Set(['role_help_unverified', 'role_help_citation_invalid']);

/** What a reply that did not come through says, in plain words. */
export function noticeText(
  kind: Exclude<NoticeKind, 'typing'>,
  roleId: string,
  errorCode?: string,
) {
  const name = personName(roleId);
  if (kind === 'held' && errorCode && HELP_REVIEW.has(errorCode))
    return T(
      `这次没有生成 ${name} 的实时回复：生成的回复超出了同事帮助的边界（给出结论或操作指令、指出多处问题等），没有发出。不影响你的评价，可以请对方重新回答。`,
      `No live reply from ${name} this time: the generated reply went beyond a colleague's help (such as giving conclusions or instructions, or raising several problems) and was not sent. It does not count against you; you can ask again.`,
    );
  return {
    held: T(
      '这条回复没有发出：没通过和资料的事实核对，不影响你的评价。',
      'This reply was held back: it did not pass the fact check against the materials. It does not count against you.',
    ),
    failed: T(
      '回复没有生成，你的问题还在。',
      'The reply did not come through. Your question is kept.',
    ),
    context: T(
      `你发问之后资料有了新版本。确认后，${name} 按新资料回答。`,
      `The materials changed after you asked. Confirm, and ${name} answers from the new versions.`,
    ),
    paused: T('练习已暂停，你的问题还在。', 'The practice is paused. Your question is kept.'),
    stopped: T('这次没有回复，你的问题还在。', 'No reply this time. Your question is kept.'),
    unknown: T(
      '还没确认这条有没有处理，你的问题还在。',
      'Not yet confirmed whether this was handled. Your question is kept.',
    ),
  }[kind];
}

/** Sending, then sent. Nobody knows whether the colleague has read it, so there is no "read". */
export function deliveryLine(doc: Document, state: 'sending' | 'sent') {
  const make = maker(doc);
  const line = make('p', `rc-msg__state rc-msg__state--${state}`);
  line.append(glyph(doc, state === 'sending' ? 'clock' : 'check', 12));
  const text = make('span');
  text.textContent = state === 'sending' ? T('发送中', 'Sending') : T('已发出', 'Sent');
  line.append(text);
  return line;
}
