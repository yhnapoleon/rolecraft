// "From your agent": the tray above the kanban (decision 11). It appears once your agent has
// connected. Empty, it is a dashed slot; a returned draft lands in it as a sheet of paper with
// Review and Dismiss. Dismiss only takes it off the tray; the work itself stays where it is.
import { icon } from '../../app/art.js';
import { T, when } from '../../app/i18n';
import { agentConnection } from '../../shell/agent-bus';

export type TrayDraft = {
  id: string;
  title: string;
  kind: string;
  version: number;
  at: string;
  /** open-artifact when filed under a task, preview-work otherwise. */
  review: string;
};

const dismissed = new Set<string>();
let landing: string | null = null;

export const dismissDraft = (id: string, version: number) => dismissed.add(`${id}@${version}`);
/** The agent just handed this draft back: the next tray render lets it land. */
export const draftLanded = (id: string) => {
  landing = id;
};
export const trayDrafts = (list: TrayDraft[]) =>
  list.filter((d) => !dismissed.has(`${d.id}@${d.version}`));

const esc = (v: unknown) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );

export function agentTray(o: { connected: boolean; drafts: TrayDraft[] }) {
  if (!o.connected) return '';
  const list = trayDrafts(o.drafts);
  const land = landing;
  landing = null;
  const head = `<header class="tray-head"><span class="tray-mark rc-agent-light" data-state="${agentConnection().state}" aria-hidden="true"></span><h2 id="tray-h">${T('来自你的 Agent', 'From your agent')}</h2>${list.length ? `<span class="sec-count">${list.length}</span>` : ''}</header>`;
  if (!list.length)
    return `<section class="agent-tray is-empty" aria-labelledby="tray-h">${head}<div class="tray-slot">${T('你的 Agent 交回的草稿会落在这里', "Your agent's drafts land here")}</div></section>`;
  return `<section class="agent-tray" aria-labelledby="tray-h">${head}<ul class="tray-list" role="list">${list
    .map(
      (d) =>
        `<li class="tray-paper${d.id === land ? ' landing' : ''}" data-tray-draft="${esc(d.id)}"><div class="tray-paper-body"><p class="tray-kind">${T('草稿', 'Draft')} · ${esc(d.kind)}</p><p class="tray-title">${esc(d.title)}</p><p class="tray-meta">${T('来自你的 Agent', 'from your agent')}${d.at ? ` · <time>${esc(when(d.at))}</time>` : ''}</p></div><div class="tray-keys"><button type="button" class="btn small" data-action="${d.review}" data-id="${esc(d.id)}">${icon('eye', 'i-sm')}${T('查看', 'Review')}</button><button type="button" class="btn small quiet" data-action="board-tray-dismiss" data-id="${esc(d.id)}" data-version="${d.version}">${T('移开', 'Dismiss')}</button></div></li>`,
    )
    .join('')}</ul></section>`;
}
