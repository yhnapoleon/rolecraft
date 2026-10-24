// "Investigate" on the stage scale: what has been found so far, as one read-only sheet of paper
// (option A, chosen by the user 2026-10-24). Four parts: documents, colleagues, tests, tasks and
// notes. Every row goes back to where it came from (the document sheet, the chat, the bench,
// the task). Built from what the practice already holds: no model call, nothing from the
// recognition layer. ui.js gathers the facts (findingsOf) and registers the route.
import './dossier.css';
import { avatar, icon, statusMark } from '../../app/art.js';
import { T } from '../../app/i18n';
import { docRowHtml } from '../board/documents';
import { registerActions } from '../../shell';

export type DocFinding = {
  id: string;
  title: string;
  version: number;
  group: 'cited' | 'new' | 'read' | 'unread';
};
export type PersonFinding = {
  role: 'manager' | 'business' | 'technical';
  name: string;
  title: string;
  asked: string;
  reply: string;
  count: number;
};
export type TestFinding = {
  id: string;
  question: string;
  answer: string;
  versions: string;
  stale: boolean;
  task: string;
};
export type WorkFinding = {
  id: string;
  title: string;
  purpose: string;
  version: string;
  adopted: boolean;
};
export type TaskFinding = {
  id: string;
  title: string;
  status: string;
  statusLabel: string;
  works: WorkFinding[];
};
export type Findings = {
  docs: DocFinding[];
  people: PersonFinding[];
  tests: TestFinding[];
  tasks: TaskFinding[];
  unfiled: WorkFinding[];
};

const FIRST = 5;
const open = new Set<string>();
let redraw: () => void = () => {};

const esc = (v: unknown) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
const zh = (text: string) => (/[一-鿿]/.test(text) ? ' lang="zh-CN"' : '');

// The first five rows of a part, then "N more", which opens the rest in place.
function rows(part: string, list: string[]) {
  const all = open.has(part);
  const shown = all ? list : list.slice(0, FIRST);
  const more = list.length - shown.length;
  return `<ul class="dz-rows" role="list">${shown.map((r) => `<li>${r}</li>`).join('')}</ul>${
    more > 0
      ? `<button type="button" class="dz-more" data-action="dossier-more" data-part="${part}" aria-expanded="false">${T(`另有 ${more} 条`, `${more} more`)}</button>`
      : all && list.length > FIRST
        ? `<button type="button" class="dz-more" data-action="dossier-more" data-part="${part}" aria-expanded="true">${T('收起', 'Show fewer')}</button>`
        : ''
  }`;
}

const part = (id: string, title: string, count: string, body: string) =>
  `<section class="dz-part" aria-labelledby="dz-${id}"><header class="dz-part-head"><h2 id="dz-${id}">${title}</h2><span class="dz-count">${count}</span></header>${body}</section>`;
const empty = (text: string) => `<p class="dz-empty">${text}</p>`;

function docs(list: DocFinding[]) {
  const order = { cited: 0, new: 1, read: 2, unread: 3 } as const;
  const known = list
    .filter((d) => d.group !== 'unread')
    .sort((x, y) => order[x.group] - order[y.group]);
  const unread = list.filter((d) => d.group === 'unread');
  // The board's own document row and marks (decision 9), so both screens read the same.
  const row = (d: DocFinding) => docRowHtml({ ...d, state: d.group });
  // Collapsed: the first five documents you got somewhere with, then one line for the rest
  // ("3 more read · 10 not read"), which opens all of them, unread ones last.
  const all = open.has('docs');
  const listed = all ? [...known, ...unread] : known.slice(0, FIRST);
  const moreRead = known.length - Math.min(known.length, FIRST);
  const rest = [
    moreRead ? T(`另有 ${moreRead} 份读过`, `${moreRead} more read`) : '',
    unread.length ? T(`${unread.length} 份没读`, `${unread.length} not read`) : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const body = `${
    listed.length
      ? `<ul class="doc-list dz-docs" role="list">${listed.map((d) => `<li>${row(d)}</li>`).join('')}</ul>`
      : empty(T('还没读过资料。', 'No documents read yet.'))
  }${
    all
      ? `<button type="button" class="dz-more" data-action="dossier-more" data-part="docs" aria-expanded="true">${T('收起', 'Show fewer')}</button>`
      : rest
        ? `<button type="button" class="dz-more" data-action="dossier-more" data-part="docs" aria-expanded="false">${rest}</button>`
        : ''
  }`;
  return part(
    'docs',
    T('资料', 'Documents'),
    T(
      `读了 ${list.length - unread.length} / ${list.length} 份`,
      `${list.length - unread.length} of ${list.length} read`,
    ),
    body,
  );
}

function people(list: PersonFinding[]) {
  const talked = list.filter((p) => p.count > 0).length;
  const row = (p: PersonFinding) =>
    `<button type="button" class="dz-row dz-person" data-action="chat" data-role="${p.role}">${avatar(p.role, 'sm')}<span class="dz-person-body"><span class="dz-person-name"><b>${esc(p.name)}</b><small>${esc(p.title)}</small></span>${
      p.count
        ? `${p.asked ? `<span class="dz-said"><span class="dz-said-who">${T('你问', 'You asked')}</span><span${zh(p.asked)}>${esc(p.asked)}</span></span>` : ''}${p.reply ? `<span class="dz-said"><span class="dz-said-who">${esc(p.name)}</span><span${zh(p.reply)}>${esc(p.reply)}</span></span>` : ''}`
        : `<span class="dz-said is-none">${T('还没问过', 'Not asked yet')}</span>`
    }</span><span class="dz-open">${p.count ? T(`${p.count} 条 · 打开对话`, `${p.count} messages · Open`) : T('去问', 'Ask')}</span></button>`;
  return part(
    'people',
    T('同事', 'Colleagues'),
    T(`问过 ${talked} / ${list.length} 位`, `${talked} of ${list.length} asked`),
    `<ul class="dz-rows" role="list">${list.map((p) => `<li>${row(p)}</li>`).join('')}</ul>`,
  );
}

function tests(list: TestFinding[]) {
  const row = (t: TestFinding) =>
    `<button type="button" class="dz-row dz-test" data-action="open-run" data-id="${esc(t.id)}">${icon('flask', 'i-sm dz-i')}<span class="dz-test-body"><span class="dz-q"${zh(t.question)}>${esc(t.question)}</span>${t.answer ? `<span class="dz-a"${zh(t.answer)}>${esc(t.answer)}</span>` : ''}</span><span class="dz-test-meta">${t.stale ? `<span class="dz-tag is-new">${icon('stale', 'i-xs')}${esc(t.versions)}</span>` : `<span class="dz-v">${esc(t.versions)}</span>`}${t.task ? `<span class="dz-task"${zh(t.task)}>${esc(t.task)}</span>` : ''}</span></button>`;
  return part(
    'tests',
    T('测试', 'Tests'),
    T(`${list.length} 次`, `${list.length} ${list.length === 1 ? 'run' : 'runs'}`),
    list.length
      ? rows('tests', list.map(row))
      : empty(T('还没在测试台问过助手。', 'No questions asked on the test bench yet.')),
  );
}

function work(w: WorkFinding) {
  return `<button type="button" class="dz-work" data-action="open-artifact" data-id="${esc(w.id)}"><span class="dz-work-title"${zh(w.title)}>${esc(w.title)}</span><span class="dz-work-meta">${esc(w.purpose)} · ${esc(w.version)} · ${w.adopted ? T('已采用', 'Adopted') : T('待你检查', 'Awaiting your check')}</span></button>`;
}

function tasks(list: TaskFinding[], unfiled: WorkFinding[]) {
  const count = list.reduce((n, t) => n + t.works.length, 0) + unfiled.length;
  const row = (t: TaskFinding) =>
    `<div class="dz-task-block"><button type="button" class="dz-row dz-task-row" data-action="open-task" data-id="${esc(t.id)}">${statusMark(t.status)}<span class="dz-task-title"${zh(t.title)}>${esc(t.title)}</span><span class="dz-v">${esc(t.statusLabel)}</span></button>${
      t.works.length
        ? `<div class="dz-works">${t.works.map(work).join('')}</div>`
        : `<p class="dz-empty is-inline">${T('还没有作品', 'No work yet')}</p>`
    }</div>`;
  const blocks = list.map(row);
  if (unfiled.length)
    blocks.push(
      `<div class="dz-task-block"><p class="dz-row dz-task-row is-unfiled">${icon('note', 'i-sm dz-i')}<span class="dz-task-title">${T('不在事项里的作品', 'Work outside any task')}</span></p><div class="dz-works">${unfiled.map(work).join('')}</div></div>`,
    );
  return part(
    'tasks',
    T('事项和笔记', 'Tasks and notes'),
    T(`${list.length} 件事项 · ${count} 份作品`, `${list.length} tasks · ${count} works`),
    blocks.length ? rows('tasks', blocks) : empty(T('还没有事项。', 'No tasks yet.')),
  );
}

/** The whole page: a quiet head on the desk, then the sheet. */
export function dossierHtml(f: Findings, back: { label: string; action: string }) {
  const read = f.docs.filter((d) => d.group !== 'unread').length;
  const talked = f.people.filter((p) => p.count > 0).length;
  const works = f.tasks.reduce((n, t) => n + t.works.length, 0) + f.unfiled.length;
  const reading = (label: string, num: string, unit: string) =>
    `<div class="dz-reading"><dt>${label}</dt><dd><b>${num}</b><span>${unit}</span></dd></div>`;
  return `<div class="dossier-page">
    <header class="dossier-head">
      <p class="dossier-kicker">${T('调查 · 只读', 'Investigate · read only')}</p>
      <h1 class="dossier-title">${T('到现在查到的', 'What you have found so far')}</h1>
      <p class="dossier-note">${T('这里只看，工作在工作板上做。', 'This page is for looking back; the work happens on the board.')}<button type="button" class="btn quiet small" data-action="${back.action}">${esc(back.label)}</button></p>
    </header>
    <article class="dossier" aria-labelledby="dossier-title">
      <h2 class="sr-only" id="dossier-title">${T('调查档案', 'Findings')}</h2>
      <dl class="dz-readings">
        ${reading(T('资料', 'Documents'), `${read}/${f.docs.length}`, T('份已读', 'read'))}
        ${reading(T('同事', 'Colleagues'), `${talked}/${f.people.length}`, T('位问过', 'asked'))}
        ${reading(T('测试', 'Tests'), String(f.tests.length), T('次', f.tests.length === 1 ? 'run' : 'runs'))}
        ${reading(T('作品', 'Works'), String(works), T('份', works === 1 ? 'piece' : 'pieces'))}
      </dl>
      ${docs(f.docs)}
      ${people(f.people)}
      ${tests(f.tests)}
      ${tasks(f.tasks, f.unfiled)}
    </article>
  </div>`;
}

/** ui.js hands over how to redraw the main screen after "N more". */
export function installDossier(o: { redraw: () => void }) {
  redraw = o.redraw;
}

registerActions({
  'dossier-more': (el) => {
    const p = el.dataset.part || '';
    if (open.has(p)) open.delete(p);
    else open.add(p);
    redraw();
    document
      .querySelector<HTMLElement>(`[data-action="dossier-more"][data-part="${CSS.escape(p)}"]`)
      ?.focus({ preventScroll: true });
  },
});
