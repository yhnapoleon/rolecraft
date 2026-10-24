/** "By colleague": Grace · Chen · Daniel side by side, each with the review's own rows for the
 * criteria that are theirs (colleagues.ts). Rows are the same rows as "By status": they open the
 * same basis and carry the same direct buttons. */
import {
  renderItemRow,
  type ItemRow,
  type ItemsRenderHooks,
  type ItemsView,
} from '../../features/feedback-native/feedback-items';
import { feedbackText, type FeedbackLanguage } from '../../features/feedback-native/localization';
import { byColleague, type Colleague, unowned } from './colleagues';

export function renderColleagues(
  doc: Document,
  view: ItemsView,
  language: FeedbackLanguage,
  hooks: Pick<ItemsRenderHooks, 'id' | 'isOpen' | 'onToggle' | 'basis' | 'action'>,
  /** "Ask Grace" at the foot of each person's column (opens the conversation in the rail). */
  ask?: (who: Colleague) => HTMLElement,
): HTMLElement {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', cls = '') => {
    const node = doc.createElement(tag);
    if (text) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  // Own ids, so a row open in both views never shares an element id.
  // In a person's column, asking is the column's own last key: rows not known yet carry none.
  const own = {
    ...hooks,
    id: `${hooks.id}-by-colleague`,
    action: (row: ItemRow) => (row.mark === 'unknown' ? null : (hooks.action?.(row) ?? null)),
  };
  const root = el('div', '', 'result-colleagues');
  root.dataset.view = 'colleague';
  const column = (
    key: string,
    name: string,
    remit: string,
    rows: ItemRow[],
    person?: 'manager' | 'business' | 'technical',
  ) => {
    const box = el('section', '', 'result-colleague');
    box.dataset.person = key;
    const head = el('header', '', 'result-colleague__head');
    if (person) {
      const avatar = el('span', name[0], 'result-colleague__avatar');
      avatar.setAttribute('aria-hidden', 'true');
      head.append(avatar);
    }
    const who = el('div', '', 'result-colleague__who');
    who.append(el('h3', name, 'result-colleague__name'), el('p', remit, 'result-colleague__remit'));
    head.append(who);
    const tally = el('p', '', 'result-colleague__tally');
    const counts = {
      unmet: rows.filter((row) => row.mark === 'unmet').length,
      unknown: rows.filter((row) => row.mark === 'unknown').length,
      met: rows.filter((row) => row.mark === 'met').length,
    };
    const said: string[] = [];
    for (const [mark, glyph, zh, en] of [
      ['unmet', '✕', '没站住', 'didn’t hold up'],
      ['unknown', '?', '还不知道', 'can’t tell yet'],
      ['met', '✓', '站得住', 'hold up'],
    ] as const) {
      if (!counts[mark]) continue;
      const part = el('span', '', 'result-colleague__count');
      part.dataset.mark = mark;
      const g = el('span', glyph, 'result-mark');
      g.dataset.mark = mark;
      g.setAttribute('aria-hidden', 'true');
      part.append(g, doc.createTextNode(String(counts[mark])));
      tally.append(part);
      said.push(`${counts[mark]} ${T(zh, en)}`);
    }
    tally.setAttribute('aria-label', said.join(T('，', ', ')));
    head.append(tally);
    box.append(head);
    const list = el('ul', '', 'fb-list result-colleague__list');
    list.append(...rows.map((row) => renderItemRow(doc, row, language, own)));
    if (!rows.length)
      box.append(
        el('p', T('这次没有适用的项。', 'Nothing applies this time.'), 'result-colleague__empty'),
      );
    else box.append(list);
    if (person && ask) {
      const foot = el('div', '', 'result-colleague__foot');
      foot.append(ask(person));
      box.append(foot);
    }
    root.append(box);
  };
  for (const col of byColleague(view, language))
    column(col.who, col.name, col.remit, col.rows, col.who);
  const rest = unowned(view);
  if (rest.length)
    column('other', T('其他', 'Other'), T('不归某位同事', 'Not one colleague’s'), rest);
  return root;
}
