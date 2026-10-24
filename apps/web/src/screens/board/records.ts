// The record (what was the Activity tab): who did what and when, kept out of the way in a
// drawer the topbar's ⏱ opens over the rail. Newest first, grouped by day.
import { icon } from '../../app/art.js';
import { T, when } from '../../app/i18n';

export type RecordEntry = {
  at: string;
  icon: string;
  tone?: string;
  text: string;
  zh?: boolean;
  open: { action: string; id?: string; role?: string; tab?: string; compare?: boolean } | null;
};

const esc = (v: unknown) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
const day = (at: string) => (at ? at.slice(0, 10) : '');

function row(e: RecordEntry) {
  const attrs = e.open
    ? `data-action="${esc(e.open.action)}"${e.open.id ? ` data-id="${esc(e.open.id)}"` : ''}${e.open.role ? ` data-role="${esc(e.open.role)}"` : ''}${e.open.tab ? ` data-tab="${esc(e.open.tab)}"` : ''}${e.open.compare ? ' data-compare="1"' : ''}`
    : '';
  const inner = `${icon(e.icon, 'i-sm')}<span class="grow"${e.zh ? ' lang="zh-CN"' : ''}>${esc(e.text)}</span>${e.at ? `<time datetime="${esc(e.at)}">${esc(when(e.at))}</time>` : ''}`;
  return `<li class="rec-item${e.tone ? ` rec-${esc(e.tone)}` : ''}">${e.open ? `<button type="button" class="rec-open" ${attrs}>${inner}</button>` : `<div class="rec-open">${inner}</div>`}</li>`;
}

export function recordsBody(list: RecordEntry[]) {
  if (!list.length)
    return `<p class="feed-empty">${T('发生的事会按时间记在这里。', 'What happens is recorded here, in order.')}</p>`;
  const groups: { day: string; rows: RecordEntry[] }[] = [];
  for (const e of list) {
    const d = day(e.at);
    const last = groups.at(-1);
    if (last && last.day === d) last.rows.push(e);
    else groups.push({ day: d, rows: [e] });
  }
  return groups
    .map(
      (g) =>
        `${groups.length > 1 && g.day ? `<h3 class="rec-day">${esc(g.day)}</h3>` : ''}<ol class="records">${g.rows.map(row).join('')}</ol>`,
    )
    .join('');
}
