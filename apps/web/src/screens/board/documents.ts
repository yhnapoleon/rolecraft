// The board's documents: a list under the kanban (decision 9), not a wall of cards. Six rows
// first, then "Show all". Each row says one thing on its right: a new version, your agent is
// reading it, unread, or cited in your work. The overlay opens from the row (open-doc).
import { icon } from '../../app/art.js';
import { T } from '../../app/i18n';

export type DocState = 'new' | 'agent' | 'unread' | 'cited' | 'read';
export type DocRow = { id: string; title: string; version: number; state: DocState };

const FIRST = 6;
const esc = (v: unknown) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );

// What changed comes first; the rest keeps the server's order, so a row never jumps while
// your agent reads it or once you have read it.
const RANK: Record<DocState, number> = { new: 0, agent: 1, unread: 1, cited: 1, read: 1 };
export const orderDocs = (rows: DocRow[]) =>
  rows
    .map((row, i) => ({ row, i }))
    .sort((x, y) => RANK[x.row.state] - RANK[y.row.state] || x.i - y.i)
    .map((x) => x.row);

function stateMark(s: DocState) {
  if (s === 'new') return `<span class="tag new">${T('有新版本', 'New version')}</span>`;
  if (s === 'agent')
    return `<span class="doc-agent"><span class="doc-agent-dot" aria-hidden="true"></span>${T('你的 Agent 在读', 'Your agent is reading')}</span>`;
  if (s === 'unread') return `<span class="doc-unread">${T('未读', 'Unread')}</span>`;
  if (s === 'cited')
    return `<span class="doc-cited">${icon('quote', 'i-xs')}${T('已引用', 'Cited')}</span>`;
  return '';
}

export function documentsSection(rows: DocRow[], opts: { all: boolean; loading?: string }) {
  const unread = rows.filter((r) => r.state === 'unread' || r.state === 'new').length;
  // "Documents · 18 · 15 unread" (decision 9): the separators keep the two figures apart.
  const head = `<header class="sec-head"><h2 id="docs-h">${T('资料', 'Documents')}</h2>${
    rows.length
      ? `<span class="sec-count">· ${T(`${rows.length} 份`, String(rows.length))}${unread ? ` · ${T(`${unread} 份未读`, `${unread} unread`)}` : ''}</span>`
      : ''
  }</header>`;
  if (!rows.length)
    return `<section class="work-sec docs-sec" aria-labelledby="docs-h">${head}<p class="empty-line">${esc(opts.loading || '')}</p></section>`;
  const list = orderDocs(rows);
  // A document your agent is reading shows even past the first six.
  const shown = opts.all ? list : list.filter((r, i) => i < FIRST || r.state === 'agent');
  const more = list.length - shown.length;
  return `<section class="work-sec docs-sec" aria-labelledby="docs-h">${head}
    <ul class="doc-list" role="list">${shown
      .map(
        (r) =>
          `<li><button type="button" class="doc-row is-${r.state}" data-action="open-doc" data-id="${esc(r.id)}" data-doc-row="${esc(r.id)}">${icon('doc', 'i-sm doc-row-i')}<span class="doc-row-title">${esc(r.title)}</span><span class="doc-row-v">v${r.version}</span><span class="doc-row-state">${stateMark(r.state)}</span></button></li>`,
      )
      .join('')}</ul>
    ${more > 0 ? `<button type="button" class="doc-more" data-action="board-docs-all" aria-expanded="false">${T(`显示全部 ${list.length} 份`, `Show all ${list.length}`)}</button>` : opts.all && list.length > FIRST ? `<button type="button" class="doc-more" data-action="board-docs-all" aria-expanded="true">${T('收起', 'Show fewer')}</button>` : ''}
  </section>`;
}

// Who to ask about a document when the scenario names nobody (B2): the manager's own papers go
// to Grace; business and data to Chen; policies, knowledge sources, the index and the system to
// Daniel. Fixed rules, no model.
const OWNER: Record<string, 'manager' | 'business' | 'technical'> = {
  approvals: 'manager',
  brief: 'manager',
  demo: 'manager',
  business_case: 'business',
  coordination: 'business',
  demand: 'business',
  interviews: 'business',
  restricted: 'business',
  scope_note: 'business',
  user_groups: 'business',
  policy: 'technical',
  faq: 'technical',
  leave: 'technical',
  meal: 'technical',
  onboarding: 'technical',
  failures: 'technical',
  technical: 'technical',
  trial_details: 'technical',
};
export const docOwner = (id: string) => OWNER[id] ?? 'business';

// A new version that changed more than its figures (o1): the words around them differ too.
export const wordingChanged = (before: string, after: string) => {
  const words = (t: string) =>
    String(t)
      .replace(/\d+(?:[.,]\d+)?/g, '#')
      .replace(/\s+/g, ' ')
      .trim();
  return words(before) !== words(after);
};

// The colleague's role, short enough for one line of the rail in both languages (B5).
const ROLE_LINE = {
  manager: ['目标、资源、优先级', 'Goals, resources, priorities'],
  business: ['首批用户与业务流程', 'First users and how the business runs'],
  technical: ['系统限制、索引与测试证据', 'System limits, index, test evidence'],
} as const;
export const roleLine = (r: keyof typeof ROLE_LINE) => T(ROLE_LINE[r][0], ROLE_LINE[r][1]);
