// RoleCraft workbench. A workplace in two levels: the board shows the whole job, and
// each task opens its own workbench. Server state (materials, colleagues, tests,
// approvals, submission, review) comes from the API through window.PracticeLive;
// tasks, work, agent imports and the scenario rules in coach.js are local.
import { T, locale, getPreference, setPreference, onLocaleChange, detect, when, isChinese } from './i18n';
import { icon, priMark, statusMark, PEOPLE, ROLES, avatar, agentMark, assistantMark } from './art.js';
import * as Coach from './coach.js';
import { PRI, STATUS, ROLE_TITLE, KNOWS, OPENER, CASE, SEED_KEYS, situationTask, taskTitle, taskNote, seedText, purposeLabel, purposeFromLabel, INTENT_HINT, UPDATE, FALLBACK, DOMAIN, WORK_ITEM, WORK_COST, materialTitle, criterionName, LABEL, FIELDS, FIELD, FIELD_HINT, errText } from './vocab.js';
import { pendingTurnRole, serverText } from '../store';
import { eventLine, isFeedEvent } from './events.js';
import { testSetView, testSetPreview, caseState, testRunView } from './test-set-view.js';
import './test-set.css';
import { investigationView, investigationPreview, investigationSourceKey } from './investigation-view.js';
import './investigation.css';
import { createDocumentMotion } from './document-motion.js';
import './document-motion.css';
import { workFolderMarkup, installWorkFolders } from './work-folder.js';
import './work-folder.css';

const L = window.PracticeLive;
const E = L.engine;
const app = document.getElementById('app');
const sheet = document.getElementById('sheet');
const toastEl = document.getElementById('toast');
const KEY = 'rolecraft.open-work.ui.v1';
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const documentMotion = createDocumentMotion();
const ROLE_ID = { manager: 'supervisor', business: 'business_lead', technical: 'tech_lead' };
const ROLE_OF = { supervisor: 'manager', business_lead: 'business', tech_lead: 'technical' };
const INDEX_DELAY_HOURS = 24; // scenario constant; not yet part of the session state

/* ---------- local record ---------- */
let state; let storageIssue = ''; let storageLocked = false; let rawRecord = null;
try {
  rawRecord = localStorage.getItem(KEY);
  state = rawRecord ? JSON.parse(rawRecord) : E.newState();
  if (!state || state.version !== E.VERSION || !Array.isArray(state.attempts)) throw new Error('version');
  state.attempts = state.attempts.filter(a => { try { E.normalizeAttempt(a); return true; } catch (_) { return false; } });
  if (state.activeId && !state.attempts.some(a => a.id === state.activeId)) state.activeId = null;
} catch (err) {
  state = E.newState(); storageLocked = true;
  storageIssue = err && err.name === 'SecurityError' ? 'blocked' : 'unreadable';
}
const storageText = () => ({
  blocked: T('这个浏览器不允许本页保存，本地笔记只留在当前页面。', 'This browser blocks saving, so local notes stay on this page only.'),
  unreadable: T('之前的本地记录读不出来，原记录没有被覆盖。', 'Earlier local notes could not be read. The original record is untouched.'),
  failed: T('浏览器没能保存本地笔记。', 'The browser could not save your local notes.')
})[storageIssue] || '';

const ui = {
  route: null, routeId: null, obj: null, artifactId: null,
  rail: 'team', railTab: 'team', chatRole: null, railOpen: false, menu: null, scopeAll: false, advice: null, benchAll: false, reviewFor: null, notesCache: [],
  intake: { text: '', result: null, open: false }, busy: false, lastRun: null,
  importText: '', exportScope: { artifacts: true, materials: true, tests: true },
  labPrefill: '', compare: false, previous: {}, arriving: false, landing: false, editPending: null, previewWorkId: null,
  investigationSources: {}, investigationErrors: {}, investigationViews: {}, investigationComposing: false, investigationRefreshQueued: false,
  testOpen: {}, testHistory: {}, testModes: {}, testErrors: {}, configFromTestSet: false,
  synced: false, lastError: '', pendingRequestId: null, lastUndo: null, pendingCite: null
};
let dirty = null; let saveTimer = null; let toastTimer = null; let sheetReturn = null; let dragId = null;

/* ---------- helpers ---------- */
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const current = () => E.getAttempt(state);
const sessionOf = a => (a ? L.session(a) : null);
const snap = () => L.store.getSnapshot();
const task = () => { const a = current(); return a && ui.route === 'task' ? a.tasks.find(t => t.id === ui.routeId) || null : null; };
const artifact = () => { const a = current(); return a ? a.artifacts.find(x => x.id === ui.artifactId && !x.removedAt) || null : null; };
const works = a => E.currentArtifacts(a);
const isEarlier = (a, x) => x.adopted && !works(a).some(y => y.id === x.id);
const taskWorks = (a, id) => a.artifacts.filter(x => x.taskId === id && !x.removedAt && !isEarlier(a, x));
const shown = x => (x.draft ? Object.assign({}, x, x.draft) : x);
// What a piece of work is for: flask = a test plan, branch = options, stamp = the decision you will submit.
const purposeGlyph = intent => ({ plan: 'flask', option: 'branch', commit: 'stamp' }[intent] ? icon({ plan: 'flask', option: 'branch', commit: 'stamp' }[intent], 'i-xs purpose-i') : '');
// Doing something on a task moves it from 待处理 to 正在做; calling it done stays with you.
const startWorking = (a, t) => { if (t && t.status === 'open') E.updateTask(a, t.id, { status: 'working' }); };
const hasDecision = a => works(a).some(w => { const v = shown(w); return E.intentOf(v.purpose) === 'commit' && v.body.trim(); });
const scen = id => E.scenarios.find(s => s.id === id) || E.scenarios[0];
const statusOf = a => (a && a.backend && a.backend.status) || 'active';
const canWrite = a => { const s = sessionOf(a); const n = snap(); return !!s && s.world.status === 'active' && !n.busy && !s.pending && !n.storageError; };
const typingRole = a => ROLE_OF[pendingTurnRole(sessionOf(a))] || null;
const vtName = s => String(s).replace(/[^a-zA-Z0-9-]/g, '');
const zhAttr = text => (locale() === 'en' && isChinese(text) ? ' lang="zh-CN"' : '');
const zhTag = text => (locale() === 'en' && isChinese(text) ? '<span class="msg-local" title="The server has no English version of this text yet">Chinese source</span>' : '');
const readSet = a => new Set(a.events.filter(e => e.server && e.type === 'material_read').map(e => e.detail && e.detail.materialId));
const unread = (a, role) => { const n = (a.conversations[role] || []).filter(m => m.role !== 'user').length; return Math.max(0, n - ((a.readTurns || {})[role] ?? n)); };
const btn = (label, action, cls = '', attrs = '') => `<button type="button" class="btn ${cls}" data-action="${action}" ${attrs}>${label}</button>`;
const answerText = s => String(s || '').replace(/^#{1,6}\s+/, '');

function md(raw, opts = {}) {
  let lines = esc(raw || '').split('\n');
  if (opts.dropTitle && /^#\s/.test(lines[0] || '')) lines = lines.slice(1);
  let out = ''; let list = null;
  const inline = s => s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  const close = () => { if (list) { out += `</${list}>`; list = null; } };
  for (const line of lines) {
    const ul = line.match(/^\s*[-*]\s+(.*)$/); const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) { const kind = ul ? 'ul' : 'ol'; if (list !== kind) { close(); out += `<${kind}>`; list = kind; } out += '<li>' + inline((ul || ol)[1]) + '</li>'; continue; }
    close();
    if (/^#{1,2}\s/.test(line)) out += '<h3>' + inline(line.replace(/^#{1,2}\s/, '')) + '</h3>';
    else if (/^#{3,6}\s/.test(line)) out += '<h4>' + inline(line.replace(/^#{3,6}\s/, '')) + '</h4>';
    else if (line.trim()) out += '<p>' + inline(line) + '</p>';
  }
  close();
  return out || `<p class="muted">${T('还没有正文。', 'Nothing written yet.')}</p>`;
}

// Word-level comparison for document versions. Chinese is compared by character.
function diffHtml(before, after) {
  const tokens = s => (String(s).match(/[一-鿿]|[A-Za-z0-9_.]+|\s+|[^\sA-Za-z0-9_一-鿿]/g) || []);
  const a = tokens(before); const b = tokens(after);
  if (a.length * b.length > 4e6) return md(after, { dropTitle: true });
  const dp = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let i = 0; let j = 0; const ops = [];
  const put = (cls, t) => { const last = ops[ops.length - 1]; if (last && last[0] === cls) last[1] += t; else ops.push([cls, t]); };
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { put('', a[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { put('del', a[i]); i++; } else { put('ins', b[j]); j++; }
  }
  while (i < a.length) put('del', a[i++]);
  while (j < b.length) put('ins', b[j++]);
  // Wrap each changed run per line so paragraphs survive.
  const out = ops.map(([cls, t]) => t.split('\n').map(part => cls && part ? `<${cls}>${esc(part)}</${cls}>` : esc(part)).join('\n')).join('');
  return `<div class="diff">${out.split('\n').filter(l => l.replace(/<[^>]+>/g, '').trim() && !/^(<\w+>)?#\s/.test(l)).map(l => `<p>${l}</p>`).join('')}</div>`;
}
function investigationDiffHtml(before, after) {
  const count = text => (String(text).match(/[一-鿿]|[A-Za-z0-9_.]+|\s+|[^\sA-Za-z0-9_一-鿿]/g) || []).length;
  if (count(before) * count(after) > 4e6) return `<p class="inv-missing">${T('正文较长，未生成逐字差异。切换到“原文”分别核对，原文均完整保留。','These sources are too long for word-by-word comparison. Switch to Originals to read both complete texts.')}</p>`;
  return diffHtml(before, after);
}

/* ---------- saving ---------- */
function persist() {
  if (storageLocked) { updateSave(); return false; }
  try { localStorage.setItem(KEY, JSON.stringify(state)); if (storageIssue === 'failed') storageIssue = ''; updateSave(); return true; }
  catch (_) { storageIssue = 'failed'; updateSave(); return false; }
}
function saveLabel() {
  const x = artifact();
  if (storageIssue) return T('没有保存', 'Not saved');
  if (dirty) return T('正在保存…', 'Saving…');
  return x && x.draft ? T('草稿已保存', 'Draft saved') : T('已存本机', 'Saved locally');
}
function updateSave() {
  document.querySelectorAll('[data-save]').forEach(el => { el.textContent = saveLabel(); el.classList.toggle('error', !!storageIssue); });
  const x = artifact(); document.querySelectorAll('[data-revision]').forEach(el => { if (x) el.textContent = 'v' + x.revision; });
}
// A pause in typing keeps a draft; leaving the editor, switching, submitting or ⌘S makes a version.
function flush() {
  clearTimeout(saveTimer);
  if (!dirty) return false;
  const a = state.attempts.find(x => x.id === dirty.attemptId); const x = a && a.artifacts.find(y => y.id === dirty.id);
  if (x) x.draft = { title: dirty.title || T('未命名', 'Untitled'), purpose: dirty.purpose, body: dirty.body, ...(dirty.cases ? { kind: 'test_set', cases: dirty.cases } : {}), ...(dirty.blocks ? {kind:'investigation',question:dirty.question,blocks:dirty.blocks,review:dirty.review} : {}) };
  dirty = null; persist();
  return !!x;
}
// All investigation fields share one draft so rapid edits and evidence refreshes
// preserve each other. Reading options stay separate from the saved work.
function queueInvestigationDraft(a, x, patch) {
  const pending = dirty?.attemptId === a.id && dirty.id === x.id ? dirty : null;
  const next = { ...shown(x), ...pending, ...patch, kind: 'investigation' };
  const review = structuredClone(next.review || { focus: 'uncertain', note: '' });
  dirty = { attemptId: a.id, id: x.id, kind: 'investigation', title: next.title,
    purpose: next.purpose, question: next.question, blocks: structuredClone(next.blocks), review,
    body: E.investigationSummary({ ...next, review }) };
  updateSave(); clearTimeout(saveTimer); saveTimer = setTimeout(flush, 450);
}
function investigationViewState(a, x) {
  const key = a.id + '|' + x.id;
  return ui.investigationViews[key] ||= { modes: {}, open: {} };
}
function commit() {
  flush();
  let changed = false;
  state.attempts.forEach(a => a.artifacts.forEach(x => {
    if (!x.draft || x.removedAt) return;
    const d = x.draft; delete x.draft;
    try { const before = x.revision; E.saveArtifact(a, x.id, d); changed = changed || x.revision !== before; } catch (err) { x.draft = d; notify(errText(err)); }
  }));
  persist();
  return changed;
}

/* ---------- toast & announcements ---------- */
function notify(text, opts = {}) {
  if (sheet.open && [...sheet.querySelectorAll('[data-approval-denial] span')].some(el => el.textContent === text)) { announce(text); return; }
  if (sheet.open && !sheet.classList.contains('closing') && !opts.undo && !opts.action && !opts.toast) {
    let el = sheet.querySelector('.inline-alert');
    if (!el) { el = document.createElement('div'); el.className = 'inline-alert'; el.setAttribute('role', 'alert'); sheet.querySelector('.sheet-body')?.prepend(el); }
    el.textContent = text; return;
  }
  const act = opts.undo ? { label: T('撤销', 'Undo'), run: opts.undo } : opts.action;
  toastEl.innerHTML = `${opts.lead || ''}<span class="toast-text">${esc(text)}</span>${act ? `<button type="button" class="toast-act">${esc(act.label)}</button>` : ''}`;
  toastEl.classList.add('visible'); toastEl.classList.toggle('actionable', !!act);
  ui.lastUndo = opts.undo || null;
  if (act) toastEl.querySelector('.toast-act').onclick = () => { act.run(); ui.lastUndo = null; toastEl.classList.remove('visible'); };
  announce(text);
  const hide = () => { if (!toastEl.matches(':hover, :focus-within')) toastEl.classList.remove('visible'); else toastTimer = setTimeout(hide, 1500); };
  clearTimeout(toastTimer); toastTimer = setTimeout(hide, act ? 6500 : 3200);
}
function announce(text) { const el = document.getElementById('announcer'); if (!el) return; el.textContent = ''; setTimeout(() => { el.textContent = text; }, 30); }

/* ---------- routing ---------- */
// #/ jobs · #/pm entry · #/work board · #/task/<id> task workbench · #/doc/<id> · #/bench · #/review
const WS = ['work', 'task', 'doc', 'bench'];
function parseRoute() {
  const [r, id] = location.hash.replace(/^#\/?/, '').split('/');
  if (['pm', 'work', 'bench', 'review'].includes(r)) return { r, id: null };
  if ((r === 'task' || r === 'doc') && id) return { r, id: decodeURIComponent(id) };
  return { r: '', id: null };
}
const hashOf = (r, id) => '#/' + r + (id ? '/' + encodeURIComponent(id) : '');
let activeTransition = null;
function withTransition(fn) {
  if (activeTransition) { try { activeTransition.skipTransition(); } catch (_) { /* finished */ } }
  if (!document.startViewTransition || reduceMotion.matches) { fn(); return; }
  const transition = document.startViewTransition(() => { fn(); });
  activeTransition = transition;
  transition.finished.finally(() => { if (activeTransition === transition) activeTransition = null; });
}
// An undo belongs to the page it was offered on; leaving the page withdraws it.
function dropUndo() { if (ui.lastUndo) { ui.lastUndo = null; toastEl.classList.remove('visible'); } }
function go(route, opts = {}) {
  commit(); dropUndo();
  if ((WS.includes(route) || route === 'review') && !current()) route = 'pm';
  const id = opts.id || null;
  const from = ui.route, fromId = ui.routeId;
  const run = () => { if (sheet.open) closeSheet(true); ui.menu = null; ui.railOpen = false; ui.advice = null; ui.route = route; ui.routeId = id; history.pushState(null, '', hashOf(route, id)); render(); window.scrollTo(0, 0); document.getElementById('main')?.scrollTo?.(0, 0); };
  if ((from === 'work' && route === 'doc') || (from === 'doc' && route === 'work')) {
    activeTransition?.skipTransition();
    documentMotion.transition(from, route, route === 'doc' ? id : fromId, run);
  } else { documentMotion.cancel(); if (opts.transition) withTransition(run); else run(); }
}
window.addEventListener('popstate', () => {
  commit(); dropUndo(); if (sheet.open) closeSheet(true); ui.menu = null; ui.advice = null;
  const from = ui.route, fromId = ui.routeId, p = parseRoute();
  const update = () => { ui.route = p.r; ui.routeId = p.id; render(); if (p.r === 'doc') document.getElementById('main')?.scrollTo(0,0); };
  if ((from === 'work' && p.r === 'doc') || (from === 'doc' && p.r === 'work')) {
    activeTransition?.skipTransition(); documentMotion.transition(from, p.r, p.r === 'doc' ? p.id : fromId, update);
  } else { documentMotion.cancel(); withTransition(update); }
});

/* ---------- render ---------- */
function render() {
  const key = focusKey();
  if (ui.route == null) { const p = parseRoute(); ui.route = p.r; ui.routeId = p.id; }
  const r = ui.route;
  if (r === 'task' && current() && !current().tasks.some(t => t.id === ui.routeId)) { ui.route = 'work'; ui.routeId = null; history.replaceState(null, '', hashOf('work')); }
  document.body.dataset.view = WS.includes(ui.route) ? 'work' : (ui.route || 'careers');
  const banner = storageIssue ? `<div class="storage-alert" role="alert">${icon('info', 'i-sm')}<span>${esc(storageText())}</span>${btn(T('导出本地笔记', 'Export local notes'), 'export', 'small quiet')}${rawRecord && storageLocked ? btn(T('另存后重新开始', 'Back up and start fresh'), 'reset-storage', 'small quiet') : ''}</div>` : '';
  if (r === 'pm') app.innerHTML = banner + renderEntry();
  else if (WS.includes(ui.route) && current()) app.innerHTML = banner + renderWorkspace();
  else if (r === 'review' && current()) app.innerHTML = banner + renderReview();
  else app.innerHTML = banner + renderCareers();
  afterRender();
  restoreFocus(key);
}
function afterRender() {
  // Only the workbench's own scroll regions move; browser focus must not shift
  // the entire fixed-height workspace (especially after viewport changes).
  if (WS.includes(ui.route) && window.scrollY) window.scrollTo(0, 0);
  document.querySelectorAll('.segmented').forEach(layoutSegmented);
  const body = document.getElementById('editor-body'); if (body) autoGrow(body);
  document.querySelectorAll('.thread').forEach(t => { t.scrollTop = t.scrollHeight; });
  updateSave(); syncPanels(); markRead();
  const a = current();
  const activeWork = a && ui.obj?.type === 'work' ? artifact() : null; if(activeWork?.kind === 'investigation') loadInvestigationSources(a, shown(activeWork));
  document.title = (WS.includes(ui.route) || ui.route === 'review') && a ? CASE(a.scenarioId).title + ' · Practice' : T('Practice · 在真实的工作里练习', 'Practice · Learn on real work');
  const skip = document.querySelector('.skip-link'); if (skip) skip.textContent = T('跳到主要内容', 'Skip to content');
  documentMotion.sync();
  workFolders.sync();
}
function layoutSegmented(seg) {
  const active = seg.querySelector('[aria-pressed="true"]'); const thumb = seg.querySelector('.thumb');
  if (!thumb) return; if (!active) { thumb.style.opacity = '0'; return; }
  thumb.style.opacity = '1'; thumb.style.width = active.offsetWidth + 'px'; thumb.style.transform = `translateX(${active.offsetLeft - 2}px)`;
}
const nativeGrow = window.CSS && CSS.supports && CSS.supports('field-sizing', 'content');
function autoGrow(el) {
  if (nativeGrow) return;
  // The desk scrolls, not the window; keep its position while the field resizes.
  const box = el.closest('.desk'); const y = box ? box.scrollTop : window.scrollY;
  el.style.height = 'auto'; el.style.height = Math.max(el.scrollHeight, 320) + 'px';
  if (box) box.scrollTop = y; else if (window.scrollY !== y) window.scrollTo(0, y);
}
function focusKey() {
  const el = document.activeElement; if (!el || el === document.body) return null;
  if (el.id && el.id !== 'main') return { id: el.id, pos: el.selectionStart ?? null, end: el.selectionEnd ?? null, direction: el.selectionDirection ?? 'none' };
  if(el.tagName==='SUMMARY'&&el.parentElement?.dataset.key) return {sel:`.investigation-work details[data-key="${CSS.escape(el.parentElement.dataset.key)}"] > summary`};
  const d = el.dataset || {}; const parts = ['action', 'id', 'view', 'role', 'rail', 'change', 'case', 'key', 'menu', 'lang', 'status', 'mode', 'investigationReview'].filter(k => d[k] !== undefined).map(k => `[data-${k.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())}="${CSS.escape(d[k])}"]`);
  return parts.length ? { sel: el.tagName.toLowerCase() + parts.join('') } : null;
}
function restoreFocus(key) {
  if (!key) return;
  const el = key.id ? document.getElementById(key.id) : document.querySelector(key.sel);
  if (!el || el === document.activeElement) return;
  el.focus({ preventScroll: true });
  if (key.pos != null && el.setSelectionRange) try { el.setSelectionRange(key.pos, key.end ?? key.pos, key.direction || 'none'); } catch (_) { /* not a text field */ }
}

/* ---------- shared chrome ---------- */
const wordmark = () => `<button type="button" class="wordmark" data-action="home" aria-label="${esc(T('Practice，回到岗位选择', 'Practice, back to jobs'))}"><span class="wordmark-glyph" aria-hidden="true"></span><span>Practice</span></button>`;
const backBtn = (action, label) => `<button type="button" class="btn quiet back" data-action="${action}">${icon('back')}<span>${esc(label)}</span></button>`;
function langControl() {
  return `<div class="menu-wrap"><button type="button" class="btn quiet lang-btn" data-action="menu" data-menu="lang" aria-haspopup="menu" aria-expanded="${ui.menu === 'lang'}" aria-label="${esc(T('界面语言：中文', 'Interface language: English'))}">${icon('globe', 'i-sm')}<span class="lang-now">${locale() === 'zh' ? '中文' : 'EN'}</span></button>${ui.menu === 'lang' ? langMenu() : ''}</div>`;
}
function langMenu() {
  const pref = getPreference();
  const item = (v, label, sub = '') => `<button type="button" role="menuitemradio" aria-checked="${pref === v}" data-action="set-lang" data-lang="${v}"><span class="grow">${label}${sub ? `<small>${sub}</small>` : ''}</span>${pref === v ? icon('check', 'i-sm') : ''}</button>`;
  return `<div class="menu" role="menu">${item('auto', T('跟随系统', 'Match system'), detect() === 'zh' ? '中文' : 'English')}${item('zh', '中文')}${item('en', 'English')}</div>`;
}
const topbar = (left, right = '') => `<header class="topbar">${left}<div class="spacer"></div>${right}${langControl()}</header>`;
const letter = (role, quote, size = '') => `<figure class="letter ${size}">${avatar(role, size === 'sm' ? 'sm' : size === 'lg' ? 'lg' : 'md')}<div class="letter-body"><blockquote>${esc(quote)}</blockquote><figcaption>${PEOPLE[role].name}<span>${ROLE_TITLE(role)}</span></figcaption></div></figure>`;
const facts = w => [
  ['seats', T(`${w.capacity} 人容量`, `${w.capacity} seats`)],
  ['hours', T(`${w.devDays} 人日开发`, `${w.devDays} person-days`)],
  ['calendar', T(`第 ${w.deadline} 天上线`, `Launch on day ${w.deadline}`)],
  ['sync', T(`索引最多滞后 ${INDEX_DELAY_HOURS} 小时`, `Index up to ${INDEX_DELAY_HOURS} h behind`)]
];
const FACT_KEYS = ['capacity', 'devDays', 'deadline', 'delay'];
const factRow = (w, cls = '') => `<ul class="facts ${cls}">${facts(w).map(([i, l], n) => `<li class="${ui.changed && ui.changed.until > Date.now() && ui.changed.keys.includes(FACT_KEYS[n]) ? 'changed' : ''}">${icon(i, 'i-sm')}<span>${l}</span></li>`).join('')}</ul>`;
function priPick(id, p, title, change = 'priority') {
  return `<label class="pri-pick" title="${esc(PRI(p))}">${priMark(p)}<select aria-label="${esc(T('「' + title + '」的优先级：' + PRI(p), 'Priority for “' + title + '”: ' + PRI(p)))}" data-change="${change}" data-id="${esc(id)}">${['first', 'next', 'later'].map(k => `<option value="${k}" ${k === p ? 'selected' : ''}>${PRI(k)}</option>`).join('')}</select></label>`;
}

/* ---------- 1. jobs ---------- */
function renderCareers() {
  const a = current(); const t = a && a.tasks.find(x => x.id === a.selectedTaskId);
  const resume = a ? `<section class="resume"><span class="resume-icon">${icon('note')}</span><div class="grow"><p class="resume-title">${esc(CASE(a.scenarioId).title)}</p><p class="resume-sub">${statusOf(a) === 'submitted' ? T('已交付，可以看评审', 'Submitted. The review is ready to read.') : t ? esc(T('停在「' + taskTitle(t) + '」', 'Stopped at “' + taskTitle(t) + '”')) : T('还没开始具体的事', 'Nothing started yet')}</p></div>${btn(statusOf(a) === 'submitted' ? T('看评审', 'See review') : T('继续', 'Continue'), statusOf(a) === 'submitted' ? 'review-attempt' : 'resume', 'primary', `data-id="${a.id}"`)}</section>` : '';
  const preview = `<div class="mini-board" aria-hidden="true">
    <div class="mb-cols">${[['first', []], ['next', SEED_KEYS], ['later', []]].map(([p, keys]) => `<div class="mb-col"><p class="mb-head">${priMark(p)}${PRI(p)}</p>${keys.map(k => `<div class="mb-card"><span class="mb-status">${statusMark('open')}</span><span>${esc(seedText(k))}</span></div>`).join('') || '<div class="mb-empty"></div>'}</div>`).join('')}</div>
    <div class="mb-side"><p class="mb-head">${T('团队', 'Team')}</p>${ROLES.map(r => `<div class="mb-person">${avatar(r, 'xs')}<span>${PEOPLE[r].name}</span><small>${ROLE_TITLE(r)}</small></div>`).join('')}<div class="mb-person">${agentMark('xs')}<span>${T('我的 Agent', 'My agent')}</span></div></div>
  </div>`;
  return `${topbar(wordmark())}
    <main id="main" class="page careers" tabindex="-1">
      <header class="hero">
        <h1 class="display">${T('你想先练哪份工作？', 'Which job do you want to practise?')}</h1>
        <p class="lede">${T('接手一件真实的工作。可以犯错，可以求助，也可以重来。', 'Take on a real piece of work. Get it wrong, ask for help, try again.')}</p>
      </header>
      ${resume}
      <div class="career-grid">
        <article class="career open">
          <div class="career-art">${preview}</div>
          <div class="career-body">
            <h2 class="career-name"><span style="view-transition-name: career-pm">${T('AI 产品经理', 'AI Product Manager')}</span></h2>
            <p>${T('判断一个 AI 功能该不该上线、先给谁用、怎样保障，并为这个决定负责。', 'Decide whether an AI feature should launch, who gets it first and how it stays safe, then own the call.')}</p>
            <p class="meta">${T('3 个情境，每次 20–30 分钟。上面是你会用到的工作板：三件起始事项和三位同事。', '3 situations, 20–30 min each. Above is the board you will work on: three starting tasks and three colleagues.')}</p>
            <div class="career-cta">${btn(a ? T('看看所有工作', 'See all work') : T('开始', 'Start'), 'open-career', a ? '' : 'primary large')}</div>
          </div>
        </article>
        <article class="career later" aria-disabled="true">
          <div class="career-art later-art"><span class="soon">${icon('lock', 'i-sm')}${T('稍后开放', 'Coming later')}</span><ul class="later-list"><li>${T('复现检索与回答问题', 'Reproduce retrieval and answer bugs')}</li><li>${T('修改代码或配置', 'Change code or config')}</li><li>${T('用可复现的测试证明修复', 'Prove the fix with repeatable tests')}</li></ul></div>
          <div class="career-body">
            <h2 class="career-name">${T('AI 应用工程师', 'AI Application Engineer')}</h2>
            <p>${T('需要可运行的代码环境和回归检查，排在 AI 产品经理之后。', 'Needs a runnable code environment and regression checks; it comes after AI Product Manager.')}</p>
          </div>
        </article>
      </div>
    </main>`;
}

/* ---------- 2. PM entry ---------- */
function renderEntry() {
  const last = id => state.attempts.filter(a => a.scenarioId === id).at(-1);
  const attempts = state.attempts.slice().reverse();
  return `${topbar(backBtn('home', T('岗位', 'Jobs')))}
    <main id="main" class="page entry" tabindex="-1">
      <header class="entry-head">
        <h1 class="title-xl"><span style="view-transition-name: career-pm">${T('AI 产品经理', 'AI Product Manager')}</span></h1>
        <p class="lede">${T('你负责判断一个 AI 功能能不能上线、先给谁用、怎样保障，并为这个决定负责。', 'You decide whether an AI feature is ready, who gets it first and how it stays safe, and you own that call.')}</p>
      </header>
      ${caseHero('pilot', last('pilot'))}
      <section class="block">
        <h2 class="section-title">${T('同样的责任，换一个条件', 'Same job, one condition changed')}</h2>
        <div class="variants">${['urgent', 'capacity'].map(id => variantCard(id, last(id))).join('')}</div>
      </section>
      <section class="block">${intakeBlock()}</section>
      ${attempts.length ? practiceList(attempts) : ''}
    </main>`;
}
const worldOf = id => { const s = scen(id); return { capacity: s.capacity, devDays: 3, deadline: s.deadline }; };
// What the situation asks for, as numbers with names. A variant marks the one that changed.
function caseConditions(id) {
  const w = worldOf(id); const base = worldOf('pilot');
  const item = (value, label, was) => `<div class="cond ${was ? 'changed' : ''}"><span class="cond-val">${value}</span><span class="cond-label">${label}</span>${was ? `<span class="cond-was">${T('通常是', 'usually')} ${was}</span>` : ''}</div>`;
  return `<div class="conds big">
    ${item(T(w.capacity + ' 人', w.capacity + ' seats'), T('试点容量', 'Capacity'), w.capacity !== base.capacity ? T(base.capacity + ' 人', String(base.capacity)) : '')}
    ${item(T(w.devDays + ' 人日', w.devDays + ' person-days'), T('可用开发', 'Engineering'))}
    ${item(T('第 ' + w.deadline + ' 天', 'Day ' + w.deadline), T('期望上线', 'Launch target'), w.deadline !== base.deadline ? T('第 ' + base.deadline + ' 天', 'day ' + base.deadline) : '')}
    ${item(T(INDEX_DELAY_HOURS + ' 小时', INDEX_DELAY_HOURS + ' h'), T('索引最长滞后', 'Index lag, max'))}
  </div>`;
}
function caseHero(id, existing) {
  const c = CASE(id);
  const go1 = existing && statusOf(existing) !== 'submitted';
  return `<article class="case-hero" style="view-transition-name: case-surface">
    <div class="case-main">
      <h2 class="case-title"><span style="view-transition-name: case-title">${esc(c.title)}</span></h2>
      ${letter('manager', c.quote)}
      ${caseConditions(id)}
      <div class="seeds"><p class="seeds-cap">${T('你会接手这三件事，可以先排个优先级', 'You will pick up these three tasks; rank them now if you like')}</p>${SEED_KEYS.map((k, i) => `<div class="seed" style="view-transition-name: seed-${i}">${priPick(id + '-' + i, 'next', seedText(k), 'triage')}<span>${esc(seedText(k))}</span></div>`).join('')}</div>
      <footer class="case-foot"><span class="meta">${T(c.minutes + '，没有倒计时，可随时暂停', c.minutes + ', no countdown, pause any time')}</span><span class="spacer"></span>${go1 ? btn(T('重新开始一次', 'Start over'), 'take-case', 'quiet', `data-case="${id}"`) + btn(T('继续', 'Continue'), 'resume-attempt', 'primary', `data-id="${existing.id}"`) : btn(T('接手这件工作', 'Take this on'), 'take-case', 'primary', `data-case="${id}"`)}</footer>
    </div>
  </article>`;
}
function variantCard(id, existing) {
  const c = CASE(id); const open = existing && statusOf(existing) !== 'submitted';
  return `<article class="variant">
    <div class="variant-body">
      <p class="variant-change">${icon('bolt', 'i-sm')}${esc(c.change)}</p>
      <h3>${esc(c.title)}</h3>
      <figure class="variant-quote">${avatar('manager', 'xs')}<blockquote>${esc(c.quote)}</blockquote></figure>
      ${caseConditions(id)}
      <div class="variant-foot">${open ? btn(T('继续', 'Continue'), 'resume-attempt', 'small', `data-id="${existing.id}"`) : ''}${btn(open ? T('再开一次', 'New attempt') : T('开始', 'Start'), 'take-case', open ? 'small quiet' : 'small', `data-case="${id}"`)}</div>
    </div>
  </article>`;
}
function matchIntake(text) {
  const raw = String(text || '').trim();
  if (!raw) return { status: 'empty' };
  const find1 = re => { const m = raw.match(re); return m ? m[0] : null; };
  const topic = find1(/知识助手|知识库|问答|FAQ|政策查询|查政策|内部助手|knowledge (?:base|assistant)|Q&A|\bassistant\b|\bchatbot\b/i);
  const internal = find1(/员工|同事|内部|行政|人事|\bHR\b|\bstaff\b|\binternal\b|\bemployees?\b|\bcolleagues?\b/i);
  const external = find1(/外部客户|顾客|消费者|买家|\bcustomers?\b|\bshoppers?\b|\bclients?\b/i);
  const other = find1(/推荐|排序|广告|\brecommend\w*|\branking\b|\badverts?\b/i);
  const policy = find1(/差旅|报销|政策|\bpolic(?:y|ies)\b|\btravel\b|\bexpenses?\b/i);
  if (!topic && !policy) return { status: 'none', text: raw.slice(0, 2000) };
  const fits = []; const gaps = [];
  if (internal) fits.push(['internal', internal]);
  if (policy) fits.push(['policy', policy]);
  const pilot = find1(/试点|小范围|一部分人|先给|\bpilot\b|\btrial\b|\ba few\b/i); if (pilot) fits.push(['pilot', pilot]);
  const week = find1(/一周|下周|7 ?天|\bnext week\b|\bone week\b|\ba week\b/i); if (week) fits.push(['week', week]);
  if (external) gaps.push(['external', external]);
  if (other) gaps.push(['other', other]);
  const scale = find1(/\d{2,}\s*(?:人|名|位|people|staff|employees|users)(?![日天])/i); if (scale) gaps.push(['scale', scale]);
  if (!fits.length) fits.push(['decision', '']);
  return { status: external || other ? 'partial' : 'matched', template: 'pilot', text: raw.slice(0, 2000), fits, gaps };
}
const FIT = ([k, q]) => ({
  internal: T(`使用者是内部员工（你写了“${q}”）`, `Users are internal staff (you wrote “${q}”)`),
  policy: T(`要回答会变化的政策（你写了“${q}”）`, `It answers policy that changes (you wrote “${q}”)`),
  pilot: T(`先做小范围试点（你写了“${q}”）`, `It starts as a small pilot (you wrote “${q}”)`),
  week: T(`一周左右上线（你写了“${q}”）`, `Launch in about a week (you wrote “${q}”)`),
  decision: T('一个知识助手的上线决定', 'A launch decision for a knowledge assistant'),
  external: T(`面向外部客户（你写了“${q}”）：本情境只覆盖内部员工`, `External customers (you wrote “${q}”): this situation covers staff only`),
  other: T(`“${q}”类功能：本情境只覆盖知识问答`, `“${q}”: this situation covers knowledge Q&A only`),
  scale: T(`规模“${q}”：本情境沿用 30 人容量`, `Scale “${q}”: this situation keeps 30 seats`)
})[k] || '';
const intakeLines = (list, legacy) => (Array.isArray(list) && list.length ? list.map(FIT) : (legacy || []));
function intakeBlock() {
  const r = ui.intake.result;
  return `<details class="intake" ${ui.intake.open || r ? 'open' : ''} data-intake>
    <summary><span class="section-title">${T('用你自己的业务来练', 'Practise with your own business')}</span>${icon('down', 'i-sm chev')}</summary>
    <form data-form="intake" class="intake-form">
      <label class="sr-only" for="intake-text">${T('描述你想练的情境', 'Describe the situation you want to practise')}</label>
      <textarea id="intake-text" class="textarea" name="text" rows="3" maxlength="2000" placeholder="${esc(T('例如：我们 HR 每天收到员工重复的政策问题，想先给一小部分人试用知识助手。', 'For example: our HR team answers the same policy questions every day and wants a few staff to try a knowledge assistant first.'))}">${esc(ui.intake.text)}</textarea>
      <div class="row-actions"><button type="submit" class="btn">${T('看看能不能练', 'Check the match')}</button><span class="meta">${T('只匹配审核过的情境', 'Matches reviewed situations only')}</span></div>
    </form>
    ${r ? intakeResult(r) : ''}
  </details>`;
}
function intakeResult(r) {
  if (r.status === 'empty') return `<p class="intake-result muted">${T('先写一句你想练的业务。', 'Write a sentence about the business first.')}</p>`;
  if (r.status === 'none') return `<div class="intake-result" tabindex="-1"><p class="intake-head">${T('这个情境现在还练不了', 'This one cannot be practised yet')}</p><p class="muted">${T('目前审核过的只有“内部知识助手上线决定”。', 'The only reviewed situation is a launch decision for an internal knowledge assistant.')}</p></div>`;
  const cols = `<div class="intake-cols"><ul class="ticks">${intakeLines(r.fits).map(x => `<li>${icon('check', 'i-sm')}${esc(x)}</li>`).join('')}</ul>${r.gaps.length ? `<ul class="ticks muted">${intakeLines(r.gaps).map(x => `<li>${icon('minus', 'i-sm')}${esc(x)}</li>`).join('')}</ul>` : ''}</div>`;
  return `<div class="intake-result" tabindex="-1"><p class="intake-head">${r.status === 'partial' ? T('只能借用「知识助手试点」的决策结构', 'Only the decision structure of the pilot carries over') : T('最接近「知识助手试点」', 'Closest match: the knowledge assistant pilot')}</p>${cols}<div class="row-actions">${btn(r.status === 'partial' ? T('仍用这个情境开始', 'Start with it anyway') : T('用这个情境开始', 'Start with this situation'), 'start-intake', r.status === 'partial' ? '' : 'primary')}</div></div>`;
}
function practiceList(list) {
  return `<section class="block"><h2 class="section-title">${T('我的练习', 'My practice')}</h2><div class="list">${list.slice(0, 6).map(a => {
    const st = statusOf(a);
    const label = st === 'submitted' ? T('已交付', 'Submitted') : st === 'paused' ? T('已暂停', 'Paused') : T('进行中', 'In progress');
    return `<div class="list-row"><span class="resume-icon">${icon('note', 'i-sm')}</span><div class="grow"><p class="row-title">${esc(CASE(a.scenarioId).title)}</p><p class="row-sub">${label}${a.createdAt ? '，' + T('开始于 ', 'started ') + when(a.createdAt) : ''}</p></div>${st === 'submitted' ? btn(T('看评审', 'Review'), 'review-attempt', 'small quiet', `data-id="${a.id}"`) : ''}${btn(T('打开', 'Open'), 'resume-attempt', 'small', `data-id="${a.id}"`)}</div>`;
  }).join('')}</div></section>`;
}

/* ---------- 3. workspace: the board, a task's workbench, a document, the test bench ---------- */
// Two levels. The board shows the whole job: the brief and its conditions, the product
// under test, every task by priority, every document. A task opens its own workbench:
// its work, documents and tests on the left, the open item in the middle. The right
// rail keeps the team and the context: talk, feedback, my agent, activity.
function renderWorkspace() {
  const a = current();
  const arriving = ui.arriving; ui.arriving = false; ui.landing = arriving;
  ui.notesCache = Coach.notes(a, E);
  const html = `<div class="ws view-${ui.route} ${arriving ? 'arriving' : ''} ${ui.railOpen ? 'rail-open' : ''}" data-status="${statusOf(a)}">
    ${wsToolbar(a)}
    <main id="main" class="stage" tabindex="-1"><div id="ws-stage" class="stage-inner">${wsStage(a)}</div></main>
    <aside class="rail" id="ws-rail" aria-label="${esc(T('团队与上下文', 'Team and context'))}">${wsRail(a)}</aside>
    <button type="button" class="scrim" data-action="close-panels" aria-label="${esc(T('关闭面板', 'Close panel'))}" tabindex="-1"></button>
  </div>`;
  ui.landing = false;
  return html;
}
const routeTask = a => (ui.route === 'task' ? a.tasks.find(t => t.id === ui.routeId) || null : null);
function wsToolbar(a) {
  const st = statusOf(a); const n = snap(); const s = sessionOf(a);
  const t = routeTask(a); const m = ui.route === 'doc' ? E.getMaterials(a).find(x => x.id === ui.routeId) : null;
  const conn = !n.connected ? `<button type="button" class="conn bad" data-action="live-refresh" title="${esc(T('连接不上后端，点击重试', 'Cannot reach the server. Click to retry.'))}"><span class="conn-dot"></span>${T('离线', 'Offline')}</button>`
    : s?.pending && !s.pending.jobId && !n.busy ? `<button type="button" class="conn warn" data-action="live-retry" title="${esc(T('上一个操作没有得到确认，点击用原请求重试', 'The last action was not confirmed. Retry the same request.'))}">${icon('refresh', 'i-sm')}${T('待确认', 'Unconfirmed')}</button>` : '';
  const typing = typingRole(a); const noteRoles = new Set((ui.notesCache || []).map(x => x.role));
  const back = ui.route === 'work'
    ? `<button type="button" class="btn quiet back" data-action="to-entry" title="${esc(T('离开工作台，回到 AI 产品经理', 'Leave the workspace for AI Product Manager'))}">${icon('back')}<span class="hide-md">${T('离开', 'Leave')}</span></button>`
    : `<button type="button" class="btn quiet back up" data-action="to-board">${icon('back')}<span>${T('工作板', 'Board')}</span></button>`;
  const here = t ? `<span class="crumb-sep">${icon('chev', 'i-xs')}</span><span class="crumb-now">${esc(taskTitle(t))}</span>`
    : m ? `<span class="crumb-sep">${icon('chev', 'i-xs')}</span><span class="crumb-now">${esc(materialTitle(m))}</span>`
    : ui.route === 'bench' ? `<span class="crumb-sep">${icon('chev', 'i-xs')}</span><span class="crumb-now">${T('测试台', 'Test bench')}</span>` : '';
  return `<header class="topbar ws-toolbar" id="ws-toolbar">
    ${back}
    <nav class="crumbbar" aria-label="${esc(T('位置', 'Location'))}">
      <div class="menu-wrap title-wrap"><h1 class="ws-title"><button type="button" class="title-btn" data-action="menu" data-menu="brief" aria-expanded="${ui.menu === 'brief'}" aria-haspopup="dialog" title="${esc(T('委托与条件', 'Brief and conditions'))}"><span class="title-text" style="view-transition-name: case-title">${esc(CASE(a.scenarioId).title)}</span>${icon('down', 'i-sm')}</button></h1>${ui.menu === 'brief' ? briefPopover(a) : ''}</div>
      ${here}
    </nav>
    ${st !== 'active' ? `<span class="state-chip ${st}">${st === 'paused' ? T('已暂停', 'Paused') : T('已交付', 'Submitted')}</span>` : ''}
    ${conn}
    <div class="spacer"></div>
    <button type="button" class="team-btn" data-action="open-rail" aria-label="${esc(T('团队', 'Team'))}">${ROLES.map(r => avatar(r, 'sm', { typing: typing === r, dot: unread(a, r) > 0 || noteRoles.has(r) })).join('')}</button>
    ${langControl()}
    <div class="menu-wrap">${btn(icon('more'), 'menu', 'icon quiet', `data-menu="more" aria-haspopup="menu" aria-expanded="${ui.menu === 'more'}" aria-label="${esc(T('更多', 'More'))}"`)}${ui.menu === 'more' ? moreMenu(a) : ''}</div>
    ${st === 'submitted' ? btn(T('看评审', 'See review'), 'to-review', 'primary') : btn(icon('stamp', 'i-sm') + T('交付', 'Submit'), 'submit', hasDecision(a) ? 'primary' : '')}
  </header>`;
}
function moreMenu(a) {
  const st = statusOf(a);
  const item = (action, label, ic, attrs = '') => `<button type="button" role="menuitem" data-action="${action}" ${attrs}>${icon(ic, 'i-sm')}<span class="grow">${label}</span></button>`;
  return `<div class="menu right" role="menu">${st !== 'submitted' ? item('live-session', st === 'paused' ? T('恢复练习', 'Resume practice') : T('暂停练习', 'Pause practice'), st === 'paused' ? 'play' : 'pause') : ''}${item('live-timeline', T('后端过程记录', 'Server log'), 'history')}${item('export', T('导出本地笔记', 'Export local notes'), 'download')}${item('about', T('关于这个工作台', 'About this workspace'), 'info')}${item('to-entry', T('离开工作台', 'Leave the workspace'), 'back')}</div>`;
}
function briefPopover(a) {
  const c = CASE(a.scenarioId);
  return `<div class="popover brief-pop" role="dialog" aria-label="${esc(T('委托与条件', 'Brief and conditions'))}">
    ${letter('manager', c.quote, 'sm')}
    ${intakeNote(a)}
    ${conditions(a, 'compact')}
    <div class="pop-actions">${btn(icon('doc', 'i-sm') + T('看完整委托', 'Read the full brief'), 'open-doc', 'small', 'data-id="brief"')}${btn(icon('hand', 'i-sm') + T('申请资源', 'Request resources'), 'resources', 'small quiet')}</div>
  </div>`;
}
function intakeNote(a) {
  if (!a.intake) return '';
  const fits = intakeLines(a.intake.fits, a.intake.adopted); const gaps = intakeLines(a.intake.gaps, a.intake.notModeled);
  return `<div class="intake-note"><p class="meta">${T('按你描述的业务', 'From your description')}</p><ul class="ticks small">${fits.map(x => `<li>${icon('check', 'i-xs')}${esc(x)}</li>`).join('')}${gaps.map(x => `<li class="muted">${icon('minus', 'i-xs')}${esc(x)}</li>`).join('')}</ul></div>`;
}
// Conditions are numbers with names. An approved change shows the old value beside it.
function conditions(a, cls = '') {
  const base = worldOf(a.scenarioId); const w = a.world;
  const lit = k => (ui.changed && ui.changed.until > Date.now() && ui.changed.keys.includes(k) ? ' lit' : '');
  const item = (value, label, was, k = '') => `<div class="cond ${was ? 'changed' : ''}${lit(k)}"><span class="cond-val">${value}</span><span class="cond-label">${label}</span>${was ? `<span class="cond-was">${T('原', 'was')} ${was} · ${T('已批准', 'approved')}</span>` : ''}</div>`;
  return `<div class="conds ${cls}">
    ${item(T(w.capacity + ' 人', w.capacity + ' seats'), T('试点容量', 'Capacity'), w.capacity !== base.capacity ? T(base.capacity + ' 人', String(base.capacity)) : '', 'capacity')}
    ${item(T(w.devDays + ' 人日', w.devDays + ' person-days'), T('可用开发', 'Engineering'), w.devDays !== base.devDays ? T(base.devDays + ' 人日', String(base.devDays)) : '', 'devDays')}
    ${item(T('第 ' + w.deadline + ' 天', 'Day ' + w.deadline), T('期望上线', 'Launch target'), w.deadline !== base.deadline ? T('第 ' + base.deadline + ' 天', 'day ' + base.deadline) : '', 'deadline')}
    ${item(T(INDEX_DELAY_HOURS + ' 小时', INDEX_DELAY_HOURS + ' h'), T('索引最长滞后', 'Index lag, max'))}
  </div>`;
}
function wsStage(a) {
  const st = statusOf(a);
  const lock = st === 'paused' ? `<div class="stage-banner">${icon('pause', 'i-sm')}<span class="grow">${T('练习已暂停。资料可以看，操作要先恢复。', 'Paused. You can read; resume to act.')}</span>${btn(T('恢复', 'Resume'), 'live-session', 'small')}</div>`
    : st === 'submitted' ? `<div class="stage-banner">${icon('stamp', 'i-sm')}<span class="grow">${T('已固定交付，这次练习只读。', 'Submitted. This practice is read-only now.')}</span>${btn(T('看评审', 'See review'), 'to-review', 'small')}</div>` : '';
  const t = routeTask(a);
  if (t) return lock + taskView(a, t);
  if (ui.route === 'doc') return lock + `<div class="page-pad">${docBody(a, ui.routeId, false)}</div>`;
  if (ui.route === 'bench') return lock + `<div class="page-pad">${bench(a, null)}</div>`;
  return lock + boardView(a);
}

/* the board */
function boardView(a) {
  const v = a.world.policyVersion;
  const policyNew = v > 1 && !(a.acks || []).includes('policy-v' + v);
  return `<div class="board">
    <section class="brief-band" style="view-transition-name: case-surface">
      <div class="band-letter">${letter('manager', CASE(a.scenarioId).quote)}<div class="band-actions">${btn(icon('doc', 'i-sm') + T('看完整委托', 'Read the full brief'), 'open-doc', 'small quiet', 'data-id="brief"')}</div>${intakeNote(a)}</div>
      ${conditions(a)}
    </section>
    ${policyNew ? situationBanner(a) : ''}
    ${productBar(a)}
    <section class="work-sec" aria-labelledby="tasks-h">
      <header class="sec-head"><h2 id="tasks-h">${T('事项', 'Tasks')}</h2><span class="sec-hint">${T('拖动卡片调整优先级', 'Drag cards to reprioritise')}</span><span class="spacer"></span>
        <div class="menu-wrap">${btn(icon('bubble', 'i-sm') + T('问问怎么排', 'Ask how to prioritise'), 'menu', 'small quiet', `data-menu="rank" aria-haspopup="menu" aria-expanded="${ui.menu === 'rank'}"`)}${ui.menu === 'rank' ? rankMenu() : ''}</div>
        ${btn(icon('plus', 'i-sm') + T('新事项', 'New task'), 'new-task', 'small')}</header>
      ${ui.advice ? advicePanel(a) : ''}
      <p id="move-help" class="sr-only">${T('按住 Option 或 Alt：左右方向键换列（改优先级），上下方向键调整顺序。', 'Hold Option or Alt: left and right move between columns (priority), up and down change the order.')}</p>
      <div class="kanban">${['first', 'next', 'later'].map(p => column(a, p)).join('')}</div>
    </section>
    <section class="work-sec" aria-labelledby="docs-h">
      <header class="sec-head"><h2 id="docs-h">${T('资料', 'Documents')}</h2></header>
      ${docGrid(a)}
    </section>
  </div>`;
}
function situationBanner(a) {
  const v = a.world.policyVersion; const behind = a.world.indexVersion < v;
  return `<section class="world-event" role="status">
    <span class="we-icon">${icon('bolt')}</span>
    <div class="grow"><p class="we-kicker">${T('刚发生', 'Just happened')}</p><p class="we-title">${T(`差旅政策更新为 v${v}`, `The travel policy is now v${v}`)}</p>${behind ? `<p class="we-sub">${T(`知识助手的索引还是 v${a.world.indexVersion}，它会继续按旧版本回答，直到你刷新索引。`, `The assistant still indexes v${a.world.indexVersion} and will keep answering from it until you refresh the index.`)}</p>` : ''}</div>
    <div class="we-actions">${btn(T('看哪里变了', 'See what changed'), 'open-doc', 'small primary', 'data-id="policy" data-compare="1"')}${btn(T('记为事项', 'Add as a task'), 'situation-task', 'small')}${btn(T('知道了', 'Got it'), 'ack', 'small quiet', `data-key="policy-v${v}"`)}</div>
  </section>`;
}
function productBar(a) {
  const c = a.config; const configured = !!a.backend?.configured; const stale = a.world.indexVersion < a.world.policyVersion;
  return `<section class="product-bar ${stale ? 'is-stale' : ''}" aria-label="${esc(T('知识助手', 'Knowledge assistant'))}">
    ${assistantMark('md')}
    <div class="grow"><p class="pb-name">${T('知识助手', 'Knowledge assistant')}<span class="pb-role">${T('你要决定能否试点的产品', 'The product you are deciding on')}</span></p>
      <ul class="pb-state">${configured ? `<li>${T('配置 v', 'Config v')}${a.configVersion}</li><li>${T(c.participants + ' 人', c.participants + ' users')}</li><li>${c.domains.map(DOMAIN).join(' + ') || T('未开放知识', 'No knowledge')}</li><li>${UPDATE(c.update)}</li>` : `<li class="muted">${T('还没有试点设置', 'No pilot settings yet')}</li>`}<li class="${stale ? 'warn' : ''}">${stale ? icon('stale', 'i-xs') : ''}${T('政策 v' + a.world.policyVersion + ' / 索引 v' + a.world.indexVersion, 'Policy v' + a.world.policyVersion + ' / index v' + a.world.indexVersion)}${stale ? T('，索引落后', ', index behind') : ''}</li></ul></div>
    ${btn(icon('flask', 'i-sm') + T('测试台', 'Test bench') + (a.tests.length ? `<span class="btn-count">${a.tests.length}</span>` : ''), 'open-bench', 'small')}${btn(icon('gear', 'i-sm') + T('设置', 'Settings'), 'config', configured ? 'small quiet' : 'small primary')}${btn(icon('hand', 'i-sm') + T('申请', 'Requests'), 'resources', 'small quiet')}
  </section>`;
}
function rankMenu() {
  return `<div class="menu" role="menu"><p class="menu-cap">${T('想听谁的看法', 'Whose view?')}</p>${ROLES.map(r => `<button type="button" role="menuitem" data-action="show-advice" data-role="${r}">${avatar(r, 'xs')}<span class="grow">${PEOPLE[r].name}<small>${ROLE_TITLE(r)}</small></span></button>`).join('')}</div>`;
}
function advicePanel(a) {
  const adv = Coach.advice(a, ui.advice); const r = ui.advice;
  return `<div class="advice who-${r}">
    <div class="advice-head">${avatar(r, 'sm')}<b>${PEOPLE[r].name}</b><span class="muted">${ROLE_TITLE(r)}</span><span class="rule-tag" title="${esc(T('按场景规则生成，不是同事实时回复', 'Generated from scenario rules, not a live reply'))}">${T('规则示意', 'Rule-based')}</span><span class="spacer"></span>
      <div class="segmented" role="group" aria-label="${esc(T('谁的看法', 'Whose view'))}"><span class="thumb"></span>${ROLES.map(x => `<button type="button" aria-pressed="${x === r}" data-action="show-advice" data-role="${x}">${PEOPLE[x].name}</button>`).join('')}</div>${btn(icon('x'), 'close-advice', 'icon quiet small', `aria-label="${esc(T('关闭', 'Close'))}"`)}</div>
    <p class="advice-why">${esc(adv.why)}</p>
    <ol class="advice-list">${adv.items.map(i => { const t = a.tasks.find(x => x.id === i.taskId); return `<li>${priMark(i.priority)}<span class="adv-pri">${PRI(i.priority)}</span><span class="grow">${esc(taskTitle(t))}</span></li>`; }).join('')}</ol>
    <div class="row-actions">${adv.items.length ? btn(T('按此排列', 'Arrange like this'), 'apply-advice', 'small primary') : ''}${btn(T('直接问 ' + PEOPLE[r].name, 'Ask ' + PEOPLE[r].name + ' directly'), 'ask-rank', 'small quiet', `data-role="${r}"`)}</div>
  </div>`;
}
function column(a, p) {
  const list = a.tasks.filter(t => t.priority === p);
  return `<div class="col col-${p}" data-lane="${p}">
    <header class="col-head">${priMark(p)}<span class="col-name">${PRI(p)}</span><span class="col-count">${list.length}</span></header>
    <ol class="cards" role="list">${list.map(t => taskCard(a, t)).join('')}${!list.length ? `<li class="col-empty">${T('拖到这里', 'Drop here')}</li>` : ''}</ol>
  </div>`;
}
function taskCard(a, t) {
  const list = taskWorks(a, t.id); const tests = a.tests.filter(r => r.taskId === t.id);
  const stale = tests.some(r => r.policyVersion < a.world.policyVersion);
  const toCheck = list.filter(w => w.source !== 'user' && !w.adopted).length;
  const notes = (ui.notesCache || []).filter(n => n.taskId === t.id);
  const vt = ui.landing && t.seed ? 'seed-' + SEED_KEYS.indexOf(t.seed) : 't-' + vtName(t.id);
  const latest = list.at(-1);
  return `<li class="card ${t.status}" draggable="true" data-task-id="${t.id}" style="view-transition-name: ${vt}; --i: ${a.tasks.indexOf(t)}">
    <button type="button" class="card-open" data-action="open-task" data-id="${t.id}" aria-describedby="move-help">
      <span class="card-head" title="${esc(STATUS(t.status))}">${statusMark(t.status)}<span class="card-title">${esc(taskTitle(t))}</span><span class="sr-only">${esc(STATUS(t.status))}</span></span>
      ${latest ? `<span class="card-latest">${icon('note', 'i-xs')}<span>${esc(shown(latest).title)}</span><em>${esc(purposeLabel(shown(latest).purpose))}</em></span>` : `<span class="card-latest empty">${T('还没有作品', 'No work yet')}</span>`}
      <span class="card-meta"><span title="${esc(T('作品', 'Work'))}">${icon('note', 'i-xs')}${list.length}</span><span title="${esc(T('测试', 'Tests'))}">${icon('flask', 'i-xs')}${tests.length}</span>${notes.length ? `<span class="card-notes" title="${esc(notes.map(n => PEOPLE[n.role].name).join(T('、', ', ')) + T(' 有提醒', ' left a reminder'))}">${[...new Set(notes.map(n => n.role))].map(r => avatar(r, 'xs')).join('')}</span>` : ''}</span>
      ${stale || toCheck ? `<span class="card-flags">${stale ? `<span class="flag-chip warn">${icon('stale', 'i-xs')}${T('测试早于政策更新', 'Tests predate the policy update')}</span>` : ''}${toCheck ? `<span class="flag-chip agent">${agentMark('xs')}${T(toCheck + ' 份回传待检查', toCheck + ' agent return(s) to check')}</span>` : ''}</span>` : ''}
    </button>
    ${workFolderMarkup({taskId: t.id, title: taskTitle(t), works: list.map(shown)})}
    <button type="button" class="btn icon quiet small card-more" data-action="edit-task" data-id="${t.id}" aria-label="${esc(T('编辑「' + taskTitle(t) + '」', 'Edit “' + taskTitle(t) + '”'))}">${icon('more')}</button>
  </li>`;
}
const WHO = { supervisor: 'manager', business_lead: 'business', tech_lead: 'technical' };
const whoHas = m => (m.visible_to || []).map(r => WHO[r]).filter(Boolean);
function docGrid(a) {
  const list = E.getMaterials(a);
  if (!list.length) return `<p class="empty-line">${snap().connected ? T('正在取资料…', 'Loading documents…') : T('连上后端后显示资料', 'Documents appear once connected')}</p>`;
  const read = readSet(a);
  return `<div class="doc-grid">${list.map(m => {
    const fresh = m.version > 1 && !(a.acks || []).includes('read-' + m.id + '-v' + m.version);
    const who = whoHas(m);
    return `<button type="button" class="doc-card ${read.has(m.id) ? 'read' : 'unread'}" data-action="open-doc" data-id="${esc(m.id)}">
      <span class="dc-top">${icon('doc', 'i-sm')}<span class="dc-ver">v${m.version}</span>${fresh ? `<span class="tag new">${T('有新版本', 'New version')}</span>` : read.has(m.id) ? '' : `<span class="unread-dot" title="${esc(T('未读', 'Unread'))}"><span class="sr-only">${T('未读', 'Unread')}</span></span>`}</span>
      <span class="dc-title">${esc(materialTitle(m))}</span>
      ${who.length ? `<span class="dc-who" title="${esc(who.map(r => PEOPLE[r].name).join(T('、', ', ')) + T(' 也有这份资料', ' have this too'))}"><span class="dc-ask">${T('可以问', 'Ask')}</span>${who.map(r => avatar(r, 'xs')).join('')}</span>` : ''}
    </button>`;
  }).join('')}</div>`;
}

/* a task's workbench */
function relatedDocs(a, t) {
  const ids = new Set(t.docs || []);
  taskWorks(a, t.id).forEach(w => (w.evidence || []).forEach(ev => { if (ev.type === 'material') ids.add(ev.id); }));
  return E.getMaterials(a).filter(m => ids.has(m.id));
}
function defaultObj(a, t) {
  const list = taskWorks(a, t.id);
  return list.length ? { task: t.id, type: 'work', id: list.at(-1).id } : { task: t.id, type: 'start' };
}
function taskView(a, t) {
  if (!ui.obj || ui.obj.task !== t.id) ui.obj = defaultObj(a, t);
  if (ui.obj.type === 'work' && !a.artifacts.some(x => x.id === ui.obj.id && x.taskId === t.id && !x.removedAt)) ui.obj = defaultObj(a, t);
  return `<div class="task-ws">
    <header class="task-head" style="view-transition-name: t-${vtName(t.id)}">
      <div class="th-row">${priPick(t.id, t.priority, taskTitle(t))}<h2 class="th-title">${esc(taskTitle(t))}</h2><span class="spacer"></span>
        <div class="segmented status-seg" role="group" aria-label="${esc(T('进展', 'Progress'))}"><span class="thumb"></span>${['open', 'working', 'done'].map(k => `<button type="button" aria-pressed="${t.status === k}" data-action="set-status" data-status="${k}" data-id="${t.id}">${statusMark(k)}<span>${STATUS(k)}</span></button>`).join('')}</div>${btn(icon('more'), 'edit-task', 'icon quiet small', `data-id="${t.id}" aria-label="${esc(T('编辑事项', 'Edit task'))}"`)}</div>
      ${taskNote(t) ? `<p class="th-note">${esc(taskNote(t))}</p>` : ''}
    </header>
    <div class="task-body">
      <nav class="outline" aria-label="${esc(T('这件事的内容', 'What this task holds'))}">${outline(a, t)}</nav>
      <section class="object" id="ws-object">${objectView(a, t)}</section>
    </div>
  </div>`;
}
function outline(a, t) {
  const removed = a.artifacts.filter(x => x.taskId === t.id && x.removedAt);
  const list = taskWorks(a, t.id); const docs = relatedDocs(a, t); const tests = a.tests.filter(r => r.taskId === t.id).slice().reverse();
  const on = (type, id) => ui.obj && ui.obj.type === type && (ui.obj.id || '') === (id || '');
  const head = (label, action, attrs, aria) => `<p class="ol-head"><span>${label}</span><button type="button" class="ol-add" data-action="${action}" ${attrs} aria-label="${esc(aria)}" title="${esc(aria)}">${icon('plus', 'i-xs')}</button></p>`;
  return `<div class="ol-sec">${head(T('作品', 'Work'), 'new-artifact', '', T('新作品', 'New piece of work'))}
      ${list.map(w => { const v = shown(w); return `<button type="button" class="ol-row ${on('work', w.id) ? 'on' : ''}" data-action="obj" data-type="work" data-id="${w.id}" ${on('work', w.id) ? 'aria-current="true"' : ''}>${w.source !== 'user' ? agentMark('xs') : icon('note', 'i-sm')}<span class="grow"><span class="ol-title">${esc(v.title)}</span><span class="ol-meta">${esc(purposeLabel(v.purpose))} · v${w.revision}${w.source !== 'user' && !w.adopted ? ' · ' + T('待检查', 'to check') : ''}</span></span></button>`; }).join('') || `<button type="button" class="ol-row ghost ${on('start') ? 'on' : ''}" data-action="obj" data-type="start">${icon('plus', 'i-sm')}<span class="grow">${T('开始写', 'Start writing')}</span></button>`}
      ${removed.length ? `<button type="button" class="work-recycle-link" data-action="removed-works">${icon('history','i-xs')}${T('已移除作品（' + removed.length + '）', 'Removed work (' + removed.length + ')')}</button>` : ''}
    </div>
    <div class="ol-sec">${head(T('资料', 'Documents'), 'pick-doc', '', T('打开一份资料', 'Open a document'))}
      ${docs.map(m => `<button type="button" class="ol-row ${on('doc', m.id) ? 'on' : ''}" data-action="obj" data-type="doc" data-id="${esc(m.id)}">${icon('doc', 'i-sm')}<span class="grow"><span class="ol-title">${esc(materialTitle(m))}</span><span class="ol-meta">v${m.version}</span></span></button>`).join('') || `<p class="ol-empty">${T('打开或引用过的资料会列在这里', 'Documents you open or cite here appear in this list')}</p>`}
    </div>
    <div class="ol-sec">${head(T('测试', 'Tests'), 'obj', 'data-type="bench"', T('在测试台问一个问题', 'Ask the assistant something'))}
      ${tests.map(r => `<button type="button" class="ol-row ${on('bench') && ui.lastRun === r.id ? 'on' : ''}" data-action="open-run" data-id="${esc(r.id)}">${icon('flask', 'i-sm')}<span class="grow"><span class="ol-title"${zhAttr(r.question)}>${esc(r.question)}</span><span class="ol-meta ${r.policyVersion < a.world.policyVersion ? 'warn' : ''}">${T('政策 v', 'policy v')}${r.policyVersion}${r.stale ? ' · ' + T('引用过期', 'stale cite') : ''}</span></span></button>`).join('') || `<p class="ol-empty">${T('在测试台问的问题会记在这件事下', 'Questions you ask here are filed under this task')}</p>`}
    </div>`;
}
function objectView(a, t) {
  const o = ui.obj;
  if (o.type === 'doc') return docBody(a, o.id, true);
  if (o.type === 'bench') return bench(a, t);
  if (o.type === 'work') { const x = a.artifacts.find(y => y.id === o.id && !y.removedAt); if (x) { ui.artifactId = x.id; return workView(a, t, x); } }
  return startView(a, t);
}
// No tiles to click through: the page is already a sheet you can write on.
function startView(a, t) {
  const docsFor = { needs: ['business', 'brief'], policy: ['policy', 'technical'], decision: ['brief', 'approval_process', 'technical'] }[t.seed] || ['brief'];
  const docs = E.getMaterials(a).filter(m => docsFor.includes(m.id));
  const who = t.seed === 'policy' ? 'technical' : t.seed === 'decision' ? 'manager' : 'business';
  return `<div class="obj-pad">
    <article class="paper editor intent-explore">
      <label class="sr-only" for="new-title">${T('标题', 'Title')}</label>
      <input id="new-title" class="editor-title" data-new="title" maxlength="160" placeholder="${esc(T('给这份作品起个名字', 'Name this piece of work'))}">
      <div class="editor-meta"><label class="purpose"><select data-new="purpose" aria-label="${esc(T('用途', 'Purpose'))}">${E.PURPOSES.map(p => `<option value="${p}" ${p === '探索笔记' ? 'selected' : ''}>${esc(purposeLabel(p))}</option>`).join('')}</select>${icon('down', 'i-xs')}</label><span>${T('开始输入就会保存在这件事下', 'Saved under this task as soon as you type')}</span></div>
      <label class="sr-only" for="new-body">${T('正文', 'Body')}</label>
      <textarea id="new-body" class="editor-body" data-new="body" spellcheck="false" placeholder="${esc(T('你现在想弄清什么？\n\n写判断、要问的问题，或直接起草方案。## 写小标题，- 写列表。', 'What are you trying to figure out?\n\nWrite a judgement, the questions you need to ask, or a draft plan. ## for headings, - for lists.'))}"></textarea>
    </article>
    <div class="side-hints">
      <p class="mini-title">${T('手边可以用', 'At hand')}</p>
      ${docs.map(m => `<button type="button" class="hint-row" data-action="obj" data-type="doc" data-id="${esc(m.id)}">${icon('doc', 'i-sm')}<span class="grow">${esc(materialTitle(m))}</span><span class="ver">v${m.version}</span></button>`).join('')}
      <button type="button" class="hint-row" data-action="obj" data-type="bench">${assistantMark('xs')}<span class="grow">${T('在测试台问知识助手', 'Ask the knowledge assistant')}</span></button>
      <button type="button" class="hint-row" data-action="chat" data-role="${who}">${avatar(who, 'xs')}<span class="grow">${T('问 ' + PEOPLE[who].name, 'Ask ' + PEOPLE[who].name)}</span></button>
      <button type="button" class="hint-row" data-action="agent">${agentMark('xs')}<span class="grow">${T('交给我的 Agent', 'Hand to my agent')}</span></button>
    </div>
  </div>`;
}
function canEditWork(a, x) {
  return !!x && !x.removedAt && statusOf(a) === 'active' && !storageIssue && !snap().storageError;
}
function workControls(a, x, editable, structured = false) {
  const mutable = canEditWork(a, x);
  const pending = sessionOf(a)?.pending?.localRun?.workId === x.id || sessionOf(a)?.pending?.localRun?.investigationId === x.id;
  const control = (glyph, label, action, tip, attrs = '') => {
    const tipId = 'tip-' + action + '-' + x.id;
    return `<span class="icon-control"><button type="button" class="btn icon quiet work-icon" data-action="${action}" data-id="${x.id}" aria-label="${esc(label)}" aria-describedby="${tipId}" ${attrs}>${icon(glyph)}</button><span class="action-tooltip" id="${tipId}" role="tooltip">${esc(tip)}</span></span>`;
  };
  return `<div class="work-controls work-controls-icons" role="group" aria-label="${esc(T('作品操作','Work actions'))}">
    ${!structured ? control(editable?'eye':'edit',editable?T('预览作品','Preview work'):T('编辑作品','Edit work'),editable?'work-preview':'work-edit',editable?T('预览','Preview'):T('编辑','Edit'),`${!editable&&!mutable?'disabled':''} data-work-mode`) : ''}
    ${control('save',T('保存修改','Save changes'),'save-work',T('保存','Save'),mutable&&editable?'':'disabled')}
    <span class="work-control-divider" aria-hidden="true"></span>
    ${control('trash',T('删除作品','Remove work'),'remove-work',pending?T('先恢复未确认的运行','Resolve the pending run first'):T('删除','Remove'),mutable&&!pending?'':'disabled')}
  </div>`;
}
function requireWorkMutation(a, x) {
  if (!canEditWork(a, x)) throw new Error(T('这份作品当前只读，或本地存储不可用。', 'This work is read-only or local storage is unavailable.'));
}
function localWorkChange(a, change) {
  const backup = structuredClone(a);
  change();
  if (!persist()) {
    for (const key of Object.keys(a)) delete a[key]; Object.assign(a, backup);
    throw new Error(T('未能保存，作品保留原状。', 'Could not save. The work was kept unchanged.'));
  }
}
function removedWorksSheet(scopeTaskId = task()?.id || null) {
  const a = current(); if (!a) return;
  const removed = a.artifacts.filter(w=>w.removedAt && (!scopeTaskId || w.taskId === scopeTaskId));
  openSheet(T('已移除作品','Removed work'), `<p class="meta">${T('这里只保留工作台里的副本，电脑上的原文件没有改变。', 'These are workspace copies. Original files on your computer are unchanged.')}</p><div class="removed-work-list">${removed.map(w=>`<div class="removed-work-row"><div class="grow"><h3>${esc(shown(w).title)}</h3><p class="meta">${esc(purposeLabel(w.purpose))} · v${w.revision} · ${esc(when(w.removedAt))}</p></div>${btn(T('恢复','Restore'),'restore-work','small',`data-id="${w.id}" ${statusOf(a)==='active'&&!storageIssue&&!snap().storageError?'':'disabled'}`)}</div>`).join('') || `<p class="empty-line">${T('没有已移除的作品。','No removed work.')}</p>`}</div>`, btn(T('关闭','Close'),'close','quiet'), 'narrow');
}
function restoreWork(a, id) {
  const x = a.artifacts.find(w=>w.id===id);
  if (!x || statusOf(a) !== 'active' || storageIssue || snap().storageError) throw new Error(T('当前无法恢复作品。','Work cannot be restored right now.'));
  localWorkChange(a, ()=>E.restoreArtifact(a,id));
  closeSheet(true); openTask(x.taskId, {type:'work', id});
  notify(T('已恢复《' + shown(x).title + '》', 'Restored “' + shown(x).title + '”'));
}
function workView(a, t, x) {
  if (x.kind === 'test_set') return structuredWorkView(a, t, x);
  if (x.kind === 'investigation') return structuredInvestigationView(a, t, x);
  const list = taskWorks(a, t.id);
  const view = shown(x); const intent = E.intentOf(view.purpose); const prog = E.agentProgress(a, x);
  const editable = canEditWork(a, x) && ui.previewWorkId !== x.id;
  const notes = (ui.notesCache || []).filter(n => n.targetId === x.id || (!n.targetId && n.taskId === t.id));
  return `<div class="obj-pad ${notes.length ? 'with-margin' : ''}">
    <div class="work-grid">
      <article class="paper editor intent-${intent}">
        ${prog ? agentStrip(a, x, prog) : ''}
        ${workControls(a, x, editable)}
        <label class="sr-only" for="editor-title">${T('标题', 'Title')}</label>
        <input id="editor-title" class="editor-title" data-edit="title" maxlength="160" value="${esc(view.title)}" ${editable ? '' : 'readonly'}>
        <div class="editor-meta">
          <label class="purpose" title="${esc(INTENT_HINT(intent))}"><span class="sr-only">${T('用途', 'Purpose')}</span>${purposeGlyph(intent)}<select data-edit="purpose" ${editable ? '' : 'disabled'}>${E.PURPOSES.map(p => `<option value="${p}" ${p === view.purpose ? 'selected' : ''}>${esc(purposeLabel(p))}</option>`).join('')}</select>${icon('down', 'i-xs')}</label>
          <span data-revision>v${x.revision}</span>
          <span>${x.source === 'user' ? T('你写的', 'By you') : (x.requestId ? T('来自你的 Agent', 'From your agent') : T('导入的作品', 'Imported work'))}</span>
          <span class="save" data-save title="${esc(T('作品保存在本机；交付时可合并进交付稿', 'Work stays on this device; fold it into your deliverable when you submit'))}"></span>
        </div>
        ${editable ? `<label class="sr-only" for="editor-body">${T('正文', 'Body')}</label><textarea id="editor-body" class="editor-body" data-edit="body" maxlength="50000" spellcheck="false" placeholder="${esc(T('写判断、问题，或直接起草方案。## 写小标题，- 写列表。', 'Write a judgement, questions or a draft plan. ## for headings, - for lists.'))}">${esc(view.body)}</textarea>` : `<div class="prose">${md(view.body)}</div>`}
        ${x.evidence.length ? `<div class="evidence-row"><span class="meta">${T('依据', 'Evidence')}</span>${x.evidence.map(ev => `<button type="button" class="chip" data-action="view-evidence" data-id="${esc(ev.id)}" data-version="${esc(ev.version ?? '')}">${icon(ev.type === 'test' ? 'flask' : 'doc', 'i-xs')}<span>${esc(evTitle(ev))}</span>${ev.version ? `<span class="ver">v${ev.version}</span>` : ''}</button>`).join('')}</div>` : ''}
      </article>
      ${notes.length ? `<aside class="margin" aria-label="${esc(T('同事的提醒', 'Reminders from colleagues'))}">${notes.map(marginNote).join('')}</aside>` : ''}
    </div>
    <div class="action-bar">
      ${btn(icon('quote', 'i-sm') + T('引用依据', 'Cite evidence'), 'cite-pick', 'small quiet')}
      ${btn(icon('flask', 'i-sm') + T('测一测', 'Test it'), 'obj', 'small quiet', 'data-type="bench"')}
      ${btn(icon('bubble', 'i-sm') + T('问同事', 'Ask a colleague'), 'discuss-artifact', 'small quiet')}
      ${btn(agentMark('xs') + T('交给我的 Agent', 'Hand to my agent'), 'agent', 'small quiet')}
      <span class="spacer"></span>
      ${btn(icon('eye', 'i-sm') + T('请求评审', 'Request a review'), 'request-review', 'small')}
    </div>
    ${list.length > 1 ? '' : ''}
  </div>`;
}
function structuredWorkView(a, t, x) {
  const view = shown(x); const prog = E.agentProgress(a, x);
  const editable = (x.adopted || ui.editPending === x.id) && statusOf(a) === 'active' && !storageIssue;
  const evidence = x.evidence.length ? `<div class="evidence-row test-set-evidence"><span class="meta">${T('这份计划的依据', 'Evidence for this plan')}</span>${x.evidence.map(ev => `<button type="button" class="chip" data-action="view-evidence" data-id="${esc(ev.id)}" data-version="${esc(ev.version ?? '')}">${icon(ev.type === 'test' ? 'flask' : 'doc', 'i-xs')}<span>${esc(evTitle(ev))}</span></button>`).join('')}</div>` : '';
  return testSetView({ work: view, attempt: a, session: sessionOf(a), busy: ui.busy || snap().busy, canRun: canWrite(a) && !storageIssue && !!a.backend.configured, editable, opened: ui.testOpen[x.id], selectedRuns: ui.testHistory, modes: ui.testModes, errors: ui.testErrors, md, strip: (prog ? agentStrip(a, x, prog) : '') + workControls(a, x, editable, true), evidence });
}
function structuredInvestigationView(a, t, x) {
  const mutable=canEditWork(a,x) && (x.adopted || ui.editPending === x.id);
  const prog=E.agentProgress(a,x);
  return investigationView({work:shown(x),attempt:a,session:sessionOf(a),mutable,readOnly:!canEditWork(a,x),canRun:canWrite(a)&&!storageIssue&&!!a.backend.configured,busy:ui.busy||snap().busy,cache:ui.investigationSources,errors:ui.investigationErrors,controls:workControls(a,x,mutable,true),strip:prog?agentStrip(a,x,prog):'',md,diffHtml:investigationDiffHtml,viewState:investigationViewState(a,x)});
}
async function loadInvestigationSources(a, work, onlyBlockId) {
  for(const block of work.blocks.filter(b=>b.type==='source_check'&&(!onlyBlockId||b.id===onlyBlockId))) {
    const key=investigationSourceKey(a.id,block);
    if(ui.investigationSources[key]) continue;
    ui.investigationSources[key]={loading:true};
    Promise.allSettled([L.citationSource(a,block.testId,block.material.id),L.materialVersion(a,block.material.id,block.material.version)]).then(results=>{
      const citation=results[0].status==='fulfilled'?results[0].value:null;
      const selected=results[1].status==='fulfilled'?results[1].value:null;
      const failed=results.find(r=>r.status==='rejected');
      ui.investigationSources[key]={loading:false,citation,selected,error:failed?T('暂未取得全部证据，可以重新读取。','Some evidence is unavailable. You can try loading it again.'):''};
      if(current()?.id===a.id&&ui.obj?.type==='work'&&ui.obj.id===work.id) refreshWS(['stage']);
    });
  }
}
function openInvestigation(runId) {
  commit(); const a=current(), run=a?.tests.find(r=>r.id===runId);
  if(!run) throw new Error(T('这条实际测试记录暂不可用。','That actual test is unavailable.'));
  if(statusOf(a)!=='active'||storageIssue) throw new Error(T('当前只读，不能新建调查。','This practice is read-only; a new investigation cannot be created.'));
  const ref=run.citations.find(c=>c.id==='policy') || run.citations[0];
  const material=ref && E.getMaterials(a).find(m=>m.id===ref.id);
  const seed=[run.id,material?.version||0,a.configVersion].join('|');
  let work=a.artifacts.find(w=>!w.removedAt&&w.kind==='investigation'&&w.ruleOrigin==='feedback'&&w.investigationSeed===seed);
  if(!work) {
    const blocks=[{type:'note',title:T('先核对实际依据','Start with the actual evidence'),text:T('先看这次回答实际引用的版本，再对照当前资料。是否调整设置或重测，由你决定。','Check the version this answer actually cited, then compare it with the current source. You decide whether to change settings or rerun.')}];
    if(material) blocks.push({type:'source_check',testId:run.id,material:{id:material.id,version:material.version}});
    const other=a.tests.filter(r=>r.question===run.question&&r.id!==run.id).at(-1);
    if(other || !material) blocks.push({type:'test_compare',testIds:other?[run.id,other.id]:[run.id]});
    blocks.push({type:'retest',testId:run.id});
    localWorkChange(a,()=>{work=E.createArtifact(a,{kind:'investigation',taskId:run.taskId||task()?.id||a.tasks[0].id,title:T('核对回答与资料','Check the answer against its sources'),question:T('这次回答用了哪版资料？当前条件下会怎样回答？','Which source version did this answer use, and what happens under the current settings?'),blocks,source:'user',adopted:true,ruleOrigin:'feedback'});work.investigationSeed=seed;});
  }
  openTask(work.taskId,{type:'work',id:work.id});
  document.getElementById('main')?.scrollTo(0,0);
}
async function runInvestigationBlock(blockId) {
  if(ui.busy) return; commit(); const a=current(), work=artifact(), block=work?.blocks?.find(b=>b.id===blockId), baseline=block&&a.tests.find(r=>r.id===block.testId);
  if(!a||!work||!baseline||block.type!=='retest') return;
  if(work.draft||storageIssue||!persist()) throw new Error(T('先保存这份调查，再运行。','Save this investigation before running it.'));
  ui.busy=true; delete ui.investigationErrors[blockId]; refreshWS(['stage']);
  try { await L.test(a,{question:baseline.question,expectation:baseline.expectation||'',taskId:work.taskId,investigationId:work.id,investigationRevision:work.revision,blockId:block.id,blockRevision:block.revision,baselineRunId:baseline.id}); if(!persist()) throw new Error(T('结果已返回，本地视图尚未保存。','The result returned, but the local view has not been saved.')); announce(T('重测结果已返回，原始记录仍保留。','The rerun is back. The original record is kept.')); }
  catch(err) {ui.investigationErrors[blockId]=errText(err);}
  finally {ui.busy=false;refreshWS(['stage','rail']);}
}

// Save a field without replacing the node receiving the next pointer/Tab action.
function updateTestChrome() {
  const a = current(), x = artifact(); if (!a || !x || x.kind !== 'test_set') return;
  const session = sessionOf(a); let completed = 0;
  x.cases.forEach((c, i) => {
    const status = caseState(x, c, a, session?.pending, ui.busy || snap().busy);
    if (status.current) completed++;
    const row = document.querySelector(`[data-case-row="${CSS.escape(c.id)}"]`); if (!row) return;
    const question = row.querySelector('.test-case-question'), intent = row.querySelector('.test-case-intent'), badge = row.querySelector('.test-state');
    if (question) question.textContent = c.question || T('写一个测试问题','Write a test question');
    if (intent) intent.textContent = c.intent || T('这个问题想验证什么？','What should this question verify?');
    if (badge) { badge.textContent = status.label; badge.classList.toggle('attention', !!status.tone); }
    const version = row.querySelector('.test-case-foot > span'); if (version) version.textContent = 'v' + c.revision + ' · ' + T('每次重测另存结果','Every rerun keeps a new result');
    const runButton = row.querySelector('[data-action="test-run"]'); if (runButton) runButton.disabled = !x.adopted || !canWrite(a) || !!storageIssue || !a.backend.configured || !c.question.trim() || !!status.waiting;
    const run = status.runs.find(r=>r.id===ui.testHistory[c.id]) || status.runs[0];
    const result = row.querySelector('.test-result');
    if (result && run && !result.contains(document.activeElement)) result.outerHTML = testRunView({run,runs:status.runs,item:c,work:x,session,md});
    document.querySelectorAll('.test-progress > span')[i]?.classList.toggle('recorded', !!status.current);
  });
  const count = document.querySelector('.test-count-results'); if (count) count.textContent = T(completed + ' / ' + x.cases.length + ' 问题有结果', completed + ' / ' + x.cases.length + ' questions have results');
  const label = document.querySelector(`.ol-row[data-id="${CSS.escape(x.id)}"] .ol-meta`); if (label) label.textContent = purposeLabel(x.purpose) + ' · v' + x.revision;
  updateSave();
}
function animateTestReveal(id) {
  if (reduceMotion.matches || ui.kbd) return;
  document.getElementById('case-panel-' + id)?.animate([{ opacity: 0, transform: 'translateY(-4px)' }, { opacity: 1, transform: 'none' }], { duration: 180, easing: 'cubic-bezier(.32,.72,0,1)' });
}
async function runTestCase(id) {
  if (ui.busy) return;
  commit(); const a = current(), x = artifact();
  if (!a || !x || x.kind !== 'test_set') return;
  if (x.draft || storageIssue || !persist()) throw new Error(T('先保存这份计划，再运行测试。', 'Save this plan before running a test.'));
  const c = x.cases.find(c => c.id === id); if (!c) return;
  ui.testOpen[x.id] = id; delete ui.testErrors[id]; ui.busy = true; refreshWS(['stage']);
  try {
    const r = await L.test(a, { question: c.question, expectation: c.expectation || '', intent: c.intent, refs: c.refs || [], taskId: x.taskId, workId: x.id, workRevision: x.revision, caseId: c.id, caseRevision: c.revision });
    ui.lastRun = r.id; ui.testHistory[id] = r.id; ui.testModes[id] = 'result'; startWorking(a, task());
    if (!persist()) throw new Error(T('测试已有结果，本地显示未保存。保留当前页面后重试保存。', 'The test returned a result, but the local view was not saved. Keep this page open and retry saving.'));
    announce(T('这条问题已有回答，请检查结果。', 'This question has an answer. Review the result.'));
  } catch (err) { ui.testErrors[id] = errText(err); }
  finally { ui.busy = false; refreshWS(['stage','rail']); animateTestReveal(id); }
}

const KIND = k => ({ remind: T('提醒', 'Reminder'), object: T('异议', 'Objection'), correct: T('纠正', 'Correction'), help: T('帮忙', 'Offer') })[k] || '';
function marginNote(n) {
  return `<div class="note ${n.kind} who-${n.role}" data-note="${esc(n.key)}">
    <p class="note-head">${avatar(n.role, 'xs')}<b>${PEOPLE[n.role].name}</b><span class="note-kind">${KIND(n.kind)}</span><span class="rule-tag" title="${esc(T('按场景规则生成，不是同事实时回复', 'Generated from scenario rules, not a live reply'))}">${T('规则', 'Rule')}</span></p>
    <p class="note-text">${esc(n.text)}</p>
    <div class="note-actions"><button type="button" class="link" data-action="reply-note" data-key="${esc(n.key)}">${T('回应', 'Reply')}</button><button type="button" class="link quiet" data-action="ack" data-key="note:${esc(n.key)}">${T('先放下', 'Set aside')}</button></div>
  </div>`;
}
const evTitle = ev => (ev.type === 'test' ? String(ev.title || '').replace(/^测试：/, '') : materialTitle({ id: ev.id, title: ev.title }));
function agentStrip(a, x, prog) {
  if (!['test_set','investigation'].includes(x.kind) && !x.requestId) return `<div class="import-work-status">${icon('doc','i-sm')}<div class="grow"><b>${x.adopted ? T('已采用','Adopted') : T('待检查','To check')}</b><span>${T('这是导入副本，修改不会影响原文件。','This is an imported copy. Edits leave the original file unchanged.')}</span></div>${!x.adopted && canEditWork(a,x) ? btn(T('采用为当前作品','Adopt this work'),'adopt','small primary',`data-id="${x.id}"`) : ''}</div>`;
  const steps = [['exported', T('已交出', 'Handed over')], ['returned', T('已带回', 'Returned')], ['adopted', T('已采用', 'Adopted')], ['linked', prog.linkedRuns ? T('关联测试 ' + prog.linkedRuns + ' 次', prog.linkedRuns + ' linked test' + (prog.linkedRuns > 1 ? 's' : '')) : T('未关联测试', 'No linked test')]];
  return `<div class="agent-strip">${agentMark('xs')}<ol>${steps.map(([k, l]) => `<li class="${prog[k] ? 'done' : ''}">${l}</li>`).join('')}</ol>${!x.adopted && canEditWork(a,x) ? `<span class="spacer"></span>${ui.editPending === x.id ? '' : btn(T('编辑', 'Edit'), 'edit-pending', 'small quiet', `data-id="${x.id}"`)}${btn(T('采用', 'Adopt'), 'adopt', 'small primary', `data-id="${x.id}"`)}` : ''}</div>${(x.staleInputs || []).length ? `<p class="warn-line">${icon('stale', 'i-sm')}${T('它基于你较早的版本，采用前先对照。', 'It was based on an earlier version of your work. Compare before adopting.')}</p>` : ''}`;
}
function docBody(a, id, inTask) {
  const list = E.getMaterials(a);
  if (!list.length) return `<div class="empty">${T('还没有取得资料。', 'No documents yet.')}${btn(T('刷新', 'Refresh'), 'live-refresh', 'small')}</div>`;
  const m = list.find(x => x.id === id) || list[0];
  const prev = ui.previous[m.id];
  const compare = ui.compare && prev && prev.version < m.version;
  const zhOnly = locale() === 'en' && isChinese(m.content);
  const who = whoHas(m);
  return `<div class="${inTask ? 'obj-pad' : ''}">
    <article class="paper document" data-document-id="${esc(m.id)}">
      <header class="doc-head"><span class="doc-icon">${icon('doc')}</span><div class="grow"><h2 class="doc-title" id="document-title-${esc(m.id)}" tabindex="-1">${esc(materialTitle(m))}</h2><p class="doc-meta"><span class="stamp">v${m.version}</span>${m.id === 'policy' ? `<span class="${a.world.indexVersion < m.version ? 'warn' : ''}">${T('知识助手索引 v' + a.world.indexVersion, 'Assistant index v' + a.world.indexVersion)}</span>` : ''}${zhOnly ? `<span class="lang-tag" title="The server sends this document in Chinese until an English version exists.">Chinese source</span>` : ''}</p></div>
        ${m.version > 1 ? `<button type="button" class="toggle" data-action="toggle-compare" aria-pressed="${!!compare}">${icon('layers', 'i-sm')}${T('对比 v' + (m.version - 1), 'Compare with v' + (m.version - 1))}</button>` : ''}</header>
      <div class="prose serif"${zhOnly ? ' lang="zh-CN"' : ''}>${compare ? diffHtml(prev.content, m.content) : md(m.content, { dropTitle: true })}</div>
      <footer class="doc-foot">${btn(icon('quote', 'i-sm') + (inTask ? T('引用到这件事的作品', 'Cite in this task’s work') : T('引用到作品', 'Cite in my work')), 'cite-material', 'small', `data-id="${esc(m.id)}"`)}${who.map(r => btn(avatar(r, 'xs') + T('问 ' + PEOPLE[r].name, 'Ask ' + PEOPLE[r].name), 'discuss-material', 'small quiet', `data-id="${esc(m.id)}" data-role="${r}"`)).join('')}</footer>
    </article>
  </div>`;
}
function bench(a, t) {
  const c = a.config; const stale = a.world.indexVersion < a.world.policyVersion; const configured = !!a.backend?.configured; const s = sessionOf(a);
  const runs = t && !ui.benchAll ? a.tests.filter(r => r.taskId === t.id) : a.tests;
  return `<div class="${t ? 'obj-pad' : ''} lab">
    <section class="console ${stale ? 'is-stale' : ''}">
      <header class="console-head">${assistantMark('lg')}<div class="grow">
        <h2 class="console-name">${T('知识助手', 'Knowledge assistant')}<span class="stamp">${configured ? T('配置 v' + a.configVersion, 'Config v' + a.configVersion) : T('未设置', 'Not set up')}</span></h2>
        ${configured ? `<ul class="console-state"><li>${icon('seats', 'i-sm')}${T(c.participants + ' 人', c.participants + ' users')}</li><li>${icon('layers', 'i-sm')}${c.domains.map(DOMAIN).join(' + ') || T('未开放知识', 'No knowledge')}</li><li>${icon('sync', 'i-sm')}${UPDATE(c.update)}</li><li class="${stale ? 'warn' : ''}">${icon(stale ? 'stale' : 'doc', 'i-sm')}${T('政策源 v' + a.world.policyVersion + '，索引 v' + a.world.indexVersion, 'Policy v' + a.world.policyVersion + ', index v' + a.world.indexVersion)}</li></ul>` : `<p class="console-hint">${T('先定试点范围，助手才能回答。', 'Set the pilot scope before the assistant can answer.')}</p>`}
      </div><div class="console-tools">${stale && configured ? btn(icon('refresh', 'i-sm') + T('刷新索引', 'Refresh index'), 'refresh-index', 'small quiet') : ''}${btn(icon('gear', 'i-sm') + T('试点设置', 'Pilot settings'), 'config', configured ? 'small quiet' : 'small primary')}</div></header>
      <form class="console-compose" data-form="run-test">
        <label class="sr-only" for="lab-q">${T('你想问助手什么', 'Your question for the assistant')}</label>
        <textarea id="lab-q" name="question" class="console-q" rows="2" required maxlength="4000" placeholder="${esc(T('像员工那样问它一个问题…', 'Ask what an employee would ask…'))}">${esc(s?.inputs.question || ui.labPrefill)}</textarea>
        <div class="console-row"><label class="sr-only" for="lab-e">${T('想确认什么（选填）', 'What are you checking? (optional)')}</label><input id="lab-e" name="expectation" class="input" maxlength="5000" value="${esc(s?.inputs.expected || '')}" placeholder="${esc(T('想确认什么？选填', 'What are you checking? Optional'))}"><button type="submit" class="btn primary run-btn" ${ui.busy || !configured ? 'disabled' : ''}>${icon('play', 'i-sm')}${ui.busy ? T('运行中', 'Running') : T('运行', 'Run')}</button></div>
        <p class="console-file">${icon('note', 'i-xs')}${t ? esc(T('结果记在「' + taskTitle(t) + '」下', 'Results are filed under “' + taskTitle(t) + '”')) : T('结果不归入具体事项；从事项里打开测试台可以归档', 'Results are not filed under a task; open the bench from a task to file them')}</p>
      </form>
    </section>
    ${t ? `<div class="runs-head"><div class="segmented" role="group"><span class="thumb"></span><button type="button" aria-pressed="${!ui.benchAll}" data-action="bench-scope" data-all="0">${T('这件事的测试', 'This task')}</button><button type="button" aria-pressed="${!!ui.benchAll}" data-action="bench-scope" data-all="1">${T('全部测试', 'All tests')}</button></div></div>` : ''}
    <div class="runs">${runs.length ? groupRuns({ tests: runs }).map(g => runGroup(a, g)).join('') : `<p class="empty-line">${T('还没有测试。和预期不符的回答，往往最有用。', 'No tests yet. Surprising answers are the useful ones.')}</p>`}</div>
  </div>`;
}
function groupRuns(a) {
  const map = new Map();
  a.tests.slice().reverse().forEach(r => { const k = r.question.trim(); if (!map.has(k)) map.set(k, []); map.get(k).push(r); });
  return [...map.values()];
}
function runGroup(a, runs) {
  const r = runs[0];
  // `stale` is the server's own flag: the cited version differs from the current source.
  const old = x => (x.stale !== undefined ? !!x.stale : x.indexVersion < x.policyVersion);
  const tk = r.taskId && a.tasks.find(t => t.id === r.taskId);
  return `<article class="run ${r.id === ui.lastRun ? 'fresh' : ''}" id="run-${esc(r.id)}">
    <header class="run-q"><span class="run-asker">${T('你问', 'You asked')}</span><h3${zhAttr(r.question)}>${esc(r.question)}</h3>${runs.length > 1 ? `<span class="meta">${T(runs.length + ' 次', runs.length + ' runs')}</span>` : ''}${tk && ui.route !== 'task' ? `<button type="button" class="run-task" data-action="open-task" data-id="${tk.id}">${icon('note', 'i-xs')}${esc(taskTitle(tk))}</button>` : ''}</header>
    ${r.expectation ? `<p class="run-expect">${icon('eye', 'i-xs')}<span${zhAttr(r.expectation)}>${esc(r.expectation)}</span></p>` : ''}
    <div class="run-cols ${runs.length > 1 ? 'two' : ''}">${runs.slice(0, 2).map((x, i) => `<div class="run-col">${runs.length > 1 ? `<p class="col-cap">${i === 0 ? T('最新', 'Latest') : T('上一次', 'Previous')}</p>` : ''}
      <div class="answer ${x.fallback ? 'handoff' : ''}">${assistantMark('sm')}<div class="answer-body"${zhAttr(x.answer)}>${md(x.answer, { dropTitle: true })}${zhTag(x.answer) ? `<p class="answer-tag">${zhTag(x.answer)}</p>` : ''}</div></div>
      <div class="run-meta"><span class="stamp">${T('配置 v', 'Config v')}${x.configVersion}</span><span class="stamp ${old(x) ? 'warn' : ''}">${old(x) ? icon('stale', 'i-xs') : ''}${T('政策源 v' + x.policyVersion + ' · 索引 v' + x.indexVersion, 'Policy v' + x.policyVersion + ' · index v' + x.indexVersion)}</span>${x.citations.map(c => `<button type="button" class="chip" data-action="run-source" data-run="${esc(x.id)}">${icon('doc', 'i-xs')}<span>${esc(materialTitle({ id: c.id, title: c.title }))}</span><span class="ver">v${c.version}</span></button>`).join('')}</div></div>`).join('')}</div>
    ${old(r) ? `<p class="flag">${icon('warn', 'i-sm')}${T('这次回答引用的版本已经不是最新。', 'This answer cites a version that is no longer current.')}</p>` : ''}
    <div class="run-actions">${btn(icon('layers','i-xs')+T('核对依据','Inspect evidence'),'investigate-run','small quiet',`data-id="${esc(r.id)}"`)}${btn(icon('refresh', 'i-xs') + T('同题重测', 'Run again'), 'rerun', 'small quiet', `data-id="${esc(r.id)}"`)}${btn(icon('quote', 'i-xs') + T('作为依据', 'Use as evidence'), 'cite-run', 'small quiet', `data-id="${esc(r.id)}"`)}${btn(avatar('technical', 'xs') + T('问 Daniel', 'Ask Daniel'), 'discuss-run', 'small quiet', `data-id="${esc(r.id)}"`)}</div>
  </article>`;
}

/* the rail: talk, feedback, my agent, activity */
function wsRail(a) {
  const tabs = [['team', T('讨论', 'Talk')], ['feedback', T('反馈', 'Feedback')], ['agent', 'Agent'], ['activity', T('动态', 'Activity')]];
  const badge = { team: ROLES.reduce((n, r) => n + unread(a, r), 0) + (ui.notesCache || []).length, agent: a.artifacts.filter(x => !x.removedAt && x.source !== 'user' && !x.adopted).length };
  const t = routeTask(a);
  const scope = t && ['feedback', 'activity'].includes(ui.railTab) ? `<div class="scope"><div class="segmented" role="group" aria-label="${esc(T('范围', 'Scope'))}"><span class="thumb"></span><button type="button" aria-pressed="${!ui.scopeAll}" data-action="scope" data-all="0">${T('这件事', 'This task')}</button><button type="button" aria-pressed="${!!ui.scopeAll}" data-action="scope" data-all="1">${T('整件工作', 'Whole job')}</button></div></div>` : '';
  const body = ui.railTab === 'feedback' ? railFeedback(a, t) : ui.railTab === 'agent' ? railAgent(a, t) : ui.railTab === 'activity' ? railActivity(a, t) : ui.rail === 'chat' && ui.chatRole ? railChat(a, ui.chatRole) : railTeam(a, t);
  return `<div class="rail-top"><div class="segmented rail-tabs" role="tablist" aria-label="${esc(T('侧栏内容', 'Rail content'))}"><span class="thumb"></span>${tabs.map(([k, l]) => `<button type="button" role="tab" aria-selected="${ui.railTab === k}" aria-pressed="${ui.railTab === k}" data-action="rail-tab" data-tab="${k}">${l}${badge[k] ? `<span class="tab-badge">${badge[k]}</span>` : ''}</button>`).join('')}</div>${btn(icon('x'), 'close-panels', 'icon quiet small rail-close', `aria-label="${esc(T('关闭', 'Close'))}"`)}</div>
    <div class="rail-body">${scope}${body}</div>`;
}
function railTeam(a, t) {
  const typing = typingRole(a);
  const notes = (ui.notesCache || []).filter(n => !t || ui.scopeAll || !n.taskId || n.taskId === t.id);
  return `<div class="rail-pad">
    ${notes.length ? `<section class="notes-list"><h3 class="mini-title">${T('同事的提醒', 'Reminders')}</h3>${notes.map(marginNote).join('')}</section>` : ''}
    <ul class="people">${ROLES.map(r => {
      const last = (a.conversations[r] || []).filter(m => m.role !== 'user').at(-1); const n = unread(a, r);
      const line = typing === r ? `<span class="typing">${T('正在输入', 'typing')}<i></i><i></i><i></i></span>` : last ? `<span${zhAttr(last.text)}>${esc(last.text)}</span>` : esc(KNOWS(r));
      return `<li><button type="button" class="person ${n ? 'unread' : ''}" data-action="chat" data-role="${r}">${avatar(r, 'md', { typing: typing === r })}<span class="grow"><span class="person-name">${PEOPLE[r].name}<small>${ROLE_TITLE(r)}</small></span><span class="person-line">${line}</span></span>${n ? `<span class="count-badge">${n}</span>` : ''}</button></li>`;
    }).join('')}
      <li><button type="button" class="person mine" data-action="rail-tab" data-tab="agent">${agentMark('md')}<span class="grow"><span class="person-name">${T('我的 Agent', 'My agent')}<small>${T('你自己的工具', 'Your own tool')}</small></span><span class="person-line">${esc(agentLine(a))}</span></span></button></li>
    </ul>
  </div>`;
}
function agentLine(a) {
  const exp = (a.exports || []).length; const back = a.artifacts.filter(x => !x.removedAt && x.source !== 'user').length;
  if (!exp && !back) return T('还没交出任务', 'Nothing handed over yet');
  return T(`交出 ${exp} 次，带回 ${back} 份`, `${exp} handed over, ${back} returned`);
}
function railChat(a, role) {
  const msgs = a.conversations[role] || []; const t = routeTask(a); const x = t && ui.obj && ui.obj.type === 'work' ? artifact() : null; const typing = typingRole(a) === role; const s = sessionOf(a);
  const failed = s?.failedTurn && ROLE_OF[s.failedTurn.body.role_id] === role;
  return `<div class="chat who-${role}">
    <header class="chat-head">${btn(icon('back'), 'rail', 'icon quiet small', `data-rail="team" aria-label="${esc(T('返回团队', 'Back to team'))}"`)}${avatar(role, 'md', { typing })}<div class="grow"><p class="chat-name">${PEOPLE[role].name}<small>${ROLE_TITLE(role)}</small></p><p class="chat-knows">${esc(KNOWS(role))}</p></div></header>
    <div class="thread" role="log" aria-live="polite">${msgs.length ? msgs.map(m => msgHtml(a, role, m)).join('') : `<div class="chat-empty">${avatar(role, 'xl')}<p>${esc(OPENER(role))}</p></div>`}${typing ? `<div class="msg them is-typing" aria-label="${esc(T(PEOPLE[role].name + ' 正在输入', PEOPLE[role].name + ' is typing'))}"><span class="typing"><i></i><i></i><i></i></span></div>` : ''}${failed ? `<div class="msg-fail">${icon('warn', 'i-sm')}<span class="grow">${T('上一条没有得到回复。', 'Your last message got no reply.')}</span>${btn(T('再发一次', 'Send again'), 'resend-turn', 'small quiet')}</div>` : ''}</div>
    <div class="chat-context">${t ? `<span class="ctx" title="${esc(T('这条对话会记在这件事下', 'This conversation is filed under this task'))}">${icon('note', 'i-xs')}<span>${esc(taskTitle(t))}</span></span>` : ''}${x ? `<button type="button" class="ctx add" data-action="prefill-artifact">${icon('plus', 'i-xs')}${T('附上作品', 'Attach work')}</button>` : ''}${a.tests.length ? `<button type="button" class="ctx add" data-action="prefill-run">${icon('plus', 'i-xs')}${T('附上测试', 'Attach a test')}</button>` : ''}</div>
    <form class="composer" data-form="chat"><label class="sr-only" for="chat-input">${esc(T('给 ' + PEOPLE[role].name + ' 的消息', 'Message to ' + PEOPLE[role].name))}</label><textarea id="chat-input" name="text" rows="2" maxlength="4000" required placeholder="${esc(T('写给 ' + PEOPLE[role].name + '…', 'Message ' + PEOPLE[role].name + '…'))}">${esc(s?.inputs.messages[ROLE_ID[role]] || '')}</textarea><button type="submit" class="btn icon primary send" aria-label="${esc(T('发送', 'Send'))}" ${canWrite(a) ? '' : 'disabled'}>${icon('send')}</button></form>
  </div>`;
}
// The server's local provider answers with a fact list, not a reply. Label it so nobody mistakes it for the colleague.
const LOCAL_REPLY = /^本地事实模式[:：]\s*/;
function msgHtml(a, role, m) {
  const mine = m.role === 'user';
  const local = !mine && LOCAL_REPLY.test(m.text);
  const text = local ? m.text.replace(LOCAL_REPLY, '').split(/[；;]\s*/).filter(Boolean).map(s => '- ' + s).join('\n') : m.text;
  const t = (a.turnTimes || {})[m.traceId];
  const time = m.createdAt || (t ? (mine ? t.asked : t.answered) : '');
  const tk = m.context?.task_id ?? (a.turnTask || {})[m.traceId]; const task = tk && a.tasks.find(x => x.id === tk);
  const tag = (mine ? '' : zhTag(m.text)) + (local ? `<span class="msg-local" title="${esc(T('后端以本地模式运行，没有接模型：这里列出的是这位同事掌握的事实，并没有读你的问题。', 'The server runs in local mode with no model: this lists facts the colleague holds and does not read your question.'))}">${T('本地模式', 'Local mode')}</span>` : '');
  return `<div class="msg ${mine ? 'me' : 'them'}${local ? ' local' : ''}"><div class="bubble"${zhAttr(m.text)}>${mine ? esc(text) : md(text)}</div>${time || tag || (mine && tk) ? `<span class="msg-foot">${tag}${mine && tk ? (task ? `<button type="button" class="msg-task" data-action="open-task" data-id="${task.id}">${icon('note', 'i-xs')}${esc(taskTitle(task))}</button>` : `<span class="msg-task" title="${esc(tk)}">${esc(T('关联事项：', 'Linked task: ') + Array.from(String(tk)).slice(0, 8).join('') + (Array.from(String(tk)).length > 8 ? '…' : ''))}</span>`) : ''}${time ? `<time title="${esc(time)}">${when(time)}</time>` : ''}</span>` : ''}</div>`;
}
function railFeedback(a, t) {
  const scoped = t && !ui.scopeAll;
  const items = Coach.observations(a, E, scoped ? t.id : null);
  const x = t && ui.obj && ui.obj.type === 'work' ? a.artifacts.find(y => y.id === ui.obj.id && !y.removedAt) : null;
  const review = ui.reviewFor && x && ui.reviewFor === x.id ? Coach.checks(a, E, Object.assign({}, shown(x), { revision: x.revision })) : null;
  return `<div class="rail-pad fb-pad">
    ${x ? `<div class="fb-req"><div class="grow"><p class="fb-req-title">${esc(shown(x).title)}</p><p class="meta">${esc(purposeLabel(shown(x).purpose))} · v${x.revision}</p></div>${btn(icon('eye', 'i-sm') + T('请求评审', 'Request a review'), 'request-review', 'small')}</div>` : ''}
    ${review ? `<section class="checks-list"><h3 class="mini-title">${T('记录核对', 'Record check')}</h3>${review.map(c => `<p class="${c.ok ? 'ok' : 'bad'}">${icon(c.ok ? 'check' : 'warn', 'i-sm')}<span>${esc(c.text)}</span></p>`).join('')}</section>` : ''}
    ${items.length ? `<ol class="feedback">${items.map(i => fbItem(a, i)).join('')}</ol>` : `<p class="feed-empty">${T('从现有记录里，暂时没有要提醒的地方。这不等于论证已经成立。', 'Nothing to flag from the record so far. That does not mean the reasoning holds.')}</p>`}
    <p class="fb-label">${icon('info', 'i-xs')}${T('规则示意：根据已经发生的记录生成，不打分。正式评审在交付后由后端生成。', 'Rule-based: generated from what has happened, no scores. The formal review comes from the server after you submit.')}</p>
  </div>`;
}
function fbItem(a, i, full = false) {
  const candidate=(i.refs||[]).find(r=>r.type==='test')?.id || (i.actions||[]).find(x=>x.act==='rerun')?.id; const investigationRun=candidate&&a.tests.some(r=>r.id===candidate)?candidate:null;
  const tone = i.kind === 'contribution' ? 'star' : i.kind === 'order' ? 'branch' : { good: 'good', check: 'warn', unknown: 'question' }[i.tone];
  const key = (i.kind || i.tone) + '|' + i.title; const disputes = (a.disputes || []).filter(d => d.key === key);
  const task = i.taskId && a.tasks.find(t => t.id === i.taskId);
  return `<li class="fb ${i.tone} ${i.kind || ''}"><div class="fb-icon">${icon(tone)}</div><div class="fb-body">
    <h4>${esc(i.title)}</h4>
    <p><span class="fb-label-k">${T('看到', 'Seen')}</span>${esc(i.observed)}</p>
    ${i.basis ? `<p><span class="fb-label-k">${T('当时可知', 'Knowable then')}</span>${esc(i.basis)}</p>` : ''}
    <p><span class="fb-label-k">${T('为什么重要', 'Why it matters')}</span>${esc(i.why)}</p>
    ${i.actions.length ? `<div class="fb-actions">${i.actions.map(x => `<button type="button" class="link" data-action="fb-act" data-act="${x.act}" data-id="${esc(x.id || '')}" data-role="${x.role || ''}" data-task="${i.taskId || ''}">${esc(x.label)}</button>`).join('')}</div>` : ''}
    ${investigationRun ? `<div class="fb-actions"><button type="button" class="link" data-action="investigate-run" data-id="${esc(investigationRun)}">${icon('layers','i-xs')}${T('一起看证据','Inspect the evidence')}</button></div>`:''}
    ${full && task ? `<button type="button" class="fb-task" data-action="open-task" data-id="${task.id}">${icon('note', 'i-xs')}${esc(taskTitle(task))}</button>` : ''}
    <div class="fb-dispute">${ui.disputeOpen === key ? `<form class="dispute" data-form="dispute" data-key="${esc(key)}"><label class="sr-only" for="dispute-text">${T('你的不同看法', 'Your view')}</label><textarea id="dispute-text" class="textarea" name="text" rows="2" required maxlength="2000" placeholder="${esc(T('哪里不对？', 'What is wrong with it?'))}"></textarea><div class="row-actions"><button type="submit" class="btn small primary">${T('记下', 'Save')}</button>${btn(T('取消', 'Cancel'), 'dispute', 'small quiet', `data-key="${esc(key)}"`)}</div></form>` : `<button type="button" class="link quiet" data-action="dispute" data-key="${esc(key)}">${T('我有不同看法', 'I see it differently')}</button>`}${disputes.map(d => `<p class="dispute-note">${icon('bubble', 'i-xs')}<span${zhAttr(d.text)}>${esc(d.text)}</span></p>`).join('')}</div>
  </div></li>`;
}
function railAgent(a, t) {
  const sc = ui.exportScope; const read = readSet(a); read.add('brief');
  const scopeWorks = (t ? works(a).filter(w => w.taskId === t.id) : works(a)).length;
  const log = agentLog(a, t && !ui.scopeAll ? t.id : null);
  return `<div class="rail-pad agent-panel">
    <section class="agent-conn">
      <div class="conn-row">${agentMark('md')}<div class="grow"><p class="agent-name">${T('我的 Agent', 'My agent')}</p><p class="meta">${T('你自己的工具：只看到你交出去的内容', 'Your own tool: it only sees what you hand over')}</p></div></div>
      <div class="conn-ways">
        <div class="way on"><span class="way-dot"></span><span class="grow">${T('任务包（复制或下载，手动带回）', 'Task package (copy or download, bring back by hand)')}</span><span class="way-state">${T('可用', 'Available')}</span></div>
        <div class="way"><span class="way-dot off"></span><span class="grow">${T('MCP 直连', 'Direct MCP connection')}</span><span class="way-state">${T('后端未提供', 'Not on the server yet')}</span></div>
      </div>
    </section>
    <section class="agent-step"><h3><span class="step-n">1</span>${T('交出去', 'Hand over')}</h3><p class="agent-test-hint">${T('把任务包交给 Codex 等外部 Agent。需要测试时，它可以带回测试计划，也可以选择并组合证据模块，形成调查视图。', 'Give the package to your external agent, such as Codex. It can return a runnable test plan or compose an investigation from evidence modules.')}</p>
      <div class="checks">
        <label class="check"><input type="checkbox" checked disabled><span>${t ? esc(T('这件事：' + taskTitle(t), 'This task: ' + taskTitle(t))) : T('整件工作', 'The whole job')}</span></label>
        <label class="check"><input type="checkbox" data-scope="artifacts" ${sc.artifacts ? 'checked' : ''}><span>${T('作品', 'Work')}</span><small>${scopeWorks}</small></label>
        <label class="check"><input type="checkbox" data-scope="materials" ${sc.materials ? 'checked' : ''}><span>${T('读过的资料', 'Documents you read')}</span><small>${read.size}</small></label>
        <label class="check"><input type="checkbox" data-scope="tests" ${sc.tests ? 'checked' : ''}><span>${T('测试记录', 'Test runs')}</span><small>${a.tests.length}</small></label>
      </div>
      <div class="row-actions">${btn(icon('copy', 'i-sm') + T('复制任务包', 'Copy'), 'copy-package', 'small')}${btn(icon('download', 'i-sm') + T('下载', 'Download'), 'download-package', 'small quiet')}${btn(T('查看', 'Preview'), 'package', 'small quiet')}</div>
    </section>
    <section class="agent-step"><h3><span class="step-n">2</span>${T('带回来', 'Bring back')}</h3>
      <form data-form="import" id="import-form" class="stack">
        <label class="sr-only" for="import-content">${T('粘贴 Agent 的产出', 'Paste your agent’s output')}</label>
        <textarea class="textarea" name="content" id="import-content" rows="3" required placeholder="${esc(T('粘贴 Agent 的文字、测试计划或调查…', 'Paste your agent’s writing, test plan or investigation…'))}">${esc(ui.importText)}</textarea>
        <div class="row-actions"><label class="file-pick">${icon('upload', 'i-sm')}<span>${T('选择文件', 'Choose a file')}</span><input type="file" id="import-file" accept=".md,.txt,.json,text/plain,application/json"></label><span class="spacer"></span><button type="submit" class="btn small primary">${T('预览', 'Preview')}</button></div>
      </form>
    </section>
    <section class="agent-log"><h3 class="mini-title">${T('它做了什么', 'What it did')}</h3>
      ${log.length ? `<ol class="log">${log.map(e => `<li class="log-item">${e.icon}<div class="grow"><p>${esc(e.text)}</p>${e.sub ? `<p class="meta">${esc(e.sub)}</p>` : ''}</div>${e.at ? `<time>${when(e.at)}</time>` : ''}</li>`).join('')}</ol>` : `<p class="feed-empty">${T('交出任务包、带回作品、采用和关联测试都会记在这里。', 'Hand-overs, returns, adoptions and linked tests are recorded here.')}</p>`}
      <div class="mcp-preview"><p class="mcp-cap">${T('MCP 接入后，这里会逐条记录 Agent 的动作。示例：', 'Once MCP is connected, each agent action is logged here. Example:')}</p>
        <ol class="log ghost" aria-label="${esc(T('示例，不是真实记录', 'Example, not a real record'))}">
          <li class="log-item">${icon('doc', 'i-sm')}<div class="grow"><p>${T('读取《差旅政策》v2', 'Read “Travel policy” v2')}</p></div><span class="tag">${T('示例', 'Example')}</span></li>
          <li class="log-item">${icon('flask', 'i-sm')}<div class="grow"><p>${T('请求运行测试：住宿报销上限是多少？', 'Asked to run: what is the hotel limit?')}</p><p class="meta">${T('需要你确认后执行', 'Runs only after you confirm')}</p></div><span class="tag">${T('示例', 'Example')}</span></li>
          <li class="log-item">${icon('note', 'i-sm')}<div class="grow"><p>${T('写回草稿《测试集》，待你检查', 'Wrote back the draft “Test set”, waiting for your check')}</p></div><span class="tag">${T('示例', 'Example')}</span></li>
        </ol></div>
    </section>
  </div>`;
}
function agentLog(a, taskId) {
  const out = [];
  (a.exports || []).filter(x => !taskId || x.taskId === taskId).forEach(x => { const tk = a.tasks.find(t => t.id === x.taskId); out.push({ at: x.createdAt, icon: icon('upload', 'i-sm'), text: T('交出任务包', 'Handed over a package'), sub: (tk ? taskTitle(tk) + ' · ' : '') + T((x.inputVersions || []).length + ' 份作品', (x.inputVersions || []).length + ' work item(s)') }); });
  a.artifacts.filter(w => w.source !== 'user' && (!taskId || w.taskId === taskId)).forEach(w => {
    out.push({ at: w.createdAt, icon: icon('download', 'i-sm'), text: T('带回《' + w.title + '》', 'Returned “' + w.title + '”'), sub: w.removedAt ? T('已移除，可恢复','Removed; can be restored') : w.adopted ? T('已采用', 'Adopted') : T('待你检查', 'Waiting for your check') });
    if (w.adoptedAt) out.push({ at: w.adoptedAt, icon: icon('check', 'i-sm'), text: T('你采用了《' + w.title + '》', 'You adopted “' + w.title + '”'), sub: E.agentProgress(a,w)?.linked ? T('已关联测试', 'Linked to a test') : T('还没关联测试', 'Not linked to a test yet') });
  });
  return out.sort((x, y) => String(y.at).localeCompare(String(x.at)));
}
// Everything that happened, in plain words: the world, your work, your agent, your talks.
function activity(a, taskId) {
  const out = []; const times = a.eventTimes || {};
  a.events.forEach((e, i) => {
    if (e.server) {
      if (['save_artifact', 'pause', 'resume'].includes(e.type)) return;
      let tid = null; let open = null;
      if (e.type === 'test_assistant') { const r = a.tests.find(x => x.id === (e.detail || {}).object_id); tid = r && r.taskId; open = r ? { action: 'open-run', id: r.id } : null; }
      if (e.type === 'material_read') open = { action: 'open-doc', id: (e.detail || {}).materialId };
      const world = ['policy_updated', 'approve_request', 'approval_denied'].includes(e.type);
      if (taskId && !world && tid !== taskId) return;
      const l = eventLine(a, e);
      out.push({ at: e.createdAt || times[e.seq] || '', order: i, icon: l.icon || 'info', tone: l.tone || (world ? 'world' : ''), text: l.text, open });
      return;
    }
    const d = e.detail || {}; const work = d.artifactId && a.artifacts.find(x => x.id === d.artifactId); const tk = (d.taskId && a.tasks.find(t => t.id === d.taskId)) || (work && a.tasks.find(t => t.id === work.taskId));
    if (taskId && (!tk || tk.id !== taskId)) return;
    const text = e.type === 'task_added' && tk ? T('新增事项「' + taskTitle(tk) + '」', 'Added the task “' + taskTitle(tk) + '”')
      : e.type === 'artifact_created' && work && work.source === 'user' ? T('开始写《' + shown(work).title + '》', 'Started “' + shown(work).title + '”')
      : e.type === 'artifact_removed' && work ? T('移除《'+work.title+'》，可恢复','Removed “'+work.title+'”; can be restored')
      : e.type === 'artifact_restored' && work ? T('恢复《'+work.title+'》','Restored “'+work.title+'”')
      : e.type === 'artifact_saved' && work ? T('《' + shown(work).title + '》存为 v' + d.revision, 'Saved “' + shown(work).title + '” as v' + d.revision)
      : e.type === 'task_updated' && tk && d.changes && d.changes.status ? T('「' + taskTitle(tk) + '」改为' + STATUS(d.changes.status), '“' + taskTitle(tk) + '” is now ' + STATUS(d.changes.status))
      : e.type === 'priority_adopted' ? T('采用了同事的排序建议', 'Took a colleague’s priority advice')
      : e.type === 'feedback_disputed' ? T('对一条反馈提出了不同看法', 'Disputed a piece of feedback')
      : e.type === 'review_requested' ? T('请求评审', 'Requested a review') : '';
    if (text) out.push({ at: e.createdAt || '', order: i, icon: e.type.startsWith('artifact') ? 'note' : 'info', text, open: work ? { action: 'open-artifact', id: work.id } : tk ? { action: 'open-task', id: tk.id } : null });
  });
  Object.entries(a.turnTimes || {}).forEach(([trace, t]) => {
    if (!t || !t.answered) return;
    const tk = (a.turnTask || {})[trace]; if (taskId && tk !== taskId) return;
    const role = ROLES.find(r => (a.conversations[r] || []).some(m => m.traceId === trace)); if (!role) return;
    out.push({ at: t.answered, order: 1e9, icon: 'bubble', text: T(PEOPLE[role].name + ' 回复了你', PEOPLE[role].name + ' replied'), open: { action: 'chat', role } });
  });
  agentLog(a, taskId).forEach(e => out.push({ at: e.at, order: 1e9, icon: 'spark', text: T('我的 Agent：', 'My agent: ') + e.text, open: { action: 'rail-tab', tab: 'agent' } }));
  (ui.notesCache || []).filter(n => !taskId || n.taskId === taskId).forEach(n => out.push({ at: n.at, order: 1e9, icon: 'bubble', tone: 'note', text: T(PEOPLE[n.role].name + '（规则提醒）：', PEOPLE[n.role].name + ' (rule reminder): ') + n.text, open: { action: 'chat', role: n.role } }));
  return out.sort((x, y) => (x.at && y.at ? x.at.localeCompare(y.at) : x.at ? 1 : y.at ? -1 : x.order - y.order)).reverse();
}
function railActivity(a, t) {
  const list = activity(a, t && !ui.scopeAll ? t.id : null).slice(0, 40);
  return `<div class="rail-pad">${list.length ? `<ol class="activity">${list.map(e => `<li class="act-item ${e.tone || ''}">${e.open ? `<button type="button" class="act-open" data-action="${e.open.action}" ${e.open.id ? `data-id="${esc(e.open.id)}"` : ''} ${e.open.role ? `data-role="${e.open.role}"` : ''} ${e.open.tab ? `data-tab="${e.open.tab}"` : ''}>` : '<div class="act-open">'}${icon(e.icon, 'i-sm')}<span class="grow"${zhAttr(e.text)}>${esc(e.text)}</span>${e.at ? `<time>${when(e.at)}</time>` : ''}${e.open ? '</button>' : '</div>'}</li>`).join('')}</ol>` : `<p class="feed-empty">${T('发生的事会按时间记在这里。', 'What happens is recorded here, in order.')}</p>`}</div>`;
}

/* ---------- 4. review ---------- */
function renderReview() {
  const a = current(); const s = sessionOf(a); const fb = s?.feedback; const submission = s ? L.store.submissionId(s) : '';
  const pending = s?.pending && (s.pending.job?.kind ?? s.pending.kind) === 'feedback';
  const head = topbar(backBtn('to-board', T('工作板', 'Board')));
  if (!submission) return `${head}<main id="main" class="page review" tabindex="-1"><div class="empty big"><h1 class="title-l">${T('交付之后，评审会出现在这里', 'The review appears here after you submit')}</h1>${btn(T('回到工作台', 'Back to the workspace'), 'to-work', 'primary')}</div></main>`;
  const items = fb ? fb.items : [];
  const groups = [
    ['NOT_MET', T('需要补上', 'Needs work'), 'warn'],
    ['open', T('证据不足或需要核验', 'Not enough evidence, or needs checking'), 'question'],
    ['MET', T('已经站住', 'Holds up'), 'good'],
    ['NOT_APPLICABLE', T('不适用', 'Not applicable'), 'minus']
  ];
  const bucket = i => (i.label === 'NOT_MET' ? 'NOT_MET' : i.label === 'MET' && !i.review_required ? 'MET' : i.label === 'NOT_APPLICABLE' ? 'NOT_APPLICABLE' : 'open');
  const counts = Object.fromEntries(groups.map(([k]) => [k, items.filter(i => bucket(i) === k).length]));
  const art = s.artifact; const content = art ? art.content : s.draft;
  // The server attaches the same evidence to every criterion; show the shared set once.
  const common = items.length ? items.map(i => new Set(i.evidence_ids || [])).reduce((x, y) => new Set([...x].filter(v => y.has(v)))) : new Set();
  const firstCrit = items[0] ? items[0].criterion_id : '';
  ui.reviewCommon = common;
  return `${head}
    <main id="main" class="page review" tabindex="-1">
      <header class="review-hero">
        <div class="review-title"><p class="meta">${esc(CASE(a.scenarioId).title)}</p><h1 class="title-xl">${T('上线评审', 'Launch review')}</h1>
          <p class="review-stamp">${icon('stamp', 'i-sm')}${T('已固定交付', 'Submitted')}${art ? `<span>${T('交付稿 v' + art.version, 'Deliverable v' + art.version)}</span><span>${T('配置 v' + art.config_version, 'Config v' + art.config_version)}</span>` : ''}${fb ? `<span>${T('截至事件 #' + fb.as_of_seq, 'As of event #' + fb.as_of_seq)}</span>` : ''}</p></div>
        <div class="review-conds"><p class="meta">${T('交付时的条件', 'Conditions at submission')}</p>${conditions(a, 'compact')}</div>
      </header>
      <nav class="review-tabs segmented" role="group" aria-label="${esc(T('评审内容', 'Review content'))}"><span class="thumb"></span><button type="button" aria-pressed="${ui.reviewTab !== 'coach'}" data-action="review-tab" data-tab="rules">${T('上线检查（后端规则）', 'Launch checks (server rules)')}</button><button type="button" aria-pressed="${ui.reviewTab === 'coach'}" data-action="review-tab" data-tab="coach">${T('情境反馈（当时可知）', 'In context (what was knowable)')}</button></nav>
      ${fb?.overflow && ui.reviewTab !== 'coach' ? `<p class="warn-line" data-feedback-overflow>${icon('warn', 'i-sm')}${T('证据超过长度上限，部分条目未评。', 'The evidence exceeds the length limit; some items were not reviewed.')}${btn(T('查看交付面板的作品选择', 'View work selection in the deliverable'), 'review-works', 'small quiet')}</p>` : ''}
      ${fb && ui.reviewTab !== 'coach' ? `<div class="tally" role="img" aria-label="${esc(groups.filter(([k]) => counts[k]).map(([k, l]) => l + ' ' + counts[k]).join(T('，', ', ')))}">${groups.filter(([k]) => counts[k]).map(([k, l, ic]) => `<span class="tally-seg ${k}" style="flex:${counts[k]}"><span class="tally-label">${icon(ic, 'i-xs')}${counts[k]}</span></span>`).join('')}</div>` : ''}
      ${fb && common.size && ui.reviewTab !== 'coach' ? `<div class="shared-evidence"><span class="meta">${T('评审读取的记录', 'Records the review read')}</span>${[...common].map(id => `<button type="button" class="chip" data-action="live-evidence" data-criterion="${esc(firstCrit)}" data-id="${esc(id)}">${icon(evidenceIcon(fb, id), 'i-xs')}<span>${esc(evidenceLabel(a, fb, id))}</span></button>`).join('')}</div>` : ''}
      <div class="review-grid">
        <div class="review-main">
          ${pending || (!fb && !s.feedbackFailure) ? `<div class="review-wait">${pending ? `<span class="spinner"></span><p>${T('评审正在生成…', 'The review is being written…')}</p>` : `<p>${T('交付已固定，评审还没生成。', 'Submitted; the review has not been generated yet.')}</p>${btn(T('生成评审', 'Generate the review'), 'live-feedback', 'primary', canWrite(a) || s.world.status === 'submitted' ? '' : 'disabled')}`}</div>` : ''}
          ${s.feedbackFailure && !pending ? `<div class="review-wait bad">${icon('warn', 'i-sm')}<p>${esc(T('评审任务失败：', 'The review job failed: ') + (s.feedbackFailure.error || ''))}</p>${s.feedbackFailure.kind === 'feedback' ? btn(T('重新生成', 'Regenerate'), 'live-feedback', 'primary', 'data-retry="true"') : `<p>${T('当前服务不支持重新生成失败的评审。', 'This server cannot regenerate failed reviews.')}</p>`}</div>` : ''}
          ${ui.reviewTab === 'coach' ? coachSection(a) : ''}
          ${ui.reviewTab !== 'coach' && fb ? groups.map(([k, l, ic]) => { const list = items.filter(i => bucket(i) === k); return list.length ? `<section class="review-group ${k}"><h2 class="group-title">${icon(ic, 'i-sm')}${l}<span class="count">${list.length}</span></h2><ol class="criteria">${mergeSame(list).map(g => criterionItem(a, fb, g, common)).join('')}</ol></section>` : ''; }).join('') : ''}
          ${ui.reviewTab !== 'coach' && fb && fb.practice && fb.practice.length ? `<section class="review-group"><h2 class="group-title">${icon('branch', 'i-sm')}${T('建议补练', 'Suggested practice')}</h2><ul class="practice-list">${fb.practice.map(p => `<li${zhAttr(p)}>${esc(p)}</li>`).join('')}</ul></section>` : ''}
          ${ui.reviewTab !== 'coach' && fb ? `<p class="review-foot">${icon('info', 'i-xs')}${esc(T(`规则检查 ${fb.model_revision}：不是最终评分；标为“需要核验”的项要由人确认。`, `Rule check ${fb.model_revision}: not a final grade. Items marked “needs checking” need a person to confirm.`))}</p>` : ''}
        </div>
        <aside class="review-side">
          <article class="paper deliverable">${stampMark(a)}<h2 class="paper-title">${T('你交付的内容', 'What you submitted')}</h2>${FIELDS.map(k => `<section class="field-doc"><h3>${FIELD(k)}</h3>${content && content[k] ? `<div class="prose serif"${zhAttr(content[k])}>${md(content[k])}</div>` : `<p class="muted">${T('（空）', '(empty)')}</p>`}</section>`).join('')}</article>
          <section class="next"><h2 class="group-title">${T('接下来', 'Next')}</h2>
            ${['pilot', 'urgent', 'capacity'].filter(id => id !== a.scenarioId).map(id => `<button type="button" class="next-row" data-action="practice-variant" data-case="${id}">${icon('bolt', 'i-sm row-icon')}<span class="grow"><span class="row-title">${esc(CASE(id).title)}</span><span class="row-sub">${esc(CASE(id).change || T('回到主情境', 'Back to the main situation'))}</span></span>${icon('chev', 'i-sm')}</button>`).join('')}
            <button type="button" class="next-row" data-action="practice-variant" data-case="${esc(a.scenarioId)}">${icon('refresh', 'i-sm row-icon')}<span class="grow"><span class="row-title">${T('同一情境再来一次', 'Try the same situation again')}</span><span class="row-sub">${T('新的练习，这次的记录保留', 'A fresh attempt; this one stays as it is')}</span></span>${icon('chev', 'i-sm')}</button>
          </section>
        </aside>
      </div>
    </main>`;
}
// Feedback in context: what is in the record, what was knowable at the time, why it matters.
function coachSection(a) {
  const items = Coach.observations(a, E, null);
  return `<section class="review-group coach"><p class="coach-lede">${T('从你实际做过的事里整理：看到了什么、当时能知道什么、为什么重要、可以做什么。不打分，可以提出不同看法。', 'Drawn from what you actually did: what is in the record, what was knowable then, why it matters, what you could do. No scores; you can disagree.')}</p>
    ${items.length ? `<ol class="feedback full">${items.map(i => fbItem(a, i, true)).join('')}</ol>` : `<p class="feed-empty">${T('从现有记录里没有可整理的观察。', 'Nothing to draw from the record.')}</p>`}
    <p class="review-foot">${icon('info', 'i-xs')}${T('规则示意：根据记录生成，不是模型评审。情境化 Judge 需要后端支持。', 'Rule-based, from the record, not a model review. A contextual judge needs server support.')}</p></section>`;
}
// Criteria with the same verdict and the same reason read as one finding.
function mergeSame(list) {
  const out = [];
  for (const i of list) { const k = i.label + '|' + i.reason + '|' + !!i.review_required; const g = out.find(x => x.key === k); if (g) g.names.push(i.criterion_id); else out.push({ ...i, key: k, names: [i.criterion_id] }); }
  return out;
}
function stampMark(a) {
  const fresh = ui.justSubmitted === a.id; if (fresh) ui.justSubmitted = null;
  return `<div class="stamp-mark ${fresh ? 'fresh' : ''}" aria-hidden="true"><span>${T('已提交', 'Submitted')}</span>${a.submittedAt ? `<small>${esc(new Date(a.submittedAt).toLocaleDateString(locale() === 'en' ? 'en-GB' : 'zh-CN', { year: 'numeric', month: 'short', day: 'numeric' }))}</small>` : ''}</div>`;
}
function criterionItem(a, fb, i, common) {
  const ic = i.label === 'MET' ? 'good' : i.label === 'NOT_MET' ? 'warn' : i.label === 'NOT_APPLICABLE' ? 'minus' : 'question';
  const own = [...new Set(i.evidence_ids || [])].filter(id => !common.has(id));
  return `<li class="criterion ${i.label}">
    <div class="crit-icon">${icon(ic)}</div>
    <div class="crit-body">
      <h3><span class="crit-name">${esc((i.names || [i.criterion_id]).map(criterionName).join(T('、', ', ')))}</span><span class="label-chip ${i.label}">${LABEL(i.label)}</span>${i.review_required ? `<span class="label-chip check">${T('需要核验', 'Needs checking')}</span>` : ''}</h3>
      <p${zhAttr(i.reason)}>${esc(i.reason)}</p>
      ${own.length ? `<div class="crit-evidence">${own.map(id => `<button type="button" class="chip" data-action="live-evidence" data-criterion="${esc(i.criterion_id)}" data-id="${esc(id)}">${icon(evidenceIcon(fb, id), 'i-xs')}<span>${esc(evidenceLabel(a, fb, id))}</span></button>`).join('')}</div>` : ''}
    </div>
  </li>`;
}
function evidenceRef(fb, id) { for (const c of Object.values((fb && fb.sources) || {})) if (c && c[id]) return c[id]; return null; }
function evidenceIcon(fb, id) { const r = evidenceRef(fb, id); return ({ config: 'gear', artifact: 'stamp', event: 'history', test_result: 'flask', document: 'doc' })[r && r.kind] || 'doc'; }
function evidenceLabel(a, fb, id) {
  const r = evidenceRef(fb, id); if (!r) return T('记录 ', 'Record ') + id;
  if (r.kind === 'config') return T('试点设置 v' + r.version, 'Pilot settings v' + r.version);
  if (r.kind === 'artifact') return T('交付稿', 'Deliverable');
  if (r.kind === 'event') return T('条件与审批', 'Conditions and approvals');
  if (r.kind === 'test_result') { const t = a.tests.find(x => x.id === r.object_id); return T('测试：', 'Test: ') + (t ? t.question.slice(0, 28) : String(r.object_id).slice(0, 8)); }
  if (r.kind === 'document') return materialTitle({ id: r.object_id, title: r.object_id });
  return r.kind;
}

/* ---------- sheets ---------- */
function openSheet(title, body, foot = '', cls = '') {
  commit();
  if (!sheet.open) sheetReturn = focusKey();
  sheet.className = 'sheet ' + cls;
  sheet.innerHTML = `<header class="sheet-head"><h2 id="sheet-title">${title}</h2>${btn(icon('x'), 'close', 'icon quiet small', `aria-label="${esc(T('关闭', 'Close'))}"`)}</header><div class="sheet-body">${body}</div>${foot ? `<footer class="sheet-foot">${foot}</footer>` : ''}`;
  if (!sheet.open) sheet.showModal();
  (sheet.querySelector('[autofocus]') || sheet.querySelector('.sheet-body input:not([type=checkbox]):not([type=radio]), .sheet-body textarea') || sheet.querySelector('.sheet-foot .primary') || sheet.querySelector('.sheet-head .btn'))?.focus();
  sheet.querySelectorAll('.segmented').forEach(layoutSegmented);
}
function closeSheet(instant) {
  if (!sheet.open) return;
  const done = () => { sheet.classList.remove('closing'); sheet.close(); const el = sheetReturn && (sheetReturn.id ? document.getElementById(sheetReturn.id) : document.querySelector(sheetReturn.sel)); if (el) el.focus({ preventScroll: true }); else document.getElementById('main')?.focus({ preventScroll: true }); };
  if (instant || reduceMotion.matches) { done(); return; }
  sheet.classList.add('closing'); setTimeout(done, 200);
}
function sheetTask(id) {
  const a = current(); const t = a.tasks.find(x => x.id === id);
  openSheet(t ? T('编辑事项', 'Edit task') : T('新事项', 'New task'), `<form data-form="task" data-id="${t ? t.id : ''}" class="stack" id="task-form">
      <label class="field"><span>${T('要处理的事', 'What needs doing')}</span><input class="input" name="title" required maxlength="120" value="${esc(t ? taskTitle(t) : '')}" placeholder="${esc(T('例如：问清政策多久变一次', 'For example: find out how often policy changes'))}" autofocus></label>
      <label class="field"><span>${T('补充', 'Notes')} <small>${T('选填', 'optional')}</small></span><textarea class="textarea" name="note" rows="3" maxlength="5000">${esc(t ? taskNote(t) : '')}</textarea></label>
      <fieldset class="field"><legend>${T('优先级', 'Priority')}</legend><div class="choices">${['first', 'next', 'later'].map(k => `<label class="choice"><input type="radio" name="priority" value="${k}" ${(t ? t.priority : 'next') === k ? 'checked' : ''}><span>${priMark(k)}${PRI(k)}</span></label>`).join('')}</div></fieldset>
      ${t ? `<label class="field"><span>${T('拆出一件新事', 'Split off a new task')} <small>${T('选填', 'optional')}</small></span><input class="input" name="split" maxlength="120"></label>` : ''}
    </form>`, `${t ? `${btn(icon('back', 'i-sm') + T('上移', 'Move up'), 'move-task', 'quiet', `data-id="${t.id}" data-dir="-1"`)}${btn(T('下移', 'Move down'), 'move-task', 'quiet', `data-id="${t.id}" data-dir="1"`)}<span class="spacer"></span>` : ''}<button type="submit" form="task-form" class="btn primary">${t ? T('保存', 'Save') : T('加入', 'Add')}</button>`, 'narrow');
}
function sheetNewArtifact(purpose) {
  const a = current(); const t = task();
  openSheet(T('新作品', 'New piece of work'), `<form data-form="artifact" id="artifact-form" class="stack">
    <label class="field"><span>${T('标题', 'Title')}</span><input class="input" name="title" required maxlength="160" value="${purpose === '试点决定' ? esc(T('试点决定', 'Pilot decision')) : ''}" placeholder="${esc(T('例如：我对首批范围的判断', 'For example: who goes first, and why'))}" autofocus></label>
    <fieldset class="field"><legend>${T('它现在用来做什么', 'What it is for, for now')}</legend><div class="choices wrap">${E.PURPOSES.map(p => `<label class="choice"><input type="radio" name="purpose" value="${p}" ${p === (purpose || '探索笔记') ? 'checked' : ''}><span>${esc(purposeLabel(p))}</span></label>`).join('')}</div></fieldset>
    <label class="field"><span>${T('属于哪件事', 'Which task')}</span><select class="select" name="taskId" required>${t || purpose ? '' : `<option value="" selected disabled>${T('选一件事', 'Pick a task')}</option>`}${a.tasks.map(x => `<option value="${x.id}" ${(t ? x.id === t.id : purpose && x.seed === 'decision') ? 'selected' : ''}>${esc(taskTitle(x))}</option>`).join('')}</select></label>
  </form>`, `<button type="submit" form="artifact-form" class="btn primary">${T('开始写', 'Start writing')}</button>`, 'narrow');
}
function configChecks(a, c) {
  const cost = (c.workItems || []).reduce((n, k) => n + (WORK_COST[k] || 0), 0) + (c.update === 'realtime' && !(c.workItems || []).includes('realtime') ? 5 : 0);
  const rows = [[T(`试点 ${c.participants || 0} 人`, `${c.participants || 0} users`), T(`容量 ${a.world.capacity}`, `capacity ${a.world.capacity}`), c.participants <= a.world.capacity], [T(`开发 ${cost} 人日`, `${cost} person-days`), T(`可用 ${a.world.devDays}`, `${a.world.devDays} available`), cost <= a.world.devDays], [T(`开放 ${(c.domains || []).length} 类知识`, `${(c.domains || []).length} knowledge areas`), T('至少 1 类', 'at least 1'), (c.domains || []).length > 0]];
  return `<div class="checks-live" data-checks>${rows.map(([l, r, ok]) => `<p class="${ok ? 'ok' : 'bad'}">${icon(ok ? 'check' : 'x', 'i-sm')}<span>${l}</span><span class="muted">${r}</span></p>`).join('')}${rows.some(r => !r[2]) ? `<p class="checks-note">${T('超出条件的方案可以保存，但要另外申请并获批才算数。', 'You can save a plan beyond the limits, but it only counts once a request is approved.')}</p>` : ''}</div>`;
}
function sheetConfig() {
  const a = current();
  const c = a.configDraft || (!a.backend.configured ? { participants: Math.min(20, a.world.capacity), domains: ['faq', 'policy'], update: 'daily', fallback: 'human', workItems: ['scope', 'fallback'], launchDay: a.world.deadline } : a.config);
  openSheet(T('试点设置', 'Pilot settings'), `<form data-form="config" id="config-form" class="stack">
    <div class="field-row"><label class="field"><span>${T('试点人数', 'Users in the pilot')}</span><input class="input" type="number" name="participants" min="1" max="10000" value="${c.participants}" required></label>
    <label class="field"><span>${T('计划上线日', 'Planned launch day')}</span><input class="input" name="launchDay" type="number" min="1" value="${c.launchDay || a.world.deadline}" required></label></div>
    <fieldset class="field"><legend>${T('开放的知识', 'Knowledge it covers')}</legend><div class="choices">${['faq', 'policy'].map(k => `<label class="choice"><input type="checkbox" name="domains" value="${k}" ${c.domains.includes(k) ? 'checked' : ''}><span>${DOMAIN(k)}</span></label>`).join('')}</div></fieldset>
    <fieldset class="field"><legend>${T('政策怎么保持最新', 'Keeping policy current')}</legend><div class="choices wrap">${['daily', 'realtime', 'manual'].map(k => `<label class="choice"><input type="radio" name="update" value="${k}" ${c.update === k ? 'checked' : ''}><span>${UPDATE(k)}</span></label>`).join('')}</div></fieldset>
    <fieldset class="field"><legend>${T('答不了或不确定时', 'When it cannot answer')}</legend><div class="choices">${['human', 'none'].map(k => `<label class="choice"><input type="radio" name="fallback" value="${k}" ${c.fallback === k ? 'checked' : ''}><span>${FALLBACK(k)}</span></label>`).join('')}</div></fieldset>
    <fieldset class="field"><legend>${T('要安排的开发', 'Engineering work')}</legend><div class="choices wrap">${['scope', 'fallback', 'realtime'].map(k => `<label class="choice"><input type="checkbox" name="workItems" value="${k}" ${c.workItems.includes(k) ? 'checked' : ''}><span>${WORK_ITEM(k)}<small>${T(WORK_COST[k] + ' 人日', WORK_COST[k] + ' pd')}</small></span></label>`).join('')}</div></fieldset>
    ${configChecks(a, c)}
  </form>`, `${btn(icon('hand', 'i-sm') + T('申请资源', 'Request resources'), 'resources', 'quiet')}<span class="spacer"></span><button type="submit" form="config-form" class="btn primary">${T('保存设置', 'Save settings')}</button>`, '');
}
function sheetResources() {
  const a = current(); const s = sessionOf(a);
  const pending = s?.world.pending_requests || [];
  const denials = (s?.timeline.approval_denials || []).slice(-3).reverse();
  if (s?.approvalError && !denials.some(d => d.rule_id === s.approvalError.rule_id && d.code === s.approvalError.code)) denials.unshift(s.approvalError);
  openSheet(T('资源与审批', 'Resources and approvals'), `<div class="res-now">${conditions(a, 'compact')}</div>
    ${denials.map(d => `<p class="warn-line" data-approval-denial>${icon('hand', 'i-sm')}<span>${esc(serverText(d.error || '', d.code, d.details))}</span></p>`).join('')}
    <form data-form="resources" id="res-form" class="stack">
      <fieldset class="field"><legend>${T('申请什么', 'What you need')}</legend><div class="choices">${[['request_capacity', T('更多名额', 'More seats')], ['request_resources', T('更多开发资源或延期', 'More engineering time or a later date')]].map(([k, l], i) => `<label class="choice"><input type="radio" name="kind" value="${k}" ${i === 0 ? 'checked' : ''}><span>${l}</span></label>`).join('')}</div></fieldset>
      <label class="field"><span>${T('理由', 'Why')}</span><textarea class="textarea" name="reason" required maxlength="4000" rows="4" placeholder="${esc(T('要多少、做什么、为什么值得', 'How much, for what, and why it is worth it'))}"></textarea></label>
    </form>
    ${pending.length ? `<section class="pending"><h3 class="mini-title">${T('等待 Priya 处理', 'Waiting for Priya')}</h3>${pending.map(rule => `<div class="pending-row">${avatar('manager', 'sm')}<span class="grow">${rule === 'capacity_approved' ? T('扩容申请', 'Seat request') : T('资源与延期申请', 'Resource request')}</span>${btn(T('请 Priya 处理', 'Ask Priya to decide'), 'live-approval', 'small', `data-id="${esc(rule)}"`)}</div>`).join('')}</section>` : ''}`,
  `<button type="submit" form="res-form" class="btn primary">${T('提交申请', 'Send request')}</button>`, 'narrow');
}
// Which pieces of local work go into the deliverable is the learner's choice.
function deliverPick(a) {
  const list = works(a).filter(w => shown(w).body.trim());
  if (!ui.deliverPick || ui.deliverPickFor !== a.id) {
    const decisions = list.filter(w => E.intentOf(shown(w).purpose) === 'commit');
    ui.deliverPick = new Set((decisions.length ? decisions : list).map(w => w.id)); ui.deliverPickFor = a.id;
  }
  return list;
}
function rationaleFrom(a, ids) {
  return works(a).filter(w => ids.has(w.id)).map(x => { const v = shown(x); return '## ' + v.title + T('（' + purposeLabel(v.purpose) + '）', ' (' + purposeLabel(v.purpose) + ')') + '\n' + v.body.trim() + (x.evidence.length ? '\n' + T('依据：', 'Evidence: ') + x.evidence.map(e => evTitle(e) + (e.version ? ' v' + e.version : '')).join(T('；', '; ')) : ''); }).join('\n\n');
}
// The review reads one evidence bundle of at most 16,000 bytes; past that every item
// is left unreviewed with an explicit overflow flag. Rough estimate from measurements on this backend.
function bundleRisk(a, draft) {
  const bytes = s => new TextEncoder().encode(String(s || '')).length;
  const fields = FIELDS.reduce((n, k) => n + bytes(draft[k]), 0);
  return 7000 + fields + bytes(draft.rationale) + a.tests.length * 750 > 14500;
}
function sheetDeliver(readOnly = false) {
  const a = current(); const s = sessionOf(a);
  if (s.world.status === 'submitted' && !readOnly) { closeSheet(true); go('review'); return; }
  const list = deliverPick(a);
  if (!readOnly && !s.draft.rationale && list.length) L.store.update(a.id, { draft: { ...s.draft, rationale: rationaleFrom(a, ui.deliverPick) } });
  const now = sessionOf(a); const saved = now.artifact && JSON.stringify(now.artifact.content) === JSON.stringify(now.draft) && now.artifact.config_version === now.world.config_version;
  const risk = bundleRisk(a, now.draft);
  const displayed = readOnly ? (s.artifact?.content || s.draft) : now.draft;
  openSheet(T('交付试点决定', 'Submit your pilot decision'), `<div class="deliver">
  <form data-form="live-deliver" id="live-deliver" class="deliver-doc paper">
    ${FIELDS.map(k => `<section class="field-doc"><label for="d-${k}"><span class="fd-name">${FIELD(k)}</span><span class="fd-hint">${FIELD_HINT(k)}</span></label><textarea id="d-${k}" class="doc-input" name="${k}" ${readOnly ? 'readonly' : ''} rows="${k === 'rationale' ? 8 : 2}"${zhAttr(now.draft[k])}>${esc(displayed[k])}</textarea></section>`).join('')}
  </form>
  <aside class="deliver-side">
    <h3 class="mini-title">${T('附上的作品', 'Work to include')}</h3>
    ${list.length ? `<div class="checks">${list.map(w => { const v = shown(w); return `<label class="check"><input type="checkbox" data-pick="${w.id}" ${readOnly ? 'disabled' : ''} ${ui.deliverPick.has(w.id) ? 'checked' : ''}><span>${esc(v.title)}</span><small>${esc(purposeLabel(v.purpose))}</small></label>`; }).join('')}</div>` : `<p class="muted">${T('没有可附上的作品。', 'No work to include.')}</p>`}
    ${!readOnly && (list.length || now.draft.rationale) ? btn(icon('refresh', 'i-sm') + (list.length ? T('按勾选重写依据', 'Rewrite evidence from these') : T('清空方案与依据','Clear rationale and evidence')), 'live-collect', 'small quiet') : ''}
    ${a.deliverRemovalNotice ? `<p class="warn-line">${icon('info','i-sm')}${T('有作品被移除，交付稿中的手写内容已保留。请核对，或按当前作品重新整理。','Some work was removed. Edited deliverable text was kept. Review it, or rebuild it from the current work.')}</p>` : ''}
    ${risk ? `<p class="warn-line">${icon('warn', 'i-sm')}${T('内容偏长：评审一次最多读约 16 KB 记录，超过后相关条目不会评审。精简依据或少附作品。', 'This is long. The review reads about 16 KB of records at most; items beyond that limit are left unreviewed. Trim the evidence or include fewer pieces.')}</p>` : ''}
    <p class="meta">${now.artifact ? (saved ? T('已保存为交付稿 v' + now.artifact.version, 'Saved as deliverable v' + now.artifact.version) : T('交付稿 v' + now.artifact.version + ' 之后有改动', 'Changed since deliverable v' + now.artifact.version)) : T('还没保存', 'Not saved yet')}</p>
  </aside></div>`,
  readOnly ? `<span class="foot-note">${T('本次交付已固定。下次交付可在这里少选作品、精简依据。', 'This submission is fixed. For the next submission, select fewer works here and trim the evidence.')}</span>${btn(T('关闭', 'Close'), 'close', 'primary')}` : `<span class="foot-note">${T('提交后这次练习只读，可以换个条件再练。', 'Once submitted, this practice is read-only. You can practise again with a new condition.')}</span><span class="spacer"></span>${btn(T('保存', 'Save'), 'live-save', saved ? 'quiet' : '')}${btn(icon('stamp', 'i-sm') + T('提交', 'Submit'), 'live-submit', 'primary', saved ? '' : 'disabled')}`, 'wide doc');
}
function sheetCitePicker() {
  const a = current(); const read = readSet(a); read.add('brief');
  const docs = E.getMaterials(a).filter(m => read.has(m.id));
  openSheet(T('引用依据', 'Cite evidence'), `<div class="pick-list">
    <h3 class="mini-title">${T('读过的资料', 'Documents you read')}</h3>${docs.map(m => `<button type="button" class="pick-row" data-action="cite-material" data-id="${esc(m.id)}">${icon('doc', 'i-sm')}<span class="grow">${esc(materialTitle(m))}</span><span class="ver">v${m.version}</span></button>`).join('') || `<p class="muted">${T('还没读过资料。', 'No documents read yet.')}</p>`}
    <h3 class="mini-title">${T('测试', 'Tests')}</h3>${a.tests.slice().reverse().map(r => `<button type="button" class="pick-row" data-action="cite-run" data-id="${esc(r.id)}">${assistantMark('xs')}<span class="grow"${zhAttr(r.question)}>${esc(r.question)}</span><span class="ver">${T('配置 v', 'config v')}${r.configVersion}</span></button>`).join('') || `<p class="muted">${T('还没有测试。', 'No tests yet.')}</p>`}
  </div>`, '', 'narrow');
}
function sheetAbout() {
  const n = snap();
  openSheet(T('关于这个工作台', 'About this workspace'), `<div class="prose">
    <p>${T('资料、三位同事的回复、试点设置、申请审批、助手测试、交付和评审，都来自 RoleCraft 后端。', 'Documents, colleague replies, pilot settings, approvals, assistant tests, submission and review come from the RoleCraft server.')}</p>
    <p>${T('事项、作品和 Agent 导入保存在这个浏览器；交付时由你合并进交付稿。', 'Tasks, work and agent imports are kept in this browser. You fold them into the deliverable when you submit.')}</p>
    <dl class="kv"><div><dt>${T('后端', 'Server')}</dt><dd>${n.connected ? T('已连接', 'Connected') : T('未连接', 'Not connected')}</dd></div><div><dt>${T('同事与助手模式', 'Colleague and assistant mode')}</dt><dd>${esc(n.model || '—')}</dd></div></dl>
    <h3 class="mini-title">${T('颜色和形状', 'Colour and shape')}</h3>
    <ul class="legend">
      <li><span class="sw ink"></span>${T('你，和你能做的事；你的 Agent 也是这个颜色', 'You and what you can do; your agent shares it')}</li>
      <li><span class="sw warn"></span>${T('外面变了或已过期：政策更新、索引落后、条件被改变', 'Changed from outside or out of date: a policy update, a lagging index, a changed condition')}</li>
      <li><span class="sw good"></span>${T('站得住：已完成、已满足、已批准、可用', 'Holds: done, met, approved, available')}</li>
      <li><span class="sw bad"></span>${T('超出限制', 'Over a limit')}</li>
      <li><span class="sw grey"></span>${T('还不知道：证据不足、需要核验', 'Not known yet: thin evidence, needs checking')}</li>
      <li><span class="sw-people">${avatar('manager', 'xs')}${avatar('business', 'xs')}${avatar('technical', 'xs')}${assistantMark('xs')}</span>${T('谁：Priya、Mei、Daniel、知识助手', 'Who: Priya, Mei, Daniel, the knowledge assistant')}</li>
      <li><span class="sw-shape">${priMark('first')}${priMark('next')}${priMark('later')}</span>${T('优先级：先做、随后、暂放', 'Priority: first, next, later')}</li>
      <li><span class="sw-shape">${statusMark('open')}${statusMark('working')}${statusMark('done')}</span>${T('进展：待处理、正在做、已处理', 'Progress: to do, in progress, done')}</li>
    </ul>
    <p class="muted">${T('还没有：同事主动发言、跨回合记忆、交付后修订、MCP 直连、模型评审。', 'Not yet available: colleagues speaking first, memory across turns, revising after submission, direct MCP connection, model-based review.')}</p>
  </div>`, `${btn(T('刷新连接', 'Reconnect'), 'live-refresh', 'quiet')}<span class="spacer"></span>${btn(T('好', 'OK'), 'close', 'primary')}`, 'narrow');
}

/* ---------- live world: connection, typing, arrivals ---------- */
function onLive(changed) {
  const n = snap();
  noticeArrivals();
  if (n.error && n.error !== ui.lastError) { ui.lastError = n.error; notify(n.error); } else if (!n.error) ui.lastError = '';
  if (changed) scheduleRefresh(); else refreshChrome();
}
let refreshQueued = false;
function scheduleRefresh() {
  if (refreshQueued) return; refreshQueued = true;
  queueMicrotask(() => {
    refreshQueued = false;
    if (dirty) flush();
    if (WS.includes(ui.route) && current()) refreshWS(); else render();
  });
}
function refreshChrome() { if (WS.includes(ui.route) && current()) refreshWS(['toolbar']); }
// What changed in the world since we last looked: replies, policy versions, approvals.
function noticeArrivals() {
  const a = current(); if (!a || !a.backend) return;
  const s = sessionOf(a); if (!s) return;
  a.turnTimes = a.turnTimes || {}; a.eventTimes = a.eventTimes || {}; a.readTurns = a.readTurns || {};
  const first = !ui.synced;
  const pend = pendingTurnRole(s) ? s.pending : null;
  if (pend) ui.pendingTurn = { role: ROLE_OF[pendingTurnRole(s)], created: pend.job?.queued_at || pend.created, taskId: pend.body.task_id ?? ui.chatTask ?? null };
  a.turnTask = a.turnTask || {};
  let dirtyRecord = false;
  for (const r of ROLES) {
    const msgs = (a.conversations[r] || []).filter(m => m.role !== 'user');
    if (a.readTurns[r] === undefined) { a.readTurns[r] = msgs.length; dirtyRecord = true; }
    for (const m of msgs) {
      if (!m.traceId) continue;
      if (a.turnTimes[m.traceId] !== undefined) { if (m.createdAt) a.turnTimes[m.traceId] = { asked: m.createdAt, answered: m.createdAt }; continue; }
      if (first) { a.turnTimes[m.traceId] = m.createdAt ? { asked: m.createdAt, answered: m.createdAt } : null; continue; }
      const asked = ui.pendingTurn && ui.pendingTurn.role === r ? ui.pendingTurn.created : null;
      a.turnTimes[m.traceId] = { asked: m.createdAt || asked, answered: m.createdAt || new Date().toISOString() }; dirtyRecord = true;
      if (m.context?.task_id === undefined && ui.pendingTurn && ui.pendingTurn.role === r && ui.pendingTurn.taskId) a.turnTask[m.traceId] = ui.pendingTurn.taskId;
      if (ui.pendingTurn && ui.pendingTurn.role === r) ui.pendingTurn = null;
      const visible = WS.includes(ui.route) && ui.railTab === 'team' && ui.rail === 'chat' && ui.chatRole === r && railVisible();
      if (!visible) notify(T(PEOPLE[r].name + ' 回复了', PEOPLE[r].name + ' replied'), { lead: avatar(r, 'sm'), action: { label: T('查看', 'View'), run: () => openChat(r) } });
    }
  }
  // Approved requests change the conditions; mark them so the facts can light up once.
  const was = ui.lastWorld && ui.lastWorld.id === a.id ? ui.lastWorld : null;
  if (was && !first) { const keys = ['capacity', 'devDays', 'deadline'].filter(k => was[k] !== a.world[k]); if (keys.length) ui.changed = { keys, until: Date.now() + 4000 }; }
  ui.lastWorld = { id: a.id, capacity: a.world.capacity, devDays: a.world.devDays, deadline: a.world.deadline };
  for (const e of a.events.filter(x => x.server)) {
    if (a.eventTimes[e.seq] !== undefined) { if (e.createdAt) a.eventTimes[e.seq] = e.createdAt; continue; }
    a.eventTimes[e.seq] = e.createdAt || (first ? null : new Date().toISOString()); dirtyRecord = true;
    if (first) continue;
    const l = eventLine(a, e);
    if (l.announce) notify(l.text, l.announce === 'policy' ? { toast: true, lead: `<span class="toast-icon">${icon('bolt', 'i-sm')}</span>`, action: { label: T('看变化', 'See changes'), run: () => openMaterial('policy', true) } } : { toast: true, lead: `<span class="toast-icon">${icon(l.icon || 'info', 'i-sm')}</span>` });
  }
  if (!first || s.timeline.events.length || s.materials.length) ui.synced = ui.synced || (!!s.materials.length);
  if (dirtyRecord) persist();
}
const railVisible = () => window.matchMedia('(min-width: 1280px)').matches || ui.railOpen;
function markRead() {
  const a = current(); if (!a || !WS.includes(ui.route) || ui.railTab !== 'team' || ui.rail !== 'chat' || !ui.chatRole || !railVisible()) return;
  const n = (a.conversations[ui.chatRole] || []).filter(m => m.role !== 'user').length;
  a.readTurns = a.readTurns || {};
  if (a.readTurns[ui.chatRole] !== n) { a.readTurns[ui.chatRole] = n; persist(); }
}

/* ---------- workspace refresh ---------- */
function refreshWS(parts = ['toolbar', 'stage', 'rail']) {
  const a = current(); if (!a || !WS.includes(ui.route)) { render(); return; }
  // An asynchronous source reply must not tear down an active IME composition.
  if (parts.includes('stage') && ui.investigationComposing) {
    ui.investigationRefreshQueued = true; parts = parts.filter(p => p !== 'stage');
  }
  if (parts.includes('stage') && dirty) flush();
  ui.notesCache = Coach.notes(a, E);
  const key = focusKey();
  const ws = document.querySelector('.ws'); if (!ws) { render(); return; }
  const stage = document.getElementById('main'); const y = stage ? stage.scrollTop : 0;
  if (parts.includes('toolbar')) { const tb = document.getElementById('ws-toolbar'); if (tb) tb.outerHTML = wsToolbar(a); }
  if (parts.includes('stage')) { document.getElementById('ws-stage').innerHTML = wsStage(a); if (stage) stage.scrollTop = y; }
  if (parts.includes('rail')) { const rb = document.querySelector('#ws-rail .rail-body'); const ry = rb ? rb.scrollTop : 0; document.getElementById('ws-rail').innerHTML = wsRail(a); const nb = document.querySelector('#ws-rail .rail-body'); if (nb) nb.scrollTop = ry; }
  ws.classList.toggle('rail-open', ui.railOpen); ws.dataset.status = statusOf(a);
  afterRender();
  restoreFocus(key);
}
const narrowRail = () => window.matchMedia('(max-width: 1279px)').matches;
function syncPanels() {
  const rail = document.getElementById('ws-rail'); if (!rail) return;
  rail.inert = narrowRail() && !ui.railOpen;
  ['#main', '#ws-toolbar'].forEach(sel => { const el = document.querySelector(sel); if (el) el.inert = narrowRail() && ui.railOpen; });
}

/* ---------- actions ---------- */
function ensureArtifact() {
  const a = current(); const t = task();
  if (!t) return null;
  let x = artifact();
  if (x && x.taskId === t.id && !isEarlier(a, x) && x.adopted) return x;
  x = a.artifacts.filter(y => y.taskId === t.id && !y.removedAt && !isEarlier(a, y) && y.adopted).at(-1);
  if (!x) x = E.createArtifact(a, { taskId: t.id, title: T('关于「' + taskTitle(t) + '」的记录', 'Notes on “' + taskTitle(t) + '”'), purpose: '探索笔记', body: '' });
  ui.artifactId = x.id; ui.obj = { task: t.id, type: 'work', id: x.id }; return x;
}
function cite(ev) {
  const a = current(); const x = ensureArtifact();
  if (!x) {
    ui.pendingCite = ev;
    openSheet(T('加到哪件事', 'Add it to which task?'), `<div class="pick-list">${a.tasks.map(t => `<button type="button" class="pick-row" data-action="cite-into" data-id="${t.id}">${priMark(t.priority)}<span class="grow">${esc(taskTitle(t))}</span>${icon('chev', 'i-xs')}</button>`).join('')}</div>`, '', 'narrow');
    return;
  }
  try { E.addEvidence(a, x.id, ev); persist(); closeSheet(true); notify(T('已加入「' + shown(x).title + '」的依据', 'Added to the evidence for “' + shown(x).title + '”')); }
  catch (err) { notify(errText(err)); }
}
function attachToTurn(a, item) {
  const s = sessionOf(a), role = ROLE_ID[ui.chatRole]; if (!s || !role) return false;
  const context = s.turnContexts?.[role] || {};
  const attachments = (context.attachments || []).filter(x => !(x.type === item.type && x.id === item.id));
  if (attachments.length >= 10) { notify(T('每条消息最多附上 10 个对象。', 'Attach up to 10 items per message.')); return false; }
  return L.store.update(a.id, { turnContexts: { ...s.turnContexts, [role]: { ...context, attachments: [...attachments, item] } } });
}
function openChat(role, prefill = '') {
  const a = current(); ui.railTab = 'team'; ui.rail = 'chat'; ui.chatRole = role; ui.menu = null;
  if (narrowRail()) ui.railOpen = true;
  if (!WS.includes(ui.route)) { go('work'); } else refreshWS(['rail', 'toolbar']);
  if (a) markRead();
  const input = document.getElementById('chat-input'); if (input) { if (prefill) { input.value = prefill; input.dispatchEvent(new Event('input', { bubbles: true })); } input.focus(); }
}
// Inside a task a document opens beside the work; from the board it opens on its own page.
async function openMaterial(id, compare = false) {
  const a = current(); if (!a) return;
  commit(); ui.menu = null; ui.compare = compare;
  const m = E.getMaterials(a).find(x => x.id === id);
  if (m) a.acks = [...new Set([...(a.acks || []), 'read-' + id + '-v' + m.version])];
  const t = routeTask(a);
  if (t) { t.docs = [...new Set([...(t.docs || []), id])]; ui.obj = { task: t.id, type: 'doc', id }; persist(); refreshWS(['stage', 'toolbar']); }
  else { persist(); go('doc', { id }); }
  // Reading is a counted business action on the server; record the first read of each version only.
  const readKey = id + '@' + (m ? m.version : 0);
  a.readSent = Array.isArray(a.readSent) ? a.readSent : [];
  if (!a.readSent.includes(readKey)) {
    try { await L.read(a, id); a.readSent.push(readKey); persist(); } catch (err) { notify(errText(err)); }
  }
  if (m && m.version > 1 && !ui.previous[id]) {
    try { const hist = await L.history(a, 0); const prev = hist.find(x => x.id === id && x.version < m.version); if (prev) { ui.previous[id] = { version: prev.version, content: prev.content }; refreshWS(['stage']); } }
    catch (_) { /* comparison stays unavailable */ }
  }
}
function openTask(id, obj) {
  const a = current(); if (!a) return; commit();
  a.selectedTaskId = id; ui.obj = obj ? { task: id, ...obj } : null; persist();
  if (ui.route === 'task' && ui.routeId === id) { refreshWS(['stage', 'toolbar', 'rail']); return; }
  go('task', { id, transition: true });
}
function flip(mutate) {
  const sel = '.kanban .card';
  const before = new Map([...document.querySelectorAll(sel)].map(el => [el.dataset.taskId, el.getBoundingClientRect()]));
  mutate();
  if (reduceMotion.matches) return;
  document.querySelectorAll(sel).forEach(el => {
    const b = before.get(el.dataset.taskId);
    if (!b) { el.animate([{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'none' }], { duration: 300, easing: 'cubic-bezier(.32,.72,0,1)' }); return; }
    const r = el.getBoundingClientRect(); const dx = b.left - r.left; const dy = b.top - r.top;
    if (dx || dy) el.animate([{ transform: `translate(${dx}px,${dy}px)` }, { transform: 'none' }], { duration: 420, easing: 'cubic-bezier(.32,.72,0,1)' });
  });
}
function moveWithUndo(a, id, to, message) {
  let before;
  flip(() => { before = E.moveTask(a, id, to); persist(); refreshWS(['stage', 'toolbar']); });
  notify(message, { undo: () => { flip(() => { E.restoreOrder(a, before); persist(); refreshWS(['stage']); }); } });
}
function download(data, name) { const blob = new Blob([typeof data === 'string' ? data : JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
function resetAttemptUi() { Object.assign(ui, { obj: null, artifactId: null, rail: 'team', railTab: 'team', chatRole: null, railOpen: false, menu: null, advice: null, scopeAll: false, benchAll: false, reviewFor: null, pendingRequestId: null, lastUndo: null, compare: false, editPending: null, lastRun: null, reviewTab: 'rules' }); }
async function startAttempt(caseId, opts) {
  const a = await L.start(caseId, opts);
  ui.arriving = true; a.selectedTaskId = null; a.readTurns = {}; a.turnTimes = {}; a.eventTimes = {}; a.turnTask = {};
  resetAttemptUi(); persist();
  return a;
}
async function enterWork(fn) { await fn(); withTransition(() => { if (sheet.open) closeSheet(true); ui.route = 'work'; ui.routeId = null; history.pushState(null, '', hashOf('work')); render(); window.scrollTo(0, 0); }); }
async function runQuestion(question, expectation) {
  if (ui.busy) return; const a = current(); ui.busy = true; ui.labPrefill = ''; refreshWS(['stage']);
  try { const t = task(); const run = await L.test(a, { question, expectation, taskId: t ? t.id : null }); ui.lastRun = run.id; startWorking(a, t); persist(); announce(T('知识助手回答：', 'The assistant answered: ') + run.answer); }
  catch (err) { notify(errText(err)); }
  finally { ui.busy = false; if (WS.includes(ui.route) && current() === a) { const t = task(); if (t) ui.obj = { task: t.id, type: 'bench' }; refreshWS(); document.getElementById('run-' + ui.lastRun)?.scrollIntoView({ block: 'nearest', behavior: reduceMotion.matches ? 'auto' : 'smooth' }); } }
}
function pkgFor(a, record) {
  const t = task(); const sc = ui.exportScope;
  if (!ui.pendingRequestId) ui.pendingRequestId = 'request-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
  const scope = { record, requestId: ui.pendingRequestId };
  if (record) setTimeout(() => { ui.pendingRequestId = null; }, 0);
  if (!sc.artifacts) scope.artifactIds = [];
  if (!sc.materials) scope.materialIds = ['brief'];
  if (!sc.tests) scope.testIds = [];
  return E.preparePackage(a, t ? t.id : null, scope);
}
// Agents may answer with English purpose names; store them as the engine's values.
function normalizeImport(text) {
  try { const data = JSON.parse(text); const art = data.artifact || data; if (art && art.purpose) art.purpose = purposeFromLabel(art.purpose); return JSON.stringify(data); }
  catch (_) { return text; }
}
function setObj(obj) { const t = task(); if (!t) return; commit(); ui.obj = { task: t.id, ...obj }; if (obj.type === 'work') ui.artifactId = obj.id; refreshWS(['stage', 'rail']); document.getElementById('ws-object')?.scrollIntoView?.({ block: 'start' }); }

async function act(el) {
  const a = current(); const id = el.dataset.id; const action = el.dataset.action;
  if (action !== 'menu' && action !== 'set-lang' && action !== 'show-advice' && ui.menu) { ui.menu = null; if (WS.includes(ui.route)) refreshWS(['toolbar', 'stage']); else render(); }
  switch (action) {
    case 'investigate-run': openInvestigation(id); break;
    case 'investigation-retest': await runInvestigationBlock(id); break;
    case 'investigation-refresh-index': {
      if(ui.busy)break; commit(); const x=artifact(),b=x?.blocks?.find(b=>b.id===id),r=b&&a.tests.find(t=>t.id===b.testId);
      requireWorkMutation(a,x);
      if(x?.kind!=='investigation'||!x.adopted||b?.type!=='retest'||!r?.citations?.some(c=>c.id==='policy')||!canWrite(a))throw new Error(T('这份调查当前不能刷新索引。','The index cannot be refreshed from this investigation right now.'));
      if(x.draft||storageIssue||!persist())throw new Error(T('先保存调查判断，再刷新索引。','Save your investigation notes before refreshing the index.'));
      ui.busy=true;refreshWS(['stage']);
      try {await L.action(a,'refresh_index');persist();notify(T('索引已更新；可在这份调查里同题重测。','Index refreshed. Rerun the question in this investigation.'));}
      finally {ui.busy=false;refreshWS(['stage','rail']);}
      break;
    }
    case 'investigation-mode': { const x=artifact(); if(!x||x.kind!=='investigation'||!x.blocks.some(b=>b.id===id))break; const mode=el.dataset.mode; if(!['diff','original'].includes(mode))break; investigationViewState(a,x).modes[id]=mode; refreshWS(['stage']); break; }
    case 'investigation-review-save': { const x=artifact(); requireWorkMutation(a,x); if(x.kind!=='investigation')break; commit(); if(x.draft||!persist())throw new Error(T('判断尚未保存，请保留页面并检查提示。','Your notes have not been saved. Keep this page open and check the message.')); refreshWS(['stage','rail']); notify(T('你的调查判断已保存','Your investigation notes are saved')); break; }
    case 'investigation-load': {const x=artifact(),b=x?.blocks?.find(b=>b.id===id);if(b){delete ui.investigationSources[investigationSourceKey(a.id,b)];loadInvestigationSources(a,x,id);refreshWS(['stage']);}break;}
    case 'investigation-move': {commit();const x=artifact();requireWorkMutation(a,x);const i=x.blocks.findIndex(b=>b.id===id),dir=Number(el.dataset.dir),before=dir<0?x.blocks[i-1]?.id:x.blocks[i+2]?.id;if(i<0||i+dir<0||i+dir>=x.blocks.length)break;localWorkChange(a,()=>E.moveInvestigationBlock(a,x.id,id,before));refreshWS(['stage']);announce(T('模块顺序已保存','Module order saved'));break;}
    case 'investigation-cite': {commit();const x=artifact(),r=a.tests.find(r=>r.id===id);requireWorkMutation(a,x);if(!x.adopted)throw new Error(T('先采用这份调查，再引用结果。','Adopt this investigation before citing results.'));if(r){E.addEvidence(a,x.id,{type:'test',id:r.id,version:r.configVersion});if(!persist())throw new Error(storageText());refreshWS(['stage','rail']);notify(T('这次运行已加入调查依据','This run is now evidence for the investigation'));}break;}
    case 'work-edit': { const x = artifact(); requireWorkMutation(a,x); ui.previewWorkId = null; ui.editPending = x.id; refreshWS(['stage']); document.getElementById('editor-body')?.focus(); break; }
    case 'work-preview': commit(); ui.previewWorkId = id; refreshWS(['stage']); if(ui.kbd) document.querySelector('[data-work-mode]')?.focus({preventScroll:true}); break;
    case 'save-work': { const x = artifact(); requireWorkMutation(a,x); commit(); if (x.draft || !persist()) throw new Error(T('修改尚未保存，请保留页面并检查提示。','Changes have not been saved. Keep this page open and check the message.')); refreshWS(['stage','rail']); notify(x.adopted ? T('修改已保存','Changes saved') : T('修改已保存，仍为待检查作品','Changes saved; still awaiting adoption')); break; }
    case 'removed-works': commit(); removedWorksSheet(); break;
    case 'remove-work': { const x = artifact(); requireWorkMutation(a,x); commit(); if (x.draft || !persist()) throw new Error(T('请先保存修改。','Save your changes first.')); openSheet(T('删除这份作品？','Remove this work?'), `<p class="work-remove-title">${esc(shown(x).title)}</p><p class="work-remove-note">${T('移入“已移除作品”，随时可以恢复。原文件和已保存的测试记录会保留。','Move it to Removed work. You can restore it later. The original file and saved test runs are kept.')}</p>${x.adopted && sessionOf(a)?.draft.rationale ? `<p class="work-remove-note">${T('交付稿中已有文字：自动汇总会更新，手写修改会保留并提示核对；已保存的交付版本不会撤回。','The deliverable already has text. Generated summaries will update; edited text stays for review. Saved deliverable versions are not withdrawn.')}</p>`:''}`, `${btn(T('保留','Keep'),'close','quiet')}<span class="spacer"></span>${btn(T('删除作品','Remove work'),'confirm-remove-work','primary',`data-id="${x.id}"`)}`, 'narrow'); break; }
    case 'confirm-remove-work': { const x = a.artifacts.find(w=>w.id===id); requireWorkMutation(a,x); if (sessionOf(a)?.pending?.localRun?.workId === id || sessionOf(a)?.pending?.localRun?.investigationId === id) throw new Error(T('先确认这份作品的运行结果，再删除。','Resolve this work’s pending run before removing it.')); commit(); if (x.draft) throw new Error(T('请先保存修改。','Save your changes first.')); const before=sessionOf(a).draft.rationale; const selected=ui.deliverPick ? new Set(ui.deliverPick) : new Set(works(a).map(w=>w.id)); const wasGenerated=!!before && selected.has(id) && before===rationaleFrom(a,selected); localWorkChange(a,()=>{ E.removeArtifact(a,id); if(x.adopted && before) a.deliverRemovalNotice=true; }); if(wasGenerated) { const ss=sessionOf(a); if(L.store.update(a.id,{draft:{...ss.draft,rationale:rationaleFrom(a,selected)}})) { a.deliverRemovalNotice=false; persist(); } } const name=shown(x).title; ui.artifactId=null; ui.previewWorkId=null; ui.editPending=null; ui.reviewFor=null; closeSheet(true); const t=task(); if(t) ui.obj=defaultObj(a,t); refreshWS(); notify(T('已移除《'+name+'》','Removed “'+name+'”'), {undo:()=>restoreWork(a,id)}); break; }
    case 'restore-work': restoreWork(a,id); break;
    case 'test-toggle': { commit(); const x = artifact(); if (!x) break; const open = ui.testOpen[x.id] === undefined ? null : ui.testOpen[x.id]; ui.testOpen[x.id] = open === id ? null : id; refreshWS(['stage']); if (ui.testOpen[x.id]) animateTestReveal(id); break; }
    case 'test-run': await runTestCase(id); break;
    case 'test-mode': commit(); ui.testModes[id] = el.dataset.mode; refreshWS(['stage']); animateTestReveal(id); break;
    case 'test-add': { commit(); const x = artifact(); if (!x || statusOf(a) !== 'active' || storageIssue) break; const c = E.addTestCase(a, x.id); ui.testOpen[x.id] = c.id; persist(); refreshWS(['stage']); animateTestReveal(c.id); document.getElementById('case-question-' + c.id)?.focus({ preventScroll: true }); break; }
    case 'test-remove': { commit(); const x = artifact(); if (!x || statusOf(a) !== 'active' || storageIssue) break; E.removeTestCase(a, x.id, id); ui.testOpen[x.id] = x.cases[0]?.id ?? null; persist(); refreshWS(['stage']); notify(T('问题已移除，历史测试仍保留', 'Question removed. Its test history is kept.'), { undo: () => { if (statusOf(a) !== 'active' || storageIssue) return; E.restoreTestCase(a, x.id, id); persist(); ui.testOpen[x.id] = id; refreshWS(['stage']); } }); break; }
    case 'test-cite': { commit(); const x = artifact(), run = a.tests.find(r => r.id === id); if (!x || !run || run.workId !== x.id || statusOf(a) !== 'active' || !x.adopted || storageIssue) break; E.addEvidence(a, x.id, { type: 'test', id: run.id, version: run.configVersion }); if (!persist()) throw new Error(storageText()); refreshWS(['stage','rail']); notify(T('这次运行已加入计划依据', 'This run is now evidence for the plan.')); break; }
    case 'test-ref': { const m = E.getMaterials(a).find(m=>m.id===id); if (!m) throw new Error(T('当前会话没有这份资料。','This document is not available in this session.')); const v = Number(el.dataset.version); openSheet(materialTitle(m), `<p class="meta">${T('计划引用 v','Plan references v')}${v} · ${T('当前可见 v','Currently visible v')}${m.version}</p>${v!==m.version?`<p class="warn-line">${T('材料已变化，下面显示当前版本。','The document changed. The current version is shown below.')}</p>`:''}<div class="prose serif">${md(m.content || m.body)}</div>`, btn(T('好','OK'),'close','primary'),'wide'); break; }
    case 'test-export': { commit(); const x = artifact(); if (!x) break; download({ schemaVersion: 1, returnId: 'export-' + crypto.randomUUID(), artifact: { kind: 'test_set', title: x.title, purpose: x.purpose, body: x.body, cases: x.cases.map(({question,intent,expectation,refs})=>({question,intent,expectation,refs})) } }, 'test-plan.json'); break; }

    case 'home': go('', { transition: true }); break;
    case 'open-career': go('pm', { transition: true }); break;
    case 'set-lang': ui.menu = null; setPreference(el.dataset.lang, localStorage); render(); break;
    case 'start-intake': { const r = ui.intake.result; await enterWork(() => startAttempt('pilot', { intake: { text: r.text, fits: r.fits, gaps: r.gaps } })); break; }
    case 'practice-variant': { const caseId = el.dataset.case; const parent = a ? a.id : null; await enterWork(() => startAttempt(caseId, parent ? { parentAttemptId: parent } : undefined)); break; }
    case 'close': closeSheet(); break;
    case 'about': sheetAbout(); break;
    case 'export': download(storageLocked && rawRecord ? rawRecord : state, storageLocked && rawRecord ? 'practice-original-record.json' : 'practice-local-notes.json'); notify(T('已交给浏览器下载', 'Handed to the browser to download')); break;
    case 'reset-storage': try { localStorage.setItem(KEY + '.bak', rawRecord); storageLocked = false; storageIssue = ''; rawRecord = null; persist(); render(); notify(T('原记录已另存，可以重新开始了', 'The original record is backed up. You can start fresh.')); } catch (_) { notify(T('浏览器不允许保存，没能另存', 'The browser blocked saving the backup.')); } break;
    case 'set-status': { const t = a.tasks.find(x => x.id === id); if (t && t.status !== el.dataset.status) { E.updateTask(a, id, { status: el.dataset.status }); persist(); refreshWS(['stage']); } break; }
    case 'new-task': sheetTask(); break;
    case 'edit-task': sheetTask(id); break;
    case 'move-task': { const t = a.tasks.find(x => x.id === id); const i = a.tasks.indexOf(t); const dir = Number(el.dataset.dir); const target = a.tasks[i + dir]; if (!target) { notify(T('已经到头了', 'Already at the end')); break; } closeSheet(true); moveWithUndo(a, id, dir < 0 ? { priority: target.priority, beforeId: target.id } : { priority: target.priority, beforeId: a.tasks[i + 2] ? a.tasks[i + 2].id : null }, T('已调整顺序', 'Order changed')); break; }
    case 'edit-pending': if (a.artifacts.find(w=>w.id===id)?.kind === 'test_set' && (statusOf(a) !== 'active' || storageIssue)) break; ui.editPending = id; refreshWS(['stage']); (document.querySelector('[data-case-field]') || document.getElementById('editor-body'))?.focus(); break;
    case 'cite-pick': sheetCitePicker(); break;
    case 'view-evidence': { const x = artifact(); const ev = x && x.evidence.find(e => e.id === id && String(e.version ?? '') === el.dataset.version); if (ev) openSheet(esc(evTitle(ev)), `<p class="meta">${T('引用时保存的内容', 'Saved when you cited it')}${ev.version ? ' · v' + esc(ev.version) : ''}</p><div class="prose serif quoteblock"${zhAttr(ev.body)}>${md(ev.body || '')}</div>`, btn(T('好', 'OK'), 'close', 'primary'), 'narrow'); break; }
    case 'run-source': {
      const run=a.tests.find(r=>r.id===el.dataset.run); if(!run) break;
      const sources=await Promise.allSettled(run.citations.map(c=>L.citationSource(a,run.id,c.id)));
      openSheet(T('这次回答用的来源','Sources behind this answer'),`<div class="answer">${assistantMark('sm')}<div class="answer-body">${md(run.answer,{dropTitle:true})}</div></div>${run.citations.map((c,i)=>{const result=sources[i].status==='fulfilled'?sources[i].value:null;const m=result?.material;return `<article class="paper document small"><header class="doc-head">${icon('doc','i-sm')}<h3 class="doc-title">${esc(materialTitle(m||{id:c.id,title:c.title}))}</h3><span class="stamp">v${c.version}</span></header>${m?`<div class="prose serif">${md(m.content,{dropTitle:true})}</div>`:`<p class="muted">${T('本次引用 v'+c.version+'；这个版本的正文暂未取得。','This run cited v'+c.version+'. Its exact text is unavailable.')}</p>`}</article>`;}).join('')}`,btn(T('好','OK'),'close','primary'),'wide');
      break;
    }
    case 'rerun': { const r = a.tests.find(x => x.id === id); if (r) await runQuestion(r.question, r.expectation); break; }
    case 'config': ui.configFromTestSet = ['test_set','investigation'].includes(artifact()?.kind) && ui.obj?.type === 'work'; closeSheet(true); ui.menu = null; sheetConfig(); break;
    case 'resend-turn': { const s = sessionOf(a); const op = s?.failedTurn; if (op) { await L.turn(a, ROLE_OF[op.body.role_id], String(op.body.text), { ...(op.body.task_id !== undefined ? { task_id: op.body.task_id } : {}), ...(op.body.work_id !== undefined ? { work_id: op.body.work_id } : {}), ...(op.body.attachments ? { attachments: op.body.attachments } : {}) }); L.store.update(a.id, { failedTurn: undefined }); refreshWS(['rail']); } break; }
    case 'discuss-run': { const r = a.tests.find(x => x.id === id); openChat('technical', T(`我测了“${r.question}”，助手答“${answerText(r.answer).slice(0, 300)}”（政策源 v${r.policyVersion}，索引 v${r.indexVersion}）。我想确认：`, `I asked “${r.question}” and the assistant said “${answerText(r.answer).slice(0, 300)}” (policy v${r.policyVersion}, index v${r.indexVersion}). I want to check: `)); break; }
    case 'prefill-artifact': { const x = artifact(); const input = document.getElementById('chat-input'); if (input && x) { if (!attachToTurn(a, { type: 'work', id: x.id, version: x.revision })) break; const v = shown(x); input.value = T(`这是我的「${v.title}」：\n${v.body.slice(0, 1500)}\n\n`, `Here is my “${v.title}”:\n${v.body.slice(0, 1500)}\n\n`) + input.value; input.dispatchEvent(new Event('input', { bubbles: true })); input.focus(); } break; }
    case 'prefill-run': { const r = a.tests.at(-1); const input = document.getElementById('chat-input'); if (input && r) { if (!attachToTurn(a, { type: 'test', id: r.id, version: r.configVersion })) break; input.value = T(`最近一次测试：“${r.question}” → “${answerText(r.answer).slice(0, 300)}”。`, `Latest test: “${r.question}” → “${answerText(r.answer).slice(0, 300)}”. `) + input.value; input.dispatchEvent(new Event('input', { bubbles: true })); input.focus(); } break; }
    case 'package': openSheet(T('任务包', 'Task package'), `<p class="meta">${T('这是会交给你的 Agent 的内容，不含任何连接凭据。', 'This is what your agent receives. It contains no credentials.')}</p><label class="sr-only" for="package-text">${T('任务包内容', 'Package content')}</label><textarea id="package-text" class="textarea mono" rows="16" readonly>${esc(JSON.stringify(pkgFor(a, false), null, 2))}</textarea>`, `${btn(T('关闭', 'Close'), 'close', 'quiet')}<span class="spacer"></span>${btn(T('复制并记为已导出', 'Copy and mark as handed over'), 'copy-package', 'primary')}`, 'wide'); break;
    case 'copy-package': { const pkg = pkgFor(a, true); persist(); closeSheet(true); try { await navigator.clipboard.writeText(JSON.stringify(pkg, null, 2)); notify(T('任务包已复制，记为已导出', 'Package copied and marked as handed over')); } catch (_) { notify(T('浏览器不允许自动复制；已记为导出，可在“查看”里手动复制', 'The browser blocked copying. It is marked as handed over; copy it from Preview.')); } refreshWS(['rail']); break; }
    case 'download-package': download(pkgFor(a, true), 'practice-task.json'); persist(); notify(T('任务包已交给浏览器下载', 'Package handed to the browser to download')); refreshWS(['rail']); break;
    case 'submit': commit(); sheetDeliver(); break;
    case 'live-refresh': await L.refresh(a); refreshChrome(); notify(snap().connected ? T('已连接', 'Connected') : T('还是连不上后端', 'Still cannot reach the server')); break;
    case 'live-retry': { const meta = sessionOf(a)?.pending?.localRun; await L.retry(a); if(meta?.investigationId && meta?.blockId){if(snap().error)ui.investigationErrors[meta.blockId]=snap().error;else if(!sessionOf(a)?.pending)delete ui.investigationErrors[meta.blockId];}
      if (meta?.caseId) { ui.testOpen[meta.workId] = meta.caseId; ui.testModes[meta.caseId] = 'result'; if (snap().error) ui.testErrors[meta.caseId] = snap().error; else if (!sessionOf(a)?.pending) { delete ui.testErrors[meta.caseId]; const restored = a.tests.find(r=>r.requestId===meta.requestId); if (restored) ui.testHistory[meta.caseId] = restored.id; } } refreshChrome(); if (meta?.caseId || meta?.investigationId) refreshWS(['stage']); break; }
    case 'live-session': { closeSheet(true); if (statusOf(a) === 'submitted') { go('review'); break; } await L.action(a, statusOf(a) === 'paused' ? 'resume' : 'pause'); refreshWS(); break; }
    case 'live-approval': try { await L.perform(a, () => L.store.approval(el.dataset.id)); } finally { sheetResources(); refreshWS(); } break;
    case 'live-collect': { a.deliverRemovalNotice=false; persist(); commit(); const f = document.getElementById('live-deliver'); if (f) saveDraftFields(a, f); deliverPick(a); L.store.update(a.id, { draft: { ...sessionOf(a).draft, rationale: rationaleFrom(a, ui.deliverPick) } }); sheetDeliver(); break; }
    case 'live-save': { const f = document.getElementById('live-deliver'); if (f) saveDraftFields(a, f); await L.save(a, sessionOf(a).draft); sheetDeliver(); notify(T('交付稿已保存', 'Deliverable saved')); break; }
    case 'live-submit': {
      await L.submit(a); if (!L.store.submissionId(sessionOf(a))) throw new Error(T('还没得到提交确认。', 'The submission has not been confirmed yet.'));
      a.submittedAt = sessionOf(a).submission?.created_at || new Date().toISOString(); ui.justSubmitted = a.id; persist();
      closeSheet(true); go('review', { transition: true }); await L.feedback(a); render(); break;
    }
    case 'review-works': sheetDeliver(true); break;
    case 'live-feedback': toastEl.classList.remove('visible'); await L.feedback(a, el.dataset.retry === 'true'); render(); break;
    case 'live-evidence': {
      const value = await L.evidence(a, el.dataset.criterion, id);
      openSheet(esc(evidenceLabel(a, sessionOf(a).feedback, id)), evidenceView(a, value), btn(T('好', 'OK'), 'close', 'primary'), 'narrow'); break;
    }
    case 'live-timeline': {
      ui.menu = null; await L.store.sync(a.id);
      const events = sessionOf(a).timeline.events.slice().reverse();
      openSheet(T('过程记录', 'Activity log'), `<ol class="log-list">${events.map(e => { const l = eventLine(a, { server: true, type: e.event_type, detail: { ...e.payload, materialId: e.payload.material_id }, seq: e.seq, actor: e.actor_id }); return `<li>${icon(l.icon || 'info', 'i-sm')}<span class="grow">${esc(l.text)}</span><span class="meta">#${e.seq}</span></li>`; }).join('') || `<li class="muted">${T('还没有记录。', 'Nothing yet.')}</li>`}</ol>`, btn(T('好', 'OK'), 'close', 'primary'), 'narrow');
      break;
    }
    case 'take-case': {
      const caseId = el.dataset.case; const card = el.closest('.case-hero, .variant');
      const triage = card ? [...card.querySelectorAll('select[data-change="triage"]')].map(x => x.value) : [];
      await enterWork(async () => { const na = await startAttempt(caseId); triage.forEach((p, i) => { if (na.tasks[i] && p !== na.tasks[i].priority) E.updateTask(na, na.tasks[i].id, { priority: p }); }); const order = { first: 0, next: 1, later: 2 }; na.tasks.sort((x, y) => order[x.priority] - order[y.priority]); persist(); });
      break;
    }
    case 'menu': { const m = el.dataset.menu; ui.menu = ui.menu === m ? null : m; if (WS.includes(ui.route)) refreshWS(['toolbar', 'stage']); else render(); if (ui.kbd) document.querySelector('.menu button, .popover .btn')?.focus(); break; }
    case 'resume': await L.refresh(a); resetAttemptUi(); go('work', { transition: true }); break;
    case 'resume-attempt': commit(); state.activeId = id; L.select(current()); await L.refresh(current()); resetAttemptUi(); persist(); go('work', { transition: true }); break;
    case 'review-attempt': commit(); state.activeId = id; L.select(current()); await L.refresh(current()); resetAttemptUi(); persist(); go('review', { transition: true }); break;
    case 'to-entry': go('pm', { transition: true }); break;
    case 'to-board': case 'to-work': go('work', { transition: true }); break;
    case 'to-review': go('review', { transition: true }); break;
    case 'open-rail': ui.railOpen = true; refreshWS(['toolbar', 'rail']); if (ui.kbd) document.querySelector('#ws-rail button')?.focus(); break;
    case 'close-panels': ui.railOpen = false; refreshWS(['toolbar']); break;
    case 'rail': ui.railTab = 'team'; ui.rail = el.dataset.rail; if (narrowRail()) ui.railOpen = true; refreshWS(['rail']); break;
    case 'rail-tab': ui.railTab = el.dataset.tab; if (el.dataset.tab !== 'team') ui.rail = 'team'; if (narrowRail()) ui.railOpen = true; refreshWS(['rail', 'toolbar']); break;
    case 'scope': ui.scopeAll = el.dataset.all === '1'; refreshWS(['rail']); break;
    case 'bench-scope': ui.benchAll = el.dataset.all === '1'; refreshWS(['stage']); break;
    case 'open-task': openTask(id); break;
    case 'obj': if (el.dataset.type === 'doc') { commit(); await openMaterial(el.dataset.id); } else setObj({ type: el.dataset.type, id: el.dataset.id }); break;
    case 'open-doc': case 'open-material': await openMaterial(id, el.dataset.compare === '1'); break;
    case 'open-bench': { const t = task(); if (t) setObj({ type: 'bench' }); else go('bench', { transition: true }); break; }
    case 'pick-doc': { const docs = E.getMaterials(a); openSheet(T('打开一份资料', 'Open a document'), `<div class="pick-list">${docs.map(m => `<button type="button" class="pick-row" data-action="open-doc" data-id="${esc(m.id)}">${icon('doc', 'i-sm')}<span class="grow">${esc(materialTitle(m))}</span><span class="ver">v${m.version}</span></button>`).join('')}</div>`, '', 'narrow'); break; }
    case 'toggle-done': { const t = a.tasks.find(x => x.id === id); if (!t) break; const before = t.status; const next = before === 'done' ? 'open' : 'done'; E.updateTask(a, id, { status: next }); persist(); refreshWS(['stage']); notify(next === 'done' ? T('「' + taskTitle(t) + '」已处理', '“' + taskTitle(t) + '” is done') : T('「' + taskTitle(t) + '」重新打开', '“' + taskTitle(t) + '” reopened'), { undo: () => { E.updateTask(a, id, { status: before }); persist(); refreshWS(['stage']); } }); break; }
    case 'show-advice': ui.menu = null; ui.advice = el.dataset.role; refreshWS(['stage']); break;
    case 'close-advice': ui.advice = null; refreshWS(['stage']); break;
    case 'apply-advice': { const adv = Coach.advice(a, ui.advice); if (!adv.items.length) break; let before; flip(() => { before = E.applySuggestion(a, { roleId: adv.roleId, items: adv.items }); ui.advice = null; persist(); refreshWS(['stage']); }); notify(T('已按 ' + adv.name + ' 的看法排列', 'Arranged the way ' + adv.name + ' sees it'), { undo: () => { flip(() => { E.restoreOrder(a, before); persist(); refreshWS(['stage']); }); } }); break; }
    case 'ask-rank': { ui.menu = null; ui.advice = null; const list = a.tasks.map(t => taskTitle(t)).join(T('；', '; ')); openChat(el.dataset.role, T('这是我手头的事项：' + list + '。你觉得我该先弄清哪件，为什么？', 'Here is what I have on my plate: ' + list + '. What would you tackle first, and why?')); break; }
    case 'situation-task': { const v = a.world.policyVersion; const st = situationTask(); const t = E.addTask(a, { title: st.title, note: st.note, priority: 'next' }); t.origin = 'situation'; a.acks = [...(a.acks || []), 'policy-v' + v]; persist(); openTask(t.id); break; }
    case 'ack': a.acks = [...new Set([...(a.acks || []), el.dataset.key])]; persist(); refreshWS(['stage', 'rail', 'toolbar']); break;
    case 'reply-note': { const n = (ui.notesCache || []).find(x => x.key === el.dataset.key); if (!n) break; a.acks = [...new Set([...(a.acks || []), 'note:' + n.key])]; persist(); openChat(n.role, T(`关于你说的“${n.text.slice(0, 60)}${n.text.length > 60 ? '…' : ''}”：`, `About what you said (“${n.text.slice(0, 60)}${n.text.length > 60 ? '…' : ''}”): `)); break; }
    case 'new-artifact': sheetNewArtifact(); break;
    case 'open-artifact': { const x = a.artifacts.find(y => y.id === id); if (!x) break; if (x.removedAt) { removedWorksSheet(x.taskId); break; } if (task() && task().id === x.taskId) setObj({ type: 'work', id }); else openTask(x.taskId, { type: 'work', id }); break; }
    case 'adopt': { const x=a.artifacts.find(w=>w.id===id); requireWorkMutation(a,x); commit(); if(x.draft) throw new Error(T('请先保存修改。','Save your changes first.')); } if (a.artifacts.find(w=>w.id===id)?.kind === 'test_set' && (statusOf(a) !== 'active' || storageIssue)) throw new Error(T('这份计划当前只读。','This plan is read-only.')); E.adoptArtifact(a, id); persist(); refreshWS(); notify(T('已采用。里面的结论仍要你检查和验证。', 'Adopted. Its claims still need your checking.')); break;
    case 'toggle-compare': ui.compare = !ui.compare; refreshWS(['stage']); break;
    case 'cite-material': { const m = E.getMaterials(a).find(x => x.id === id); if (m) cite({ id: m.id, title: m.title, version: m.version, body: m.body, type: 'material' }); refreshWS(['stage']); break; }
    case 'cite-run': { const r = a.tests.find(x => x.id === id); if (r) cite({ id: r.id, title: r.question, version: r.configVersion, body: r.answer, type: 'test' }); refreshWS(['stage']); break; }
    case 'cite-into': { const ev = ui.pendingCite; ui.pendingCite = null; closeSheet(true); openTask(id); if (ev) setTimeout(() => cite(ev), 0); break; }
    case 'open-run': { const r = a.tests.find(x => x.id === id); ui.lastRun = id; if (r && r.taskId && (!task() || task().id !== r.taskId)) openTask(r.taskId, { type: 'bench' }); else if (task()) setObj({ type: 'bench' }); else if (ui.route !== 'bench') go('bench'); else refreshWS(['stage']); setTimeout(() => document.getElementById('run-' + id)?.scrollIntoView({ block: 'center', behavior: reduceMotion.matches ? 'auto' : 'smooth' }), 80); break; }
    case 'refresh-index': await L.action(a, 'refresh_index'); persist(); refreshWS(); notify(T('索引已更新到 v' + a.world.indexVersion + '，可以同题重测比较。', 'Index refreshed to v' + a.world.indexVersion + '. Run the same question again to compare.')); break;
    case 'resources': closeSheet(true); ui.menu = null; if (WS.includes(ui.route)) refreshWS(['toolbar']); sheetResources(); break;
    case 'chat': openChat(el.dataset.role); break;
    case 'discuss-artifact': { const x = artifact(); closeSheet(true); const v = x && shown(x); openChat(x && E.intentOf(v.purpose) === 'commit' ? 'manager' : 'business', v ? T(`这是我的「${v.title}」（${purposeLabel(v.purpose)}）：\n${v.body.slice(0, 1500)}\n\n想请你看看：`, `Here is my “${v.title}” (${purposeLabel(v.purpose)}):\n${v.body.slice(0, 1500)}\n\nCould you look at: `) : ''); break; }
    case 'discuss-material': { const m = E.getMaterials(a).find(x => x.id === id); const role = el.dataset.role || whoHas(m)[0] || 'business'; openChat(role, T(`我在看《${materialTitle(m)}》v${m.version}，想确认：`, `I am reading “${materialTitle(m)}” v${m.version}. I want to check: `)); break; }
    case 'agent': ui.railTab = 'agent'; if (narrowRail()) ui.railOpen = true; refreshWS(['rail', 'toolbar']); break;
    case 'request-review': { const x = artifact(); if (!x) { ui.railTab = 'feedback'; refreshWS(['rail']); break; } commit(); E.log(a, 'review_requested', '请求评审', { artifactId: x.id }); ui.reviewFor = x.id; ui.railTab = 'feedback'; ui.scopeAll = false; persist(); if (narrowRail()) ui.railOpen = true; refreshWS(['rail', 'toolbar']); notify(T('已对照记录整理反馈，见右侧“反馈”', 'Feedback drawn from the record is in the Feedback tab'), { toast: true }); break; }
    case 'fb-act': { const kind = el.dataset.act; const tid = el.dataset.task; closeSheet(true);
      if (kind === 'chat') { openChat(el.dataset.role); break; }
      if (kind === 'rerun') { const r = a.tests.find(x => x.id === id); ui.labPrefill = r ? r.question : ''; if (tid) openTask(tid, { type: 'bench' }); else go('bench'); break; }
      if (kind === 'lab') { if (tid) openTask(tid, { type: 'bench' }); else if (task()) setObj({ type: 'bench' }); else go('bench'); break; }
      if (kind === 'config') { sheetConfig(); break; }
      if (kind === 'resources') { sheetResources(); break; }
      if (kind === 'material') { if (ui.route === 'review') go('work'); await openMaterial(el.dataset.id); break; }
      if (kind === 'open-artifact') { const x = a.artifacts.find(y => y.id === id); if (x?.removedAt) removedWorksSheet(x.taskId); else if (x) openTask(x.taskId, { type: 'work', id }); break; }
      if (kind === 'new-decision') { const t = a.tasks.find(x => x.seed === 'decision') || a.tasks[0]; openTask(t.id, { type: 'start' }); setTimeout(() => sheetNewArtifact('试点决定'), 60); break; }
      break; }
    case 'dispute': ui.disputeOpen = ui.disputeOpen === el.dataset.key ? null : el.dataset.key; if (ui.route === 'review') render(); else refreshWS(['rail']); document.querySelector('.dispute textarea')?.focus(); break;
    case 'review-tab': ui.reviewTab = el.dataset.tab; render(); break;
    case 'confirm-import': {
      try {
        const t = task(); const parsed = E.validateImported(normalizeImport(ui.importText)); if ((statusOf(a) !== 'active' || storageIssue || snap().storageError)) throw new Error(T('这次练习只读或存储不可用，不能导入新作品。','This practice is read-only or storage is unavailable. New work cannot be imported.')); const res = E.importReturn(a, normalizeImport(ui.importText), t ? t.id : null);
        if (res.duplicate) { if(res.removed) { closeSheet(true); removedWorksSheet(); notify(T('这份回传已经移除，可以在这里恢复。','This return was removed. Restore it here.'), {toast:true}); } else notify(T('这份回传已经导入过了', 'This return was already imported')); break; }
        if (!res.artifact.taskId) res.artifact.taskId = (t || a.tasks[0]).id;
        startWorking(a, a.tasks.find(x => x.id === res.artifact.taskId));
        if (res.artifact.title === '外部 Agent 回传作品') res.artifact.title = T('外部 Agent 回传作品', 'Returned by my agent');
        ui.importText = ''; persist(); closeSheet(); openTask(res.artifact.taskId, { type: 'work', id: res.artifact.id }); notify(T('收到了，先检查再决定是否采用', 'Received. Check it before you adopt it.'));
      } catch (err) { notify(errText(err)); }
      break;
    }
  }
}
function saveDraftFields(a, form) {
  const draft = { ...sessionOf(a).draft };
  FIELDS.forEach(k => { const el = form.elements[k]; if (el) draft[k] = el.value; });
  L.store.update(a.id, { draft });
}
// Evidence as the reviewer saw it, rendered by kind rather than as raw JSON.
function evidenceView(a, value) {
  const v = value && typeof value === 'object' ? value : {};
  const c = v.content;
  const at = v.observed_at_seq != null ? `<p class="meta">${T('截至事件 #' + v.observed_at_seq, 'As of event #' + v.observed_at_seq)}</p>` : '';
  const kv = rows => `<dl class="kv">${rows.filter(r => r[1] !== undefined && r[1] !== '').map(([k, x]) => `<div><dt>${k}</dt><dd${zhAttr(String(x))}>${esc(String(x))}</dd></div>`).join('')}</dl>`;
  if (v.kind === 'config' && c && c.pilot) {
    const p = L.fromPilot(c.pilot);
    return at + kv([[T('试点人数', 'Users'), p.participants], [T('开放的知识', 'Knowledge'), p.domains.map(DOMAIN).join(' + ') || '—'], [T('更新方式', 'Updates'), UPDATE(p.update)], [T('兜底', 'Fallback'), FALLBACK(p.fallback)], [T('开发', 'Engineering'), p.workItems.map(WORK_ITEM).join(T('、', ', ')) || '—'], [T('计划上线日', 'Launch day'), p.launchDay]]);
  }
  if (v.kind === 'artifact' && c && c.content) return at + `<article class="paper deliverable small">${FIELDS.map(k => `<section class="field-doc"><h3>${FIELD(k)}</h3>${c.content[k] ? `<div class="prose serif"${zhAttr(c.content[k])}>${md(c.content[k])}</div>` : `<p class="muted">${T('（空）', '(empty)')}</p>`}</section>`).join('')}</article>`;
  if (v.kind === 'event' && c) {
    const res = c.resources || {}; const rules = c.applied_rules || [];
    const ruleName = r => ({ policy_updated: T('政策已更新', 'Policy updated'), capacity_approved: T('扩容已批准', 'More seats approved'), resources_approved: T('资源已批准', 'Resources approved') })[r] || r;
    return at + kv([[T('容量', 'Capacity'), res.capacity], [T('开发人日', 'Person-days'), res.dev_days], [T('上线期限', 'Deadline'), res.deadline_day != null ? T('第 ' + res.deadline_day + ' 天', 'Day ' + res.deadline_day) : ''], [T('已生效', 'In effect'), rules.map(ruleName).join(T('、', ', ')) || T('无', 'None')]]);
  }
  if (v.kind === 'test_result' && c) return at + `<div class="run-q"><span class="run-asker">${T('你问', 'You asked')}</span><h3${zhAttr(c.query)}>${esc(c.query)}</h3></div><div class="answer">${assistantMark('sm')}<div class="answer-body"${zhAttr(c.answer)}>${md(c.answer, { dropTitle: true })}</div></div><p class="meta">${T('配置 v' + c.config_version, 'Config v' + c.config_version)}</p>`;
  if (v.kind === 'document' && typeof c === 'string') return at + `<div class="prose serif"${zhAttr(c)}>${md(c, { dropTitle: true })}</div>`;
  return at + `<details class="raw" open><summary>${T('原始记录', 'Raw record')}</summary><pre>${esc(JSON.stringify(v, null, 2))}</pre></details>`;
}

/* ---------- events ---------- */
document.addEventListener('click', e => {
  if (ui.menu && !e.target.closest('.menu-wrap')) { ui.menu = null; if (WS.includes(ui.route)) refreshWS(['toolbar', 'stage']); else render(); }
  const el = e.target.closest('[data-action]'); if (!el || el.disabled) return;
  if (el.tagName === 'A') e.preventDefault();
  ui.kbd = e.detail === 0; document.documentElement.dataset.input = ui.kbd ? 'keyboard' : 'pointer';
  Promise.resolve(act(el)).catch(err => notify(errText(err) || T('这一步没有完成，内容还在。', 'That did not go through. Nothing was lost.')));
});
document.addEventListener('toggle', e => {
  const d=e.target;
  if(d.matches?.('details[data-intake]')) ui.intake.open=d.open;
  if(d.isConnected&&d.matches?.('.investigation-work details[data-key]')) {
    const a=current(),x=artifact(); if(a&&x?.kind==='investigation') investigationViewState(a,x).open[d.dataset.key]=d.open;
  }
},true);
document.addEventListener('compositionstart', e => { if(e.target.closest?.('.investigation-work')) ui.investigationComposing=true; });
document.addEventListener('compositionend', e => {
  const investigation=e.target.closest?.('.investigation-work');
  if(investigation) ui.investigationComposing=false;
  if(e.target.dataset&&(e.target.dataset.edit||e.target.dataset.caseField||e.target.dataset.investigationQuestion!==undefined||e.target.dataset.investigationReview)) e.target.dispatchEvent(new Event('input',{bubbles:true}));
  if(investigation&&ui.investigationRefreshQueued) { ui.investigationRefreshQueued=false; refreshWS(['stage']); }
});
document.addEventListener('input', e => {
  const el = e.target; const a = current();
  if (a && ['lab-q', 'lab-e', 'chat-input'].includes(el.id)) {
    const s = sessionOf(a); if (s) { const inputs = { ...s.inputs, messages: { ...s.inputs.messages } };
      if (el.id === 'lab-q') inputs.question = el.value;
      if (el.id === 'lab-e') inputs.expected = el.value;
      if (el.id === 'chat-input' && ui.chatRole) inputs.messages[ROLE_ID[ui.chatRole]] = el.value;
      L.store.update(a.id, { inputs }); }
  }
  if (a && el.form?.dataset.form === 'live-deliver' && FIELDS.includes(el.name)) { L.store.update(a.id, { draft: { ...sessionOf(a).draft, [el.name]: el.value } }); const live = document.querySelector('[data-action="live-submit"]'); if (live) live.disabled = true; const save = document.querySelector('[data-action="live-save"]'); if (save) save.classList.remove('quiet'); }
  if (e.isComposing) return;
  if(el.dataset.investigationReview && a) {
    const x=artifact(); if(!x||x.kind!=='investigation'||!canEditWork(a,x))return;
    const v=dirty?.attemptId===a.id&&dirty.id===x.id?dirty:shown(x);
    const key=el.dataset.investigationReview; if(!['focus','note'].includes(key))return;
    queueInvestigationDraft(a,x,{review:{...(v.review||{focus:'uncertain',note:''}),[key]:el.value}});return;
  }
  if (el.dataset.investigationQuestion !== undefined && a) {
    const x=artifact(); if(!x||x.kind!=='investigation'||!canEditWork(a,x))return;
    queueInvestigationDraft(a,x,{question:el.value});return;
  }
  if (el.dataset.caseField && a) {
    const x = artifact(); if (!x || x.kind !== 'test_set' || statusOf(a) !== 'active' || !(x.adopted || ui.editPending === x.id)) return;
    const v = dirty?.id === x.id ? dirty : shown(x); const cases = structuredClone(v.cases); const c = cases.find(c=>c.id===el.dataset.caseId); if (!c) return;
    c[el.dataset.caseField] = el.value;
    dirty = { attemptId:a.id, id:x.id, title:v.title, purpose:v.purpose, kind:'test_set', cases, body:E.testSetSummary({...v,cases}) };
    updateSave(); clearTimeout(saveTimer); saveTimer = setTimeout(flush, 450); return;
  }
  if (el.dataset.testNote && a) {
    const s = sessionOf(a), id = el.dataset.testNote;
    if (s && s.world.status === 'active') L.store.update(a.id, { testNotes: { ...s.testNotes, [id]: { ...(s.testNotes[id] || {expected:''}), diagnosis: el.value } } });
    return;
  }
  if (el.id === 'editor-body') autoGrow(el);
  if (el.id === 'import-content') ui.importText = el.value;
  if (el.id === 'intake-text') ui.intake.text = el.value;
  if (el.dataset.new !== undefined && a && el.dataset.new !== 'purpose') {
    const t = task(); const title = document.getElementById('new-title'); const body = document.getElementById('new-body');
    if (!t || !(title.value.trim() || body.value.trim())) return;
    const x = E.createArtifact(a, { taskId: t.id, title: title.value.trim() || T('我的初步想法', 'First thoughts'), purpose: document.querySelector('[data-new="purpose"]')?.value || '探索笔记', body: '' });
    startWorking(a, t);
    const caret = el.selectionStart; const focusTitle = el === title;
    if (body.value) x.draft = { title: x.title, purpose: x.purpose, body: body.value };
    ui.obj = { task: t.id, type: 'work', id: x.id }; ui.artifactId = x.id; persist(); refreshWS(['stage']);
    const next = document.getElementById(focusTitle ? 'editor-title' : 'editor-body'); if (next) { next.focus(); try { next.setSelectionRange(caret, caret); } catch (_) { /* not text */ } }
    return;
  }
  if (!el.dataset.edit) return; const x = artifact(); if (!a || !canEditWork(a,x)) return;
  if(x.kind==='investigation') { queueInvestigationDraft(a,x,{[el.dataset.edit]:el.value});return; }
  dirty = { attemptId: a.id, id: x.id, title: document.getElementById('editor-title')?.value || x.title, purpose: document.querySelector('[data-edit="purpose"]')?.value || x.purpose, body: document.getElementById('editor-body')?.value ?? shown(x).body, ...(x.kind === 'test_set' ? { kind:'test_set', cases: structuredClone(shown(x).cases) } : {}), ...(x.kind==='investigation'?{kind:'investigation',question:shown(x).question,blocks:structuredClone(shown(x).blocks)}:{}) };
  updateSave(); clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { flush(); const cur = artifact(); const row = cur && document.querySelector(`.ol-row[data-id="${cur.id}"] .ol-title`); if (row) row.textContent = shown(cur).title; }, 700);
});
document.addEventListener('change', e => {
  const el = e.target; const a = current();
  try {
    if(el.dataset.investigationReview){commit();updateSave();return;}
    if(el.dataset.investigationQuestion !== undefined){commit();updateSave();return;}
    if (el.dataset.caseHistory) { commit(); ui.testHistory[el.dataset.caseHistory] = el.value; refreshWS(['stage']); return; }
    if (el.dataset.caseField) { commit(); updateTestChrome(); return; }
    if (el.dataset.change === 'triage') { const pick = el.closest('.pri-pick'); pick.outerHTML = priPick(el.dataset.id, el.value, el.closest('.seed')?.textContent.trim() || '', 'triage'); return; }
    if (el.dataset.change === 'priority') { commit(); const t = a.tasks.find(x => x.id === el.dataset.id); moveWithUndo(a, el.dataset.id, { priority: el.value }, T('「' + taskTitle(t) + '」改为' + PRI(el.value), '“' + taskTitle(t) + '” is now ' + PRI(el.value))); return; }
    if (el.dataset.edit === 'purpose') { el.dispatchEvent(new Event('input', { bubbles: true })); commit(); updateSave(); refreshWS(['toolbar', 'stage']); }
    if (el.dataset.scope) ui.exportScope[el.dataset.scope] = el.checked;
    if (el.dataset.pick && ui.deliverPick) { if (el.checked) ui.deliverPick.add(el.dataset.pick); else ui.deliverPick.delete(el.dataset.pick); }
    if (el.id === 'import-file' && el.files && el.files[0]) { const f = el.files[0]; if (f.size > 2 * 1024 * 1024) throw new Error(T('请选 2 MB 以内的文本文件', 'Choose a text file under 2 MB')); f.text().then(text => { const t = document.getElementById('import-content'); if (t) { t.value = text; ui.importText = text; } }).catch(() => notify(T('文件读不出来，可以直接粘贴文本', 'That file could not be read. Paste the text instead.'))); }
    if (el.form && el.form.dataset.form === 'config') { const f = new FormData(el.form); const c = { participants: Number(f.get('participants')), domains: f.getAll('domains'), update: String(f.get('update')), workItems: f.getAll('workItems') }; const box = document.querySelector('[data-checks]'); if (box) box.outerHTML = configChecks(a, c); }
  } catch (err) { notify(errText(err)); }
});
document.addEventListener('submit', async e => {
  const form = e.target; if (!form.dataset.form) return; e.preventDefault(); commit();
  const f = new FormData(form); const a = current();
  try {
    switch (form.dataset.form) {
      case 'intake': {
        ui.intake.text = String(f.get('text') || ''); ui.intake.result = matchIntake(ui.intake.text); ui.intake.open = true; render();
        const r = ui.intake.result; announce({ empty: T('先写一句你想练的业务', 'Write a sentence first'), none: T('这个情境现在还练不了', 'This one cannot be practised yet'), partial: T('只能借用知识助手试点的决策结构', 'Only the decision structure carries over'), matched: T('最接近知识助手试点', 'Closest match: the knowledge assistant pilot') }[r.status]);
        const out = document.querySelector('.intake-result'); out?.focus({ preventScroll: true }); out?.scrollIntoView({ block: 'nearest', behavior: reduceMotion.matches ? 'auto' : 'smooth' });
        break;
      }
      case 'task': {
        const values = { title: String(f.get('title')).trim(), note: String(f.get('note') || '') }; const pr = String(f.get('priority') || 'next');
        if (form.dataset.id) {
          const t = a.tasks.find(x => x.id === form.dataset.id);
          if (values.title === taskTitle(t)) delete values.title; if (values.note === taskNote(t)) delete values.note;
          if (Object.keys(values).length) E.updateTask(a, t.id, values);
          if (t.priority !== pr) E.moveTask(a, t.id, { priority: pr });
          const split = String(f.get('split') || '').trim(); if (split) E.splitTask(a, t.id, split);
        } else {
          let t; closeSheet(true);
          if (ui.route === 'work') { flip(() => { t = E.addTask(a, { ...values, priority: pr }); E.moveTask(a, t.id, { priority: pr }); persist(); refreshWS(['stage']); }); notify(T('已加到「' + PRI(pr) + '」', 'Added to “' + PRI(pr) + '”'), { action: { label: T('打开', 'Open'), run: () => openTask(t.id) } }); }
          else { t = E.addTask(a, { ...values, priority: pr }); E.moveTask(a, t.id, { priority: pr }); persist(); openTask(t.id); }
          break;
        }
        persist(); closeSheet(); flip(() => refreshWS()); break;
      }
      case 'artifact': { const x = E.createArtifact(a, { title: String(f.get('title')).trim(), purpose: String(f.get('purpose')), taskId: String(f.get('taskId')), body: '' }); startWorking(a, a.tasks.find(y => y.id === x.taskId)); persist(); closeSheet(true); openTask(x.taskId, { type: 'work', id: x.id }); setTimeout(() => document.getElementById('editor-body')?.focus(), 80); break; }
      case 'run-test': runQuestion(String(f.get('question')), String(f.get('expectation') || '')); break;
      case 'chat': { const text = String(f.get('text')).trim(); if (!text || !ui.chatRole) break; ui.chatTask = task() ? task().id : null; const x = ui.obj?.type === 'work' ? artifact() : null; const context = { ...(sessionOf(a).turnContexts?.[ROLE_ID[ui.chatRole]] || {}), ...(ui.chatTask ? { task_id: ui.chatTask } : {}), ...(x ? { work_id: x.id } : {}) }; await L.turn(a, ui.chatRole, text, context); refreshWS(['rail', 'toolbar']); document.getElementById('chat-input')?.focus(); break; }
      case 'config': {
        await L.config(a, { participants: Number(f.get('participants')), domains: f.getAll('domains'), update: String(f.get('update')), fallback: String(f.get('fallback')), workItems: f.getAll('workItems'), launchDay: Number(f.get('launchDay')) });
        closeSheet(); { const t = task(); if (t && !ui.configFromTestSet) ui.obj = { task: t.id, type: 'bench' }; ui.configFromTestSet = false; } refreshWS(); notify(T('试点设置 v' + a.configVersion + ' 已保存，下一次测试会用它。', 'Pilot settings v' + a.configVersion + ' saved. The next test uses them.'));
        break;
      }
      case 'resources': await L.action(a, String(f.get('kind')), { reason: String(f.get('reason')).trim() }); sheetResources(); refreshWS(); notify(T('申请已提交给 Priya', 'Request sent to Priya')); break;
      case 'live-deliver': saveDraftFields(a, form); await L.save(a, sessionOf(a).draft); sheetDeliver(); break;
      case 'import': {
        const text = String(f.get('content')); const data = E.validateImported(normalizeImport(text)); ui.importText = text; if ((statusOf(a) !== 'active' || storageIssue || snap().storageError)) throw new Error(T('这次练习只读或存储不可用，不能导入新作品。','This practice is read-only or storage is unavailable. New work cannot be imported.')); const t = task();
        openSheet(T('检查带回的内容', 'Check what came back'), `<p class="meta">${esc(T(`来自你的 Agent，用途「${purposeLabel(data.purpose)}」，放在「${taskTitle(t || a.tasks[0])}」下`, `From your agent, purpose “${purposeLabel(data.purpose)}”, filed under “${taskTitle(t || a.tasks[0])}”`))}</p>${data.kind === 'investigation' ? investigationPreview(data) : data.kind === 'test_set' ? testSetPreview(data, E.getMaterials(a)) : `<article class="paper"><h3 class="paper-title">${esc(data.title)}</h3><div class="prose">${md(data.body)}</div></article>`}`, `${btn(T('返回', 'Back'), 'close', 'quiet')}<span class="spacer"></span>${btn(T('导入为待检查作品', 'Import as “to check”'), 'confirm-import', 'primary')}`, 'wide');
        break;
      }
    }
  } catch (err) { notify(errText(err) || T('请检查输入', 'Please check the input')); }
});
document.addEventListener('pointermove', () => document.documentElement.classList.remove('hide-tooltips'), {passive:true});
document.addEventListener('focusin', () => document.documentElement.classList.remove('hide-tooltips'));
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.documentElement.classList.add('hide-tooltips');
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); const v = commit(); notify(storageIssue ? storageText() : v ? T('已存为新版本', 'Saved as a new version') : T('已保存', 'Saved')); updateSave(); }
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && (e.target.id === 'chat-input' || e.target.id === 'lab-q')) { e.preventDefault(); e.target.form.requestSubmit(); }
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'z' && ui.lastUndo && !/^(INPUT|TEXTAREA)$/.test(e.target.tagName)) { e.preventDefault(); const u = ui.lastUndo; ui.lastUndo = null; u(); toastEl.classList.remove('visible'); notify(T('已撤销', 'Undone')); }
  if (e.key === 'Escape' && !sheet.open) {
    if (ui.menu) { ui.menu = null; if (WS.includes(ui.route)) refreshWS(['toolbar', 'stage']); else render(); return; }
    if (ui.railOpen) { ui.railOpen = false; refreshWS(['toolbar']); return; }
    if (ui.advice) { ui.advice = null; refreshWS(['stage']); return; }
    if (ui.route === 'doc') { e.preventDefault(); go('work'); return; }
  }
  if (e.altKey && /^Arrow/.test(e.key) && e.target.classList && e.target.classList.contains('card-open')) {
    e.preventDefault();
    const a = current(); const id = e.target.dataset.id; const t = a.tasks.find(x => x.id === id); if (!t) return;
    const order = ['first', 'next', 'later']; const lane = a.tasks.filter(x => x.priority === t.priority); const li = lane.indexOf(t);
    let to = null;
    if (e.key === 'ArrowLeft' && order.indexOf(t.priority) > 0) to = { priority: order[order.indexOf(t.priority) - 1] };
    if (e.key === 'ArrowRight' && order.indexOf(t.priority) < 2) to = { priority: order[order.indexOf(t.priority) + 1] };
    if (e.key === 'ArrowUp' && li > 0) to = { priority: t.priority, beforeId: lane[li - 1].id };
    if (e.key === 'ArrowDown' && li < lane.length - 1) to = { priority: t.priority, beforeId: lane[li + 2] ? lane[li + 2].id : null };
    if (!to) { notify(T('已经到头了', 'Already at the end')); return; }
    moveWithUndo(a, id, to, to.priority !== t.priority ? T('「' + taskTitle(t) + '」改为' + PRI(to.priority), '“' + taskTitle(t) + '” is now ' + PRI(to.priority)) : T('已调整顺序', 'Order changed'));
    document.querySelector(`.card-open[data-id="${id}"]`)?.focus();
    const moved = a.tasks.find(x => x.id === id); const laneNow = a.tasks.filter(x => x.priority === moved.priority);
    announce(T('「' + taskTitle(moved) + '」现在在' + PRI(moved.priority) + '第 ' + (laneNow.indexOf(moved) + 1) + ' 位，共 ' + laneNow.length + ' 项', '“' + taskTitle(moved) + '” is now ' + (laneNow.indexOf(moved) + 1) + ' of ' + laneNow.length + ' in ' + PRI(moved.priority)));
  }
});
sheet.addEventListener('cancel', e => { e.preventDefault(); closeSheet(); });
sheet.addEventListener('click', e => { if (e.target === sheet) { const r = sheet.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) closeSheet(); } });
// Drag between priority groups: drop on a task to insert before it, on a group to append.
document.addEventListener('dragstart', e => { const row = e.target.closest && e.target.closest('.kanban [data-task-id]'); if (!row) return; dragId = row.dataset.taskId; row.classList.add('dragging'); document.querySelector('.kanban')?.classList.add('is-dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragId); });
document.addEventListener('dragover', e => { const laneEl = e.target.closest && e.target.closest('.col'); if (!laneEl || !dragId) return; e.preventDefault(); document.querySelectorAll('.drop-before, .col.drop').forEach(x => x.classList.remove('drop-before', 'drop')); const row = e.target.closest('[data-task-id]'); if (row && row.dataset.taskId !== dragId) row.classList.add('drop-before'); else laneEl.classList.add('drop'); });
document.addEventListener('drop', e => {
  const laneEl = e.target.closest && e.target.closest('.col'); if (!laneEl || !dragId) return; e.preventDefault();
  const a = current(); const row = e.target.closest('[data-task-id]'); const t = a.tasks.find(x => x.id === dragId); const pr = laneEl.dataset.lane; const id = dragId; dragId = null;
  document.querySelectorAll('.dragging, .drop-before, .col.drop').forEach(x => x.classList.remove('dragging', 'drop-before', 'drop')); document.querySelector('.kanban')?.classList.remove('is-dragging');
  if (row && row.dataset.taskId === id) return;
  moveWithUndo(a, id, { priority: pr, beforeId: row ? row.dataset.taskId : null }, t.priority !== pr ? T('「' + taskTitle(t) + '」移到' + PRI(pr), '“' + taskTitle(t) + '” moved to ' + PRI(pr)) : T('已调整顺序', 'Order changed'));
});
document.addEventListener('dragend', () => { dragId = null; document.querySelector('.kanban')?.classList.remove('is-dragging'); document.querySelectorAll('.dragging, .drop-before, .col.drop').forEach(x => x.classList.remove('dragging', 'drop-before', 'drop')); });
document.addEventListener('focusout', e => {
  if(e.target.dataset.investigationQuestion !== undefined){commit();updateSave();return;}
  if (e.target.dataset.caseField) { commit(); updateTestChrome(); return; }
  if (e.target.id !== 'editor-body' && e.target.id !== 'editor-title') return;
  setTimeout(() => { const a = current(); const x = artifact(); if (!a || !x) return; if (document.activeElement && (document.activeElement.id === 'editor-body' || document.activeElement.id === 'editor-title')) return; commit(); updateSave(); }, 0);
});
window.addEventListener('beforeunload', commit);
window.addEventListener('scroll', () => document.documentElement.classList.toggle('scrolled', window.scrollY > 4), { passive: true });
window.addEventListener('resize', () => { document.querySelectorAll('.segmented').forEach(layoutSegmented); syncPanels(); });
onLocaleChange(() => { flush(); if (sheet.open) closeSheet(true); render(); });

/* ---------- boot ---------- */
const workFolders = installWorkFolders(document, { onSelect: (taskId, workId, event) => {
  ui.kbd = event?.detail === 0; document.documentElement.dataset.input = ui.kbd ? 'keyboard' : 'pointer';
  openTask(taskId, { type: 'work', id: workId });
  if (ui.kbd) {
    const focusWork = () => document.getElementById('editor-title')?.focus({ preventScroll: true });
    if (activeTransition) activeTransition.updateCallbackDone.then(focusWork); else focusWork();
  }
}, onInteract: () => {
  if (!ui.menu) return;
  ui.menu = null;
  document.querySelectorAll('.menu, .popover').forEach(el => el.remove());
  document.querySelectorAll('[data-menu][aria-expanded="true"]').forEach(el => el.setAttribute('aria-expanded', 'false'));
} });
L.attach(state, onLive);
L.refresh(current()).then(() => { ui.synced = true; });
setInterval(() => { if (!document.hidden) L.store.poll(); }, 1500);
{ const p = parseRoute(); ui.route = p.r; ui.routeId = p.id; }
if ((WS.includes(ui.route) || ui.route === 'review') && !current()) { ui.route = ''; ui.routeId = null; history.replaceState(null, '', '#/'); }
render();
