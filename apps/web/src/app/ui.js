// RoleCraft workbench. A workplace in two levels: the board shows the whole job, and
// each task opens its own workbench. Server state (materials, colleagues, tests,
// approvals, submission, review) comes from the API through window.PracticeLive;
// tasks, work, agent imports and the scenario rules in coach.js are local.
import { createPageTransition } from './view-transition';
import {
  T,
  locale,
  getPreference,
  setPreference,
  onLocaleChange,
  detect,
  when,
  isChinese,
  practiceLocale,
  setPracticeLocale,
} from './i18n';
import {
  icon,
  priMark,
  statusMark,
  PEOPLE,
  ROLES,
  avatar,
  agentMark,
  assistantMark,
} from './art.js';
import * as Coach from './coach.js';
import { workSourceLabel } from './work-source.js';
import { summaryText } from '../features/recognition-native/badge';
import { lensOn, onLensChange, setLens } from '../features/recognition-native/lens';
import { openLensForDelivery } from '../screens/result/deliver-lens';
import { registerResultScreen } from '../screens/result';
import { playReading } from '../features/recognition-native/sentences';
import { signalsHtml } from '../features/recognition-native/signals';
import { installCardToggles, fillCardMetrics } from '../features/recognition-native/profile-card';
// The system profile page (#/lab) loads its code on demand, its styles with the main bundle.
import '../features/recognition-lab/lab.css';
import './practice-language.css';
import { behaviorHtml } from '../features/behavior-native/view';
import {
  PRI,
  STATUS,
  ROLE_TITLE,
  KNOWS,
  OPENER,
  CASE,
  say,
  SEED_KEYS,
  SEEDS,
  situationTask,
  taskTitle,
  taskNote,
  seedText,
  purposeLabel,
  purposeFromLabel,
  INTENT_HINT,
  UPDATE,
  FALLBACK,
  DOMAIN,
  DECISION,
  WORK_ITEM,
  materialTitle,
  criterionName,
  LABEL,
  FIELDS,
  FIELD,
  FIELD_HINT,
  errText,
  PRODUCT_NAME,
  workVersion,
  caseShown,
} from './vocab.js';
import { modelPartsHtml, modelPopoverHtml, modelStatus, modelWaitHtml } from './model-status';
import { awaitingRoles, isLocalReply, previewLine } from '../features/roles-native/chat-model';
import { requestRefs } from '../features/roles-native/v4-data';
import { aboutFacts } from './about-facts';
import { canonicalPurpose } from '../features/workspace/native-v4/form-values';
import { workspaceActionMessage } from '../features/workspace/native-v4/messages';
import { pendingTurnRole, serverText } from '../store';
import { eventLine, isFeedEvent } from './events.js';
import { testSetView, testSetPreview, caseState, testRunView } from './test-set-view.js';
import {
  answerModeLine,
  assistantText,
  generatorField,
  quotedAnswer,
  submittedGenerator,
} from './assistant-mode';
import './test-set.css';
import {
  investigationView,
  investigationPreview,
  investigationSourceKey,
} from './investigation-view.js';
import './investigation.css';
import { createDocumentMotion } from './document-motion.js';
import {
  configUse,
  planWorkItems,
  savedConfigNotice,
  syncStrategyWork,
  workCost,
  workItemChoice,
} from './pilot-config';
import './pilot-config.css';
import './document-motion.css';
import { markdownHtml } from './markdown';
import { copyBlockedText, returnPlacement, unmatchedReturnText } from './agent-return';
import { workFolderMarkup, installWorkFolders } from './work-folder.js';
import './work-folder.css';
import { createConnectionKeeper, renderAgentConnection } from './agent-connection';
import { feedStore, provideAgentPage, syncAgentFeed } from '../features/agent-page';
import './agent-connection.css';
import { installV4References } from '../v4-references';
import {
  changeSentence,
  practiceCardLine,
  practiceCards,
  practiceSharedLine,
} from './practice-cards';
import { nativeCiteAction } from './native-cite';
import { createPracticeRecovery } from '../features/practice-recovery/view';
import { criterionLabels } from '../features/feedback-native/index';
import {
  isSealedPracticeError,
  practiceUnavailableText,
} from '../features/feedback-native/read-only-notice';
import { afterPracticeRead } from '../features/feedback-native/practice-read';
import { provideTaskCardFacts, testFacts } from '../features/workspace/native-v4/card-facts';
import {
  ENGINEER_CASES,
  ENGINEER_ROUTES,
  engineerEntryId,
  installEngineer,
  navigateStage,
  openEngineerHandover,
  openEngineerTicket,
  colleagueReported,
  readLearnerRole,
  takeInPractice,
  writeLearnerRole,
} from '../features/engineer-desk/entry';
import {
  afterShellRender,
  agentConnection,
  dismissToasts,
  hasStage,
  everEngineer,
  hatOf,
  rememberRole,
  roleOf,
  installShell,
  lastTicket,
  onAgentConnection,
  lightState,
  setHat,
  setLastTicket,
  stageOf,
  isRegisteredRoute,
  onRouteRegistered,
  pmStage,
  registeredRoute,
  registeredAction,
  registeredRouteNames,
  registerRoute,
  registerStage,
  showToast,
} from '../shell';
import { HatScale, PrimaryKey } from '../shell/bar';
import '../shell/bar.css';
import { carried, distillation, progressOf } from '../shell/progress';
import { comparisonFor } from '../features/recognition-native/test-comparison';
import { createWorkChecks, workCheckHtml } from '../features/recognition-native/work-check';
import { createV4FeedbackAdapter } from '../features/feedback-native/v4-slot';
import { testMomentHtml, testAgeText, retrievalHit } from '../features/recognition-native/test-moment';
import * as Greetings from '../features/colleague-greetings';
import { messageRows, noteKey } from '../features/colleague-greetings/unread';
import { engineerApi } from '../features/engineer-desk/api';
import { ProgressBand } from '../shell/progress-band';
import { Compass } from '../features/aipm-guide/compass';
import { WorkStack } from '../shell/work-stack/stack';
import { quoteToWorksheet, sourceLabel } from '../features/aipm-design/install';
import { createAipmPractice } from '../features/aipm-guide/practice';
import { showDraftToast } from '../features/aipm-guide/draft-toast';
import '../shell/progress.css';
import '../shell/unread-light.css';
import '../shell/home-pill.css';
import { agentLine } from '../screens/board/agent-line';
import * as Board from '../screens/board';
import { dossierHtml, installDossier } from '../screens/investigate';
import { islandSlot, keepIsland } from '../islands/mount';
import {
  entryHtml,
  fadeIn,
  homeHtml,
  leaveForBrief,
  resetSeedOrder,
  seedOrder,
} from '../screens/home/home';

const L = window.PracticeLive;
const E = L.engine;
const app = document.getElementById('app');
const sheet = document.getElementById('sheet');
const KEY = 'rolecraft.open-work.ui.v1';
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const documentMotion = createDocumentMotion();
const ROLE_ID = { manager: 'supervisor', business: 'business_lead', technical: 'tech_lead' };
const ROLE_OF = { supervisor: 'manager', business_lead: 'business', tech_lead: 'technical' };
const INDEX_DELAY_HOURS = 24; // scenario constant; not yet part of the session state

/* ---------- local record ---------- */
let state;
let storageIssue = '';
let storageLocked = false;
let rawRecord = null;
try {
  rawRecord = localStorage.getItem(KEY);
  state = rawRecord ? JSON.parse(rawRecord) : E.newState();
  if (!state || state.version !== E.VERSION || !Array.isArray(state.attempts))
    throw new Error('version');
  state.attempts = state.attempts.filter((a) => {
    try {
      E.normalizeAttempt(a);
      return true;
    } catch (_) {
      return false;
    }
  });
  if (state.activeId && !state.attempts.some((a) => a.id === state.activeId)) state.activeId = null;
} catch (err) {
  state = E.newState();
  storageLocked = true;
  storageIssue = err && err.name === 'SecurityError' ? 'blocked' : 'unreadable';
}
const storageText = () =>
  ({
    blocked: T(
      '这个浏览器不允许本页保存，本地笔记只留在当前页面。',
      'This browser blocks saving, so local notes stay on this page only.',
    ),
    unreadable: T(
      '之前的本地记录读不出来，原记录没有被覆盖。',
      'Earlier local notes could not be read. The original record is untouched.',
    ),
    failed: T('浏览器没能保存本地笔记。', 'The browser could not save your local notes.'),
  })[storageIssue] || '';

const ui = {
  route: null,
  routeId: null,
  obj: null,
  artifactId: null,
  rail: 'team',
  railTab: 'team',
  chatRole: null,
  railOpen: false,
  menu: null,
  scopeAll: false,
  benchAll: false,
  reviewFor: null,
  notesCache: [],
  behaviorStepsOpen: new Set(),
  intake: { text: '', result: null, open: false },
  busy: false,
  lastRun: null,
  importDrafts: {},
  chatQuotes: {},
  practice: {},
  practiceBusy: false,
  practiceBrowse: null,
  practiceNote: null,
  exportScope: { artifacts: true, materials: true, tests: true },
  labPrefill: '',
  compare: false,
  previous: {},
  arriving: false,
  // "Take this on" pressed, the practice opening: the brief holds (screens/home walk-in).
  walkIn: false,
  landing: false,
  editPending: null,
  previewWorkId: null,
  investigationSources: {},
  investigationErrors: {},
  investigationViews: {},
  investigationComposing: false,
  investigationRefreshQueued: false,
  testOpen: {},
  testHistory: {},
  testModes: {},
  testErrors: {},
  configFromTestSet: false,
  synced: false,
  lastError: '',
  pendingRequestId: null,
  lastUndo: null,
  pendingCite: null,
};
let dirty = null;
let saveTimer = null;
let sheetReturn = null;
let dragId = null;

/* ---------- helpers ---------- */
const esc = (v) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
const current = () => E.getAttempt(state);
const sessionOf = (a) => (a ? L.session(a) : null);
// The practice's work language ('zh' | 'en'), fixed when it started; null for an old local one.
// World text inside a practice (the manager's words, what happened) is told in it; labels follow
// the interface. caseOf is the situation's words inside this practice.
const workLang = (a) => {
  const l = sessionOf(a)?.v2Binding?.workLanguage;
  return l === 'zh' || l === 'en' ? l : null;
};
const worldText = (a) => say(workLang(a));
const caseOf = (a) => CASE(a.scenarioId, workLang(a));
// Marks text whose language differs from the interface, for screen readers and fonts.
const langAttr = (l) => (l && l !== locale() ? ` lang="${l === 'zh' ? 'zh-CN' : 'en'}"` : '');
const langOf = (a) => langAttr(workLang(a));
// Server-confirmed sealed binding (an old package after a switch); the host context knows first.
const sealedSession = (a) =>
  sessionOf(a)?.v2ReadOnly === true || L.v4Host(a)?.snapshot()?.readOnly === true;
const snap = () => L.store.getSnapshot();
const task = () => {
  const a = current();
  return a && ui.route === 'task' ? a.tasks.find((t) => t.id === ui.routeId) || null : null;
};
const artifact = () => {
  const a = current();
  return a ? a.artifacts.find((x) => x.id === ui.artifactId && !x.removedAt) || null : null;
};
const works = (a) => E.currentArtifacts(a);
const isEarlier = (a, x) => x.adopted && !works(a).some((y) => y.id === x.id);
const taskWorks = (a, id) =>
  a.artifacts.filter((x) => x.taskId === id && !x.removedAt && !isEarlier(a, x));
const shown = (x) => (x.draft ? Object.assign({}, x, x.draft) : x);
function editorView(a, x) {
  const view = shown(x);
  if (!L.nativeWorkspace(a) || ui.previewWorkId === x.id) return view;
  const value = L.nativeProductValue(a, x.id);
  if (!value) return view;
  return {
    ...view,
    title: value.title,
    body: value.content,
    purpose:
      E.PURPOSES.find((purpose) => canonicalPurpose(purpose) === value.purpose) ?? value.purpose,
  };
}
// What a piece of work is for: flask = a test plan, branch = options, stamp = the decision you will submit.
const purposeGlyph = (intent) =>
  ({ plan: 'flask', option: 'branch', commit: 'stamp' })[intent]
    ? icon({ plan: 'flask', option: 'branch', commit: 'stamp' }[intent], 'i-xs purpose-i')
    : '';
// Doing something on a task moves it from 待处理 to 正在做; calling it done stays with you.
const startWorking = (a, t) => {
  if (!L.nativeWorkspace(a) && t && t.status === 'open')
    E.updateTask(a, t.id, { status: 'working' });
};
const scen = (id) => E.scenarios.find((s) => s.id === id) || E.scenarios[0];
const statusOf = (a) => (a && a.backend && a.backend.status) || 'active';
const canWrite = (a) => {
  const s = sessionOf(a);
  const n = snap();
  return !!s && s.world.status === 'active' && !n.busy && !s.pending && !n.storageError;
};
const typingRole = (a) => ROLE_OF[pendingTurnRole(sessionOf(a))] || null;
const vtName = (s) => String(s).replace(/[^a-zA-Z0-9-]/g, '');
const zhAttr = (text) => (locale() === 'en' && isChinese(text) ? ' lang="zh-CN"' : '');
const zhTag = (text) =>
  locale() === 'en' && isChinese(text)
    ? '<span class="msg-local" title="The server has no English version of this text yet">Chinese source</span>'
    : '';
const readSet = (a) =>
  new Set(
    a.events
      .filter((e) => e.server && e.type === 'material_read')
      .map((e) => e.detail && e.detail.materialId),
  );
const replyIds = (a, role) => messageRows(a.conversations[role] || []).filter(row => row.key).map(row => row.key);
const unread = (a, role) =>
  Greetings.receipts.count(a.id, role, [
    ...replyIds(a, role),
    ...(ui.notesCache || []).filter(note => note.role === role).map(note => noteKey(note.key)),
    ...(Greetings.hasArrived(a.id, role) ? [Greetings.greetingId] : []),
  ]);
const unreadLabel = (n) => T(`${n} 条未读消息`, `${n} unread message${n === 1 ? '' : 's'}`);
const unreadBadge = (n) =>
  `<span class="unread-mark" ${n ? '' : 'hidden'}><span class="sr-only">${esc(unreadLabel(n))}</span></span>`;
function paintUnread() {
  const a = current();
  if (!a) return;
  for (const role of ROLES) {
    const n = unread(a, role);
    const person = document.querySelector(`[data-action="chat"][data-role="${role}"]`);
    person?.classList.toggle('unread', n > 0);
    const badge = person?.querySelector('.unread-mark');
    if (badge) {
      badge.hidden = !n;
      badge.firstElementChild.textContent = unreadLabel(n);
    }
    const dot = document.querySelector(`.team-btn .who-${role} .av-dot`);
    if (dot) dot.hidden = !n;
  }
  const total = ROLES.reduce((n, r) => n + unread(a, r), 0);
  const summary = document.querySelector('.team-compact .unread-mark');
  if (summary) { summary.hidden = !total; summary.firstElementChild.textContent = unreadLabel(total); }
  document
    .querySelector('.team-btn')
    ?.setAttribute('aria-label', T('团队', 'Team') + (total ? ` · ${unreadLabel(total)}` : ''));
}
function refreshGreeting() {
  const a = current(),
    slot = document.querySelector('[data-chat-greeting]');
  if (a && slot && !slot.firstElementChild && Greetings.hasArrived(a.id, ui.chatRole))
    slot.innerHTML = Greetings.introductionHtml(
      a.id,
      hatHere(a) === 'engineer' ? 'engineer' : 'pm',
      ui.chatRole,
      locale(),
      true,
      canWrite(a),
    );
  const next = document.querySelector('[data-entry-next]');
  if (a && next && hatHere(a) === 'engineer') next.outerHTML = nextStep(a);
  paintUnread();
}
document.addEventListener('rolecraft:greetings', refreshGreeting);
const btn = (label, action, cls = '', attrs = '') =>
  `<button type="button" class="btn ${cls}" data-action="${action}" ${attrs}>${label}</button>`;
// Continue codes: the ⋯ dialog of a practice and the entry on the job page. Codes are never stored.
const recovery = createPracticeRecovery({
  live: L,
  button: btn,
  icon,
  openSheet,
  onSheetClose: (done) => sheet.addEventListener('close', () => done(sheet), { once: true }),
  notify,
  render,
  // A practice this browser already had keeps its reading state and selection; it is switched to.
  enter: (a, held) =>
    enterWork(() => {
      if (!held) return freshAttemptUi(a);
      resetAttemptUi();
      persist();
    }),
  showEntry: (focus) => {
    go('pm');
    document.getElementById(focus)?.focus();
  },
});
const answerText = (s) => String(s || '').replace(/^#{1,6}\s+/, '');
// Agent paste drafts belong to one practice; switching practice never carries them over.
const importDraft = (a) => (a && ui.importDrafts[a.id]) || '';
const setImportDraft = (a, value) => {
  if (a) ui.importDrafts[a.id] = value;
};
// A quoted test travels with the next message to that colleague; it is not editable text.
const quoteKey = (a, role) => (a ? a.id : '') + ':' + role;
// A generated answer keeps its mode marker wherever it is quoted.
const testQuote = (r) => {
  const said = quotedAnswer(r, String(r.rawAnswer ?? answerText(r.answer)).slice(0, 300));
  return T(
    `我测了“${r.question}”，助手答：“${said}”（配置 v${r.configVersion}，政策源 v${r.policyVersion}，索引 v${r.indexVersion}）。`,
    `I asked “${r.question}”. The assistant answered: “${said}” (config v${r.configVersion}, policy v${r.policyVersion}, index v${r.indexVersion}).`,
  );
};

function md(raw, opts = {}) {
  return (
    markdownHtml(raw, opts) || `<p class="muted">${T('还没有正文。', 'Nothing written yet.')}</p>`
  );
}

// Word-level comparison for document versions. Chinese is compared by character.
function diffHtml(before, after) {
  const tokens = (s) => String(s).match(/[一-鿿]|[A-Za-z0-9_.]+|\s+|[^\sA-Za-z0-9_一-鿿]/g) || [];
  const a = tokens(before);
  const b = tokens(after);
  if (a.length * b.length > 4e6) return md(after, { dropTitle: true });
  const dp = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let i = 0;
  let j = 0;
  const ops = [];
  const put = (cls, t) => {
    const last = ops[ops.length - 1];
    if (last && last[0] === cls) last[1] += t;
    else ops.push([cls, t]);
  };
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      put('', a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      put('del', a[i]);
      i++;
    } else {
      put('ins', b[j]);
      j++;
    }
  }
  while (i < a.length) put('del', a[i++]);
  while (j < b.length) put('ins', b[j++]);
  // Wrap each changed run per line so paragraphs survive.
  const out = ops
    .map(([cls, t]) =>
      t
        .split('\n')
        .map((part) => (cls && part ? `<${cls}>${esc(part)}</${cls}>` : esc(part)))
        .join('\n'),
    )
    .join('');
  return `<div class="diff">${out
    .split('\n')
    .filter((l) => l.replace(/<[^>]+>/g, '').trim() && !/^(<\w+>)?#\s/.test(l))
    .map((l) => `<p>${l}</p>`)
    .join('')}</div>`;
}
function investigationDiffHtml(before, after) {
  const count = (text) =>
    (String(text).match(/[一-鿿]|[A-Za-z0-9_.]+|\s+|[^\sA-Za-z0-9_一-鿿]/g) || []).length;
  if (count(before) * count(after) > 4e6)
    return `<p class="inv-missing">${T('正文较长，未生成逐字差异。切换到“原文”分别核对，原文均完整保留。', 'These sources are too long for word-by-word comparison. Switch to Originals to read both complete texts.')}</p>`;
  return diffHtml(before, after);
}

/* ---------- saving ---------- */
function persist() {
  if (storageLocked) {
    updateSave();
    return false;
  }
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
    if (storageIssue === 'failed') storageIssue = '';
    updateSave();
    return true;
  } catch (_) {
    storageIssue = 'failed';
    updateSave();
    return false;
  }
}
function saveLabel() {
  const x = artifact();
  if (storageIssue) return T('没有保存', 'Not saved');
  if (dirty) return T('正在保存…', 'Saving…');
  return x && x.draft ? T('草稿已保存', 'Draft saved') : T('已存本机', 'Saved locally');
}
function updateSave() {
  document.querySelectorAll('[data-save]:not([data-v4-managed])').forEach((el) => {
    el.textContent = saveLabel();
    el.classList.toggle('error', !!storageIssue);
  });
  const x = artifact();
  // Only the editor's version label; a form's data-revision is its exact revision token.
  document.querySelectorAll('[data-revision-label]').forEach((el) => {
    if (x) el.textContent = workVersion(x.revision);
  });
}
// A pause in typing keeps a draft; leaving the editor, switching, submitting or ⌘S makes a version.
function flush() {
  clearTimeout(saveTimer);
  if (!dirty) return false;
  const a = state.attempts.find((x) => x.id === dirty.attemptId);
  const x = a && a.artifacts.find((y) => y.id === dirty.id);
  if (x)
    x.draft = {
      title: dirty.title || T('未命名', 'Untitled'),
      purpose: dirty.purpose,
      body: dirty.body,
      ...(dirty.cases ? { kind: 'test_set', cases: dirty.cases } : {}),
      ...(dirty.blocks
        ? {
            kind: 'investigation',
            question: dirty.question,
            blocks: dirty.blocks,
            review: dirty.review,
          }
        : {}),
    };
  dirty = null;
  persist();
  return !!x;
}
// All investigation fields share one draft so rapid edits and evidence refreshes
// preserve each other. Reading options stay separate from the saved work.
function queueInvestigationDraft(a, x, patch) {
  const pending = dirty?.attemptId === a.id && dirty.id === x.id ? dirty : null;
  const next = { ...shown(x), ...pending, ...patch, kind: 'investigation' };
  const review = structuredClone(next.review || { focus: 'uncertain', note: '' });
  dirty = {
    attemptId: a.id,
    id: x.id,
    kind: 'investigation',
    title: next.title,
    purpose: next.purpose,
    question: next.question,
    blocks: structuredClone(next.blocks),
    review,
    body: E.investigationSummary({ ...next, review }),
  };
  updateSave();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flush, 450);
}
function investigationViewState(a, x) {
  const key = a.id + '|' + x.id;
  return (ui.investigationViews[key] ||= { modes: {}, open: {} });
}
function commit() {
  flush();
  let changed = false;
  state.attempts.forEach((a) =>
    a.artifacts.forEach((x) => {
      if (!x.draft || x.removedAt) return;
      const d = x.draft;
      delete x.draft;
      try {
        const before = x.revision;
        E.saveArtifact(a, x.id, d);
        changed = changed || x.revision !== before;
      } catch (err) {
        x.draft = d;
        notify(errText(err));
      }
    }),
  );
  persist();
  return changed;
}

/* ---------- toast & announcements ---------- */
function notify(text, opts = {}) {
  if (
    sheet.open &&
    [...sheet.querySelectorAll('[data-approval-denial] span')].some((el) => el.textContent === text)
  ) {
    announce(text);
    return;
  }
  if (
    sheet.open &&
    !sheet.classList.contains('closing') &&
    !opts.undo &&
    !opts.action &&
    !opts.toast
  ) {
    let el = sheet.querySelector('.inline-alert');
    if (!el) {
      el = document.createElement('div');
      el.className = 'inline-alert';
      el.setAttribute('role', 'alert');
      sheet.querySelector('.sheet-body')?.prepend(el);
    }
    el.textContent = text;
    return;
  }
  const act = opts.undo ? { label: T('撤销', 'Undo'), run: opts.undo } : opts.action;
  ui.lastUndo = opts.undo || null;
  // One global Sonner toaster (shell/toast.ts): bottom centre of the main screen.
  showToast(text, {
    lead: opts.lead,
    label: act?.label,
    run: act
      ? () => {
          act.run();
          ui.lastUndo = null;
        }
      : undefined,
  });
  announce(text);
}
function announce(text) {
  const el = document.getElementById('announcer');
  if (!el) return;
  el.textContent = '';
  setTimeout(() => {
    el.textContent = text;
  }, 30);
}

/* ---------- routing ---------- */
// #/ jobs · #/pm entry · #/work board · #/task/<id> task workbench · #/doc/<id> · #/bench · #/review
const WS = ['work', 'task', 'doc', 'bench'];
// Screens other lines register (shell/registry.ts) are drawn in the workspace's main screen.
WS.push(...registeredRouteNames());
onRouteRegistered((name) => WS.push(name));
function parseRoute() {
  const [r, id] = location.hash.replace(/^#\/?/, '').split('/');
  if (['pm', 'work', 'bench', 'review', 'engineer-report'].includes(r)) return { r, id: null };
  // #/lab/<row>: the system profile, scrolled to one recognizer (a lens card's way in).
  if (r === 'lab') return { r, id: id ? decodeURIComponent(id) : null };
  if ((r === 'task' || r === 'doc') && id) return { r, id: decodeURIComponent(id) };
  if (isRegisteredRoute(r)) return { r, id: id ? decodeURIComponent(id) : null };
  // The engineer's desk (#/engineer/<ticket>) and a review's report (#/engineer-review/<review>).
  if (ENGINEER_ROUTES.includes(r)) return { r, id: id ? decodeURIComponent(id) : null };
  return { r: '', id: null };
}
const hashOf = (r, id) => '#/' + r + (id ? '/' + encodeURIComponent(id) : '');
const pageTransition = createPageTransition(document, reduceMotion);
const withTransition = pageTransition.run;
// An undo belongs to the page it was offered on; leaving the page withdraws it.
function dropUndo() {
  if (ui.lastUndo) {
    ui.lastUndo = null;
    dismissToasts();
  }
}
function go(route, opts = {}) {
  commit();
  dropUndo();
  if ((WS.includes(route) || route === 'review') && !current()) route = 'pm';
  if (route === 'lab' && ui.route !== 'lab' && current()) ui.labReturn = hashOf(ui.route, ui.routeId);
  const id = opts.id || null;
  const from = ui.route,
    fromId = ui.routeId;
  const run = () => {
    if (sheet.open) closeSheet(true);
    ui.menu = null;
    ui.railOpen = false;
    ui.route = route;
    ui.routeId = id;
    const state = opts.aipmScreen
      ? { aipm: opts.aipmScreen, aipmSession: current()?.id }
      : null;
    if (route === 'work') Aipm.restoreHistory(state);
    if (!opts.aipmScreen || from !== route || fromId !== id || JSON.stringify(history.state) !== JSON.stringify(state))
      history.pushState(state, '', hashOf(route, id));
    render();
    window.scrollTo(0, 0);
    document.getElementById('main')?.scrollTo?.(0, 0);
  };
  if ((from === 'work' && route === 'doc') || (from === 'doc' && route === 'work')) {
    pageTransition.skip();
    documentMotion.transition(from, route, route === 'doc' ? id : fromId, run);
  } else {
    documentMotion.cancel();
    if (opts.transition) withTransition(run);
    else run();
  }
}
window.addEventListener('popstate', (event) => {
  commit();
  dropUndo();
  if (sheet.open) closeSheet(true);
  ui.menu = null;
  const from = ui.route,
    fromId = ui.routeId,
    p = parseRoute();
  if (p.r === 'lab' && from !== 'lab' && current()) ui.labReturn = hashOf(from, fromId);
  const update = () => {
    ui.route = p.r;
    ui.routeId = p.id;
    Aipm.restoreHistory(p.r === 'work' ? event.state : null);
    render();
    if (p.r === 'doc') document.getElementById('main')?.scrollTo(0, 0);
  };
  if ((from === 'work' && p.r === 'doc') || (from === 'doc' && p.r === 'work')) {
    pageTransition.skip();
    documentMotion.transition(from, p.r, p.r === 'doc' ? p.id : fromId, update);
  } else {
    documentMotion.cancel();
    withTransition(update);
  }
});

/* ---------- render ---------- */
function render() {
  const key = focusKey();
  if (ui.route == null) {
    const p = parseRoute();
    ui.route = p.r;
    ui.routeId = p.id;
  }
  // One practice, one language: inside a practice the interface speaks the practice's own
  // language; on home, the job page and the lab the preference does. A change redraws through
  // onLocaleChange, so this pass stops here.
  if (setPracticeLocale(practiceUiLocale())) return;
  const r = ui.route;
  // One practice, one role: the other role's screens are not this practice's (phase 2). A
  // practice from before roles has none and keeps both.
  const role = current() && inPractice() ? roleOf(current().id) : null;
  if (role === 'pm' && ENGINEER_ROUTES.includes(r)) {
    go('work');
    return;
  }
  if (role === 'engineer' && ['work', 'task', 'doc', 'bench', 'investigate', 'review'].includes(r)) {
    const ticket = lastTicket(current().id);
    go('engineer', ticket ? { id: ticket } : {});
    return;
  }
  if (r === 'task' && current() && !current().tasks.some((t) => t.id === ui.routeId)) {
    ui.route = 'work';
    ui.routeId = null;
    history.replaceState(null, '', hashOf('work'));
  }
  document.body.dataset.view = WS.includes(ui.route) ? 'work' : ui.route || 'careers';
  const banner = storageIssue
    ? `<div class="storage-alert" role="alert">${icon('info', 'i-sm')}<span>${esc(storageText())}</span>${btn(T('导出本地笔记', 'Export local notes'), 'export', 'small quiet')}${rawRecord && storageLocked ? btn(T('另存后重新开始', 'Back up and start fresh'), 'reset-storage', 'small quiet') : ''}</div>`
    : '';
  if (r === 'pm') app.innerHTML = banner + renderEntry();
  else if (WS.includes(ui.route) && current()) app.innerHTML = banner + renderWorkspace();
  else if (r === 'review' && current()) app.innerHTML = banner + renderReview();
  else if (r === 'lab') app.innerHTML = banner + renderLab();
  else if (r === 'engineer-report') app.innerHTML = banner + renderEngineerReport();
  else app.innerHTML = banner + renderCareers();
  afterRender();
  restoreFocus(key);
}
// Being on a hat's own screen puts that hat on; the desk's ticket is remembered for the switch.
const ticketOf = (id) => {
  const t = String(id || '').split('?')[0];
  return t.startsWith('ticket-') ? t : null;
};
function syncHat() {
  const a = current();
  if (!a || !inPractice()) return;
  // Only a real ticket is worth coming back to (not the intro or the revision page, whose id
  // part is "?intro…"); a query after the id is not part of it.
  const ticketId = ticketOf(ui.routeId);
  if (ui.route === 'engineer' && ticketId) setLastTicket(a.id, ticketId);
  if (ENGINEER_ROUTES.includes(ui.route)) setHat(a.id, 'engineer');
  else if (WS.slice(0, 4).includes(ui.route) || ui.route === 'review') setHat(a.id, 'pm');
}
function mountNativeSlots() {
  L.mountV4(current(), {
    taskId: task()?.id || null,
    productId: ui.obj?.type === 'work' ? ui.obj.id : null,
  });
}
function renderLab() {
  const back = `<a class="btn quiet back" href="${current() ? ui.labReturn || (hatHere(current()) === 'engineer' ? '#/engineer' : '#/work') : '#/'}">${icon('back')}<span>${esc(current() ? T('返回工作区', 'Back to your work') : T('首页', 'Home'))}</span></a>`;
  return `${topbar(back)}<main id="main" class="page rc-lab" data-rc-lab tabindex="-1"></main>`;
}
// The lab keeps its element across redraws: mounted once per entry into the route, and
// again only when the language or the practice changes (its data stay cached).
let labView = null;
function mountLabPage() {
  const slot = document.querySelector('[data-rc-lab]');
  if (!slot) return;
  const a = current();
  const sessionKey = a && L.nativeWorkspace(a) ? a.id : '';
  const key = `${locale()}|${sessionKey}`;
  document.title = T(`系统剖面 · ${PRODUCT_NAME}`, `System profile · ${PRODUCT_NAME}`);
  const skip = document.querySelector('.skip-link');
  if (skip) skip.textContent = T('跳到主要内容', 'Skip to content');
  if (labView?.key === key) {
    slot.replaceWith(labView.el);
    labJump(ui.routeId);
    return;
  }
  const refresh = !labView;
  labView = { key, el: slot };
  // How many times this practice was submitted: the lab numbers deliveries only when their
  // sentence records match these one to one.
  const events = sessionKey ? sessionOf(a)?.timeline?.events : null;
  const submitted = Array.isArray(events)
    ? events.filter((e) => e?.event_type === 'submitted').length
    : null;
  import('../features/recognition-lab/lab').then(({ mountLab }) =>
    mountLab(slot, {
      language: locale(),
      session: sessionKey ? () => L.recognition(a) : null,
      sessionKey,
      refresh,
      submitted,
    }).then(() => labJump(ui.routeId)),
  );
}
// Opened from a lens card (#/lab/<row>): its recognizer's entry in the register, focused.
function labJump(row) {
  const entry = row && document.getElementById(`rc-${row}`);
  if (!entry) return;
  entry.scrollIntoView({ block: 'start', behavior: reduceMotion.matches ? 'auto' : 'smooth' });
  entry.setAttribute('tabindex', '-1');
  entry.focus({ preventScroll: true });
  entry.dataset.jumped = '';
}
// #/engineer-report: read-only sample regression reports; the page keeps itself across re-renders.
function renderEngineerReport() {
  const back = `<a class="btn quiet back" href="#/">${icon('back')}<span>${esc(T('首页', 'Home'))}</span></a>`;
  return `${topbar(back)}<main id="main" class="page" data-engineer-report-page tabindex="-1"></main>`;
}
function mountEngineerReportRoute() {
  document.title = T(
    `回归报告样例 · ${PRODUCT_NAME}`,
    `Regression report sample · ${PRODUCT_NAME}`,
  );
  const root = document.querySelector('[data-engineer-report-page]');
  if (root)
    import('../features/engineer-report/page').then((m) => {
      if (root.isConnected) m.mountEngineerReportPage(root, { language: locale() });
    });
}
function afterRender() {
  afterShellRender();
  Greetings.mountGreetings(
    (WS.includes(ui.route) || ENGINEER_ROUTES.includes(ui.route) || isRegisteredRoute(ui.route)) &&
      current() &&
      statusOf(current()) === 'active'
      ? current().id
      : null,
    locale(),
  );
  discoverRole(current());
  syncHat();
  mountShellBar();
  refreshAgentIssued();
  if (ui.route !== 'lab') labView = null;
  // The arrival is played once; cards drawn later (the native board mounts after this render)
  // still settle in with it, but a later redraw of the lanes does not replay it.
  const arriving = document.querySelector('.ws.arriving');
  if (arriving) setTimeout(() => arriving.classList.remove('arriving'), 1400);
  if (ui.route === 'lab') {
    mountLabPage();
    return;
  }
  if (ui.route === 'engineer-report') {
    mountEngineerReportRoute();
    return;
  }
  mountNativeSlots();
  const registered = registeredRoute(ui.route);
  const stageRoot = registered && document.getElementById('ws-stage');
  if (stageRoot) registered.mount?.(stageRoot);
  if (ui.route === 'review' && current() && L.nativeWorkspace(current()))
    loadRecognitionSummary(current());
  // Only the workbench's own scroll regions move; browser focus must not shift
  // the entire fixed-height workspace (especially after viewport changes).
  if (WS.includes(ui.route) && window.scrollY) window.scrollTo(0, 0);
  document.querySelectorAll('.segmented').forEach(layoutSegmented);
  const body = document.getElementById('editor-body');
  if (body) autoGrow(body);
  // A native thread keeps its own place (it follows new messages only while you are at the end).
  document.querySelectorAll('.thread').forEach((t) => {
    if (!t.closest('[data-v4-region]')) t.scrollTop = t.scrollHeight;
  });
  updateSave();
  syncPanels();
  markRead();
  markNotesRead();
  refreshGreeting();
  const a = current();
  const activeWork = a && ui.obj?.type === 'work' ? artifact() : null;
  if (activeWork?.kind === 'investigation') loadInvestigationSources(a, shown(activeWork));
  document.title =
    (WS.includes(ui.route) || ui.route === 'review') && a
      ? `${caseOf(a).title} · ${PRODUCT_NAME}`
      : T(`${PRODUCT_NAME} · 在真实的工作里练习`, `${PRODUCT_NAME} · Learn on real work`);
  const skip = document.querySelector('.skip-link');
  if (skip) skip.textContent = T('跳到主要内容', 'Skip to content');
  documentMotion.sync();
  workFolders.sync();
}
function layoutSegmented(seg) {
  const active = seg.querySelector('[aria-pressed="true"]');
  const thumb = seg.querySelector('.thumb');
  if (!thumb) return;
  if (!active) {
    thumb.style.opacity = '0';
    return;
  }
  thumb.style.opacity = '1';
  thumb.style.width = active.offsetWidth + 'px';
  thumb.style.transform = `translateX(${active.offsetLeft - 2}px)`;
}
const nativeGrow = window.CSS && CSS.supports && CSS.supports('field-sizing', 'content');
function autoGrow(el) {
  if (nativeGrow) return;
  // The desk scrolls, not the window; keep its position while the field resizes.
  const box = el.closest('.desk');
  const y = box ? box.scrollTop : window.scrollY;
  el.style.height = 'auto';
  el.style.height = Math.max(el.scrollHeight, 320) + 'px';
  if (box) box.scrollTop = y;
  else if (window.scrollY !== y) window.scrollTo(0, y);
}
function focusKey() {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  if (el.id && el.id !== 'main')
    return {
      id: el.id,
      pos: el.selectionStart ?? null,
      end: el.selectionEnd ?? null,
      direction: el.selectionDirection ?? 'none',
    };
  if (el.tagName === 'SUMMARY' && el.parentElement?.dataset.key)
    return {
      sel: `.investigation-work details[data-key="${CSS.escape(el.parentElement.dataset.key)}"] > summary`,
    };
  const d = el.dataset || {};
  const parts = [
    'action',
    'id',
    'view',
    'role',
    'rail',
    'change',
    'case',
    'key',
    'menu',
    'lang',
    'status',
    'mode',
    'investigationReview',
    'docRow',
  ]
    .filter((k) => d[k] !== undefined)
    .map(
      (k) => `[data-${k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase())}="${CSS.escape(d[k])}"]`,
    );
  return parts.length ? { sel: el.tagName.toLowerCase() + parts.join('') } : null;
}
function restoreFocus(key) {
  if (!key) return;
  const el = key.id ? document.getElementById(key.id) : document.querySelector(key.sel);
  if (!el || el === document.activeElement) return;
  el.focus({ preventScroll: true });
  if (key.pos != null && el.setSelectionRange)
    try {
      el.setSelectionRange(key.pos, key.end ?? key.pos, key.direction || 'none');
    } catch (_) {
      /* not a text field */
    }
}

/* ---------- shared chrome ---------- */
const wordmark = () =>
  `<button type="button" class="wordmark" data-action="home" aria-label="${esc(T(`${PRODUCT_NAME}，回到岗位选择`, `${PRODUCT_NAME}, back to jobs`))}"><span class="wordmark-glyph" aria-hidden="true"></span><span class="wordmark-text">${esc(PRODUCT_NAME)}</span></button>`;
const backBtn = (action, label) =>
  `<button type="button" class="btn quiet back" data-action="${action}">${icon('back')}<span>${esc(label)}</span></button>`;
function langControl() {
  return `<div class="menu-wrap"><button type="button" class="btn quiet lang-btn" data-action="menu" data-menu="lang" aria-haspopup="menu" aria-expanded="${ui.menu === 'lang'}" aria-label="${esc(T('界面语言：中文', 'Interface language: English'))}">${icon('globe', 'i-sm')}<span class="lang-now">${locale() === 'zh' ? '中文' : 'EN'}</span></button>${ui.menu === 'lang' ? langMenu() : ''}</div>`;
}
function langItems() {
  const pref = getPreference();
  const item = (v, label, sub = '') =>
    `<button type="button" role="menuitemradio" aria-checked="${pref === v}" data-action="set-lang" data-lang="${v}"><span class="grow">${label}${sub ? `<small>${sub}</small>` : ''}</span>${pref === v ? icon('check', 'i-sm') : ''}</button>`;
  return `${item('auto', T('跟随系统', 'Match system'), detect() === 'zh' ? '中文' : 'English')}${item('zh', '中文')}${item('en', 'English')}`;
}
function langMenu() {
  if (practiceLocale()) return practiceLangNote();
  return `<div class="menu right" role="menu">${langItems()}</div>`;
}
// The language of the practice on screen, or null off a practice (home, job page, lab, samples).
function practiceUiLocale() {
  const a = current();
  if (!a) return null;
  const r = ui.route;
  const here = WS.includes(r) || r === 'review' || r === 'lab' || ENGINEER_ROUTES.includes(r) || isRegisteredRoute(r);
  return here ? workLang(a) : null;
}
// Inside a practice the language is the practice's: say so instead of offering a half switch.
function practiceLangNote() {
  return `<div class="menu right lang-note" role="dialog" aria-label="${esc(T('界面语言', 'Language'))}"><p class="lang-note__head">${icon('globe', 'i-sm')}<span>${T('这一局是中文的', 'This practice is in English')}</span></p><p class="lang-note__body">${T('想用英文练，回首页切换语言，再开一局。', 'To practise in Chinese, change the language on the home page and start a new practice.')}</p>${btn(T('回首页', 'Go home'), 'home', 'small')}</div>`;
}
// Inside a practice every screen (board, result, sign-off desk, registered screens) shares one
// shell bar; elsewhere (home, job page, lab) the light topbar stays.
const inPractice = () =>
  !!current() &&
  (WS.includes(ui.route) || ui.route === 'review' || ENGINEER_ROUTES.includes(ui.route));
const topbar = (left, right = '') =>
  inPractice()
    ? shellBar(current(), {
        // The result page and the desk are peers of the board: the hat and the scale lead there.
        back: ui.route === 'review' || ui.route === 'engineer' ? '' : left,
        more: right,
      })
    : `<header class="topbar">${left}<div class="spacer"></div>${right}${langControl()}</header>`;
const letter = (role, quote, size = '') =>
  `<figure class="letter ${size}">${avatar(role, size === 'sm' ? 'sm' : size === 'lg' ? 'lg' : 'md')}<div class="letter-body"><blockquote>${esc(quote)}</blockquote><figcaption>${PEOPLE[role].name}${PEOPLE[role].titled ? '' : `<span>${ROLE_TITLE(role)}</span>`}</figcaption></div></figure>`;
// The manager's brief, plus one line in the manager's own voice on what to hand back, by when
// and where: the decision and its evidence, before the launch day the situation sets, through
// Submit at the top right. The day comes from the practice's own state; without it, no line.
function briefDirection(a) {
  const day = a?.world?.deadline;
  if (!Number.isFinite(day)) return '';
  return worldText(a)(
    `第 ${day} 天上线前，把你的试点决定和依据交给我。写好了，点右上角的「交付」。`,
    `Before launch on day ${day}, bring me your pilot decision and the evidence behind it. When it is ready, use Submit at the top right.`,
  );
}
const briefLetter = (a, size = '') => {
  const direction = briefDirection(a);
  const p = PEOPLE.manager;
  return `<figure class="letter brief-letter ${size}">${avatar('manager', size === 'sm' ? 'sm' : 'md')}<div class="letter-body"><blockquote${langOf(a)}>${esc(caseOf(a).quote)}</blockquote>${direction ? `<blockquote class="brief-direction" data-brief-direction${langOf(a)}>${esc(direction)}</blockquote>` : ''}<figcaption>${p.name}${p.titled ? '' : `<span>${ROLE_TITLE('manager')}</span>`}</figcaption></div></figure>`;
};
const facts = (w) => [
  ['seats', T(`${w.capacity} 人容量`, `${w.capacity} seats`)],
  ['hours', T(`${w.devDays} 人日开发`, `${w.devDays} person-days`)],
  ['calendar', T(`第 ${w.deadline} 天上线`, `Launch on day ${w.deadline}`)],
  [
    'sync',
    T(`索引最多滞后 ${INDEX_DELAY_HOURS} 小时`, `Index up to ${INDEX_DELAY_HOURS} h behind`),
  ],
];
const FACT_KEYS = ['capacity', 'devDays', 'deadline', 'delay'];
const factRow = (w, cls = '') =>
  `<ul class="facts ${cls}">${facts(w)
    .map(
      ([i, l], n) =>
        `<li class="${ui.changed && ui.changed.until > Date.now() && ui.changed.keys.includes(FACT_KEYS[n]) ? 'changed' : ''}">${icon(i, 'i-sm')}<span>${l}</span></li>`,
    )
    .join('')}</ul>`;
function priPick(id, p, title, change = 'priority') {
  return `<label class="pri-pick" title="${esc(PRI(p))}">${priMark(p)}<select aria-label="${esc(T(`「${title}」的优先级：${PRI(p)}`, `Priority for “${title}”: ${PRI(p)}`))}" data-change="${change}" data-id="${esc(id)}" data-title="${esc(title)}">${['first', 'next', 'later'].map((k) => `<option value="${k}" ${k === p ? 'selected' : ''}>${PRI(k)}</option>`).join('')}</select></label>`;
}

/* ---------- 1. jobs ---------- */
// Home: two role scenes and their entry actions (screens/home). A practice
// under way shows first, as a continue slip with the hat on and its stage.
function renderCareers() {
  // A practice in a hidden situation (reopened with a continue code) is not offered here.
  const a = current() && caseShown(current().scenarioId) ? current() : null;
  return homeHtml({
    topbar: topbar(wordmark()),
    quote: CASE('pilot').quote,
    capacity: worldOf('pilot').capacity,
    resume: a ? continueInfo(a) : null,
    continueCode: recovery.homeLink(),
  });
}
// The continue slip's words: the hat this practice is worn with and, for each hat worn, the step
// its scale is on (shell stage.ts; the engineer's scale is 201's).
const STEP_STATUS = {
  investigate: ['调查中', 'Investigating'],
  decide: ['决定中', 'Deciding'],
  delivered: ['已交付', 'Delivered'],
};
function stepWords(hat, a) {
  const steps = stageOf(hat, a)?.steps || [];
  const at = steps.find((x) => x.state === 'current') || steps.filter((x) => x.state === 'done').at(-1);
  const words = at && (STEP_STATUS[at.id] || at.label);
  if (words) return T(words[0], words[1]);
  return hat === 'engineer' ? T('委托进行中', 'Ticket in progress') : '';
}
function continueInfo(a) {
  const submitted = statusOf(a) === 'submitted';
  return {
    id: a.id,
    title: CASE(a.scenarioId).title,
    hat: hatOf(a.id),
    stage: submitted ? T('已交付', 'Delivered') : stepWords('pm', a),
    submitted,
    engineer: everEngineer(a.id) ? { stage: stepWords('engineer', a) } : null,
    lang: workLang(a),
  };
}

/* ---------- 2. PM entry ---------- */
// The job page: one brief on paper (readouts, the three starting tasks, Take this on), the
// variants in one line under it, then your own business, continue codes and past practice.
function renderEntry() {
  const last = (id) => state.attempts.filter((a) => a.scenarioId === id).at(-1);
  const open = (x) => (x && statusOf(x) !== 'submitted' ? x.id : null);
  const attempts = state.attempts.filter((x) => caseShown(x.scenarioId)).reverse();
  const c = CASE('pilot');
  const base = worldOf('pilot');
  return entryHtml({
    topbar: topbar(backBtn('home', T('岗位', 'Jobs'))),
    caseId: 'pilot',
    title: c.title,
    quote: c.quote,
    minutes: c.minutes,
    readouts: caseReadouts('pilot'),
    seeds: SEED_KEYS.map(seedText),
    existingId: open(last('pilot')),
    holding: ui.walkIn,
    variants: [
      {
        id: 'urgent',
        label: T('上线提前到第', 'Launch moves up to day'),
        value: worldOf('urgent').deadline,
        was: String(base.deadline),
        openId: open(last('urgent')),
      },
      {
        id: 'capacity',
        label: T('容量只剩', 'Seats drop to'),
        value: worldOf('capacity').capacity,
        was: String(base.capacity),
        openId: open(last('capacity')),
      },
    ].filter((v) => caseShown(v.id)),
    after: `<section class="block">${intakeBlock()}</section>${recovery.entry()}${attempts.length ? practiceList(attempts) : ''}`,
  });
}
const worldOf = (id) => {
  const s = scen(id);
  return { capacity: s.capacity, devDays: 3, deadline: s.deadline };
};
// What the situation asks for, as numbers with names. A variant marks the one that changed.
function caseReadouts(id) {
  const w = worldOf(id);
  const base = worldOf('pilot');
  return [
    {
      label: T('试点容量', 'Capacity'),
      value: w.capacity,
      unit: T('人', 'seats'),
      was: w.capacity !== base.capacity ? String(base.capacity) : '',
    },
    { label: T('可用开发', 'Engineering'), value: w.devDays, unit: T('人日', 'person-days') },
    {
      label: T('期望上线', 'Launch target'),
      pre: T('第', 'Day'),
      value: w.deadline,
      unit: T('天', ''),
      was: w.deadline !== base.deadline ? String(base.deadline) : '',
    },
    { label: T('索引最长滞后', 'Max index lag'), value: INDEX_DELAY_HOURS, unit: T('小时', 'h') },
  ];
}
function matchIntake(text) {
  const raw = String(text || '').trim();
  if (!raw) return { status: 'empty' };
  const find1 = (re) => {
    const m = raw.match(re);
    return m ? m[0] : null;
  };
  const topic = find1(
    /知识助手|知识库|问答|FAQ|政策查询|查政策|内部助手|knowledge (?:base|assistant)|Q&A|\bassistant\b|\bchatbot\b/i,
  );
  const internal = find1(
    /员工|同事|内部|行政|人事|\bHR\b|\bstaff\b|\binternal\b|\bemployees?\b|\bcolleagues?\b/i,
  );
  const external = find1(/外部客户|顾客|消费者|买家|\bcustomers?\b|\bshoppers?\b|\bclients?\b/i);
  const other = find1(/推荐|排序|广告|\brecommend\w*|\branking\b|\badverts?\b/i);
  const policy = find1(/差旅|报销|政策|\bpolic(?:y|ies)\b|\btravel\b|\bexpenses?\b/i);
  if (!topic && !policy) return { status: 'none', text: raw.slice(0, 2000) };
  const fits = [];
  const gaps = [];
  if (internal) fits.push(['internal', internal]);
  if (policy) fits.push(['policy', policy]);
  const pilot = find1(/试点|小范围|一部分人|先给|\bpilot\b|\btrial\b|\ba few\b/i);
  if (pilot) fits.push(['pilot', pilot]);
  const week = find1(/一周|下周|7 ?天|\bnext week\b|\bone week\b|\ba week\b/i);
  if (week) fits.push(['week', week]);
  if (external) gaps.push(['external', external]);
  if (other) gaps.push(['other', other]);
  const scale = find1(/\d{2,}\s*(?:人|名|位|people|staff|employees|users)(?![日天])/i);
  if (scale) gaps.push(['scale', scale]);
  if (!fits.length) fits.push(['decision', '']);
  return {
    status: external || other ? 'partial' : 'matched',
    template: 'pilot',
    text: raw.slice(0, 2000),
    fits,
    gaps,
  };
}
const FIT = ([k, q]) =>
  ({
    internal: T(`使用者是内部员工（你写了“${q}”）`, `Users are internal staff (you wrote “${q}”)`),
    policy: T(
      `要回答会变化的政策（你写了“${q}”）`,
      `It answers policy that changes (you wrote “${q}”)`,
    ),
    pilot: T(`先做小范围试点（你写了“${q}”）`, `It starts as a small pilot (you wrote “${q}”)`),
    week: T(`一周左右上线（你写了“${q}”）`, `Launch in about a week (you wrote “${q}”)`),
    decision: T('一个知识助手的上线决定', 'A launch decision for a knowledge assistant'),
    external: T(
      `面向外部客户（你写了“${q}”）：本情境只覆盖内部员工`,
      `External customers (you wrote “${q}”): this situation covers staff only`,
    ),
    other: T(
      `“${q}”类功能：本情境只覆盖知识问答`,
      `“${q}”: this situation covers knowledge Q&A only`,
    ),
    scale: T(`规模“${q}”：本情境沿用 30 人容量`, `Scale “${q}”: this situation keeps 30 seats`),
  })[k] || '';
const intakeLines = (list, legacy) =>
  Array.isArray(list) && list.length ? list.map(FIT) : legacy || [];
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
  if (r.status === 'empty')
    return `<p class="intake-result muted">${T('先写一句你想练的业务。', 'Write a sentence about the business first.')}</p>`;
  if (r.status === 'none')
    return `<div class="intake-result" tabindex="-1"><p class="intake-head">${T('这个情境现在还练不了', 'This one cannot be practised yet')}</p><p class="muted">${T('目前审核过的只有“内部知识助手上线决定”。', 'The only reviewed situation is a launch decision for an internal knowledge assistant.')}</p><div class="row-actions">${btn(T('改练内部知识助手上线决定', 'Practise the knowledge assistant launch instead'), 'take-case', '', 'data-case="pilot"')}</div></div>`;
  const cols = `<div class="intake-cols"><ul class="ticks">${intakeLines(r.fits)
    .map((x) => `<li>${icon('check', 'i-sm')}${esc(x)}</li>`)
    .join('')}</ul>${
    r.gaps.length
      ? `<ul class="ticks muted">${intakeLines(r.gaps)
          .map((x) => `<li>${icon('minus', 'i-sm')}${esc(x)}</li>`)
          .join('')}</ul>`
      : ''
  }</div>`;
  return `<div class="intake-result" tabindex="-1"><p class="intake-head">${r.status === 'partial' ? T('只能借用「知识助手试点」的决策结构', 'Only the decision structure of the pilot carries over') : T('最接近「知识助手试点」', 'Closest match: the knowledge assistant pilot')}</p>${cols}<div class="row-actions">${btn(r.status === 'partial' ? T('仍用这个情境开始', 'Start with it anyway') : T('用这个情境开始', 'Start with this situation'), 'start-intake', r.status === 'partial' ? '' : 'primary')}</div></div>`;
}
function practiceList(list) {
  return `<section class="block"><h2 class="section-title">${T('我的练习', 'My practice')}</h2><div class="list">${list
    .slice(0, 6)
    .map((a) => {
      const st = statusOf(a);
      const label =
        st === 'submitted'
          ? T('已交付', 'Submitted')
          : st === 'paused'
            ? T('已暂停', 'Paused')
            : T('进行中', 'In progress');
      return `<div class="list-row"><span class="resume-icon">${icon('note', 'i-sm')}</span><div class="grow"><p class="row-title">${esc(CASE(a.scenarioId).title)}${a.practiceOrigin ? `<span class="tag">${T('补练', 'Practice round')}</span>` : ''}</p><p class="row-sub">${label}${recovery.since(a.createdAt, sessionOf(a))}</p></div>${st === 'submitted' ? btn(T('看结果', 'See the result'), 'review-attempt', 'small quiet', `data-id="${a.id}"`) : ''}${btn(T('打开', 'Open'), 'resume-attempt', 'small', `data-id="${a.id}"`)}</div>`;
    })
    .join('')}</div></section>`;
}

/* ---------- 3. workspace: the board, a task's workbench, a document, the test bench ---------- */
// Two levels. The board shows the whole job: the brief and its conditions, the product
// under test, every task by priority, every document. A task opens its own workbench:
// its work, documents and tests on the left, the open item in the middle. The right
// rail keeps the team and the context: talk, feedback, my agent, activity.
function renderWorkspace() {
  const a = current();
  const arriving = ui.arriving;
  ui.arriving = false;
  ui.landing = arriving;
  ui.notesCache = Coach.notes(a, E);
  const html = `<div class="ws view-${ui.route} ${arriving ? 'arriving' : ''} ${ui.railOpen ? 'rail-open' : ''}" data-status="${statusOf(a)}">
    ${wsToolbar(a)}
    <main id="main" class="stage" tabindex="-1"><div id="ws-stage" class="stage-inner" ${L.nativeWorkspace(a) ? 'data-v4-region="workspace"' : ''}>${progressSlot(a)}${aipmScreen(a) ? '' : wsStage(a)}</div></main>
    ${docLayer()}
    <aside class="rail" id="ws-rail" aria-label="${esc(T('同事与需要你回应的事', 'Colleagues and what needs you'))}">${wsRail(a)}</aside>
    <button type="button" class="scrim" data-action="close-panels" aria-label="${esc(T('关闭面板', 'Close panel'))}" tabindex="-1"></button>
    ${recordsDrawer()}
  </div>`;
  ui.landing = false;
  requestAnimationFrame(boardSettle);
  return html;
}
const routeTask = (a) =>
  ui.route === 'task' ? a.tasks.find((t) => t.id === ui.routeId) || null : null;
function wsToolbar(a) {
  const t = routeTask(a);
  const m = ui.route === 'doc' ? E.getMaterials(a).find((x) => x.id === ui.routeId) : null;
  // A screen another line registered (My agent…) is worn in the practice's hat: in the
  // engineer's, "back" leads to the sign-off desk, not the product manager's board. The desk
  // itself is the engineer's home screen (no way back, like the board); its report and any
  // other screen go back to it.
  const deskBack =
    isRegisteredRoute(ui.route) && ui.route !== 'engineer' && hatHere(a) === 'engineer';
  const ticket = deskBack ? ticketOf(lastTicket(a.id)) : null;
  const home = homePill(a);
  const back =
    ui.route === 'work' || (ui.route === 'engineer' && isRegisteredRoute('engineer')) || home
      ? ''
      : deskBack
        ? ticket
          ? `<a class="btn quiet back up" style="text-decoration: none" href="${esc(hashOf('engineer', ticket))}">${icon('back')}<span>${T('签字台', 'Sign-off desk')}</span></a>`
          : `<button type="button" class="btn quiet back up" data-action="hat-switch" data-hat="engineer">${icon('back')}<span>${T('签字台', 'Sign-off desk')}</span></button>`
        : `<button type="button" class="btn quiet back up" data-action="to-board">${icon('back')}<span>${T('工作板', 'Board')}</span></button>`;
  const here = home
    ? ''
    : t
    ? `<span class="crumb-sep">${icon('chev', 'i-xs')}</span><span class="crumb-now">${esc(taskTitle(t))}</span>`
    : m
      ? `<span class="crumb-sep">${icon('chev', 'i-xs')}</span><span class="crumb-now">${esc(materialTitle(m))}</span>`
      : ui.route === 'bench'
        ? `<span class="crumb-sep">${icon('chev', 'i-xs')}</span><span class="crumb-now">${T('测试台', 'Test bench')}</span>`
        : '';
  return shellBar(a, { back, here, home, id: 'ws-toolbar', cls: 'ws-toolbar', brief: true });
}
/* ---------- the way back to the workbench ---------- */
// Wherever a product manager is in a practice other than the workbench, one pill at the top
// centre takes them back: "Workbench › where you are". The workbench itself shows none.
function awayFrom(a) {
  if (!a || hatHere(a) !== 'pm') return null;
  if (ui.docSheet) {
    const m = E.getMaterials(a).find((x) => x.id === ui.docSheet);
    return m ? materialTitle(m) : T('资料', 'Material');
  }
  if (ui.route === 'work') return aipmHere(a) ? Aipm.screenName(a) : null;
  const t = routeTask(a);
  if (t) return taskTitle(t);
  if (ui.route === 'doc') {
    const m = E.getMaterials(a).find((x) => x.id === ui.routeId);
    return m ? materialTitle(m) : T('资料', 'Material');
  }
  const named = {
    bench: T('测试台', 'Test bench'),
    agent: T('我的 Agent', 'My agent'),
    review: T('交付结果', 'Delivery result'),
    investigate: T('调查记录', 'Findings'),
  };
  return named[ui.route] ?? null;
}
function homePill(a) {
  const where = awayFrom(a);
  if (!where) return '';
  return `<button type="button" class="ws-home" data-action="to-workbench" aria-label="${esc(T(`回到工作台，当前在：${where}`, `Back to the workbench, now in: ${where}`))}"><span class="ws-home__go">${icon('board', 'i-sm')}<span>${T('工作台', 'Workbench')}</span></span><span class="ws-home__sep" aria-hidden="true">›</span><span class="ws-home__here"${langOf(a)}>${esc(where)}</span></button>`;
}
function toWorkbench() {
  const a = current();
  if (ui.docSheet) {
    ui.docSheet = null;
    ui.compare = false;
    refreshWS(['overlay', 'toolbar']);
  }
  if (a && aipmHere(a)) Aipm.host.openWorkbench();
  if (ui.route !== 'work') go('work', { transition: true });
}
/* ---------- the shell bar (decision 1) ---------- */
// The situation's own name, for a hat that has no title of its own yet (the engineer's, until
// its line registers one): never the product manager's question.
const SITUATION = {
  pilot: ['知识助手试点', 'Knowledge-assistant pilot'],
  urgent: ['知识助手试点 · 期限提前', 'Knowledge-assistant pilot, earlier deadline'],
  capacity: ['知识助手试点 · 容量受限', 'Knowledge-assistant pilot, limited capacity'],
  itticket: ['IT 工单助手试点', 'IT ticket-assistant pilot'],
};
const situationName = (a) => {
  const n = SITUATION[a.scenarioId] || SITUATION.pilot;
  return T(n[0], n[1]);
};
// Which hat this screen is worn in: the desk and its reports are the engineer's, the board and
// the result the product manager's; screens other lines register follow the practice's hat.
function hatHere(a) {
  if (ENGINEER_ROUTES.includes(ui.route)) return 'engineer';
  if (WS.slice(0, 4).includes(ui.route) || ui.route === 'review') return 'pm';
  return hatOf(a.id);
}
function shellBar(
  a,
  { back = '', here = '', home = '', more = '', id = '', cls = '', brief = false } = {},
) {
  const st = statusOf(a);
  const n = snap();
  const s = sessionOf(a);
  const conn = !n.connected
    ? `<button type="button" class="conn" data-action="live-refresh" aria-label="${esc(T('离线，重试连接', 'Offline, retry connection'))}" title="${esc(T('连接不上后端，点击重试', 'Cannot reach the server. Click to retry.'))}"><span class="conn-dot"></span><span class="conn-label">${T('离线 · 重试', 'Offline · Retry')}</span></button>`
    : s?.pending && !s.pending.jobId && !n.busy
      ? `<button type="button" class="conn warn" data-action="live-retry" title="${esc(T('上一个操作没有得到确认，点击用原请求重试', 'The last action was not confirmed. Retry the same request.'))}">${icon('refresh', 'i-sm')}${T('待确认', 'Unconfirmed')}</button>`
      : '';
  const typing = typingRole(a);
  const replying = replyingRoles(a);
  // The title is what this hat is working on: the case's question for the product manager, the
  // ticket for the engineer (its line registers it as Stage.title; until then a neutral name).
  const hat = hatHere(a);
  const own = stageOf(hat, a)?.title;
  const titleText =
    hat === 'engineer'
      ? `<span class="title-text">${esc(own ? T(own[0], own[1]) : situationName(a))}</span>`
      : `<span class="title-text" style="view-transition-name: case-title"${langOf(a)}>${esc(own ? T(own[0], own[1]) : caseOf(a).title)}</span>`;
  const title =
    brief && hat === 'pm'
      ? `<div class="menu-wrap title-wrap"><h1 class="ws-title"><button type="button" class="title-btn" data-action="menu" data-menu="brief" aria-expanded="${ui.menu === 'brief'}" aria-haspopup="dialog" title="${esc(T('委托与条件', 'Brief and conditions'))}">${titleText}</button></h1>${ui.menu === 'brief' ? briefPopover(a) : ''}</div>`
      : `<p class="ws-title"><span class="title-btn">${titleText}</span></p>`;
  // Phone width keeps a way out even where the wide bar has none.
  const narrowBack =
    back || home
    ? ''
    : `<button type="button" class="btn quiet back narrow-only" data-action="to-entry" aria-label="${esc(T('离开练习', 'Leave the practice'))}">${icon('back')}</button>`;
  const c = agentConnection();
  const { label: lampLabel, title: lampTitle, state: lampState } = lampText(c);
  const lamp = `<button type="button" class="agent-lamp" data-action="open-agent" data-state="${lampState}" title="${esc(lampTitle)}" aria-label="${esc(`${lampTitle}: ${lampLabel}`)}"><span class="lamp rc-agent-light" data-state="${lampState}" aria-hidden="true"><span class="lamp-ring"></span></span><span class="lamp-label">${esc(lampLabel)}</span></button>`;
  const record = `<button type="button" class="btn quiet icon icon-key record-btn" data-action="records" aria-label="${esc(T('记录', 'Record'))}" title="${esc(T('记录', 'Record'))}">${icon('hours', 'i-sm')}</button>`;
  const moreWrap =
    more ||
    `<div class="menu-wrap">${btn(icon('more'), 'menu', 'icon quiet icon-key', `data-menu="more" aria-haspopup="menu" aria-expanded="${['more', 'lang', 'model'].includes(ui.menu)}" aria-label="${esc(T('更多', 'More'))}"`)}${ui.menu === 'more' ? moreMenu(a) : ui.menu === 'lang' ? langMenu() : ui.menu === 'model' && modelStatusOf(a) ? modelPopoverHtml(modelStatusOf(a)) : ''}</div>`;
  return `<header class="topbar shell-bar ${cls} ${barFolds.join(' ')}" ${id ? `id="${id}"` : ''} data-hat="${hat}"${home ? ` data-away${homeInline ? ' data-home-inline' : ''}` : ''}>
    ${back}${narrowBack}${wordmark()}<span class="sep before-title" aria-hidden="true"></span>
    <nav class="crumbbar" aria-label="${esc(T('位置', 'Location'))}">${title}${here}</nav>
    ${/* Delivered is the scale's to say; the chip stays only for states the scale does not show. */ ''}
    ${st !== 'active' && (st !== 'submitted' || s?.v2ReadOnly) ? `<span class="state-chip ${st}">${s?.v2ReadOnly ? T('旧版 · 只读', 'Earlier version · Read-only') : T('已暂停', 'Paused')}</span>` : ''}
    <span class="sep before-hat" aria-hidden="true"></span>
    ${islandSlot('shell-hatscale')}
    ${home}
    <div class="spacer"></div>
    <button type="button" class="team-btn" data-action="open-rail" aria-label="${esc(T('团队', 'Team'))}">${ROLES.map((r) => avatar(r, 'sm', { typing: typing === r || replying.has(r), dot: true })).join('')}<span class="team-compact">${icon('team', 'i-sm')}${unreadBadge(ROLES.reduce((n, r) => n + unread(a, r), 0))}</span></button>
    <span class="shell-connection">${conn}</span>${lamp}${record}${moreWrap}
    ${islandSlot('shell-primary')}
  </header>`;
}
/** Mounts or updates the bar's islands after a render: hat + scale, and the primary key. */
function mountShellBar() {
  const a = current();
  if (!a || !document.querySelector('[data-island="shell-hatscale"]')) return;
  requestAnimationFrame(fitShellBar);
  const hat = hatHere(a);
  const stage = stageOf(hat, a);
  const steps = (stage?.steps || []).map((x) => ({
    id: x.id,
    label: T(x.label[0], x.label[1]),
    state: x.state,
  }));
  const delivered = steps.length > 0 && steps.every((x) => x.state === 'done');
  const at = delivered
    ? steps.length - 1
    : Math.max(
        0,
        steps.findIndex((x) => x.state === 'current'),
      );
  const stepName = steps.length
    ? T(
        `第 ${at + 1} 步，共 ${steps.length} 步：${steps[at].label}`,
        `Step ${at + 1} of ${steps.length}: ${steps[at].label}`,
      )
    : '';
  keepIsland('shell-hatscale', HatScale, {
    hat,
    hats: {
      pm: T('产品经理', 'Product manager'),
      engineer: T('工程师', 'Engineer'),
      label: T('帽子', 'Hat'),
      busy: T('正在换帽子', 'Switching hats'),
    },
    canSwitch: !!L.nativeWorkspace(a) && !sessionOf(a)?.v2ReadOnly && !roleOf(a.id),
    // The practice's one role, said once in the bar (phase 2); the switch is gone.
    fixed: roleOf(a.id)
      ? roleOf(a.id) === 'pm'
        ? T('产品经理 · 本人', 'Product manager · you')
        : T('工程师 · 本人', 'Engineer · you')
      : undefined,
    // The product manager's place is the problem ruler at the top of the stage (mountProgress);
    // the bar keeps only the engineer's sign-off steps.
    steps: hat === 'pm' || (ui.route === 'engineer' && String(ui.routeId || '').includes('?nothing')) ? [] : steps,
    scaleLabel: T('签字的步骤', 'Sign-off steps'),
    stepName,
    delivered,
    lang: locale(),
  });
  if (hat === 'pm') mountProgress(a);
  const p = stage?.primary;
  if (p)
    keepIsland('shell-primary', PrimaryKey, {
      label: T(p.label[0], p.label[1]),
      action: p.action,
      id: p.id,
      reason: p.disabledReason ? T(p.disabledReason[0], p.disabledReason[1]) : undefined,
      // The manager's line on what to hand back and when, moved out of the brief onto the key.
      hint:
        p.action === 'submit'
          ? briefDirection(a) ||
            T(
              '把试点决定和依据交给经理',
              'Hand your pilot decision and its evidence to the manager',
            )
          : undefined,
      icon: p.action === 'submit' ? 'stamp' : 'none',
    });
}
/* ---------- one role per practice (phase 2, step 3) ---------- */
// Written once on the server right after the practice starts (engineer store, learner_role).
// If it cannot be written the practice is not quietly taken as a product manager's: the page
// says so and offers to try again.
async function keepRole(a, role) {
  rememberRole(a.id, role);
  try {
    await writeLearnerRole(L.gatewayTransport(a), a.id, role);
    if (ui.roleUnsaved?.id === a.id) ui.roleUnsaved = null;
  } catch (err) {
    ui.roleUnsaved = { id: a.id, role };
    notify(
      T(
        `这一局的岗位没记到服务器上：${err?.message || err}`,
        `This practice’s role did not reach the server: ${err?.message || err}`,
      ),
      { action: { label: T('重试', 'Try again'), run: () => keepRole(a, role) } },
    );
  }
  if (WS.includes(ui.route) || ENGINEER_ROUTES.includes(ui.route)) refreshWS(['toolbar', 'stage']);
}
// A practice opened here that this browser has no role for: ask the server once. One started
// before roles answers null and keeps both hats.
const roleAsked = new Set();
function discoverRole(a) {
  if (!a || !L.nativeWorkspace(a) || roleOf(a.id) || roleAsked.has(a.id)) return;
  roleAsked.add(a.id);
  readLearnerRole(L.gatewayTransport(a), a.id)
    .then((role) => {
      if (!role || current()?.id !== a.id) return;
      rememberRole(a.id, role);
      render();
    })
    .catch(() => roleAsked.delete(a.id));
}
const roleBanner = (a) =>
  ui.roleUnsaved?.id === a.id
    ? `<div class="stage-banner is-warn" role="alert"><span class="grow">${T('这一局的岗位还没记到服务器上，先重试一次再继续。', 'This practice’s role is not on the server yet. Try again before you go on.')}</span>${btn(T('重试', 'Try again'), 'role-retry', 'small')}</div>`
    : '';

/* ---------- the problem ruler (phase 2, step 1) ---------- */
// What the six layers are read from: the person's own records only (shell/progress.ts).
const ROLE_OF_TURN = { manager: 'manager', business: 'business', technical: 'technical' };
function progressFacts(a) {
  const tests = a.tests || [];
  const list = works(a).filter((w) => !w.removedAt);
  const s = sessionOf(a);
  return {
    accepted: Board.walkInAccepted(a.id),
    tests: tests.map((t) => ({
      id: t.id,
      answer: t.answer,
      question: t.question,
      indexVersion: t.indexVersion,
      previousTestId: t.recognition?.find((r) => r.task === 'drift')?.outputs?.previous_test_id,
      policyVersion: Number(t.policyVersion) || 1,
      configVersion: Number(t.configVersion) || 0,
      noted: !!(String(t.expectation || '').trim() || String(t.diagnosis || '').trim()),
    })),
    asked: Object.keys(ROLE_OF_TURN).filter((r) =>
      (a.conversations?.[r] || []).some((m) => m.role === 'user'),
    ),
    works: list.map((w) => ({
      id: w.id,
      decision: E.intentOf(w.purpose) === 'commit',
      hasBody:
        !!String(w.body || '').trim() ||
        (w.cases || []).length > 0 ||
        (w.blocks || []).some((b) => String(b.text || b.body || '').trim() || b.testId),
      evidence: [
        ...(w.evidence || []).map((e) => ({
          kind: e.type === 'test' ? 'test' : 'material',
          id: e.id,
        })),
        ...(w.blocks || [])
          .flatMap((b) => [b.testId, ...(b.testIds || [])])
          .filter(Boolean)
          .map((id) => ({ kind: 'test', id })),
        ...(w.cases || []).flatMap((c) =>
          (c.refs || []).map((r) => ({ kind: 'material', id: r.id })),
        ),
      ],
    })),
    policyVersion: Number(a.world?.policyVersion) || 1,
    configVersion: Number(a.configVersion) || 0,
    baseConfigVersion: 0,
    pendingRequests: (a.requests || []).filter((r) => r.status === 'pending').length,
    approvedRequests: (a.events || []).filter(
      (e) => e.server && ['approve_request', 'resource_grant_committed'].includes(e.type),
    ).length,
    delivered: statusOf(a) === 'submitted',
    feedback: !!(s?.feedback || a.feedback),
  };
}
const PROGRESS_FOLD = 'rolecraft.progress.folded.v2';
const foldKey = () => (ui.route === 'work' ? 'board' : 'page');
const PROGRESS_SEEN = 'rolecraft.progress.passed.v1';
const readJson = (k, d) => {
  try {
    return JSON.parse(localStorage.getItem(k) || '') ?? d;
  } catch {
    return d;
  }
};
const writeJson = (k, v) => {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* this page only */
  }
};
// The layers this practice had passed when last shown here. A layer passing since arrives once
// with its distillation; the first time a practice is shown, what it already passed is taken as
// seen (a returning person is not shown a burst of old summaries).
function passedNow(a, p) {
  const all = readJson(PROGRESS_SEEN, {});
  const done = p.layers
    .filter((l) => l.state === 'done' || l.state === 'reopened')
    .map((l) => l.id);
  if (!all[a.id]) {
    all[a.id] = done;
    writeJson(PROGRESS_SEEN, all);
  }
  const seen = new Set(all[a.id]);
  return { arrived: done.filter((id) => !seen.has(id)).at(-1), all };
}
// A product manager's practice the server enrolled in the seven steps (AIPM phase 1): one guide,
// one numbering, read from the server's progress. Every other practice keeps the six layers.
const Aipm = createAipmPractice({
  current,
  transport: (a) => L.gatewayTransport(a),
  dataHost: (a) => (L.nativeWorkspace(a) ? L.v4Host(a) : null),
  language: (a) => workLang(a) ?? locale(),
  redraw: () => refreshWS(['stage', 'toolbar']),
  openMaterial: (id) => openMaterial(id),
  openChat: (role, text) => openChat(role, text),
  ask: (role, text) => {
    const a = current();
    if (a) void askColleague(a, role, text);
  },
  openWork: () => go('work'),
  openSettings: () => {
    closeSheet(true);
    ui.menu = null;
    sheetConfig();
  },
  submit: () => {
    commit();
    sheetDeliver();
  },
  notifyDraft: (text, label, dismiss, open) => showDraftToast(text, label, dismiss, open),
  prefillColleague: (role, text, attach, detail) => {
    const a = current(),
      prd = Aipm.prdOf(a);
    if (a && prd) prdChoice.set(`${a.id}:${role}:${prd.version}`, attach);
    if (a) {
      if (detail?.trim()) reviewDetails.set(`${a.id}:${role}`, detail.trim());
      else reviewDetails.delete(`${a.id}:${role}`);
    }
    openChat(role, text);
  },
  prdSharedWith: (role, prd) => prdShared(current(), role, prd) === true,
  rememberPrompts: (role, prompts) => {
    const a = current();
    if (!a) return;
    mentorPrompts.set(`${a.id}:${role}`, prompts);
    if (ui.rail === 'chat' && ui.chatRole === role) refreshWS(['rail']);
  },
  showBoard: (screen) => go('work', { aipmScreen: screen }),
  openProduct: (id) => {
    const a = current(),
      x = a?.artifacts.find((y) => y.id === id && !y.removedAt);
    if (!x) return;
    Aipm.host.openWorkbench();
    if (x.taskId) openTask(x.taskId, { type: 'work', id });
    else previewWork(a, id);
  },
  newFreeSheet: () => sheetNewArtifact(undefined, true),
  materialHtml: (id) => {
    const a = current();
    return a ? docBody(a, id, true) : '';
  },
  readMaterial: async (id) => {
    const a = current();
    if (!a) return;
    await recordRead(a, id);
    if (current()?.id === a.id) refreshWS(['stage']);
  },
  materialTitle: (id) => {
    const a = current(),
      m = a && E.getMaterials(a).find((x) => x.id === id);
    return m ? materialTitle(m) : id;
  },
  colleagueName: (c) => PEOPLE[c]?.name ?? c,
  quoteToSheet: async (id, paragraphs = []) => {
    const a = current(),
      host = a && L.nativeWorkspace(a) ? L.v4Host(a) : null,
      m = a && E.getMaterials(a).find((x) => x.id === id);
    if (!host || !m) return;
    // Selected paragraphs quote the passages read from this exact version, in order; anything
    // that matches none falls back to the picker.
    const flat = (t) => (t || '').replace(/\s+/g, '');
    const read = (host.draft('workspace', 'evidence-cache') ?? []).filter(
      (r) => r.kind === 'material' && r.object_id === m.id && r.version === m.version && r.quote,
    );
    const hits = [
      ...new Set(
        paragraphs
          .map(flat)
          .filter(Boolean)
          .map((p) => read.find((r) => flat(r.quote) === p) ?? read.find((r) => flat(r.quote).includes(p))),
      ),
    ].filter(Boolean);
    const refs = hits.length
      ? hits
      : await host.chooseEvidence({
          focus: { session_id: a.id, kind: 'material', object_id: m.id, version: m.version },
        });
    for (const ref of refs.filter((r) => r.kind === 'material'))
      if (!quoteToWorksheet(ref, sourceLabel(workLang(a) ?? locale(), materialTitle(m), ref.version))) {
        notify(T('先打开一张工作纸，再引用这一段。', 'Open a sheet first, then quote this passage.'));
        break;
      }
  },
});
const aipmHere = (a) => hatHere(a) === 'pm' && L.nativeWorkspace(a) && Aipm.ready(a);
// The materials pile beside the sheets: the same component, every material, new ones counted.
function materialPile(a) {
  const rows = docRows(a);
  if (!rows.length) return null;
  const word = {
    new: T('有新版本', 'New version'),
    agent: T('你的 Agent 在读', 'Your agent is reading'),
    unread: T('未读', 'Unread'),
    cited: T('已引用', 'Cited'),
    read: T('已读', 'Read'),
  };
  const fresh = rows.filter((r) => r.state === 'new').length;
  const status = fresh
    ? T(`${rows.length} 份 · ${fresh} 份更新`, `${rows.length} · ${fresh} updated`)
    : T(`${rows.length} 份`, `${rows.length} documents`);
  return {
    kind: 'materials',
    title: T('资料', 'Materials'),
    status,
    ariaLabel: T(`资料，${rows.length} 份`, `Materials, ${rows.length}`) + (fresh ? T(`，${fresh} 份有新版本`, `, ${fresh} with a new version`) : ''),
    capsule: T('资料', 'Materials'),
    items: rows.map((r) => ({
      id: r.id,
      order: null,
      segment: 'material',
      icon: 'FileText',
      name: r.title,
      purpose: `v${r.version}`,
      status: 'not_started',
      statusText: `v${r.version} · ${word[r.state]}`,
      agentDraft: false,
      suggested: false,
      updated: r.state === 'new',
    })),
    words: { suggested: T('建议', 'Suggested'), close: T('收起', 'Close') },
    onOpen: (id) =>
      Aipm.screenOf(a) === 'worksheet' ? Aipm.host.openMaterialSplit(id) : openMaterial(id),
  };
}
// A seven-step practice opens a sheet or a review in the main screen instead of the board.
const aipmScreen = (a) => ui.route === 'work' && aipmHere(a) && Aipm.screenOf(a) !== 'workbench';
// The ruler sits at the top of the stage, in the same light and gutters as the board, on every
// product manager's screen of the practice. A seven-step practice (v2) has the compass there
// instead, the sheet pile in the lower-left corner and, when open, a sheet in the main screen.
// The seven steps start loading while Grace's brief is still open, so the walk-through finds them.
const progressSlot = (a, sevenSteps = aipmHere(a)) =>
  ['work', 'engineer'].includes(ui.route) && Board.entryPending(a)
    ? ''
    : sevenSteps
      ? `<div class="rc-prog-wrap aipm-v2">${islandSlot('aipm-compass')}</div>${
          aipmScreen(a) ? '<div class="aipm-main" data-aipm-main></div>' : ''
        }<div class="aipm-stack-slot">${islandSlot('aipm-materials')}${islandSlot('aipm-stack')}</div>`
      : (hatHere(a) === 'pm'
          ? `<div class="rc-prog-wrap">${islandSlot('shell-progress')}</div>`
          : '') + (['work', 'engineer'].includes(ui.route) ? nextStep(a) : '');
function nextSuggestion(a) {
  if (!(a.tests || []).length)
    return T('先试一个员工会问的问题。', 'Try a question an employee would ask.');
  const p = progressOf(progressFacts(a)),
    layer = p.layers.find((l) => l.id === p.current);
  return layer?.missing.length
    ? T(layer.missing[0][0], layer.missing[0][1])
    : T(
        '整理已有证据，形成你的试点决定。',
        'Bring the evidence together in your pilot recommendation.',
      );
}
function nextStep(a) {
  if (statusOf(a) !== 'active' || hatHere(a) !== 'engineer') return '';
  const stage = stageOf('engineer', a),
    step = stage?.steps.find((s) => s.state === 'current');
  const next = stage?.primary?.label;
  const label = step?.label;
  return `<p class="rc-entry-next" data-entry-next><b>${label ? esc(T(label[0], label[1])) : T('复现', 'Reproduce')}</b><span>${T('下一步：', 'Next: ')}${next ? esc(T(next[0], next[1])) : T('先复现委托里的问题。', 'Reproduce the issue in the ticket.')}</span></p>`;
}
function mountProgress(a) {
  const compass = a && document.querySelector('[data-island="aipm-compass"]') && Aipm.compassProps(a);
  if (compass) {
    keepIsland('aipm-compass', Compass, compass);
    const pile = Aipm.stackProps(a);
    if (pile) keepIsland('aipm-stack', WorkStack, pile);
    const materials = materialPile(a);
    if (materials) keepIsland('aipm-materials', WorkStack, materials);
    Aipm.mountMain(a, document.querySelector('[data-aipm-main]'));
    return;
  }
  if (!document.querySelector('[data-island="shell-progress"]')) return;
  const p = progressOf(progressFacts(a));
  const tx = (t) => T(t[0], t[1]);
  const { arrived } = passedNow(a, p);
  const now = pmCurrent(a);
  const routeLayer =
    ui.route === 'investigate' ? 'understand' : ui.route === 'review' ? 'reflect' : undefined;
  keepIsland('shell-progress', ProgressBand, {
    lang: locale(),
    suggestion: { label: T('下一步', 'Next step'), text: nextSuggestion(a) },
    current: p.current,
    carried: carried(p).map(tx),
    arrived,
    // The current summary stays visible; the six-layer overview opens on request.
    folded: readJson(PROGRESS_FOLD, {})[foldKey()] ?? null,
    foldedByDefault: true,
    routeViewing: routeLayer,
    back: routeLayer ? stageBack(a) : undefined,
    actions: {
      // The dossier of findings, once there is something in it.
      understand:
        ui.route === 'investigate' || !(a.tests || []).length
          ? undefined
          : {
              label: T('看调查记录', 'See what you found'),
              action: 'stage-pm',
              data: { step: 'investigate' },
            },
      ...(statusOf(a) === 'submitted' && ui.route !== 'review'
        ? {
            reflect: {
              label: T('看结果', 'See the result'),
              action: 'stage-pm',
              data: { step: 'delivered' },
            },
          }
        : {}),
      ...(now !== 'delivered' && ui.route !== 'work'
        ? { [p.current]: { label: T('回到工作板', 'Back to the board'), action: 'to-board' } }
        : {}),
    },
    layers: p.layers.map((l) => {
      const d = distillation(p, l.id);
      return {
        id: l.id,
        n: l.n,
        label: tx(l.label),
        goal: tx(l.goal),
        state: l.state,
        confirmed: l.confirmed.map(tx),
        compactConfirmed: l.compactConfirmed?.map(tx),
        compactMissing: l.compactMissing?.map(tx),
        missing: l.missing.map(tx),
        ...(l.reopened ? { reopened: tx(l.reopened) } : {}),
        ...(d ? { distilled: { confirmed: d.confirmed.map(tx), kept: d.kept.map(tx) } } : {}),
      };
    }),
    words: {
      label: T('这一局走到哪了', 'Where this practice stands'),
      now: T('当前问题', 'Current question'),
      missing: T('还差', 'Still missing'),
      nothingMissing: T('这一层的依据都在了', 'This layer has what it needs'),
      confirmed: T('已确认', 'Confirmed'),
      next: T('下一层', 'Next'),
      after: T('再下一层', 'After that'),
      basis: T('依据：你的记录', 'Based on your records'),
      basisHint: T(
        '进度只看你的记录：测试、你写下的判断、引用了依据的作品、应用的设置和交付。点击次数、聊天轮数和读了多少资料都不算；一篇草稿本身也不算过关。政策变了，只重新打开受影响的那一层。',
        'Progress reads only your records: tests, the judgements you wrote, work that cites evidence, applied settings and what you submitted. Clicks, chat turns and pages read do not count, and a draft on its own passes nothing. A policy change reopens only the layer it affects.',
      ),
      map: T('工作地图', 'Work map'),
      fold: T('收起六层', 'Hide layers'),
      unfold: T('展开六层', 'Show six layers'),
      viewing: T('正在看', 'Viewing'),
      backToNow: T('回到当前这一层', 'Back to where you are'),
      distilled: T('本层提炼', 'Layer summary'),
      kept: T('仍保留：', 'Still open: '),
      gotIt: T('知道了', 'Got it'),
      close: T('关闭', 'Close'),
      mapTitle: T('整件工作的地图', 'The whole piece of work'),
      mapLead: T(
        '六层是常见的顺序，不是关卡：随时可以回看、提前提方案或有依据地延期。每一层写着已确认的、还差的，以及仍要带着走的事。',
        'Six layers in the usual order, not gates: look back, propose early or defer with reasons at any time. Each says what is confirmed, what is missing and what you still carry forward.',
      ),
      states: {
        done: T('已完成', 'Done'),
        current: T('当前', 'Current'),
        reopened: T('需要再看', 'Needs another look'),
        todo: T('还没到', 'Ahead'),
        uncovered: T('这局没覆盖', 'Not covered this time'),
      },
      ending: {
        title: T('接下来可以', 'What can follow'),
        items: [
          T('修订作品，关联到原来的交付', 'Revise the work, linked to what you submitted'),
          T(
            '换一个条件再练：期限提前或容量收紧',
            'Practise again under new conditions: an earlier deadline or less capacity',
          ),
        ],
      },
      stepOf: (n, total, label) =>
        T(`第 ${n} 层，共 ${total} 层：${label}`, `Layer ${n} of ${total}: ${label}`),
    },
    onFold: (v) => {
      writeJson(PROGRESS_FOLD, { ...readJson(PROGRESS_FOLD, {}), [foldKey()]: v });
      mountProgress(current());
    },
    onArrivedSeen: (id) => {
      const all = readJson(PROGRESS_SEEN, {});
      all[a.id] = [...new Set([...(all[a.id] || []), id])];
      writeJson(PROGRESS_SEEN, all);
      mountProgress(current());
    },
  });
}
// The product manager's steps and their screens: Investigate → the findings dossier; Decide → the
// board; Delivered → the result. The board is also where the Investigate step is worked, so it
// counts as the current step's own screen until the practice is delivered.
const pmCurrent = (a) =>
  statusOf(a) === 'submitted'
    ? 'delivered'
    : works(a).some((x) => String(editorView(a, x).body || '').trim())
      ? 'decide'
      : 'investigate';
function pmViewing(a) {
  const now = pmCurrent(a);
  if (ui.route === 'investigate') return 'investigate';
  if (ui.route === 'review') return now === 'delivered' ? null : 'delivered';
  if (now === 'delivered' && ['work', 'task', 'doc', 'bench'].includes(ui.route)) return 'decide';
  return null;
}
// The way back to the current step's own screen, as the scale's ghost key and the dossier's.
function stageBack(a) {
  const now = pmCurrent(a);
  const label =
    now === 'delivered'
      ? T('回到结果', 'Back to the result')
      : pmViewing(a) === now
        ? T('回到工作板', 'Back to the board')
        : now === 'decide'
          ? T('回到决定', 'Back to Decide')
          : T('回到调查', 'Back to Investigate');
  return { label, action: 'stage-back' };
}
// Between the board and the dossier the old page leaves first (160ms, fading and blurring a
// little), then the new one rises 10px into place (280ms): two pages of text never overlap.
// Reduced motion: the new page fades in over 160ms.
// The problem ruler stays put while the page under it changes.
const stageBody = (el) => [...el.children].filter((c) => !c.classList.contains('rc-prog-wrap'));
function switchStage(run) {
  const old = document.getElementById('ws-stage');
  const arrive = () => {
    const next = document.getElementById('ws-stage');
    if (!next) return;
    for (const part of stageBody(next))
      part.animate(
        reduceMotion.matches
          ? [{ opacity: 0 }, { opacity: 1 }]
          : [
              { opacity: 0, transform: 'translateY(10px)' },
              { opacity: 1, transform: 'none' },
            ],
        { duration: reduceMotion.matches ? 160 : 280, easing: 'cubic-bezier(.23,1,.32,1)' },
      );
  };
  if (!old || reduceMotion.matches) {
    run();
    arrive();
    return;
  }
  Promise.all(
    stageBody(old).map(
      (part) =>
        part.animate(
          [
            { opacity: 1, filter: 'blur(0)' },
            { opacity: 0, filter: 'blur(2px)' },
          ],
          { duration: 160, easing: 'ease-out', fill: 'forwards' },
        ).finished,
    ),
  ).then(() => {
    run();
    arrive();
  });
}
// Going back to the board puts it where it was left.
function goBoard() {
  const y = ui.boardY || 0;
  const held = ui.boardH || 0;
  switchStage(() => {
    go('work');
    if (!y) return;
    // The board is drawn at its old height and scroll before it rises; its cards mount a moment
    // later, then the held height is let go. So it arrives where it was, without a jump.
    const stage = document.getElementById('ws-stage');
    const main = document.getElementById('main');
    if (stage && held) stage.style.minHeight = `${held}px`;
    if (main) main.scrollTop = y;
    Board.tasksDrawn(1, 1500).then(() =>
      requestAnimationFrame(() => {
        if (stage?.isConnected) stage.style.minHeight = '';
      }),
    );
  });
}
const keepBoardPlace = () => {
  if (ui.route !== 'work') return;
  ui.boardY = document.getElementById('main')?.scrollTop || 0;
  ui.boardH = document.getElementById('ws-stage')?.offsetHeight || 0;
};
// The bar never overlaps itself. The title gives way first (down to its minimum, with an
// ellipsis); if the row still does not fit, things fold in a fixed order: the lamp's words and
// the disabled key's reason, then the scale to "1/3", then the hat switch into ⋯.
const BAR_FOLDS = ['fold-words', 'fold-scale', 'fold-hat'];
// A redrawn bar starts with the last folds, so it never paints one frame overlapped.
let barFolds = [];
/** Whether the way home last had to leave the centre; kept across renders so it never jumps. */
let homeInline = false;
const watchedBar = new WeakSet();
const barResize = new ResizeObserver(() => requestAnimationFrame(fitShellBar));
function fitShellBar() {
  const bar = document.querySelector('.shell-bar');
  if (!bar) return;
  bar.classList.remove(...BAR_FOLDS);
  barFolds = [];
  for (const fold of BAR_FOLDS) {
    if (bar.scrollWidth <= bar.clientWidth + 1) break;
    bar.classList.add(fold);
    barFolds.push(fold);
  }
  // The way home holds the centre only while nothing else in the bar reaches it.
  const home = bar.querySelector('.ws-home');
  if (home) {
    bar.removeAttribute('data-home-inline');
    const r = home.getBoundingClientRect();
    const boxes = (el) =>
      getComputedStyle(el).display === 'contents' ? [...el.children].flatMap(boxes) : [el];
    homeInline = [...bar.children]
      .filter((el) => el !== home && !el.classList.contains('spacer'))
      .flatMap(boxes)
      .some((el) => {
        const o = el.getBoundingClientRect();
        return o.width > 0 && o.left < r.right + 12 && o.right > r.left - 12;
      });
    if (homeInline) bar.setAttribute('data-home-inline', '');
  }
  // The islands draw after this render and change width with the stage: fit again then.
  for (const el of bar.querySelectorAll('.rc-hatscale, .rc-primary, .crumbbar'))
    if (!watchedBar.has(el)) {
      watchedBar.add(el);
      barResize.observe(el);
    }
}
window.addEventListener('resize', () => requestAnimationFrame(fitShellBar));
/** The practice's one model status, once the server has read it; null for legacy practice. */
function modelStatusOf(a) {
  const host = a && L.nativeWorkspace(a) ? L.v4Host(a) : null;
  const read = host?.snapshot();
  return read?.asOf ? modelStatus(read.semantic) : null;
}
const menuItem = (action, label, ic, attrs = '') =>
  `<button type="button" role="menuitem" data-action="${action}" ${attrs}>${icon(ic, 'i-sm')}<span class="grow">${label}</span></button>`;
// The ⋯ menu holds what a person does with the practice. Records, exports and other
// workbench internals live in "About this workspace".
function moreMenu(a) {
  const st = statusOf(a);
  const rows = [
    st !== 'submitted' && !sessionOf(a)?.v2ReadOnly
      ? menuItem(
          'live-session',
          st === 'paused' ? T('恢复练习', 'Resume practice') : T('暂停练习', 'Pause practice'),
          st === 'paused' ? 'play' : 'pause',
        )
      : '',
    sessionOf(a)?.protocol === 2 ? menuItem('continue-code', recovery.menuLabel(), 'sync') : '',
    lensMenuItems(),
    `<div class="menu-sep" role="separator"></div>`,
    // Inside a practice the language is the practice's: the row says so and is marked locked.
    `<button type="button" role="menuitem" data-action="menu" data-menu="lang">${icon('globe', 'i-sm')}<span class="grow">${T('语言', 'Language')}</span><span class="menu-value">${practiceLocale() ? T('跟随这一局', 'Follows this practice') : locale() === 'zh' ? '中文' : 'English'}</span>${practiceLocale() ? icon('lock', 'i-xs lang-lock') : ''}</button>`,
    modelStatusOf(a)
      ? `<button type="button" role="menuitem" data-action="menu" data-menu="model">${icon('circle', 'i-sm')}<span class="grow">${T('模型', 'Model')}</span><span class="menu-value">${esc(modelStatusOf(a).short)}</span></button>`
      : '',
    `<span class="narrow-item">${menuItem('open-rail', T('团队与信号', 'Team and signals'), 'team')}</span>`,
    L.nativeWorkspace(a) && !roleOf(a.id)
      ? `<span class="phone-item">${menuItem('hat-switch', hatHere(a) === 'pm' ? T('换成工程师', 'Switch to Engineer') : T('换成产品经理', 'Switch to Product manager'), 'sync', `data-hat="${hatHere(a) === 'pm' ? 'engineer' : 'pm'}"`)}</span>`
      : '',
    L.nativeWorkspace(a)
      ? menuItem('walk-tour', T('重看入门引导', 'Walk me through again'), 'question')
      : '',
    menuItem('about', T('关于这个工作台', 'About this workspace'), 'info'),
    menuItem('to-entry', T('离开工作台', 'Leave the workspace'), 'back'),
  ];
  return `<div class="menu right" role="menu">${rows.join('')}</div>`;
}
/* Show recognition details: a per-viewer switch in "⋯", plus the way into the system profile
 * (#/lab). Both items live here so the menu takes them in one line. */
function lensMenuItems() {
  const on = lensOn();
  return `<button type="button" role="menuitemcheckbox" aria-checked="${on}" data-action="lens-toggle">${icon('eye', 'i-sm')}<span class="grow">${T('技术透视', 'Show recognition details')}</span>${on ? icon('check', 'i-sm') : ''}</button><button type="button" role="menuitem" data-action="open-lab">${icon('layers', 'i-sm')}<span class="grow">${T('系统剖面', 'System profile')}</span></button>`;
}
/** The review page has no workbench toolbar; its "⋯" carries the lens items and "About". It
 * opens and closes in place: redrawing the review page would remount the feedback. */
function toggleReviewMenu(open) {
  const wrap = document.querySelector('[data-review-menu]');
  if (!wrap) return;
  const menu = wrap.querySelector('.menu');
  const trigger = wrap.querySelector('[data-action="review-menu"]');
  const show = open ?? !menu;
  if (!show) {
    menu?.remove();
    trigger?.setAttribute('aria-expanded', 'false');
    return;
  }
  if (menu) return;
  wrap.insertAdjacentHTML(
    'beforeend',
    // The same ⋯ as on every other screen of the practice; it only opens in place here.
    moreMenu(current()),
  );
  trigger?.setAttribute('aria-expanded', 'true');
  if (ui.kbd) wrap.querySelector('.menu button')?.focus();
}
document.addEventListener('click', (e) => {
  if (!e.target.closest?.('[data-review-menu]')) toggleReviewMenu(false);
});
document.addEventListener('keydown', (e) => {
  const wrap = document.querySelector('[data-review-menu]');
  if (e.key !== 'Escape' || !wrap?.querySelector('.menu')) return;
  toggleReviewMenu(false);
  wrap.querySelector('[data-action="review-menu"]')?.focus();
});
/** An explicit technical-view switch in the submission header. Records do not replay. */
function mountLensSwitch(head) {
  const close = head?.querySelector('[data-action="close"]');
  if (!close || head.querySelector('[data-lens-switch]')) return;
  close.insertAdjacentHTML(
    'beforebegin',
    `<button type="button" class="rc-switch" role="switch" aria-checked="${lensOn()}" data-action="lens-switch" data-lens-switch><span class="rc-switch__track" aria-hidden="true"></span><span class="rc-switch__long">${T('技术透视', 'Show recognition details')}</span><span class="rc-switch__short">${T('技术透视', 'Details')}</span></button>`,
  );
}
/** Close an open menu without redrawing the page (inputs and scroll stay as they are). */
function closeMenuInPlace() {
  ui.menu = null;
  for (const menu of document.querySelectorAll('.menu-wrap > .menu')) menu.remove();
  const trigger = document.querySelector('[data-menu="more"], [data-action="review-menu"]');
  trigger?.setAttribute('aria-expanded', 'false');
  if (WS.includes(ui.route)) toolbarShown = { node: null, html: '' };
  trigger?.focus({ preventScroll: true });
}
const materialNameOf = (a) => (id) => {
  const m = a && E.getMaterials(a).find((x) => x.id === id);
  return m ? materialTitle(m) : id;
};
/** A test run's recognition signals: quiet facts by default, chips in the lens. */
function runSignals(a, x) {
  return `<div data-rc-run="${esc(x.id)}">${lensOn() ? signalsHtml(x.recognition, locale(), { context: 'test', lens: true, materialName: materialNameOf(a), cards: { comparison: { current: x, tests: a.tests || [] } } }) : ''}</div>`;
}
/** Redraw only the recognition parts of the current page when the lens opens or closes. */
onLensChange((on) => {
  for (const toggle of document.querySelectorAll('[data-lens-switch]'))
    toggle.setAttribute('aria-checked', String(on));
  for (const replay of document.querySelectorAll('[data-lens-replay]')) replay.hidden = !on;
  const a = current();
  if (!a) return;
  document.querySelectorAll('[data-rc-run]').forEach((node) => {
    const run = (a.tests || []).find((t) => t.id === node.dataset.rcRun);
    node.innerHTML = run && on
      ? signalsHtml(run.recognition, locale(), {
          context: 'test',
          lens: lensOn(),
          materialName: materialNameOf(a),
          cards: { comparison: { current: run, tests: a.tests || [] } },
        })
      : '';
  });
  const hero = document.querySelector('[data-rc-hero]');
  if (hero) hero.innerHTML = recognitionHeroInner(a);
  const behavior = document.querySelector('[data-rc-behavior]');
  if (behavior) fillBehavior(behavior, a);
});
function briefPopover(a) {
  return `<div class="popover brief-pop" role="dialog" aria-label="${esc(T('委托与条件', 'Brief and conditions'))}">
    ${briefLetter(a, 'sm')}
    ${intakeNote(a)}
    ${conditions(a, 'compact')}
    <div class="pop-actions">${btn(icon('doc', 'i-sm') + T('看完整委托', 'Read the full brief'), 'open-doc', 'small', 'data-id="brief"')}${btn(icon('hand', 'i-sm') + T('申请资源', 'Request resources'), 'resources', 'small quiet')}</div>
  </div>`;
}
function intakeNote(a) {
  if (!a.intake) return '';
  const fits = intakeLines(a.intake.fits, a.intake.adopted);
  const gaps = intakeLines(a.intake.gaps, a.intake.notModeled);
  return `<div class="intake-note"><p class="meta">${T('按你描述的业务', 'From your description')}</p><ul class="ticks small">${fits.map((x) => `<li>${icon('check', 'i-xs')}${esc(x)}</li>`).join('')}${gaps.map((x) => `<li class="muted">${icon('minus', 'i-xs')}${esc(x)}</li>`).join('')}</ul></div>`;
}
// A condition reads like an instrument: the number carries the weight, its unit sits beside it.
// The text stays the same ("30 seats", "第 7 天"); only the number gets its own span.
const readout = (value) => {
  const m = /^(\D*?)(\d+(?:\.\d+)?)(\D*)$/.exec(value);
  return m
    ? `${m[1] ? `<span class="cond-unit">${m[1]}</span>` : ''}<span class="cond-num">${m[2]}</span>${m[3] ? `<span class="cond-unit">${m[3]}</span>` : ''}`
    : value;
};
// Conditions are numbers with names. An approved change shows the old value beside it.
function conditions(a, cls = '') {
  const base = worldOf(a.scenarioId);
  const w = a.world;
  const lit = (k) =>
    ui.changed && ui.changed.until > Date.now() && ui.changed.keys.includes(k) ? ' lit' : '';
  const item = (value, label, was, k = '') =>
    `<div class="cond ${was ? 'changed' : ''}${lit(k)}"><span class="cond-val">${readout(value)}</span><span class="cond-label">${label}</span>${was ? `<span class="cond-was">${T('原', 'was')} ${was} · ${T('已批准', 'approved')}</span>` : ''}</div>`;
  return `<div class="conds ${cls}">
    ${item(T(w.capacity + ' 人', w.capacity + ' seats'), T('试点容量', 'Capacity'), w.capacity !== base.capacity ? T(base.capacity + ' 人', String(base.capacity)) : '', 'capacity')}
    ${item(T(w.devDays + ' 人日', w.devDays + ' person-days'), T('可用开发', 'Engineering'), w.devDays !== base.devDays ? T(base.devDays + ' 人日', String(base.devDays)) : '', 'devDays')}
    ${item(T('第 ' + w.deadline + ' 天', 'Day ' + w.deadline), T('期望上线', 'Launch target'), w.deadline !== base.deadline ? T('第 ' + base.deadline + ' 天', 'day ' + base.deadline) : '', 'deadline')}
    ${item(T(`${INDEX_DELAY_HOURS} 小时`, `${INDEX_DELAY_HOURS} h`), T('索引最长滞后', 'Max index lag'))}
  </div>`;
}
function wsStage(a) {
  if (['work', 'engineer'].includes(ui.route) && Board.entryPending(a)) return Board.entryStory(a);
  const st = statusOf(a);
  let lock = sessionOf(a)?.v2ReadOnly
    ? `<div class="stage-banner" role="status"><span class="grow">${T('这个练习使用旧版场景，原记录可以只读查看。要继续练习，请开始新的工作。', 'This practice uses an earlier scenario. View its original records read-only, or start new work to continue practising.')}</span>${btn(T('开始新的练习', 'Start a new practice'), 'v4-new-practice', 'small')}</div>`
    : st === 'paused'
      ? `<div class="stage-banner">${icon('pause', 'i-sm')}<span class="grow">${T('练习已暂停。资料可以看，操作要先恢复。', 'Paused. You can read; resume to act.')}</span>${btn(T('恢复', 'Resume'), 'live-session', 'small')}</div>`
      : st === 'submitted'
        ? `<div class="stage-banner is-submitted">${icon('stamp', 'i-sm')}${handedIn(a)}</div>`
        : '';
  lock = roleBanner(a) + lock;
  const registered = registeredRoute(ui.route);
  if (registered) return lock + registered.render(ui.routeId);
  const t = routeTask(a);
  if (t) return lock + taskView(a, t);
  if (ui.route === 'doc')
    return lock + `<div class="page-pad">${docBody(a, ui.routeId, false)}</div>`;
  if (ui.route === 'bench') return lock + `<div class="page-pad">${bench(a, null)}</div>`;
  const v = a.world.policyVersion;
  const policyNew = v > 1 && !(a.acks || []).includes('policy-v' + v);
  return lock + (policyNew ? situationBanner(a) : '') + needsStrip(a) + boardView(a);
}

/* the board */
// The brief has been read once its document was opened (locally at once, on the server after).
const briefRead = (a) =>
  readSet(a).has('brief') || (a.acks || []).some((k) => String(k).startsWith('read-brief-'));
// The manager's letter on the board: the brief in serif, signed underneath, with the way to the
// full brief on the same line. What to hand back and where lives with the Submit key now.
function boardMemo(a) {
  const p = PEOPLE.manager;
  const rolled = briefRead(a);
  return `<article class="band-letter memo"><blockquote${langOf(a)}>${esc(caseOf(a).quote)}</blockquote>
    <p class="memo-by">${avatar('manager', 'sm')}<span><b>${p.name}</b>${p.titled ? '' : `<span>${ROLE_TITLE('manager')}</span>`}</span><span class="spacer"></span><button type="button" class="brief-line-read" data-action="open-doc" data-id="brief">${icon('doc', 'i-sm')}${T('看完整委托', 'Read the full brief')}</button>${rolled ? `<button type="button" class="btn icon quiet small brief-line-toggle" data-action="board-brief-toggle" aria-expanded="true" aria-label="${esc(T('收起委托', 'Roll the brief up'))}"><svg class="i i-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5"/></svg></button>` : ''}</p>
    ${intakeNote(a)}</article>`;
}
function boardBrief(a) {
  if (!Board.briefRolled(a.id, briefRead(a) && ui.docSheet !== 'brief'))
    return `<section class="brief-band" data-flip="brief" style="view-transition-name: case-surface">${boardMemo(a)}${conditions(a)}</section>`;
  return Board.rolledBrief({
    avatar: avatar('manager', 'sm'),
    line: Board.briefKeyLine(caseOf(a).quote),
    lang: langOf(a),
    readouts: conditions(a, 'mini'),
    roll: Board.takeRoll(a.id),
    esc,
  }).replace('data-brief-rolled', 'data-brief-rolled data-flip="brief"');
}
// The tray: drafts your agent handed back that you have not adopted yet.
function boardTray(a) {
  const drafts = (a.artifacts || [])
    .filter((x) => !x.removedAt && x.source === 'external-agent' && !x.adopted)
    .map((x) => ({
      id: x.id,
      title: shown(x).title || T('未命名', 'Untitled'),
      kind: purposeLabel(shown(x).purpose),
      version: x.revision || 1,
      at: x.updatedAt || x.createdAt || '',
      review: x.taskId ? 'open-artifact' : 'preview-work',
    }));
  const html = Board.agentTray({ connected: Board.agentConnected() || drafts.length > 0, drafts });
  return html ? `<div data-flip="tray">${html}</div>` : '';
}
const canWriteBoard = (a) => canWrite(a) && !sealedSession(a);
function boardView(a) {
  const writable = canWriteBoard(a);
  const blocked = writable ? '' : 'disabled aria-describedby="tasks-write-reason"';
  return `<div class="board">
    ${boardBrief(a)}
    ${practiceOriginNote(a)}
    <div data-flip="product">${productBar(a)}</div>
    ${boardTray(a)}
    <section class="work-sec" aria-labelledby="tasks-h" data-flip="tasks" data-board-tasks>
      <header class="sec-head"><h2 id="tasks-h">${T('事项', 'Tasks')}</h2><span class="sec-hint" ${writable ? '' : 'hidden'}><span class="hint-drag">${T('拖动卡片调整优先级', 'Drag to reprioritise')}</span><span class="hint-keys">${T('，或按住 Option 用方向键', ', or hold Option and use the arrow keys')}</span></span><span class="spacer"></span>
        <div class="menu-wrap">${btn(icon('bubble', 'i-sm') + T('问问怎么排', 'Ask how to prioritise'), 'menu', 'small quiet', `data-menu="rank" aria-haspopup="menu" aria-expanded="${writable && ui.menu === 'rank'}" ${blocked}`)}${writable && ui.menu === 'rank' ? rankMenu() : ''}</div>
        ${btn(icon('plus', 'i-sm') + T('新事项', 'New task'), 'new-task', 'small', blocked)}</header>
      ${writable ? '' : `<p id="tasks-write-reason" class="meta">${statusOf(a) === 'submitted' ? T('这一局已只读，开始修订后可以继续。', 'This practice is read-only. Start a revision to continue.') : T('当前不能更改事项或提问。', 'Tasks and questions cannot be changed right now.')}</p>`}
      ${revisionNote(a)}
      <p id="move-help" class="sr-only">${T('按住 ⌥ Option 或 Alt：← → 改优先级，↑ ↓ 调顺序。', 'Hold ⌥ Option or Alt, then ← → to change priority and ↑ ↓ to reorder.')}</p>
      <div class="kanban">${['first', 'next', 'later'].map((p) => column(a, p)).join('')}</div>
    </section>
    <div data-flip="docs">${docGrid(a)}</div>
    ${unfiledWorks(a)}
  </div>`;
}
// Whose request each starting task is, as its own brief says: the business team asked for the
// first users' needs and for policy Q&A; the manager asked for the pilot decision (SEEDS).
const SEED_FROM = { needs: 'business', policy: 'business', decision: 'manager' };
function seedRequester(title) {
  const key = Object.keys(SEEDS).find((k) => SEEDS[k].zh[0] === title || SEEDS[k].en[0] === title);
  return key ? SEED_FROM[key] : undefined;
}
// After "Start a revision": where to pick the work up, from the last delivery's unmet items,
// said by the manager in the work's own words. It stays until dismissed or the next delivery.
function revisionGuide(a) {
  const g = a?.revisionGuide;
  return g && !g.dismissed && statusOf(a) === 'active' ? g : null;
}
function revisionTaskIds(a) {
  const g = revisionGuide(a);
  if (!g) return new Set();
  return new Set(
    (a.artifacts || [])
      .filter((x) => (g.products || []).includes(x.id) && x.taskId)
      .map((x) => x.taskId),
  );
}
function revisionNote(a) {
  const g = revisionGuide(a);
  if (!g) return '';
  // Inside the manager's quoted words: corner brackets in Chinese, single quotes in English.
  const quote = (t) => T(`「${t}」`, `‘${t}’`);
  const names = (g.unmet || []).slice(0, 3).map(quote);
  const more = (g.unmet || []).length - names.length;
  const listed =
    names.join(T('、', ', ')) +
    (more > 0 ? T(` 等 ${g.unmet.length} 项`, ` and ${more} more`) : '');
  const tasks = [...revisionTaskIds(a)]
    .map((id) => a.tasks.find((t) => t.id === id))
    .filter(Boolean)
    .map((t) => quote(taskTitle(t)));
  const works = (g.products || [])
    .map((id) => a.artifacts.find((x) => x.id === id))
    .filter(Boolean)
    .map((x) => T(`《${shown(x).title}》`, `‘${shown(x).title}’`));
  const where = tasks[0] || works[0] || '';
  const round = Number.isFinite(g.delivery)
    ? T(`第 ${g.delivery} 次交付里，`, `In delivery ${g.delivery}, `)
    : T('上次交付里，', 'In your last delivery, ');
  const said = names.length
    ? round + T(`${listed}还没站住。`, `${listed} did not hold up yet. `)
    : g.reason
      ? T(
          `你说这次要「${g.reason.replace(/[。.]$/, '')}」。`,
          `You said: ‘${g.reason.replace(/[.。]$/, '')}’. `,
        )
      : '';
  const next = where
    ? T(
        `从${where}接着改，改好再交给我。`,
        `Pick it up from ${where} and bring it back to me when it is ready.`,
      )
    : T('改好再交给我。', 'Bring it back to me when it is ready.');
  return `<aside class="revise-note" data-revise-note aria-label="${esc(T('从哪里修订', 'Where to revise'))}">${letter('manager', said + next, 'sm')}${btn(T('知道了', 'Got it'), 'revise-note-ok', 'small quiet')}</aside>`;
}
// What changed, in the notice's own words: the first clause of the new policy text, with the
// number it replaced read from the version before. Both versions come from the read-only
// materials query (no read is recorded), are fetched once per practice and kept here.
function policyText(a, version) {
  ui.policyTexts = ui.policyTexts || {};
  const key = `${a.id}@${version}`;
  if (key in ui.policyTexts) return ui.policyTexts[key];
  ui.policyTexts[key] = null;
  Promise.resolve(L.materialVersion(a, 'policy', version))
    .then((m) => {
      if (m?.content) {
        ui.policyTexts[key] = String(m.content);
        refreshWS(['stage']);
      }
    })
    .catch(() => {
      /* the band keeps its title; the change line waits for the text */
    });
  return null;
}
function policyChange(a, v) {
  const current = policyText(a, v);
  if (!current) return '';
  const prev = v > 1 ? policyText(a, v - 1) : null;
  const text = current
    .replace(/^#.*\n+/, '')
    .replace(/[*_`]/g, '')
    .trim();
  let clause = text.split(/(?<=[。；！？])|(?<=[;.!?])\s+/)[0].replace(/[。；;.]$/, '');
  const colon = clause.search(/[：:]\s?/);
  if (colon > 0 && colon < 40) clause = clause.slice(colon + 1).trim();
  if (!clause) return '';
  clause = clause[0].toUpperCase() + clause.slice(1);
  const nums = (t) => String(t).match(/\d+(?:\.\d+)?/g) || [];
  const now = prev ? nums(clause).find((n) => !nums(prev).includes(n)) : undefined;
  const was = now ? nums(prev).find((n) => !nums(text).includes(n)) : undefined;
  let old = '';
  if (was) {
    const around = new RegExp(`([A-Z]{3}\\s?)?${now}(元|%)?`).exec(clause);
    old = (around?.[1] || '') + was + (around?.[2] || '');
  }
  const W = worldText(a);
  return clause + (old ? W(`（原为${old}）`, ` (was ${old})`) : '') + W('。', '.');
}
// The latest delivery (its call and when it was made), read once per practice for the
// handed-in band.
function delivered(a) {
  ui.deliveredDecisions = ui.deliveredDecisions || {};
  if (a.id in ui.deliveredDecisions) return ui.deliveredDecisions[a.id];
  ui.deliveredDecisions[a.id] = null;
  const host = L.nativeWorkspace(a) ? L.v4Host(a) : null;
  Promise.resolve(host?.query('submissions.list'))
    .then((list) => {
      const rows = Array.isArray(list) ? list : Array.isArray(list?.items) ? list.items : [];
      const last = rows.at(-1);
      if (last?.decision) {
        ui.deliveredDecisions[a.id] = { decision: last.decision, at: last.created_at || null };
        refreshWS(['stage']);
      }
    })
    .catch(() => {
      /* the band falls back to the plain sentence */
    });
  return null;
}
// "12:18  Submitted: proceed with a limited scope. This practice is read-only now."
function handedIn(a) {
  const d = delivered(a);
  const at = a.submittedAt || d?.at;
  const call = d ? DECISION(d.decision) : '';
  const said = call
    ? `<b>${T(`已交付：${call}。`, `Submitted: ${call[0].toLowerCase() + call.slice(1)}.`)}</b> ${T('现在只能查看。', 'This practice is read-only now.')}`
    : T('已固定交付，现在只能查看。', 'Submitted. This practice is read-only now.');
  return `${at ? `<time class="sb-when">${esc(when(at))}</time>` : ''}<span class="grow">${said}</span>`;
}
// When the world changed: "Just now" for the first few minutes, then the time it happened.
function changedAt(a) {
  const times = a.eventTimes || {};
  const e = (a.events || []).filter((x) => x.type === 'policy_updated').at(-1);
  const at = e && (e.createdAt || times[e.seq]);
  const t = at ? Date.parse(at) : NaN;
  return Number.isFinite(t) && Date.now() - t > 5 * 60_000 ? when(at) : T('刚刚', 'Just now');
}
// True while the page's own dialog covers the board; the board is drawn again when it closes, so
// what changed meanwhile (a policy update, a new config version) plays where it can be seen.
function sheetCovers(a) {
  const covered = sheet.open;
  if (covered && !ui.arrivalWaits) {
    ui.arrivalWaits = true;
    sheet.addEventListener(
      'close',
      () =>
        setTimeout(() => {
          ui.arrivalWaits = false;
          if (current() === a && WS.includes(ui.route)) refreshWS(['stage']);
        }, 160),
      { once: true },
    );
  }
  return covered;
}
// The event lives in the light, right under the topbar: when, what changed (world text in the
// work language, the first sentence set in ink), and three keys. Its line draws once.
function situationBanner(a) {
  const v = a.world.policyVersion;
  const behind = a.world.indexVersion < v;
  const change = policyChange(a, v);
  const W = worldText(a);
  const title = W(`差旅政策更新为 v${v}。`, `The travel policy is now v${v}.`);
  const before = a.tests.filter((r) => r.policyVersion < v).length;
  const after = [
    change,
    before
      ? W(
          `你之前的 ${before} 次测试用的是旧版政策。`,
          before > 1
            ? `The ${before} tests you ran before this used v${v - 1}.`
            : `The test you ran before this used v${v - 1}.`,
        )
      : '',
    behind
      ? W(
          `知识助手的索引还是 v${a.world.indexVersion}，刷新前它会继续按旧版回答。`,
          `The assistant still indexes v${a.world.indexVersion} until you refresh it.`,
        )
      : '',
  ].filter(Boolean);
  const what = `<p class="we-what"${langOf(a)}><strong>${esc(title)}</strong> ${esc(after.join(' '))}</p>`;
  // The submitted board is a record; policy history remains in documents and the record drawer.
  if (statusOf(a) === 'submitted') return '';
  // A change that lands while a dialog is open arrives when the dialog has gone.
  const covered = sheetCovers(a);
  const age = covered ? null : Board.arrivalAge(a.id, `policy-v${v}`);
  if (age != null) ui.amberArriving = age;
  return `<section class="world-event${age != null ? ' arriving' : covered ? ' pending' : ''}" role="status"${age ? ` style="--arrive-age: ${age}ms"` : ''}><span class="we-when">${esc(changedAt(a))}</span>${what}
    <div class="we-actions">${btn(T('看哪里变了', 'See what changed'), 'open-doc', 'small primary', 'data-id="policy" data-compare="1"')}${btn(T('记为事项', 'Add as a task'), 'situation-task', 'small')}${btn(T('知道了', 'Got it'), 'ack', 'small quiet', `data-key="policy-v${v}"`)}</div>
  </section>`;
}
// What the next test actually uses, beside the saved settings, when the two differ.
function configUseLine(use, prefix = '') {
  return use
    ? `<p class="config-use${use.unfunded ? ' bad' : ''}" data-config-use>${icon(use.unfunded ? 'x' : 'minus', 'i-xs')}<span>${esc(prefix + use.text)}</span></p>`
    : '';
}
// The product under test as an instrument panel: its name and keys on top, the settings it
// runs with read out underneath. An index that lags the policy is the one amber reading.
function productBar(a) {
  const c = a.config;
  const configured = !!a.backend?.configured;
  const stale = a.world.indexVersion < a.world.policyVersion;
  const use = configured ? configUse(a.effectiveConfig, a.world.devDays) : null;
  const gauge = (k, v, cls = '', extra = '') =>
    `<li class="pb-gauge ${cls}"><span class="pb-k">${k}</span> <span class="pb-v">${v}</span>${extra}</li>`;
  const sources = c.domains.map(DOMAIN);
  // A reading that moved since it was last drawn rolls and glows once (Board.reading); under an
  // open dialog the bar keeps showing what it showed, and plays when the dialog has gone.
  const covered = sheetCovers(a);
  const read = (name, value, prefix = '') =>
    covered
      ? `${prefix}${Board.readingShown(a.id, name) ?? value}`
      : Board.reading(a.id, name, value, prefix);
  const gauges = configured
    ? [
        gauge(use ? T('已保存', 'Saved') : T('配置', 'Config'), read('config', a.configVersion, 'v')),
        gauge(T('开放人数', 'Participants'), read('participants', Number(c.participants))),
        gauge(
          T('知识来源', 'Sources'),
          read('sources', sources.length),
          '',
          sources.length ? `<span class="sr-only">${esc(sources.join(T('、', ', ')))}</span>` : '',
        ),
        gauge(T('索引方式', 'Index'), read('index', UPDATE_SHORT(c.update))),
      ]
    : [`<li class="pb-gauge muted">${T('还没有试点设置', 'No pilot settings yet')}</li>`];
  gauges.push(
    gauge(T('政策', 'Policy'), `v${a.world.policyVersion}`),
    gauge(
      T('索引基于', 'Index built on'),
      stale
        ? `${icon('stale', 'i-xs')}${T(`v${a.world.indexVersion}，落后`, `v${a.world.indexVersion}, behind`)}`
        : `v${a.world.indexVersion}`,
      stale ? 'warn' : '',
    ),
  );
  return `<section class="product-bar ${stale ? 'is-stale' : ''}" aria-label="${esc(T('知识助手', 'Knowledge assistant'))}">
    <div class="pb-top">${assistantMark('md')}<p class="pb-name">${T('知识助手', 'Knowledge assistant')}<span class="pb-role">${T('你要决定能否试点的产品', 'The product you are deciding on')}</span></p>
      <div class="pb-keys">${btn(`${icon('flask', 'i-sm')}<span class="pb-key-label">${T('测试台', 'Test bench')}</span>${a.tests.length ? `<span class="btn-count">${a.tests.length}</span>` : ''}`, 'open-bench', 'small', `aria-label="${esc(T('测试台', 'Test bench'))}"`)}${btn(`${icon('gear', 'i-sm')}<span class="pb-key-label">${T('设置', 'Settings')}</span>`, 'config', configured ? 'small quiet' : 'small primary', `aria-label="${esc(T('设置', 'Settings'))}"`)}${btn(`${icon('hand', 'i-sm')}<span class="pb-key-label">${T('申请', 'Requests')}</span>`, 'resources', 'small quiet', `aria-label="${esc(T('申请', 'Requests'))}"`)}</div></div>
    <ul class="pb-state">${gauges.join('')}</ul>${configUseLine(use)}
  </section>`;
}
const UPDATE_SHORT = (k) =>
  ({
    daily: T('每日', 'Daily'),
    realtime: T('实时', 'Real-time'),
    manual: T('转人工', 'Manual check'),
  })[k] || UPDATE(k);
function rankMenu() {
  return `<div class="menu" role="menu"><p class="menu-cap">${T('想听谁的看法', 'Whose view?')}</p>${ROLES.map((r) => `<button type="button" role="menuitem" data-action="ask-priority" data-role="${r}">${avatar(r, 'xs')}<span class="grow">${PEOPLE[r].name}${PEOPLE[r].titled ? '' : `<small>${ROLE_TITLE(r)}</small>`}</span></button>`).join('')}</div>`;
}
// "Ask how to prioritise": the open tasks in board order and the question, for a colleague to
// answer in their own conversation.
function priorityQuestion(a) {
  const order = ['first', 'next', 'later'];
  const list = a.tasks
    .filter((t) => t.status !== 'done')
    .sort((x, y) => order.indexOf(x.priority) - order.indexOf(y.priority))
    .map((t) => taskTitle(t))
    .join(T('；', '; '));
  return list
    ? T(
        '这是我手头的事项：' + list + '。你觉得我该先弄清哪件，为什么？',
        'Here is what I have on my plate: ' + list + '. What would you tackle first, and why?',
      )
    : T(
        '我手头的事项都处理完了。你觉得接下来该先弄清什么，为什么？',
        'Everything on my plate is done. What should I find out next, and why?',
      );
}
// An empty lane says what it is for; the starting tasks all wait in "Up next" for you to rank.
const LANE_HINT = {
  first: () => T('把上线前必须做的拖到这里', 'Drag here what must happen before launch'),
  later: () => T('能等的先放这里', 'Park what can wait'),
};
function column(a, p) {
  const list = a.tasks.filter((t) => t.priority === p);
  const hint = LANE_HINT[p] ? ` data-empty-hint="${esc(LANE_HINT[p]())}"` : '';
  return `<div class="col col-${p}" data-lane="${p}">
    <header class="col-head">${priMark(p)}<span class="col-name">${PRI(p)}</span><span class="col-count">${list.length}</span></header>
    <ol class="cards" role="list" data-board-lane="${p}"${hint}>${L.nativeWorkspace(a) ? '' : list.map((t) => taskCard(a, t)).join('')}${!L.nativeWorkspace(a) && !list.length ? `<li class="col-empty">${T('拖到这里', 'Drop here')}</li>` : ''}</ol>
  </div>`;
}
function taskCard(a, t) {
  const list = taskWorks(a, t.id);
  const tests = a.tests.filter((r) => r.taskId === t.id);
  const stale = tests.some((r) => r.policyVersion < a.world.policyVersion);
  const toCheck = list.filter((w) => w.source !== 'user' && !w.adopted).length;
  const notes = (ui.notesCache || []).filter((n) => n.taskId === t.id);
  const vt = ui.landing && t.seed ? 'seed-' + SEED_KEYS.indexOf(t.seed) : 't-' + vtName(t.id);
  const latest = list.at(-1);
  return `<li class="card ${t.status}" draggable="true" data-task-id="${t.id}" style="view-transition-name: ${vt}; --i: ${a.tasks.indexOf(t)}">
    <button type="button" class="card-open" data-action="open-task" data-id="${t.id}" aria-describedby="move-help">
      <span class="card-head" title="${esc(STATUS(t.status))}">${statusMark(t.status)}<span class="card-title">${esc(taskTitle(t))}</span><span class="sr-only">${esc(STATUS(t.status))}</span></span>
      ${latest ? `<span class="card-latest">${icon('note', 'i-xs')}<span>${esc(shown(latest).title)}</span><em>${esc(purposeLabel(shown(latest).purpose))}</em></span>` : `<span class="card-latest empty">${T('还没有作品', 'No work yet')}</span>`}
      <span class="card-meta"><span title="${esc(T('作品', 'Work'))}">${icon('note', 'i-xs')}${list.length}</span><span title="${esc(T('测试', 'Tests'))}">${icon('flask', 'i-xs')}${tests.length}</span>${notes.length ? `<span class="card-notes" title="${esc(notes.map((n) => PEOPLE[n.role].name).join(T('、', ', ')) + T(' 有提醒', ' left a reminder'))}">${[...new Set(notes.map((n) => n.role))].map((r) => avatar(r, 'xs')).join('')}</span>` : ''}</span>
      ${stale || toCheck ? `<span class="card-flags">${stale ? `<span class="flag-chip warn">${icon('stale', 'i-xs')}${T('测试早于政策更新', 'Tests predate the policy update')}</span>` : ''}${toCheck ? `<span class="flag-chip agent">${agentMark('xs')}${T(toCheck + ' 份回传待检查', toCheck + ' agent return(s) to check')}</span>` : ''}</span>` : ''}
    </button>
    ${workFolderMarkup({ taskId: t.id, title: taskTitle(t), works: list.map(shown) })}
    <button type="button" class="btn icon quiet small card-more" data-action="edit-task" data-id="${t.id}" aria-label="${esc(T('编辑「' + taskTitle(t) + '」', 'Edit “' + taskTitle(t) + '”'))}">${icon('more')}</button>
  </li>`;
}
const WHO = { supervisor: 'manager', business_lead: 'business', tech_lead: 'technical' };
const whoHas = (m) => (m.visible_to || []).map((r) => WHO[r]).filter(Boolean);
// Materials the learner's work cites, so their row can say "Cited".
const citedMaterials = (a) =>
  new Set(
    works(a).flatMap((x) =>
      (shown(x).evidence || []).filter((ev) => ev.type === 'material').map((ev) => ev.id),
    ),
  );
// The first sentence of a text, without Markdown, for a one-line summary.
const firstLine = (text, max = 140) => {
  const t = String(text || '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_`>]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  const one = t.split(/(?<=[。！？])|(?<=[.!?])\s/)[0] || t;
  return one.length > max ? `${one.slice(0, max - 1)}…` : one;
};
// What has been found so far, for the Investigate dossier: plain facts the practice already
// holds (reads, citations, conversations, test runs, tasks and works). No model, no recognition.
function findingsOf(a) {
  const read = readSet(a);
  const cited = citedMaterials(a);
  const docs = E.getMaterials(a).map((m) => {
    const acked = (a.acks || []).includes(`read-${m.id}-v${m.version}`);
    const group = cited.has(m.id)
      ? 'cited'
      : m.version > 1 && !acked
        ? 'new'
        : read.has(m.id) || acked
          ? 'read'
          : 'unread';
    return { id: m.id, title: materialTitle(m), version: m.version, group };
  });
  const people = ROLES.map((r) => {
    const msgs = a.conversations[r] || [];
    const asked = msgs.filter((m) => m.role === 'user').at(-1);
    const reply = msgs.filter((m) => m.role !== 'user').at(-1);
    return {
      role: r,
      name: PEOPLE[r].name,
      title: ROLE_TITLE(r),
      asked: asked ? firstLine(asked.text, 120) : '',
      reply: reply ? previewLine(reply.text) || firstLine(reply.text, 120) : '',
      count: msgs.length,
    };
  });
  const old = (x) => (x.stale !== undefined ? !!x.stale : x.indexVersion < x.policyVersion);
  const tests = a.tests
    .slice()
    .reverse()
    .map((r) => {
      const tk = r.taskId && a.tasks.find((t) => t.id === r.taskId);
      return {
        id: r.id,
        question: r.question,
        answer: firstLine(r.answer),
        versions: T(
          `政策 v${r.policyVersion} · 索引 v${r.indexVersion}`,
          `Policy v${r.policyVersion} · index v${r.indexVersion}`,
        ),
        stale: old(r),
        task: tk ? taskTitle(tk) : '',
      };
    });
  const workOf = (w) => ({
    id: w.id,
    title: shown(w).title || T('未命名', 'Untitled'),
    purpose: purposeLabel(shown(w).purpose),
    version: workVersion(w.revision || 1),
    adopted: !!w.adopted,
  });
  const tasks = a.tasks.map((t) => ({
    id: t.id,
    title: taskTitle(t),
    status: t.status,
    statusLabel: STATUS(t.status),
    works: taskWorks(a, t.id).map(workOf),
  }));
  const unfiled = (a.artifacts || []).filter((w) => !w.taskId && !w.removedAt).map(workOf);
  return { docs, people, tests, tasks, unfiled };
}
// Each material once, with what is new about it: a new version, your agent reading it, unread,
// cited in your work, or read. The board's list and the materials pile say the same.
function docRows(a) {
  const read = readSet(a);
  const cited = citedMaterials(a);
  return E.getMaterials(a).map((m) => {
    const fresh = m.version > 1 && !(a.acks || []).includes(`read-${m.id}-v${m.version}`);
    const state = fresh
      ? 'new'
      : Board.agentReading(m.id)
        ? 'agent'
        : !read.has(m.id) && !(a.acks || []).includes(`read-${m.id}-v${m.version}`)
          ? 'unread'
          : cited.has(m.id)
            ? 'cited'
            : 'read';
    return { id: m.id, title: materialTitle(m), version: m.version, state };
  });
}
function docGrid(a) {
  const rows = docRows(a);
  const html = Board.documentsSection(rows, {
    all: Board.docsAll(a.id),
    loading: snap().connected
      ? T('正在取资料…', 'Loading documents…')
      : T('连上后端后显示资料', 'Documents appear once connected'),
  });
  return html;
}

/* a task's workbench */
function relatedDocs(a, t) {
  const ids = new Set(t.docs || []);
  taskWorks(a, t.id).forEach((w) =>
    (w.evidence || []).forEach((ev) => {
      if (ev.type === 'material') ids.add(ev.id);
    }),
  );
  return E.getMaterials(a).filter((m) => ids.has(m.id));
}
function defaultObj(a, t) {
  const list = taskWorks(a, t.id);
  return list.length
    ? { task: t.id, type: 'work', id: list.at(-1).id }
    : { task: t.id, type: 'start' };
}
function taskView(a, t) {
  if (!ui.obj || ui.obj.task !== t.id) ui.obj = defaultObj(a, t);
  if (
    ui.obj.type === 'work' &&
    !a.artifacts.some((x) => x.id === ui.obj.id && x.taskId === t.id && !x.removedAt)
  )
    ui.obj = defaultObj(a, t);
  return `<div class="task-ws">
    <header class="task-head" style="view-transition-name: t-${vtName(t.id)}">
      <div class="th-row">${priPick(t.id, t.priority, taskTitle(t))}<h2 class="th-title">${esc(taskTitle(t))}</h2><span class="spacer"></span>
        <div class="segmented status-seg" role="group" aria-label="${esc(T('进展', 'Progress'))}"><span class="thumb"></span>${['open', 'working', 'done'].map((k) => `<button type="button" aria-pressed="${t.status === k}" data-action="set-status" data-status="${k}" data-id="${t.id}">${statusMark(k)}<span>${STATUS(k)}</span></button>`).join('')}</div>${btn(icon('more'), 'edit-task', 'icon quiet small', `data-id="${t.id}" aria-label="${esc(T('编辑事项', 'Edit task'))}"`)}</div>
      ${taskNote(t) ? `<p class="th-note">${esc(taskNote(t))}</p>` : ''}
      ${itemBrief(a, t)}
    </header>
    <div class="task-body">
      <nav class="outline" aria-label="${esc(T('这件事的内容', 'What this task holds'))}">${outline(a, t)}</nav>
      <section class="object" id="ws-object">${objectView(a, t)}</section>
    </div>
  </div>`;
}
// Under the item's title (story board P07): where its thinking stands, from its own records
// only. Current lean (the latest decision or comparison, else the latest work), evidence (its
// tests and the documents its work cites), open conditions (tests that predate the policy, a
// decision citing nothing, requests still waiting) and the latest change. Empty parts are left
// out; with nothing to say, there is no line at all.
function itemBrief(a, t) {
  const list = taskWorks(a, t.id).map(shown);
  const tests = (a.tests || []).filter((r) => r.taskId === t.id);
  const lean =
    list.filter((w) => ['commit', 'option'].includes(E.intentOf(w.purpose))).at(-1) || list.at(-1);
  const firstLine = (txt) =>
    String(txt || '')
      .split('\n')
      .map((x) => x.replace(/^#+\s*|^[-*]\s*/, '').trim())
      .find(Boolean) || '';
  const leanText = lean ? firstLine(lean.body) || lean.title : '';
  const docs = new Set(
    list.flatMap((w) => (w.evidence || []).filter((e) => e.type === 'material').map((e) => e.id)),
  );
  const evidence = [
    tests.length ? T(`${tests.length} 次测试`, `${tests.length} test${tests.length > 1 ? 's' : ''}`) : '',
    docs.size ? T(`${docs.size} 份资料`, `${docs.size} document${docs.size > 1 ? 's' : ''}`) : '',
  ].filter(Boolean);
  const v = a.world.policyVersion;
  const stale = tests.length > 0 && tests.every((r) => r.policyVersion < v);
  const decision = list.find((w) => E.intentOf(w.purpose) === 'commit' && String(w.body || '').trim());
  const waiting = (a.requests || []).filter((r) => r.status === 'pending').length;
  const open = [
    stale ? T(`测试都早于政策 v${v}`, `Every test predates policy v${v}`) : '',
    decision && !(decision.evidence || []).length
      ? T('决定还没引用依据', 'The decision cites nothing yet')
      : '',
    waiting ? T(`${waiting} 项申请等批复`, `${waiting} request${waiting > 1 ? 's' : ''} waiting`) : '',
  ].filter(Boolean);
  const lastTest = tests.slice().sort((x, y) => String(x.createdAt).localeCompare(String(y.createdAt))).at(-1);
  const lastWork = list
    .slice()
    .sort((x, y) => String(x.updatedAt || '').localeCompare(String(y.updatedAt || '')))
    .at(-1);
  const change =
    stale
      ? T(`差旅政策更新到 v${v}`, `Travel policy moved to v${v}`)
      : lastTest && (!lastWork || String(lastTest.createdAt) >= String(lastWork.updatedAt || ''))
        ? T(`测了「${lastTest.question}」· ${when(lastTest.createdAt)}`, `Tested “${lastTest.question}” · ${when(lastTest.createdAt)}`)
        : lastWork?.updatedAt
          ? T(`《${lastWork.title}》第 ${lastWork.revision || 1} 版 · ${when(lastWork.updatedAt)}`, `“${lastWork.title}” v${lastWork.revision || 1} · ${when(lastWork.updatedAt)}`)
          : '';
  const cells = [
    leanText ? [T('当前倾向', 'Leaning'), leanText] : null,
    evidence.length ? [T('已有依据', 'Evidence'), evidence.join(T('、', ', '))] : null,
    open.length ? [T('未决条件', 'Still open'), open.join(T('；', '; ')), 'warn'] : null,
    change ? [T('最近变化', 'Latest change'), change] : null,
  ].filter(Boolean);
  if (!cells.length) return '';
  return `<dl class="th-brief">${cells
    .map(([k, val, tone]) => `<div class="th-brief__cell${tone ? ` is-${tone}` : ''}"><dt>${k}</dt><dd>${esc(val)}</dd></div>`)
    .join('')}</dl>`;
}
function outline(a, t) {
  const removed = a.artifacts.filter((x) => x.taskId === t.id && x.removedAt);
  const list = taskWorks(a, t.id);
  const docs = relatedDocs(a, t);
  const tests = a.tests
    .filter((r) => r.taskId === t.id)
    .slice()
    .reverse();
  const on = (type, id) => ui.obj && ui.obj.type === type && (ui.obj.id || '') === (id || '');
  const head = (label, action, attrs, aria) =>
    `<p class="ol-head"><span>${label}</span><button type="button" class="ol-add" data-action="${action}" ${attrs} aria-label="${esc(aria)}" title="${esc(aria)}">${icon('plus', 'i-xs')}</button></p>`;
  return `<div class="ol-sec">${head(T('作品', 'Work'), 'new-artifact', '', T('新作品', 'New piece of work'))}
      ${
        list
          .map((w) => {
            const v = shown(w);
            return `<button type="button" class="ol-row ${on('work', w.id) ? 'on' : ''}" data-action="obj" data-type="work" data-id="${w.id}" ${on('work', w.id) ? 'aria-current="true"' : ''}>${w.source !== 'user' ? agentMark('xs') : icon('note', 'i-sm')}<span class="grow"><span class="ol-title">${esc(v.title)}</span><span class="ol-meta">${esc(purposeLabel(v.purpose))} · ${workVersion(w.revision)}${w.source !== 'user' && !w.adopted ? ` · ${T('待检查', 'to check')}` : ''}</span></span></button>`;
          })
          .join('') ||
        `<button type="button" class="ol-row ghost ${on('start') ? 'on' : ''}" data-action="obj" data-type="start">${icon('plus', 'i-sm')}<span class="grow">${T('开始写', 'Start writing')}</span></button>`
      }
      ${removed.length ? `<button type="button" class="work-recycle-link" data-action="removed-works">${icon('history', 'i-xs')}${T('已移除作品（' + removed.length + '）', 'Removed work (' + removed.length + ')')}</button>` : ''}
    </div>
    <div class="ol-sec">${head(T('资料', 'Documents'), 'pick-doc', '', T('打开一份资料', 'Open a document'))}
      ${docs.map((m) => `<button type="button" class="ol-row ${on('doc', m.id) ? 'on' : ''}" data-action="obj" data-type="doc" data-id="${esc(m.id)}">${icon('doc', 'i-sm')}<span class="grow"><span class="ol-title">${esc(materialTitle(m))}</span><span class="ol-meta">v${m.version}</span></span></button>`).join('') || `<p class="ol-empty">${T('打开或引用过的资料会列在这里', 'Documents you open or cite here appear in this list')}</p>`}
    </div>
    <div class="ol-sec">${head(T('测试', 'Tests'), 'obj', 'data-type="bench"', T('在测试台问一个问题', 'Ask the assistant something'))}
      ${tests.map((r) => `<button type="button" class="ol-row ${on('bench') && ui.lastRun === r.id ? 'on' : ''}" data-action="open-run" data-id="${esc(r.id)}">${icon('flask', 'i-sm')}<span class="grow"><span class="ol-title"${zhAttr(r.question)}>${esc(r.question)}</span><span class="ol-meta ${r.policyVersion < a.world.policyVersion ? 'warn' : ''}">${T('政策 v', 'policy v')}${r.policyVersion}${r.stale ? ' · ' + T('引用过期', 'stale cite') : ''}</span></span></button>`).join('') || `<p class="ol-empty">${T('在测试台问的问题会记在这件事下', 'Questions you ask here are filed under this task')}</p>`}
    </div>`;
}
function objectView(a, t) {
  const o = ui.obj;
  if (o.type === 'doc') return docBody(a, o.id, true);
  if (o.type === 'bench') return bench(a, t);
  if (o.type === 'work') {
    const x = a.artifacts.find((y) => y.id === o.id && !y.removedAt);
    if (x) {
      ui.artifactId = x.id;
      return workView(a, t, x);
    }
  }
  return startView(a, t);
}
// No tiles to click through: the page is already a sheet you can write on.
function startView(a, t) {
  const docsFor = {
    needs: ['business', 'brief'],
    policy: ['policy', 'technical'],
    decision: ['brief', 'approval_process', 'technical'],
  }[t.seed] || ['brief'];
  const docs = E.getMaterials(a).filter((m) => docsFor.includes(m.id));
  const who = t.seed === 'policy' ? 'technical' : t.seed === 'decision' ? 'manager' : 'business';
  return `<div class="obj-pad">
    <article class="paper editor intent-explore">
      <label class="sr-only" for="new-title">${T('标题', 'Title')}</label>
      <input id="new-title" class="editor-title" data-new="title" maxlength="160" placeholder="${esc(T('给这份作品起个名字', 'Name this piece of work'))}">
      <div class="editor-meta"><label class="purpose"><select data-new="purpose" aria-label="${esc(T('用途', 'Purpose'))}">${E.PURPOSES.map((p) => `<option value="${p}" ${p === '探索笔记' ? 'selected' : ''}>${esc(purposeLabel(p))}</option>`).join('')}</select>${icon('down', 'i-xs')}</label><span>${T('开始输入就会保存在这件事下', 'Saved under this task as soon as you type')}</span></div>
      <label class="sr-only" for="new-body">${T('正文', 'Body')}</label>
      <textarea id="new-body" class="editor-body" data-new="body" spellcheck="false" placeholder="${esc(T('你现在想弄清什么？\n\n写判断、要问的问题，或直接起草方案。## 写小标题，- 写列表。', 'What are you trying to figure out?\n\nWrite a judgement, the questions you need to ask, or a draft plan. ## for headings, - for lists.'))}"></textarea>
    </article>
    <div class="side-hints">
      <p class="mini-title">${T('手边可以用', 'At hand')}</p>
      ${docs.map((m) => `<button type="button" class="hint-row" data-action="obj" data-type="doc" data-id="${esc(m.id)}">${icon('doc', 'i-sm')}<span class="grow">${esc(materialTitle(m))}</span><span class="ver">v${m.version}</span></button>`).join('')}
      <button type="button" class="hint-row" data-action="obj" data-type="bench">${assistantMark('xs')}<span class="grow">${T('在测试台问知识助手', 'Ask the knowledge assistant')}</span></button>
      <button type="button" class="hint-row" data-action="chat" data-role="${who}">${avatar(who, 'xs')}<span class="grow">${T(`问 ${PEOPLE[who].name}`, `Ask ${PEOPLE[who].ref}`)}</span></button>
      <button type="button" class="hint-row" data-action="agent">${agentMark('xs')}<span class="grow">${T('交给我的 Agent', 'Hand to my agent')}</span></button>
    </div>
  </div>`;
}
function canEditWork(a, x) {
  return (
    !!x &&
    !x.removedAt &&
    statusOf(a) === 'active' &&
    !storageIssue &&
    !snap().storageError &&
    (!L.nativeWorkspace(a) || L.nativeProductEditable(a))
  );
}
function workControls(a, x, editable, structured = false) {
  const mutable = canEditWork(a, x);
  const pending =
    sessionOf(a)?.pending?.localRun?.workId === x.id ||
    sessionOf(a)?.pending?.localRun?.investigationId === x.id;
  const control = (glyph, label, action, tip, attrs = '') => {
    const tipId = 'tip-' + action + '-' + x.id;
    return `<span class="icon-control"><button type="button" class="btn icon quiet work-icon" data-action="${action}" data-id="${x.id}" aria-label="${esc(label)}" aria-describedby="${tipId}" ${attrs}>${icon(glyph)}</button><span class="action-tooltip" id="${tipId}" role="tooltip">${esc(tip)}</span></span>`;
  };
  return `<div class="work-controls work-controls-icons" role="group" aria-label="${esc(T('作品操作', 'Work actions'))}">
    ${!structured ? control(editable ? 'eye' : 'edit', editable ? T('预览作品', 'Preview work') : T('编辑作品', 'Edit work'), editable ? 'work-preview' : 'work-edit', editable ? T('预览', 'Preview') : T('编辑', 'Edit'), `${!editable && !mutable ? 'disabled' : ''} data-work-mode`) : ''}
    ${control('save', T('保存修改', 'Save changes'), 'save-work', T('保存', 'Save'), mutable && editable ? '' : 'disabled')}
    <span class="work-control-divider" aria-hidden="true"></span>
    ${control('trash', T('删除作品', 'Remove work'), 'remove-work', pending ? T('先恢复未确认的运行', 'Resolve the pending run first') : T('删除', 'Remove'), mutable && !pending ? '' : 'disabled')}
  </div>`;
}
function requireWorkMutation(a, x) {
  if (!canEditWork(a, x))
    throw new Error(
      T(
        '这份作品当前只读，或本地存储不可用。',
        'This work is read-only or local storage is unavailable.',
      ),
    );
}
function localWorkChange(a, change) {
  const backup = structuredClone(a);
  change();
  if (!persist()) {
    for (const key of Object.keys(a)) delete a[key];
    Object.assign(a, backup);
    throw new Error(T('未能保存，作品保留原状。', 'Could not save. The work was kept unchanged.'));
  }
}
function removedWorksSheet(scopeTaskId = task()?.id || null) {
  const a = current();
  if (!a) return;
  const removed = a.artifacts.filter(
    (w) => w.removedAt && (!scopeTaskId || w.taskId === scopeTaskId),
  );
  openSheet(
    T('已移除作品', 'Removed work'),
    `<p class="meta">${T('这里只保留工作台里的副本，电脑上的原文件没有改变。', 'These are workspace copies. Original files on your computer are unchanged.')}</p><div class="removed-work-list">${removed.map((w) => `<div class="removed-work-row"><div class="grow"><h3>${esc(shown(w).title)}</h3><p class="meta">${esc(purposeLabel(w.purpose))} · ${workVersion(w.revision)} · ${esc(when(w.removedAt))}</p></div>${btn(T('恢复', 'Restore'), 'restore-work', 'small', `data-id="${w.id}" ${statusOf(a) === 'active' && !storageIssue && !snap().storageError ? '' : 'disabled'}`)}</div>`).join('') || `<p class="empty-line">${T('没有已移除的作品。', 'No removed work.')}</p>`}</div>`,
    btn(T('关闭', 'Close'), 'close', 'quiet'),
    'narrow',
  );
}
function restoreWork(a, id, trigger) {
  const x = a.artifacts.find((w) => w.id === id);
  if (!x || statusOf(a) !== 'active' || storageIssue || snap().storageError)
    throw new Error(T('当前无法恢复作品。', 'Work cannot be restored right now.'));
  const finish = () => {
    closeSheet(true);
    openTask(x.taskId, { type: 'work', id });
    notify(T('已恢复《' + shown(x).title + '》', 'Restored “' + shown(x).title + '”'));
  };
  if (L.nativeWorkspace(a)) {
    return L.restoreNativeProduct(a, id).then(() => {
      if (current()?.id === a.id && sheet.open && trigger?.isConnected) finish();
    });
  }
  localWorkChange(a, () => E.restoreArtifact(a, id));
  finish();
}
async function restoreWorkFromControl(a, id, trigger) {
  trigger.disabled = true;
  try {
    await restoreWork(a, id, trigger);
  } finally {
    if (trigger.isConnected) trigger.disabled = false;
  }
}
const workChecks = createWorkChecks();
const workCheckKey = (a, x) => `${a.id}:${x.id}`;
function savedWorkBasis(a, x) {
  const products = sessionOf(a)?.v2Workspace?.products || [];
  const saved = products.find((p) => p.product_id === x.id && !p.removed_at);
  const value = L.nativeProductValue(a, x.id);
  if (!saved || !value) return null;
  const fields = (p) => [p.title || '', p.content || '', p.purpose || '', p.evidence_refs || []];
  const isDirty = JSON.stringify(fields(value)) !== JSON.stringify(fields(saved));
  const at = L.v4Host(a)?.snapshot().asOf;
  return { saved, isDirty, key: JSON.stringify([a.id, x.id, saved.version, fields(saved), at?.business_seq, at?.workspace_revision]) };
}
function workCheckSummary(a, x) {
  const basis = savedWorkBasis(a, x);
  return workCheckHtml(workChecks.get(workCheckKey(a, x)), locale(), basis?.key || '', !basis || basis.isDirty);
}
function showWorkCheck(a, x) {
  const basis = savedWorkBasis(a, x);
  if (!basis || basis.isDirty) { notify(T('请先保存作品，再核对本版。', 'Save your work before checking this version.')); return; }
  const host = L.v4Host(a);
  if (!host || statusOf(a) !== 'active') return;
  const key = workCheckKey(a, x);
  openSheet(T('核对本版', 'Check this version'),
    `<p>${esc(basis.saved.title)} · ${workVersion(basis.saved.version)}</p><p class="rc-moment-note">${T('只核对这份已保存版本，不提交决定，也不改作品。', 'Checks only this saved version. It does not submit a decision or change your work.')}</p><div class="rc-work-check-choice"><label for="work-check-decision">${T('你拟作出的交付决定', 'Your intended delivery decision')}</label><select class="select" id="work-check-decision"><option value="">${T('由你选择…', 'Choose a decision…')}</option>${['launch', 'launch_narrow', 'defer_with_conditions', 'no_go'].map((d) => `<option value="${d}">${esc(DECISION(d))}</option>`).join('')}</select><button type="button" class="btn primary" data-work-check-start disabled>${T('核对本版', 'Check this version')}</button></div><div data-work-check-result>${workCheckSummary(a, x)}</div>`,
    btn(T('回到作品', 'Back to the work'), 'close', 'quiet'), 'wide');
  const output = sheet.querySelector('[data-work-check-result]');
  const select = sheet.querySelector('#work-check-decision');
  const button = sheet.querySelector('[data-work-check-start]');
  let controller;
  let running = false;
  let closed = false;
  const currentBasis = () => savedWorkBasis(a, x);
  const stillCurrent = () => !closed && current()?.id === a.id && !currentBasis()?.isDirty && currentBasis()?.key === basis.key;
  const draw = () => { if (output.isConnected) output.innerHTML = workCheckHtml(workChecks.get(key), locale(), currentBasis()?.key || '', !!currentBasis()?.isDirty); };
  const stop = host.subscribe(() => { if (!stillCurrent()) { workChecks.invalidate(key); draw(); } });
  select.addEventListener('change', () => { workChecks.invalidate(key); draw(); button.disabled = running || !select.value || !stillCurrent(); });
  button.addEventListener('click', async () => {
    if (running || !select.value || !stillCurrent()) return;
    const decision = select.value;
    running = true; button.disabled = true; select.disabled = true;
    const result = workChecks.run(key, basis.key, async () => {
      controller = createV4FeedbackAdapter(host);
      await controller.refresh();
      if (!stillCurrent()) throw Error('stale');
      return controller.adapter.previewRecognition({ decision, products: [{ session_id: a.id, kind: 'product', object_id: x.id, version: basis.saved.version }] });
    }, stillCurrent, DECISION(decision));
    draw();
    await result;
    controller?.destroy(); controller = null;
    running = false;
    if (!closed) { select.disabled = false; button.disabled = !select.value || !stillCurrent(); draw(); }
  });
  sheet.addEventListener('close', () => {
    closed = true; stop(); controller?.destroy();
    if (running) workChecks.invalidate(key);
    const summary = document.querySelector('[data-work-check-summary]');
    if (summary && artifact()?.id === x.id) summary.innerHTML = workCheckSummary(a, x);
  }, { once: true });
}
// Native editors stop bubble events; mark old checks stale on the input's capture phase.
document.addEventListener('input', (event) => {
  if (!event.target.matches?.('[data-edit]')) return;
  const a = current(), x = artifact();
  if (!a || !x) return;
  workChecks.invalidate(workCheckKey(a, x));
  const summary = document.querySelector('[data-work-check-summary]');
  if (summary) summary.innerHTML = workCheckSummary(a, x);
}, true);
function workView(a, t, x) {
  if (x.kind === 'test_set') return structuredWorkView(a, t, x);
  if (x.kind === 'investigation') return structuredInvestigationView(a, t, x);
  const list = taskWorks(a, t.id);
  const view = editorView(a, x);
  const intent = E.intentOf(view.purpose);
  const prog = E.agentProgress(a, x);
  const editable = canEditWork(a, x) && ui.previewWorkId !== x.id;
  const showEditor =
    editable || (L.nativeWorkspace(a) && statusOf(a) === 'active' && ui.previewWorkId !== x.id);
  const notes = (ui.notesCache || []).filter(
    (n) => n.targetId === x.id || (!n.targetId && n.taskId === t.id),
  );
  return `<div class="obj-pad ${notes.length ? 'with-margin' : ''}">
    <div class="work-grid">
      <article class="paper editor intent-${intent}">
        ${prog ? agentStrip(a, x, prog) : ''}
        ${workControls(a, x, editable)}
        <label class="sr-only" for="editor-title">${T('标题', 'Title')}</label>
        <input id="editor-title" class="editor-title" data-edit="title" maxlength="160" value="${esc(view.title)}" ${editable ? '' : 'readonly'}>
        <div class="editor-meta">
          <label class="purpose" title="${esc(INTENT_HINT(intent))}"><span class="sr-only">${T('用途', 'Purpose')}</span>${purposeGlyph(intent)}<select data-edit="purpose" ${editable ? '' : 'disabled'}>${E.PURPOSES.map((p) => `<option value="${p}" ${p === view.purpose ? 'selected' : ''}>${esc(purposeLabel(p))}</option>`).join('')}</select>${icon('down', 'i-xs')}</label>
          <span data-revision-label>${workVersion(x.revision)}</span>
          <span>${esc(workSourceLabel(x, locale(), sessionOf(a)?.v2Workspace?.products.find((p) => p.product_id === x.id)?.author.kind))}</span>
          <span class="save" data-save title="${esc(T('作品保存在本机；交付时可合并进交付稿', 'Work stays on this device; fold it into your deliverable when you submit'))}"></span>
        </div>
        ${L.nativeWorkspace(a) ? `<div class="rc-work-check-actions">${btn(T('核对本版', 'Check this version'), 'check-work', 'small', `data-id="${esc(x.id)}" ${canEditWork(a, x) ? '' : 'disabled'}`)}<span class="rc-moment-note">${T('先保存，再选择拟交付决定', 'Save first, then choose your intended decision')}</span></div>` : ''}
        ${showEditor ? `<label class="sr-only" for="editor-body">${T('正文', 'Body')}</label><textarea id="editor-body" class="editor-body" data-edit="body" ${editable ? '' : 'readonly'} maxlength="50000" spellcheck="false" placeholder="${esc(T('写判断、问题，或直接起草方案。## 写小标题，- 写列表。', 'Write a judgement, questions or a draft plan. ## for headings, - for lists.'))}">${esc(view.body)}</textarea>` : `<div class="prose">${md(view.body)}</div>`}
        ${L.nativeWorkspace(a) ? `<section class="rc-work-check" data-work-check-summary>${workCheckSummary(a, x)}</section>` : ''}
        ${L.nativeWorkspace(a) ? nativeEvidenceRow(a, x, T('依据', 'Evidence')) : x.evidence.length ? `<div class="evidence-row"><span class="meta">${T('依据', 'Evidence')}</span>${x.evidence.map((ev) => `<button type="button" class="chip" data-action="view-evidence" data-id="${esc(ev.id)}" data-version="${esc(ev.version ?? '')}">${icon(ev.type === 'test' ? 'flask' : 'doc', 'i-xs')}<span>${esc(evTitle(ev))}</span>${ev.version ? `<span class="ver">v${ev.version}</span>` : ''}</button>`).join('')}</div>` : ''}
      </article>
      ${notes.length ? `<aside class="margin" aria-label="${esc(T('同事的提醒', 'Reminders from colleagues'))}">${notes.map(marginNote).join('')}</aside>` : ''}
    </div>
    <div class="action-bar">
      ${btn(icon('quote', 'i-sm') + T('引用依据', 'Cite evidence'), 'cite-pick', 'small quiet', L.nativeWorkspace(a) && !editable ? 'disabled' : '')}
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
  const view = editorView(a, x);
  const prog = E.agentProgress(a, x);
  const editable = (x.adopted || ui.editPending === x.id) && canEditWork(a, x);
  const evidence = x.evidence.length
    ? `<div class="evidence-row test-set-evidence"><span class="meta">${T('这份计划的依据', 'Evidence for this plan')}</span>${x.evidence.map((ev) => `<button type="button" class="chip" data-action="view-evidence" data-id="${esc(ev.id)}" data-version="${esc(ev.version ?? '')}">${icon(ev.type === 'test' ? 'flask' : 'doc', 'i-xs')}<span>${esc(evTitle(ev))}</span></button>`).join('')}</div>`
    : '';
  return testSetView({
    work: view,
    attempt: a,
    session: sessionOf(a),
    busy: ui.busy || snap().busy,
    canRun: canWrite(a) && !storageIssue && !!a.backend.configured,
    editable,
    opened: ui.testOpen[x.id],
    selectedRuns: ui.testHistory,
    modes: ui.testModes,
    errors: ui.testErrors,
    md,
    strip: (prog ? agentStrip(a, x, prog) : '') + workControls(a, x, editable, true),
    evidence: L.nativeWorkspace(a)
      ? nativeEvidenceRow(a, x, T('这份计划的依据', 'Evidence for this plan'), 'test-set-evidence')
      : evidence,
  });
}
function structuredInvestigationView(a, t, x) {
  const mutable = canEditWork(a, x) && (x.adopted || ui.editPending === x.id);
  const prog = E.agentProgress(a, x);
  return investigationView({
    work: editorView(a, x),
    attempt: a,
    session: sessionOf(a),
    mutable,
    readOnly: !canEditWork(a, x),
    canRun: canWrite(a) && !storageIssue && !!a.backend.configured,
    busy: ui.busy || snap().busy,
    cache: ui.investigationSources,
    errors: ui.investigationErrors,
    controls: workControls(a, x, mutable, true),
    strip: prog ? agentStrip(a, x, prog) : '',
    md,
    diffHtml: investigationDiffHtml,
    viewState: investigationViewState(a, x),
  });
}
async function loadInvestigationSources(a, work, onlyBlockId) {
  for (const block of work.blocks.filter(
    (b) => b.type === 'source_check' && (!onlyBlockId || b.id === onlyBlockId),
  )) {
    const key = investigationSourceKey(a.id, block);
    if (ui.investigationSources[key]) continue;
    ui.investigationSources[key] = { loading: true };
    Promise.allSettled([
      L.citationSource(a, block.testId, block.material.id),
      L.materialVersion(a, block.material.id, block.material.version),
    ]).then((results) => {
      const citation = results[0].status === 'fulfilled' ? results[0].value : null;
      const selected = results[1].status === 'fulfilled' ? results[1].value : null;
      const failed = results.find((r) => r.status === 'rejected');
      ui.investigationSources[key] = {
        loading: false,
        citation,
        selected,
        error: failed
          ? T(
              '暂未取得全部证据，可以重新读取。',
              'Some evidence is unavailable. You can try loading it again.',
            )
          : '',
      };
      if (current()?.id === a.id && ui.obj?.type === 'work' && ui.obj.id === work.id)
        refreshWS(['stage']);
    });
  }
}
async function openInvestigation(runId, chosenTaskId) {
  commit();
  const a = current(),
    run = a?.tests.find((r) => r.id === runId);
  if (!run) throw new Error(T('这条实际测试记录暂不可用。', 'That actual test is unavailable.'));
  if (statusOf(a) !== 'active' || storageIssue)
    throw new Error(
      T(
        '当前只读，不能新建调查。',
        'This practice is read-only; a new investigation cannot be created.',
      ),
    );
  if (L.nativeWorkspace(a)) {
    const target = chosenTaskId || run.taskId;
    if (!target) {
      openSheet(
        T('这份调查放在哪件事下？', 'Which task should contain this investigation?'),
        `<div class="pick-list">${a.tasks.map((t) => `<button type="button" class="pick-row" data-action="native-investigation-task" data-id="${esc(t.id)}" data-run="${esc(runId)}">${esc(taskTitle(t))}</button>`).join('')}</div>`,
        '',
        'narrow',
      );
      return;
    }
    const route = ui.route,
      routeId = ui.routeId;
    const id = await L.createNativeInvestigation(a, runId, target);
    if (current() === a && ui.route === route && ui.routeId === routeId) {
      closeSheet(true);
      openTask(target, { type: 'work', id });
    }
    return;
  }
  const ref = run.citations.find((c) => c.id === 'policy') || run.citations[0];
  const material = ref && E.getMaterials(a).find((m) => m.id === ref.id);
  const seed = [run.id, material?.version || 0, a.configVersion].join('|');
  let work = a.artifacts.find(
    (w) =>
      !w.removedAt &&
      w.kind === 'investigation' &&
      w.ruleOrigin === 'feedback' &&
      w.investigationSeed === seed,
  );
  if (!work) {
    const blocks = [
      {
        type: 'note',
        title: T('先核对实际依据', 'Start with the actual evidence'),
        text: T(
          '先看这次回答实际引用的版本，再对照当前资料。是否调整设置或重测，由你决定。',
          'Check the version this answer actually cited, then compare it with the current source. You decide whether to change settings or rerun.',
        ),
      },
    ];
    if (material)
      blocks.push({
        type: 'source_check',
        testId: run.id,
        material: { id: material.id, version: material.version },
      });
    const other = a.tests.filter((r) => r.question === run.question && r.id !== run.id).at(-1);
    if (other || !material)
      blocks.push({ type: 'test_compare', testIds: other ? [run.id, other.id] : [run.id] });
    blocks.push({ type: 'retest', testId: run.id });
    localWorkChange(a, () => {
      work = E.createArtifact(a, {
        kind: 'investigation',
        taskId: run.taskId || task()?.id || a.tasks[0].id,
        title: T('核对回答与资料', 'Check the answer against its sources'),
        question: T(
          '这次回答用了哪版资料？当前条件下会怎样回答？',
          'Which source version did this answer use, and what happens under the current settings?',
        ),
        blocks,
        source: 'user',
        adopted: true,
        ruleOrigin: 'feedback',
      });
      work.investigationSeed = seed;
    });
  }
  openTask(work.taskId, { type: 'work', id: work.id });
  document.getElementById('main')?.scrollTo(0, 0);
}
async function runInvestigationBlock(blockId) {
  if (ui.busy) return;
  commit();
  const a = current(),
    work = artifact(),
    block = work?.blocks?.find((b) => b.id === blockId),
    baseline = block && a.tests.find((r) => r.id === block.testId);
  if (!a || !work || !baseline || block.type !== 'retest') return;
  if (work.draft || storageIssue || !persist())
    throw new Error(T('先保存这份调查，再运行。', 'Save this investigation before running it.'));
  ui.busy = true;
  delete ui.investigationErrors[blockId];
  refreshWS(['stage']);
  try {
    const rerun = await L.test(a, {
      question: baseline.question,
      expectation: baseline.expectation || '',
      taskId: work.taskId,
      investigationId: work.id,
      investigationRevision: work.revision,
      blockId: block.id,
      blockRevision: block.revision,
      baselineRunId: baseline.id,
    });
    if (!persist())
      throw new Error(
        T(
          '结果已返回，本地视图尚未保存。',
          'The result returned, but the local view has not been saved.',
        ),
      );
    announce(
      rerun?.queued
        ? assistantText('assistant_mode_queued')
        : T('重测结果已返回，原始记录仍保留。', 'The rerun is back. The original record is kept.'),
    );
  } catch (err) {
    ui.investigationErrors[blockId] = errText(err);
  } finally {
    ui.busy = false;
    refreshWS(['stage', 'rail']);
  }
}

// Save a field without replacing the node receiving the next pointer/Tab action.
function updateTestChrome() {
  const a = current(),
    x = artifact();
  if (!a || !x || x.kind !== 'test_set') return;
  const session = sessionOf(a);
  let completed = 0;
  x.cases.forEach((c, i) => {
    const status = caseState(x, c, a, session?.pending, ui.busy || snap().busy);
    if (status.current) completed++;
    const row = document.querySelector(`[data-case-row="${CSS.escape(c.id)}"]`);
    if (!row) return;
    const question = row.querySelector('.test-case-question'),
      intent = row.querySelector('.test-case-intent'),
      badge = row.querySelector('.test-state');
    if (question) question.textContent = c.question || T('写一个测试问题', 'Write a test question');
    if (intent)
      intent.textContent =
        c.intent || T('这个问题想验证什么？', 'What should this question verify?');
    if (badge) {
      badge.textContent = status.label;
      badge.classList.toggle('attention', !!status.tone);
    }
    const version = row.querySelector('.test-case-foot > span');
    if (version)
      version.textContent =
        'v' + c.revision + ' · ' + T('每次重测另存结果', 'Every rerun keeps a new result');
    const runButton = row.querySelector('[data-action="test-run"]');
    if (runButton)
      runButton.disabled =
        !x.adopted ||
        !canWrite(a) ||
        !!storageIssue ||
        !a.backend.configured ||
        !c.question.trim() ||
        !!status.waiting;
    const run = status.runs.find((r) => r.id === ui.testHistory[c.id]) || status.runs[0];
    const result = row.querySelector('.test-result');
    if (result && run && !result.contains(document.activeElement))
      result.outerHTML = testRunView({ run, runs: status.runs, item: c, work: x, session, md });
    document
      .querySelectorAll('.test-progress > span')
      [i]?.classList.toggle('recorded', !!status.current);
  });
  const count = document.querySelector('.test-count-results');
  if (count)
    count.textContent = T(
      completed + ' / ' + x.cases.length + ' 问题有结果',
      completed + ' / ' + x.cases.length + ' questions have results',
    );
  const label = document.querySelector(`.ol-row[data-id="${CSS.escape(x.id)}"] .ol-meta`);
  if (label) label.textContent = purposeLabel(x.purpose) + ' · v' + x.revision;
  updateSave();
}
function animateTestReveal(id) {
  if (reduceMotion.matches || ui.kbd) return;
  document.getElementById('case-panel-' + id)?.animate(
    [
      { opacity: 0, transform: 'translateY(-4px)' },
      { opacity: 1, transform: 'none' },
    ],
    { duration: 180, easing: 'cubic-bezier(.32,.72,0,1)' },
  );
}
async function runTestCase(id) {
  if (ui.busy) return;
  commit();
  const a = current(),
    x = artifact();
  if (!a || !x || x.kind !== 'test_set') return;
  if (x.draft || storageIssue || !persist())
    throw new Error(T('先保存这份计划，再运行测试。', 'Save this plan before running a test.'));
  const c = x.cases.find((c) => c.id === id);
  if (!c) return;
  ui.testOpen[x.id] = id;
  delete ui.testErrors[id];
  ui.busy = true;
  refreshWS(['stage']);
  try {
    const r = await L.test(a, {
      question: c.question,
      expectation: c.expectation || '',
      intent: c.intent,
      refs: c.refs || [],
      taskId: x.taskId,
      workId: x.id,
      workRevision: x.revision,
      caseId: c.id,
      caseRevision: c.revision,
    });
    ui.lastRun = r.id;
    if (!r.queued) {
      ui.testHistory[id] = r.id;
      ui.testModes[id] = 'result';
    }
    startWorking(a, task());
    if (!persist())
      throw new Error(
        T(
          '测试已有结果，本地显示未保存。保留当前页面后重试保存。',
          'The test returned a result, but the local view was not saved. Keep this page open and retry saving.',
        ),
      );
    announce(
      r.queued
        ? assistantText('assistant_mode_queued')
        : T('这条问题已有回答，请检查结果。', 'This question has an answer. Review the result.'),
    );
  } catch (err) {
    ui.testErrors[id] = errText(err);
  } finally {
    ui.busy = false;
    refreshWS(['stage', 'rail']);
    animateTestReveal(id);
  }
}

const KIND = (k) =>
  ({
    remind: T('提醒', 'Reminder'),
    object: T('异议', 'Objection'),
    correct: T('纠正', 'Correction'),
    help: T('帮忙', 'Offer'),
  })[k] || '';
function marginNote(n) {
  return `<div class="note ${n.kind} who-${n.role}" data-note="${esc(n.key)}">
    <p class="note-head">${avatar(n.role, 'xs')}<b>${PEOPLE[n.role].name}</b><span class="note-kind">${KIND(n.kind)}</span><span class="rule-tag" title="${esc(T('按场景规则生成，不是同事实时回复', 'Generated from scenario rules, not a live reply'))}">${T('规则', 'Rule')}</span></p>
    <p class="note-text" data-note-message-id="${esc(noteKey(n.key))}">${esc(n.text)}</p>
    <div class="note-actions"><button type="button" class="link" data-action="reply-note" data-key="${esc(n.key)}">${T('回应', 'Reply')}</button><button type="button" class="link quiet" data-action="ack" data-key="note:${esc(n.key)}">${T('先放下', 'Set aside')}</button></div>
  </div>`;
}
const evTitle = (ev) =>
  ev.type === 'test'
    ? String(ev.title || '').replace(/^测试：/, '')
    : materialTitle({ id: ev.id, title: ev.title });
function agentStrip(a, x, prog) {
  if (!['test_set', 'investigation'].includes(x.kind) && !x.requestId)
    return `<div class="import-work-status">${icon('doc', 'i-sm')}<div class="grow"><b>${x.adopted ? T('已采用', 'Adopted') : T('待检查', 'To check')}</b><span>${sessionOf(a)?.v2Workspace?.products.find((p) => p.product_id === x.id)?.author.kind === 'external_agent' ? T('Agent 制作；采用后仍需本人检查结论。', 'Made by an Agent; check its claims after adoption.') : T('这是导入副本，修改不会影响原文件。', 'This is an imported copy. Edits leave the original file unchanged.')}</span></div>${!x.adopted && canEditWork(a, x) ? btn(T('采用为当前作品', 'Adopt this work'), 'adopt', 'small primary', `data-id="${x.id}"`) : ''}</div>`;
  const steps = [
    ['exported', T('已交出', 'Handed over')],
    ['returned', T('已带回', 'Returned')],
    ['adopted', T('已采用', 'Adopted')],
    [
      'linked',
      prog.linkedRuns
        ? T(
            '关联测试 ' + prog.linkedRuns + ' 次',
            prog.linkedRuns + ' linked test' + (prog.linkedRuns > 1 ? 's' : ''),
          )
        : T('未关联测试', 'No linked test'),
    ],
  ];
  return `<div class="agent-strip">${agentMark('xs')}<ol>${steps.map(([k, l]) => `<li class="${prog[k] ? 'done' : ''}">${l}</li>`).join('')}</ol>${!x.adopted && canEditWork(a, x) ? `<span class="spacer"></span>${ui.editPending === x.id || L.nativeWorkspace(a) ? '' : btn(T('编辑', 'Edit'), 'edit-pending', 'small quiet', `data-id="${x.id}"`)}${btn(T('采用', 'Adopt'), 'adopt', 'small primary', `data-id="${x.id}"`)}` : ''}</div>${(x.staleInputs || []).length ? `<p class="warn-line">${icon('stale', 'i-sm')}${T('它基于你较早的版本，采用前先对照。', 'It was based on an earlier version of your work. Compare before adopting.')}</p>` : ''}`;
}
function docBody(a, id, inTask) {
  const list = E.getMaterials(a);
  if (!list.length)
    return `<div class="empty">${T('还没有取得资料。', 'No documents yet.')}${btn(T('刷新', 'Refresh'), 'live-refresh', 'small')}</div>`;
  const m = list.find((x) => x.id === id) || list[0];
  const prev = ui.previous[m.id];
  const compare = ui.compare && prev && prev.version < m.version;
  const zhOnly = locale() === 'en' && isChinese(m.content);
  const who = whoHas(m);
  return `<div class="${inTask ? 'obj-pad' : ''}">
    <article class="paper document" data-document-id="${esc(m.id)}">
      <header class="doc-head"><span class="doc-icon">${icon('doc')}</span><div class="grow"><h2 class="doc-title" id="document-title-${esc(m.id)}" tabindex="-1">${esc(materialTitle(m))}</h2><p class="doc-meta"><span class="stamp">v${m.version}</span>${m.id === 'policy' ? `<span class="${a.world.indexVersion < m.version ? 'warn' : ''}">${T('知识助手索引 v' + a.world.indexVersion, 'Assistant index v' + a.world.indexVersion)}</span>` : ''}${zhOnly ? `<span class="lang-tag" title="The server sends this document in Chinese until an English version exists.">Chinese source</span>` : ''}</p></div>
        ${m.version > 1 ? `<button type="button" class="toggle" data-action="toggle-compare" aria-pressed="${!!compare}">${icon('layers', 'i-sm')}${T('对比 v' + (m.version - 1), 'Compare with v' + (m.version - 1))}</button>` : ''}</header>
      <div class="prose serif"${zhOnly ? ' lang="zh-CN"' : ''}>${compare ? diffHtml(prev.content, m.content) : md(m.content, { dropTitle: true })}</div>
      <footer class="doc-foot">${btn(icon('quote', 'i-sm') + (inTask ? T('引用到这件事的作品', 'Cite in this task’s work') : T('引用到作品', 'Cite in my work')), 'cite-material', 'small', `data-id="${esc(m.id)}"`)}${who.map((r) => btn(avatar(r, 'xs') + T('问' + PEOPLE[r].name, 'Ask ' + PEOPLE[r].ref), 'discuss-material', 'small quiet', `data-id="${esc(m.id)}" data-role="${r}"`)).join('')}</footer>
    </article>
  </div>`;
}
function bench(a, t) {
  const c = a.config;
  const stale = a.world.indexVersion < a.world.policyVersion;
  const configured = !!a.backend?.configured;
  const use = configured ? configUse(a.effectiveConfig, a.world.devDays) : null;
  const s = sessionOf(a);
  const runs = t && !ui.benchAll ? a.tests.filter((r) => r.taskId === t.id) : a.tests;
  return `<div class="${t ? 'obj-pad' : ''} lab">
    <section class="console ${stale ? 'is-stale' : ''}">
      <header class="console-head">${assistantMark('lg')}<div class="grow">
        <h2 class="console-name">${T('知识助手', 'Knowledge assistant')}<span class="console-role">${T('你要决定能否试点的产品', 'The product you are deciding on')}</span></h2>
        ${
          configured
            ? `<ul class="bench-state">${[
                [use ? T('已保存', 'Saved') : T('配置', 'Config'), `v${a.configVersion}`],
                [T('开放人数', 'Users'), c.participants],
                [
                  T('知识来源', 'Sources'),
                  `${c.domains.length}<span class="sr-only">${esc(c.domains.map(DOMAIN).join(T('、', ', ')))}</span>`,
                ],
                [T('索引方式', 'Index'), UPDATE_SHORT(c.update)],
                [T('政策', 'Policy'), `v${a.world.policyVersion}`],
                [
                  T('索引基于', 'Index built on'),
                  stale ? `${icon('stale', 'i-xs')}${T(`v${a.world.indexVersion}，落后`, `v${a.world.indexVersion}, behind`)}` : `v${a.world.indexVersion}`,
                  stale ? 'warn' : '',
                ],
              ]
                .map(([k, v, cls = '']) => `<li class="pb-gauge ${cls}"><span class="pb-k">${k}</span> <span class="pb-v">${v}</span></li>`)
                .join('')}</ul>`
            : `<p class="console-hint">${T('先定试点范围，助手才能回答。', 'Set the pilot scope before the assistant can answer.')}</p>`
        }
        ${configUseLine(use)}
      </div><div class="console-tools">${L.nativeWorkspace(a) && ENGINEER_CASES.includes(a.scenarioId) && a.tests.length ? btn(icon('branch', 'i-sm') + (roleOf(a.id) === 'pm' ? T('交给 Daniel', 'Hand to Daniel') : T('交给工程', 'Hand to engineering')), 'engineer-handover', 'small quiet') : ''}${stale && configured ? btn(icon('refresh', 'i-sm') + T('刷新索引', 'Refresh index'), 'refresh-index', 'small quiet') : ''}${btn(icon('gear', 'i-sm') + T('试点设置', 'Pilot settings'), 'config', configured ? 'small quiet' : 'small primary')}</div></header>
      <form class="console-compose" data-form="run-test">
        <label class="sr-only" for="lab-q">${T('你想问助手什么', 'Your question for the assistant')}</label>
        <textarea id="lab-q" name="question" class="console-q" rows="2" required maxlength="4000" placeholder="${esc(T('像员工那样问它一个问题…', 'Ask what an employee would ask…'))}">${esc(s?.inputs.question || ui.labPrefill)}</textarea>
        <div class="console-row"><label class="sr-only" for="lab-e">${T('想确认什么（选填）', 'What are you checking? (optional)')}</label><input id="lab-e" name="expectation" class="input" maxlength="5000" value="${esc(s?.inputs.expected || '')}" placeholder="${esc(T('想确认什么？选填', 'What are you checking? Optional'))}"><button type="submit" class="btn primary run-btn" ${ui.busy || !configured ? 'disabled' : ''}>${icon('play', 'i-sm')}${ui.busy ? T('运行中', 'Running') : T('运行', 'Run')}</button></div>
        <p class="console-file">${icon('note', 'i-xs')}${t ? esc(T(`结果记在「${taskTitle(t)}」下`, `Results are filed under “${taskTitle(t)}”`)) : T('这些结果不归入事项；从事项里打开测试台才会归档。', 'These results aren’t filed under a task. Open the bench from a task to file them.')}</p>
      </form>
    </section>
    ${t ? `<div class="runs-head"><div class="segmented" role="group"><span class="thumb"></span><button type="button" aria-pressed="${!ui.benchAll}" data-action="bench-scope" data-all="0">${T('这件事的测试', 'This task')}</button><button type="button" aria-pressed="${!!ui.benchAll}" data-action="bench-scope" data-all="1">${T('全部测试', 'All tests')}</button></div></div>` : ''}
    <div class="runs">${queuedRuns(a, t)}${
      runs.length
        ? groupRuns({ tests: runs })
            .map((g) => runGroup(a, g))
            .join('')
        : (a.queuedTests || []).length
          ? ''
          : `<p class="empty-line">${T('还没有测试。和预期不符的回答，往往最有用。', 'No tests yet. Surprising answers are the useful ones.')}</p>`
    }</div>
  </div>`;
}
function queuedRuns(a, t) {
  return (a.queuedTests || [])
    .filter((q) => !t || ui.benchAll || q.taskId === t.id)
    .map(
      (q) =>
        `<article class="run is-queued" data-queued-request="${esc(q.requestId)}"><header class="run-q"><span class="run-asker">${T('你问', 'You asked')}</span><h3${zhAttr(q.question)}>${esc(q.question)}</h3></header><p class="answer-mode" data-answer-mode="queued" role="status">${esc(assistantText('assistant_mode_queued'))}</p></article>`,
    )
    .join('');
}
function groupRuns(a) {
  const map = new Map();
  a.tests
    .slice()
    .reverse()
    .forEach((r) => {
      const k = r.question.trim();
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(r);
    });
  return [...map.values()];
}
function runGroup(a, runs) {
  const r = runs[0];
  const comparison = comparisonFor(r, a.tests);
  const paired = comparison.referenced ? [r, ...(comparison.previous ? [comparison.previous] : [])] : runs.slice(0, 2);
  const ordinal = (x) => a.tests.findIndex((t) => t.id === x.id) + 1;
  // `stale` is the server's own flag: the cited version differs from the current source.
  const old = (x) => (x.stale !== undefined ? !!x.stale : x.indexVersion < x.policyVersion);
  const tk = r.taskId && a.tasks.find((t) => t.id === r.taskId);
  return `<article class="run ${r.id === ui.lastRun ? 'fresh' : ''}" id="run-${esc(r.id)}">
    <header class="run-q"><span class="run-asker">${T('你问', 'You asked')}</span><h3${zhAttr(r.question)}>${esc(r.question)}</h3>${runs.length > 1 ? `<span class="meta">${T(runs.length + ' 次', runs.length + ' runs')}</span>` : ''}${tk && ui.route !== 'task' ? `<button type="button" class="run-task" data-action="open-task" data-id="${tk.id}">${icon('note', 'i-xs')}${esc(taskTitle(tk))}</button>` : ''}</header>
    ${r.expectation ? `<p class="run-expect">${icon('eye', 'i-xs')}<span${zhAttr(r.expectation)}>${esc(r.expectation)}</span></p>` : ''}
    ${testAgeText(r, a.world.policyVersion, locale()) ? `<p class="rc-test-age">${esc(testAgeText(r, a.world.policyVersion, locale()))}</p>` : ''}
    <div class="run-cols ${paired.length > 1 ? 'two' : ''}">${paired
      .map(
        (
          x,
          i,
        ) => `<div class="run-col">${runs.length > 1 ? `<p class="col-cap">${(i === 0 ? T('最新', 'Latest') : comparison.referenced ? T('识别基准', 'Recognition baseline') : T('上一次', 'Previous')) + T(` · 第 ${ordinal(x)} 次测试`, ` · Run ${ordinal(x)}`)}</p>` : ''}
      <div class="answer ${x.fallback ? 'handoff' : ''}">${assistantMark('sm')}<div class="answer-body"${zhAttr(x.answer)}>${answerModeLine(x)}${md(x.answer, { dropTitle: true })}${zhTag(x.answer) ? `<p class="answer-tag">${zhTag(x.answer)}</p>` : ''}</div></div>
      <div class="run-meta"><span class="stamp">${T('配置 v', 'Config v')}${x.configVersion}</span><span class="stamp ${old(x) ? 'warn' : ''}">${old(x) ? icon('stale', 'i-xs') : ''}${T(`政策源 v${x.policyVersion} · 索引 v${x.indexVersion}`, `Policy v${x.policyVersion} · index v${x.indexVersion}`)}</span>${x.citations.map((c) => `<button type="button" class="chip" data-action="run-source" data-run="${esc(x.id)}">${icon('doc', 'i-xs')}<span>${esc(materialTitle({ id: c.id, title: c.title }))}</span><span class="ver">v${c.version}</span></button>`).join('')}</div></div>`,
      )
      .join('')}</div>
    ${testMomentHtml(r, a.tests, locale(), materialNameOf(a))}
    <div class="run-lens">${runSignals(a, r)}${paired[1] ? `<details class="run-baseline-signals"><summary>${T('比较对象的识别记录', 'Recognition records of the comparison run')}</summary>${runSignals(a, paired[1])}</details>` : ''}</div>
    ${comparison.referenced && !comparison.previous ? `<p class="meta">${T('识别记录指定的比较对象未载入；没有用上一次测试代替。', 'The recorded comparison baseline is not loaded; the previous run has not been substituted.')}</p>` : ''}
    ${old(r) ? `<p class="flag">${icon('warn', 'i-sm')}${T('这次回答引用的版本已经不是最新。', 'This answer cites a version that is no longer current.')}</p>` : ''}
    <div class="run-actions">${btn(icon('layers', 'i-xs') + T('看依据', 'Check sources'), 'investigate-run', 'small quiet', `data-id="${esc(r.id)}"`)}${btn(icon('refresh', 'i-xs') + T('同题重测', 'Run again'), 'rerun', 'small quiet', `data-id="${esc(r.id)}"`)}${btn(icon('quote', 'i-xs') + T('作为依据', 'Use as evidence'), 'cite-run', 'small quiet', `data-id="${esc(r.id)}"`)}${btn(avatar('technical', 'xs') + T('问技术负责人', 'Ask the technical lead'), 'discuss-run', 'small quiet', `data-id="${esc(r.id)}"`)}</div>
  </article>`;
}

/* the rail: people, and what needs you. A chat pushes in where the people were. */
function wsRail(a) {
  // Until the agent and result lines take them over, their panels open in place of the people.
  const body =
    ui.railTab === 'feedback'
      ? railFeedback(a, routeTask(a))
      : ui.railTab === 'agent'
        ? railAgent()
        : ui.rail === 'chat' && ui.chatRole
          ? railChat(a, ui.chatRole)
          : railTeam(a);
  const back =
    ui.railTab === 'feedback' || ui.railTab === 'agent'
      ? `<div class="rail-top">${btn(icon('back'), 'rail-tab', 'icon quiet small', `data-tab="team" aria-label="${esc(T('返回', 'Back'))}"`)}<span class="grow"></span>${btn(icon('x'), 'close-panels', 'icon quiet small rail-close', `aria-label="${esc(T('关闭', 'Close'))}"`)}</div>`
      : `<div class="rail-top rail-top-min">${btn(icon('x'), 'close-panels', 'icon quiet small rail-close', `aria-label="${esc(T('关闭', 'Close'))}"`)}</div>`;
  return `${back}<div class="rail-body ${Board.takeRailPush()}">${body}</div>`;
}
// Where the rail is a drawer, what needs you shows as one line on the desk (B3): how many,
// who first; it opens the rail at "Needs you".
function needsStrip(a) {
  const list = Board.collectSignals(a).slice(0, 3);
  if (!list.length) return '';
  const first = list[0];
  const who =
    first.source === 'person' && first.person ? avatar(first.person, 'xs') : agentMark('xs');
  return `<button type="button" class="needs-strip" data-action="board-needs-open">${who}<span class="needs-strip-label">${T('需要你回应', 'Needs you')}</span><span class="needs-strip-n">${list.length}</span><span class="needs-strip-text">${esc(first.text)}</span>${icon('chev', 'i-sm')}</button>`;
}
const signalPeople = () =>
  Object.fromEntries(ROLES.map((r) => [r, { name: PEOPLE[r].name, title: ROLE_TITLE(r) }]));
function railTeam(a) {
  const typing = typingRole(a);
  const replying = replyingRoles(a);
  const signals = Board.collectSignals(a);
  const needs = Board.needsYou(signals, signalPeople(), Board.freshSignals(signals.map((x) => x.id)));
  return `<div class="rail-board">
    ${needs}
    <section aria-labelledby="people-h"><h3 class="mini-title" id="people-h">${T('同事', 'Colleagues')}</h3><ul class="people">${(hatHere(a) === 'engineer' ? ['technical', 'manager', 'business'] : ROLES).map(
      (r) => {
        const last = (a.conversations[r] || []).filter((m) => m.role !== 'user').at(-1);
        const n = unread(a, r);
        const waits = typing === r || replying.has(r);
        const line = waits
          ? `<span class="person-replying">${T('正在回复…', 'Replying…')}</span>`
          : (last && teamLine(last.text)) || esc(Board.roleLine(r));
        return `<li class="person-row"><button type="button" class="person ${n ? 'unread' : ''}" data-action="chat" data-role="${r}">${avatar(r, 'md', { typing: waits })}<span class="grow"><span class="person-name">${PEOPLE[r].name}${PEOPLE[r].titled ? '' : `<small>${ROLE_TITLE(r)}</small>`}</span><span class="person-line">${line}</span></span>${unreadBadge(n)}</button><button type="button" class="btn quiet small rc-greet-recall" data-action="greet-chat" data-role="${r}" aria-label="${esc(T(`回看 ${PEOPLE[r].name} 的介绍`, `Read ${PEOPLE[r].name}’s introduction`))}">${T('介绍', 'Intro')}</button></li>`;
      },
    ).join('')}
      <li class="people-sep" role="separator"></li>
      <li><button type="button" class="person mine" data-action="board-my-agent">${agentMark('md')}<span class="grow"><span class="person-name">${T('我的 Agent', 'My agent')}<span class="rc-agent-light" data-state="${agentConnection().state}" role="img" aria-label="${esc(agentConnection().state === 'connected' ? T('已连接', 'Connected') : T('未连接或空闲', 'Not connected or idle'))}"></span><small>${T('你自己的工具', 'Your own tool')}</small></span><span class="person-line">${esc(agentLine(a, hatOf(a.id), agentConnection(), feedStore.snapshot().events))}</span></span></button></li>
    </ul></section>
  </div>`;
}
// The first sentence of the last reply, without Markdown, source tags or the local reference's
// lines about itself; a reply quoted by rules keeps the grey mark. Empty when nothing fits.
function teamLine(text) {
  const line = previewLine(text);
  if (!line) return '';
  return `${isLocalReply(text) ? modelWaitHtml() : ''}<span${zhAttr(line)}>${esc(line)}</span>`;
}
// Colleagues still answering a question sent from this browser (native practices): the request
// is pending on the server and its reply is not in the conversation yet.
function replyingRoles(a) {
  const host = L.v4Host(a);
  if (!host?.pendingRequests) return new Set();
  try {
    const replied = new Set(
      ROLES.flatMap((r) => (a.conversations[r] || []).map((m) => m.traceId).filter(Boolean)),
    );
    const ids = awaitingRoles(host.pendingRequests(), requestRefs(host, 'roles'), replied);
    return new Set([...ids].map((id) => ROLE_OF[id]).filter(Boolean));
  } catch (_) {
    return new Set();
  }
}
/* ---------- the pilot PRD travels with a question (AIPM v2, Q5) ---------- */
// Which PRD versions each colleague has been shared, read from the share projection. A colleague
// who has not seen the latest version gets it attached by default; the person can take it off.
const prdShares = new Map(); // `${session}:${role}` → Set of `${product}@${version}`
const prdSharesAt = new Map(); // session → version point the shares were read at
const prdChoice = new Map(); // `${session}:${role}:${version}` → attach (true/false) chosen
const mentorPrompts = new Map(); // `${session}:${role}` → preset prompts from the review asked from
// Without a conversation model a colleague answers with excerpts; the review's rule-triggered
// question for them follows as a dashed card that says it is preset, not their reply. With a
// model the card waits, and shows only when their latest reply was held back by the checks, so
// the person is never left with nothing.
function mentorCard(a, role) {
  const prompts = mentorPrompts.get(`${a.id}:${role}`) || [];
  if (!prompts.length) return '';
  const model = L.v4Host(a)?.snapshot().semantic?.roles === 'model';
  const name = PEOPLE[role].name;
  return `<aside class="aipm-mentor"${model ? ' data-when="held"' : ''}>${prompts
    .map(
      (m) =>
        `<p class="aipm-mentor__label">${T(`预设提示 · 按批改规则触发，不是 ${name} 的实时回复`, `Preset prompt · triggered by review rules, not ${PEOPLE[role].ref}’s live reply`)}</p><p class="aipm-mentor__q">${T('“', '“')}${esc(m.question)}${T('”', '”')}</p>${
          m.materialId
            ? `<button type="button" class="aipm-mentor__link" data-action="open-material" data-id="${esc(m.materialId)}">${esc(m.pointer || T('打开相关资料', 'Open the material'))} ›</button>`
            : m.pointer
              ? `<p class="aipm-mentor__pointer">${esc(m.pointer)}</p>`
              : ''
        }`,
    )
    .join('')}</aside>`;
}
function prdShared(a, role, prd) {
  if (!a || !prd) return undefined;
  const set = prdShares.get(`${a.id}:${ROLE_ID[role]}`);
  return set ? set.has(`${prd.id}@${prd.version}`) : undefined;
}
async function readPrdShares(a) {
  const host = L.v4Host(a);
  const at = JSON.stringify(host?.snapshot().asOf ?? null);
  if (!host || prdSharesAt.get(a.id) === at) return;
  prdSharesAt.set(a.id, at);
  try {
    const found = new Map();
    let cursor = 0;
    for (;;) {
      const page = await host.query('work_products.list', { cursor, limit: 100 });
      const data = page?.result ?? page;
      for (const share of data.shares || []) {
        if (share.revoked_at != null || !share.product) continue;
        const key = `${a.id}:${share.recipient_role}`;
        if (!found.has(key)) found.set(key, new Set());
        found.get(key).add(`${share.product.object_id}@${share.product.version}`);
      }
      if (data.next_cursor == null || data.next_cursor <= cursor) break;
      cursor = data.next_cursor;
    }
    for (const r of ROLES) prdShares.set(`${a.id}:${ROLE_ID[r]}`, found.get(`${a.id}:${ROLE_ID[r]}`) || new Set());
    if (current()?.id === a.id && ui.rail === 'chat') refreshWS(['rail']);
  } catch (_) {
    prdSharesAt.delete(a.id);
  }
}
const prdAttached = (a, role, prd) =>
  prdChoice.get(`${a.id}:${role}:${prd.version}`) ?? prdShared(a, role, prd) === false;
// The chip above the composer, and what this colleague can see, in one line at the top.
// A review's own words, offered beside the short prefill: one click puts them in the message.
const reviewDetails = new Map();
function detailChip(a, role) {
  return reviewDetails.has(`${a.id}:${role}`)
    ? `<button type="button" class="aipm-prd-chip" data-action="aipm-detail-insert" data-role="${role}">${icon('plus', 'i-xs')}${T('附上批改摘要', 'Add the review summary')}</button>`
    : '';
}
function prdChip(a, role) {
  const prd = aipmHere(a) ? Aipm.prdOf(a) : null;
  if (!prd) return '';
  void readPrdShares(a);
  const seen = prdShared(a, role, prd);
  if (seen === undefined) return '';
  if (seen)
    return `<p class="aipm-prd-note">${T(`${PEOPLE[role].name} 已看过试点 PRD 第 ${prd.version} 版`, `${PEOPLE[role].ref} has seen pilot PRD version ${prd.version}`)}</p>`;
  const on = prdAttached(a, role, prd);
  return `<button type="button" class="aipm-prd-chip" data-action="aipm-prd-toggle" data-role="${role}" aria-pressed="${on}">${on ? icon('check', 'i-xs') : ''}${T(`附上 PRD 第 ${prd.version} 版`, `Attach PRD version ${prd.version}`)}</button>`;
}
function prdSees(a, role) {
  const prd = aipmHere(a) ? Aipm.prdOf(a) : null;
  if (!prd) return '';
  const set = prdShares.get(`${a.id}:${ROLE_ID[role]}`);
  const versions = set
    ? [...set].filter((k) => k.startsWith(`${prd.id}@`)).map((k) => Number(k.split('@')[1]))
    : [];
  const latest = versions.length ? Math.max(...versions) : 0;
  const name = PEOPLE[role].name;
  // One line that opens: what this colleague has, and on request what they do not.
  return `<details class="aipm-sees"><summary><b>${T(`${name} 能看到：`, `${PEOPLE[role].ref} can see: `)}</b><span class="aipm-sees__what">${
    latest
      ? T(`试点 PRD 第 ${latest} 版 · 你的消息`, `pilot PRD version ${latest} · your messages`)
      : T('你消息里写的内容（还没附上 PRD）', 'what your messages say (no PRD attached yet)')
  }</span><span class="aipm-sees__i" aria-hidden="true">ⓘ</span></summary><p>${T('看不到：没附上的版本、你的 Agent 对话、批改单里的其余内容', 'Cannot see: versions you did not attach, your agent’s conversation, the rest of a review')}</p></details>`;
}
// Sending with the chip on: share that exact PRD version first, then let the message go as usual
// (a native turn carries every share its colleague has).
document.addEventListener(
  'submit',
  async (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || form.dataset.form !== 'chat') return;
    if (form.dataset.prdReady === '1') {
      delete form.dataset.prdReady;
      return;
    }
    const a = current(),
      role = ui.chatRole,
      prd = a && aipmHere(a) ? Aipm.prdOf(a) : null;
    if (!a || !prd || !role || !prdAttached(a, role, prd) || prdShared(a, role, prd) !== false) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    try {
      const result = await L.v4Host(a).command('work_products.shares.create', {
        product_id: prd.id,
        product_version: prd.version,
        recipient_role: ROLE_ID[role],
      });
      if (result.status !== 'confirmed') throw new Error(result.result?.message || result.status);
      prdShares.get(`${a.id}:${ROLE_ID[role]}`)?.add(`${prd.id}@${prd.version}`);
    } catch (err) {
      notify(
        T(
          `PRD 没有附上，消息还没发：${err?.message || err}`,
          `The PRD was not attached, so nothing was sent: ${err?.message || err}`,
        ),
      );
      return;
    }
    // Hand it to the bound composer as a typed message would go, and, once it is accepted, clear
    // the draft the way a suggested question does (the composer kept it while the share was made).
    const live = document.querySelector('form.composer[data-form="chat"]') || form;
    const question = live.querySelector('#chat-input')?.value ?? '';
    const token = crypto.randomUUID();
    live.addEventListener('rolecraft:greeting-result', async function done(event) {
      if (event.detail?.token !== token) return;
      live.removeEventListener('rolecraft:greeting-result', done);
      if (!event.detail.accepted) return;
      const key = `question:${ROLE_ID[role]}`;
      const host = L.v4Host(a);
      if (host?.draft('roles', key) === question) await host.keepDraft('roles', key, '');
      const input = document.getElementById('chat-input');
      if (input && input.value === question) input.value = '';
    });
    live.dataset.greetingRequest = token;
    live.dataset.prdReady = '1';
    const send = live.querySelector('button[type="submit"]');
    live.requestSubmit(send || undefined);
  },
  true,
);
// The introduction folds to one line once you have written to that colleague (once, so opening
// it again stays open).
const introFolded = new Set();
function foldIntroduction(a, role, msgs, sending = false) {
  const key = `${a.id}:${role}`;
  if (introFolded.has(key) || !(sending || msgs.some((m) => m.role === 'user'))) return;
  introFolded.add(key);
  Greetings.rememberIntroduction(a.id, role);
  document.querySelector('.chat .rc-greet-chat[open]')?.removeAttribute('open');
}
// Sending is the moment: the reply may take a while, the introduction steps aside at once.
document.addEventListener(
  'submit',
  (e) => {
    const a = current();
    if (a && ui.chatRole && e.target instanceof HTMLFormElement && e.target.dataset.form === 'chat')
      foldIntroduction(a, ui.chatRole, [], true);
  },
  true,
);
function railChat(a, role) {
  const msgs = a.conversations[role] || [];
  foldIntroduction(a, role, msgs);
  const t = routeTask(a);
  const x = t && ui.obj && ui.obj.type === 'work' ? artifact() : null;
  const typing = typingRole(a) === role;
  const s = sessionOf(a);
  const native = s?.protocol === 2;
  const question = native
    ? (L.v4Host(a)?.draft('roles', `question:${ROLE_ID[role]}`) ??
      s.inputs.messages[ROLE_ID[role]] ??
      '')
    : s?.inputs.messages[ROLE_ID[role]] || '';
  const failed = s?.failedTurn && ROLE_OF[s.failedTurn.body.role_id] === role;
  const quote = ui.chatQuotes[quoteKey(a, role)];
  // What travels with the next message sits on the composer as a card you can take off again.
  const attached = (quote
    ? `<div class="chat-quote" data-quote="${esc(quote)}">${icon('flask', 'i-sm chat-quote-i')}<span class="chat-quote-body"><span class="chat-quote-label">${T('测试记录 · 随这条消息发出', 'Test run · sent with your message')}</span><span class="chat-quote-text">${esc(quote)}</span></span><button type="button" class="btn icon quiet small" data-action="drop-quote" aria-label="${esc(T('移除这段引用', 'Remove this quote'))}">${icon('x', 'i-xs')}</button></div>`
    : '') + prdChip(a, role) + detailChip(a, role);
  const tools = `${a.tests.length ? `<button type="button" class="composer-tool${quote ? ' on' : ''}" data-action="prefill-run" aria-label="${esc(T('附上最近一次测试', 'Attach the latest test run'))}" title="${esc(T('附上最近一次测试', 'Attach the latest test run'))}">${icon('flask', 'i-sm')}</button>` : ''}${x ? `<button type="button" class="composer-tool" data-action="prefill-artifact" aria-label="${esc(T('分享这份作品', 'Share this work'))}" title="${esc(T('分享这份作品', 'Share this work'))}">${icon('doc', 'i-sm')}</button>` : ''}`;
  return `<div class="chat who-${role}" ${native ? 'data-v4-region="roles"' : ''}>
    <header class="chat-head">${btn(icon('back'), 'rail', 'icon quiet small', `data-rail="team" aria-label="${esc(T('返回团队', 'Back to team'))}"`)}${avatar(role, 'md', { typing })}<div class="grow"><p class="chat-name">${PEOPLE[role].name}</p><p class="chat-knows">${esc(`${ROLE_TITLE(role)} · ${KNOWS(role)}`)}</p></div></header>
    ${prdSees(a, role)}
    <div data-chat-greeting>${Greetings.hasArrived(a.id, role) ? Greetings.introductionHtml(a.id, hatHere(a) === 'engineer' ? 'engineer' : 'pm', role, locale(), true, canWrite(a)) : ''}</div>
    <div class="thread" data-role-id="${ROLE_ID[role]}" role="log" aria-live="polite">${native ? '' : `${msgs.length ? messageRows(msgs).map(({ message, key }) => msgHtml(a, message, key)).join('') : `<div class="chat-empty">${avatar(role, 'xl')}<p>${esc(OPENER(role))}</p></div>`}${typing ? `<div class="msg them is-typing" aria-label="${esc(T(`${PEOPLE[role].name}正在输入`, `${PEOPLE[role].subject} is typing`))}"><span class="typing"><i></i><i></i><i></i></span></div>` : ''}${failed ? `<div class="msg-fail">${icon('warn', 'i-sm')}<span class="grow">${T('上一条没有得到回复。', 'Your last message got no reply.')}</span>${btn(T('再发一次', 'Send again'), 'resend-turn', 'small quiet')}</div>` : ''}`}</div>
    ${mentorCard(a, role)}
    ${t ? `<div class="chat-context"><span class="ctx" title="${esc(T('这条对话会记在这件事下', 'This conversation is filed under this task'))}">${icon('note', 'i-xs')}<span>${esc(taskTitle(t))}</span></span></div>` : ''}
    <form class="composer" data-form="chat">${attached}<div class="composer-line">${tools ? `<span class="composer-tools">${tools}</span>` : ''}<label class="sr-only" for="chat-input">${esc(T(`给 ${PEOPLE[role].name} 的消息`, `Message to ${PEOPLE[role].ref}`))}</label><textarea id="chat-input" name="text" rows="1" maxlength="4000" required enterkeyhint="send" aria-describedby="chat-hint" placeholder="${esc(quote ? T('你想就这次测试确认什么？', 'What do you want to check about this test?') : T(`写给 ${PEOPLE[role].name}…`, `Message ${PEOPLE[role].ref}…`))}">${esc(question)}</textarea><button type="submit" class="btn icon primary send" aria-label="${esc(T('发送', 'Send'))}" ${canWrite(a) ? '' : 'disabled'}>${icon('send')}</button></div></form>
    <p class="composer-hint" id="chat-hint">${T('回车发送 · Shift+回车换行', 'Enter to send · Shift+Enter for a new line')}</p>
  </div>`;
}
// The server's local provider answers with a fact list, not a reply. Label it so nobody mistakes it for the colleague.
const LOCAL_REPLY = /^本地事实模式[:：]\s*/;
function msgHtml(a, m, messageId) {
  const mine = m.role === 'user';
  const local = !mine && LOCAL_REPLY.test(m.text);
  const text = local
    ? m.text
        .replace(LOCAL_REPLY, '')
        .split(/[；;]\s*/)
        .filter(Boolean)
        .map((s) => '- ' + s)
        .join('\n')
    : m.text;
  const t = (a.turnTimes || {})[m.traceId];
  const time = m.createdAt || (t ? (mine ? t.asked : t.answered) : '');
  const tk = m.context?.task_id ?? (a.turnTask || {})[m.traceId];
  const task = tk && a.tasks.find((x) => x.id === tk);
  const tag =
    (mine ? '' : zhTag(m.text)) +
    (local
      ? `<span class="msg-local" title="${esc(T('后端以本地模式运行，没有接模型：这里列出的是这位同事掌握的事实，并没有读你的问题。', 'The server runs in local mode with no model: this lists facts the colleague holds and does not read your question.'))}">${T('本地模式', 'Local mode')}</span>`
      : '');
  return `<div ${mine ? '' : `data-message-id="${esc(messageId)}"`} class="msg ${mine ? 'me' : 'them'}${local ? ' local' : ''}"><div class="bubble"${zhAttr(m.text)}>${mine ? esc(text) : md(text)}</div>${time || tag || (mine && tk) ? `<span class="msg-foot">${tag}${mine && tk ? (task ? `<button type="button" class="msg-task" data-action="open-task" data-id="${task.id}">${icon('note', 'i-xs')}${esc(taskTitle(task))}</button>` : `<span class="msg-task" title="${esc(tk)}">${esc(T('关联事项：', 'Linked task: ') + Array.from(String(tk)).slice(0, 8).join('') + (Array.from(String(tk)).length > 8 ? '…' : ''))}</span>`) : ''}${time ? `<time title="${esc(time)}">${when(time)}</time>` : ''}</span>` : ''}</div>`;
}
// The rail no longer carries the result (it lives on the result page, the main screen). Until
// the board line drops this tab, it holds one line and the way there.
function railFeedback(a) {
  return `<div class="rail-pad"><p class="feed-empty">${statusOf(a) === 'submitted' ? T('结果在结果页。', 'The result is on the result page.') : T('交付以后，结果会在主屏打开。', 'After you submit, the result opens on the main screen.')}</p>${statusOf(a) === 'submitted' ? btn(T('看结果', 'See the result'), 'to-review', 'small') : ''}</div>`;
}
function fbItem(a, i, full = false) {
  const candidate =
    (i.refs || []).find((r) => r.type === 'test')?.id ||
    (i.actions || []).find((x) => x.act === 'rerun')?.id;
  const investigationRun = candidate && a.tests.some((r) => r.id === candidate) ? candidate : null;
  const tone =
    i.kind === 'contribution'
      ? 'star'
      : i.kind === 'order'
        ? 'branch'
        : { good: 'good', check: 'warn', unknown: 'question' }[i.tone];
  const key = (i.kind || i.tone) + '|' + i.title;
  const disputes = (a.disputes || []).filter((d) => d.key === key);
  const task = i.taskId && a.tasks.find((t) => t.id === i.taskId);
  return `<li class="fb ${i.tone} ${i.kind || ''}"><div class="fb-icon">${icon(tone)}</div><div class="fb-body">
    <h4>${esc(i.title)}</h4>
    <p><span class="fb-label-k">${T('看到', 'Seen')}</span>${esc(i.observed)}</p>
    ${i.basis ? `<p><span class="fb-label-k">${T('当时可知', 'Knowable then')}</span>${esc(i.basis)}</p>` : ''}
    <p><span class="fb-label-k">${T('为什么重要', 'Why it matters')}</span>${esc(i.why)}</p>
    ${i.actions.length ? `<div class="fb-actions">${i.actions.map((x) => `<button type="button" class="link" data-action="fb-act" data-act="${x.act}" data-id="${esc(x.id || '')}" data-role="${x.role || ''}" data-task="${i.taskId || ''}">${esc(x.label)}</button>`).join('')}</div>` : ''}
    ${investigationRun ? `<div class="fb-actions"><button type="button" class="link" data-action="investigate-run" data-id="${esc(investigationRun)}">${icon('layers', 'i-xs')}${T('一起看证据', 'Inspect the evidence')}</button></div>` : ''}
    ${full && task ? `<button type="button" class="fb-task" data-action="open-task" data-id="${task.id}">${icon('note', 'i-xs')}${esc(taskTitle(task))}</button>` : ''}
    <div class="fb-dispute">${ui.disputeOpen === key ? `<form class="dispute" data-form="dispute" data-key="${esc(key)}"><label class="sr-only" for="dispute-text">${T('你的不同看法', 'Your view')}</label><textarea id="dispute-text" class="textarea" name="text" rows="2" required maxlength="2000" placeholder="${esc(T('哪里不对？', 'What is wrong with it?'))}"></textarea><div class="row-actions"><button type="submit" class="btn small primary">${T('记下', 'Save')}</button>${btn(T('取消', 'Cancel'), 'dispute', 'small quiet', `data-key="${esc(key)}"`)}</div></form>` : `<button type="button" class="link quiet" data-action="dispute" data-key="${esc(key)}">${T('我有不同看法', 'I see it differently')}</button>`}${disputes.map((d) => `<p class="dispute-note">${icon('bubble', 'i-xs')}<span${zhAttr(d.text)}>${esc(d.text)}</span></p>`).join('')}</div>
  </div></li>`;
}
const issuedViews = new WeakMap();
const connectionKeeper = createConnectionKeeper(() => refreshAgentIssued());
function refreshAgentIssued() {
  syncAgentFeed();
  const a = current();
  // The token is offered only while its practice is on screen; leaving or switching withdraws it.
  const onPractice =
    a &&
    L.nativeWorkspace(a) &&
    (WS.includes(ui.route) || ui.route === 'review' || ENGINEER_ROUTES.includes(ui.route));
  connectionKeeper.track(onPractice ? L.v4Host(a) : null);
  const target = document.querySelector('[data-agent-issued]');
  if (!a || !target) return;
  const identity = JSON.stringify([a.id, locale(), L.v4Host(a)?.issuedDelegation()]);
  if (issuedViews.get(target) === identity) return;
  issuedViews.set(target, identity);
  renderAgentConnection(target, L.nativeWorkspace(a) ? L.v4Host(a) : null, {
    origin: location.origin,
    notify,
    download,
    refresh: refreshAgentIssued,
  });
}
// The agent has its own page (#/agent); the rail only points there until its tab goes.
function railAgent() {
  return `<div class="rail-pad agent-panel"><section class="agent-conn"><div class="conn-row">${agentMark('md')}<div class="grow"><p class="agent-name">${T('我的 Agent', 'My agent')}</p><p class="meta">${T('连接、传输和交回的作品都在它自己的页面。', 'Connecting, transmission and returned work live on its own page.')}</p></div></div><div class="row-actions">${btn(T('打开我的 Agent', 'Open My agent'), 'open-agent', 'small')}</div></section></div>`;
}
// "No MCP? Hand over a package": the manual way, kept at the foot of the My agent page.
function agentPackageHtml(a) {
  const t = routeTask(a);
  const sc = ui.exportScope;
  const read = readSet(a);
  read.add('brief');
  const scopeWorks = (t ? works(a).filter((w) => w.taskId === t.id) : works(a)).length;
  return `<details class="ag-fallback"><summary>${icon('chev', 'i-sm')}<span><b>${T('没有 MCP？', 'No MCP?')}</b> ${T('交给它一个任务包', 'Hand over a package')}</span></summary><div class="ag-fallback-body agent-panel">
    <section class="agent-step"><h3><span class="step-n">1</span>${T('交出去', 'Hand over')}</h3><p class="agent-test-hint">${T('复制或下载任务包，交给任何 Agent。', 'Copy or download the package and give it to any agent.')}</p>
      <div class="checks">
        <label class="check"><input type="checkbox" checked disabled><span>${t ? esc(T('这件事：' + taskTitle(t), 'This task: ' + taskTitle(t))) : T('整件工作', 'The whole job')}</span></label>
        <label class="check"><input type="checkbox" data-scope="artifacts" ${sc.artifacts ? 'checked' : ''}><span>${T('作品', 'Work')}</span><small>${scopeWorks}</small></label>
        <label class="check"><input type="checkbox" data-scope="materials" ${sc.materials ? 'checked' : ''}><span>${T('读过的资料', 'Documents you read')}</span><small>${read.size}</small></label>
        <label class="check"><input type="checkbox" data-scope="tests" ${sc.tests ? 'checked' : ''}><span>${T('测试记录', 'Test runs')}</span><small>${a.tests.length}</small></label>
      </div>
      <div class="row-actions">${btn(icon('copy', 'i-sm') + T('复制任务包', 'Copy package'), 'copy-package', 'small')}${btn(icon('download', 'i-sm') + T('下载', 'Download'), 'download-package', 'small quiet')}</div>
    </section>
    <section class="agent-step"><h3><span class="step-n">2</span>${T('带回来', 'Bring back')}</h3>
      <form data-form="import" id="import-form" class="stack">
        <label class="sr-only" for="import-content">${T('粘贴 Agent 的产出', 'Paste your agent’s output')}</label>
        <textarea class="textarea" name="content" id="import-content" rows="3" required ${canWrite(a) ? '' : 'disabled'} placeholder="${esc(T('粘贴 Agent 的文字、测试计划或调查…', 'Paste your agent’s writing, test plan or investigation…'))}">${esc(importDraft(a))}</textarea>${canWrite(a) ? '' : `<p class="meta">${T('这次练习已交付或只读，不能带回新作品；开始修订或新练习后再导入。', 'This practice is submitted or read-only. Start a revision or a new practice to bring work back.')}</p>`}
        <div class="row-actions"><label class="file-pick">${icon('upload', 'i-sm')}<span>${T('选择文件', 'Choose a file')}</span><input type="file" id="import-file" accept=".md,.txt,.json,text/plain,application/json" ${canWrite(a) ? '' : 'disabled'}></label><span class="spacer"></span><button type="submit" class="btn small primary" ${canWrite(a) ? '' : 'disabled'}>${T('预览', 'Preview return')}</button></div>
      </form>
    </section>
  </div></details>`;
}
function agentLog(a, taskId) {
  const out = [];
  (a.exports || [])
    .filter((x) => !taskId || x.taskId === taskId)
    .forEach((x) => {
      const tk = a.tasks.find((t) => t.id === x.taskId);
      out.push({
        at: x.createdAt,
        icon: icon('upload', 'i-sm'),
        text: T('交出任务包', 'Handed over a package'),
        sub:
          (tk ? taskTitle(tk) + ' · ' : '') +
          T(
            (x.inputVersions || []).length + ' 份作品',
            (x.inputVersions || []).length + ' work item(s)',
          ),
      });
    });
  a.artifacts
    .filter((w) => w.source !== 'user' && (!taskId || w.taskId === taskId))
    .forEach((w) => {
      out.push({
        at: w.createdAt,
        icon: icon('download', 'i-sm'),
        text: T('带回《' + w.title + '》', 'Returned “' + w.title + '”'),
        sub: w.removedAt
          ? T('已移除，可恢复', 'Removed; can be restored')
          : w.adopted
            ? T('已采用', 'Adopted')
            : T('待你检查', 'Waiting for your check'),
      });
      if (w.adoptedAt)
        out.push({
          at: w.adoptedAt,
          icon: icon('check', 'i-sm'),
          text: T('你采用了《' + w.title + '》', 'You adopted “' + w.title + '”'),
          sub: E.agentProgress(a, w)?.linked
            ? T('已关联测试', 'Linked to a test')
            : T('还没关联测试', 'Not linked to a test yet'),
        });
    });
  return out.sort((x, y) => String(y.at).localeCompare(String(x.at)));
}
// Everything that happened, in plain words: the world, your work, your agent, your talks.
function activity(a, taskId) {
  const out = [];
  const times = a.eventTimes || {};
  a.events.forEach((e, i) => {
    if (e.server) {
      if (['save_artifact', 'pause', 'resume'].includes(e.type)) return;
      const l = eventLine(a, e, workLang(a));
      if (taskId && !l.world && l.taskId !== taskId) return;
      out.push({
        at: e.createdAt || times[e.seq] || '',
        order: i,
        icon: l.icon || 'info',
        tone: l.tone || (l.world ? 'world' : ''),
        text: l.text,
        open: l.open || null,
      });
      return;
    }
    const d = e.detail || {};
    const work = d.artifactId && a.artifacts.find((x) => x.id === d.artifactId);
    const tk =
      (d.taskId && a.tasks.find((t) => t.id === d.taskId)) ||
      (work && a.tasks.find((t) => t.id === work.taskId));
    if (taskId && (!tk || tk.id !== taskId)) return;
    const text =
      e.type === 'task_added' && tk
        ? T('新增事项「' + taskTitle(tk) + '」', 'Added the task “' + taskTitle(tk) + '”')
        : e.type === 'artifact_created' && work && work.source === 'user'
          ? T('开始写《' + shown(work).title + '》', 'Started “' + shown(work).title + '”')
          : e.type === 'artifact_removed' && work
            ? T(
                '移除《' + work.title + '》，可恢复',
                'Removed “' + work.title + '”; can be restored',
              )
            : e.type === 'artifact_restored' && work
              ? T('恢复《' + work.title + '》', 'Restored “' + work.title + '”')
              : e.type === 'artifact_saved' && work
                ? T(
                    '《' + shown(work).title + '》存为 v' + d.revision,
                    'Saved “' + shown(work).title + '” as v' + d.revision,
                  )
                : e.type === 'task_updated' && tk && d.changes && d.changes.status
                  ? T(
                      '「' + taskTitle(tk) + '」改为' + STATUS(d.changes.status),
                      '“' + taskTitle(tk) + '” is now ' + STATUS(d.changes.status),
                    )
                  : e.type === 'priority_adopted'
                    ? T('采用了同事的排序建议', 'Took a colleague’s priority advice')
                    : e.type === 'feedback_disputed'
                      ? T('对一条反馈提出了不同看法', 'Disputed a piece of feedback')
                      : e.type === 'review_requested'
                        ? T('请求评审', 'Requested a review')
                        : '';
    if (text)
      out.push({
        at: e.createdAt || '',
        order: i,
        icon: e.type.startsWith('artifact') ? 'note' : 'info',
        text,
        open: work
          ? { action: 'open-artifact', id: work.id }
          : tk
            ? { action: 'open-task', id: tk.id }
            : null,
      });
  });
  Object.entries(a.turnTimes || {}).forEach(([trace, t]) => {
    if (!t || !t.answered) return;
    const tk = (a.turnTask || {})[trace];
    if (taskId && tk !== taskId) return;
    const role = ROLES.find((r) => (a.conversations[r] || []).some((m) => m.traceId === trace));
    if (!role) return;
    out.push({
      at: t.answered,
      order: 1e9,
      icon: 'bubble',
      text: T(`${PEOPLE[role].name} 回复了你`, `${PEOPLE[role].subject} replied`),
      open: { action: 'chat', role },
    });
  });
  agentLog(a, taskId).forEach((e) =>
    out.push({
      at: e.at,
      order: 1e9,
      icon: 'spark',
      text: T('我的 Agent：', 'My agent: ') + e.text,
      open: { action: 'rail-tab', tab: 'agent' },
    }),
  );
  (ui.notesCache || [])
    .filter((n) => !taskId || n.taskId === taskId)
    .forEach((n) =>
      out.push({
        at: n.at,
        order: 1e9,
        icon: 'bubble',
        tone: 'note',
        text:
          T(PEOPLE[n.role].name + '（规则提醒）：', PEOPLE[n.role].subject + ' (rule reminder): ') +
          n.text,
        open: { action: 'chat', role: n.role },
      }),
    );
  return out
    .sort((x, y) =>
      x.at && y.at ? x.at.localeCompare(y.at) : x.at ? 1 : y.at ? -1 : x.order - y.order,
    )
    .reverse();
}
// The record drawer, from the topbar's ⏱: what was the Activity tab, as a sheet over the rail.
function recordsDrawer() {
  return islandSlot('board-records');
}
function keepRecords(a) {
  keepIsland(
    'board-records',
    Board.RecordsSheet,
    {
      open: Board.recordsShown(),
      title: T('记录', 'Record'),
      close: T('关闭记录', 'Close the record'),
      body: Board.recordsShown()
        ? Board.recordsBody(
            activity(a, null)
              .slice(0, 80)
              .map((e) => ({ ...e, zh: locale() === 'en' && isChinese(e.text) })),
          )
        : '',
      onClose: Board.closeRecords,
    },
    { persist: true },
  );
}
// The document over the board: the layer covers the desk column; the sheet is an island in it.
function docLayer() {
  return `<div class="mat-layer" data-mat-layer>${islandSlot('board-doc')}</div>`;
}
function docSheetData(a) {
  const id = ui.docSheet;
  const m = id && E.getMaterials(a).find((x) => x.id === id);
  if (!m) return null;
  const prev = ui.previous[m.id];
  const hasPrev = prev && prev.version < m.version;
  const zhOnly = locale() === 'en' && isChinese(m.content);
  const owner = whoHas(m)[0] || Board.docOwner(m.id);
  const showV1 = ui.compare && hasPrev;
  const meta = `<span>v${m.version}</span>${m.id === 'policy' ? `<span class="${a.world.indexVersion < m.version ? 'warn' : ''}">${T(`知识助手索引 v${a.world.indexVersion}`, `Assistant index v${a.world.indexVersion}`)}</span>` : ''}${zhOnly ? '<span class="lang-tag">Chinese source</span>' : ''}${hasPrev && !showV1 && Board.wordingChanged(prev.content, m.content) ? `<span class="mat-reworded">${T('措辞也有改动', 'Wording changed too')}</span>` : ''}${hasPrev ? `<button type="button" class="mat-compare" role="switch" aria-checked="${!!showV1}" data-action="toggle-compare"><span class="track" aria-hidden="true"></span>${T(`对照 v${prev.version}`, `Compare with v${prev.version}`)}</button>` : ''}`;
  const lang = zhOnly ? ' lang="zh-CN"' : '';
  const body = showV1
    ? `<p class="mat-was">${T(`v${prev.version} 原文，已被 v${m.version} 取代`, `v${prev.version} as it was, replaced by v${m.version}`)}</p><div class="prose serif"${lang}>${md(prev.content, { dropTitle: true })}</div>`
    : !String(m.content || '').trim()
      ? `<div class="mat-loading" role="status" aria-label="${esc(T('正在取资料', 'Loading the document'))}"><i></i><i></i><i></i><i></i><i></i><i></i></div>`
      : `<div class="prose serif"${lang}>${hasPrev ? Board.markChangedFigures(md(m.content, { dropTitle: true }), prev.content, m.content) : md(m.content, { dropTitle: true })}</div>`;
  const foot = `${btn(icon('quote', 'i-sm') + T('引用到作品', 'Cite in my work'), 'cite-material', 'small', `data-id="${esc(m.id)}"`)}${owner ? btn(avatar(owner, 'xs') + T(`问${PEOPLE[owner].name}这份资料`, `Ask ${PEOPLE[owner].ref} about this`), 'discuss-material', 'small quiet', `data-id="${esc(m.id)}" data-role="${owner}"`) : ''}`;
  return { id: m.id, title: materialTitle(m), titleLang: zhOnly ? 'zh-CN' : undefined, meta, body, foot };
}
function keepDocSheet(a) {
  keepIsland('board-doc', Board.DocSheet, {
    sheet: a ? docSheetData(a) : null,
    container: document.querySelector('[data-mat-layer]'),
    labels: {
      close: T('关闭资料', 'Close the document'),
      dim: T('关闭资料，回到工作板', 'Close the document and return to the board'),
    },
    onClose: Board.closeDoc,
  });
}

/* ---------- 4. review ---------- */
// The result page (#/review) is drawn in the workspace's main screen (registered below): the
// topbar and the people stay, the main screen holds the stamped result and its detail, then the
// optional practice. References open as a sheet over the main screen; recognition counts live
// in #/lab, not here.
function renderReview() {
  if (current() && L.nativeWorkspace(current())) {
    const a = current();
    return `<div class="result-desk">
        <h1 class="sr-only">${T('结果', 'Result')}</h1>
        <div class="result-main" data-v4-feedback data-v4-region="feedback" data-result-layout="true"></div>
        <section class="result-after" aria-label="${esc(T('接下来', 'What next'))}">
          ${behaviorSection(a)}
          ${practiceOriginNote(a)}
          <section class="review-practice" data-v4-practice aria-live="polite">
            ${practiceSection(a)}
          </section>
        </section>
      </div>`;
  }
  const a = current();
  const s = sessionOf(a);
  const fb = s?.feedback;
  const submission = s ? L.store.submissionId(s) : '';
  const pending = s?.pending && (s.pending.job?.kind ?? s.pending.kind) === 'feedback';
  const head = '';
  if (!submission)
    return `<div class="page review"><div class="empty big"><h1 class="title-l">${T('交付之后，评审会出现在这里', 'The review appears here after you submit')}</h1>${btn(T('回到工作台', 'Back to the workspace'), 'to-work', 'primary')}</div></div>`;
  const items = fb ? fb.items : [];
  const groups = [
    ['NOT_MET', T('需要补上', 'Needs work'), 'warn'],
    ['open', T('证据不足或需要核验', 'Not enough evidence, or needs checking'), 'question'],
    ['MET', T('已经站住', 'Holds up'), 'good'],
    ['NOT_APPLICABLE', T('不适用', 'Not applicable'), 'minus'],
  ];
  const bucket = (i) =>
    i.label === 'NOT_MET'
      ? 'NOT_MET'
      : i.label === 'MET' && !i.review_required
        ? 'MET'
        : i.label === 'NOT_APPLICABLE'
          ? 'NOT_APPLICABLE'
          : 'open';
  const counts = Object.fromEntries(
    groups.map(([k]) => [k, items.filter((i) => bucket(i) === k).length]),
  );
  const art = s.artifact;
  const content = art ? art.content : s.draft;
  // The server attaches the same evidence to every criterion; show the shared set once.
  const common = items.length
    ? items
        .map((i) => new Set(i.evidence_ids || []))
        .reduce((x, y) => new Set([...x].filter((v) => y.has(v))))
    : new Set();
  const firstCrit = items[0] ? items[0].criterion_id : '';
  ui.reviewCommon = common;
  return `${head}
    <div class="page review">
      <header class="review-hero">
        <div class="review-title"><p class="meta"${langOf(a)}>${esc(caseOf(a).title)}</p><h1 class="title-xl">${T('上线评审', 'Launch review')}</h1>
          <p class="review-stamp">${icon('stamp', 'i-sm')}${T('已固定交付', 'Submitted')}${art ? `<span>${T('交付稿 v' + art.version, 'Deliverable v' + art.version)}</span><span>${T('配置 v' + art.config_version, 'Config v' + art.config_version)}</span>` : ''}${fb ? `<span>${T('截至事件 #' + fb.as_of_seq, 'As of event #' + fb.as_of_seq)}</span>` : ''}</p></div>
        <div class="review-conds"><p class="meta">${T('交付时的条件', 'Conditions at submission')}</p>${conditions(a, 'compact')}</div>
      </header>
      <nav class="review-tabs segmented" role="group" aria-label="${esc(T('评审内容', 'Review content'))}"><span class="thumb"></span><button type="button" aria-pressed="${ui.reviewTab !== 'coach'}" data-action="review-tab" data-tab="rules">${T('上线检查（后端规则）', 'Launch checks (server rules)')}</button><button type="button" aria-pressed="${ui.reviewTab === 'coach'}" data-action="review-tab" data-tab="coach">${T('情境反馈（当时可知）', 'In context (what was knowable)')}</button></nav>
      ${fb?.overflow && ui.reviewTab !== 'coach' ? `<p class="warn-line" data-feedback-overflow>${icon('warn', 'i-sm')}${T('证据超过长度上限，部分条目未评。', 'The evidence exceeds the length limit; some items were not reviewed.')}${btn(T('查看交付面板的作品选择', 'View work selection in the deliverable'), 'review-works', 'small quiet')}</p>` : ''}
      ${
        fb && ui.reviewTab !== 'coach'
          ? `<div class="tally" role="img" aria-label="${esc(
              groups
                .filter(([k]) => counts[k])
                .map(([k, l]) => l + ' ' + counts[k])
                .join(T('，', ', ')),
            )}">${groups
              .filter(([k]) => counts[k])
              .map(
                ([k, l, ic]) =>
                  `<span class="tally-seg ${k}" style="flex:${counts[k]}"><span class="tally-label">${icon(ic, 'i-xs')}${counts[k]}</span></span>`,
              )
              .join('')}</div>`
          : ''
      }
      ${fb && common.size && ui.reviewTab !== 'coach' ? `<div class="shared-evidence"><span class="meta">${T('评审读取的记录', 'Records the review read')}</span>${[...common].map((id) => `<button type="button" class="chip" data-action="live-evidence" data-criterion="${esc(firstCrit)}" data-id="${esc(id)}">${icon(evidenceIcon(fb, id), 'i-xs')}<span>${esc(evidenceLabel(a, fb, id))}</span></button>`).join('')}</div>` : ''}
      <div class="review-grid">
        <div class="review-main">
          ${pending || (!fb && !s.feedbackFailure) ? `<div class="review-wait">${pending ? `<span class="spinner"></span><p>${T('评审正在生成…', 'The review is being written…')}</p>` : `<p>${T('交付已固定，评审还没生成。', 'Submitted; the review has not been generated yet.')}</p>${btn(T('生成评审', 'Generate the review'), 'live-feedback', 'primary', canWrite(a) || s.world.status === 'submitted' ? '' : 'disabled')}`}</div>` : ''}
          ${s.feedbackFailure && !pending ? `<div class="review-wait bad">${icon('warn', 'i-sm')}<p>${esc(T('评审任务失败：', 'The review job failed: ') + (s.feedbackFailure.error || ''))}</p>${s.feedbackFailure.kind === 'feedback' ? btn(T('重新生成', 'Regenerate'), 'live-feedback', 'primary', 'data-retry="true"') : `<p>${T('当前服务不支持重新生成失败的评审。', 'This server cannot regenerate failed reviews.')}</p>`}</div>` : ''}
          ${ui.reviewTab === 'coach' ? coachSection(a) : ''}
          ${
            ui.reviewTab !== 'coach' && fb
              ? groups
                  .map(([k, l, ic]) => {
                    const list = items.filter((i) => bucket(i) === k);
                    return list.length
                      ? `<section class="review-group ${k}"><h2 class="group-title">${icon(ic, 'i-sm')}${l}<span class="count">${list.length}</span></h2><ol class="criteria">${mergeSame(
                          list,
                        )
                          .map((g) => criterionItem(a, fb, g, common))
                          .join('')}</ol></section>`
                      : '';
                  })
                  .join('')
              : ''
          }
          ${ui.reviewTab !== 'coach' && fb && fb.practice && fb.practice.length ? `<section class="review-group"><h2 class="group-title">${icon('branch', 'i-sm')}${T('建议补练', 'Suggested practice')}</h2><ul class="practice-list">${fb.practice.map((p) => `<li${zhAttr(p)}>${esc(p)}</li>`).join('')}</ul></section>` : ''}
          ${ui.reviewTab !== 'coach' && fb ? `<p class="review-foot">${icon('info', 'i-xs')}${esc(T(`规则检查 ${fb.model_revision}：不是最终评分；标为“需要核验”的项要由人确认。`, `Rule check ${fb.model_revision}: not a final grade. Items marked “needs checking” need a person to confirm.`))}</p>` : ''}
        </div>
        <aside class="review-side">
          <article class="paper deliverable">${stampMark(a)}<h2 class="paper-title">${T('你交付的内容', 'What you submitted')}</h2>${FIELDS.map((k) => `<section class="field-doc"><h3>${FIELD(k)}</h3>${content && content[k] ? `<div class="prose serif"${zhAttr(content[k])}>${md(content[k])}</div>` : `<p class="muted">${T('（空）', '(empty)')}</p>`}</section>`).join('')}</article>
          <section class="next"><h2 class="group-title">${T('接下来', 'Next')}</h2>
            ${['pilot', 'urgent', 'capacity']
              .filter((id) => id !== a.scenarioId && caseShown(id))
              .map(
                (id) =>
                  `<button type="button" class="next-row" data-action="practice-variant" data-case="${id}">${icon('bolt', 'i-sm row-icon')}<span class="grow"><span class="row-title">${esc(CASE(id).title)}</span><span class="row-sub">${esc(CASE(id).change || T('回到主情境', 'Back to the main situation'))}</span></span>${icon('chev', 'i-sm')}</button>`,
              )
              .join('')}
            ${caseShown(a.scenarioId) ? `<button type="button" class="next-row" data-action="practice-variant" data-case="${esc(a.scenarioId)}">${icon('refresh', 'i-sm row-icon')}<span class="grow"><span class="row-title">${T('同一情境再来一次', 'Try the same situation again')}</span><span class="row-sub">${T('新的练习，这次的记录保留', 'A fresh attempt; this one stays as it is')}</span></span>${icon('chev', 'i-sm')}</button>` : ''}
          </section>
        </aside>
      </div>
    </div>`;
}
// Optional practice after feedback (W05 rules, reviewed situations only). Nothing here is required or scored.
function practiceSection(a) {
  const v = ui.practice[a.id];
  if (!v) {
    queueMicrotask(() => loadPractice(a));
    return `<h2 class="group-title">${icon('branch', 'i-sm')}${practiceHeading()}</h2><p class="meta">${T('正在查看这轮反馈有没有可选的补练…', 'Checking whether this feedback suggests an optional practice…')}</p>`;
  }
  const head = `<h2 class="group-title">${icon('branch', 'i-sm')}${practiceHeading()}</h2>`;
  // A sealed session will never get new feedback or practice: say so instead of "check again".
  const sealed = v.sealed === true || sealedSession(a);
  if (v.error || (sealed && v.state === 'feedback_pending')) {
    // Never show the failure code; a read-only session cannot start practice, so no retry.
    const readOnly = sealed;
    return `${head}<p class="warn-line" data-practice-unavailable="${readOnly ? 'read-only' : 'retry'}">${icon('warn', 'i-sm')}${esc(practiceUnavailableText(readOnly, locale()))}</p>${readOnly ? '' : btn(T('重新查看', 'Check again'), 'practice-reload', 'small quiet')}`;
  }
  if (v.state === 'no_submission')
    return `${head}<p class="meta">${T('交付并生成反馈后，这里会列出可选的补练。', 'After you submit and the feedback is ready, optional practice appears here.')}</p>`;
  if (v.state === 'feedback_pending')
    return `${head}<p class="meta">${T('反馈生成后，这里会列出可选的补练。', 'Optional practice appears here once the feedback is ready.')}</p>${btn(T('重新查看', 'Check again'), 'practice-reload', 'small quiet')}`;
  if (v.state !== 'ready') return '';
  const busy = ui.practiceBusy ? 'disabled' : '';
  const titleOf = (id) =>
    [...(v.options || []), ...(v.catalog || [])].find((o) => o.id === id)?.title || id;
  const links = (v.links || [])
    .map((l) => {
      const target =
        l.target_session_id && state.attempts.find((x) => x.id === l.target_session_id);
      const label =
        l.choice === 'choose'
          ? T('按建议开始补练：', 'Started the suggested practice: ') + titleOf(l.option_id)
          : l.choice === 'choose_other'
            ? T('自选开始练习：', 'Started a practice you picked: ') + titleOf(l.option_id)
            : l.choice === 'decline'
              ? T('你选择了不补练', 'You chose not to practise')
              : T('你选择继续修订原作品', 'You chose to keep revising');
      return `<li class="practice-link"><span class="grow">${esc(label)}<span class="meta"> · ${esc(when(l.created_at))}</span></span>${target ? btn(T('打开', 'Open'), 'resume-attempt', 'small quiet', `data-id="${esc(target.id)}"`) : l.target_session_id ? `<span class="meta">${T('这台浏览器没有它的入口', 'Not available in this browser')}</span>` : ''}</li>`;
    })
    .join('');
  // What all suggestions revisit is said once; each card says only why it is worth practising.
  // A hidden situation (the IT domain) is never offered, even when the server lists it.
  const shownOptions = (v.options || []).filter(practiceOptionShown);
  const shownCatalog = (v.catalog || []).filter(practiceOptionShown);
  const suggested = practiceCards(
    shownOptions.map((o) => ({ ...o, work_language: practiceLanguage(o) })),
    shownCatalog,
    criterionLabels(locale()),
    practiceChange,
  );
  // One front-end sentence says what the suggestions share; the server's reasons are not repeated.
  // The honesty note (new feedback looks only at the new situation) sits behind ⓘ.
  const note = practiceNote(a, v);
  const options = suggested.cards.length
    ? `<p class="practice-shared">${esc(practiceSharedLine(suggested))}${note.button}</p>${note.body}${suggested.cards
        .map(
          (
            o,
          ) => `<article class="practice-option"><h3 class="row-title"${langAttr(o.language)}>${esc(o.title)}</h3><p class="meta">${esc(practiceCardLine(o))}</p>
    ${btn(icon('play', 'i-sm') + T('练这个', 'Practise this one'), 'practice-choose', 'small', `data-option="${esc(o.id)}" ${busy}`)}</article>`,
        )
        .join('')}`
    : '';
  const pending =
    a.practiceRequest && a.practiceRequest.submissionId === v.submissionId
      ? a.practiceRequest
      : null;
  const resume = pending
    ? `<p class="warn-line" role="status">${icon('warn', 'i-sm')}<span class="grow">${esc(T('上次的选择还没确认完成：', 'Your last choice is not confirmed yet: ') + (pending.optionId ? titleOf(pending.optionId) : pending.choice === 'decline' ? T('不补练', 'no practice') : T('继续修订', 'keep revising')))}</span>${btn(T('确认这次选择', 'Confirm this choice'), 'practice-resume', 'small', busy)}</p>`
    : '';
  const browse =
    ui.practiceBrowse === a.id
      ? `<div class="practice-browse"><p class="meta">${T('审核过的情境都可以自己选；会记下这是你自选的，并和这次反馈关联。', 'You can pick any reviewed situation. It is recorded as your own pick and linked to this feedback.')}</p>
    ${
      shownCatalog
        .map((o) => {
          const lang = practiceLanguage(o);
          const change = changeSentence(practiceChange(o.id, lang), lang);
          return `<article class="practice-option"><h3 class="row-title"${langAttr(lang)}>${esc(o.title)}${o.suggested ? `<span class="tag">${T('建议', 'Suggested')}</span>` : ''}</h3>${change ? `<p class="meta"${langAttr(lang)}>${esc(change)}</p>` : ''}
      ${btn(icon('play', 'i-sm') + T('练这个', 'Practise this one'), 'practice-choose-other', 'small', `data-option="${esc(o.id)}" ${busy}`)}</article>`;
        })
        .join('') ||
      `<p class="meta">${T('这个语言暂时没有可选的审核情境。', 'No reviewed situation is available in this language yet.')}</p>`
    }</div>`
      : '';
  return `${head}
    ${resume}
    ${options || `<p class="meta">${T('这轮反馈没有需要换情境再练的事项。', 'This feedback has nothing that calls for practice in another situation.')}${note.button}</p>${note.body}`}
    <div class="practice-actions">${btn(T('继续修订', 'Keep revising instead'), 'practice-continue', 'small quiet', busy)}${btn(T('暂不需要', 'Not now'), 'practice-decline', 'small quiet', busy)}${btn(ui.practiceBrowse === a.id ? T('收起情境', 'Hide situations') : T('自己选情境', 'Choose another situation'), 'practice-browse', 'small quiet', `aria-expanded="${ui.practiceBrowse === a.id}"`)}</div>
    ${browse}
    ${links ? `<ul class="practice-links">${links}</ul>` : ''}`;
}
const practiceHeading = () => T('换个情境再练', 'Practise in another situation');
// A suggested situation's work language, from its server record or the -zh/-en of its id.
const practiceLanguage = (o) =>
  o?.work_language === 'zh' || o?.work_language === 'en'
    ? o.work_language
    : (/-(zh|en)$/.exec(String(o?.id ?? '')) || [])[1] || null;
// The server's honesty note for the next feedback, one ⓘ away; empty without a note.
function practiceNote(a, v) {
  if (!v.note) return { button: '', body: '' };
  const open = ui.practiceNote === a.id;
  const label = T('之后的反馈看什么', 'What later feedback looks at');
  return {
    button: `<button type="button" class="practice-info" data-action="practice-note" aria-expanded="${open}" aria-controls="practice-note" aria-label="${esc(label)}" title="${esc(label)}">${icon('info', 'i-xs')}</button>`,
    body: `<p class="practice-note" id="practice-note"${langAttr(v.work_language)}${open ? '' : ' hidden'}>${esc(v.note)}</p>`,
  };
}
// Work saved without a task (for example, returned by an Agent over MCP) stays visible on the board.
// Work not filed under any task sits after the board, folded into one line.
function unfiledWorks(a) {
  const list = (a.artifacts || []).filter((w) => !w.taskId && !w.removedAt);
  if (!list.length) return '';
  return `<details class="work-sec unfiled-fold" data-flip="unfiled"><summary>${icon('chev', 'i-sm')}<span>${T('不在事项里的作品', 'Work outside any task')}</span><span class="sec-count">${list.length}</span></summary>
    <p class="sec-hint">${T('先查看确切版本，再决定是否采用', 'Check which version it is before you adopt it')}</p>
    <div class="unfiled-list">${list.map((w) => `<button type="button" class="next-row" data-action="preview-work" data-id="${esc(w.id)}">${icon(w.source === 'external-agent' ? 'spark' : 'note', 'i-sm row-icon')}<span class="grow"><span class="row-title">${esc(w.title || T('未命名', 'Untitled'))}</span><span class="row-sub">${esc(purposeLabel(w.purpose))} · ${workVersion(w.revision)} · ${w.adopted ? T('已采用', 'Adopted') : T('待你检查', 'Awaiting your check')}${w.source === 'external-agent' ? T(' · 来自我的 Agent', ' · from my Agent') : ''}</span></span>${icon('chev', 'i-sm')}</button>`).join('')}</div></details>`;
}
function previewWork(a, id) {
  const w = a.artifacts.find((x) => x.id === id && !x.removedAt);
  if (!w) return;
  const body =
    w.kind === 'test_set'
      ? `<ol class="practice-basis">${(w.cases || []).map((c) => `<li${zhAttr(c.question || '')}>${esc(c.question || '')}${c.expectation ? `<span class="meta"> — ${esc(c.expectation)}</span>` : ''}</li>`).join('')}</ol>`
      : w.kind === 'investigation'
        ? `<p class="prose">${esc(w.question || '')}</p><p class="meta">${T(`${(w.blocks || []).length} 个调查模块`, `${(w.blocks || []).length} investigation blocks`)}</p>`
        : `<div class="prose serif"${zhAttr(w.body || '')}>${md(w.body || '')}</div>`;
  const canAdopt = !w.adopted && w.source === 'external-agent' && statusOf(a) === 'active';
  openSheet(
    `${esc(w.title || T('未命名', 'Untitled'))} · ${workVersion(w.revision)}`,
    `<p class="meta">${esc(purposeLabel(w.purpose))} · ${w.adopted ? T('此版本已采用', 'This version is adopted') : T('此版本待你检查', 'This version awaits your check')}${w.source === 'external-agent' ? T(' · 来自我的 Agent', ' · from my Agent') : ''}</p>${body}${L.nativeWorkspace(a) ? nativeEvidenceRow(a, w, T('依据', 'Evidence')) : ''}`,
    `${btn(T('关闭', 'Close'), 'close', 'quiet')}${L.nativeWorkspace(a) && statusOf(a) === 'active' && savedWorkBasis(a, w) ? btn(T('核对本版', 'Check this version'), 'check-work', 'small', `data-id="${esc(w.id)}"`) : ''}${canAdopt ? btn(T('检查后采用这版', 'Adopt this version after checking'), 'adopt', 'primary', `data-id="${esc(w.id)}"`) : ''}`,
    'narrow',
  );
}
const practiceScenario = (optionId) => String(optionId).replace(/-(zh|en)$/, '');
const practiceOptionShown = (o) => caseShown(practiceScenario(o.id));
// The visible condition change of a reviewed variant, from the same case texts the practice list shows.
// It is world text, so it is told in that practice's work language.
function practiceChange(optionId, language = null) {
  const caseId = {
    pm_pilot_urgent: 'urgent',
    pm_pilot_capacity15: 'capacity',
    it_ticket_pilot: 'itticket',
  }[String(optionId).replace(/-(zh|en)$/, '')];
  return caseId ? CASE(caseId, language).change || '' : '';
}
function practiceOriginNote(a) {
  const o = a && a.practiceOrigin;
  if (!o) return '';
  const source = state.attempts.find((x) => x.id === o.sourceAttemptId);
  return `<p class="practice-origin">${icon('branch', 'i-sm')}<span class="grow">${esc((o.choice === 'choose_other' ? T('这是看过上一轮反馈后自选的练习：', 'Practice you picked after earlier feedback: ') : T('这是按上一轮反馈建议开始的补练：', 'Practice suggested by earlier feedback: ')) + (o.title || ''))}${o.criteria && o.criteria.length ? `<span class="meta"> · ${esc(o.criteria.map((c) => criterionLabels(locale())[c] || c).join(T('、', ', ')))}</span>` : ''}</span>${source ? btn(T('看原反馈', 'Original feedback'), 'review-attempt', 'small quiet', `data-id="${esc(source.id)}"`) : ''}</p>`;
}
/* recognition layer on the review page: a lens-only summary line with the way into the system
 * profile (#/lab), and the behaviour section; neither appears when the layer is off. */
const recognitionReads = new Map();
function recognitionHeroInner(a) {
  const read = ui.recognition?.[a?.id];
  if (!lensOn() || !read || read.enabled === false) return '';
  return `<p class="rc-summary">${esc(summaryText(read.counts, locale()))}</p><a class="rc-lab-link" href="#/lab">${T('系统剖面：看每一步识别的中间结果 →', 'System profile: see every recognition step →')}</a>`;
}
function behaviorInner(a) {
  return behaviorHtml(ui.behavior?.[a?.id], locale(), {
    lens: lensOn(),
    materialName: materialNameOf(a),
    stepsOpen: ui.behaviorStepsOpen.has(a?.id),
  });
}
function behaviorSection(a) {
  const html = behaviorInner(a);
  return `<section class="rc-behavior" data-rc-behavior aria-live="polite"${html ? '' : ' hidden'}>${html}</section>`;
}
function fillBehavior(box, a) {
  const html = behaviorInner(a);
  box.innerHTML = html;
  box.hidden = !html;
}
async function loadRecognitionSummary(a) {
  const last = recognitionReads.get(a.id) ?? 0;
  if (Date.now() - last < 3000) return;
  recognitionReads.set(a.id, Date.now());
  try {
    const read = await L.recognition(a);
    ui.recognition ||= {};
    ui.recognition[a.id] = { counts: read.counts, enabled: read.enabled !== false };
    const box = document.querySelector('[data-rc-hero]');
    if (box && current()?.id === a.id) box.innerHTML = recognitionHeroInner(a);
  } catch {
    // The summary is an annotation; a failed read leaves the page as it was.
  }
  try {
    const behavior = await L.behavior(a);
    ui.behavior ||= {};
    ui.behavior[a.id] = behavior;
    const box = document.querySelector('[data-rc-behavior]');
    if (box && current()?.id === a.id) fillBehavior(box, a);
  } catch {
    // Same: the behaviour section stays hidden when the read fails.
  }
}
const practiceReads = new Set();
const practicePoints = new Map();
const practiceDrops = new Map();
async function loadPractice(a, force = false) {
  if (!a || practiceReads.has(a.id) || (!force && ui.practice[a.id])) return;
  practiceReads.add(a.id);
  const before = JSON.stringify(ui.practice[a.id]);
  const point = JSON.stringify(L.v4Host(a)?.snapshot().asOf);
  if (!ui.practice[a.id]) ui.practice[a.id] = { state: 'loading' };
  let read;
  try {
    read = { view: await L.practice(a) };
  } catch (error) {
    read = { error };
  }
  // The code only says whether the session is sealed; wording is chosen at render time.
  const sealed = 'error' in read && (isSealedPracticeError(read.error?.code) || sealedSession(a));
  const next = afterPracticeRead(ui.practice[a.id], read, practiceDrops.get(a.id) ?? 0, sealed);
  ui.practice[a.id] = next.view;
  practiceDrops.set(a.id, next.dropsInARow);
  practiceReads.delete(a.id);
  // A dropped read is asked again on the next poll tick; otherwise wait for a new point.
  if (next.readAgain) practicePoints.delete(a.id);
  else practicePoints.set(a.id, point);
  if (current()?.id === a.id && before !== JSON.stringify(ui.practice[a.id])) {
    const box = document.querySelector('[data-v4-practice]');
    if (box) box.innerHTML = practiceSection(a);
  }
}
async function choosePractice(a, choice, optionId) {
  const v = ui.practice[a.id];
  if (!v || v.state !== 'ready' || ui.practiceBusy) return;
  // Reuse the request id after an unconfirmed attempt so a retry can never create a second practice.
  const prior = a.practiceRequest;
  const same =
    prior &&
    prior.choice === choice &&
    prior.optionId === optionId &&
    prior.submissionId === v.submissionId;
  const requestId = same ? prior.requestId : crypto.randomUUID();
  a.practiceRequest = { requestId, choice, optionId, submissionId: v.submissionId };
  persist();
  ui.practiceBusy = true;
  const box = document.querySelector('[data-v4-practice]');
  if (box) box.innerHTML = practiceSection(a);
  try {
    if (choice === 'choose' || choice === 'choose_other') {
      const shown = { ...v };
      delete shown.state;
      delete shown.submissionId;
      delete shown.links;
      delete shown.available;
      await enterWork(async () => {
        const { attempt } = await L.choosePractice(a, shown, choice, optionId, requestId, {
          initialTasks: SEED_KEYS.map((key) => ({ title: seedText(key) })),
        });
        a.practiceRequest = null;
        delete ui.practice[a.id];
        attempt.selectedTaskId = null;
        attempt.readTurns = {};
        attempt.turnTimes = {};
        attempt.eventTimes = {};
        attempt.turnTask = {};
        ui.arriving = true;
        resetAttemptUi();
        persist();
      });
      notify(
        T(
          '补练已开始；原练习和它的反馈保持不变。',
          'The practice has started; the original practice and its feedback are unchanged.',
        ),
      );
      return;
    }
    const shown = { ...v };
    delete shown.state;
    delete shown.submissionId;
    delete shown.links;
    delete shown.available;
    delete shown.catalog;
    await L.choosePractice(a, shown, choice, null, requestId);
    a.practiceRequest = null;
    persist();
    notify(
      choice === 'decline'
        ? T('已记录：这轮不补练。', 'Recorded: no practice this round.')
        : T(
            '已记录：继续修订原作品。可以在上方反馈里开始修订。',
            'Recorded: keep revising. Start a revision from the feedback above.',
          ),
    );
    await loadPractice(a, true);
  } catch (e) {
    notify(T('补练选择未确认：', 'The practice choice was not confirmed: ') + (e?.message || ''), {
      toast: true,
    });
  } finally {
    ui.practiceBusy = false;
    if (current() === a && ui.route === 'review') {
      const b = document.querySelector('[data-v4-practice]');
      if (b) b.innerHTML = practiceSection(a);
    }
  }
}
// Feedback in context: what is in the record, what was knowable at the time, why it matters.
function coachSection(a) {
  const items = Coach.observations(a, E, null);
  return `<section class="review-group coach"><p class="coach-lede">${T('从你实际做过的事里整理：看到了什么、当时能知道什么、为什么重要、可以做什么。不打分，可以提出不同看法。', 'Drawn from what you actually did: what is in the record, what was knowable then, why it matters, what you could do. No scores; you can disagree.')}</p>
    ${items.length ? `<ol class="feedback full">${items.map((i) => fbItem(a, i, true)).join('')}</ol>` : `<p class="feed-empty">${T('从现有记录里没有可整理的观察。', 'Nothing to draw from the record.')}</p>`}
    <p class="review-foot">${icon('info', 'i-xs')}${T('规则示意：根据记录生成，不是模型评审。情境化 Judge 需要后端支持。', 'Rule-based, from the record, not a model review. A contextual judge needs server support.')}</p></section>`;
}
// Criteria with the same verdict and the same reason read as one finding.
function mergeSame(list) {
  const out = [];
  for (const i of list) {
    const k = i.label + '|' + i.reason + '|' + !!i.review_required;
    const g = out.find((x) => x.key === k);
    if (g) g.names.push(i.criterion_id);
    else out.push({ ...i, key: k, names: [i.criterion_id] });
  }
  return out;
}
function stampMark(a) {
  const fresh = ui.justSubmitted === a.id;
  if (fresh) ui.justSubmitted = null;
  return `<div class="stamp-mark ${fresh ? 'fresh' : ''}" aria-hidden="true"><span>${T('已提交', 'Submitted')}</span>${a.submittedAt ? `<small>${esc(new Date(a.submittedAt).toLocaleDateString(locale() === 'en' ? 'en-GB' : 'zh-CN', { year: 'numeric', month: 'short', day: 'numeric' }))}</small>` : ''}</div>`;
}
function criterionItem(a, fb, i, common) {
  const ic =
    i.label === 'MET'
      ? 'good'
      : i.label === 'NOT_MET'
        ? 'warn'
        : i.label === 'NOT_APPLICABLE'
          ? 'minus'
          : 'question';
  const own = [...new Set(i.evidence_ids || [])].filter((id) => !common.has(id));
  return `<li class="criterion ${i.label}">
    <div class="crit-icon">${icon(ic)}</div>
    <div class="crit-body">
      <h3><span class="crit-name">${esc((i.names || [i.criterion_id]).map(criterionName).join(T('、', ', ')))}</span><span class="label-chip ${i.label}">${LABEL(i.label)}</span>${i.review_required ? `<span class="label-chip check">${T('需要核验', 'Needs checking')}</span>` : ''}</h3>
      <p${zhAttr(i.reason)}>${esc(i.reason)}</p>
      ${own.length ? `<div class="crit-evidence">${own.map((id) => `<button type="button" class="chip" data-action="live-evidence" data-criterion="${esc(i.criterion_id)}" data-id="${esc(id)}">${icon(evidenceIcon(fb, id), 'i-xs')}<span>${esc(evidenceLabel(a, fb, id))}</span></button>`).join('')}</div>` : ''}
    </div>
  </li>`;
}
function evidenceRef(fb, id) {
  for (const c of Object.values((fb && fb.sources) || {})) if (c && c[id]) return c[id];
  return null;
}
function evidenceIcon(fb, id) {
  const r = evidenceRef(fb, id);
  return (
    { config: 'gear', artifact: 'stamp', event: 'history', test_result: 'flask', document: 'doc' }[
      r && r.kind
    ] || 'doc'
  );
}
function evidenceLabel(a, fb, id) {
  const r = evidenceRef(fb, id);
  if (!r) return T('记录 ', 'Record ') + id;
  if (r.kind === 'config') return T('试点设置 v' + r.version, 'Pilot settings v' + r.version);
  if (r.kind === 'artifact') return T('交付稿', 'Deliverable');
  if (r.kind === 'event') return T('条件与审批', 'Conditions and approvals');
  if (r.kind === 'test_result') {
    const t = a.tests.find((x) => x.id === r.object_id);
    return T('测试：', 'Test: ') + (t ? t.question.slice(0, 28) : String(r.object_id).slice(0, 8));
  }
  if (r.kind === 'document') return materialTitle({ id: r.object_id, title: r.object_id });
  return r.kind;
}

/* ---------- sheets ---------- */
function openSheet(title, body, foot = '', cls = '', region = '') {
  commit();
  if (!sheet.open) sheetReturn = focusKey();
  sheet.className = 'sheet ' + cls;
  sheet.innerHTML = `<header class="sheet-head"><h2 id="sheet-title">${title}</h2>${btn(icon('x'), 'close', 'icon quiet small', `aria-label="${esc(T('关闭', 'Close'))}"`)}</header><div class="sheet-body" ${region ? `data-v4-region="${region}"` : ''}>${body}</div>${foot ? `<footer class="sheet-foot">${foot}</footer>` : ''}`;
  if (!sheet.open) sheet.showModal();
  (
    sheet.querySelector('[autofocus]') ||
    sheet.querySelector(
      '.sheet-body input:not([type=checkbox]):not([type=radio]), .sheet-body textarea',
    ) ||
    sheet.querySelector('.sheet-foot .primary') ||
    sheet.querySelector('.sheet-head .btn')
  )?.focus();
  sheet.querySelectorAll('.segmented').forEach(layoutSegmented);
  mountNativeSlots();
}
function closeSheet(instant) {
  if (!sheet.open) return;
  const done = () => {
    sheet.classList.remove('closing');
    sheet.close();
    mountNativeSlots();
    const el =
      sheetReturn &&
      (sheetReturn.id
        ? document.getElementById(sheetReturn.id)
        : document.querySelector(sheetReturn.sel));
    if (el) el.focus({ preventScroll: true });
    else document.getElementById('main')?.focus({ preventScroll: true });
  };
  if (instant || reduceMotion.matches) {
    done();
    return;
  }
  sheet.classList.add('closing');
  setTimeout(done, 200);
}
function sheetTask(id) {
  const a = current();
  const t = a.tasks.find((x) => x.id === id);
  openSheet(
    t ? T('编辑事项', 'Edit task') : T('新事项', 'New task'),
    `<form data-form="task" data-id="${t ? t.id : ''}" class="stack" id="task-form" data-revision="${t?.revision ?? ''}">
      <label class="field"><span>${T('要处理的事', 'What needs doing')}</span><input class="input" name="title" required maxlength="120" value="${esc(t ? taskTitle(t) : '')}" placeholder="${esc(T('例如：问清政策多久变一次', 'For example: find out how often policy changes'))}" autofocus></label>
      <label class="field"><span>${T('补充', 'Notes')} <small>${T('选填', 'optional')}</small></span><textarea class="textarea" name="note" rows="3" maxlength="5000">${esc(t ? taskNote(t) : '')}</textarea></label>
      <fieldset class="field"><legend>${T('优先级', 'Priority')}</legend><div class="choices">${['first', 'next', 'later'].map((k) => `<label class="choice"><input type="radio" name="priority" value="${k}" ${(t ? t.priority : 'next') === k ? 'checked' : ''}><span>${priMark(k)}${PRI(k)}</span></label>`).join('')}</div></fieldset>
      ${t ? `<label class="field"><span>${T('拆出一件新事', 'Split off a new task')} <small>${T('选填', 'optional')}</small></span><input class="input" name="split" maxlength="120"></label>` : ''}
    </form>`,
    `${t ? `${btn(icon('back', 'i-sm') + T('上移', 'Move up'), 'move-task', 'quiet', `data-id="${t.id}" data-dir="-1"`)}${btn(T('下移', 'Move down'), 'move-task', 'quiet', `data-id="${t.id}" data-dir="1"`)}<span class="spacer"></span>` : ''}<button type="submit" form="task-form" class="btn primary">${t ? T('保存', 'Save') : T('加入', 'Add')}</button>`,
    'narrow',
    L.nativeWorkspace(a) ? 'workspace-form' : '',
  );
}
function sheetNewArtifact(purpose, freeSheet = false) {
  const a = current();
  const t = task();
  openSheet(
    freeSheet ? T('新建自由纸', 'New free sheet') : T('新作品', 'New piece of work'),
    `<form data-form="artifact" id="artifact-form" class="stack">
    <label class="field"><span>${T('标题', 'Title')}</span><input class="input" name="title" required maxlength="160" value="${purpose === '试点决定' ? esc(T('试点决定', 'Pilot decision')) : ''}" placeholder="${esc(T('例如：我对首批范围的判断', 'For example: who goes first, and why'))}" autofocus></label>
    ${freeSheet ? `<label class="field"><span>${T('关联到能力点（可选）', 'Link to a point (optional)')}</span><select class="select" name="aipmStep"><option value="">${T('不关联', 'No link')}</option>${(Aipm.compassProps(a)?.rows ?? []).map((row) => `<option value="${esc(row.id)}">${row.order} · ${esc(row.label)}</option>`).join('')}</select></label>` : ''}
    <fieldset class="field"><legend>${T('它现在用来做什么', 'What it is for, for now')}</legend><div class="choices wrap">${E.PURPOSES.map((p) => `<label class="choice"><input type="radio" name="purpose" value="${p}" ${p === (purpose || '探索笔记') ? 'checked' : ''}><span>${esc(purposeLabel(p))}</span></label>`).join('')}</div></fieldset>
    <label class="field"><span>${T('属于哪件事', 'Which task')}</span><select class="select" name="taskId" required>${t || purpose ? '' : `<option value="" selected disabled>${T('选一件事', 'Pick a task')}</option>`}${a.tasks.map((x) => `<option value="${x.id}" ${(t ? x.id === t.id : purpose && x.seed === 'decision') ? 'selected' : ''}>${esc(taskTitle(x))}</option>`).join('')}</select></label>
  </form>`,
    `<button type="submit" form="artifact-form" class="btn primary">${T('开始写', 'Start writing')}</button>`,
    'narrow',
    L.nativeWorkspace(a) ? 'workspace-form' : '',
  );
}
function configChecks(a, c) {
  const cost = workCost(c.update, c.workItems || []);
  const rows = [
    [
      T(`试点 ${c.participants || 0} 人`, `${c.participants || 0} users`),
      T(`容量 ${a.world.capacity}`, `capacity ${a.world.capacity}`),
      c.participants <= a.world.capacity,
    ],
    [
      T(`开发 ${cost} 人日`, `${cost} person-days`),
      T(`可用 ${a.world.devDays}`, `${a.world.devDays} available`),
      cost <= a.world.devDays,
    ],
    [
      T(`开放 ${(c.domains || []).length} 类知识`, `${(c.domains || []).length} knowledge areas`),
      T('至少 1 类', 'at least 1'),
      (c.domains || []).length > 0,
    ],
    // The planned launch day must not fall after the deadline (e.g. day 5 when the pilot moves up).
    ...(c.launchDay
      ? [
          [
            T(`第 ${c.launchDay} 天上线`, `Launch on day ${c.launchDay}`),
            T(`期限第 ${a.world.deadline} 天`, `deadline day ${a.world.deadline}`),
            Number(c.launchDay) <= a.world.deadline,
          ],
        ]
      : []),
  ];
  return `<div class="checks-live" data-checks>${rows.map(([l, r, ok]) => `<p class="${ok ? 'ok' : 'bad'}">${icon(ok ? 'check' : 'x', 'i-sm')}<span>${l}</span><span class="muted">${r}</span></p>`).join('')}${rows.some((r) => !r[2]) ? `<p class="checks-note">${T('超出条件的方案可以保存，但要另外申请并获批才算数。', 'You can save a plan beyond the limits, but it only counts once a request is approved.')}</p>` : ''}</div>`;
}
function sheetConfig() {
  const a = current();
  const c =
    a.configDraft ||
    (!a.backend.configured
      ? {
          participants: Math.min(20, a.world.capacity),
          domains: ['faq', 'policy'],
          update: 'daily',
          fallback: 'human',
          workItems: ['scope', 'fallback'],
          launchDay: a.world.deadline,
        }
      : a.config);
  openSheet(
    T('试点设置', 'Pilot settings'),
    `<form data-form="config" id="config-form" class="stack">
    ${a.backend.configured ? configUseLine(configUse(a.effectiveConfig, a.world.devDays), T(`已保存 v${a.configVersion} · `, `Saved v${a.configVersion} · `)) : ''}
    <div class="field-row"><label class="field"><span>${T('试点人数', 'Users in the pilot')}</span><input class="input" type="number" name="participants" min="1" max="10000" value="${c.participants}" required></label>
    <label class="field"><span>${T('计划上线日', 'Planned launch day')}</span><input class="input" name="launchDay" type="number" min="1" value="${c.launchDay || a.world.deadline}" required></label></div>
    <fieldset class="field"><legend>${T('开放的知识', 'Knowledge it covers')}</legend><div class="choices">${L.configDomains(
      a,
    )
      .map(
        (k) =>
          `<label class="choice"><input type="checkbox" name="domains" value="${k}" ${c.domains.includes(k) ? 'checked' : ''}><span>${DOMAIN(k)}</span></label>`,
      )
      .join('')}</div></fieldset>
    <fieldset class="field"><legend>${T('政策怎么保持最新', 'Keeping policy current')}</legend><div class="choices wrap">${['daily', 'realtime', 'manual'].map((k) => `<label class="choice"><input type="radio" name="update" value="${k}" ${c.update === k ? 'checked' : ''}><span>${UPDATE(k)}</span></label>`).join('')}</div></fieldset>
    <fieldset class="field"><legend>${T('答不了或不确定时', 'When it cannot answer')}</legend><div class="choices">${['human', 'none'].map((k) => `<label class="choice"><input type="radio" name="fallback" value="${k}" ${c.fallback === k ? 'checked' : ''}><span>${FALLBACK(k)}</span></label>`).join('')}</div></fieldset>
    <fieldset class="field"><legend>${T('要安排的开发', 'Engineering work')}</legend><div class="choices wrap">${['scope', 'fallback', 'realtime'].map((k) => workItemChoice(k, c)).join('')}</div></fieldset>
    ${a.assistantMode ? generatorField(c.generator || 'extractive', a.assistantMode) : ''}
    ${configChecks(a, c)}
  </form>`,
    `${btn(icon('hand', 'i-sm') + T('申请资源', 'Request resources'), 'resources', 'quiet')}<span class="spacer"></span><button type="submit" form="config-form" class="btn primary">${T('保存设置', 'Save settings')}</button>`,
    '',
  );
  // The title takes the first focus (no ring); a field shows focus only when the learner enters it.
  const title = document.getElementById('sheet-title');
  if (title) {
    title.tabIndex = -1;
    title.focus({ preventScroll: true });
  }
}
function sheetResources() {
  const a = current();
  const s = sessionOf(a);
  const pending = s?.world.pending_requests || [];
  const denials = (s?.timeline.approval_denials || []).slice(-3).reverse();
  if (
    s?.approvalError &&
    !denials.some((d) => d.rule_id === s.approvalError.rule_id && d.code === s.approvalError.code)
  )
    denials.unshift(s.approvalError);
  openSheet(
    T('资源与审批', 'Resources and approvals'),
    `<div class="res-now">${conditions(a, 'compact')}</div>
    ${denials.map((d) => `<p class="warn-line" data-approval-denial>${icon('hand', 'i-sm')}<span>${esc(serverText(d.error || '', d.code, d.details))}</span></p>`).join('')}
    <form data-form="resources" id="res-form" class="stack">
      <fieldset class="field"><legend>${T('申请什么', 'What you need')}</legend><div class="choices">${[
        ['request_capacity', T('更多名额', 'More seats')],
        ['request_resources', T('更多开发资源或延期', 'More engineering time or a later date')],
      ]
        .map(
          ([k, l], i) =>
            `<label class="choice"><input type="radio" name="kind" value="${k}" ${i === 0 ? 'checked' : ''}><span>${l}</span></label>`,
        )
        .join('')}</div></fieldset>
      <label class="field"><span>${T('理由', 'Why')}</span><textarea class="textarea" name="reason" required maxlength="4000" rows="4" placeholder="${esc(T('要多少、做什么、为什么值得', 'How much, for what, and why it is worth it'))}"></textarea></label>
    </form>
    ${pending.length ? `<section class="pending"><h3 class="mini-title">${T(`等待 ${PEOPLE.manager.name} 处理`, `Waiting for ${PEOPLE.manager.ref}`)}</h3>${pending.map((rule) => `<div class="pending-row">${avatar('manager', 'sm')}<span class="grow">${rule === 'capacity_approved' ? T('扩容申请', 'Seat request') : T('资源与延期申请', 'Resource request')}</span>${btn(T(`请 ${PEOPLE.manager.name} 处理`, `Ask ${PEOPLE.manager.ref} to decide`), 'live-approval', 'small', `data-id="${esc(rule)}"`)}</div>`).join('')}</section>` : ''}`,
    `<button type="submit" form="res-form" class="btn primary">${T('提交申请', 'Send request')}</button>`,
    'narrow',
    s?.protocol === 2 ? 'resource-requests' : '',
  );
}
// Which pieces of local work go into the deliverable is the learner's choice.
function deliverPick(a) {
  const list = works(a).filter((w) => shown(w).body.trim());
  if (!ui.deliverPick || ui.deliverPickFor !== a.id) {
    const decisions = list.filter((w) => E.intentOf(shown(w).purpose) === 'commit');
    ui.deliverPick = new Set((decisions.length ? decisions : list).map((w) => w.id));
    ui.deliverPickFor = a.id;
  }
  return list;
}
function rationaleFrom(a, ids) {
  return works(a)
    .filter((w) => ids.has(w.id))
    .map((x) => {
      const v = shown(x);
      return (
        '## ' +
        v.title +
        T('（' + purposeLabel(v.purpose) + '）', ' (' + purposeLabel(v.purpose) + ')') +
        '\n' +
        v.body.trim() +
        (x.evidence.length
          ? '\n' +
            T('依据：', 'Evidence: ') +
            x.evidence
              .map((e) => evTitle(e) + (e.version ? ' v' + e.version : ''))
              .join(T('；', '; '))
          : '')
      );
    })
    .join('\n\n');
}
// The review reads one evidence bundle of at most 16,000 bytes; past that every item
// is left unreviewed with an explicit overflow flag. Rough estimate from measurements on this backend.
function bundleRisk(a, draft) {
  const bytes = (s) => new TextEncoder().encode(String(s || '')).length;
  const fields = FIELDS.reduce((n, k) => n + bytes(draft[k]), 0);
  return 7000 + fields + bytes(draft.rationale) + a.tests.length * 750 > 14500;
}
function sheetDeliver(readOnly = false) {
  const a = current();
  const s = sessionOf(a);
  if (L.nativeWorkspace(a)) {
    // The delivery's own button sits at the right of this footer (placed there by the panel,
    // right after the pre-submission card in reading order); the way to past feedback is a text
    // button on the left. On a phone it says only "View feedback", so it stays on one line; the
    // hidden label is display: none, so a screen reader hears just the one shown.
    openSheet(
      T('交付试点决定', 'Submit your pilot decision'),
      `<div class="deliver-doc"
        data-v4-submission data-v4-region="submission"></div>`,
      btn(
        `<span class="when-wide">${T('查看提交与反馈', 'View submission and feedback')}</span><span class="when-narrow">${T('查看反馈', 'View feedback')}</span>`,
        'v4-feedback',
        'quiet',
      ),
      'wide doc deliver-sheet',
    );
    mountLensSwitch(sheet.querySelector('.sheet-head'));
    openLensForDelivery(sheet);
    // Start reading at the title: no control looks chosen until the person moves.
    const title = sheet.querySelector('#sheet-title');
    if (title) {
      title.tabIndex = -1;
      title.focus({ preventScroll: true });
    }
    return;
  }
  if (s.world.status === 'submitted' && !readOnly) {
    closeSheet(true);
    go('review');
    return;
  }
  const list = deliverPick(a);
  if (!readOnly && !s.draft.rationale && list.length)
    L.store.update(a.id, { draft: { ...s.draft, rationale: rationaleFrom(a, ui.deliverPick) } });
  const now = sessionOf(a);
  const saved =
    now.artifact &&
    JSON.stringify(now.artifact.content) === JSON.stringify(now.draft) &&
    now.artifact.config_version === now.world.config_version;
  const risk = bundleRisk(a, now.draft);
  const displayed = readOnly ? s.artifact?.content || s.draft : now.draft;
  openSheet(
    T('交付试点决定', 'Submit your pilot decision'),
    `<div class="deliver">
  <form data-form="live-deliver" id="live-deliver" class="deliver-doc paper">
    ${FIELDS.map((k) => `<section class="field-doc"><label for="d-${k}"><span class="fd-name">${FIELD(k)}</span><span class="fd-hint">${FIELD_HINT(k)}</span></label><textarea id="d-${k}" class="doc-input" name="${k}" ${readOnly ? 'readonly' : ''} rows="${k === 'rationale' ? 8 : 2}"${zhAttr(now.draft[k])}>${esc(displayed[k])}</textarea></section>`).join('')}
  </form>
  <aside class="deliver-side">
    <h3 class="mini-title">${T('附上的作品', 'Work to include')}</h3>
    ${
      list.length
        ? `<div class="checks">${list
            .map((w) => {
              const v = shown(w);
              return `<label class="check"><input type="checkbox" data-pick="${w.id}" ${readOnly ? 'disabled' : ''} ${ui.deliverPick.has(w.id) ? 'checked' : ''}><span>${esc(v.title)}</span><small>${esc(purposeLabel(v.purpose))}</small></label>`;
            })
            .join('')}</div>`
        : `<p class="muted">${T('没有可附上的作品。', 'No work to include.')}</p>`
    }
    ${!readOnly && (list.length || now.draft.rationale) ? btn(icon('refresh', 'i-sm') + (list.length ? T('按勾选重写依据', 'Rewrite evidence from these') : T('清空方案与依据', 'Clear rationale and evidence')), 'live-collect', 'small quiet') : ''}
    ${a.deliverRemovalNotice ? `<p class="warn-line">${icon('info', 'i-sm')}${T('有作品被移除，交付稿中的手写内容已保留。请核对，或按当前作品重新整理。', 'Some work was removed. Edited deliverable text was kept. Review it, or rebuild it from the current work.')}</p>` : ''}
    ${risk ? `<p class="warn-line">${icon('warn', 'i-sm')}${T('内容偏长：评审一次最多读约 16 KB 记录，超过后相关条目不会评审。精简依据或少附作品。', 'This is long. The review reads about 16 KB of records at most; items beyond that limit are left unreviewed. Trim the evidence or include fewer pieces.')}</p>` : ''}
    <p class="meta">${now.artifact ? (saved ? T('已保存为交付稿 v' + now.artifact.version, 'Saved as deliverable v' + now.artifact.version) : T('交付稿 v' + now.artifact.version + ' 之后有改动', 'Changed since deliverable v' + now.artifact.version)) : T('还没保存', 'Not saved yet')}</p>
  </aside></div>`,
    readOnly
      ? `<span class="foot-note">${T('本次交付已固定。下次交付可在这里少选作品、精简依据。', 'This submission is fixed. For the next submission, select fewer works here and trim the evidence.')}</span>${btn(T('关闭', 'Close'), 'close', 'primary')}`
      : `<span class="foot-note">${T('提交后这次练习只读，可以换个条件再练。', 'Once submitted, this practice is read-only. You can practise again with a new condition.')}</span><span class="spacer"></span>${btn(T('保存', 'Save'), 'live-save', saved ? 'quiet' : '')}${btn(icon('stamp', 'i-sm') + T('提交', 'Submit'), 'live-submit', 'primary', saved ? '' : 'disabled')}`,
    'wide doc',
  );
}
function sheetCitePicker() {
  const a = current();
  const read = readSet(a);
  read.add('brief');
  const docs = E.getMaterials(a).filter((m) => read.has(m.id));
  openSheet(
    T('引用依据', 'Cite evidence'),
    `<div class="pick-list">
    <h3 class="mini-title">${T('读过的资料', 'Documents you read')}</h3>${docs.map((m) => `<button type="button" class="pick-row" data-action="cite-material" data-id="${esc(m.id)}">${icon('doc', 'i-sm')}<span class="grow">${esc(materialTitle(m))}</span><span class="ver">v${m.version}</span></button>`).join('') || `<p class="muted">${T('还没读过资料。', 'No documents read yet.')}</p>`}
    <h3 class="mini-title">${T('测试', 'Tests')}</h3>${
      a.tests
        .slice()
        .reverse()
        .map(
          (r) =>
            `<button type="button" class="pick-row" data-action="cite-run" data-id="${esc(r.id)}">${assistantMark('xs')}<span class="grow"${zhAttr(r.question)}>${esc(r.question)}</span><span class="ver">${T('配置 v', 'config v')}${r.configVersion}</span></button>`,
        )
        .join('') || `<p class="muted">${T('还没有测试。', 'No tests yet.')}</p>`
    }
  </div>`,
    '',
    'narrow',
  );
}
// "About this workspace": what the workbench is made of, the model status in full, and the
// internals kept out of the working view (records with event numbers, raw exports, the rubric
// and the situation's content version).
function sheetAbout() {
  const n = snap();
  const a = current();
  const native = !!a && L.nativeWorkspace(a);
  const status = a ? modelStatusOf(a) : null;
  const s = a ? sessionOf(a) : null;
  const kv = (rows) =>
    `<dl class="kv">${rows
      .filter(([, value]) => value)
      .map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`)
      .join('')}</dl>`;
  const facts = a ? aboutFacts(a.id) : [];
  const hash = s?.v2Binding?.scenarioHash;
  const records = a
    ? `<section class="about-sec" data-about="records"><h3 class="mini-title">${T('记录与导出', 'Records and exports')}</h3>
    ${kv([
      ...facts.map((fact) => [fact.label, fact.value]),
      [T('情境内容版本', 'Situation content version'), hash ? String(hash).slice(0, 12) : ''],
    ])}
    <div class="about-actions">${btn(icon('history', 'i-sm') + T('过程记录（含事件序号）', 'Activity log with event numbers'), 'live-timeline', 'small quiet')}${btn(icon('doc', 'i-sm') + T('查看任务包（JSON）', 'View task package (JSON)'), 'package', 'small quiet')}${btn(icon('download', 'i-sm') + T('导出本地笔记（JSON）', 'Export local notes (JSON)'), 'export', 'small quiet')}</div>
    </section>`
    : '';
  openSheet(
    T('关于这个工作台', 'About this workspace'),
    `<div class="prose about">
    <p>${T(`资料、三位同事的回复、试点设置、申请审批、助手测试、交付和评审，都来自 ${PRODUCT_NAME} 后端。`, `Documents, colleague replies, pilot settings, approvals, assistant tests, submission and review come from the ${PRODUCT_NAME} server.`)}</p>
    <p>${
      native
        ? T(
            '事项、作品版本、分享、提交与反馈由服务端保存。未保存草稿与恢复信息保留在这个浏览器。',
            'Tasks, work versions, shares, submissions and feedback are saved by the server. ' +
              'Unsaved drafts and recovery information remain in this browser.',
          )
        : T(
            '旧会话的事项、作品和 Agent 导入保存在这个浏览器；交付时由你合并进交付稿。',
            'In legacy sessions, tasks, work and agent imports stay in this browser. ' +
              'You fold them into the deliverable when you submit.',
          )
    }</p>
    <section class="about-sec" data-about="model"><h3 class="mini-title">${status ? esc(status.label) : T('模型', 'Model')}</h3>
    ${status ? modelPartsHtml(status) : ''}
    ${kv([
      [T('后端', 'Server'), n.connected ? T('已连接', 'Connected') : T('未连接', 'Not connected')],
      [T('同事与助手模式', 'Colleague and assistant mode'), n.model || '—'],
    ])}
    </section>
    <section class="about-sec"><h3 class="mini-title">${T('颜色和形状', 'Colour and shape')}</h3>
    <ul class="legend">
      <li><span class="sw ink"></span>${T('你，和你能做的事；你的 Agent 也是这个颜色', 'You and what you can do; your agent shares it')}</li>
      <li><span class="sw warn"></span>${T('外面变了或已过期：政策更新、索引落后、条件被改变', 'Changed from outside or out of date: a policy update, a lagging index, a changed condition')}</li>
      <li><span class="sw good"></span>${T('站得住：已完成、已满足、已批准、可用', 'Holds: done, met, approved, available')}</li>
      <li><span class="sw bad"></span>${T('超出限制', 'Over a limit')}</li>
      <li><span class="sw grey"></span>${T('还不知道：证据不足、需要核验', 'Not known yet: thin evidence, needs checking')}</li>
      <li><span class="sw-shape">${modelWaitHtml()}</span>${T('等模型接入：现在用规则或原文代替', 'Awaiting a model: rules or source passages stand in for now')}</li>
      <li><span class="sw-people">${avatar('manager', 'xs')}${avatar('business', 'xs')}${avatar('technical', 'xs')}${assistantMark('xs')}</span>${T(`谁：${ROLES.map((r) => PEOPLE[r].label).join('、')}、知识助手`, `Who: ${ROLES.map((r) => PEOPLE[r].label).join(', ')}, the knowledge assistant`)}</li>
      <li><span class="sw-shape">${priMark('first')}${priMark('next')}${priMark('later')}</span>${T('优先级：先做、随后、暂放', 'Priority: do first, up next, later')}</li>
      <li><span class="sw-shape">${statusMark('open')}${statusMark('working')}${statusMark('done')}</span>${T('进展：待处理、正在做、已处理', 'Progress: to do, in progress, done')}</li>
    </ul>
    </section>
    ${records}
    <p class="muted">${
      native
        ? T(
            '支持关联修订与授权 MCP 协作。带灰圈的内容等待模型接入，尚未做语义评审。',
            'Linked revisions and authorized MCP collaboration are available. ' +
              'Items with a grey ring await a model and have no semantic review yet.',
          )
        : T(
            '当前旧会话保留原有交付与回读方式，模型能力以界面标注为准。',
            'Legacy sessions retain their submission and history workflow. ' +
              'Model capabilities follow the displayed status.',
          )
    }</p>
  </div>`,
    `${btn(T('刷新连接', 'Reconnect'), 'live-refresh', 'quiet')}<span class="spacer"></span>${btn(T('好', 'OK'), 'close', 'primary')}`,
    'narrow',
  );
}

/* ---------- live world: connection, typing, arrivals ---------- */
function onLive(changed) {
  const n = snap();
  refreshAgentIssued();
  noticeArrivals();
  if (sheet.open && sheet.querySelector('.res-now') && current())
    sheet.querySelector('.res-now').innerHTML = conditions(current(), 'compact');
  if (n.error && n.error !== ui.lastError) {
    ui.lastError = n.error;
    notify(n.error);
  } else if (!n.error) ui.lastError = '';
  if (changed) scheduleRefresh();
  else refreshChrome();
}
let refreshQueued = false;
function scheduleRefresh() {
  if (refreshQueued) return;
  refreshQueued = true;
  queueMicrotask(() => {
    refreshQueued = false;
    if (dirty) flush();
    if (WS.includes(ui.route) && current()) refreshWS();
    else render();
  });
}
function refreshChrome() {
  if (WS.includes(ui.route) && current()) refreshWS(['toolbar']);
}
// What changed in the world since we last looked: replies, policy versions, approvals.
function noticeArrivals() {
  const a = current();
  if (!a || !a.backend) return;
  const s = sessionOf(a);
  if (!s) return;
  a.turnTimes = a.turnTimes || {};
  a.eventTimes = a.eventTimes || {};
  a.readTurns = a.readTurns || {};
  // A practice opened with its continue code arrives with history; its first full read is not news.
  const history = !!s.recovered && !a.historyRead;
  const first = !ui.synced || history;
  const pend = pendingTurnRole(s) ? s.pending : null;
  if (pend)
    ui.pendingTurn = {
      role: ROLE_OF[pendingTurnRole(s)],
      created: pend.job?.queued_at || pend.created,
      taskId: pend.body.task_id ?? ui.chatTask ?? null,
    };
  a.turnTask = a.turnTask || {};
  let dirtyRecord = false;
  for (const r of ROLES) {
    const msgs = (a.conversations[r] || []).filter((m) => m.role !== 'user');
    Greetings.receipts.seed(
      a.id,
      r,
      replyIds(a, r).slice(0, a.readTurns[r] ?? (history ? msgs.length : 0)),
    );
    if (a.readTurns[r] === undefined) {
      a.readTurns[r] = msgs.length;
      dirtyRecord = true;
    }
    for (const m of msgs) {
      if (!m.traceId) continue;
      if (a.turnTimes[m.traceId] !== undefined) {
        if (m.createdAt) a.turnTimes[m.traceId] = { asked: m.createdAt, answered: m.createdAt };
        continue;
      }
      if (first) {
        a.turnTimes[m.traceId] = m.createdAt ? { asked: m.createdAt, answered: m.createdAt } : null;
        continue;
      }
      const asked = ui.pendingTurn && ui.pendingTurn.role === r ? ui.pendingTurn.created : null;
      a.turnTimes[m.traceId] = {
        asked: m.createdAt || asked,
        answered: m.createdAt || new Date().toISOString(),
      };
      dirtyRecord = true;
      if (
        m.context?.task_id === undefined &&
        ui.pendingTurn &&
        ui.pendingTurn.role === r &&
        ui.pendingTurn.taskId
      )
        a.turnTask[m.traceId] = ui.pendingTurn.taskId;
      if (ui.pendingTurn && ui.pendingTurn.role === r) ui.pendingTurn = null;
      const visible =
        WS.includes(ui.route) &&
        ui.railTab === 'team' &&
        ui.rail === 'chat' &&
        ui.chatRole === r &&
        railVisible();
      if (!visible)
        notify(T(`${PEOPLE[r].name} 回复了`, `${PEOPLE[r].subject} replied`), {
          lead: avatar(r, 'sm'),
          action: { label: T('查看', 'View'), run: () => openChat(r) },
        });
    }
  }
  // Approved requests change the conditions; mark them so the facts can light up once.
  const was = ui.lastWorld && ui.lastWorld.id === a.id ? ui.lastWorld : null;
  if (was && !first) {
    const keys = ['capacity', 'devDays', 'deadline'].filter((k) => was[k] !== a.world[k]);
    if (keys.length) ui.changed = { keys, until: Date.now() + 4000 };
  }
  ui.lastWorld = {
    id: a.id,
    capacity: a.world.capacity,
    devDays: a.world.devDays,
    deadline: a.world.deadline,
  };
  for (const e of a.events.filter((x) => x.server)) {
    if (a.eventTimes[e.seq] !== undefined) {
      if (e.createdAt) a.eventTimes[e.seq] = e.createdAt;
      continue;
    }
    a.eventTimes[e.seq] = e.createdAt || (first ? null : new Date().toISOString());
    dirtyRecord = true;
    if (first) continue;
    const l = eventLine(a, e, workLang(a));
    if (l.announce)
      notify(
        l.text,
        l.announce === 'policy'
          ? {
              toast: true,
              lead: `<span class="toast-icon">${icon('bolt', 'i-sm')}</span>`,
              action: {
                label: T('看变化', 'See changes'),
                run: () => openMaterial('policy', true),
              },
            }
          : {
              toast: true,
              lead: `<span class="toast-icon">${icon(l.icon || 'info', 'i-sm')}</span>`,
            },
      );
  }
  if (!first || s.timeline.events.length || s.materials.length)
    ui.synced = ui.synced || !!s.materials.length;
  if (history && s.materials.length) {
    a.historyRead = true;
    dirtyRecord = true;
  }
  if (dirtyRecord) persist();
}
const railVisible = () => window.matchMedia('(min-width: 1280px)').matches || ui.railOpen;
let readRoot = null;
let stopReading = () => {};
function markRead() {
  const a = current(),
    root = document.querySelector('#ws-rail .chat');
  if (root === readRoot) return;
  stopReading();
  readRoot = root;
  if (!a || !root || !ui.chatRole) return;
  const role = ui.chatRole;
  stopReading = Greetings.watchMessages(
    root,
    (id) => {
      if (Greetings.receipts.read(a.id, role, id)) paintUnread();
    },
    () =>
      current()?.id === a.id &&
      ui.rail === 'chat' &&
      ui.chatRole === role &&
      railVisible() &&
      !sheet.open &&
      !document.querySelector('.rc-tour'),
  );
}

let notesReadRoot = null;
let stopReadingNotes = () => {};
function markNotesRead() {
  const a = current(), root = document.querySelector('.ws');
  if (root === notesReadRoot) return;
  stopReadingNotes();
  notesReadRoot = root;
  if (!a || !root) return;
  stopReadingNotes = Greetings.watchMessages(root, id => {
    const note = (ui.notesCache || []).find(n => noteKey(n.key) === id);
    if (note && Greetings.receipts.read(a.id, note.role, id)) paintUnread();
  }, () => current()?.id === a.id && !sheet.open && !document.querySelector('.rc-tour'), '[data-note-message-id]');
}

/* ---------- workspace refresh ---------- */
// The toolbar holds open menus and pressed buttons: replace it only when its markup changes.
let toolbarShown = { node: null, html: '' };
function refreshWS(parts = ['toolbar', 'stage', 'rail']) {
  const a = current();
  if (!a || !WS.includes(ui.route)) {
    render();
    return;
  }
  // An asynchronous source reply must not tear down an active IME composition.
  if (parts.includes('stage') && ui.investigationComposing) {
    ui.investigationRefreshQueued = true;
    parts = parts.filter((p) => p !== 'stage');
  }
  // Under an open document the board stays as it is (B1); it catches up when the sheet closes.
  if (parts.includes('stage') && ui.docSheet && WS.includes(ui.route) && !routeTask(a)) {
    ui.stageStale = true;
    parts = parts.filter((p) => p !== 'stage');
  }
  if (parts.includes('stage') && dirty) flush();
  ui.notesCache = Coach.notes(a, E);
  const key = focusKey();
  const ws = document.querySelector('.ws');
  if (!ws) {
    render();
    return;
  }
  const stage = document.getElementById('main');
  const y = stage ? stage.scrollTop : 0;
  const openMomentCards = [...(stage?.querySelectorAll('.rc-test-moment [data-rc-card][aria-expanded="true"]') || [])].map((key) => key.dataset.rcCard);
  if (parts.includes('toolbar')) {
    const tb = document.getElementById('ws-toolbar');
    const html = wsToolbar(a);
    if (tb && (tb !== toolbarShown.node || html !== toolbarShown.html)) {
      tb.outerHTML = html;
      toolbarShown = { node: document.getElementById('ws-toolbar'), html };
    }
  }
  if (parts.includes('stage')) {
    // The native board draws its cards a moment after this markup; until then the page would be
    // shorter and the scroll position clamped. Hold the old height until the cards are back.
    const held = document.getElementById('ws-stage')?.offsetHeight || 0;
    document.getElementById('ws-stage').outerHTML =
      `<div id="ws-stage" class="stage-inner" ${L.nativeWorkspace(a) ? 'data-v4-region="workspace"' : ''}>${progressSlot(a)}${aipmScreen(a) ? '' : wsStage(a)}</div>`;
    const next = document.getElementById('ws-stage');
    if (next && held) {
      next.style.minHeight = `${held}px`;
      const release = () => {
        if (next.isConnected) next.style.minHeight = '';
      };
      (document.querySelector('.kanban') ? Board.tasksDrawn(1, 1500) : Promise.resolve()).then(() =>
        requestAnimationFrame(release),
      );
    }
    if (stage) stage.scrollTop = y;
    for (const id of openMomentCards) {
      const card = document.getElementById(id);
      const key = next?.querySelector(`[data-rc-card="${CSS.escape(id)}"]`);
      if (card && key) { card.hidden = false; key.setAttribute('aria-expanded', 'true'); void fillCardMetrics(card, locale()); }
    }
    ui.stageStale = false;
  }
  if (parts.includes('rail')) {
    const rb = document.querySelector('#ws-rail .rail-body');
    const ry = rb ? rb.scrollTop : 0;
    document.getElementById('ws-rail').innerHTML = wsRail(a);
    const nb = document.querySelector('#ws-rail .rail-body');
    if (nb) nb.scrollTop = ry;
  }
  ws.classList.toggle('rail-open', ui.railOpen);
  ws.dataset.status = statusOf(a);
  afterRender();
  restoreFocus(key);
  boardSettle();
}
// After the board is drawn: a newly opened document slides in, an arriving change hangs its
// amber marks one after another.
function boardSettle() {
  const a = current();
  if (a && document.querySelector('.ws')) {
    keepDocSheet(a);
    keepRecords(a);
  }
  Board.playReadings();
  if (ui.amberArriving != null) {
    Board.staggerAmber(ui.amberArriving);
    ui.amberArriving = null;
  }
}
const narrowRail = () => window.matchMedia('(max-width: 1279px)').matches;
function syncPanels() {
  const rail = document.getElementById('ws-rail');
  if (!rail) return;
  rail.inert = narrowRail() && !ui.railOpen;
  ['#main', '#ws-toolbar'].forEach((sel) => {
    const el = document.querySelector(sel);
    if (el) el.inert = narrowRail() && ui.railOpen;
  });
}

/* ---------- actions ---------- */
function ensureArtifact() {
  const a = current();
  const t = task();
  if (!t) return null;
  let x = artifact();
  if (x && x.taskId === t.id && !isEarlier(a, x) && x.adopted) return x;
  x = a.artifacts
    .filter((y) => y.taskId === t.id && !y.removedAt && !isEarlier(a, y) && y.adopted)
    .at(-1);
  if (!x)
    x = E.createArtifact(a, {
      taskId: t.id,
      title: T('关于「' + taskTitle(t) + '」的记录', 'Notes on “' + taskTitle(t) + '”'),
      purpose: '探索笔记',
      body: '',
    });
  ui.artifactId = x.id;
  ui.obj = { task: t.id, type: 'work', id: x.id };
  return x;
}
// Evidence actions on server work open the shared picker on the work's draft (native-cite.ts).
const nativeCiteHost = {
  native: (a) => L.nativeWorkspace(a),
  open: () => artifact(),
  find: (a, id) => a.artifacts.find((x) => x.id === id && !x.removedAt) || null,
  newest: (a) => {
    const t = task();
    return (t && taskWorks(a, t.id).at(-1)) || null;
  },
  cite: (a, x, focus) => L.citeNative(a, x.id, focus),
  view: (a, x, key) => L.openNativeEvidence(a, x.id, key),
  materialVersion: (a, id) => E.getMaterials(a).find((m) => m.id === id)?.version,
  show: (x) => {
    if (ui.route === 'task' && ui.obj?.type === 'work' && ui.artifactId === x.id)
      refreshWS(['stage']);
    else if (x.taskId) {
      ui.artifactId = x.id;
      openTask(x.taskId, { type: 'work', id: x.id });
    } else refreshWS(['stage']);
  },
  notify: (text) => notify(text),
  errorText: errText,
};
// A work's evidence: one chip per cited object, then each cited passage in its own words so the
// basis can be read where the work is (an agent's returned work included). Chips open the original.
function nativeEvidenceRow(a, x, label, cls = '') {
  const chips = L.nativeEvidenceChips(a, x.id);
  if (!chips.length) return '';
  const glyph = { material: 'doc', test: 'flask', product: 'note' };
  const work = `data-work="${esc(x.id)}"`;
  const quotes = chips.filter((c) => c.quote);
  return `<div class="evidence-row ${cls}"><span class="meta">${label}</span>${chips.map((c) => `<button type="button" class="chip" data-action="view-evidence" data-key="${esc(c.key)}" ${work} aria-label="${esc(c.description)}" title="${esc(c.description)}">${icon(glyph[c.kind] || 'doc', 'i-xs')}<span>${esc(c.label)}</span>${c.version ? `<span class="ver">${esc(c.version)}</span>` : ''}</button>`).join('')}</div>${
    quotes.length
      ? `<ul class="evidence-quotes" aria-label="${esc(T('引用的原文', 'Cited passages'))}">${quotes.map((c) => `<li><blockquote class="evidence-quote"${zhAttr(c.quote)}>${esc(c.quote)}</blockquote>${chips.length > 1 ? `<button type="button" class="link quiet evidence-quote-src" data-action="view-evidence" data-key="${esc(c.key)}" ${work}>${esc(c.label)} · ${esc(c.version)}</button>` : ''}</li>`).join('')}</ul>`
      : ''
  }`;
}
function cite(ev) {
  const a = current();
  const x = ensureArtifact();
  if (!x) {
    ui.pendingCite = ev;
    openSheet(
      T('加到哪件事', 'Add it to which task?'),
      `<div class="pick-list">${a.tasks.map((t) => `<button type="button" class="pick-row" data-action="cite-into" data-id="${t.id}">${priMark(t.priority)}<span class="grow">${esc(taskTitle(t))}</span>${icon('chev', 'i-xs')}</button>`).join('')}</div>`,
      '',
      'narrow',
    );
    return;
  }
  try {
    E.addEvidence(a, x.id, ev);
    persist();
    closeSheet(true);
    notify(
      T(
        '已加入「' + shown(x).title + '」的依据',
        'Added to the evidence for “' + shown(x).title + '”',
      ),
    );
  } catch (err) {
    notify(errText(err));
  }
}
function attachToTurn(a, item) {
  const s = sessionOf(a),
    role = ROLE_ID[ui.chatRole];
  if (!s || !role) return false;
  const context = s.turnContexts?.[role] || {};
  const attachments = (context.attachments || []).filter(
    (x) => !(x.type === item.type && x.id === item.id),
  );
  if (attachments.length >= 10) {
    notify(T('每条消息最多附上 10 个对象。', 'Attach up to 10 items per message.'));
    return false;
  }
  return L.store.update(a.id, {
    turnContexts: {
      ...s.turnContexts,
      [role]: { ...context, attachments: [...attachments, item] },
    },
  });
}
function openChat(role, prefill = '') {
  const a = current();
  ui.railTab = 'team';
  ui.rail = 'chat';
  ui.chatRole = role;
  ui.menu = null;
  if (narrowRail()) ui.railOpen = true;
  if (!WS.includes(ui.route) && !ENGINEER_ROUTES.includes(ui.route) && !isRegisteredRoute(ui.route)) {
    go('work');
  } else refreshWS(['rail', 'toolbar']);
  if (a) markRead();
  const input = document.getElementById('chat-input');
  if (input) {
    if (prefill) {
      input.value = prefill;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    input.focus();
  }
}
// Opens a colleague's conversation and sends the question through its bound composer, the same
// path a typed question takes (pending requests, retries and the real reply stay with it). A draft
// or attachment already there is kept and nothing is sent. Resolves whether it was accepted.
async function askColleague(a, person, question) {
  const attemptId = a.id;
  openChat(person);
  // Let the existing native slot bind its permissions and composer. It owns submission,
  // pending requests, retries and the eventual real reply; no alternate send API is added.
  for (let i = 0; i < 100; i += 1) {
    if (current()?.id !== attemptId || ui.chatRole !== person) return false;
    const form = document.querySelector('.composer');
    const input = document.getElementById('chat-input');
    const send = form?.querySelector('button[type="submit"]');
    if (
      form &&
      input &&
      send &&
      !send.disabled &&
      form.dataset.rolesBound === ROLE_ID[person]
    ) {
      if (input.value.trim() || ui.chatQuotes[quoteKey(a, person)]) {
        notify(
          T(
            '你的草稿和引用已保留。先处理它们，再点建议问题。',
            'Your draft and attachment are safe. Send or clear them before choosing a suggested question.',
          ),
        );
        return false;
      }
      // Submit synchronously through the bound owner. Its send method saves the draft;
      // a synthetic input event here could remount the form before submit.
      input.value = question;
      return await new Promise((resolve) => {
        const token = crypto.randomUUID();
        let revised = false;
        const changed = (event) => {
          if (
            current()?.id === attemptId &&
            ui.chatRole === person &&
            event.target.id === 'chat-input'
          )
            revised = true;
        };
        const cleanup = () => {
          clearTimeout(timeout);
          document.removeEventListener('input', changed, true);
          form.removeEventListener('rolecraft:greeting-result', settled);
        };
        const settled = async (event) => {
          if (event.detail?.token !== token) return;
          clearTimeout(timeout);
          form.removeEventListener('rolecraft:greeting-result', settled);
          try {
            if (event.detail.accepted && !revised) {
              const host = L.v4Host(a);
              const key = `question:${ROLE_ID[person]}`;
              if (host?.draft('roles', key) === question)
                await host.keepDraft('roles', key, '');
              const liveInput = document.getElementById('chat-input');
              if (
                !revised &&
                current()?.id === attemptId &&
                ui.chatRole === person &&
                liveInput?.value === question
              )
                liveInput.value = '';
            }
            resolve(!!event.detail.accepted);
          } catch (error) {
            notify(errText(error));
            resolve(false);
          } finally {
            cleanup();
          }
        };
        const timeout = setTimeout(() => {
          cleanup();
          resolve(false);
        }, 25000);
        document.addEventListener('input', changed, true);
        form.addEventListener('rolecraft:greeting-result', settled);
        form.dataset.greetingRequest = token;
        form.requestSubmit(send);
      });
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  notify(
    T(
      '对话还没就绪，请稍后再点这个问题。',
      'The conversation is not ready yet. Try the question again shortly.',
    ),
  );
  return false;
}
// Reading is a counted business action on the server; record the first read of each version only.
async function recordRead(a, id, m = E.getMaterials(a).find((x) => x.id === id)) {
  if (m) a.acks = [...new Set([...(a.acks || []), `read-${id}-v${m.version}`])];
  const readKey = id + '@' + (m ? m.version : 0);
  a.readSent = Array.isArray(a.readSent) ? a.readSent : [];
  if (!a.readSent.includes(readKey) || !m?.body) {
    try {
      await L.read(a, id);
      a.readSent.push(readKey);
      persist();
    } catch (err) {
      notify(errText(err));
    }
  }
}
// Inside a task a document opens beside the work; from the board it opens on its own page.
async function openMaterial(id, compare = false) {
  const a = current();
  if (!a) return;
  commit();
  ui.menu = null;
  ui.compare = compare;
  const m = E.getMaterials(a).find((x) => x.id === id);
  if (m) a.acks = [...new Set([...(a.acks || []), 'read-' + id + '-v' + m.version])];
  const t = routeTask(a);
  if (t) {
    t.docs = [...new Set([...(t.docs || []), id])];
    ui.obj = { task: t.id, type: 'doc', id };
    persist();
    refreshWS(['stage', 'toolbar']);
  } else if (ui.route === 'doc' || !WS.includes(ui.route)) {
    persist();
    go('doc', { id });
  } else {
    persist();
    if (ui.docSheet !== id) Board.willOpen(id);
    ui.docSheet = id;
    // Over the board a new version marks its change in place; v1 is one switch away.
    ui.compare = false;
    refreshWS(['overlay', 'toolbar']);
  }
  await recordRead(a, id, m);
  if (m && m.version > 1 && !ui.previous[id]) {
    try {
      // The version before, read without recording a read (as the change band does).
      const prev = L.nativeWorkspace(a)
        ? await L.materialVersion(a, id, m.version - 1)
        : (await L.history(a, 0)).find((x) => x.id === id && x.version < m.version);
      if (prev?.content) {
        ui.previous[id] = { version: prev.version || m.version - 1, content: String(prev.content) };
        refreshWS(['stage']);
      }
    } catch (_) {
      /* comparison stays unavailable */
    }
  }
}
function openTask(id, obj) {
  const a = current();
  if (!a) return;
  commit();
  a.selectedTaskId = id;
  ui.obj = obj ? { task: id, ...obj } : null;
  persist();
  if (ui.route === 'task' && ui.routeId === id) {
    refreshWS(['stage', 'toolbar', 'rail']);
    return;
  }
  go('task', { id, transition: true });
}
function flip(mutate) {
  const sel = '.kanban .card';
  const before = new Map(
    [...document.querySelectorAll(sel)].map((el) => [
      el.dataset.taskId,
      el.getBoundingClientRect(),
    ]),
  );
  mutate();
  if (reduceMotion.matches) return;
  document.querySelectorAll(sel).forEach((el) => {
    const b = before.get(el.dataset.taskId);
    if (!b) {
      el.animate(
        [
          { opacity: 0, transform: 'translateY(-6px)' },
          { opacity: 1, transform: 'none' },
        ],
        { duration: 280, easing: 'cubic-bezier(.32,.72,0,1)' },
      );
      return;
    }
    const r = el.getBoundingClientRect();
    const dx = b.left - r.left;
    const dy = b.top - r.top;
    if (dx || dy)
      el.animate([{ transform: `translate(${dx}px,${dy}px)` }, { transform: 'none' }], {
        duration: 280,
        easing: 'cubic-bezier(.32,.72,0,1)',
      });
  });
}
// A dropped card moves at once (position tween, FLIP) and the server's order follows; if the
// server does not confirm, the board is drawn again from its records.
function placeCard(id, to) {
  const card = document.querySelector(`.kanban .card[data-task-id="${CSS.escape(id)}"]`);
  const lane = document.querySelector(`.kanban .col-${to.priority} .cards`);
  if (!card || !lane) return;
  const before = to.beforeId
    ? lane.querySelector(`.card[data-task-id="${CSS.escape(to.beforeId)}"]`)
    : null;
  const from = card.parentElement;
  lane.querySelector(':scope > .col-empty')?.remove();
  lane.insertBefore(card, before);
  if (from && from !== lane && !from.querySelector('.card')) {
    const empty = document.createElement('li');
    empty.className = 'col-empty';
    empty.textContent = T('拖到这里', 'Drop here');
    from.append(empty);
  }
}
function moveWithUndo(a, id, to, message) {
  if (L.nativeWorkspace(a)) {
    flip(() => placeCard(id, to));
    void L.moveNativeTask(a, id, to)
      .then(() => notify(message))
      .catch((error) => {
        notify(errText(error));
        refreshWS(['stage']);
      });
    return;
  }
  let before;
  flip(() => {
    before = E.moveTask(a, id, to);
    persist();
    refreshWS(['stage', 'toolbar']);
  });
  notify(message, {
    undo: () => {
      flip(() => {
        E.restoreOrder(a, before);
        persist();
        refreshWS(['stage']);
      });
    },
  });
}
function download(data, name) {
  const blob = new Blob([typeof data === 'string' ? data : JSON.stringify(data, null, 2)], {
    type: 'application/json;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function resetAttemptUi() {
  Object.assign(ui, {
    obj: null,
    artifactId: null,
    rail: 'team',
    railTab: 'team',
    chatRole: null,
    railOpen: false,
    menu: null,
    scopeAll: false,
    benchAll: false,
    reviewFor: null,
    pendingRequestId: null,
    lastUndo: null,
    compare: false,
    editPending: null,
    lastRun: null,
    reviewTab: 'rules',
    practice: {},
  });
}
/** The starting order the person set on the brief (screens/home keeps it). Only the knowledge
 * assistant brief carries the three pickers; a variant starts with all three up next. */
function startingOrder(caseId) {
  return caseId === 'pilot' ? seedOrder() : [];
}
async function startAttempt(caseId, opts, learnerJob = 'pm') {
  if (!caseShown(caseId)) throw new Error(T('这个情境暂不开放。', 'This situation is not open.'));
  const a = await L.start(caseId, {
    ...opts,
    initialTasks: SEED_KEYS.map((key) => ({ title: seedText(key) })),
  });
  Greetings.prepareGreetings(a.id, learnerJob);
  ui.arriving = true;
  return freshAttemptUi(a);
}
// A practice this browser just took up, started here or opened with its continue code.
function freshAttemptUi(a) {
  a.selectedTaskId = null;
  a.readTurns = {};
  a.turnTimes = {};
  a.eventTimes = {};
  a.historyRead = false;
  a.turnTask = {};
  resetAttemptUi();
  persist();
  return a;
}
// A new practice lands on Grace’s commission. Cards arrive only after the person starts.
async function enterWork(fn, trigger) {
  const show = () => {
    if (sheet.open) closeSheet(true);
    ui.route = 'work';
    ui.routeId = null;
    history.pushState(null, '', hashOf('work'));
    render();
    window.scrollTo(0, 0);
  };
  if (trigger) {
    if (ui.walkIn) return;
    ui.walkIn = true;
    if (ui.route === 'pm') render();
    try {
      await fn();
      ui.arriving = false;
      resetSeedOrder();
      show();
    } finally {
      ui.walkIn = false;
    }
    return;
  }
  await fn();
  if (reduceMotion.matches) {
    show();
    fadeIn();
  } else await withTransition(show);
}
async function runQuestion(question, expectation) {
  if (ui.busy) return;
  const a = current();
  ui.busy = true;
  ui.labPrefill = '';
  refreshWS(['stage']);
  try {
    const t = task();
    const run = await L.test(a, { question, expectation, taskId: t ? t.id : null });
    ui.lastRun = run.id;
    startWorking(a, t);
    persist();
    announce(
      run.queued
        ? assistantText('assistant_mode_queued')
        : T('知识助手回答：', 'The assistant answered: ') + run.answer,
    );
  } catch (err) {
    notify(errText(err));
  } finally {
    ui.busy = false;
    if (WS.includes(ui.route) && current() === a) {
      const t = task();
      if (t) ui.obj = { task: t.id, type: 'bench' };
      refreshWS();
      document
        .getElementById('run-' + ui.lastRun)
        ?.scrollIntoView({ block: 'nearest', behavior: reduceMotion.matches ? 'auto' : 'smooth' });
    }
  }
}
async function pkgFor(a, record) {
  const t = task();
  const sc = ui.exportScope;
  if (!ui.pendingRequestId)
    ui.pendingRequestId =
      'request-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
  const scope = { record, requestId: ui.pendingRequestId };
  if (record)
    setTimeout(() => {
      ui.pendingRequestId = null;
    }, 0);
  if (!sc.artifacts) scope.artifactIds = [];
  if (!sc.materials) scope.materialIds = ['brief'];
  if (!sc.tests) scope.testIds = [];
  return L.preparePackageExact(a, t ? t.id : null, scope);
}
// Agents may answer with English purpose names; store them as the engine's values.
function normalizeImport(text) {
  try {
    const data = JSON.parse(text);
    const art = data.artifact || data;
    if (art && art.purpose) art.purpose = purposeFromLabel(art.purpose);
    return JSON.stringify(data);
  } catch (_) {
    return text;
  }
}
// What came back, where it will be filed and whether it can come in at all. The chosen
// task rides on the import button; nothing is saved until the person imports.
function returnPreviewSheet(a, data) {
  const t = task();
  const placement = returnPlacement(data, a.exports || [], a.tasks, t ? t.id : null);
  const chosen = placement.status === 'unmatched' ? '' : placement.taskId || '';
  const named = (id) => taskTitle(a.tasks.find((x) => x.id === id));
  const where =
    placement.status === 'unmatched'
      ? `<p class="warn-line" role="alert">${esc(unmatchedReturnText())}</p>`
      : placement.status === 'package'
        ? `<p class="meta">${esc(T(`放在「${named(chosen)}」下：任务包是从这件事交出的。`, `Filed under “${named(chosen)}”: the package was handed over from this task.`))}</p>`
        : `<label class="return-task"><span class="meta">${T('放在哪件事项下', 'File it under')}</span><select class="select" data-change="return-task">${chosen ? '' : `<option value="" selected>${T('选择一件事项', 'Choose a task')}</option>`}${a.tasks.map((x) => `<option value="${esc(x.id)}" ${x.id === chosen ? 'selected' : ''}>${esc(taskTitle(x))}</option>`).join('')}</select></label>`;
  const preview =
    data.kind === 'investigation'
      ? investigationPreview(data)
      : data.kind === 'test_set'
        ? testSetPreview(data, E.getMaterials(a))
        : `<article class="paper"><h3 class="paper-title">${esc(data.title)}</h3><div class="prose">${md(data.body)}</div></article>`;
  openSheet(
    T('检查带回的内容', 'Check what came back'),
    `<p class="meta">${esc(T(`来自你的 Agent，用途「${purposeLabel(data.purpose)}」`, `From your agent, purpose “${purposeLabel(data.purpose)}”`))}</p>${where}${preview}`,
    `${btn(T('返回', 'Back'), 'close', 'quiet')}<span class="spacer"></span>${placement.status === 'unmatched' ? '' : btn(T('导入为待检查作品', 'Import as “to check”'), 'confirm-import', 'primary', `data-task="${esc(chosen)}" ${chosen ? '' : 'disabled'}`)}`,
    'wide',
  );
}
function setObj(obj) {
  const t = task();
  if (!t) return;
  // Opening an object leaves any open sheet, as changing route does.
  if (sheet.open) closeSheet(true);
  commit();
  ui.obj = { task: t.id, ...obj };
  if (obj.type === 'work') ui.artifactId = obj.id;
  refreshWS(['stage', 'rail']);
  document.getElementById('ws-object')?.scrollIntoView?.({ block: 'start' });
}

async function act(el, ev = new Event('rc-action')) {
  const a = current();
  const id = el.dataset.id;
  const action = el.dataset.action;
  if (action !== 'menu' && action !== 'set-lang' && ui.menu) {
    ui.menu = null;
    if (WS.includes(ui.route)) refreshWS(['toolbar', 'stage']);
    else render();
  }
  // A line's registered handler wins; without one, carry on in the same tick (no await).
  const registered = registeredAction(action);
  if (registered) {
    await registered(el, ev);
    return;
  }
  if (nativeCiteAction(nativeCiteHost, a, action, el.dataset)) return;
  switch (action) {
    case 'investigate-run':
      await openInvestigation(id);
      break;
    case 'native-investigation-task':
      await openInvestigation(el.dataset.run, id);
      break;
    case 'investigation-retest':
      await runInvestigationBlock(id);
      break;
    case 'investigation-refresh-index': {
      if (ui.busy) break;
      commit();
      const x = artifact(),
        b = x?.blocks?.find((b) => b.id === id),
        r = b && a.tests.find((t) => t.id === b.testId);
      requireWorkMutation(a, x);
      if (
        x?.kind !== 'investigation' ||
        !x.adopted ||
        b?.type !== 'retest' ||
        !r?.citations?.some((c) => c.id === 'policy') ||
        !canWrite(a)
      )
        throw new Error(
          T(
            '这份调查当前不能刷新索引。',
            'The index cannot be refreshed from this investigation right now.',
          ),
        );
      if (x.draft || storageIssue || !persist())
        throw new Error(
          T(
            '先保存调查判断，再刷新索引。',
            'Save your investigation notes before refreshing the index.',
          ),
        );
      ui.busy = true;
      refreshWS(['stage']);
      try {
        await L.action(a, 'refresh_index');
        persist();
        notify(
          T(
            '索引已更新；可在这份调查里同题重测。',
            'Index refreshed. Rerun the question in this investigation.',
          ),
        );
      } finally {
        ui.busy = false;
        refreshWS(['stage', 'rail']);
      }
      break;
    }
    case 'investigation-mode': {
      const x = artifact();
      if (!x || x.kind !== 'investigation' || !x.blocks.some((b) => b.id === id)) break;
      const mode = el.dataset.mode;
      if (!['diff', 'original'].includes(mode)) break;
      investigationViewState(a, x).modes[id] = mode;
      refreshWS(['stage']);
      break;
    }
    case 'investigation-review-save': {
      const x = artifact();
      requireWorkMutation(a, x);
      if (x.kind !== 'investigation') break;
      commit();
      if (x.draft || !persist())
        throw new Error(
          T(
            '判断尚未保存，请保留页面并检查提示。',
            'Your notes have not been saved. Keep this page open and check the message.',
          ),
        );
      refreshWS(['stage', 'rail']);
      notify(T('你的调查判断已保存', 'Your investigation notes are saved'));
      break;
    }
    case 'investigation-load': {
      const x = artifact(),
        b = x?.blocks?.find((b) => b.id === id);
      if (b) {
        delete ui.investigationSources[investigationSourceKey(a.id, b)];
        loadInvestigationSources(a, x, id);
        refreshWS(['stage']);
      }
      break;
    }
    case 'investigation-move': {
      commit();
      const x = artifact();
      requireWorkMutation(a, x);
      const i = x.blocks.findIndex((b) => b.id === id),
        dir = Number(el.dataset.dir),
        before = dir < 0 ? x.blocks[i - 1]?.id : x.blocks[i + 2]?.id;
      if (i < 0 || i + dir < 0 || i + dir >= x.blocks.length) break;
      localWorkChange(a, () => E.moveInvestigationBlock(a, x.id, id, before));
      refreshWS(['stage']);
      announce(T('模块顺序已保存', 'Module order saved'));
      break;
    }
    case 'investigation-cite': {
      commit();
      const x = artifact(),
        r = a.tests.find((r) => r.id === id);
      requireWorkMutation(a, x);
      if (!x.adopted)
        throw new Error(
          T('先采用这份调查，再引用结果。', 'Adopt this investigation before citing results.'),
        );
      if (r) {
        E.addEvidence(a, x.id, { type: 'test', id: r.id, version: r.configVersion });
        if (!persist()) throw new Error(storageText());
        refreshWS(['stage', 'rail']);
        notify(T('这次运行已加入调查依据', 'This run is now evidence for the investigation'));
      }
      break;
    }
    case 'work-edit': {
      const x = artifact();
      requireWorkMutation(a, x);
      ui.previewWorkId = null;
      ui.editPending = x.id;
      refreshWS(['stage']);
      document.getElementById('editor-body')?.focus();
      break;
    }
    case 'work-preview':
      commit();
      ui.previewWorkId = id;
      refreshWS(['stage']);
      if (ui.kbd) document.querySelector('[data-work-mode]')?.focus({ preventScroll: true });
      break;
    case 'check-work': {
      const x = a.artifacts.find((w) => w.id === id);
      if (x) showWorkCheck(a, x);
      break;
    }
    case 'save-work': {
      const x = artifact();
      requireWorkMutation(a, x);
      commit();
      if (x.draft || !persist())
        throw new Error(
          T(
            '修改尚未保存，请保留页面并检查提示。',
            'Changes have not been saved. Keep this page open and check the message.',
          ),
        );
      refreshWS(['stage', 'rail']);
      notify(
        x.adopted
          ? T('修改已保存', 'Changes saved')
          : T('修改已保存，仍为待检查作品', 'Changes saved; still awaiting adoption'),
      );
      break;
    }
    case 'removed-works':
      commit();
      removedWorksSheet();
      break;
    case 'remove-work': {
      const x = artifact();
      requireWorkMutation(a, x);
      commit();
      if (x.draft || !persist()) throw new Error(T('请先保存修改。', 'Save your changes first.'));
      openSheet(
        T('删除这份作品？', 'Remove this work?'),
        `<p class="work-remove-title">${esc(shown(x).title)}</p><p class="work-remove-note">${T('移入“已移除作品”，随时可以恢复。原文件和已保存的测试记录会保留。', 'Move it to Removed work. You can restore it later. The original file and saved test runs are kept.')}</p>${x.adopted && sessionOf(a)?.draft.rationale ? `<p class="work-remove-note">${T('交付稿中已有文字：自动汇总会更新，手写修改会保留并提示核对；已保存的交付版本不会撤回。', 'The deliverable already has text. Generated summaries will update; edited text stays for review. Saved deliverable versions are not withdrawn.')}</p>` : ''}`,
        `${btn(T('保留', 'Keep'), 'close', 'quiet')}<span class="spacer"></span>${btn(T('删除作品', 'Remove work'), 'confirm-remove-work', 'primary', `data-id="${x.id}"`)}`,
        'narrow',
      );
      break;
    }
    case 'confirm-remove-work': {
      const x = a.artifacts.find((w) => w.id === id);
      requireWorkMutation(a, x);
      if (
        sessionOf(a)?.pending?.localRun?.workId === id ||
        sessionOf(a)?.pending?.localRun?.investigationId === id
      )
        throw new Error(
          T(
            '先确认这份作品的运行结果，再删除。',
            'Resolve this work’s pending run before removing it.',
          ),
        );
      commit();
      if (x.draft) throw new Error(T('请先保存修改。', 'Save your changes first.'));
      const before = sessionOf(a).draft.rationale;
      const selected = ui.deliverPick
        ? new Set(ui.deliverPick)
        : new Set(works(a).map((w) => w.id));
      const wasGenerated = !!before && selected.has(id) && before === rationaleFrom(a, selected);
      localWorkChange(a, () => {
        E.removeArtifact(a, id);
        if (x.adopted && before) a.deliverRemovalNotice = true;
      });
      if (wasGenerated) {
        const ss = sessionOf(a);
        if (
          L.store.update(a.id, { draft: { ...ss.draft, rationale: rationaleFrom(a, selected) } })
        ) {
          a.deliverRemovalNotice = false;
          persist();
        }
      }
      const name = shown(x).title;
      ui.artifactId = null;
      ui.previewWorkId = null;
      ui.editPending = null;
      ui.reviewFor = null;
      closeSheet(true);
      const t = task();
      if (t) ui.obj = defaultObj(a, t);
      refreshWS();
      notify(T('已移除《' + name + '》', 'Removed “' + name + '”'), {
        undo: () => restoreWork(a, id),
      });
      break;
    }
    case 'restore-work':
      await restoreWorkFromControl(a, id, el);
      break;
    case 'test-toggle': {
      commit();
      const x = artifact();
      if (!x) break;
      const open = ui.testOpen[x.id] === undefined ? null : ui.testOpen[x.id];
      ui.testOpen[x.id] = open === id ? null : id;
      refreshWS(['stage']);
      if (ui.testOpen[x.id]) animateTestReveal(id);
      break;
    }
    case 'test-run':
      await runTestCase(id);
      break;
    case 'test-mode':
      commit();
      ui.testModes[id] = el.dataset.mode;
      refreshWS(['stage']);
      animateTestReveal(id);
      break;
    case 'test-add': {
      commit();
      const x = artifact();
      if (!x || statusOf(a) !== 'active' || storageIssue) break;
      const c = E.addTestCase(a, x.id);
      ui.testOpen[x.id] = c.id;
      persist();
      refreshWS(['stage']);
      animateTestReveal(c.id);
      document.getElementById('case-question-' + c.id)?.focus({ preventScroll: true });
      break;
    }
    case 'test-remove': {
      commit();
      const x = artifact();
      if (!x || statusOf(a) !== 'active' || storageIssue) break;
      E.removeTestCase(a, x.id, id);
      ui.testOpen[x.id] = x.cases[0]?.id ?? null;
      persist();
      refreshWS(['stage']);
      notify(T('问题已移除，历史测试仍保留', 'Question removed. Its test history is kept.'), {
        undo: () => {
          if (statusOf(a) !== 'active' || storageIssue) return;
          E.restoreTestCase(a, x.id, id);
          persist();
          ui.testOpen[x.id] = id;
          refreshWS(['stage']);
        },
      });
      break;
    }
    case 'test-cite': {
      commit();
      const x = artifact(),
        run = a.tests.find((r) => r.id === id);
      if (
        !x ||
        !run ||
        run.workId !== x.id ||
        statusOf(a) !== 'active' ||
        !x.adopted ||
        storageIssue
      )
        break;
      E.addEvidence(a, x.id, { type: 'test', id: run.id, version: run.configVersion });
      if (!persist()) throw new Error(storageText());
      refreshWS(['stage', 'rail']);
      notify(T('这次运行已加入计划依据', 'This run is now evidence for the plan.'));
      break;
    }
    case 'test-ref': {
      const m = E.getMaterials(a).find((m) => m.id === id);
      if (!m)
        throw new Error(
          T('当前会话没有这份资料。', 'This document is not available in this session.'),
        );
      const v = Number(el.dataset.version);
      openSheet(
        materialTitle(m),
        `<p class="meta">${T('计划引用 v', 'Plan references v')}${v} · ${T('当前可见 v', 'Currently visible v')}${m.version}</p>${v !== m.version ? `<p class="warn-line">${T('材料已变化，下面显示当前版本。', 'The document changed. The current version is shown below.')}</p>` : ''}<div class="prose serif">${md(m.content || m.body)}</div>`,
        btn(T('好', 'OK'), 'close', 'primary'),
        'wide',
      );
      break;
    }
    case 'test-export': {
      commit();
      const x = artifact();
      if (!x) break;
      download(
        {
          schemaVersion: 1,
          returnId: 'export-' + crypto.randomUUID(),
          artifact: {
            kind: 'test_set',
            title: x.title,
            purpose: x.purpose,
            body: x.body,
            cases: x.cases.map(({ question, intent, expectation, refs }) => ({
              question,
              intent,
              expectation,
              refs,
            })),
          },
        },
        'test-plan.json',
      );
      break;
    }

    case 'home':
      go('', { transition: true });
      break;
    // Home to the brief: the page fades out, the brief rises in (screens/home).
    case 'open-career':
      await leaveForBrief();
      go('pm');
      break;
    // The engineer card: a new practice with the engineer's hat on, starting from its ticket
    // (the intro first: "same practice, second hat").
    case 'engineer-start': {
      el.disabled = true;
      el.textContent = T('正在准备委托…', 'Preparing the ticket…');
      try {
        const na = await startAttempt('pilot', {}, 'engineer');
        await keepRole(na, 'engineer');
        const ticket = await openEngineerTicket(L.gatewayTransport(na), na.id, { from: 'seeded' });
        setHat(na.id, 'engineer');
        go('engineer', {
          id: ticket.id,
          transition: true,
        });
      } finally {
        if (el.isConnected) {
          el.disabled = false;
          el.textContent = T('开始', 'Start');
        }
      }
      break;
    }
    // The same practice, the other hat: the ticket that comes with the situation.
    case 'engineer-take': {
      // The ticket that comes with the situation, only while its problem exists here (189);
      // a delivered practice opens a revision first (on the intro).
      el.disabled = true;
      try {
        await takeInPractice(a);
      } finally {
        if (el.isConnected) el.disabled = false;
      }
      break;
    }
    // The test bench: hand chosen tests to engineering and put on the engineer's hat.
    case 'engineer-handover':
      if (roleOf(a.id) === 'pm') {
        // A product manager's practice: Daniel takes the tests; his report comes back here.
        await openEngineerHandover({
          transport: L.gatewayTransport(a),
          sessionId: a.id,
          tests: a.tests
            .slice()
            .reverse()
            .map((t) => ({ id: t.id, question: t.question, answer: t.answer, stale: !!t.stale })),
          open: () => {},
          colleague: {
            taskId: routeTask(a)?.id ?? null,
            done: async (ticket) => {
              const failed = await colleagueReported(L.gatewayTransport(a), a.id, ticket, () =>
                L.load(a),
              ).catch((e) => e?.message || String(e));
              if (failed) notify(failed);
              refreshWS(['rail']);
            },
          },
        });
        break;
      }
      await openEngineerHandover({
        transport: L.gatewayTransport(a),
        sessionId: a.id,
        tests: a.tests
          .slice()
          .reverse()
          .map((t) => ({ id: t.id, question: t.question, answer: t.answer, stale: !!t.stale })),
        open: (ticketId) => navigateStage('engineer', engineerEntryId(a.id, ticketId, 'handover')),
      });
      break;
    // The practice's role did not reach the server: write it again (nothing else waits on it).
    case 'role-retry':
      if (a && ui.roleUnsaved?.id === a.id) await keepRole(a, ui.roleUnsaved.role);
      break;
    case 'set-lang':
      ui.menu = null;
      setPreference(el.dataset.lang, localStorage);
      render();
      break;
    case 'start-intake': {
      const r = ui.intake.result;
      await enterWork(() =>
        startAttempt('pilot', {
          intake: { text: r.text, fits: r.fits, gaps: r.gaps },
          priorities: startingOrder('pilot'),
        }),
      );
      break;
    }
    case 'practice-variant': {
      const caseId = el.dataset.case;
      const parent = a ? a.id : null;
      await enterWork(() => startAttempt(caseId, parent ? { parentAttemptId: parent } : undefined));
      break;
    }
    case 'close':
      closeSheet();
      break;
    case 'about':
      sheetAbout();
      break;
    case 'review-menu':
      toggleReviewMenu();
      break;
    case 'lens-toggle':
      closeMenuInPlace();
      setLens(!lensOn());
      break;
    case 'lens-switch':
      setLens(!lensOn());
      break;
    case 'lens-replay': {
      const block = document.querySelector('.sheet [data-rc-sentences]');
      if (block) playReading(block);
      break;
    }
    case 'open-lab':
      go('lab', { transition: true });
      break;
    case 'continue-code':
      await recovery.open(a);
      break;
    case 'continue-code-create':
      await recovery.create();
      break;
    case 'continue-code-copy':
      await recovery.copy();
      break;
    case 'continue-code-home':
      recovery.reveal();
      break;
    case 'export':
      download(
        storageLocked && rawRecord ? rawRecord : state,
        storageLocked && rawRecord ? 'practice-original-record.json' : 'practice-local-notes.json',
      );
      notify(T('已交给浏览器下载', 'Handed to the browser to download'));
      break;
    case 'reset-storage':
      try {
        localStorage.setItem(KEY + '.bak', rawRecord);
        storageLocked = false;
        storageIssue = '';
        rawRecord = null;
        persist();
        render();
        notify(
          T(
            '原记录已另存，可以重新开始了',
            'The original record is backed up. You can start fresh.',
          ),
        );
      } catch (_) {
        notify(T('浏览器不允许保存，没能另存', 'The browser blocked saving the backup.'));
      }
      break;
    case 'set-status': {
      if (L.nativeWorkspace(a)) {
        await L.patchNativeTask(a, id, { status: el.dataset.status });
        break;
      }
      const t = a.tasks.find((x) => x.id === id);
      if (t && t.status !== el.dataset.status) {
        E.updateTask(a, id, { status: el.dataset.status });
        persist();
        refreshWS(['stage']);
      }
      break;
    }
    case 'new-task':
      if (!canWriteBoard(a)) break;
      sheetTask();
      break;
    case 'edit-task':
      sheetTask(id);
      break;
    case 'move-task': {
      const t = a.tasks.find((x) => x.id === id);
      const i = a.tasks.indexOf(t);
      const dir = Number(el.dataset.dir);
      const target = a.tasks[i + dir];
      if (!target) {
        notify(T('已经到头了', 'Already at the end'));
        break;
      }
      closeSheet(true);
      moveWithUndo(
        a,
        id,
        dir < 0
          ? { priority: target.priority, beforeId: target.id }
          : { priority: target.priority, beforeId: a.tasks[i + 2] ? a.tasks[i + 2].id : null },
        T('已调整顺序', 'Order changed'),
      );
      break;
    }
    case 'edit-pending':
      if (
        a.artifacts.find((w) => w.id === id)?.kind === 'test_set' &&
        (statusOf(a) !== 'active' || storageIssue)
      )
        break;
      ui.editPending = id;
      refreshWS(['stage']);
      (
        document.querySelector('[data-case-field]') || document.getElementById('editor-body')
      )?.focus();
      break;
    case 'cite-pick':
      sheetCitePicker();
      break;
    case 'view-evidence': {
      const x = artifact();
      const ev =
        x && x.evidence.find((e) => e.id === id && String(e.version ?? '') === el.dataset.version);
      if (ev)
        openSheet(
          esc(evTitle(ev)),
          `<p class="meta">${T('引用时保存的内容', 'Saved when you cited it')}${ev.version ? ' · v' + esc(ev.version) : ''}</p><div class="prose serif quoteblock"${zhAttr(ev.body)}>${md(ev.body || '')}</div>`,
          btn(T('好', 'OK'), 'close', 'primary'),
          'narrow',
        );
      break;
    }
    case 'run-source': {
      const run = a.tests.find((r) => r.id === el.dataset.run);
      if (!run) break;
      const sources = await Promise.allSettled(
        run.citations.map((c) => L.citationSource(a, run.id, c.id)),
      );
      openSheet(
        T('这次回答用的来源', 'Sources behind this answer'),
        `<div class="answer">${assistantMark('sm')}<div class="answer-body">${answerModeLine(run)}${md(run.answer, { dropTitle: true })}</div></div>${run.citations
          .map((c, i) => {
            const result = sources[i].status === 'fulfilled' ? sources[i].value : null;
            const m = result?.material;
            return `<article class="paper document small"><header class="doc-head">${icon('doc', 'i-sm')}<h3 class="doc-title">${esc(materialTitle(m || { id: c.id, title: c.title }))}</h3><span class="stamp">v${c.version}</span></header>${m ? `<div class="prose serif">${md(m.content, { dropTitle: true })}</div>` : `<p class="muted">${T('本次引用 v' + c.version + '；这个版本的正文暂未取得。', 'This run cited v' + c.version + '. Its exact text is unavailable.')}</p>`}</article>`;
          })
          .join('')}`,
        btn(T('好', 'OK'), 'close', 'primary'),
        'wide',
      );
      break;
    }
    case 'run-hit': {
      const r = a.tests.find((x) => x.id === id);
      const hit = r && retrievalHit(r);
      if (!hit?.citation) break;
      const c = hit.citation;
      const result = await L.citationSource(a, r.id, c.id);
      const m = result?.material;
      const text = String(m?.content || '');
      const at = text.indexOf(hit.quote);
      const passage = at >= 0
        ? `${md(text.slice(0, at), { dropTitle: true })}<mark data-hit-target>${esc(hit.quote)}</mark>${md(text.slice(at + hit.quote.length), { dropTitle: true })}`
        : `${m ? md(text, { dropTitle: true }) : `<p>${T('这个引用版本的正文暂未取得。', 'The exact cited version is unavailable.')}</p>`}`;
      openSheet(T('本次检索原文', 'Retrieved passage'),
        `<div class="rc-moment-hit"><p class="rc-moment-hit-title">${esc(c.title || materialNameOf(a)(c.id))} · v${c.version}</p><blockquote>${esc(hit.quote)}</blockquote></div><div class="prose serif">${passage}</div>`,
        btn(T('返回测试', 'Back to the test'), 'close', 'primary'), 'wide');
      sheet.querySelector('[data-hit-target]')?.scrollIntoView({ block: 'center' });
      break;
    }
    case 'rerun': {
      const r = a.tests.find((x) => x.id === id);
      if (r) await runQuestion(r.question, r.expectation);
      break;
    }
    case 'config':
      ui.configFromTestSet =
        ['test_set', 'investigation'].includes(artifact()?.kind) && ui.obj?.type === 'work';
      closeSheet(true);
      ui.menu = null;
      sheetConfig();
      break;
    case 'resend-turn': {
      const s = sessionOf(a);
      const op = s?.failedTurn;
      if (op) {
        await L.turn(a, ROLE_OF[op.body.role_id], String(op.body.text), {
          ...(op.body.task_id !== undefined ? { task_id: op.body.task_id } : {}),
          ...(op.body.work_id !== undefined ? { work_id: op.body.work_id } : {}),
          ...(op.body.attachments ? { attachments: op.body.attachments } : {}),
        });
        L.store.update(a.id, { failedTurn: undefined });
        refreshWS(['rail']);
      }
      break;
    }
    case 'discuss-run': {
      const r = a.tests.find((x) => x.id === id);
      if (r && L.nativeWorkspace(a)) {
        ui.chatQuotes[quoteKey(a, 'technical')] = testQuote(r);
        openChat('technical');
        break;
      }
      openChat(
        'technical',
        T(
          `我测了“${r.question}”，助手答“${quotedAnswer(r, answerText(r.answer).slice(0, 300))}”（政策源 v${r.policyVersion}，索引 v${r.indexVersion}）。我想确认：`,
          `I asked “${r.question}” and the assistant said “${quotedAnswer(r, answerText(r.answer).slice(0, 300))}” (policy v${r.policyVersion}, index v${r.indexVersion}). I want to check: `,
        ),
      );
      break;
    }
    case 'v4-new-practice': {
      if (sheet.open) closeSheet(true);
      go('pm');
      break;
    }
    case 'v4-feedback': {
      closeSheet(true);
      go('review');
      break;
    }
    case 'prefill-artifact': {
      if (L.nativeWorkspace(a)) {
        const sharing = document.querySelector('[data-v4-insertion=sharing]');
        sharing?.scrollIntoView({ block: 'nearest' });
        sharing?.querySelector('select,button')?.focus();
        notify(
          T(
            '在作品下方选好版本和同事后分享，对方看到的是这一确切版本。',
            'Choose a version and colleague below the work to share it. They will see this exact version.',
          ),
        );
        break;
      }
      const x = artifact();
      const input = document.getElementById('chat-input');
      if (input && x) {
        if (!attachToTurn(a, { type: 'work', id: x.id, version: x.revision })) break;
        const v = shown(x);
        input.value =
          T(
            `这是我的「${v.title}」：\n${v.body.slice(0, 1500)}\n\n`,
            `Here is my “${v.title}”:\n${v.body.slice(0, 1500)}\n\n`,
          ) + input.value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
      }
      break;
    }
    case 'prefill-run': {
      if (L.nativeWorkspace(a)) {
        const r = a.tests.at(-1);
        if (r && ui.chatRole) {
          ui.chatQuotes[quoteKey(a, ui.chatRole)] = testQuote(r);
          refreshWS(['rail']);
          document.getElementById('chat-input')?.focus();
        }
        break;
      }
      const r = a.tests.at(-1);
      const input = document.getElementById('chat-input');
      if (input && r) {
        if (!attachToTurn(a, { type: 'test', id: r.id, version: r.configVersion })) break;
        input.value =
          T(
            `最近一次测试：“${r.question}” → “${answerText(r.answer).slice(0, 300)}”。`,
            `Latest test: “${r.question}” → “${answerText(r.answer).slice(0, 300)}”. `,
          ) + input.value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
      }
      break;
    }
    case 'package': {
      const pkg = await pkgFor(a, false);
      openSheet(
        T('任务包', 'Task package'),
        `<p class="meta">${T('这是会交给你的 Agent 的内容，不含任何连接凭据。', 'This is what your agent receives. It contains no credentials.')}</p><label class="sr-only" for="package-text">${T('任务包内容', 'Package content')}</label><textarea id="package-text" class="textarea mono" rows="16" readonly>${esc(JSON.stringify(pkg, null, 2))}</textarea>`,
        `${btn(T('关闭', 'Close'), 'close', 'quiet')}<span class="spacer"></span>${btn(T('复制并记为已导出', 'Copy and mark as handed over'), 'copy-package', 'primary')}`,
        'wide',
      );
      break;
    }
    case 'copy-package': {
      const pkg = await pkgFor(a, true);
      persist();
      closeSheet(true);
      try {
        await navigator.clipboard.writeText(JSON.stringify(pkg, null, 2));
        notify(T('任务包已复制，记为已导出', 'Package copied and marked as handed over'));
      } catch (_) {
        notify(copyBlockedText());
      }
      refreshWS(['rail']);
      break;
    }
    case 'download-package':
      download(await pkgFor(a, true), 'practice-task.json');
      persist();
      notify(T('任务包已交给浏览器下载', 'Package handed to the browser to download'));
      refreshWS(['rail']);
      break;
    case 'submit':
      commit();
      sheetDeliver();
      break;
    case 'live-refresh':
      await L.refresh(a);
      refreshChrome();
      notify(
        snap().connected
          ? T('已连接', 'Connected')
          : T('还是连不上后端', 'Still cannot reach the server'),
      );
      break;
    case 'live-retry': {
      const meta = sessionOf(a)?.pending?.localRun;
      await L.retry(a);
      if (meta?.investigationId && meta?.blockId) {
        if (snap().error) ui.investigationErrors[meta.blockId] = snap().error;
        else if (!sessionOf(a)?.pending) delete ui.investigationErrors[meta.blockId];
      }
      if (meta?.caseId) {
        ui.testOpen[meta.workId] = meta.caseId;
        ui.testModes[meta.caseId] = 'result';
        if (snap().error) ui.testErrors[meta.caseId] = snap().error;
        else if (!sessionOf(a)?.pending) {
          delete ui.testErrors[meta.caseId];
          const restored = a.tests.find((r) => r.requestId === meta.requestId);
          if (restored) ui.testHistory[meta.caseId] = restored.id;
        }
      }
      refreshChrome();
      if (meta?.caseId || meta?.investigationId) refreshWS(['stage']);
      break;
    }
    case 'live-session': {
      closeSheet(true);
      if (statusOf(a) === 'submitted') {
        go('review');
        break;
      }
      await L.action(a, statusOf(a) === 'paused' ? 'resume' : 'pause');
      refreshWS();
      break;
    }
    case 'live-approval':
      try {
        await L.perform(a, () => L.store.approval(el.dataset.id));
      } finally {
        sheetResources();
        refreshWS();
      }
      break;
    case 'live-collect': {
      a.deliverRemovalNotice = false;
      persist();
      commit();
      const f = document.getElementById('live-deliver');
      if (f) saveDraftFields(a, f);
      deliverPick(a);
      L.store.update(a.id, {
        draft: { ...sessionOf(a).draft, rationale: rationaleFrom(a, ui.deliverPick) },
      });
      sheetDeliver();
      break;
    }
    case 'live-save': {
      const f = document.getElementById('live-deliver');
      if (f) saveDraftFields(a, f);
      await L.save(a, sessionOf(a).draft);
      sheetDeliver();
      notify(T('交付稿已保存', 'Deliverable saved'));
      break;
    }
    case 'live-submit': {
      await L.submit(a);
      if (!L.store.submissionId(sessionOf(a)))
        throw new Error(T('还没得到提交确认。', 'The submission has not been confirmed yet.'));
      a.submittedAt = sessionOf(a).submission?.created_at || new Date().toISOString();
      ui.justSubmitted = a.id;
      persist();
      closeSheet(true);
      go('review', { transition: true });
      await L.feedback(a);
      render();
      break;
    }
    case 'review-works':
      sheetDeliver(true);
      break;
    case 'live-feedback':
      dismissToasts();
      await L.feedback(a, el.dataset.retry === 'true');
      render();
      break;
    case 'live-evidence': {
      const value = await L.evidence(a, el.dataset.criterion, id);
      openSheet(
        esc(evidenceLabel(a, sessionOf(a).feedback, id)),
        evidenceView(a, value),
        btn(T('好', 'OK'), 'close', 'primary'),
        'narrow',
      );
      break;
    }
    case 'live-timeline': {
      ui.menu = null;
      await L.store.sync(a.id);
      const events = sessionOf(a).timeline.events.slice().reverse();
      openSheet(
        T('过程记录', 'Activity log'),
        `<ol class="log-list">${
          events
            .map((e) => {
              const l = eventLine(
                a,
                {
                  server: true,
                  type: e.event_type,
                  detail: { ...e.payload, materialId: e.payload.material_id },
                  refs: e.refs,
                  agent: e.executor_kind === 'external_agent',
                  seq: e.seq,
                  actor: e.actor_id,
                },
                workLang(a),
              );
              return `<li>${icon(l.icon || 'info', 'i-sm')}<span class="grow">${esc(l.text)}</span><span class="meta">#${e.seq}</span></li>`;
            })
            .join('') || `<li class="muted">${T('还没有记录。', 'Nothing yet.')}</li>`
        }</ol>`,
        `${btn(icon('back', 'i-sm') + T('关于这个工作台', 'About this workspace'), 'about', 'quiet')}<span class="spacer"></span>${btn(T('好', 'OK'), 'close', 'primary')}`,
        'narrow',
      );
      break;
    }
    case 'take-case': {
      const caseId = el.dataset.case;
      const triage = startingOrder(caseId);
      await enterWork(async () => {
        const na = await startAttempt(caseId, { priorities: triage });
        if (L.nativeWorkspace(na)) await keepRole(na, 'pm');
        if (!L.nativeWorkspace(na))
          triage.forEach((p, i) => {
            if (na.tasks[i] && p !== na.tasks[i].priority)
              E.updateTask(na, na.tasks[i].id, { priority: p });
          });
        const order = { first: 0, next: 1, later: 2 };
        na.tasks.sort((x, y) => order[x.priority] - order[y.priority]);
        persist();
      }, el.closest('.hm-brief') ? el : null);
      break;
    }
    case 'menu': {
      const m = el.dataset.menu;
      if (m === 'rank' && !canWriteBoard(a)) break;
      // On the result page ⋯ opens in place (a redraw would remount the feedback): its
      // language and model rows swap the menu for their panel there too.
      const inPlace = el.closest('[data-review-menu]');
      if (inPlace && (m === 'lang' || m === 'model')) {
        const status = modelStatusOf(a);
        inPlace.querySelector('.menu')?.remove();
        inPlace.insertAdjacentHTML(
          'beforeend',
          m === 'lang'
            ? langMenu()
            : status
              ? `<div class="menu right">${modelPopoverHtml(status)}</div>`
              : '',
        );
        if (ui.kbd) inPlace.querySelector('.menu button')?.focus();
        break;
      }
      ui.menu = ui.menu === m ? null : m;
      if (WS.includes(ui.route)) refreshWS(['toolbar', 'stage']);
      else render();
      if (ui.kbd) document.querySelector('.menu button, .popover .btn')?.focus();
      break;
    }
    case 'resume':
      await L.refresh(a);
      resetAttemptUi();
      go('work', { transition: true });
      break;
    case 'resume-attempt':
      commit();
      state.activeId = id;
      L.select(current());
      await L.refresh(current());
      resetAttemptUi();
      persist();
      go('work', { transition: true });
      break;
    case 'review-attempt':
      commit();
      state.activeId = id;
      L.select(current());
      await L.refresh(current());
      resetAttemptUi();
      persist();
      go('review', { transition: true });
      break;
    case 'to-entry':
      go('pm', { transition: true });
      break;
    case 'to-workbench':
      toWorkbench();
      break;
    case 'to-board':
    case 'to-work':
      go('work', { transition: true });
      break;
    case 'to-review':
      go('review', { transition: true });
      break;
    case 'revise-note-ok':
      if (a.revisionGuide) a.revisionGuide.dismissed = true;
      persist();
      refreshWS(['stage']);
      break;
    case 'review-practice': {
      // The results cover's "practise" step: bring the optional practice into view.
      const choice = document.querySelector(
        '[data-v4-practice] [data-action="practice-choose"], [data-v4-practice] button',
      );
      const column = document.querySelector('[data-v4-practice]');
      column?.scrollIntoView({
        block: 'nearest',
        behavior: reduceMotion.matches ? 'auto' : 'smooth',
      });
      (choice || column)?.focus?.({ preventScroll: true });
      break;
    }
    // The hat switch (topbar, or ⋯ at phone width). The engineer's side opens the desk's
    // ticket from before, or the one that comes with the situation.
    case 'hat-switch': {
      if (!a) break;
      const to = el.dataset.hat === 'engineer' ? 'engineer' : 'pm';
      // No page-wide view transition: the bar stays put and its thumb slides; only the main
      // screen changes.
      if (to === 'pm') {
        setHat(a.id, 'pm');
        go('work');
        break;
      }
      let ticket = lastTicket(a.id);
      if (!ticket) {
        try {
          ticket = (await openEngineerTicket(L.gatewayTransport(a), a.id, { from: 'seeded' })).id;
        } catch (err) {
          // Only reached when the engineer line's own hat-switch is absent or failed. A delivered
          // practice offers a revision (wording from 201); the key runs hat-switch again.
          if (statusOf(a) === 'submitted') {
            const refused = new Error(
              T(
                '这一局已经交付。要接手工程委托，先开一轮修订：你的交付和反馈都保留。',
                'This practice is delivered. Open a revision to take the engineering ticket; your delivery and feedback stay.',
              ),
            );
            refused.toastAction = {
              label: T('开始修订', 'Open a revision'),
              action: 'hat-switch',
              data: { hat: 'engineer' },
            };
            throw refused;
          }
          throw new Error(
            err?.message || T('委托没能打开，再试一次。', 'The ticket did not open. Try again.'),
          );
        }
        setLastTicket(a.id, ticket);
      }
      setHat(a.id, 'engineer');
      go('engineer', { id: ticket });
      break;
    }
    // A step on the product manager's scale opens that step's screen, read only where it is not
    // the current one: Investigate the findings dossier, Decide the board, Delivered the result
    // (before submitting, a line saying so).
    case 'stage-pm': {
      if (!a) break;
      const step = el.dataset.step;
      if (step === 'delivered') {
        if (statusOf(a) === 'submitted') {
          keepBoardPlace();
          go('review', { transition: true });
        }
        // What to do next, by where the practice stands.
        else
          notify(
            pmCurrent(a) === 'decide'
              ? T(
                  '交付以后这里是结果。准备好了就点右上角「交付」。',
                  'Your result shows here once you submit. When you are ready, use Submit at the top right.',
                )
              : T(
                  '交付以后这里是结果。先写一份作品草稿，再点右上角「交付」。',
                  'Your result shows here once you submit. Draft your work first, then use Submit at the top right.',
                ),
          );
      } else if (step === 'investigate') {
        if (ui.route !== 'investigate') {
          keepBoardPlace();
          switchStage(() => go('investigate'));
        }
      } else if (ui.route !== 'work') goBoard();
      break;
    }
    // Back to the current step's own screen: the result once delivered, else the board.
    case 'stage-back':
      if (!a) break;
      if (statusOf(a) === 'submitted') go('review', { transition: true });
      else goBoard();
      break;
    // The agent lamp: the My agent screen once the agent line registers it; until then the
    // rail's agent tab.
    case 'open-agent':
      if (isRegisteredRoute('agent')) go('agent', { transition: true });
      else {
        if (!WS.includes(ui.route)) go('work');
        ui.railTab = 'agent';
        ui.rail = 'team';
        if (narrowRail()) ui.railOpen = true;
        refreshWS(['rail', 'toolbar']);
      }
      break;
    // ⏱ The record. The board line registers its drawer under the same name (and wins); this is
    // the rail's record tab until then.
    case 'records':
      if (!WS.includes(ui.route)) go('work');
      ui.railTab = 'activity';
      ui.rail = 'team';
      if (narrowRail()) ui.railOpen = true;
      refreshWS(['rail', 'toolbar']);
      break;
    case 'open-rail':
      ui.railOpen = true;
      refreshWS(['toolbar', 'rail']);
      if (ui.kbd) document.querySelector('#ws-rail button')?.focus();
      break;
    case 'close-panels':
      ui.railOpen = false;
      refreshWS(['toolbar']);
      break;
    case 'rail':
      if (ui.rail === 'chat' && el.dataset.rail === 'team') Board.railPush('back');
      ui.railTab = 'team';
      ui.rail = el.dataset.rail;
      if (narrowRail()) ui.railOpen = true;
      refreshWS(['rail']);
      break;
    case 'rail-tab':
      ui.railTab = el.dataset.tab;
      if (el.dataset.tab !== 'team') ui.rail = 'team';
      if (narrowRail()) ui.railOpen = true;
      refreshWS(['rail', 'toolbar']);
      break;
    case 'scope':
      ui.scopeAll = el.dataset.all === '1';
      refreshWS(['rail']);
      break;
    case 'bench-scope':
      ui.benchAll = el.dataset.all === '1';
      refreshWS(['stage']);
      break;
    case 'open-task':
      openTask(id);
      break;
    case 'obj':
      if (el.dataset.type === 'doc') {
        commit();
        await openMaterial(el.dataset.id);
      } else setObj({ type: el.dataset.type, id: el.dataset.id });
      break;
    case 'open-doc':
    case 'open-material':
      await openMaterial(id, el.dataset.compare === '1');
      break;
    case 'open-bench': {
      const t = task();
      if (t) setObj({ type: 'bench' });
      else go('bench', { transition: true });
      break;
    }
    case 'pick-doc': {
      const docs = E.getMaterials(a);
      openSheet(
        T('打开一份资料', 'Open a document'),
        `<div class="pick-list">${docs.map((m) => `<button type="button" class="pick-row" data-action="open-doc" data-id="${esc(m.id)}">${icon('doc', 'i-sm')}<span class="grow">${esc(materialTitle(m))}</span><span class="ver">v${m.version}</span></button>`).join('')}</div>`,
        '',
        'narrow',
      );
      break;
    }
    case 'toggle-done': {
      if (L.nativeWorkspace(a)) {
        const row = a.tasks.find((t) => t.id === id);
        if (row)
          await L.patchNativeTask(a, id, { status: row.status === 'done' ? 'open' : 'done' });
        break;
      }
      const t = a.tasks.find((x) => x.id === id);
      if (!t) break;
      const before = t.status;
      const next = before === 'done' ? 'open' : 'done';
      E.updateTask(a, id, { status: next });
      persist();
      refreshWS(['stage']);
      notify(
        next === 'done'
          ? T('「' + taskTitle(t) + '」已处理', '“' + taskTitle(t) + '” is done')
          : T('「' + taskTitle(t) + '」重新打开', '“' + taskTitle(t) + '” reopened'),
        {
          undo: () => {
            E.updateTask(a, id, { status: before });
            persist();
            refreshWS(['stage']);
          },
        },
      );
      break;
    }
    case 'ask-priority':
      if (!canWriteBoard(a)) break;
      openChat(el.dataset.role, priorityQuestion(a));
      break;
    case 'situation-task': {
      if (ui.busy || !canWrite(a)) break;
      const version = a.world.policyVersion;
      const situation = situationTask();
      const route = location.hash;
      ui.busy = true;
      try {
        let taskId;
        if (L.nativeWorkspace(a)) {
          taskId = await L.createNativeTask(a, {
            title: situation.title,
            goal: situation.note,
            priority: 1,
          });
        } else {
          const item = E.addTask(a, {
            title: situation.title,
            note: situation.note,
            priority: 'next',
          });
          item.origin = 'situation';
          taskId = item.id;
        }
        a.acks = [...(a.acks || []), `policy-v${version}`];
        persist();
        if (current() === a && location.hash === route) openTask(taskId);
      } finally {
        ui.busy = false;
      }
      break;
    }
    case 'ack':
      a.acks = [...new Set([...(a.acks || []), el.dataset.key])];
      persist();
      refreshWS(['stage', 'rail', 'toolbar']);
      break;
    case 'reply-note': {
      const n = (ui.notesCache || []).find((x) => x.key === el.dataset.key);
      if (!n) break;
      a.acks = [...new Set([...(a.acks || []), 'note:' + n.key])];
      persist();
      openChat(
        n.role,
        T(
          `关于你说的“${n.text.slice(0, 60)}${n.text.length > 60 ? '…' : ''}”：`,
          `About what you said (“${n.text.slice(0, 60)}${n.text.length > 60 ? '…' : ''}”): `,
        ),
      );
      break;
    }
    case 'new-artifact':
      sheetNewArtifact();
      break;
    case 'open-artifact': {
      const x = a.artifacts.find((y) => y.id === id);
      if (!x) break;
      if (x.removedAt) {
        removedWorksSheet(x.taskId);
        break;
      }
      if (task() && task().id === x.taskId) setObj({ type: 'work', id });
      else openTask(x.taskId, { type: 'work', id });
      break;
    }
    case 'adopt': {
      if (L.nativeWorkspace(a)) {
        // Adoption can finish after the person opens another sheet (for example a version
        // check). Only dismiss the sheet that initiated this adoption.
        const adoptionSheet = sheet.open ? sheet.firstElementChild : null;
        await L.adoptNative(a, id);
        if (adoptionSheet && sheet.open && sheet.firstElementChild === adoptionSheet)
          closeSheet(true);
        refreshWS();
        notify(
          T(
            '已采用。里面的结论仍要你检查和验证。',
            'Adopted. Its claims still need your checking.',
          ),
        );
        break;
      }
      const x = a.artifacts.find((w) => w.id === id);
      requireWorkMutation(a, x);
      commit();
      if (x.draft) throw new Error(T('请先保存修改。', 'Save your changes first.'));
      if (x?.kind === 'test_set' && (statusOf(a) !== 'active' || storageIssue))
        throw new Error(T('这份计划当前只读。', 'This plan is read-only.'));
      E.adoptArtifact(a, id);
      persist();
      refreshWS();
      notify(
        T('已采用。里面的结论仍要你检查和验证。', 'Adopted. Its claims still need your checking.'),
      );
      break;
    }
    case 'toggle-compare':
      ui.compare = !ui.compare;
      refreshWS(['stage']);
      break;
    case 'cite-material': {
      const m = E.getMaterials(a).find((x) => x.id === id);
      if (m) cite({ id: m.id, title: m.title, version: m.version, body: m.body, type: 'material' });
      refreshWS(['stage']);
      break;
    }
    case 'cite-hit': {
      const r = a.tests.find((x) => x.id === id);
      const hit = r && retrievalHit(r);
      if (hit?.citation && L.nativeWorkspace(a)) {
        const work = nativeCiteHost.open() || nativeCiteHost.newest(a);
        if (!work) { notify(T('先在这件事里写一份作品，再引用依据。', 'Write a piece of work for this task first, then cite evidence.')); break; }
        const c = hit.citation;
        const accepted = await nativeCiteHost.cite(a, work, { session_id: a.id, kind: 'material', object_id: c.id, version: c.version });
        if (accepted) { nativeCiteHost.show(work); notify(T('依据已加入草稿，保存这版后生效。', 'Evidence added to your draft. Save this version to keep it.')); }
        break;
      }
      if (hit?.citation) cite({ id: hit.citation.id, title: hit.citation.title, version: hit.citation.version, body: hit.quote, type: 'material' });
      refreshWS(['stage']);
      break;
    }
    case 'cite-run': {
      const r = a.tests.find((x) => x.id === id);
      if (r)
        cite({
          id: r.id,
          title: r.question,
          version: r.configVersion,
          body: r.answer,
          type: 'test',
        });
      refreshWS(['stage']);
      break;
    }
    case 'cite-into': {
      const ev = ui.pendingCite;
      ui.pendingCite = null;
      closeSheet(true);
      openTask(id);
      if (ev) setTimeout(() => cite(ev), 0);
      break;
    }
    case 'open-run': {
      const r = a.tests.find((x) => x.id === id);
      ui.lastRun = id;
      if (r && r.taskId && (!task() || task().id !== r.taskId))
        openTask(r.taskId, { type: 'bench' });
      else if (task()) setObj({ type: 'bench' });
      else if (ui.route !== 'bench') go('bench');
      else refreshWS(['stage']);
      setTimeout(
        () =>
          document.getElementById('run-' + id)?.scrollIntoView({
            block: 'center',
            behavior: reduceMotion.matches ? 'auto' : 'smooth',
          }),
        80,
      );
      break;
    }
    case 'refresh-index':
      await L.action(a, 'refresh_index');
      persist();
      refreshWS();
      notify(
        T(
          '索引已更新到 v' + a.world.indexVersion + '，可以同题重测比较。',
          'Index refreshed to v' +
            a.world.indexVersion +
            '. Run the same question again to compare.',
        ),
      );
      break;
    case 'resources':
      closeSheet(true);
      ui.menu = null;
      if (WS.includes(ui.route)) refreshWS(['toolbar']);
      sheetResources();
      break;
    case 'greet-dismiss':
      Greetings.dismissGreetings(a.id);
      break;
    case 'greet-chat':
      Greetings.showIntroduction(a.id, el.dataset.role);
      openChat(el.dataset.role);
      {
        const slot = document.querySelector('[data-chat-greeting]');
        if (slot)
          slot.innerHTML = Greetings.introductionHtml(
            a.id,
            hatHere(a) === 'engineer' ? 'engineer' : 'pm',
            el.dataset.role,
            locale(),
            true,
            canWrite(a),
          );
      }
      break;
    case 'greet-ask': {
      const person = el.dataset.role;
      await Greetings.askGreeting(
        a.id,
        hatHere(a) === 'engineer' ? 'engineer' : 'pm',
        person,
        Number(el.dataset.question),
        locale(),
        (question) => askColleague(a, person, question),
      );
      break;
    }
    case 'chat':
      if (ui.rail !== 'chat' || ui.railTab !== 'team') Board.railPush('in');
      openChat(el.dataset.role);
      break;
    case 'preview-work':
      previewWork(a, id);
      break;
    case 'practice-reload':
      delete ui.practice[a.id];
      await loadPractice(a, true);
      break;
    case 'practice-choose':
      await choosePractice(a, 'choose', el.dataset.option);
      break;
    case 'practice-choose-other':
      await choosePractice(a, 'choose_other', el.dataset.option);
      break;
    case 'practice-note': {
      // Toggled in place, so focus stays on the ⓘ; the choice survives the next redraw.
      ui.practiceNote = ui.practiceNote === a.id ? null : a.id;
      const open = ui.practiceNote === a.id;
      el.setAttribute('aria-expanded', String(open));
      const body = document.getElementById(el.getAttribute('aria-controls'));
      if (body) body.hidden = !open;
      break;
    }
    case 'practice-browse': {
      ui.practiceBrowse = ui.practiceBrowse === a.id ? null : a.id;
      const box = document.querySelector('[data-v4-practice]');
      if (box) box.innerHTML = practiceSection(a);
      break;
    }
    case 'practice-resume': {
      const r = a.practiceRequest;
      if (r) await choosePractice(a, r.choice, r.optionId);
      break;
    }
    case 'practice-decline':
      await choosePractice(a, 'decline', null);
      break;
    case 'practice-continue':
      await choosePractice(a, 'continue_revision', null);
      break;
    case 'aipm-prd-toggle': {
      const prd = Aipm.prdOf(a),
        role = el.dataset.role;
      if (prd) prdChoice.set(`${a.id}:${role}:${prd.version}`, !prdAttached(a, role, prd));
      refreshWS(['rail']);
      break;
    }
    case 'aipm-detail-insert': {
      const key = `${a.id}:${el.dataset.role}`,
        detail = reviewDetails.get(key),
        input = document.getElementById('chat-input');
      reviewDetails.delete(key);
      if (detail && input) {
        input.value = `${input.value.trimEnd()}\n\n${detail}`;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
      }
      el.remove();
      break;
    }
    case 'drop-quote': {
      if (ui.chatRole) delete ui.chatQuotes[quoteKey(a, ui.chatRole)];
      refreshWS(['rail']);
      document.getElementById('chat-input')?.focus();
      break;
    }
    case 'discuss-artifact': {
      const x = artifact();
      closeSheet(true);
      const v = x && shown(x);
      openChat(
        x && E.intentOf(v.purpose) === 'commit' ? 'manager' : 'business',
        v
          ? T(
              `这是我的「${v.title}」（${purposeLabel(v.purpose)}）：\n${v.body.slice(0, 1500)}\n\n想请你看看：`,
              `Here is my “${v.title}” (${purposeLabel(v.purpose)}):\n${v.body.slice(0, 1500)}\n\nCould you look at: `,
            )
          : '',
      );
      break;
    }
    case 'discuss-material': {
      const m = E.getMaterials(a).find((x) => x.id === id);
      const role = el.dataset.role || whoHas(m)[0] || Board.docOwner(m.id);
      Board.railPush('in');
      openChat(
        role,
        T(
          `我在看《${materialTitle(m)}》v${m.version}，想确认：`,
          `I am reading “${materialTitle(m)}” v${m.version}. I want to check: `,
        ),
      );
      break;
    }
    case 'agent':
      ui.railTab = 'agent';
      if (narrowRail()) ui.railOpen = true;
      refreshWS(['rail', 'toolbar']);
      break;
    case 'request-review': {
      if (L.nativeWorkspace(a)) {
        ui.reviewFor = artifact()?.id || true;
        ui.railTab = 'feedback';
        if (narrowRail()) ui.railOpen = true;
        refreshWS(['rail']);
        break;
      }
      const x = artifact();
      if (!x) {
        ui.railTab = 'feedback';
        refreshWS(['rail']);
        break;
      }
      commit();
      E.log(a, 'review_requested', '请求评审', { artifactId: x.id });
      ui.reviewFor = x.id;
      ui.railTab = 'feedback';
      ui.scopeAll = false;
      persist();
      if (narrowRail()) ui.railOpen = true;
      refreshWS(['rail', 'toolbar']);
      notify(
        T(
          '已对照记录整理反馈，见右侧“反馈”',
          'Feedback drawn from the record is in the Feedback tab',
        ),
        { toast: true },
      );
      break;
    }
    case 'fb-act': {
      const kind = el.dataset.act;
      const tid = el.dataset.task;
      closeSheet(true);
      if (kind === 'chat') {
        openChat(el.dataset.role);
        break;
      }
      if (kind === 'rerun') {
        const r = a.tests.find((x) => x.id === id);
        ui.labPrefill = r ? r.question : '';
        if (tid) openTask(tid, { type: 'bench' });
        else go('bench');
        break;
      }
      if (kind === 'lab') {
        if (tid) openTask(tid, { type: 'bench' });
        else if (task()) setObj({ type: 'bench' });
        else go('bench');
        break;
      }
      if (kind === 'config') {
        sheetConfig();
        break;
      }
      if (kind === 'resources') {
        sheetResources();
        break;
      }
      if (kind === 'material') {
        if (ui.route === 'review') go('work');
        await openMaterial(el.dataset.id);
        break;
      }
      if (kind === 'open-artifact') {
        const x = a.artifacts.find((y) => y.id === id);
        if (x?.removedAt) removedWorksSheet(x.taskId);
        else if (x) openTask(x.taskId, { type: 'work', id });
        break;
      }
      if (kind === 'new-decision') {
        const t = a.tasks.find((x) => x.seed === 'decision') || a.tasks[0];
        openTask(t.id, { type: 'start' });
        setTimeout(() => sheetNewArtifact('试点决定'), 60);
        break;
      }
      break;
    }
    case 'dispute':
      ui.disputeOpen = ui.disputeOpen === el.dataset.key ? null : el.dataset.key;
      if (ui.route === 'review') render();
      else refreshWS(['rail']);
      document.querySelector('.dispute textarea')?.focus();
      break;
    case 'review-tab':
      ui.reviewTab = el.dataset.tab;
      render();
      break;
    case 'confirm-import': {
      try {
        const t = task();
        const parsed = E.validateImported(normalizeImport(importDraft(a)));
        if (statusOf(a) !== 'active' || storageIssue || snap().storageError)
          throw new Error(
            T(
              '这次练习只读或存储不可用，不能导入新作品。',
              'This practice is read-only or storage is unavailable. New work cannot be imported.',
            ),
          );
        // The task chosen in the preview, or the one its package belongs to.
        const target = el.dataset.task || null;
        if (L.nativeWorkspace(a)) {
          const saved = await L.importNativeReturn(a, normalizeImport(importDraft(a)), target);
          persist();
          closeSheet(true);
          if (saved.duplicate) {
            if (saved.removed) {
              removedWorksSheet();
              notify(
                T(
                  '这份回传已经移除，可以在这里恢复。',
                  'This return was removed. Restore it here.',
                ),
                { toast: true },
              );
            } else {
              openTask(saved.taskId, { type: 'work', id: saved.productId });
              notify(T('这份回传已经导入过了', 'This return was already imported'));
            }
            break;
          }
          setImportDraft(a, '');
          openTask(saved.taskId, { type: 'work', id: saved.productId });
          notify(
            T(
              '已保存为待检查作品；检查后再决定是否采用。',
              'Saved as work to check. Check it before you adopt it.',
            ),
          );
          break;
        }
        const res = E.importReturn(a, normalizeImport(importDraft(a)), target);
        if (res.duplicate) {
          if (res.removed) {
            closeSheet(true);
            removedWorksSheet();
            notify(
              T('这份回传已经移除，可以在这里恢复。', 'This return was removed. Restore it here.'),
              { toast: true },
            );
          } else notify(T('这份回传已经导入过了', 'This return was already imported'));
          break;
        }
        if (!res.artifact.taskId) res.artifact.taskId = (t || a.tasks[0]).id;
        startWorking(
          a,
          a.tasks.find((x) => x.id === res.artifact.taskId),
        );
        if (res.artifact.title === '外部 Agent 回传作品')
          res.artifact.title = T('外部 Agent 回传作品', 'Returned by my agent');
        setImportDraft(a, '');
        persist();
        closeSheet();
        openTask(res.artifact.taskId, { type: 'work', id: res.artifact.id });
        notify(T('收到了，先检查再决定是否采用', 'Received. Check it before you adopt it.'));
      } catch (err) {
        notify(errText(err));
      }
      break;
    }
  }
}
function saveDraftFields(a, form) {
  const draft = { ...sessionOf(a).draft };
  FIELDS.forEach((k) => {
    const el = form.elements[k];
    if (el) draft[k] = el.value;
  });
  L.store.update(a.id, { draft });
}
// Evidence as the reviewer saw it, rendered by kind rather than as raw JSON.
function evidenceView(a, value) {
  const v = value && typeof value === 'object' ? value : {};
  const c = v.content;
  const at =
    v.observed_at_seq != null
      ? `<p class="meta">${T('截至事件 #' + v.observed_at_seq, 'As of event #' + v.observed_at_seq)}</p>`
      : '';
  const kv = (rows) =>
    `<dl class="kv">${rows
      .filter((r) => r[1] !== undefined && r[1] !== '')
      .map(([k, x]) => `<div><dt>${k}</dt><dd${zhAttr(String(x))}>${esc(String(x))}</dd></div>`)
      .join('')}</dl>`;
  if (v.kind === 'config' && c && c.pilot) {
    const p = L.fromPilot(c.pilot);
    return (
      at +
      kv([
        [T('试点人数', 'Users'), p.participants],
        [T('开放的知识', 'Knowledge'), p.domains.map(DOMAIN).join(' + ') || '—'],
        [T('更新方式', 'Updates'), UPDATE(p.update)],
        [T('兜底', 'Fallback'), FALLBACK(p.fallback)],
        [T('开发', 'Engineering'), p.workItems.map(WORK_ITEM).join(T('、', ', ')) || '—'],
        [T('计划上线日', 'Launch day'), p.launchDay],
      ])
    );
  }
  if (v.kind === 'artifact' && c && c.content)
    return (
      at +
      `<article class="paper deliverable small">${FIELDS.map((k) => `<section class="field-doc"><h3>${FIELD(k)}</h3>${c.content[k] ? `<div class="prose serif"${zhAttr(c.content[k])}>${md(c.content[k])}</div>` : `<p class="muted">${T('（空）', '(empty)')}</p>`}</section>`).join('')}</article>`
    );
  if (v.kind === 'event' && c) {
    const res = c.resources || {};
    const rules = c.applied_rules || [];
    const ruleName = (r) =>
      ({
        policy_updated: T('政策已更新', 'Policy updated'),
        capacity_approved: T('扩容已批准', 'More seats approved'),
        resources_approved: T('资源已批准', 'Resources approved'),
      })[r] || r;
    return (
      at +
      kv([
        [T('容量', 'Capacity'), res.capacity],
        [T('开发人日', 'Person-days'), res.dev_days],
        [
          T('上线期限', 'Deadline'),
          res.deadline_day != null
            ? T('第 ' + res.deadline_day + ' 天', 'Day ' + res.deadline_day)
            : '',
        ],
        [T('已生效', 'In effect'), rules.map(ruleName).join(T('、', ', ')) || T('无', 'None')],
      ])
    );
  }
  if (v.kind === 'test_result' && c)
    return (
      at +
      `<div class="run-q"><span class="run-asker">${T('你问', 'You asked')}</span><h3${zhAttr(c.query)}>${esc(c.query)}</h3></div><div class="answer">${assistantMark('sm')}<div class="answer-body"${zhAttr(c.answer)}>${md(c.answer, { dropTitle: true })}</div></div><p class="meta">${T('配置 v' + c.config_version, 'Config v' + c.config_version)}</p>`
    );
  if (v.kind === 'document' && typeof c === 'string')
    return at + `<div class="prose serif"${zhAttr(c)}>${md(c, { dropTitle: true })}</div>`;
  return (
    at +
    `<details class="raw" open><summary>${T('原始记录', 'Raw record')}</summary><pre>${esc(JSON.stringify(v, null, 2))}</pre></details>`
  );
}

/* ---------- events ---------- */
document.addEventListener('rolecraft:open-chat', (e) => {
  const role = ROLE_OF[e.detail?.roleId];
  if (role && current()) openChat(role);
});
app.addEventListener('rolecraft:quote-sent', (e) => {
  const a = current();
  const role = ROLE_OF[e.detail?.roleId];
  if (a && role) {
    delete ui.chatQuotes[quoteKey(a, role)];
    refreshWS(['rail']);
  }
});
document.addEventListener('click', (e) => {
  if (ui.menu && !e.target.closest('.menu-wrap')) {
    ui.menu = null;
    if (WS.includes(ui.route)) refreshWS(['toolbar', 'stage']);
    else render();
  }
  const el = e.target.closest('[data-action]');
  if (!el || el.disabled) return;
  if (el.tagName === 'A') e.preventDefault();
  ui.kbd = e.detail === 0;
  document.documentElement.dataset.input = ui.kbd ? 'keyboard' : 'pointer';
  Promise.resolve(act(el, e)).catch((err) =>
    notify(
      errText(err) || T('这一步没有完成，内容还在。', 'That did not go through. Nothing was lost.'),
    ),
  );
});
document.addEventListener(
  'toggle',
  (e) => {
    const d = e.target;
    if (d.isConnected && d.matches?.('.rc-behavior__steps') && current()) {
      if (d.open) ui.behaviorStepsOpen.add(current().id);
      else ui.behaviorStepsOpen.delete(current().id);
    }
    if (d.matches?.('details[data-intake]')) ui.intake.open = d.open;
    if (d.matches?.('details[data-continue-code]')) recovery.toggle(d.open);
    if (d.isConnected && d.matches?.('.investigation-work details[data-key]')) {
      const a = current(),
        x = artifact();
      if (a && x?.kind === 'investigation')
        investigationViewState(a, x).open[d.dataset.key] = d.open;
    }
  },
  true,
);
document.addEventListener('compositionstart', (e) => {
  if (e.target.closest?.('.investigation-work')) ui.investigationComposing = true;
});
document.addEventListener('compositionend', (e) => {
  const investigation = e.target.closest?.('.investigation-work');
  if (investigation) ui.investigationComposing = false;
  if (
    e.target.dataset &&
    (e.target.dataset.edit ||
      e.target.dataset.caseField ||
      e.target.dataset.investigationQuestion !== undefined ||
      e.target.dataset.investigationReview)
  )
    e.target.dispatchEvent(new Event('input', { bubbles: true }));
  if (investigation && ui.investigationRefreshQueued) {
    ui.investigationRefreshQueued = false;
    refreshWS(['stage']);
  }
});
document.addEventListener('input', (e) => {
  const el = e.target;
  const a = current();
  if (a && ['lab-q', 'lab-e', 'chat-input'].includes(el.id)) {
    const s = sessionOf(a);
    if (s) {
      if (el.id === 'chat-input' && ui.chatRole && s.protocol === 2) {
        const host = L.v4Host(a);
        void host
          .keepDraft('roles', `question:${ROLE_ID[ui.chatRole]}`, el.value)
          .catch((error) => notify(errText(error)));
        return;
      }
      const inputs = { ...s.inputs, messages: { ...s.inputs.messages } };
      if (el.id === 'lab-q') inputs.question = el.value;
      if (el.id === 'lab-e') inputs.expected = el.value;
      if (el.id === 'chat-input' && ui.chatRole) inputs.messages[ROLE_ID[ui.chatRole]] = el.value;
      L.store.update(a.id, { inputs });
    }
  }
  if (a && el.form?.dataset.form === 'live-deliver' && FIELDS.includes(el.name)) {
    L.store.update(a.id, { draft: { ...sessionOf(a).draft, [el.name]: el.value } });
    const live = document.querySelector('[data-action="live-submit"]');
    if (live) live.disabled = true;
    const save = document.querySelector('[data-action="live-save"]');
    if (save) save.classList.remove('quiet');
  }
  if (e.isComposing) return;
  if (el.dataset.investigationReview && a) {
    const x = artifact();
    if (!x || x.kind !== 'investigation' || !canEditWork(a, x)) return;
    const v = dirty?.attemptId === a.id && dirty.id === x.id ? dirty : shown(x);
    const key = el.dataset.investigationReview;
    if (!['focus', 'note'].includes(key)) return;
    queueInvestigationDraft(a, x, {
      review: { ...(v.review || { focus: 'uncertain', note: '' }), [key]: el.value },
    });
    return;
  }
  if (el.dataset.investigationQuestion !== undefined && a) {
    const x = artifact();
    if (!x || x.kind !== 'investigation' || !canEditWork(a, x)) return;
    queueInvestigationDraft(a, x, { question: el.value });
    return;
  }
  if (el.dataset.caseField && a) {
    const x = artifact();
    if (
      !x ||
      x.kind !== 'test_set' ||
      statusOf(a) !== 'active' ||
      !(x.adopted || ui.editPending === x.id)
    )
      return;
    const v = dirty?.id === x.id ? dirty : shown(x);
    const cases = structuredClone(v.cases);
    const c = cases.find((c) => c.id === el.dataset.caseId);
    if (!c) return;
    c[el.dataset.caseField] = el.value;
    dirty = {
      attemptId: a.id,
      id: x.id,
      title: v.title,
      purpose: v.purpose,
      kind: 'test_set',
      cases,
      body: E.testSetSummary({ ...v, cases }),
    };
    updateSave();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, 450);
    return;
  }
  if (el.dataset.testNote && a) {
    const s = sessionOf(a),
      id = el.dataset.testNote;
    if (s && s.world.status === 'active')
      L.store.update(a.id, {
        testNotes: {
          ...s.testNotes,
          [id]: { ...(s.testNotes[id] || { expected: '' }), diagnosis: el.value },
        },
      });
    return;
  }
  if (el.id === 'editor-body') autoGrow(el);
  if (el.id === 'import-content') setImportDraft(current(), el.value);
  if (el.id === 'intake-text') ui.intake.text = el.value;
  if (el.id === 'continue-code-input') recovery.input(el.value);
  if (el.dataset.new !== undefined && a && el.dataset.new !== 'purpose') {
    const t = task();
    const title = document.getElementById('new-title');
    const body = document.getElementById('new-body');
    if (!t || !(title.value.trim() || body.value.trim())) return;
    const x = E.createArtifact(a, {
      taskId: t.id,
      title: title.value.trim() || T('我的初步想法', 'First thoughts'),
      purpose: document.querySelector('[data-new="purpose"]')?.value || '探索笔记',
      body: '',
    });
    startWorking(a, t);
    const caret = el.selectionStart;
    const focusTitle = el === title;
    if (body.value) x.draft = { title: x.title, purpose: x.purpose, body: body.value };
    ui.obj = { task: t.id, type: 'work', id: x.id };
    ui.artifactId = x.id;
    persist();
    refreshWS(['stage']);
    const next = document.getElementById(focusTitle ? 'editor-title' : 'editor-body');
    if (next) {
      next.focus();
      try {
        next.setSelectionRange(caret, caret);
      } catch (_) {
        /* not text */
      }
    }
    return;
  }
  if (!el.dataset.edit) return;
  const x = artifact();
  if (!a || !canEditWork(a, x)) return;
  if (L.nativeWorkspace(a) && ['title', 'body', 'purpose'].includes(el.dataset.edit)) {
    const field = el.dataset.edit === 'body' ? 'content' : el.dataset.edit;
    void L.keepNativeProductDraft(a, x.id, { [field]: el.value }).catch((error) =>
      notify(workspaceActionMessage(error instanceof Error ? error.message : '', T)),
    );
    return;
  }
  if (x.kind === 'investigation') {
    queueInvestigationDraft(a, x, { [el.dataset.edit]: el.value });
    return;
  }
  dirty = {
    attemptId: a.id,
    id: x.id,
    title: document.getElementById('editor-title')?.value || x.title,
    purpose: document.querySelector('[data-edit="purpose"]')?.value || x.purpose,
    body: document.getElementById('editor-body')?.value ?? shown(x).body,
    ...(x.kind === 'test_set' ? { kind: 'test_set', cases: structuredClone(shown(x).cases) } : {}),
    ...(x.kind === 'investigation'
      ? {
          kind: 'investigation',
          question: shown(x).question,
          blocks: structuredClone(shown(x).blocks),
        }
      : {}),
  };
  updateSave();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    flush();
    const cur = artifact();
    const row = cur && document.querySelector(`.ol-row[data-id="${cur.id}"] .ol-title`);
    if (row) row.textContent = shown(cur).title;
  }, 700);
});
document.addEventListener('change', (e) => {
  const el = e.target;
  const a = current();
  try {
    if (el.dataset.change === 'return-task') {
      const confirm = sheet.querySelector('[data-action="confirm-import"]');
      confirm.dataset.task = el.value;
      confirm.disabled = !el.value;
      return;
    }
    if (el.dataset.investigationReview) {
      commit();
      updateSave();
      return;
    }
    if (el.dataset.investigationQuestion !== undefined) {
      commit();
      updateSave();
      return;
    }
    if (el.dataset.caseHistory) {
      commit();
      ui.testHistory[el.dataset.caseHistory] = el.value;
      refreshWS(['stage']);
      return;
    }
    if (el.dataset.caseField) {
      commit();
      updateTestChrome();
      return;
    }
    // The brief's own pickers (screens/home) keep their order themselves.
    if (el.dataset.change === 'triage' && el.closest('.pri-pick')) {
      const pick = el.closest('.pri-pick');
      const focused = document.activeElement === el;
      // The task's own name; the seed's text would also read out every option.
      pick.outerHTML = priPick(el.dataset.id, el.value, el.dataset.title || '', 'triage');
      if (focused)
        document
          .querySelector(`select[data-change="triage"][data-id="${CSS.escape(el.dataset.id)}"]`)
          ?.focus();
      return;
    }
    if (el.dataset.change === 'priority') {
      commit();
      const t = a.tasks.find((x) => x.id === el.dataset.id);
      moveWithUndo(
        a,
        el.dataset.id,
        { priority: el.value },
        T(
          '「' + taskTitle(t) + '」改为' + PRI(el.value),
          '“' + taskTitle(t) + '” is now ' + PRI(el.value),
        ),
      );
      return;
    }
    if (el.dataset.edit === 'purpose') {
      el.dispatchEvent(new Event('input', { bubbles: true }));
      commit();
      updateSave();
      refreshWS(['toolbar', 'stage']);
    }
    if (el.dataset.scope) ui.exportScope[el.dataset.scope] = el.checked;
    if (el.dataset.pick && ui.deliverPick) {
      if (el.checked) ui.deliverPick.add(el.dataset.pick);
      else ui.deliverPick.delete(el.dataset.pick);
    }
    if (el.id === 'import-file' && el.files && el.files[0]) {
      const f = el.files[0];
      if (f.size > 2 * 1024 * 1024)
        throw new Error(T('请选 2 MB 以内的文本文件', 'Choose a text file under 2 MB'));
      const owner = current();
      f.text()
        .then((text) => {
          const t = document.getElementById('import-content');
          setImportDraft(owner, text);
          if (t && current() === owner) t.value = text;
        })
        .catch(() =>
          notify(
            T(
              '文件读不出来，可以直接粘贴文本',
              'That file could not be read. Paste the text instead.',
            ),
          ),
        );
    }
    if (el.form && el.form.dataset.form === 'config') {
      if (el.name === 'update') syncStrategyWork(el.form, el.value);
      const f = new FormData(el.form);
      const c = {
        participants: Number(f.get('participants')),
        domains: f.getAll('domains'),
        update: String(f.get('update')),
        workItems: f.getAll('workItems'),
        launchDay: Number(f.get('launchDay')),
      };
      const box = document.querySelector('[data-checks]');
      if (box) box.outerHTML = configChecks(a, c);
    }
  } catch (err) {
    notify(errText(err));
  }
});
document.addEventListener('submit', async (e) => {
  const form = e.target;
  if (!form.dataset.form) return;
  e.preventDefault();
  commit();
  const f = new FormData(form);
  const a = current();
  try {
    switch (form.dataset.form) {
      case 'continue-code':
        await recovery.submit(String(f.get('code') || ''));
        break;
      case 'intake': {
        ui.intake.text = String(f.get('text') || '');
        ui.intake.result = matchIntake(ui.intake.text);
        ui.intake.open = true;
        render();
        const r = ui.intake.result;
        announce(
          {
            empty: T('先写一句你想练的业务', 'Write a sentence first'),
            none: T('这个情境现在还练不了', 'This one cannot be practised yet'),
            partial: T(
              '只能借用知识助手试点的决策结构',
              'Only the decision structure carries over',
            ),
            matched: T('最接近知识助手试点', 'Closest match: the knowledge assistant pilot'),
          }[r.status],
        );
        const out = document.querySelector('.intake-result');
        out?.focus({ preventScroll: true });
        out?.scrollIntoView({
          block: 'nearest',
          behavior: reduceMotion.matches ? 'auto' : 'smooth',
        });
        break;
      }
      case 'task': {
        const values = { title: String(f.get('title')).trim(), note: String(f.get('note') || '') };
        const pr = String(f.get('priority') || 'next');
        if (form.dataset.id) {
          const t = a.tasks.find((x) => x.id === form.dataset.id);
          if (values.title === taskTitle(t)) delete values.title;
          if (values.note === taskNote(t)) delete values.note;
          if (Object.keys(values).length) E.updateTask(a, t.id, values);
          if (t.priority !== pr) E.moveTask(a, t.id, { priority: pr });
          const split = String(f.get('split') || '').trim();
          if (split) E.splitTask(a, t.id, split);
        } else {
          let t;
          closeSheet(true);
          if (ui.route === 'work') {
            flip(() => {
              t = E.addTask(a, { ...values, priority: pr });
              E.moveTask(a, t.id, { priority: pr });
              persist();
              refreshWS(['stage']);
            });
            notify(T('已加到「' + PRI(pr) + '」', 'Added to “' + PRI(pr) + '”'), {
              action: { label: T('打开', 'Open'), run: () => openTask(t.id) },
            });
          } else {
            t = E.addTask(a, { ...values, priority: pr });
            E.moveTask(a, t.id, { priority: pr });
            persist();
            openTask(t.id);
          }
          break;
        }
        persist();
        closeSheet();
        flip(() => refreshWS());
        break;
      }
      case 'artifact': {
        const x = E.createArtifact(a, {
          title: String(f.get('title')).trim(),
          purpose: String(f.get('purpose')),
          taskId: String(f.get('taskId')),
          body: '',
        });
        startWorking(
          a,
          a.tasks.find((y) => y.id === x.taskId),
        );
        persist();
        closeSheet(true);
        openTask(x.taskId, { type: 'work', id: x.id });
        setTimeout(() => document.getElementById('editor-body')?.focus(), 80);
        break;
      }
      case 'run-test':
        runQuestion(String(f.get('question')), String(f.get('expectation') || ''));
        break;
      case 'chat': {
        const text = String(f.get('text')).trim();
        if (!text || !ui.chatRole) break;
        ui.chatTask = task() ? task().id : null;
        const x = ui.obj?.type === 'work' ? artifact() : null;
        const context = {
          ...(sessionOf(a).turnContexts?.[ROLE_ID[ui.chatRole]] || {}),
          ...(ui.chatTask ? { task_id: ui.chatTask } : {}),
          ...(x ? { work_id: x.id } : {}),
        };
        await L.turn(a, ui.chatRole, text, context);
        refreshWS(['rail', 'toolbar']);
        document.getElementById('chat-input')?.focus();
        break;
      }
      case 'config': {
        await L.config(a, {
          participants: Number(f.get('participants')),
          domains: f.getAll('domains'),
          update: String(f.get('update')),
          fallback: String(f.get('fallback')),
          workItems: planWorkItems(String(f.get('update')), f.getAll('workItems')),
          launchDay: Number(f.get('launchDay')),
          ...(a.assistantMode
            ? { generator: submittedGenerator(f, a.config.generator || 'extractive') }
            : {}),
        });
        closeSheet();
        {
          const t = task();
          if (t && !ui.configFromTestSet) ui.obj = { task: t.id, type: 'bench' };
          ui.configFromTestSet = false;
        }
        refreshWS();
        notify(savedConfigNotice(a.configVersion, configUse(a.effectiveConfig, a.world.devDays)));
        break;
      }
      case 'resources':
        await L.action(a, String(f.get('kind')), { reason: String(f.get('reason')).trim() });
        sheetResources();
        refreshWS();
        notify(T(`申请已提交给 ${PEOPLE.manager.name}`, `Request sent to ${PEOPLE.manager.ref}`));
        break;
      case 'live-deliver':
        saveDraftFields(a, form);
        await L.save(a, sessionOf(a).draft);
        sheetDeliver();
        break;
      case 'import': {
        const text = String(f.get('content'));
        const data = E.validateImported(normalizeImport(text));
        setImportDraft(a, text);
        if (statusOf(a) !== 'active' || storageIssue || snap().storageError)
          throw new Error(
            T(
              '这次练习只读或存储不可用，不能导入新作品。',
              'This practice is read-only or storage is unavailable. New work cannot be imported.',
            ),
          );
        returnPreviewSheet(a, data);
        break;
      }
    }
  } catch (err) {
    notify(errText(err) || T('请检查输入', 'Please check the input'));
  }
});
document.addEventListener(
  'pointermove',
  () => document.documentElement.classList.remove('hide-tooltips'),
  { passive: true },
);
document.addEventListener('focusin', () =>
  document.documentElement.classList.remove('hide-tooltips'),
);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') document.documentElement.classList.add('hide-tooltips');
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    const v = commit();
    notify(
      storageIssue
        ? storageText()
        : v
          ? T('已存为新版本', 'Saved as a new version')
          : T('已保存', 'Saved'),
    );
    updateSave();
  }
  if (
    (e.metaKey || e.ctrlKey) &&
    e.key === 'Enter' &&
    (e.target.id === 'chat-input' || e.target.id === 'lab-q')
  ) {
    e.preventDefault();
    e.target.form.requestSubmit();
  } else if (
    e.target.id === 'chat-input' &&
    e.key === 'Enter' &&
    !e.shiftKey &&
    !e.altKey &&
    // Choosing a word in an input method also presses Enter; it never sends.
    !e.isComposing &&
    e.keyCode !== 229
  ) {
    e.preventDefault();
    if (e.target.value.trim()) e.target.form.requestSubmit();
  }
  if (
    (e.metaKey || e.ctrlKey) &&
    !e.shiftKey &&
    e.key.toLowerCase() === 'z' &&
    ui.lastUndo &&
    !/^(INPUT|TEXTAREA)$/.test(e.target.tagName)
  ) {
    e.preventDefault();
    const u = ui.lastUndo;
    ui.lastUndo = null;
    u();
    dismissToasts();
    notify(T('已撤销', 'Undone'));
  }
  if (e.key === 'Escape' && !sheet.open) {
    if (ui.menu) {
      ui.menu = null;
      if (WS.includes(ui.route)) refreshWS(['toolbar', 'stage']);
      else render();
      return;
    }
    if (ui.railOpen) {
      ui.railOpen = false;
      refreshWS(['toolbar']);
      return;
    }
    if (ui.route === 'doc') {
      e.preventDefault();
      go('work');
      return;
    }
    const typing = e.target?.closest?.('input, textarea, select, [contenteditable="true"]');
    if (!typing && ui.route !== 'work' && awayFrom(current())) {
      e.preventDefault();
      toWorkbench();
      return;
    }
  }
  if (
    e.altKey &&
    /^Arrow/.test(e.key) &&
    e.target.classList &&
    e.target.classList.contains('card-open')
  ) {
    e.preventDefault();
    const a = current();
    const id = e.target.dataset.id;
    const t = a.tasks.find((x) => x.id === id);
    if (!t) return;
    const order = ['first', 'next', 'later'];
    const lane = a.tasks.filter((x) => x.priority === t.priority);
    const li = lane.indexOf(t);
    let to = null;
    if (e.key === 'ArrowLeft' && order.indexOf(t.priority) > 0)
      to = { priority: order[order.indexOf(t.priority) - 1] };
    if (e.key === 'ArrowRight' && order.indexOf(t.priority) < 2)
      to = { priority: order[order.indexOf(t.priority) + 1] };
    if (e.key === 'ArrowUp' && li > 0) to = { priority: t.priority, beforeId: lane[li - 1].id };
    if (e.key === 'ArrowDown' && li < lane.length - 1)
      to = { priority: t.priority, beforeId: lane[li + 2] ? lane[li + 2].id : null };
    if (!to) {
      notify(T('已经到头了', 'Already at the end'));
      return;
    }
    moveWithUndo(
      a,
      id,
      to,
      to.priority !== t.priority
        ? T(
            '「' + taskTitle(t) + '」改为' + PRI(to.priority),
            '“' + taskTitle(t) + '” is now ' + PRI(to.priority),
          )
        : T('已调整顺序', 'Order changed'),
    );
    document.querySelector(`.card-open[data-id="${id}"]`)?.focus();
    const moved = a.tasks.find((x) => x.id === id);
    const laneNow = a.tasks.filter((x) => x.priority === moved.priority);
    announce(
      T(
        '「' +
          taskTitle(moved) +
          '」现在在' +
          PRI(moved.priority) +
          '第 ' +
          (laneNow.indexOf(moved) + 1) +
          ' 位，共 ' +
          laneNow.length +
          ' 项',
        '“' +
          taskTitle(moved) +
          '” is now ' +
          (laneNow.indexOf(moved) + 1) +
          ' of ' +
          laneNow.length +
          ' in ' +
          PRI(moved.priority),
      ),
    );
  }
});
sheet.addEventListener('cancel', (e) => {
  e.preventDefault();
  closeSheet();
});
sheet.addEventListener('click', (e) => {
  if (e.target === sheet) {
    const r = sheet.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)
      closeSheet();
  }
});
// Drag between priority groups: drop on a task to insert before it, on a group to append.
document.addEventListener('dragstart', (e) => {
  const row = e.target.closest && e.target.closest('.kanban [data-task-id]');
  if (!row) return;
  dragId = row.dataset.taskId;
  row.classList.add('dragging');
  document.querySelector('.kanban')?.classList.add('is-dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', dragId);
});
document.addEventListener('dragover', (e) => {
  const laneEl = e.target.closest && e.target.closest('.col');
  if (!laneEl || !dragId) return;
  e.preventDefault();
  document
    .querySelectorAll('.drop-before, .col.drop')
    .forEach((x) => x.classList.remove('drop-before', 'drop'));
  const row = e.target.closest('[data-task-id]');
  if (row && row.dataset.taskId !== dragId) row.classList.add('drop-before');
  else laneEl.classList.add('drop');
});
document.addEventListener('drop', (e) => {
  const laneEl = e.target.closest && e.target.closest('.col');
  if (!laneEl || !dragId) return;
  e.preventDefault();
  const a = current();
  const row = e.target.closest('[data-task-id]');
  const t = a.tasks.find((x) => x.id === dragId);
  const pr = laneEl.dataset.lane;
  const id = dragId;
  dragId = null;
  document
    .querySelectorAll('.dragging, .drop-before, .col.drop')
    .forEach((x) => x.classList.remove('dragging', 'drop-before', 'drop'));
  document.querySelector('.kanban')?.classList.remove('is-dragging');
  if (row && row.dataset.taskId === id) return;
  moveWithUndo(
    a,
    id,
    { priority: pr, beforeId: row ? row.dataset.taskId : null },
    t.priority !== pr
      ? T('「' + taskTitle(t) + '」移到' + PRI(pr), '“' + taskTitle(t) + '” moved to ' + PRI(pr))
      : T('已调整顺序', 'Order changed'),
  );
});
document.addEventListener('dragend', () => {
  dragId = null;
  document.querySelector('.kanban')?.classList.remove('is-dragging');
  document
    .querySelectorAll('.dragging, .drop-before, .col.drop')
    .forEach((x) => x.classList.remove('dragging', 'drop-before', 'drop'));
});
document.addEventListener('focusout', (e) => {
  if (e.target.dataset.investigationQuestion !== undefined) {
    commit();
    updateSave();
    return;
  }
  if (e.target.dataset.caseField) {
    commit();
    updateTestChrome();
    return;
  }
  if (e.target.id !== 'editor-body' && e.target.id !== 'editor-title') return;
  setTimeout(() => {
    const a = current();
    const x = artifact();
    if (!a || !x) return;
    if (
      document.activeElement &&
      (document.activeElement.id === 'editor-body' || document.activeElement.id === 'editor-title')
    )
      return;
    commit();
    updateSave();
  }, 0);
});
window.addEventListener('beforeunload', commit);
window.addEventListener(
  'scroll',
  () => document.documentElement.classList.toggle('scrolled', window.scrollY > 4),
  { passive: true },
);
window.addEventListener('resize', () => {
  document.querySelectorAll('.segmented').forEach(layoutSegmented);
  syncPanels();
});
onLocaleChange(() => {
  flush();
  if (sheet.open) closeSheet(true);
  render();
});

window.addEventListener('v4-selection', (event) => {
  const { kind, ref } = event.detail,
    a = current();
  if (!a || a.id !== ref.session_id || !L.nativeWorkspace(a)) return;
  if (kind === 'currentTask' && a.tasks.some((t) => t.id === ref.object_id)) {
    if (sheet.open) closeSheet(true);
    openTask(ref.object_id);
  }
  if (kind === 'currentProduct') {
    const work = a.artifacts.find((x) => x.id === ref.object_id);
    if (work && !work.taskId) {
      previewWork(a, work.id);
      return;
    }
    const taskId = work?.taskId || task()?.id || a.tasks[0]?.id;
    if (work && taskId) {
      if (sheet.open) closeSheet(true);
      openTask(taskId, { type: 'work', id: work.id });
    }
  }
});
// The delivery panel stamps a confirmed delivery, then hands over to the results page.
document.addEventListener('rolecraft:delivered', () => {
  const a = current();
  if (!a) return;
  if (a.revisionGuide) {
    delete a.revisionGuide;
    persist();
  }
  if (!sheet.open || !sheet.querySelector('[data-v4-region="submission"]')) return;
  // The dialog closes inside the page transition: it fades straight into the result page, and
  // the board behind it never shows on its own (its named parts do not fly out over the dialog).
  const root = document.documentElement;
  root.classList.add('rc-handover');
  go('review', { transition: true });
  pageTransition.afterFinished(() => root.classList.remove('rc-handover'));
});
// "Start a revision" returns to the board with where to pick the work up.
document.addEventListener('rolecraft:revision-started', (event) => {
  const a = current();
  if (!a) return;
  const d = event.detail || {};
  a.revisionGuide = {
    at: new Date().toISOString(),
    delivery: Number.isFinite(d.delivery) ? d.delivery : null,
    unmet: Array.isArray(d.unmet) ? d.unmet.slice(0, 12) : [],
    products: Array.isArray(d.products) ? d.products.slice(0, 12) : [],
    reason: String(d.reason || '').slice(0, 200),
  };
  persist();
  if (ui.route === 'review') go('work', { transition: true });
});
sheet.addEventListener('w03:form-confirmed', (event) => {
  if (!event.detail.changedWhileWaiting && sheet.open && event.target.closest?.('#sheet')) {
    closeSheet(true);
    refreshWS();
  }
});
window.addEventListener('beforeunload', (event) => {
  if (L.hasUnsavedV4()) {
    event.preventDefault();
    event.returnValue = '';
  }
});

/* ---------- boot ---------- */
const workFolders = installWorkFolders(document, {
  onSelect: (taskId, workId, event) => {
    ui.kbd = event?.detail === 0;
    document.documentElement.dataset.input = ui.kbd ? 'keyboard' : 'pointer';
    openTask(taskId, { type: 'work', id: workId });
    if (ui.kbd) {
      const focusWork = () =>
        document.getElementById('editor-title')?.focus({ preventScroll: true });
      pageTransition.afterUpdate(focusWork);
    }
  },
  onInteract: () => {
    if (!ui.menu) return;
    ui.menu = null;
    document.querySelectorAll('.menu, .popover').forEach((el) => el.remove());
    document
      .querySelectorAll('[data-menu][aria-expanded="true"]')
      .forEach((el) => el.setAttribute('aria-expanded', 'false'));
  },
});
installV4References(() => L.v4Host(current()));
// Lens chips open saved records in place. Each carrier names its own provenance.
installCardToggles(locale);
// Board cards drawn by the native workspace read tests, reminders and the revision start here.
provideTaskCardFacts((taskId) => {
  const a = current();
  if (!a?.world) return null;
  const t = a.tasks.find((x) => x.id === taskId);
  return {
    ...testFacts(a.tests || [], taskId, a.world.policyVersion),
    requestedBy: t ? seedRequester(t.title) : undefined,
    asked: Object.values(a.conversations || {}).some((list) =>
      (list || []).some((m) => m.role === 'user' && m.context?.task_id === taskId),
    ),
    reminders: [
      ...new Set((ui.notesCache || []).filter((n) => n.taskId === taskId).map((n) => n.role)),
    ],
    reviseHere: revisionTaskIds(a).has(taskId),
    policyVersion: a.world.policyVersion,
    handedBy: Board.handedTask(a.id) === taskId ? 'manager' : undefined,
  };
});
// The walk-in: Grace's note, the brief landing on the policy item, the three-step walk-through.
Board.installWalkThrough({
  current,
  fresh: (a) =>
    !!a &&
    L.nativeWorkspace(a) &&
    statusOf(a) === 'active' &&
    !sessionOf(a)?.v2ReadOnly &&
    Greetings.hasEntryStory(a.id),
  job: (a) => (hatHere(a) === 'engineer' ? 'engineer' : 'pm'),
  prepareTour: () => {
    ui.menu = null;
    ui.rail = 'team';
    ui.railTab = 'team';
    if (hatHere(current()) === 'pm' && ui.route !== 'work') go('work');
    else refreshWS(['toolbar', 'rail', 'stage']);
  },
  finish: (id) => {
    Greetings.finishArrivals(id);
    // The sheet pile's first hint was held back during the walk-through: give it its turn.
    const a = current();
    if (a?.id === id && document.querySelector('[data-island="aipm-stack"]')) mountProgress(a);
  },
  openTicket: async () => {
    const a = current(), id = ui.routeId?.split('?')[0];
    if (!a || !id) return;
    const ticket = await engineerApi(L.gatewayTransport(a), a.id).ticket(id);
    if (current()?.id !== a.id) return;
    openSheet(esc(T('Grace 的工程委托', 'Grace’s engineering ticket')),
      `<h3>${esc(ticket.title)}</h3>${ticket.target_tests.map(t => `<section><h4>${esc(t.query)}</h4><blockquote>${esc(t.answer_summary)}</blockquote></section>`).join('')}<p>${T('只改允许的设置，复现并试跑后，由你亲自签字交回复核。', 'Change only supported settings, reproduce and test the issue, then sign the report yourself and hand it back for review.')}</p>`);
  },
  policyTask: (a) =>
    (a.tasks || []).find((t) => t.title === SEEDS.policy.zh[0] || t.title === SEEDS.policy.en[0])
      ?.id ?? null,
  refresh: (parts) => refreshWS(parts),
  text: (zh, en, a) => worldText(a)(zh, en),
});
L.attach(state, onLive);
// Like a poll: a read dropped while the page loads only marks the connection lost.
L.load(current()).then((loaded) => {
  if (loaded) ui.synced = true;
});
// A hidden page skips the idle refresh but keeps reading a pending reply or run until it settles,
// so a reply that finishes in the background is shown, not held until the page is looked at.
setInterval(async () => {
  if (document.hidden && !L.store.awaiting()) return;
  await L.store.poll();
  const a = current();
  // Feedback completion and a new submission change the host point. Refresh the optional
  // choices by GET, without remounting stable controls or replaying any choice.
  if (
    ui.route === 'review' &&
    a &&
    !ui.practiceBusy &&
    L.nativeWorkspace(a) &&
    practicePoints.get(a.id) !== JSON.stringify(L.v4Host(a)?.snapshot().asOf)
  )
    void loadPractice(a, true);
}, 1500);
{
  const p = parseRoute();
  ui.route = p.r;
  ui.routeId = p.id;
}
if ((WS.includes(ui.route) || ui.route === 'review') && !current()) {
  ui.route = '';
  ui.routeId = null;
  history.replaceState(null, '', '#/');
}
provideAgentPage({
  current,
  host: (a) => (a && L.nativeWorkspace(a) ? L.v4Host(a) : null),
  language: locale,
  workspace: (a, hat) => {
    const docs = E.getMaterials(a).length;
    const rows = [
      { key: 'documents', label: ['资料', 'Documents'], value: String(docs) },
      {
        key: 'brief',
        label: [`${PEOPLE.manager.name} 的委托`, `${PEOPLE.manager.ref}’s brief`],
        value: readSet(a).has('brief') ? T('已读', 'Read') : T('未读', 'Unread'),
      },
      { key: 'tests', label: ['测试记录', 'Test runs'], value: String(a.tests.length) },
      {
        key: 'work',
        label: ['作品', 'Work'],
        value: String((a.artifacts || []).filter((w) => !w.removedAt).length),
      },
      { key: 'tasks', label: ['事项', 'Tasks'], value: String(a.tasks.length) },
    ];
    if (hat === 'engineer')
      return [
        {
          key: 'ticket',
          // An engineer's practice: the ticket is Grace's (the product side, phase 2).
          label:
            roleOf(a.id) === 'engineer'
              ? [`${PEOPLE.manager.name} 的委托`, `${PEOPLE.manager.ref}’s ticket`]
              : [`${PEOPLE.technical.name} 的工单`, `${PEOPLE.technical.ref}’s ticket`],
          value: T('进行中', 'Open'),
        },
        ...rows.filter((r) => r.key !== 'brief' && r.key !== 'tasks'),
      ];
    return rows;
  },
  returned: (a) =>
    (a.artifacts || [])
      .filter((w) => w.source !== 'user')
      .map((w) => {
        const v = shown(w);
        const body = String(editorView(a, w).body || '')
          .replace(/\s+/g, ' ')
          .trim();
        return {
          id: w.id,
          title: v.title || T('未命名', 'Untitled'),
          excerpt: body.length > 220 ? `${body.slice(0, 219)}…` : body,
          version: Number(w.revision) || 1,
          adopted: !!w.adopted,
          removed: !!w.removedAt,
        };
      }),
  packageHtml: agentPackageHtml,
  refresh: (a) => L.refresh(a),
  openWork: (a, id) => {
    const x = (a.artifacts || []).find((w) => w.id === id);
    if (x?.taskId) openTask(x.taskId, { type: 'work', id });
    else previewWork(a, id);
  },
  adopt: (id) => {
    const el = document.createElement('button');
    el.dataset.action = 'adopt';
    el.dataset.id = id;
    void act(el);
  },
  notify,
  back: () => go('work'),
});
installShell((el, ev) => act(el, ev));
// The engineer's screens (201): what they need from this file to draw inside the workspace.
installEngineer({
  current,
  language: () => locale(),
  native: (a) => !!L.nativeWorkspace(a),
  transport: (a) => L.gatewayTransport(a),
  agentHost: (a) => L.v4Host(a),
  navigate: (route, id, transition) => go(route, { id, transition }),
  refresh: (parts) => {
    if (current() && WS.includes(ui.route)) refreshWS(parts);
  },
  notify,
  download,
});
// The topbar lamp's words and drawn state, from the one connection the agent line reports.
function lampText(c) {
  const state = lightState(c);
  const label =
    c.state === 'none'
      ? T('连接 Agent', 'Connect agent')
      : c.state === 'waiting'
        ? T('等待 Agent', 'Waiting for agent')
        : state === 'reachable'
          ? T('已连通', 'Reachable')
          : c.client || T('我的 Agent', 'My agent');
  const title =
    state === 'reachable'
      ? T(
          '我的 Agent · 配置已写好；已经开着的会话要重启或在 /mcp 里重连才能用上',
          'My agent · Setup written; a session that was already open must restart or reconnect in /mcp',
        )
      : c.state === 'idle' && c.lastSeen
        ? T(`我的 Agent · 上次 ${when(c.lastSeen)}`, `My agent · Last seen ${when(c.lastSeen)}`)
        : T('我的 Agent', 'My agent');
  return { label, title, state };
}
onAgentConnection(() => {
  if (inPractice()) {
    if (WS.includes(ui.route)) refreshWS(['toolbar', 'rail']);
    else {
      const c = agentConnection();
      const lamp = document.querySelector('.agent-lamp');
      const { label, title, state } = lampText(c);
      if (lamp) {
        lamp.dataset.state = state;
        lamp.title = title;
        lamp.setAttribute('aria-label', `${title}: ${label}`);
        const text = lamp.querySelector('.lamp-label');
        if (text) text.textContent = label;
      }
      for (const light of document.querySelectorAll('.agent-lamp .rc-agent-light, .person.mine .rc-agent-light')) {
        light.dataset.state = state;
        if (light.getAttribute('role') === 'img') light.setAttribute('aria-label', c.state === 'connected' ? T('已连接', 'Connected') : T('未连接或空闲', 'Not connected or idle'));
      }
    }
  }
});
// The engineer's scale until 201 registers the real one: the three steps, the first current.
if (!hasStage('engineer'))
  registerStage('engineer', () => ({
    steps: [
      { id: 'reproduce', label: ['复现', 'Reproduce'], state: 'current' },
      { id: 'fix', label: ['修复与试跑', 'Fix & trial'], state: 'todo' },
      { id: 'sign', label: ['签字', 'Sign off'], state: 'todo' },
    ],
  }));
// The board line (screens/board): what it needs from this file to redraw and to open things.
Board.installBoard({
  current,
  refresh: (parts) => {
    if (current() && WS.includes(ui.route)) refreshWS(parts);
  },
  notes: (a) => (a === current() ? ui.notesCache || [] : Coach.notes(a, E)),
  replyLabel: () => T('回应', 'Reply'),
  closeDoc: () => {
    const a = current();
    const was = ui.docSheet;
    ui.docSheet = null;
    ui.compare = false;
    // Closing the brief the first time rolls it into one line; the board below follows.
    const rolls = was === 'brief' && a && document.querySelector('.brief-band:not(.is-rolled)');
    if (rolls) {
      Board.noteBriefRead(a.id);
      Board.captureBoard();
    }
    refreshWS(['overlay', 'stage', 'toolbar']);
    if (rolls) Board.playBoard();
  },
  openRecords: () => boardSettle(),
  reload: async () => {
    const a = current();
    if (!a) return;
    await L.refresh(a);
    if (current() === a && WS.includes(ui.route)) refreshWS(['stage', 'toolbar']);
  },
  openNeeds: () => {
    ui.railTab = 'team';
    ui.rail = 'team';
    ui.railOpen = true;
    refreshWS(['rail', 'toolbar']);
    document.getElementById('needs-h')?.scrollIntoView({ block: 'start' });
    document.querySelector('#ws-rail .needs-you button')?.focus({ preventScroll: true });
  },
  myAgent: () => {
    if (isRegisteredRoute('agent')) go('agent', { transition: true });
    else {
      ui.railTab = 'agent';
      ui.rail = 'team';
      if (narrowRail()) ui.railOpen = true;
      refreshWS(['rail', 'toolbar']);
    }
  },
});
// The result page is a screen of the workspace: the shell keeps the topbar and the people.
registerRoute('review', () => (current() ? renderReview() : ''));
// "Investigate" on the scale: what has been found so far, read only (screens/investigate).
registerRoute('investigate', () => {
  const a = current();
  return a ? dossierHtml(findingsOf(a), stageBack(a)) : '';
});
installDossier({ redraw: () => refreshWS(['stage']) });
registerResultScreen({
  host: (a) => (a && L.nativeWorkspace(a) ? L.v4Host(a) : null),
  sessionOf: (a) => (a && L.nativeWorkspace(a) ? a.id : null),
  current,
  route: () => ui.route,
  language: locale,
});
// The product manager's stage: no draft yet → Investigate; a draft → Decide; submitted → Delivered.
registerStage('pm', (a) =>
  pmStage({
    // A native practice keeps its work on the server (any product counts as a draft); a local
    // one in its records.
    hasDraft:
      (sessionOf(a)?.v2Workspace?.products ?? []).length > 0 ||
      works(a).some((x) => String(editorView(a, x).body || '').trim()),
    delivered: statusOf(a) === 'submitted',
    onResult: ui.route === 'review',
  }),
);
render();
