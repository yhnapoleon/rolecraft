(() => {
  'use strict';
  const L = window.PracticeLive || null;
  const E = L ? L.engine : window.PracticeEngine;
  const app = document.getElementById('app');
  const sheet = document.getElementById('sheet');
  const toastEl = document.getElementById('toast');
  if (!E) { app.innerHTML = '<main class="page empty"><h3>页面没有加载完整</h3><p>请刷新。如果仍然这样，确认 workbench-engine.js 与本页在同一目录。</p></main>'; return; }

  const KEY = L ? 'rolecraft.open-work.ui.v1' : 'practice.open-work.v2';
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const PRI = { first: '先做', next: '随后', later: '暂放' };
  const STATUS = { open: '待处理', working: '正在做', done: '已处理' };
  const KIND = { remind: '提醒', object: '异议', correct: '纠正', help: '帮忙' };
  const KIND_VERB = { remind: '提醒了你', object: '提出异议', correct: '纠正了一处', help: '来帮忙' };
  const ROLES = ['manager', 'business', 'technical'];
  const PEOPLE = {
    manager: { name: 'Priya', role: '经理', initial: 'P', knows: '目标、资源和优先级，能批准申请' },
    business: { name: 'Mei', role: '业务负责人', initial: 'M', knows: '首批员工的需求、流程和政策' },
    technical: { name: 'Daniel', role: '技术负责人', initial: 'D', knows: '系统限制、索引状态和运行证据' }
  };
  const CASES = {
    pilot: { title: '知识助手，准备好试点了吗？', quote: '我希望第一批同事下周就能用上知识助手。先服务谁、开放什么、要什么保障，你来定方案，也告诉我什么情况下该暂停。', change: null, minutes: '约 20–30 分钟' },
    urgent: { title: '演示提前到三天后', quote: '演示提前到三天后了。还是同一个试点：哪些能承诺，哪些要先收着，你来定。', change: '期望上线从第 7 天提前到第 3 天', minutes: '约 15–25 分钟' },
    capacity: { title: '容量只剩 15 人', quote: '平台这次只能给 15 个名额。先让谁用起来、开放什么，你来定。', change: '可用容量从 30 人降到 15 人', minutes: '约 15–25 分钟' }
  };
  if (L) CASES.urgent = { ...CASES.urgent, title: '试点提前到第 5 天', quote: '主管希望在第 5 天前启动试点，范围、证据与承诺需要重新权衡。', change: '期望上线从第 7 天提前到第 5 天' };
  const SEED = ['确认首批员工的使用需求', '回应政策问答的开放请求', '形成可执行的试点决定'];
  const UPDATE_NAMES = { daily: '每日索引', realtime: '实时同步', manual: '政策转人工' };
  const FALLBACK_NAMES = L ? { none: '暂不安排', human: '转人工确认' } : { none: '暂不安排', human: '转人工确认', date: '提示引用日期' };
  const INTENT_LINE = { explore: '探索：随便写，不会被当作承诺核对。', option: '备选：用来比较取舍。本原型不核对它的内容。', plan: '计划：用来安排验证。本原型不核对它的内容。', commit: '正式承诺：本原型只核对人数与容量、是否查过需求；论证质量要等真实评审（未接入）。' };

  if (L) Object.assign(INTENT_LINE, { explore: '本地探索笔记，可加入正式交付。', option: '本地方案比较，可加入正式交付。', plan: '本地测试计划；实际运行记录来自后端。', commit: '本地决定草稿。通过“交付”保存为后端成果，固定提交后生成反馈。' });

  let state; let storageError = ''; let storageLocked = false; let rawRecord = null;
  try {
    rawRecord = localStorage.getItem(KEY);
    state = rawRecord ? JSON.parse(rawRecord) : E.newState();
    if (!state || state.version !== E.VERSION || !Array.isArray(state.attempts)) throw new Error('version');
    state.attempts = state.attempts.filter(a => { try { E.normalizeAttempt(a); return true; } catch (_) { return false; } });
    if (state.activeId && !state.attempts.some(a => a.id === state.activeId)) state.activeId = null;
  } catch (err) {
    state = E.newState(); storageLocked = true;
    storageError = err && err.name === 'SecurityError' ? '这个浏览器不允许本页保存。修改只留在当前页面，离开前可以导出备份。' : '之前的练习记录读不出来，原记录没有被覆盖。可以导出原记录，或者把它另存一份后重新开始。';
  }

  const ui = { route: null, pane: 'work', artifactId: null, materialId: 'brief', inspector: 'talk', chatRole: null, inspectorOpen: false, priorityView: null, suggestions: {}, reviewSubmissionId: null, reviewTaskId: null, intake: { text: '', result: null }, openVariant: null, busy: false, lastRun: null, known: new Set(), importText: '', exportScope: { artifacts: true, materials: true, tests: true }, disputeOpen: null, labPrefill: '' };
  let dirty = null; let saveTimer = null; let toastTimer = null; let pillTimer = null; let sheetReturn = null; let dragId = null; let popoverOpen = false;

  /* ---------- helpers ---------- */
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const current = () => E.getAttempt(state);
  const task = () => { const a = current(); return a && a.selectedTaskId ? a.tasks.find(t => t.id === a.selectedTaskId) || null : null; };
  const artifact = () => { const a = current(); return a ? a.artifacts.find(x => x.id === ui.artifactId) || null : null; };
  const openNotes = (a, filter = () => true) => (a.nudges || []).filter(n => !['later', 'dismissed', 'replied'].includes(n.status)).filter(filter);
  const unread = (a, role) => (a.nudges || []).filter(n => !n.read && (!role || n.roleId === role)).length;
  const works = a => E.currentArtifacts(a);
  const isEarlier = (a, x) => x.adopted && !works(a).some(y => y.id === x.id);
  const taskWorks = (a, id) => a.artifacts.filter(x => x.taskId === id && !isEarlier(a, x));
  const caseTitle = a => (CASES[a.scenarioId] || {}).title || a.title;
  const hasDecision = a => works(a).some(w => { const v = w.draft ? Object.assign({}, w, w.draft) : w; return E.intentOf(v.purpose) === 'commit' && v.body.trim(); });
  function when(iso) {
    const d = new Date(iso); if (Number.isNaN(d.valueOf())) return '';
    const diff = (Date.now() - d.valueOf()) / 60000;
    if (diff < 1) return '刚刚';
    if (diff < 60) return Math.floor(diff) + ' 分钟前';
    const hm = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
    return d.toDateString() === new Date().toDateString() ? '今天 ' + hm : (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + hm;
  }
  function md(raw) {
    const lines = esc(raw).split('\n'); let out = ''; let list = false;
    const inline = s => s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    for (const line of lines) {
      const bullet = line.match(/^\s*[-*]\s+(.*)$/);
      if (bullet) { if (!list) { out += '<ul>'; list = true; } out += '<li>' + inline(bullet[1]) + '</li>'; continue; }
      if (list) { out += '</ul>'; list = false; }
      if (/^#{1,2}\s/.test(line)) out += '<h3>' + inline(line.replace(/^#{1,2}\s/, '')) + '</h3>';
      else if (/^#{3,6}\s/.test(line)) out += '<h4>' + inline(line.replace(/^#{3,6}\s/, '')) + '</h4>';
      else if (line.trim()) out += '<p>' + inline(line) + '</p>';
    }
    if (list) out += '</ul>';
    return out || '<p class="tertiary">还没有正文。</p>';
  }
  const vtName = s => String(s).replace(/[^a-zA-Z0-9-]/g, '');

  /* ---------- icons ---------- */
  const P = {
    back: '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
    chev: '<path d="m9.5 5.5 6.5 6.5-6.5 6.5"/>',
    down: '<path d="m6.5 9.5 5.5 5.5 5.5-5.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    doc: '<path d="M7 3.5h6.5L18 8v12.5H7z"/><path d="M13.5 3.5V8H18M9.5 12.5h6M9.5 16h4.5"/>',
    book: '<path d="M5 4.5h5.5a2 2 0 0 1 2 2v13a1.6 1.6 0 0 0-1.6-1.6H5zM19 4.5h-5.5a2 2 0 0 0-1 .3"/><path d="M19 4.5v13.4h-5.9a1.6 1.6 0 0 0-1.6 1.6"/>',
    flask: '<path d="M9.5 3.5h5M10.5 3.5v5.8L5.3 18.4a1.4 1.4 0 0 0 1.2 2.1h11a1.4 1.4 0 0 0 1.2-2.1l-5.2-9.1V3.5"/><path d="M7.6 14.5h8.8"/>',
    bubble: '<path d="M4.5 11.5c0-3.9 3.4-7 7.5-7s7.5 3.1 7.5 7-3.4 7-7.5 7c-1 0-2-.2-2.9-.5L5 19.5l1-3.6a6.7 6.7 0 0 1-1.5-4.4z"/>',
    agent: '<rect x="5" y="6.5" width="14" height="12" rx="3.5"/><path d="M12 3.5v3M9.5 12h.01M14.5 12h.01M9.5 15.5h5"/>',
    check: '<path d="m5.5 12.5 4.2 4.2L18.5 7.8"/>',
    x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    bolt: '<path d="M13 3 5.5 13.2h5.6L10.5 21 18 10.8h-5.6z"/>',
    play: '<path d="M8 5.5v13l10.5-6.5z"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M20.5 12h-2.2M5.7 12H3.5M18 6l-1.6 1.6M7.6 16.4 6 18M18 18l-1.6-1.6M7.6 7.6 6 6"/>',
    refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.2h-4.2"/>',
    send: '<path d="M12 19.5v-15M6 10.5l6-6 6 6"/>',
    quote: '<path d="M5 18.5V13c0-3.6 1.6-6 4.6-7.2M14 18.5V13c0-3.6 1.6-6 4.6-7.2"/><path d="M5 13h4.5v5.5H5zM14 13h4.5v5.5H14z"/>',
    more: '<circle cx="6" cy="12" r="1.4" class="i-fill"/><circle cx="12" cy="12" r="1.4" class="i-fill"/><circle cx="18" cy="12" r="1.4" class="i-fill"/>',
    upload: '<path d="M12 15.5V4.5M7.5 9 12 4.5 16.5 9"/><path d="M5 15v4.5h14V15"/>',
    download: '<path d="M12 4.5v11M7.5 11 12 15.5 16.5 11"/><path d="M5 15v4.5h14V15"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2.5"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    revise: '<path d="M9 14.5 4.5 10 9 5.5"/><path d="M4.5 10h10a5 5 0 0 1 0 10H11"/>',
    branch: '<circle cx="6.5" cy="5.5" r="2"/><circle cx="6.5" cy="18.5" r="2"/><circle cx="17.5" cy="8.5" r="2"/><path d="M6.5 7.5v9M17.5 10.5c0 4-4 3.5-9.5 6.5"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>',
    circle: '<circle cx="12" cy="12" r="8"/>',
    half: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" class="i-fill"/>',
    done: '<circle cx="12" cy="12" r="8.5" class="i-fill"/><path d="m8 12.3 2.7 2.7L16.2 9.5" stroke="#fff"/>',
    warn: '<path d="M12 4.5 3.8 19h16.4z"/><path d="M12 10v4.2M12 16.6h.01"/>',
    question: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4M12 16.8h.01"/>',
    good: '<circle cx="12" cy="12" r="8.5"/><path d="m8.3 12.3 2.6 2.6 4.9-5.2"/>',
    star: '<path d="m12 4.5 2.3 4.7 5.2.8-3.8 3.7.9 5.2-4.6-2.4-4.6 2.4.9-5.2-3.8-3.7 5.2-.8z"/>',
    sidebar: '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M14.5 4.5v15"/>',
    assistant: '<rect x="4" y="4.5" width="16" height="15" rx="4"/><path d="M8.5 10h7M8.5 13.5h4.5"/>',
    stale: '<path d="M18.5 9A7 7 0 0 0 6 7.3"/><path d="M5.5 15A7 7 0 0 0 18 16.7"/><path d="M18.5 4.5V9H14M5.5 19.5V15H10"/>'
  };
  const icon = (name, cls = '') => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || ''}</svg>`;
  const statusIcon = s => `<svg class="status-mark ${s}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7">${s === 'done' ? P.done : s === 'working' ? P.half : P.circle}</svg>`;
  const assistantMark = (size = 'sm') => `<span class="avatar assistant ${size}" aria-hidden="true">${icon('assistant')}</span>`;
  const avatar = (role, size = '', dot = false) => role === 'agent' ? `<span class="avatar agent ${size}" aria-hidden="true">${icon('agent')}</span>` : `<span class="avatar ${size}" aria-hidden="true">${PEOPLE[role].initial}${dot ? '<span class="dot"></span>' : ''}</span>`;
  const btn = (label, action, cls = '', attrs = '') => `<button type="button" class="btn ${cls}" data-action="${action}" ${attrs}>${label}</button>`;
  const priSelect = (id, priority, title, change = 'priority') => `<label class="pri-select"><span class="pri ${priority}">${PRI[priority]}</span><select aria-label="「${esc(title)}」的优先级" data-change="${change}" data-id="${id}">${Object.entries(PRI).map(([k, v]) => `<option value="${k}" ${k === priority ? 'selected' : ''}>${v}</option>`).join('')}</select></label>`;

  /* ---------- persistence ---------- */
  function persist() {
    if (storageLocked) { updateSave(); return false; }
    try { localStorage.setItem(KEY, JSON.stringify(state)); storageError = ''; updateSave(); return true; }
    catch (_) { storageError = '浏览器没能保存。内容还在页面上，离开前请在“原型说明”里导出备份。'; updateSave(); return false; }
  }
  function updateSave() {
    const x0 = artifact();
    document.querySelectorAll('[data-save]').forEach(el => { el.textContent = storageError ? '没有保存' : dirty ? '正在保存…' : x0 && x0.draft ? '草稿已保存' : '已保存'; if (L && !storageError) el.textContent = '本地笔记 · ' + el.textContent; el.classList.toggle('error', !!storageError); });
    const x = artifact(); document.querySelectorAll('[data-revision]').forEach(el => { if (x) el.textContent = 'v' + x.revision; });
  }
  // A pause in typing keeps a draft (persisted, no version). A version is made when the
  // writer leaves the work: blur, switching, review, submit, ⌘S or leaving the page.
  function flush() {
    clearTimeout(saveTimer);
    if (!dirty) return false;
    const a = state.attempts.find(x => x.id === dirty.attemptId); const x = a && a.artifacts.find(y => y.id === dirty.id);
    if (x) x.draft = { title: dirty.title || '未命名', purpose: dirty.purpose, body: dirty.body };
    dirty = null; persist();
    return !!x;
  }
  function commit() {
    flush();
    let changed = false;
    state.attempts.forEach(a => a.artifacts.forEach(x => {
      if (!x.draft) return;
      const d = x.draft; delete x.draft;
      try { const before = x.revision; E.saveArtifact(a, x.id, d); changed = changed || x.revision !== before; } catch (err) { x.draft = d; notify(err.message); }
    }));
    persist();
    return changed;
  }
  const shown = x => x.draft ? Object.assign({}, x, x.draft) : x;
  function notify(text, undo) {
    if (sheet.open && !sheet.classList.contains('closing') && !undo) { let el = sheet.querySelector('.inline-alert'); if (!el) { el = document.createElement('div'); el.className = 'inline-alert'; el.setAttribute('role', 'alert'); sheet.querySelector('.sheet-body')?.prepend(el); } el.textContent = text; return; }
    toastEl.innerHTML = `<span>${esc(text)}</span>${undo ? '<button type="button" class="toast-undo">撤销</button>' : ''}`;
    toastEl.classList.add('visible'); toastEl.classList.toggle('actionable', !!undo);
    ui.lastUndo = undo || null;
    if (undo) toastEl.querySelector('.toast-undo').onclick = () => { undo(); ui.lastUndo = null; toastEl.classList.remove('visible'); };
    announce(text);
    const hide = () => { if (!toastEl.matches(':hover, :focus-within')) toastEl.classList.remove('visible'); else toastTimer = setTimeout(hide, 1500); };
    clearTimeout(toastTimer); toastTimer = setTimeout(hide, undo ? 6000 : 2800);
  }

  /* ---------- routing & transitions ---------- */
  const ROUTES = ['', 'pm', 'work', 'review'];
  const routeNow = () => { const r = location.hash.replace(/^#\/?/, ''); return ROUTES.includes(r) ? r : ''; };
  let activeTransition = null;
  function withTransition(fn) {
    if (activeTransition) { try { activeTransition.skipTransition(); } catch (_) { /* already finished */ } }
    if (!document.startViewTransition || reduceMotion.matches) { fn(); return; }
    activeTransition = document.startViewTransition(() => { fn(); });
    activeTransition.finished.finally(() => { activeTransition = null; });
  }
  function go(route, opts = {}) {
    commit();
    if ((route === 'work' || route === 'review') && !current()) route = 'pm';
    const run = () => { if (sheet.open) closeSheet(true); popoverOpen = false; ui.route = route; history.pushState(null, '', '#/' + route); render(); window.scrollTo(0, 0); };
    if (opts.transition) withTransition(run); else run();
  }
  window.addEventListener('popstate', () => { commit(); if (sheet.open) closeSheet(true); ui.route = routeNow(); withTransition(render); });

  function render() {
    const key = focusKey();
    const r = ui.route ?? routeNow(); ui.route = r;
    document.body.dataset.view = r || 'careers';
    const alert = storageError ? `<div class="storage-alert" role="alert">${esc(storageError)} ${btn(rawRecord && storageLocked ? '导出原记录' : '导出备份', 'export', 'small')}${rawRecord && storageLocked ? btn('另存原记录后重新开始', 'reset-storage', 'small quiet') : ''}</div>` : '';
    if (r === 'pm') app.innerHTML = alert + renderEntry();
    else if (r === 'work' && current()) app.innerHTML = alert + renderWorkspace();
    else if (r === 'review' && current()) app.innerHTML = alert + renderReview();
    else app.innerHTML = alert + renderCareers();
    afterRender();
    if (L) liveStatus();
    restoreFocus(key);
  }
  function afterRender() {
    document.querySelectorAll('.segmented').forEach(layoutSegmented);
    const body = document.getElementById('editor-body'); if (body) autoGrow(body);
    const thread = document.querySelector('.thread'); if (thread) thread.scrollTop = thread.scrollHeight;
    updateSave(); surfaceNewNotes(); syncDrawer(); if (L) liveStatus();
  }
  function layoutSegmented(seg) {
    const active = seg.querySelector('[aria-pressed="true"]'); const thumb = seg.querySelector('.thumb');
    if (!thumb) return; if (!active) { thumb.style.opacity = '0'; return; }
    thumb.style.opacity = '1'; thumb.style.width = active.offsetWidth + 'px'; thumb.style.transform = `translateX(${active.offsetLeft - 2}px)`;
  }
  // Grow the editor with its content without letting the page jump while typing.
  const nativeGrow = window.CSS && CSS.supports && CSS.supports('field-sizing', 'content');
  function autoGrow(el) {
    if (nativeGrow) return;
    const y = window.scrollY; el.style.height = 'auto'; el.style.height = Math.max(el.scrollHeight, 300) + 'px';
    if (window.scrollY !== y) window.scrollTo(0, y);
  }

  /* ---------- focus & announcements ---------- */
  function focusKey() {
    const el = document.activeElement; if (!el || el === document.body) return null;
    if (el.id && el.id !== 'main') return { id: el.id, pos: el.selectionStart ?? null };
    const d = el.dataset || {}; const parts = ['action', 'id', 'pane', 'tab', 'role', 'change', 'case', 'key'].filter(k => d[k] !== undefined).map(k => `[data-${k}="${CSS.escape(d[k])}"]`);
    return parts.length ? { sel: el.tagName.toLowerCase() + parts.join('') } : null;
  }
  function restoreFocus(key) {
    if (!key) return;
    const el = key.id ? document.getElementById(key.id) : document.querySelector(key.sel);
    if (!el || el === document.activeElement) return;
    el.focus({ preventScroll: true });
    if (key.pos != null && el.setSelectionRange) try { el.setSelectionRange(key.pos, key.pos); } catch (_) { /* not a text field */ }
  }
  function announce(text) { const el = document.getElementById('announcer'); if (!el) return; el.textContent = ''; setTimeout(() => { el.textContent = text; }, 30); }

  /* ---------- chrome ---------- */
  const proto = `<button type="button" class="proto-chip" data-action="about">${L ? '已接入 API · 运行说明' : '原型 · 规则模拟'}</button>`;
  const wordmark = `<button type="button" class="wordmark" data-action="home" aria-label="Practice，回到岗位选择"><span class="wordmark-mark" aria-hidden="true"></span>Practice</button>`;
  const miniCard = (title, priority, i, extra = '') => `<div class="mini-card" style="view-transition-name: seed-${i}"><span class="pri ${priority}">${PRI[priority]}</span><b>${esc(title)}</b>${extra}</div>`;

  /* ---------- 1. careers ---------- */
  function renderCareers() {
    const a = current(); const pm = E.careers.find(c => c.id === 'pm'); const eng = E.careers.find(c => c.id === 'engineer');
    const t = a && a.tasks.find(x => x.id === a.selectedTaskId);
    return `<header class="topbar">${wordmark}<div class="spacer"></div>${proto}</header>
      <main id="main" class="page careers" tabindex="-1">
        <h1 class="t-display">你想先练哪份工作？</h1>
        <p class="lede">选一个岗位，接手它真实会遇到的事。可以犯错，可以求助，也可以重来。</p>
        ${a ? `<div class="resume"><span class="grow"><span class="row-title">继续：${esc(caseTitle(a))}</span><span class="row-sub">${t ? '停在「' + esc(t.title) + '」' : '还没开始处理具体的事'}，${when(lastTouched(a))}</span></span>${btn('继续', 'resume', 'primary')}</div>` : ''}
        <section class="career-block" aria-labelledby="career-pm">
          <div class="career-copy">
            <h2 id="career-pm" class="t-large"><span style="view-transition-name: career-pm">${esc(pm.name)}</span></h2>
            <p class="career-summary">${esc(pm.summary)}</p>
            <p class="career-meta">3 个情境，每次约 20–30 分钟，可以随时暂停。</p>
            <div class="career-actions">${btn(a ? '看看所有工作' : '开始', 'open-career', a ? '' : 'primary large', 'data-career="pm"')}</div>
          </div>
          <div class="career-visual" aria-hidden="true">
            <p class="visual-cap">你会接手的事</p>
            ${SEED.map((s, i) => miniCard(s, 'next', i, statusIcon('open'))).join('')}
            <div class="mini-people">${ROLES.map(r => avatar(r, 'sm')).join('')}<span>Priya、Mei、Daniel 和你一起工作</span></div>
          </div>
        </section>
        <section class="career-later">
          <div class="grow"><h2 class="t-title3">${esc(eng.name)}<span class="later-label">稍后开放</span></h2><p class="secondary t-callout">${esc(eng.summary)}</p></div>
          <details class="later-more"><summary>会练什么</summary><p class="t-callout secondary">${eng.work.join('、')}。需要可运行的代码环境和回归检查，排在 AI 产品经理之后；现在不会打开占位内容。</p></details>
        </section>
        <p class="careers-foot">案例面试和更多岗位会在之后加入。${L ? '同事、助手测试与交付反馈来自后端；自由事项与笔记保存在此浏览器。' : '这一版里的同事、知识助手和反馈都是本地规则模拟，记录只保存在这个浏览器。'}</p>
      </main>`;
  }
  function lastTouched(a) { return (a.events[a.events.length - 1] || {}).createdAt || a.createdAt; }

  /* ---------- 2. training entry (PM) ---------- */
  function renderEntry() {
    const attempts = state.attempts.slice().reverse();
    const pilot = state.attempts.filter(a => a.scenarioId === 'pilot').at(-1);
    const r = ui.intake.result;
    return `<header class="topbar"><button type="button" class="btn quiet back" data-action="home">${icon('back')}岗位</button><div class="spacer"></div>${proto}</header>
      <main id="main" class="page entry" tabindex="-1">
        <header class="entry-head">
          <h1 class="t-large"><span style="view-transition-name: career-pm">AI 产品经理</span></h1>
          <p class="lede">你负责判断一个 AI 功能能不能上线、先给谁用、怎样保障，并为这个决定负责。</p>
          <ul class="doing">${[['question', '弄清需求和约束'], ['flask', '亲手测试 AI 助手'], ['bubble', '和三位同事协商'], ['doc', '交付有依据的决定']].map(([i, d]) => `<li>${icon(i)}<span>${d}</span></li>`).join('')}</ul>
        </header>

        <section class="block">
          <h2 class="group-title">选一项工作</h2>
          ${caseCard('pilot', pilot)}
        </section>

        <section class="block">
          <h2 class="group-title">同样的责任，换一个条件 <span class="tertiary">每次都是新的练习</span></h2>
          <div class="group">${['urgent', 'capacity'].map(id => `<details class="variant" ${ui.openVariant === id ? 'open' : ''} data-variant="${id}"><summary class="row"><span class="grow"><span class="row-title">${CASES[id].title}</span><span class="row-sub">${CASES[id].change}</span></span><span class="row-meta">${CASES[id].minutes}</span>${icon('chev', 'chev')}</summary><div class="variant-body">${caseCard(id, state.attempts.filter(a => a.scenarioId === id).at(-1), true)}</div></details>`).join('')}</div>
        </section>

        <section class="block">
          <h2 class="group-title">用你自己的业务来练</h2>
          <div class="group pad">
            <form data-form="intake" class="stack-12">
              <label class="field"><span>描述你想练的情境</span><textarea class="textarea" name="text" rows="3" maxlength="2000" placeholder="例如：我们 HR 每天收到员工重复的政策问题，想先给一小部分人试用知识助手。">${esc(ui.intake.text)}</textarea></label>
              <div class="hstack wrap"><button type="submit" class="btn">看看能不能练</button><span class="tertiary t-sub">只匹配已经审核过的情境，不会凭描述生成一家公司。</span></div>
            </form>
            ${r ? intakeResult(r) : ''}
          </div>
        </section>

        ${attempts.length ? `<section class="block"><h2 class="group-title">我的练习</h2><div class="group">${attempts.slice(0, 6).map(a => `<div class="row"><span class="grow"><span class="row-title">${esc(caseTitle(a))}</span><span class="row-sub">${a.submissions.length ? '交付 ' + a.submissions.length + ' 次' : '进行中'}，${when(lastTouched(a))}</span></span>${a.submissions.length ? btn('复盘', 'review-attempt', 'small quiet', `data-id="${a.id}"`) : ''}${btn('继续', 'resume-attempt', 'small', `data-id="${a.id}"`)}</div>`).join('')}</div></section>` : ''}
      </main>`;
  }
  function caseCard(id, existing, compact = false) {
    const c = CASES[id]; const s = E.scenarios.find(x => x.id === id);
    return `<article class="case-card ${compact ? 'compact' : ''}" style="${compact ? '' : 'view-transition-name: case-surface'}">
      ${compact ? '' : `<h3 class="t-title1"><span style="view-transition-name: case-title">${c.title}</span></h3>`}
      <blockquote class="brief-quote">${avatar('manager')}<div><p>“${c.quote}”</p><cite>Priya，经理</cite></div></blockquote>
      <dl class="case-facts">
        <div><dt>你负责</dt><dd>一份有依据、可执行的试点决定：先服务谁、开放什么、怎样保障、何时调整或暂停</dd></div>
        <div><dt>条件</dt><dd>${s.capacity} 人容量，3 人日开发，索引最多滞后 24 小时，期望第 ${s.deadline} 天上线</dd></div>
      </dl>
      <div class="seed-list"><p class="seed-cap">你会接手 <span class="tertiary">现在就可以排一下，进去后也能改</span></p>${SEED.map((t, i) => `<div class="mini-card" style="${compact ? '' : 'view-transition-name: seed-' + i}">${priSelect(id + '-' + i, 'next', t, 'triage')}<b>${t}</b>${statusIcon('open')}</div>`).join('')}</div>
      <p class="practised">常被练到：澄清需求、设计验证、约束下取舍、变化后调整。<span class="tertiary">这是观察的例子，不是要走的步骤。</span></p>
      <footer class="case-foot"><span class="tertiary t-sub">${c.minutes}，没有倒计时，可以随时暂停</span><div class="spacer"></div>${existing ? `${btn('重新开始一次', 'take-case', 'quiet', `data-case="${id}"`)}${btn('继续', 'resume-attempt', 'primary', `data-id="${existing.id}"`)}` : btn('接手这件工作', 'take-case', 'primary', `data-case="${id}"`)}</footer>
    </article>`;
  }
  function intakeResult(r) {
    if (r.status === 'empty') return `<p class="intake-result secondary">先写一句你想练的业务，也可以直接选上面的工作。</p>`;
    if (r.status === 'partial') return `<div class="intake-result" aria-live="polite"><p class="t-headline">主体不同，只能借用「知识助手试点」的决策结构</p><div class="intake-cols"><div><p class="t-sub secondary">能对上的</p><ul class="ticks">${r.adopted.map(x => `<li>${icon('check', 'i-sm')}${esc(x)}</li>`).join('')}</ul></div><div><p class="t-sub secondary">对不上的</p><ul class="ticks muted">${r.notModeled.map(x => `<li>${icon('info', 'i-sm')}${esc(x)}</li>`).join('')}</ul></div></div><p class="t-sub tertiary">练习里仍是内部员工的知识助手。想按你的情况练，需要先审核一个新情境。</p><div>${btn('仍用这个情境开始', 'start-intake', '')}</div></div>`;
    if (r.status === 'none') return `<div class="intake-result" aria-live="polite"><p class="t-headline">这个情境现在还练不了</p><p class="secondary t-callout">目前只有“内部知识助手上线决定”这一类经过审核。你的描述保留在框里，可以改写，或者先用上面的主情境。</p></div>`;
    return `<div class="intake-result" aria-live="polite">
      <p class="t-headline">最接近「知识助手试点」</p>
      <div class="intake-cols"><div><p class="t-sub secondary">会沿用你描述的</p><ul class="ticks">${r.adopted.map(x => `<li>${icon('check', 'i-sm')}${esc(x)}</li>`).join('')}</ul></div>
      <div><p class="t-sub secondary">不会照搬的部分</p><ul class="ticks muted">${(r.notModeled.length ? r.notModeled : ['没有——都在这个情境的范围内']).map(x => `<li>${icon('info', 'i-sm')}${esc(x)}</li>`).join('')}</ul></div></div>
      <p class="t-sub tertiary">事实、材料和反馈依据仍来自审核过的情境；你的描述只用来匹配，并会出现在委托里提醒你。</p>
      <div>${btn('用这个情境开始', 'start-intake', 'primary')}</div></div>`;
  }

  /* ---------- 3. workspace ---------- */
  function renderWorkspace() {
    const a = current();
    const arriving = ui.arriving; ui.arriving = false; ui.landing = arriving;
    return `<div class="ws ${ui.inspectorOpen ? 'inspector-open' : ''} ${arriving ? 'arriving' : ''}">
      ${wsToolbar(a)}
      <div class="note-pill-host" id="note-pill" aria-live="polite"></div>
      <section class="shelf-wrap" aria-label="手头的事" id="ws-shelf">${wsShelf(a)}</section>${(ui.landing = false, '')}
      <div class="ws-main">
        <main id="main" class="canvas" tabindex="-1" style="view-transition-name: case-surface"><div id="ws-canvas">${wsCanvas(a)}</div></main>
        <aside class="inspector" id="ws-inspector" aria-label="讨论、反馈与记录">${wsInspector(a)}</aside>
      </div>
      <button type="button" class="inspector-scrim" data-action="close-inspector" aria-label="关闭侧栏"></button>
    </div>`;
  }
  function wsToolbar(a) {
    const decision = hasDecision(a);
    return `<header class="topbar ws-toolbar">
      <button type="button" class="btn quiet back" data-action="to-entry">${icon('back')}<span class="hide-sm">AI 产品经理</span></button>
      <div class="title-wrap">
        <h1 class="ws-h1"><button type="button" class="title-btn" data-action="toggle-brief" aria-expanded="${popoverOpen}" aria-controls="brief-pop" aria-label="${esc(caseTitle(a))}，查看委托与条件"><span style="view-transition-name: case-title">${esc(caseTitle(a))}</span>${icon('down', 'i-sm')}</button></h1>
        ${popoverOpen ? briefPopover(a) : ''}
      </div>
      <span class="save-state hide-sm" data-save></span>
      <div class="spacer"></div>
      <button type="button" class="btn quiet people-btn hide-sm" data-action="open-talk" aria-label="同事${unread(a) ? '，有新意见' : ''}"><span class="avatar-stack">${ROLES.map(r => avatar(r, 'sm')).join('')}</span>${unread(a) ? '<span class="people-dot" aria-hidden="true"></span>' : ''}</button>
      ${btn(icon('agent', 'i-sm') + '我的 Agent', 'agent', 'quiet hide-sm', 'aria-label="我的 Agent"')}
      ${btn(icon('sidebar'), 'toggle-inspector', 'icon quiet' + (unread(a) ? ' has-unread' : ''), `aria-label="${ui.inspectorOpen ? '收起' : '打开'}侧栏${unread(a) ? '，同事有新意见' : ''}" aria-pressed="${ui.inspectorOpen}"`)}
      ${L ? btn(a.backend?.status === 'paused' ? '恢复' : a.backend?.status === 'submitted' ? '看反馈' : '暂停', 'live-session', 'quiet small') : ''}
      ${btn('交付…', 'submit', decision ? 'primary' : '')}
    </header>`;
  }
  function briefPopover(a) {
    const c = CASES[a.scenarioId] || CASES.pilot;
    return `<div class="popover" id="brief-pop" role="dialog" aria-label="委托与条件">
      <blockquote class="brief-quote">${avatar('manager', 'sm')}<div><p>“${c.quote}”</p><cite>Priya，经理</cite></div></blockquote>
      ${a.intake ? `<p class="t-sub secondary">按你描述的情境：${esc(a.intake.adopted.join('；'))}。${a.intake.notModeled && a.intake.notModeled.length ? '没有照搬：' + esc(a.intake.notModeled.join('；')) + '。' : ''}</p>` : ''}
      <dl class="facts list"><div><dt>试点容量</dt><dd>${a.world.capacity} 人</dd></div><div><dt>可用开发</dt><dd>${a.world.devDays} 人日</dd></div><div><dt>期望上线</dt><dd>第 ${a.world.deadline} 天</dd></div><div><dt>政策源 / 助手索引</dt><dd class="${a.world.indexVersion < a.world.policyVersion ? 'warn' : ''}">v${a.world.policyVersion} / v${a.world.indexVersion}</dd></div></dl>
      <p class="t-sub tertiary">期限是场景里的业务条件，练习没有倒计时。</p>
      <div class="hstack wrap">${btn('看完整委托', 'open-material', 'small', 'data-id="brief"')}${btn('申请资源或延期', 'resources', 'small quiet')}</div>
    </div>`;
  }
  function wsShelf(a) {
    const groups = ['first', 'next', 'later'];
    const policyNew = a.world.policyVersion > 1 && !(a.acks || []).includes('policy-v2');
    const view = ui.priorityView; const sug = view ? ui.suggestions[view] : null;
    const sugFor = id => sug && sug.items.find(i => i.taskId === id);
    const stale = id => a.tests.some(r => r.taskId === id && r.policyVersion < a.world.policyVersion);
    const card = t => { const n = taskWorks(a, t.id).length; const s = sugFor(t.id); const note = openNotes(a, x => x.taskId === t.id && !x.read).length;
      return `<li class="task-card ${t.id === a.selectedTaskId ? 'on' : ''} ${t.status}" draggable="true" data-task-id="${t.id}" style="view-transition-name: ${ui.landing && t.seed ? 'seed-' + ({ needs: 0, policy: 1, decision: 2 })[t.seed] : 't-' + vtName(t.id)}; --i: ${a.tasks.indexOf(t)}">
        <div class="task-top">${priSelect(t.id, t.priority, t.title).replace('class="pri-select"', 'class="pri-select dot-only"')}${s ? `<span class="sug-badge">${PEOPLE[view].name}：${PRI[s.priority]}</span>` : ''}${note ? '<span class="task-dot"><span class="sr-only">有同事的新意见</span></span>' : ''}<button type="button" class="btn icon small quiet task-more" data-action="edit-task" data-id="${t.id}" aria-label="编辑「${esc(t.title)}」">${icon('more')}</button></div>
        <button type="button" class="task-title" data-action="select-task" data-id="${t.id}" ${t.id === a.selectedTaskId ? 'aria-current="true"' : ''} aria-describedby="move-help">${esc(t.title)}</button>
        <div class="task-foot">${statusIcon(t.status)}<span>${STATUS[t.status]}</span>${n ? `<span class="tertiary">${n} 份作品</span>` : ''}${stale(t.id) ? `<span class="stale-mark" title="这件事的测试是在条件变化前做的">${icon('stale', 'i-sm')}条件变了</span>` : ''}</div>
      </li>`; };
    return `<div class="shelf-head"><h2>手头的事</h2><span class="t-sub tertiary hide-sm">拖到另一组就是改优先级；也可以用 ⌥ 加方向键。</span><div class="spacer"></div>${btn(icon('bubble', 'i-sm') + '问问优先级', 'priority-view', 'small quiet' + (view ? ' on' : ''))}${btn(icon('plus', 'i-sm') + '新事项', 'new-task', 'small')}</div>
      ${view ? `<div class="pv-strip"><div class="segmented" role="group" aria-label="谁的建议"><span class="thumb"></span>${ROLES.map(r => `<button type="button" aria-pressed="${view === r}" data-action="pv-role" data-role="${r}">${PEOPLE[r].name}</button>`).join('')}</div><p class="pv-why">${avatar(view, 'sm')}<span>${esc(sug.why)}</span></p><div class="hstack">${sug.items.length ? btn('按此排列', 'apply-suggestion', 'small') : ''}${btn('关闭', 'priority-view', 'small quiet')}</div></div>` : ''}
      <p id="move-help" class="sr-only">按住 Option 或 Alt：上下方向键换优先级组，左右方向键调整顺序。</p>
      <div class="lanes">
        ${policyNew ? `<div class="situation" role="status"><p class="sit-head">${icon('bolt', 'i-sm')}新情况</p><p class="sit-text">差旅住宿政策更新为 v2：上限从每晚 500 降到 400。</p><p class="sit-who">${avatar('business', 'sm')}<span>${L ? '后端政策更新事件，查看原文后再调整。' : 'Mei：员工会按旧金额订酒店。'}</span></p><div class="sit-actions"><button type="button" class="link-btn" data-action="open-material" data-id="policy">看变化</button><button type="button" class="link-btn" data-action="situation-task">新建事项</button><button type="button" class="link-btn" data-action="ack" data-key="policy-v2">先不处理</button></div></div>` : ''}
        ${groups.map(g => { const list = a.tasks.filter(t => t.priority === g); return `<div class="lane ${g} ${list.length ? '' : 'vacant'}" data-lane="${g}"><p class="lane-label"><span class="pri ${g}">${PRI[g]}</span><span class="tertiary">${list.length}</span></p><ol class="shelf" role="list">${list.map(card).join('')}${!list.length ? `<li class="lane-drop">拖到这里</li>` : ''}</ol></div>`; }).join('')}
      </div>`;
  }
  function wsCanvas(a) {
    const t = task();
    const tabs = [['work', '这件事', t ? taskWorks(a, t.id).length : ''], ['materials', '资料', ''], ['lab', '助手测试', a.tests.length || '']];
    return `<div class="canvas-head">
        <div class="segmented" role="group" aria-label="中央内容"><span class="thumb"></span>${tabs.map(([id, label, n]) => `<button type="button" aria-pressed="${ui.pane === id}" data-action="pane" data-pane="${id}">${label}${n !== '' && n !== 0 ? `<span class="count">${n}</span>` : ''}</button>`).join('')}</div>
        <div class="spacer"></div>
        ${t ? `<span class="canvas-task t-sub secondary hide-sm">${statusIcon(t.status)}${esc(t.title)}</span>` : ''}
        ${btn(icon('plus', 'i-sm') + '<span class="hide-sm">新作品</span>', 'new-artifact', 'small quiet', 'aria-label="新作品"')}
      </div>
      <div class="canvas-body" id="canvas-body">${ui.pane === 'materials' ? paneMaterials(a) : ui.pane === 'lab' ? paneLab(a) : t ? paneWork(a, t) : paneStart(a)}</div>`;
  }
  function paneStart(a) {
    const c = CASES[a.scenarioId] || CASES.pilot;
    return `<div class="start">
      <article class="start-brief"><p class="t-sub tertiary">经理的试点委托</p><blockquote class="brief-quote big">${avatar('manager')}<div><p>“${c.quote}”</p><cite>Priya，经理</cite></div></blockquote></article>
      <p class="start-lead">从哪里开始都可以。</p>
      <div class="start-actions">
        <button type="button" class="link-btn big" data-action="start-note">${icon('doc')}写下第一个想法</button>
        <button type="button" class="link-btn big" data-action="pane" data-pane="lab">${icon('flask')}去测试台问一个问题</button>
        <button type="button" class="link-btn big" data-action="chat" data-role="manager">${icon('bubble')}问问 Priya</button>
      </div>
      <p class="t-sub tertiary">也可以在上面选一件事。顺序没有标准答案。</p>
    </div>`;
  }
  function paneWork(a, t) {
    const list = taskWorks(a, t.id);
    let x = artifact(); if (!x || x.taskId !== t.id || isEarlier(a, x)) { x = list.at(-1) || null; ui.artifactId = x ? x.id : null; }
    const who = /政策/.test(t.title) ? 'technical' : /决定/.test(t.title) ? 'manager' : 'business';
    if (!x) return `<div class="empty work-empty"><h3>${esc(t.title)}</h3><p>${esc(t.note || '写下你准备弄清的问题。')}</p>
        <div class="start-actions">
          <button type="button" class="link-btn big" data-action="quick-note">${icon('doc')}写下想法</button>
          <button type="button" class="link-btn big" data-action="pane" data-pane="lab">${icon('flask')}试试助手</button>
          <button type="button" class="link-btn big" data-action="chat" data-role="${who}">${icon('bubble')}问问 ${PEOPLE[who].name}</button>
        </div></div>`;
    const view = shown(x);
    const intent = E.intentOf(view.purpose);
    const prog = E.agentProgress(a, x);
    const notes = marginNotes(a, x, t);
    return `<div class="doc-tabs" role="group" aria-label="这件事的作品">${list.map(w => `<button type="button" aria-pressed="${w.id === x.id}" data-action="open-artifact" data-id="${w.id}"><span class="tab-name">${esc(w.title)}</span>${w.parentArtifactId ? '<small>修订</small>' : ''}${w.source !== 'user' && !w.adopted ? '<small class="warn">待检查</small>' : ''}</button>`).join('')}</div>
      <div class="doc-grid ${notes.length ? 'with-margin' : ''}">
        <article class="editor">
          ${prog ? `<div class="agent-progress" aria-label="Agent 协作进度"><ol>${[['exported', '已导出'], ['returned', '已回传'], ['adopted', '已采用'], ['linked', prog.linkedRuns ? '关联测试 ' + prog.linkedRuns + ' 次' : '还没关联测试']].map(([k, l]) => `<li class="${prog[k] ? 'done' : ''}">${prog[k] ? icon('check', 'i-sm') : ''}${l}</li>`).join('')}</ol>${!x.adopted ? `<div class="hstack">${ui.editPending === x.id ? '' : btn('编辑', 'edit-pending', 'small quiet', `data-id="${x.id}"`)}${btn('采用', 'adopt', 'small primary', `data-id="${x.id}"`)}</div>` : ''}</div>${(x.staleInputs || []).length ? `<p class="draft-note">${icon('stale', 'i-sm')}它是按你较早的版本写的，你后来又改过，采用前先对照。</p>` : ''}` : ''}
          <label class="sr-only" for="editor-title">作品标题</label>
          <input id="editor-title" class="editor-title" data-edit="title" maxlength="160" value="${esc(view.title)}">
          <div class="editor-meta">
            <label class="purpose"><span class="sr-only">这份作品现在的用途</span><select data-edit="purpose" aria-label="作品用途">${E.PURPOSES.map(p => `<option ${p === view.purpose ? 'selected' : ''}>${p}</option>`).join('')}</select></label>
            <span data-revision>v${x.revision}</span><span>${x.source === 'user' ? '你写的' : '来自你的 Agent'}</span><span data-save></span>
          </div>
          <p class="intent-line">${INTENT_LINE[intent]}</p>
          ${!x.adopted && ui.editPending !== x.id ? `<div class="prose pending-preview">${md(view.body)}</div>` : `<label class="sr-only" for="editor-body">正文</label>
          <textarea id="editor-body" class="editor-body" data-edit="body" maxlength="50000" spellcheck="false" placeholder="你现在想弄清什么？\n\n可以写初步判断、要问的问题，或者直接起草方案。## 写小标题，- 开头写列表。">${esc(view.body)}</textarea>`}
          ${x.evidence.length ? `<div class="evidence-row"><span class="t-sub tertiary">依据</span>${x.evidence.map(ev => `<button type="button" class="evidence" data-action="view-evidence" data-id="${esc(ev.id)}" data-version="${esc(ev.version ?? '')}">${icon(ev.type === 'test' ? 'flask' : 'book', 'i-sm')}${esc(ev.title || ev.id)}${ev.version ? ' v' + ev.version : ''}</button>`).join('')}</div>` : ''}
        </article>
        ${notes.length ? `<aside class="margin" aria-label="同事的意见">${notes.map(marginNote).join('')}</aside>` : ''}
      </div>
      <div class="action-bar">
        ${btn(icon('quote', 'i-sm') + '引用依据', 'pane', 'small quiet', 'data-pane="materials"')}
        ${btn(icon('bubble', 'i-sm') + '问同事', 'discuss-artifact', 'small quiet')}
        ${btn(icon('agent', 'i-sm') + '交给我的 Agent', 'agent', 'small quiet')}
        <div class="spacer"></div>
        ${btn('请求评审', 'review-artifact', 'small')}
      </div>`;
  }
  function marginNotes(a, x, t) {
    const all = openNotes(a, n => n.targetId === x.id || (!n.targetId && n.taskId === t.id));
    const latest = new Map(); all.forEach(n => latest.set(n.roleId, n));
    return [...latest.values()].slice(-2);
  }
  function refreshMargin() {
    const a = current(); const x = artifact(); const t = task(); const grid = document.querySelector('.doc-grid');
    if (!a || !x || !t || !grid) return;
    const notes = marginNotes(a, x, t);
    let margin = grid.querySelector('.margin');
    grid.classList.toggle('with-margin', notes.length > 0);
    if (!notes.length) { margin?.remove(); return; }
    if (!margin) { margin = document.createElement('aside'); margin.className = 'margin'; margin.setAttribute('aria-label', '同事的意见'); grid.appendChild(margin); }
    margin.innerHTML = notes.map(marginNote).join('');
    notes.forEach(n => ui.known.add(n.id));
  }
  function marginNote(n) {
    const p = PEOPLE[n.roleId];
    return `<div class="note ${n.kind}" data-note="${n.id}"><p class="note-head">${avatar(n.roleId, 'sm')}<b>${p.name}</b><span class="note-kind">${KIND[n.kind] || '提醒'}</span></p><p class="note-text">${esc(n.text)}</p><div class="note-actions"><button type="button" class="link-btn" data-action="reply-note" data-id="${n.id}">回应</button><button type="button" class="link-btn quiet" data-action="later-note" data-id="${n.id}">稍后</button></div></div>`;
  }
  function paneMaterials(a) {
    const list = E.getMaterials(a);
    if (L && !list.length) return `<div class="empty"><p>尚未取得后端资料，请检查连接后刷新。${btn("刷新状态", "live-refresh", "small")}</p></div>`; const m = list.find(x => x.id === ui.materialId) || list[0]; ui.materialId = m.id;
    const read = new Set(a.events.filter(e => e.type === 'material_read').map(e => e.detail && e.detail.materialId));
    return `<div class="materials">
      <nav class="material-list" aria-label="资料">${list.map(x => `<button type="button" class="material-item ${x.id === m.id ? 'on' : ''}" data-action="open-material" data-id="${x.id}" aria-current="${x.id === m.id}"><span class="grow"><span class="row-title">${esc(x.title)}</span><span class="row-sub">v${x.version}${read.has(x.id) ? '' : '，未读'}</span></span>${x.id === 'policy' && a.world.policyVersion > 1 ? `<span class="new-dot"><span class="sr-only">有更新</span></span>` : ''}</button>`).join('')}</nav>
      <article class="reader">
        <header><h2 class="t-title2">${esc(m.title)}</h2><p class="t-sub tertiary">来源版本 v${m.version}${m.id === 'policy' ? `，知识助手当前用的索引是 v${a.world.indexVersion}` : ''}</p></header>
        <div class="prose">${md(m.body)}</div>
        <div class="action-bar flat">${btn(icon('quote', 'i-sm') + '加入当前作品的依据', 'cite-material', 'small', `data-id="${m.id}"`)}${btn(icon('bubble', 'i-sm') + '就这份问同事', 'discuss-material', 'small quiet', `data-id="${m.id}"`)}</div>
      </article>
    </div>`;
  }
  function paneLab(a) {
    const c = a.config; const stale = a.world.indexVersion < a.world.policyVersion; const t = task();
    return `<div class="lab">
      <form class="lab-compose" data-form="run-test">
        <label class="sr-only" for="lab-q">你想问助手什么</label>
        <textarea id="lab-q" name="question" class="lab-q" rows="2" required maxlength="4000" placeholder="像真实员工那样问它一个问题…">${esc(L ? (L.session(a)?.inputs.question || ui.labPrefill) : ui.labPrefill)}</textarea>
        <div class="lab-row">
          <label class="sr-only" for="lab-e">你想确认什么（选填）</label>
          <input id="lab-e" name="expectation" value="${esc(L ? L.session(a)?.inputs.expected || '' : '')}" class="input" maxlength="5000" placeholder="想确认什么？选填，例如：它引用的是不是最新政策">
          <button type="submit" class="btn primary" ${ui.busy ? 'disabled' : ''}>${icon('play', 'i-sm')}${ui.busy ? '运行中' : '运行'}</button>
        </div>
      </form>
      <div class="lab-config">
        <span class="t-sub secondary">${L && !a.backend.configured ? '尚未设置，请先应用配置' : '这次会用'}</span>
        <span class="cfg">配置 v${a.configVersion}</span><span class="cfg">${c.participants} 人</span><span class="cfg">${c.domains.map(d => d === 'faq' ? '办公 FAQ' : '差旅政策').join(' + ') || '未开放任何知识'}</span><span class="cfg">${UPDATE_NAMES[c.update]}</span><span class="cfg ${stale ? 'warn' : ''}">政策源 v${a.world.policyVersion}，索引 v${a.world.indexVersion}${stale ? '（落后）' : ''}</span>
        <div class="spacer"></div>
        ${stale ? btn(icon('refresh', 'i-sm') + '刷新索引', 'refresh-index', 'small quiet') : ''}${btn(icon('gear', 'i-sm') + '试点设置', 'config', 'small quiet')}
      </div>
      ${t ? `<p class="t-sub tertiary">结果会记在「${esc(t.title)}」下。</p>` : ''}
      ${a.configDraft ? `<p class="draft-note">${icon('info', 'i-sm')}有一份没生效的设置草案，正在用的仍是 v${a.configVersion}。${btn('看草案', 'config', 'small quiet')}</p>` : ''}
      <div class="runs">${a.tests.length ? groupRuns(a).map(g => runGroup(a, g)).join('') : `<div class="empty compact"><p>还没有测试。一次和预期不符的回答，往往比十次顺利的更有用。</p></div>`}</div>
    </div>`;
  }
  function groupRuns(a) {
    const map = new Map();
    a.tests.slice().reverse().forEach(r => { const k = r.question.trim(); if (!map.has(k)) map.set(k, []); map.get(k).push(r); });
    return [...map.values()];
  }
  function runGroup(a, runs) {
    const r = runs[0];
    const old = x => x.citations.some(c => c.id === 'policy' && c.version < x.policyVersion);
    return `<article class="run ${r.id === ui.lastRun ? 'fresh' : ''}" id="run-${r.id}">
      <header><h3>${esc(r.question)}</h3><span class="t-foot tertiary">${runs.length > 1 ? runs.length + ' 次，' : ''}${when(r.createdAt)}</span></header>
      ${r.expectation ? `<p class="run-expect">想确认：${esc(r.expectation)}</p>` : ''}
      <div class="run-compare ${runs.length > 1 ? 'multi' : ''}">${runs.slice(0, 2).map((x, i) => `<div class="run-col">${runs.length > 1 ? `<p class="t-foot tertiary">${i === 0 ? '最新' : '上一次'}</p>` : ''}<div class="answer">${assistantMark()}<p>${esc(x.answer)}</p></div>
        <div class="run-meta"><span class="stamp">${L ? '后端 · ' + esc(x.mode) : '知识助手（规则模拟）'}</span><span class="stamp">配置 v${x.configVersion}</span><span class="stamp ${old(x) ? 'warn' : ''}">${old(x) ? icon('stale', 'i-sm') : ''}政策源 v${x.policyVersion} / 索引 v${x.indexVersion}</span>${x.citations.map(c => `<button type="button" class="evidence ${old(x) ? 'stale' : ''}" data-action="run-source" data-run="${x.id}">${icon('book', 'i-sm')}${esc(c.title)}</button>`).join('')}</div></div>`).join('')}</div>
      ${old(r) ? `<p class="flag">${icon('warn', 'i-sm')}这次引用的索引比当时的政策旧。</p>` : ''}
      <div class="run-actions">${btn('同题重测', 'rerun', 'small quiet', `data-id="${r.id}"`)}${btn('作为依据', 'cite-run', 'small quiet', `data-id="${r.id}"`)}${btn('和 Daniel 讨论', 'discuss-run', 'small quiet', `data-id="${r.id}"`)}</div>
    </article>`;
  }

  /* ---------- inspector: talk / feedback / record ---------- */
  function wsInspector(a) {
    const tabs = [['talk', '讨论'], ['feedback', '反馈'], ['record', '记录']];
    const body = ui.inspector === 'feedback' ? inspFeedback(a) : ui.inspector === 'record' ? inspRecord(a) : ui.chatRole ? inspChat(a, ui.chatRole) : inspPeople(a);
    return `<div class="insp-head"><div class="segmented" role="group" aria-label="侧栏内容"><span class="thumb"></span>${tabs.map(([k, l]) => `<button type="button" aria-pressed="${ui.inspector === k}" data-action="insp-tab" data-tab="${k}">${l}${k === 'talk' && unread(a) ? '<span class="tab-dot"></span>' : ''}</button>`).join('')}</div>${btn(icon('x'), 'close-inspector', 'icon small quiet', 'aria-label="关闭侧栏"')}</div><div class="insp-body">${body}</div>`;
  }
  function inspPeople(a) {
    return `<div class="group">${ROLES.map(role => { const last = (a.nudges || []).filter(n => n.roleId === role && !n.read).at(-1); const hist = a.conversations[role] || []; const line = last ? last.text : (hist.at(-1)?.text || '知道' + PEOPLE[role].knows); return `<button type="button" class="row with-lead person-row ${last ? 'has-note' : ''}" data-action="chat" data-role="${role}">${avatar(role, '', !!last)}<span class="grow"><span class="row-title">${PEOPLE[role].name}<small> ${PEOPLE[role].role}</small></span><span class="row-sub clamp">${esc(line)}</span></span>${icon('chev', 'chev')}</button>`; }).join('')}</div>
      <p class="insp-note">三位同事各自只知道一部分；他们可能帮你，也可能反对或纠正你。${L ? '回复来自独立 worker，当前运行器不传递跨回合历史。' : '回复是规则模拟。'}</p>`;
  }
  function inspChat(a, role) {
    E.markNudgesRead(a, role); persist();
    const p = PEOPLE[role]; const t = task(); const msgs = a.conversations[role] || []; const x = artifact();
    return `<div class="chat">
      <header class="chat-head">${btn(icon('back'), 'people', 'icon quiet small', 'aria-label="返回同事列表"')}${avatar(role)}<div class="grow"><b>${p.name}</b><small>${p.role}，知道${p.knows}</small></div></header>
      <div class="thread" role="log" aria-live="polite">${msgs.length ? msgs.map(m => `<div class="msg ${m.role === 'user' ? 'me' : 'them'} ${m.proactive ? 'proactive ' + (m.kind || '') : ''}">${m.proactive ? `<span class="msg-tag">${p.name} 主动${KIND_VERB[m.kind] || '说了一句'}</span>` : ''}<p>${esc(m.text)}</p><span class="msg-time">${when(m.createdAt)}${L && m.model ? esc(m.model) : ''}</span></div>`).join('') : `<div class="chat-empty">${avatar(role, 'lg')}<p>${role === 'manager' ? '可以聊目标、资源和先后顺序。' : role === 'business' ? '可以聊首批员工真正要问什么、政策怎么变。' : '可以聊系统限制、测试结果和索引。'}</p></div>`}</div>
      <div class="chat-context">${t ? `<span class="ctx">关于「${esc(t.title)}」</span>` : ''}${x ? `<button type="button" class="ctx add" data-action="prefill-artifact">${icon('plus', 'i-sm')}附上「${esc(x.title)}」</button>` : ''}${a.tests.length ? `<button type="button" class="ctx add" data-action="prefill-run">${icon('plus', 'i-sm')}附上最近的测试</button>` : ''}</div>
      <form class="composer" data-form="chat"><label class="sr-only" for="chat-input">给 ${p.name} 的消息</label><textarea id="chat-input" name="text" rows="2" maxlength="4000" required placeholder="写给 ${p.name}…">${esc(L ? L.session(a)?.inputs.messages[{ manager: 'supervisor', business: 'business_lead', technical: 'tech_lead' }[role]] || '' : '')}</textarea><button type="submit" class="btn icon primary" aria-label="发送">${icon('send')}</button></form>
    </div>`;
  }
  function inspFeedback(a) {
    if (L) return liveFeedback(a);
    const t = task();
    const items = E.coach(a).items.filter(i => !t || !i.taskId || i.taskId === t.id);
    return `<p class="insp-note">${t ? '与「' + esc(t.title) + '」有关的观察。' : '整件工作的观察。'}普通编辑时不会打扰你；请求评审或交付时会更完整。</p>${items.length ? `<ol class="feedback compact">${items.map(i => fbItem(a, i, true)).join('')}</ol>` : '<p class="group-empty">从现有记录里，暂时没有需要提醒的地方。这不等于论证已经成立。</p>'}<p class="t-foot tertiary">规则示意：根据已发生的记录生成，不是 LLM 评审，不打分。</p>`;
  }
  function inspRecord(a) {
    const x = artifact();
    const evs = a.events.filter(e => !/material_read|task_updated|review_requested|priority_suggested/.test(e.type)).slice(-14).reverse();
    return `<section><h3 class="group-title">${x ? '「' + esc(x.title) + '」的依据' : '依据'}</h3><div class="group">${x && x.evidence.length ? x.evidence.map(ev => `<button type="button" class="row" data-action="view-evidence" data-id="${esc(ev.id)}" data-version="${esc(ev.version ?? '')}"><span class="grow"><span class="row-title t-callout">${esc(ev.title || ev.id)}</span><span class="row-sub">${ev.type === 'test' ? '测试记录' : '资料'}${ev.version ? '，v' + ev.version : ''}</span></span>${icon('chev', 'chev')}</button>`).join('') : `<p class="group-empty">${x ? '还没有引用。在资料或测试里点“加入依据”。' : '打开一份作品后，这里显示它引用的资料和测试。'}</p>`}</div></section>
      <section><h3 class="group-title">条件</h3><div class="group"><dl class="facts list"><div><dt>试点容量</dt><dd>${a.world.capacity} 人</dd></div><div><dt>可用开发</dt><dd>${a.world.devDays} 人日</dd></div><div><dt>期望上线</dt><dd>第 ${a.world.deadline} 天</dd></div><div><dt>配置</dt><dd>v${a.configVersion}${a.configDraft ? '，有草案' : ''}</dd></div></dl>
        <button type="button" class="row" data-action="resources"><span class="grow"><span class="row-title t-callout">申请资源或延期</span><span class="row-sub">${a.requests.length ? a.requests.map(r => ({ pending: 'Priya 正在看', approved: '已批准', 'needs-info': 'Priya 需要你说明' })[r.status] || '已处理').join('，') : '要经理批准才会改变条件'}</span></span>${icon('chev', 'chev')}</button></div></section>
      <section><h3 class="group-title">刚刚发生的</h3><ol class="timeline">${evs.map(e => `<li><span class="tl-dot ${e.type}"></span><span class="grow">${esc(eventLine(a, e))}</span><time class="t-foot tertiary">${when(e.createdAt)}</time></li>`).join('')}</ol></section>
      <details class="demo-ctl"><summary>演示控制</summary><p>用来体验场景变化，不属于产品功能。正常情况下，政策会在你做了三次业务操作后自己变。</p>${btn(a.world.policyVersion > 1 ? '政策已更新' : '现在更新政策', 'policy-update', 'small', a.world.policyVersion > 1 ? 'disabled' : '')}</details>`;
  }
  function fbItem(a, i, compact = false, subId = '') {
    const toneIcon = i.kind === 'order' ? 'branch' : { good: i.kind === 'contribution' ? 'star' : 'good', check: 'warn', unknown: 'question' }[i.tone];
    const toneName = i.kind === 'contribution' ? '计划外的贡献' : i.kind === 'order' ? '想一想' : { good: '做得对的地方', check: '值得再看', unknown: '证据里看不到' }[i.tone];
    const key = subId + '|' + i.title; const disputes = (a.disputes || []).filter(d => d.key === key);
    return `<li class="fb ${i.tone} ${i.kind || ''}"><div class="fb-icon">${icon(toneIcon)}</div><div class="fb-body">
      <h4><span class="sr-only">${toneName}：</span>${esc(i.title)}</h4>
      <p class="fb-observed"><span class="fb-label">看到</span>${esc(i.observed)}</p>
      ${i.basis ? `<p class="fb-basis"><span class="fb-label">当时可知</span>${esc(i.basis)}</p>` : ''}
      <p class="fb-why"><span class="fb-label">为什么重要</span>${esc(i.why)}</p>
      ${i.actions.length ? `<div class="fb-actions">${i.actions.map(x => `<button type="button" class="link-btn" data-action="fb-act" data-act="${x.act}" data-id="${esc(x.id || '')}" data-role="${x.role || ''}" data-task="${i.taskId || ''}">${esc(x.label)}</button>`).join('')}</div>` : ''}
      ${!compact ? `<div class="fb-refs">${i.refs.map(r => `<button type="button" class="evidence" data-action="open-ref" data-type="${r.type}" data-id="${r.id}" data-task="${i.taskId || ''}">${icon(r.type === 'test' ? 'flask' : r.type === 'artifact' ? 'doc' : 'bolt', 'i-sm')}${esc(r.label)}</button>`).join('')}<button type="button" class="link-btn quiet" data-action="dispute" data-key="${esc(key)}">我有不同看法</button></div>
      ${ui.disputeOpen === key ? `<form class="dispute" data-form="dispute" data-key="${esc(key)}"><label class="sr-only" for="dispute-text">你的不同看法</label><textarea id="dispute-text" class="textarea" name="text" rows="2" required maxlength="2000" placeholder="哪里不对？例如：我在决定里写了转人工，只是没引用测试。"></textarea><div class="hstack"><button type="submit" class="btn small primary">记下</button>${btn('取消', 'dispute', 'small quiet', `data-key="${esc(key)}"`)}</div></form>` : ''}
      ${disputes.map(d => `<p class="dispute-note">${icon('bubble', 'i-sm')}<span>你的看法：${esc(d.text)}<span class="tertiary">（已记在这次练习里；原型不会自动复核）</span></span></p>`).join('')}` : ''}
    </div></li>`;
  }

  function eventLine(src, e) {
    const d = e.detail || {};
    if (e.type === 'test_run') { const r = (src.tests || []).find(x => x.id === d.testId); return r ? '测试：' + r.question : e.text; }
    if (e.type === 'colleague_nudged') { const n = (src.nudges || []).find(x => x.id === d.nudgeId); return PEOPLE[d.roleId] ? PEOPLE[d.roleId].name + ' 主动' + (n && KIND_VERB[n.kind] ? KIND_VERB[n.kind] : '说了一句') : e.text; }
    if (e.type === 'policy_updated') return '新情况：差旅政策更新为 v2（500 → 400）';
    if (e.type === 'submitted') return '交付';
    return e.text;
  }

  /* ---------- 4. review ---------- */
  function renderReview() {
    if (L) return `<header class="topbar">${btn("工作台", "to-work", "quiet")}${proto}</header><main id="main" class="page" tabindex="-1"><h1>交付与反馈</h1>${liveFeedback(current())}</main>`;
    const a = current(); const subs = a.submissions;
    const head = `<header class="topbar">${btn(icon('back') + '<span>工作台</span>', 'to-work', 'quiet back')}<div class="title-wrap"><span class="title-static">复盘：${esc(caseTitle(a))}</span></div><div class="spacer"></div>${proto}</header>`;
    if (!subs.length) return `${head}<main id="main" class="page review" tabindex="-1"><div class="empty big"><h3>交付之后，这里会还原你的判断和它带来的结果</h3><p>不用等到完美。把现在的判断交出去，写清还不知道什么，之后可以接着修订。</p>${btn('回到工作台', 'to-work', 'primary')}</div></main>`;
    const sub = subs.find(s => s.id === ui.reviewSubmissionId) || subs[subs.length - 1]; ui.reviewSubmissionId = sub.id;
    const coach = E.coach(a, sub); const tasks = sub.tasks || [];
    const sel = ui.reviewTaskId && tasks.some(t => t.id === ui.reviewTaskId) ? ui.reviewTaskId : null;
    const items = coach.items.filter(i => !sel || i.taskId === sel);
    const delivered = sub.artifacts.filter(w => !sel || w.taskId === sel);
    const idx = subs.indexOf(sub);
    const policyAt = (sub.events || []).find(e => e.type === 'policy_updated');
    const ownTasks = tasks.filter(t => !t.seed && !SEED.includes(t.title) && t.origin !== 'situation').length;
    const beforePolicy = policyAt ? sub.tests.filter(t => t.policyVersion < 2).length : 0;
    const worked = tasks.filter(t => sub.artifacts.some(w => w.taskId === t.id) || sub.tests.some(r => r.taskId === t.id)).length;
    const summary = `这一轮共 ${tasks.length} 件事${ownTasks ? `（${ownTasks} 件是你加的）` : ''}，其中 ${worked} 件留下了作品或测试；测试 ${sub.tests.length} 次${policyAt ? `，${beforePolicy} 次在政策更新之前` : ''}；交了 ${sub.artifacts.length} 份作品。`;
    const flow = (sub.events || []).filter(e => ['test_run', 'artifact_created', 'artifact_saved', 'policy_updated', 'colleague_nudged', 'config_applied', 'config_draft', 'resource_requested', 'resource_approved', 'artifact_adopted', 'task_added', 'submitted'].includes(e.type));
    return `${head}<main id="main" class="page review" tabindex="-1">
      <header class="review-head">
        <div class="hstack wrap"><h1 class="t-large">${idx === 0 ? '第一次交付' : '第 ' + (idx + 1) + ' 次交付'}${sub.parentSubmissionId ? '<span class="tertiary t-title3">，修订</span>' : ''}</h1><div class="spacer"></div>${subs.length > 1 ? `<div class="segmented" role="group" aria-label="选择交付"><span class="thumb"></span>${subs.map((s, i) => `<button type="button" aria-pressed="${s.id === sub.id}" data-action="pick-submission" data-id="${s.id}">第 ${i + 1} 次</button>`).join('')}</div>` : ''}</div>
        <p class="review-summary">${summary}</p>
        <div class="flow" role="img" aria-label="动作顺序：共 ${flow.length} 个动作${policyAt ? '，政策更新发生在第 ' + (flow.indexOf(policyAt) + 1) + ' 个' : ''}">${flow.map(e => `<span class="flow-dot ${e.type}" title="${esc(eventLine(a, e))}"></span>`).join('')}<span class="flow-legend">${policyAt ? '<span class="flow-dot policy_updated"></span>政策更新' : ''}<span class="flow-dot test_run"></span>测试<span class="flow-dot colleague_nudged"></span>同事意见<span class="flow-dot submitted"></span>交付</span></div>
      </header>
      <section class="shelf-wrap review-shelf" aria-label="按事项查看"><ol class="shelf" role="list">
        <li class="task-card all ${sel ? '' : 'on'}"><button type="button" class="task-title" data-action="review-task" data-id="" ${!sel ? 'aria-current="true"' : ''}>全部事项</button><div class="task-foot"><span>${coach.items.length} 条反馈</span></div></li>
        ${tasks.map(t => { const n = coach.items.filter(i => i.taskId === t.id).length; return `<li class="task-card ${t.id === sel ? 'on' : ''}" style="view-transition-name: t-${vtName(t.id)}"><div class="task-top"><span class="pri ${t.priority}">${PRI[t.priority]}</span></div><button type="button" class="task-title" data-action="review-task" data-id="${t.id}" ${t.id === sel ? 'aria-current="true"' : ''}>${esc(t.title)}</button><div class="task-foot">${statusIcon(t.status)}<span>${STATUS[t.status]}</span>${n ? `<span class="tertiary">${n} 条反馈</span>` : ''}</div></li>`; }).join('')}
      </ol></section>
      <div class="review-grid">
        <div class="review-main">
          <section class="block"><div class="group-title"><span>反馈</span><span class="tertiary">${esc(coach.label)}</span></div>
            ${items.length ? `<ol class="feedback">${items.map(i => fbItem(a, i, false, sub.id)).join('')}</ol>` : `<p class="group-empty pad">这件事在这次交付里没有可观察到的反馈。没有反馈不代表做得好或不好。</p>`}
          </section>
          <section class="block"><h2 class="group-title">你交付的内容</h2><div class="group">${delivered.length ? delivered.map(w => `<details class="delivered"><summary><span class="grow"><span class="row-title">${esc(w.title)}</span><span class="row-sub">${esc(w.purpose)}，v${w.revision}${w.source !== 'user' ? '，来自 Agent' : ''}</span></span>${icon('chev', 'chev')}</summary><div class="prose">${md(w.body)}</div></details>`).join('') : '<p class="group-empty">这次交付没有包含这件事的作品。</p>'}</div></section>
          <details class="block checks"><summary class="group-title"><span>记录核对</span><span class="tertiary">${(sub.review.observations || []).length} 项，只核对数值和版本</span></summary><div class="group">${(sub.review.observations || []).map(o => `<div class="row"><span class="check-dot ${o.status}"></span><span class="grow"><span class="row-title t-callout">${esc(o.title)}</span><span class="row-sub">${esc(o.text)}</span></span></div>`).join('')}</div></details>
        </div>
        <aside class="review-side">
          <section class="block"><h2 class="group-title">接下来</h2><div class="group">
            <button type="button" class="row with-lead" data-action="revise" data-id="${sub.id}"><span class="lead">${icon('revise')}</span><span class="grow"><span class="row-title">从这次交付继续修订</span><span class="row-sub">这一版保持不变，修改形成新版本</span></span>${icon('chev', 'chev')}</button>
            ${['urgent', 'capacity', 'pilot'].filter(id => id !== a.scenarioId).map(id => `<button type="button" class="row with-lead" data-action="practice-variant" data-case="${id}"><span class="lead">${icon('branch')}</span><span class="grow"><span class="row-title">换个条件：${CASES[id].title}</span><span class="row-sub">${CASES[id].change || '回到主情境'}。新练习，不带入这次的结论</span></span>${icon('chev', 'chev')}</button>`).join('')}
          </div></section>
          <section class="block"><h2 class="group-title">过程</h2><ol class="timeline">${(() => { let last = ''; return flow.slice(-12).reverse().map(e => { const w = when(e.createdAt); const show = w !== last; last = w; return `<li><span class="tl-dot ${e.type}"></span><span class="grow">${esc(eventLine(a, e))}</span>${show ? `<time class="t-foot tertiary">${w}</time>` : ''}</li>`; }).join(''); })()}</ol></section>
        </aside>
      </div>
    </main>`;
  }

  /* ---------- sheets ---------- */
  function openSheet(title, body, foot = '', cls = '') {
    commit();
    if (!sheet.open) sheetReturn = focusKey();
    sheet.className = 'sheet ' + cls;
    sheet.innerHTML = `<header class="sheet-head"><h2 id="sheet-title">${title}</h2>${btn(icon('x'), 'close', 'icon quiet small', 'aria-label="关闭"')}</header><div class="sheet-body">${body}</div>${foot ? `<footer class="sheet-foot">${foot}</footer>` : ''}`;
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
    openSheet(t ? '编辑事项' : '新事项', `<form data-form="task" data-id="${t ? t.id : ''}" class="stack-16" id="task-form">
        <label class="field"><span>要处理的事</span><input class="input" name="title" required maxlength="120" value="${esc(t ? t.title : '')}" placeholder="例如：问清政策多久变一次" autofocus></label>
        <label class="field"><span>补充 <small class="tertiary">选填</small></span><textarea class="textarea" name="note" rows="3" maxlength="5000" placeholder="想弄清的问题、已有线索、卡住的地方">${esc(t ? t.note : '')}</textarea></label>
        <fieldset class="field plain"><legend>优先级</legend><div class="choice-row">${Object.entries(PRI).map(([k, v]) => `<label class="choice"><input type="radio" name="priority" value="${k}" ${(t ? t.priority : 'next') === k ? 'checked' : ''}><span><span class="pri ${k}">${v}</span></span></label>`).join('')}</div></fieldset>
        ${t ? `<fieldset class="field plain"><legend>进展</legend><div class="choice-row">${Object.entries(STATUS).map(([k, v]) => `<label class="choice"><input type="radio" name="status" value="${k}" ${t.status === k ? 'checked' : ''}><span>${statusIcon(k)}${v}</span></label>`).join('')}</div></fieldset>
        <label class="field"><span>拆出一件新事 <small class="tertiary">选填</small></span><input class="input" name="split" maxlength="120" placeholder="从这件事里单独拿出来处理的部分"></label>` : ''}
      </form>`, `${t ? `${btn('左移', 'move-task', 'quiet', `data-id="${t.id}" data-dir="-1"`)}${btn('右移', 'move-task', 'quiet', `data-id="${t.id}" data-dir="1"`)}<span class="note"></span>` : ''}<button type="submit" form="task-form" class="btn primary">${t ? '保存' : '加入'}</button>`, 'narrow');
  }
  function sheetNewArtifact(purpose) {
    const a = current(); const t = task();
    openSheet('新作品', `<form data-form="artifact" id="artifact-form" class="stack-16">
      <label class="field"><span>标题</span><input class="input" name="title" required maxlength="160" placeholder="例如：我对首批范围的判断" value="${purpose === '试点决定' ? '试点决定' : ''}" autofocus></label>
      <fieldset class="field plain"><legend>它现在用来做什么</legend><div class="choice-row wrap">${E.PURPOSES.map(p => `<label class="choice"><input type="radio" name="purpose" value="${p}" ${p === (purpose || '探索笔记') ? 'checked' : ''}><span>${p}</span></label>`).join('')}</div><small class="tertiary">用途决定评审怎么看它：只有“试点决定”会被当作承诺核对。用途可以随时改。</small></fieldset>
      <label class="field"><span>属于哪件事</span><select class="select" name="taskId" required>${t || purpose ? '' : '<option value="" selected disabled>选一件事</option>'}${a.tasks.map(x => `<option value="${x.id}" ${(t ? x.id === t.id : purpose && (x.seed === 'decision' || /决定/.test(x.title))) ? 'selected' : ''}>${esc(x.title)}</option>`).join('')}</select></label>
    </form>`, `<button type="submit" form="artifact-form" class="btn primary">开始写</button>`, 'narrow');
  }
  function configChecks(a, c) {
    const cost = (c.workItems || []).reduce((n, k) => n + ({ scope: 1, fallback: 1, realtime: 5 }[k] || 0), 0) + (c.update === 'realtime' && !(c.workItems || []).includes('realtime') ? 5 : 0);
    const rows = [[`试点 ${c.participants} 人`, `容量 ${a.world.capacity} 人`, c.participants <= a.world.capacity], [`开发 ${cost} 人日`, `可用 ${a.world.devDays} 人日`, cost <= a.world.devDays], [`开放 ${(c.domains || []).length} 类知识`, '至少 1 类', (c.domains || []).length > 0]];
    return `<div class="checks-live" data-checks>${rows.map(([l, r, ok]) => `<p class="${ok ? 'ok' : 'bad'}">${icon(ok ? 'check' : 'x', 'i-sm')}<span>${l}</span><span class="tertiary">${r}</span></p>`).join('')}</div>`;
  }
  function sheetConfig() {
    const a = current(); const c = a.configDraft || (L && !a.backend.configured ? { participants: 20, domains: ["faq", "policy"], update: "daily", fallback: "human", workItems: ["scope", "fallback"], launchDay: a.world.deadline } : a.config);
    openSheet('试点设置', `<form data-form="config" id="config-form" class="stack-16">
      <p class="t-callout secondary">${L ? '保存后，下一次测试使用这份配置。超出资源的方案可以保存，但仍须另行申请并获批，保存不等于批准。' : '应用后，下一次测试才会用新设置。条件不满足时会留作草案，正在用的 v' + a.configVersion + ' 不变。'}</p>
      <label class="field"><span>试点人数</span><input class="input" type="number" name="participants" min="1" max="10000" value="${c.participants}" required></label>
      <fieldset class="field plain"><legend>开放的知识</legend><div class="group inset">${[['faq', '办公流程 FAQ'], ['policy', '差旅政策']].map(([k, v]) => `<label class="check-row"><input type="checkbox" name="domains" value="${k}" ${c.domains.includes(k) ? 'checked' : ''}>${v}</label>`).join('')}</div></fieldset>
      <fieldset class="field plain"><legend>政策怎么保持最新</legend><div class="choice-row wrap">${Object.entries(UPDATE_NAMES).map(([k, v]) => `<label class="choice"><input type="radio" name="update" value="${k}" ${c.update === k ? 'checked' : ''}><span>${v}</span></label>`).join('')}</div><small class="tertiary">每日索引最多滞后 24 小时；实时同步要 5 人日；转人工则不自动回答政策金额。</small></fieldset>
      <label class="field"><span>答不了或不确定时</span><select class="select" name="fallback">${Object.entries(FALLBACK_NAMES).map(([k, v]) => `<option value="${k}" ${c.fallback === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
      <fieldset class="field plain"><legend>要安排的开发</legend><div class="group inset">${[['scope', '知识范围过滤', 1], ['fallback', '人工入口', 1], ['realtime', '实时同步', 5]].map(([k, v, n]) => `<label class="check-row"><input type="checkbox" name="workItems" value="${k}" ${c.workItems.includes(k) ? 'checked' : ''}>${v}<small>${n} 人日</small></label>`).join('')}</div></fieldset>
      ${L ? `<label class="field"><span>计划上线日</span><input class="input" name="launchDay" type="number" min="1" value="${c.launchDay || a.world.deadline}" required></label>` : ''}
      ${configChecks(a, c)}
    </form>`, `${btn('申请资源', 'resources', 'quiet')}<button type="submit" form="config-form" class="btn primary">应用</button>`, '');
  }
  function sheetResources() {
    const a = current();
    if (L) return liveResources(a);
    openSheet('申请资源或延期', `<p class="t-callout secondary">由经理 Priya 处理（规则模拟）。聊天里说“可以试试”不算批准；批下来之后，配置也要你自己改。</p>
      <form data-form="resources" id="res-form" class="stack-12"><label class="field"><span>你需要什么，为什么</span><textarea class="textarea" name="reason" rows="4" required maxlength="5000" placeholder="为了……，希望开发资源增加到 6 人日，上线放到第 10 天。"></textarea></label></form>
      ${a.requests.length ? `<h3 class="brief-h">申请记录</h3><div class="group inset">${a.requests.slice().reverse().map(r => `<div class="row"><span class="grow"><span class="row-title t-callout">${esc(r.reason)}</span><span class="row-sub">${r.status === 'pending' ? 'Priya 正在看' : esc(r.result || '已处理')}</span></span></div>`).join('')}</div>` : ''}`, `<button type="submit" form="res-form" class="btn primary">提交申请</button>`, 'narrow');
  }
  function sheetAgent() {
    const a = current(); const t = task(); const sc = ui.exportScope;
    const read = new Set(a.events.filter(e => e.type === 'material_read').map(e => e.detail && e.detail.materialId)); read.add('brief');
    openSheet('我的 Agent', `<div class="agent-flow">
        <p class="t-callout secondary">把这件事交给你自己的 Agent，再把它的产出带回来检查。MCP 直连还在规划中；这里不会显示假的“已连接”或进度。</p>
        <section><h3 class="brief-h"><span class="step">1</span>选择要交出去的内容</h3>
          <div class="group inset">
            <label class="check-row"><input type="checkbox" checked disabled>${t ? '这件事：' + esc(t.title) : '整件工作（还没选具体的事）'}</label>
            <label class="check-row"><input type="checkbox" data-scope="artifacts" ${sc.artifacts ? 'checked' : ''}>${t ? '这件事的作品' : '已采用的作品'}<small>${(t ? works(a).filter(w => w.taskId === t.id) : works(a)).length} 份</small></label>
            <label class="check-row"><input type="checkbox" data-scope="materials" ${sc.materials ? 'checked' : ''}>你打开过的资料<small>${read.size} 份</small></label>
            <label class="check-row"><input type="checkbox" data-scope="tests" ${sc.tests ? 'checked' : ''}>测试记录<small>${a.tests.length} 次</small></label>
          </div>
          <p class="t-sub tertiary">不会包含同事的私有信息、未来事件或评价依据。</p>
          <div class="hstack wrap">${btn(icon('copy', 'i-sm') + '复制任务包', 'copy-package', 'small')}${btn(icon('download', 'i-sm') + '下载', 'download-package', 'small')}${btn('看看内容', 'package', 'small quiet')}</div></section>
        <section><h3 class="brief-h"><span class="step">2</span>带回它的产出</h3><form data-form="import" id="import-form" class="stack-12"><label class="sr-only" for="import-content">粘贴你的 Agent 的产出</label><textarea class="textarea" name="content" id="import-content" rows="5" required placeholder="粘贴 Markdown，或任务包里说明的 JSON 格式">${esc(ui.importText)}</textarea><label class="file-pick">${icon('upload', 'i-sm')}<span>或选择 .md / .txt / .json 文件</span><input type="file" id="import-file" accept=".md,.txt,.json,text/plain,application/json"></label></form></section>
        <section><h3 class="brief-h"><span class="step">3</span>检查、采用、验证</h3><p class="t-callout secondary">带回来的内容先是一份“待检查”作品，不覆盖你已有的东西。作品上会显示：已导出、已回传、已采用、关联了几次测试。它说的“通过了”不算数，要在助手测试里真正跑一遍并加为依据；测试是否真的支持结论，由你判断。</p></section>
      </div>`, `<button type="submit" form="import-form" class="btn primary">预览带回的内容</button>`, 'wide');
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
  function sheetSubmit() {
    const a = current();
    if (L) return liveDeliver(a); const list = works(a);
    const pending = a.artifacts.filter(x => x.source !== 'user' && !x.adopted);
    openSheet('交付这个版本', `<p class="t-callout secondary">会保存此刻的作品、设置和记录。交付之后还能继续修订，这一版保持不变。</p>
      <div class="group inset">${list.length ? list.map(w => `<div class="row"><span class="lead">${icon('doc')}</span><span class="grow"><span class="row-title t-callout">${esc(w.title)}</span><span class="row-sub">${esc(w.purpose)}，v${w.revision}</span></span></div>`).join('') : '<p class="group-empty">还没有已采用的作品。也可以交付——反馈会如实说明证据不够。</p>'}</div>
      ${pending.length ? `<p class="t-sub secondary">${pending.length} 份 Agent 回传还没采用，不会一起交付。</p>` : ''}
      <p class="t-sub tertiary">交付时的条件：配置 v${a.configVersion}，政策源 v${a.world.policyVersion}，索引 v${a.world.indexVersion}${a.configDraft ? '，另有一份未生效的草案' : ''}；${a.tests.length} 次测试。</p>
      <details class="disclosure"><summary>一份试点决定通常要交代什么</summary><p class="t-callout secondary">用户范围、知识范围、容量、更新方式、兜底、要做的开发、验收测试、成功指标、退出条件。可以分散在几份作品里；写明“还不知道”也是有效信息。这里只是提醒，不做核对。</p></details>`, `${btn('再看看', 'close', 'quiet')}${btn('交付', 'confirm-submit', 'primary')}`, 'narrow');
  }
  function sheetAbout() {
    if (L) return openSheet('连接与记录', `<div class="prose"><p>资料、三位同事、配置、申请审批、测试、交付、反馈与证据来自 RoleCraft API。后端当前模型：${esc(L.store.getSnapshot().model || '尚未连接')}。本地抽取模式不调用大模型。</p><p>自由事项、笔记、优先级和 Agent 文件导入保存在这个浏览器；正式交付需要另行保存并提交到后端。三同事尚无跨回合记忆，也不会由页面伪造主动回复。</p><p>后端提交后只读；关联修订和 MCP 接口尚未实现。演示版与连接版存档分开。</p><a href="/demo/">打开独立离线演示</a></div>`, `${btn('刷新连接', 'live-refresh', 'quiet')}${btn('导出本地笔记', 'export', 'quiet')}${btn('好', 'close', 'primary')}`, 'narrow');
    openSheet('这份原型是什么', `<div class="prose"><p>这是评审产品形态用的高仿真原型。选岗位、安排事项、写作品和版本、Agent 回传、交付快照和修订，都在你的浏览器里真实发生并保存。</p><p>三位同事和知识助手按本场景的规则回应，不调用大模型。同事的主动意见由明确的场景规则触发；政策会在你做了三次业务操作（测试、改配置、申请资源、采用回传）后更新。复盘里的反馈是根据已发生记录生成的规则示意，不是 LLM 评审，也不打分。资源审批是场景模拟。</p><p>还没有：真实后端、LLM、MCP 连接、账号与跨设备同步。清除站点数据会删掉这里的练习，可以先导出备份。</p></div>`, `${btn('导出备份', 'export', 'quiet')}${btn('好', 'close', 'primary')}`, 'narrow');
  }

  /* ---------- notes surfacing ---------- */
  function surfaceNewNotes(delay = 0) {
    const a = current(); if (!a) return;
    const fresh = (a.nudges || []).filter(n => !ui.known.has(n.id));
    fresh.forEach(n => ui.known.add(n.id));
    if (ui.route !== 'work') return;
    const t = task();
    const inMargin = x => ui.pane === 'work' && t && (x.targetId ? x.targetId === ui.artifactId : x.taskId === t.id);
    const situationShown = !!document.querySelector('.situation');
    const n = fresh.filter(x => !x.read && !inMargin(x) && !(situationShown && x.key === 'policy-v2')).at(-1); if (!n) return;
    const visible = document.querySelector(`[data-note="${n.id}"]`) || (ui.inspectorOpen && ui.inspector === 'talk' && ui.chatRole === n.roleId);
    if (visible) return;
    setTimeout(() => showPill(n), delay);
  }
  function showPill(n) {
    const host = document.getElementById('note-pill'); if (!host) return;
    const p = PEOPLE[n.roleId];
    host.innerHTML = `<button type="button" class="note-pill ${n.kind}" data-action="chat" data-role="${n.roleId}">${avatar(n.roleId, 'sm')}<span><b>${p.name}${KIND[n.kind] ? '，' + KIND[n.kind] : ''}</b>${esc(n.text)}</span></button>`;
    host.inert = false; requestAnimationFrame(() => host.classList.add('show'));
    clearTimeout(pillTimer); const hide = () => { if (host.matches(':hover, :focus-within')) { pillTimer = setTimeout(hide, 1500); return; } host.classList.remove('show'); host.inert = true; }; pillTimer = setTimeout(hide, 6500);
  }
  function seedKnown() { const a = current(); if (a) (a.nudges || []).forEach(n => ui.known.add(n.id)); }

  /* ---------- workspace refresh ---------- */
  function refreshWS(parts = ['shelf', 'canvas', 'inspector', 'toolbar']) {
    const a = current(); if (!a || ui.route !== 'work') { render(); return; }
    if (parts.includes('canvas') && dirty) flush();
    const key = focusKey();
    if (parts.includes('toolbar')) { const tb = document.querySelector('.ws-toolbar'); if (tb) tb.outerHTML = wsToolbar(a); }
    if (parts.includes('shelf')) document.getElementById('ws-shelf').innerHTML = wsShelf(a);
    if (parts.includes('canvas')) document.getElementById('ws-canvas').innerHTML = wsCanvas(a);
    if (parts.includes('inspector')) document.getElementById('ws-inspector').innerHTML = wsInspector(a);
    document.querySelector('.ws')?.classList.toggle('inspector-open', ui.inspectorOpen);
    afterRender();
    syncDrawer();
    restoreFocus(key);
  }
  function afterBusinessAction(a) { return E.maybeTriggerEvents(a); }
  const narrow = () => window.matchMedia('(max-width: 1024px)').matches;
  function syncDrawer() {
    const insp = document.getElementById('ws-inspector'); const scrim = document.querySelector('.inspector-scrim'); if (!insp) return;
    const hidden = !ui.inspectorOpen;
    insp.inert = hidden; if (scrim) { scrim.tabIndex = -1; scrim.setAttribute('aria-hidden', 'true'); }
    ['.ws-main > .canvas', '.shelf-wrap', '.ws-toolbar'].forEach(sel => { const n = document.querySelector(sel); if (n) n.inert = !hidden && narrow(); });
  }

  /* ---------- actions ---------- */
  function ensureArtifact() {
    const a = current(); const t = task();
    if (!t) return null;
    let x = artifact();
    if (x && x.taskId === t.id && !isEarlier(a, x) && x.adopted) return x;
    x = a.artifacts.filter(y => y.taskId === t.id && !isEarlier(a, y) && y.adopted).at(-1);
    if (!x) x = E.createArtifact(a, { taskId: t.id, title: '关于「' + t.title + '」的记录', purpose: '探索笔记', body: '' });
    ui.artifactId = x.id; return x;
  }
  function cite(ev) {
    const a = current(); const x = ensureArtifact();
    if (!x) { ui.pendingCite = ev; openSheet('加到哪件事的作品里', `<p class="t-callout secondary">还没选具体的事。选一件，依据会加到它最近的作品里（没有就新建一份记录）。</p><div class="group inset">${a.tasks.map(t => `<button type="button" class="row" data-action="cite-into" data-id="${t.id}"><span class="grow"><span class="row-title t-callout">${esc(t.title)}</span></span>${icon('chev', 'chev')}</button>`).join('')}</div>`, '', 'narrow'); return; }
    E.addEvidence(a, x.id, ev); persist(); notify('已加入「' + x.title + '」的依据');
  }
  function openChat(role, prefill = '') {
    const a = current(); ui.inspector = 'talk'; ui.chatRole = role; ui.inspectorOpen = true;
    if (ui.route !== 'work') { ui.route = 'work'; history.pushState(null, '', '#/work'); render(); }
    E.markNudgesRead(a, role); persist();
    refreshWS(['inspector', 'toolbar', 'shelf']);
    const input = document.getElementById('chat-input'); if (input) { if (prefill) input.value = prefill; input.focus(); }
  }
  function flip(mutate) {
    const sel = '.lanes .task-card';
    const before = new Map([...document.querySelectorAll(sel)].map(el => [el.dataset.taskId, el.getBoundingClientRect()]));
    mutate();
    if (reduceMotion.matches) return;
    document.querySelectorAll(sel).forEach(el => { const b = before.get(el.dataset.taskId); if (!b) { el.animate([{ opacity: 0, transform: 'scale(.96)' }, { opacity: 1, transform: 'none' }], { duration: 300, easing: 'cubic-bezier(.32,.72,0,1)' }); return; } const r = el.getBoundingClientRect(); const dx = b.left - r.left, dy = b.top - r.top; if (dx || dy) el.animate([{ transform: `translate(${dx}px,${dy}px)` }, { transform: 'none' }], { duration: 420, easing: 'cubic-bezier(.32,.72,0,1)' }); });
  }
  function moveWithUndo(a, id, to, message) {
    let before;
    flip(() => { before = E.moveTask(a, id, to); persist(); refreshWS(['shelf', 'toolbar']); });
    notify(message, () => { flip(() => { E.restoreOrder(a, before); persist(); refreshWS(['shelf']); }); });
    surfaceNewNotes(300);
  }
  function download(data, name) { const blob = new Blob([typeof data === 'string' ? data : JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  function resetAttemptUi() { ui.artifactId = null; ui.pane = 'work'; ui.inspector = 'talk'; ui.chatRole = null; ui.inspectorOpen = false; ui.priorityView = null; ui.suggestions = {}; ui.reviewSubmissionId = null; ui.reviewTaskId = null; ui.pendingRequestId = null; ui.lastUndo = null; ui.disputeOpen = null; }
  async function startAttempt(caseId, opts) {
    const a = L ? await L.start(caseId, opts) : E.createAttempt(state, caseId, opts);
    ui.arriving = true;
    a.selectedTaskId = null;
    resetAttemptUi();
    seedKnown(); persist();
    return a;
  }
  async function enterWork(fn) { await fn(); withTransition(() => { if (sheet.open) closeSheet(true); ui.route = 'work'; history.pushState(null, '', '#/work'); render(); window.scrollTo(0, 0); }); }
  async function runQuestion(question, expectation) {
    if (ui.busy) return; const a = current(); const paneAtStart = ui.pane; ui.busy = true; ui.labPrefill = ''; refreshWS(['canvas']);
    await new Promise(r => setTimeout(r, reduceMotion.matches ? 0 : 380));
    try { const t = task(); const run = L ? await L.test(a, { question, expectation, taskId: t ? t.id : null }) : E.runTest(a, { question, expectation, taskId: t ? t.id : null }); ui.lastRun = run.id; afterBusinessAction(a); persist(); announce('知识助手回答：' + run.answer); }
    catch (err) { notify(err.message); }
    finally { ui.busy = false; if (ui.route === 'work' && current() === a) { if (ui.pane === paneAtStart) ui.pane = 'lab'; refreshWS(); } }
  }

  async function act(el) {
    const a = current(); const id = el.dataset.id; const action = el.dataset.action;
    if (L && await liveAction(action, el, a)) return;
    switch (action) {
      case 'home': go('', { transition: true }); break;
      case 'open-career': go('pm', { transition: true }); break;
      case 'resume': if (L) { L.select(a); await L.refresh(a); } seedKnown(); go('work', { transition: true }); break;
      case 'resume-attempt': commit(); state.activeId = id; if (L) { L.select(current()); await L.refresh(current()); } resetAttemptUi(); seedKnown(); persist(); go('work', { transition: true }); break;
      case 'review-attempt': commit(); state.activeId = id; if (L) { L.select(current()); await L.refresh(current()); } resetAttemptUi(); seedKnown(); persist(); go('review', { transition: true }); break;
      case 'to-entry': go('pm', { transition: true }); break;
      case 'to-work': go('work', { transition: true }); break;
      case 'take-case': { const caseId = el.dataset.case; const card = el.closest('.case-card'); const triage = [...card.querySelectorAll('select[data-change="triage"]')].map(x => x.value); await enterWork(async () => { const na = await startAttempt(caseId); triage.forEach((p, i) => { if (na.tasks[i] && p !== na.tasks[i].priority) E.updateTask(na, na.tasks[i].id, { priority: p }); }); const order = { first: 0, next: 1, later: 2 }; na.tasks.sort((x, y) => order[x.priority] - order[y.priority]); persist(); }); break; }
      case 'start-intake': { const r = ui.intake.result; await enterWork(() => startAttempt('pilot', { intake: { text: r.text, adopted: r.adopted, notModeled: r.notModeled } })); break; }
      case 'practice-variant': { const caseId = el.dataset.case; const parent = a ? a.id : null; await enterWork(() => startAttempt(caseId, parent ? { parentAttemptId: parent } : undefined)); break; }
      case 'close': closeSheet(); break;
      case 'about': sheetAbout(); break;
      case 'export': download(storageLocked && rawRecord ? rawRecord : state, storageLocked && rawRecord ? 'practice-original-record.json' : 'practice-backup.json'); notify('已交给浏览器下载'); break;
      case 'reset-storage': try { localStorage.setItem(KEY + '.bak', rawRecord); storageLocked = false; storageError = ''; rawRecord = null; persist(); render(); notify('原记录已另存为备份，可以重新开始了'); } catch (_) { notify('浏览器不允许保存，没能另存'); } break;
      case 'toggle-brief': popoverOpen = !popoverOpen; refreshWS(['toolbar']); if (popoverOpen) document.querySelector('#brief-pop .btn')?.focus(); break;
      case 'select-task': if (a.selectedTaskId !== id) { commit(); a.selectedTaskId = id; ui.artifactId = null; if (ui.pane !== 'lab' && ui.pane !== 'materials') ui.pane = 'work'; persist(); refreshWS(['shelf', 'canvas', 'inspector']); } else if (ui.pane !== 'work') { ui.pane = 'work'; refreshWS(['canvas']); } break;
      case 'pane': commit(); ui.pane = el.dataset.pane; refreshWS(['canvas']); break;
      case 'new-task': sheetTask(); break;
      case 'edit-task': sheetTask(id); break;
      case 'move-task': { const t = a.tasks.find(x => x.id === id); const lane = a.tasks.filter(x => x.priority === t.priority); const li = lane.indexOf(t); const dir = Number(el.dataset.dir); if ((dir < 0 && li === 0) || (dir > 0 && li === lane.length - 1)) { notify('已经在这一组的' + (dir < 0 ? '最前面' : '最后面')); break; } const target = dir < 0 ? lane[li - 1] : lane[li + 2]; closeSheet(true); moveWithUndo(a, id, { beforeId: target ? target.id : null, priority: t.priority }, '已调整顺序'); break; }
      case 'priority-view': ui.priorityView = ui.priorityView ? null : 'manager'; if (ui.priorityView && !ui.suggestions.manager) { ui.suggestions.manager = E.suggestPriorities(a, 'manager'); persist(); } refreshWS(['shelf']); break;
      case 'pv-role': { const r = el.dataset.role; ui.priorityView = r; if (!ui.suggestions[r]) { ui.suggestions[r] = E.suggestPriorities(a, r); persist(); } refreshWS(['shelf']); break; }
      case 'apply-suggestion': { const s = ui.suggestions[ui.priorityView]; if (!s) break; let before; flip(() => { before = E.applySuggestion(a, s); ui.priorityView = null; persist(); refreshWS(['shelf']); }); notify('已按 ' + PEOPLE[s.roleId].name + ' 的建议排列', () => { flip(() => { E.restoreOrder(a, before); persist(); refreshWS(['shelf']); }); }); break; }
      case 'situation-task': { const t = E.addTask(a, { title: '处理政策更新的影响', note: '差旅政策 v2：上限 500 → 400。判断哪些测试、配置和承诺受影响。', priority: 'next' }); t.origin = 'situation'; a.acks = [...(a.acks || []), 'policy-v2']; a.selectedTaskId = t.id; ui.artifactId = null; ui.pane = 'work'; persist(); flip(() => refreshWS()); break; }
      case 'start-note': sheetNewArtifact(); break;
      case 'quick-note': { const t = task(); const x = E.createArtifact(a, { taskId: t.id, title: '我的初步想法', purpose: '探索笔记', body: '' }); ui.artifactId = x.id; persist(); refreshWS(['canvas', 'shelf']); document.getElementById('editor-body')?.focus(); break; }
      case 'new-artifact': sheetNewArtifact(); break;
      case 'open-artifact': commit(); ui.artifactId = id; refreshWS(['canvas', 'inspector']); break;
      case 'edit-pending': ui.editPending = id; refreshWS(['canvas']); document.getElementById('editor-body')?.focus(); break;
      case 'adopt': E.adoptArtifact(a, id); afterBusinessAction(a); persist(); refreshWS(); notify('已采用。里面的结论仍要你检查和验证。'); break;
      case 'open-material': commit(); popoverOpen = false; ui.materialId = id; ui.pane = 'materials'; if (L) await L.read(a, id); else E.readMaterial(a, id); persist(); if (ui.route !== 'work') go('work'); else refreshWS(['canvas', 'toolbar']); break;
      case 'cite-material': { const m = E.getMaterials(a).find(x => x.id === id); cite({ id: m.id, title: m.title, version: m.version, body: m.body, type: 'material' }); refreshWS(['inspector', 'shelf']); break; }
      case 'cite-run': { const r = a.tests.find(x => x.id === id); cite({ id: r.id, title: '测试：' + r.question, version: r.configVersion, body: r.answer, type: 'test' }); refreshWS(['inspector', 'shelf', 'canvas']); break; }
      case 'view-evidence': { const x = artifact(); const ev = x && x.evidence.find(e => e.id === id && String(e.version ?? '') === el.dataset.version); if (ev) openSheet(esc(ev.title || ev.id), `<p class="t-sub tertiary">引用时保存的内容${ev.version ? '，v' + ev.version : ''}。原文之后改了，这里也不会变。</p><div class="prose quoteblock">${md(ev.body || '')}</div>`, btn('好', 'close', 'primary'), 'narrow'); break; }
      case 'run-source': { const r = a.tests.find(x => x.id === el.dataset.run); if (r) openSheet('这次回答用的来源', `<div class="answer">${assistantMark()}<p>${esc(r.answer)}</p></div><dl class="facts list"><div><dt>引用</dt><dd>${r.citations.map(c => esc(c.title) + '，索引 v' + c.version).join('；')}</dd></div><div><dt>当时政策源</dt><dd>v${r.policyVersion}</dd></div><div><dt>当时配置</dt><dd>v${r.configVersion}，${r.config ? UPDATE_NAMES[r.config.update] : '配置 v' + r.configVersion}</dd></div></dl>`, btn('好', 'close', 'primary'), 'narrow'); break; }
      case 'rerun': { const r = a.tests.find(x => x.id === id); await runQuestion(r.question, r.expectation); break; }
      case 'refresh-index': if (L) await L.action(a, 'refresh_index'); else E.refreshIndex(a); persist(); refreshWS(); notify('索引已更新到 v' + a.world.indexVersion + '。旧测试保持原样，可以同题重测比较。'); break;
      case 'config': closeSheet(true); popoverOpen = false; sheetConfig(); break;
      case 'resources': closeSheet(true); popoverOpen = false; if (ui.route === 'work') refreshWS(['toolbar']); sheetResources(); break;
      case 'resolve-request': E.resolveResources(a, id); persist(); sheetResources(); refreshWS(); surfaceNewNotes(400); break;
      case 'policy-update': E.triggerPolicyUpdate(a); persist(); refreshWS(); surfaceNewNotes(300); break;
      case 'ack': a.acks = [...(a.acks || []), el.dataset.key]; persist(); flip(() => refreshWS(['shelf'])); break;
      case 'open-talk': { ui.inspectorOpen = true; ui.inspector = 'talk'; const r0 = ROLES.find(r => unread(a, r)); ui.chatRole = r0 || null; if (r0) E.markNudgesRead(a, r0); persist(); refreshWS(['inspector', 'toolbar', 'shelf']); break; }
      case 'people': ui.chatRole = null; ui.inspector = 'talk'; refreshWS(['inspector']); break;
      case 'insp-tab': ui.inspector = el.dataset.tab; refreshWS(['inspector']); break;
      case 'toggle-inspector': ui.inspectorOpen = !ui.inspectorOpen; refreshWS(['toolbar', 'inspector']); if (ui.inspectorOpen) document.querySelector('#ws-inspector .segmented button')?.focus(); break;
      case 'close-inspector': ui.inspectorOpen = false; refreshWS(['toolbar']); document.querySelector('[data-action="toggle-inspector"]')?.focus(); break;
      case 'chat': openChat(el.dataset.role); break;
      case 'reply-note': { const n = (a.nudges || []).find(x => x.id === id); if (!n) break; E.respondNudge(a, id, 'replied'); persist(); openChat(n.roleId, `关于你说的“${n.text.slice(0, 60)}${n.text.length > 60 ? '…' : ''}”：`); refreshWS(['canvas']); document.getElementById('chat-input')?.focus(); break; }
      case 'later-note': E.respondNudge(a, id, 'later'); persist(); refreshWS(['canvas', 'shelf', 'toolbar']); break;
      case 'discuss-artifact': { const x = artifact(); closeSheet(true); openChat(x && E.intentOf(x.purpose) === 'commit' ? 'manager' : 'business', x ? `这是我的「${x.title}」（${x.purpose}）：\n${x.body.slice(0, 1500)}\n\n想请你看看：` : ''); break; }
      case 'discuss-material': { const m = E.getMaterials(a).find(x => x.id === id); openChat(m.id === 'technical' || m.id === 'policy' ? 'technical' : m.id === 'brief' ? 'manager' : 'business', `我在看《${m.title}》v${m.version}，想确认：`); break; }
      case 'discuss-run': { const r = a.tests.find(x => x.id === id); openChat('technical', `我测了“${r.question}”，助手答“${r.answer}”（索引 v${r.indexVersion}，政策源 v${r.policyVersion}）。我想确认：`); break; }
      case 'prefill-artifact': { const x = artifact(); const input = document.getElementById('chat-input'); if (input && x) { input.value = `这是我的「${x.title}」：\n${x.body.slice(0, 1500)}\n\n` + input.value; input.focus(); } break; }
      case 'prefill-run': { const r = a.tests.at(-1); const input = document.getElementById('chat-input'); if (input && r) { input.value = `最近一次测试：“${r.question}” → “${r.answer}”。` + input.value; input.focus(); } break; }
      case 'agent': sheetAgent(); break;
      case 'cite-into': { a.selectedTaskId = id; ui.artifactId = null; const ev = ui.pendingCite; ui.pendingCite = null; closeSheet(true); if (ev) cite(ev); persist(); refreshWS(); break; }
      case 'package': openSheet('任务包', `<p class="t-sub tertiary">这是会交给你的 Agent 的内容，不含任何连接凭据。</p><label class="sr-only" for="package-text">任务包内容</label><textarea id="package-text" class="textarea mono" rows="16" readonly>${esc(JSON.stringify(pkgFor(a, false), null, 2))}</textarea>`, `${btn('返回', 'agent', 'quiet')}${btn('复制并记为已导出', 'copy-package', 'primary')}`, 'wide'); break;
      case 'copy-package': { const pkg = pkgFor(a, true); persist(); try { await navigator.clipboard.writeText(JSON.stringify(pkg, null, 2)); notify('任务包已复制，已记为“已导出”'); } catch (_) { notify('浏览器不允许自动复制；已记为导出，可以在“看看内容”里手动复制'); } break; }
      case 'download-package': download(pkgFor(a, true), 'practice-task.json'); persist(); notify('任务包已交给浏览器下载'); break;
      case 'confirm-import': { try { const t = task(); const res = E.importReturn(a, ui.importText, t ? t.id : null); if (res.duplicate) { notify('这份回传已经导入过了，没有重复创建'); break; } if (!res.artifact.taskId) res.artifact.taskId = (t || a.tasks[0]).id; a.selectedTaskId = res.artifact.taskId; ui.artifactId = res.artifact.id; ui.pane = 'work'; ui.importText = ''; persist(); closeSheet(); refreshWS(); notify('收到了，先检查再决定是否采用'); } catch (err) { notify(err.message); } break; }
      case 'review-artifact': { if (L) { commit(); openSheet('请求评审', '<p>可以将当前作品发给同事讨论。正式规则反馈在固定交付后由后端生成。</p>', btn('和同事讨论', 'discuss-artifact', 'quiet') + btn('准备正式交付', 'submit', 'primary')); break; } commit(); const x = artifact(); if (!x) { notify('先打开一份作品'); break; } const res = E.review(a, x.id); const co = E.coach(a).items.filter(i => !i.taskId || i.taskId === x.taskId); persist();
        openSheet('看看这份作品', `<p class="t-sub tertiary">${esc(x.purpose)}：${INTENT_LINE[E.intentOf(x.purpose)]}</p>
          ${co.length ? `<ol class="feedback compact">${co.map(i => fbItem(a, i, true)).join('')}</ol>` : '<p class="secondary">从已有记录里看，暂时没有需要提醒的地方。这不等于论证已经成立。</p>'}
          <details class="disclosure"><summary>记录核对（${res.observations.length} 项）</summary>${res.observations.map(o => `<p class="t-callout"><span class="check-dot ${o.status}"></span><b>${esc(o.title)}</b>：${esc(o.text)}</p>`).join('')}</details>
          <p class="t-foot tertiary">规则示意：根据已发生的记录生成。真实的 Judge 会结合你的原句、意图和当时知道的信息，还没有接入。</p>`, `${btn('问同事', 'discuss-artifact', 'quiet')}${btn('回去改', 'close', 'primary')}`, '');
        break; }
      case 'fb-act': { const kind = el.dataset.act; const tid = el.dataset.task; closeSheet(true); if (tid && a.tasks.some(t => t.id === tid)) a.selectedTaskId = tid;
        if (kind === 'chat') { persist(); openChat(el.dataset.role); break; }
        if (kind === 'rerun') { const r = a.tests.find(x => x.id === el.dataset.id); ui.pane = 'lab'; ui.labPrefill = r ? r.question : ''; }
        else if (kind === 'lab') ui.pane = 'lab';
        else if (kind === 'config') { ui.pane = 'lab'; setTimeout(sheetConfig, 60); }
        else if (kind === 'material') { ui.pane = 'materials'; ui.materialId = el.dataset.id; if (L) await L.read(a, el.dataset.id); else E.readMaterial(a, el.dataset.id); }
        else if (kind === 'open-artifact') { ui.pane = 'work'; ui.artifactId = el.dataset.id; }
        else if (kind === 'open-decision') { const d = works(a).find(w => E.intentOf(w.purpose) === 'commit'); ui.pane = 'work'; if (d) { a.selectedTaskId = d.taskId; ui.artifactId = d.id; } }
        else if (kind === 'new-decision') { ui.pane = 'work'; setTimeout(() => sheetNewArtifact('试点决定'), 60); }
        persist(); if (ui.route !== 'work') go('work', { transition: true }); else refreshWS(); break; }
      case 'dispute': ui.disputeOpen = ui.disputeOpen === el.dataset.key ? null : el.dataset.key; render(); document.querySelector('.dispute textarea')?.focus(); break;
      case 'submit': commit(); sheetSubmit(); break;
      case 'confirm-submit': { E.submit(a); persist(); ui.reviewSubmissionId = null; ui.reviewTaskId = null; withTransition(() => { closeSheet(true); ui.route = 'review'; history.pushState(null, '', '#/review'); render(); window.scrollTo(0, 0); }); break; }
      case 'pick-submission': ui.reviewSubmissionId = id; withTransition(render); break;
      case 'review-task': ui.reviewTaskId = id || null; withTransition(render); break;
      case 'revise': { if (L) { notify('后端已固定提交，不支持原会话解锁修订。请新建练习；本地草稿仍保留。'); break; } if (!el.dataset.basis && E.laterEdits(a, id).length) { const later = E.laterEdits(a, id); openSheet('从哪一版继续修订', `<p class="t-callout secondary">交付之后你还改过：${later.map(x => '「' + esc(x.title) + '」（交付时 v' + x.snapshotRevision + '，现在 v' + x.currentRevision + '）').join('、')}。</p><p class="t-sub tertiary">两种都会保留原交付；版本号只会往后加。</p>`, `${btn('从交付版继续', 'revise', 'quiet', `data-id="${id}" data-basis="snapshot"`)}${btn('从当前版继续', 'revise', 'primary', `data-id="${id}" data-basis="current"`)}`, 'narrow'); break; }
        closeSheet(true); const copies = E.revise(a, id, { basis: el.dataset.basis === 'current' ? 'current' : 'snapshot' }); afterBusinessAction(a); ui.artifactId = copies[0] ? copies[0].id : null; if (copies[0] && copies[0].taskId) a.selectedTaskId = copies[0].taskId; ui.pane = 'work'; persist(); go('work', { transition: true }); notify('已从这次交付开始修订；原交付保持不变'); break; }
      case 'open-ref': { const type = el.dataset.type; if (el.dataset.task && a.tasks.some(t => t.id === el.dataset.task)) a.selectedTaskId = el.dataset.task; if (type === 'test') { ui.pane = 'lab'; ui.lastRun = id; } else if (type === 'artifact') { ui.pane = 'work'; ui.artifactId = a.artifacts.some(x => x.id === id) ? id : null; } else { ui.pane = 'materials'; ui.materialId = 'policy'; } persist(); go('work', { transition: true }); if (type === 'test') setTimeout(() => document.getElementById('run-' + id)?.scrollIntoView({ block: 'center', behavior: reduceMotion.matches ? 'auto' : 'smooth' }), 80); break; }
    }
  }

  /* ---------- API workflow: all server mutations use the durable request journal ---------- */
  function liveStatus() {
    if (!L) return;
    const snap = L.store.getSnapshot(), a = current(), sess = a && L.session(a), pending = sess?.pending;
    let host = document.getElementById('api-status');
    if (!host) { host = document.createElement('div'); host.id = 'api-status'; host.className = 'api-status'; app.before(host); }
    host.innerHTML = `<span>${snap.connected ? 'API 已连接' : 'API 未连接'}${snap.model ? ' · ' + esc(snap.model) : ''}${sess ? ' · ' + ({active:'进行中', paused:'已暂停', submitted:'已固定交付'}[sess.world.status]) : ''}</span><span class="spacer"></span>${pending ? `<span role="status">${esc(pending.label)}：${pending.jobId ? esc(pending.job?.status || 'queued') + '（等待 worker）' : snap.busy ? '发送中' : '结果待确认'}</span>${btn(pending.jobId ? '查询任务' : '重试原请求', 'live-retry', 'small', snap.busy ? 'disabled' : '')}` : ''}${btn('刷新状态', 'live-refresh', 'quiet small')}${snap.error ? `<p role="alert">${esc(snap.error)}</p>` : ''}${snap.storageError ? '<p role="alert">存储不可用，已暂停写入。</p>' : ''}`;
    const locked = !sess || sess.world.status !== 'active' || snap.busy || !!pending || snap.storageError;
    for (const el of document.querySelectorAll('[data-form="chat"] button[type="submit"], [data-form="config"] button[type="submit"], [data-form="resources"] button[type="submit"], [data-action="live-save"], [data-action="live-submit"]')) el.disabled = locked;
    for (const el of document.querySelectorAll('[data-action="take-case"], [data-action="start-intake"], [data-action="practice-variant"]')) el.disabled = snap.busy || snap.storageError;
    const submitter = document.querySelector('[data-form="run-test"] button[type="submit"]');
    if (submitter) submitter.disabled = locked || ui.busy || !a?.backend.configured;
    const fixed = document.querySelector('[data-action="live-submit"]'); if (fixed && !sess?.artifact) fixed.disabled = true;
  }
  function liveResources(a) {
    const sess = L.session(a);
    openSheet('申请与审批', `<p class="t-callout secondary">先在试点设置中保存希望申请的方案，再提交理由。审批读取后端的方案与约束；聊天回复不会批准资源。</p><form data-form="resources" id="res-form" class="stack-12"><label class="field"><span>申请类型</span><select name="kind" class="select"><option value="request_capacity">扩容</option><option value="request_resources">增加开发资源或延期</option></select></label><label class="field"><span>申请理由</span><textarea class="textarea" name="reason" required maxlength="4000" rows="4"></textarea></label></form><h3>待处理申请</h3>${sess.world.pending_requests.length ? sess.world.pending_requests.map(rule => `<div class="row"><span class="grow">${rule === 'capacity_approved' ? '扩容' : '资源与延期'}</span>${btn('按场景规则审核', 'live-approval', 'small', `data-id="${esc(rule)}"`)}</div>`).join('') : '<p class="secondary">没有待处理申请。</p>'}<p class="t-foot tertiary">容量 ${a.world.capacity} 人 · 开发 ${a.world.devDays} 人日 · 上线第 ${a.world.deadline} 天。只有审批成功的服务端结果会改变这些条件。</p>`, '<button type="submit" form="res-form" class="btn primary">提交申请</button>', 'narrow');
    liveStatus();
  }
  const deliveryLabels = { goal: '业务目标与用户范围', owner: '负责人', metrics: '成功指标', observation_window: '观察窗口', exit_condition: '退出条件', rationale: '方案、作品与依据' };
  function liveDeliver(a) {
    const sess = L.session(a);
    if (sess.world.status === 'submitted') { closeSheet(true); go('review'); return; }
    if (!sess.draft.rationale && works(a).length) L.store.update(a.id, { draft: { ...sess.draft, rationale: L.draftFromWorks(a) } });
    const now = L.session(a);
    openSheet('准备正式交付', `<p class="t-callout secondary">这里核对将保存到后端的内容。自由作品可合并到“方案、作品与依据”；其他字段可留空，反馈会如实记录缺失。固定提交后，这个后端会话只读。</p><form data-form="live-deliver" id="live-deliver" class="stack-12">${Object.entries(deliveryLabels).map(([key,label]) => `<label class="field"><span>${label}</span><textarea class="textarea" name="${key}" rows="${key === 'rationale' ? 8 : 2}">${esc(now.draft[key])}</textarea></label>`).join('')}</form>${btn('用当前作品更新方案摘要', 'live-collect', 'small quiet')}<p class="t-foot tertiary">${now.artifact ? '后端已保存成果 v' + now.artifact.version + '，配置 v' + now.artifact.config_version : '尚未保存后端交付稿'} · 当前配置 v${now.world.config_version}</p>`, `${btn('保存交付稿', 'live-save', 'quiet')}${btn('固定提交并生成反馈', 'live-submit', 'primary', now.artifact ? '' : 'disabled')}`, 'wide');
    liveStatus();
  }
  function liveFeedback(a) {
    if (!a) return '';
    const sess = L.session(a), fb = sess.feedback, submission = L.store.submissionId(sess);
    const names = { 'R1.target':'目标与用户范围', 'R1.metrics':'成功指标', 'R2.support':'事实与证据', 'R2.unknowns':'未证实的结论', 'R3.capacity':'人数与容量', 'R3.resources':'资源和期限', 'R4.functional_tests':'实际功能测试', 'R4.staleness_test':'政策变化测试', 'R5.impact':'变化的影响', 'R5.adjustment':'方案与配置调整', 'R6.consistency':'方案与配置一致性', 'R6.operations':'观察与退出安排' };
    const labels = { MET:'已满足', PARTIAL:'部分满足', NOT_MET:'未满足', INSUFFICIENT:'证据不足', NOT_APPLICABLE:'不适用' };
    return `<div class="stack-16"><p class="t-sub secondary">${submission ? '已固定后端交付，历史版本保持只读。' : '正式交付后，后端会基于固定时点的材料、配置与操作生成规则反馈。'}</p>${submission ? `<div class="hstack wrap">${!fb && !sess.feedbackFailure ? btn('生成反馈', 'live-feedback', 'small', sess.pending ? 'disabled' : '') : ''}${btn('读取已保存反馈', 'live-saved-feedback', 'small quiet')}</div>` : btn('准备正式交付', 'submit', 'small')}${sess.feedbackFailure ? `<p role="alert">反馈任务失败：${esc(sess.feedbackFailure.error)}。现有接口不支持重跑这个终态任务。</p>` : ''}${fb ? `<p class="t-sub">后端版本：${esc(fb.model_revision)} · 观察截至事件 #${fb.as_of_seq}</p><ol class="feedback">${fb.items.map(i => `<li class="fb"><div class="fb-icon">${icon(i.label === 'MET' ? 'good' : i.label === 'NOT_MET' ? 'warn' : 'question')}</div><div class="fb-body"><h4>${esc(names[i.criterion_id] || i.criterion_id)} · ${esc(labels[i.label] || i.label)}</h4><p>${esc(i.reason)}</p>${i.review_required ? '<p class="t-foot tertiary">需要人工核验，不能视为最终结论。</p>' : ''}<div class="hstack wrap">${i.evidence_ids.map(id => btn('查看依据 ' + esc(id), 'live-evidence', 'small quiet', `data-criterion="${esc(i.criterion_id)}" data-id="${esc(id)}"`)).join('')}</div></div></li>`).join('')}</ol><details class="disclosure"><summary>规则评价范围</summary><p>分数区间 ${fb.summary.lower ?? '—'}–${fb.summary.upper ?? '—'}，非最终分数；覆盖率 ${Math.round(fb.summary.coverage * 100)}%。状态 ${esc(fb.summary.status)}。</p></details>${fb.practice.length ? '<ul>' + fb.practice.map(p => '<li>' + esc(p) + '</li>').join('') + '</ul>' : ''}` : ''}<div class="hstack wrap">${btn('查看后端过程记录', 'live-timeline', 'small quiet')}${btn('历史材料', 'live-history', 'small quiet')}${btn('辅助证据判断', 'live-relation', 'small quiet')}</div><p class="t-foot tertiary">当前后端尚不支持提交后解锁、关联修订或针对每份自由作品的情境化 Judge。可以新建练习继续验证。</p></div>`;
  }
  async function liveAction(action, el, a) {
    switch (action) {
      case 'live-refresh': await L.refresh(a); liveStatus(); return true;
      case 'live-retry': await L.retry(a); liveStatus(); return true;
      case 'live-session': {
        if (a.backend.status === 'submitted') { go('review'); return true; }
        await L.action(a, a.backend.status === 'paused' ? 'resume' : 'pause'); refreshWS(); liveStatus(); return true;
      }
      case 'priority-view': openChat('manager', '这是我手头的事项：' + a.tasks.map(t => t.title).join('；') + '。你建议我优先弄清什么，为什么？'); return true;
      case 'policy-update': notify('政策事件由后端业务操作触发，前端不改写它。'); return true;
      case 'live-approval': await L.perform(a, () => L.store.approval(el.dataset.id)); liveResources(a); refreshWS(); return true;
      case 'live-collect': commit(); L.store.update(a.id, { draft: { ...L.session(a).draft, rationale: L.draftFromWorks(a) } }); liveDeliver(a); return true;
      case 'live-save': await L.save(a, L.session(a).draft); liveDeliver(a); return true;
      case 'live-submit': {
        await L.submit(a); if (!L.store.submissionId(L.session(a))) throw new Error('尚未取得提交确认。');
        closeSheet(true); go('review'); await L.feedback(a); render(); return true;
      }
      case 'live-feedback': await L.feedback(a); render(); return true;
      case 'live-saved-feedback': await L.savedFeedback(a); render(); return true;
      case 'live-evidence': {
        const value = await L.evidence(a, el.dataset.criterion, el.dataset.id);
        openSheet('后端依据 · ' + esc(el.dataset.id), `<p class="t-sub tertiary">这是经当前会话鉴权、按固定交付时点返回的证据。</p><pre class="api-json">${esc(JSON.stringify(value, null, 2))}</pre>`, btn('关闭', 'close', 'primary'), 'wide'); return true;
      }
      case 'live-timeline': {
        await L.store.sync(a.id);
        openSheet('后端过程记录', `<p class="t-sub tertiary">读取已保存的历史，不再次调用模型。</p><pre class="api-json">${esc(JSON.stringify(L.session(a).timeline, null, 2))}</pre>`, btn('关闭', 'close', 'primary'), 'wide'); return true;
      }
      case 'live-history': openSheet('按事件查看历史材料', `<form id="history-form" data-form="live-history" class="stack-12"><label class="field"><span>事件序号</span><input name="seq" class="input" type="number" min="0" max="${a.backend.version}" value="${a.backend.version}" required></label></form>`, '<button type="submit" form="history-form" class="btn primary">读取材料</button>', 'narrow'); return true;
      case 'run-source': {
        const run = a.tests.find(t => t.id === el.dataset.run);
        const materials = await L.history(a, run.asOfSeq);
        openSheet('测试当时的材料与索引', `<p class="t-callout">${esc(run.answer)}</p><p class="t-sub tertiary">当时事件 #${run.asOfSeq}；源文档与实际引用索引版本分别列出。源文档不等同于索引内容。</p>${run.citations.map(c => `<p>引用 ${esc(c.title)} · 索引 v${c.version}</p>`).join('')}${materials.filter(m => run.citations.some(c => c.id === m.id)).map(m => `<h3>${esc(m.title)} · 源 v${m.version}</h3><div class="prose">${md(m.content)}</div>`).join('')}`, btn('关闭', 'close', 'primary'), 'wide'); return true;
      }
      case 'live-relation': openSheet('辅助证据判断', `<p class="t-sub secondary">实验接口，仅供人工复核，不改变正式评分；服务器需要配置已冻结实验。</p><form id="relation-form" data-form="live-relation"><label class="field"><span>待核查主张</span><textarea class="textarea" name="claim" maxlength="4000" required rows="4"></textarea></label></form>`, '<button type="submit" form="relation-form" class="btn primary">核查</button>', 'narrow'); return true;
      default: return false;
    }
  }
  async function liveForm(form, f, a) {
    switch (form.dataset.form) {
      case 'chat': { await L.turn(a, ui.chatRole, String(f.get('text')).trim()); refreshWS(['inspector']); liveStatus(); return true; }
      case 'config': {
        await L.config(a, { participants:Number(f.get('participants')), domains:f.getAll('domains'), update:String(f.get('update')), fallback:String(f.get('fallback')), workItems:f.getAll('workItems'), launchDay:Number(f.get('launchDay')) });
        closeSheet(); ui.pane='lab'; refreshWS(); liveStatus(); return true;
      }
      case 'resources': await L.action(a, String(f.get('kind')), { reason:String(f.get('reason')).trim() }); liveResources(a); refreshWS(); return true;
      case 'live-deliver': await L.save(a, L.session(a).draft); liveDeliver(a); return true;
      case 'live-history': {
        const data = await L.history(a, Number(f.get('seq')));
        openSheet('历史材料 · #' + esc(f.get('seq')), data.map(m => `<h3>${esc(m.title)} · v${m.version}</h3><div class="prose">${md(m.content)}</div>`).join(''), btn('关闭','close','primary'), 'wide'); return true;
      }
      case 'live-relation': {
        await L.relation(a, String(f.get('claim')));
        openSheet('辅助判断结果', `<pre class="api-json">${esc(JSON.stringify(L.session(a).relationResult, null, 2))}</pre>`, btn('关闭','close','primary'), 'wide'); return true;
      }
      default: return false;
    }
  }

  /* ---------- events ---------- */
  document.addEventListener('click', e => {
    if (popoverOpen && !e.target.closest('.title-wrap')) { popoverOpen = false; refreshWS(['toolbar']); }
    const el = e.target.closest('[data-action]'); if (!el || el.disabled) return;
    Promise.resolve(act(el)).catch(err => notify(err.message || '这一步没有完成，内容还在。'));
  });
  document.addEventListener('toggle', e => { const d = e.target; if (d.classList && d.classList.contains('variant')) { if (d.open) ui.openVariant = d.dataset.variant; else if (ui.openVariant === d.dataset.variant) ui.openVariant = null; } }, true);
  document.addEventListener('compositionend', e => { if (e.target.dataset && e.target.dataset.edit) e.target.dispatchEvent(new Event('input', { bubbles: true })); });
  document.addEventListener('input', e => {
    const el = e.target;
    if (L && ['lab-q', 'lab-e', 'chat-input'].includes(el.id) && current()) {
      const a = current(), sess = L.session(a), inputs = { ...sess.inputs, messages: { ...sess.inputs.messages } };
      if (el.id === 'lab-q') inputs.question = el.value;
      if (el.id === 'lab-e') inputs.expected = el.value;
      if (el.id === 'chat-input' && ui.chatRole) inputs.messages[{ manager:'supervisor', business:'business_lead', technical:'tech_lead' }[ui.chatRole]] = el.value;
      L.store.update(a.id, { inputs });
    }
    if (L && el.form?.dataset.form === 'live-deliver' && current() && Object.hasOwn(deliveryLabels, el.name)) { const a = current(); L.store.update(a.id, { draft: { ...L.session(a).draft, [el.name]: el.value } }); }
    if (e.isComposing) return;
    if (el.id === 'editor-body') autoGrow(el);
    if (el.id === 'import-content') ui.importText = el.value;
    if (!el.dataset.edit) return; const a = current(); const x = artifact(); if (!a || !x) return;
    dirty = { attemptId: a.id, id: x.id, title: document.getElementById('editor-title')?.value || x.title, purpose: document.querySelector('[data-edit="purpose"]')?.value || x.purpose, body: document.getElementById('editor-body')?.value ?? x.body };
    updateSave(); clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      flush();
      const tab = document.querySelector('.doc-tabs [aria-pressed="true"] .tab-name'); const cur = artifact(); if (tab && cur) tab.textContent = shown(cur).title;
      refreshWS(['toolbar']);
    }, 700);
  });
  document.addEventListener('change', e => {
    const el = e.target; const a = current();
    try {
      if (el.dataset.change === 'triage') { const pri = el.closest('.pri-select').querySelector('.pri'); pri.className = 'pri ' + el.value; pri.textContent = PRI[el.value]; return; }
      if (el.dataset.change === 'priority') { commit(); const t = a.tasks.find(x => x.id === el.dataset.id); moveWithUndo(a, el.dataset.id, { priority: el.value }, '「' + t.title + '」改为' + PRI[el.value]); return; }
      if (el.dataset.edit === 'purpose') { const il = document.querySelector('.intent-line'); if (il) il.textContent = INTENT_LINE[E.intentOf(el.value)]; el.dispatchEvent(new Event('input', { bubbles: true })); const n0 = (a.nudges || []).length; commit(); updateSave(); refreshWS(['toolbar', 'shelf']); if ((a.nudges || []).length > n0) setTimeout(refreshMargin, 900); }
      if (el.dataset.scope) ui.exportScope[el.dataset.scope] = el.checked;
      if (el.id === 'import-file' && el.files && el.files[0]) { const f = el.files[0]; if (f.size > 2 * 1024 * 1024) throw new Error('请选 2 MB 以内的文本文件'); f.text().then(text => { const t = document.getElementById('import-content'); if (t) { t.value = text; ui.importText = text; } }).catch(() => notify('文件读不出来，可以直接粘贴文本')); }
      if (el.form && el.form.dataset.form === 'config') { const f = new FormData(el.form); const c = { participants: Number(f.get('participants')), domains: f.getAll('domains'), update: String(f.get('update')), workItems: f.getAll('workItems') }; const box = document.querySelector('[data-checks]'); if (box) box.outerHTML = configChecks(a, c); }
    } catch (err) { notify(err.message); }
  });
  document.addEventListener('submit', async e => {
    const form = e.target; if (!form.dataset.form) return; e.preventDefault(); commit();
    const f = new FormData(form); const a = current();
    try {
      if (L && await liveForm(form, f, a)) return;
      switch (form.dataset.form) {
        case 'intake': ui.intake.text = String(f.get('text') || ''); ui.intake.result = E.matchBusiness(ui.intake.text); render(); announce({ empty: '先写一句你想练的业务', none: '这个情境现在还练不了', partial: '主体不同，只能借用知识助手试点的决策结构', matched: '最接近知识助手试点' }[ui.intake.result.status]); document.querySelector('.intake-result')?.setAttribute('tabindex', '-1'); document.querySelector('.intake-result')?.focus({ preventScroll: true }); document.querySelector('.intake-result')?.scrollIntoView({ block: 'nearest', behavior: reduceMotion.matches ? 'auto' : 'smooth' }); break;
        case 'task': { const values = { title: String(f.get('title')).trim(), note: String(f.get('note') || '') }; const pr = String(f.get('priority') || 'next');
          if (form.dataset.id) { const t = a.tasks.find(x => x.id === form.dataset.id); if (f.get('status')) values.status = String(f.get('status')); E.updateTask(a, t.id, values); if (t.priority !== pr) E.moveTask(a, t.id, { priority: pr }); const split = String(f.get('split') || '').trim(); if (split) E.splitTask(a, t.id, split); }
          else { const t = E.addTask(a, { ...values, priority: pr }); E.moveTask(a, t.id, { priority: pr }); a.selectedTaskId = t.id; ui.artifactId = null; ui.pane = 'work'; }
          persist(); closeSheet(); flip(() => refreshWS()); surfaceNewNotes(300); break; }
        case 'artifact': { const x = E.createArtifact(a, { title: String(f.get('title')).trim(), purpose: String(f.get('purpose')), taskId: String(f.get('taskId')), body: '' }); a.selectedTaskId = x.taskId; ui.artifactId = x.id; ui.pane = 'work'; persist(); closeSheet(); refreshWS(); document.getElementById('editor-body')?.focus(); break; }
        case 'run-test': runQuestion(String(f.get('question')), String(f.get('expectation') || '')); break;
        case 'chat': { const text = String(f.get('text')).trim(); if (!text) break; const t = task(); const m = E.reply(a, ui.chatRole, text, t ? t.id : null); persist(); refreshWS(['inspector']); document.getElementById('chat-input')?.focus(); announce(PEOPLE[ui.chatRole].name + ' 回复：' + m.text); break; }
        case 'config': { const res = E.updateConfig(a, { participants: Number(f.get('participants')), domains: f.getAll('domains'), update: String(f.get('update')), fallback: String(f.get('fallback')), workItems: f.getAll('workItems') }); afterBusinessAction(a); persist(); closeSheet(); ui.pane = 'lab'; refreshWS(); notify(res.applied ? '设置 v' + a.configVersion + ' 已应用。下一次测试会用它。' : '没有生效，已留作草案：' + res.reason.replace('。已保留草案，正在使用的配置未变。', '')); surfaceNewNotes(500); break; }
        case 'resources': { const r = E.requestResources(a, String(f.get('reason'))); afterBusinessAction(a); persist(); sheetResources(); if (ui.route === 'work') refreshWS(['inspector', 'shelf', 'toolbar']);
          setTimeout(() => { const cur = state.attempts.find(x => x.id === a.id); if (!cur) return; E.resolveResources(cur, r.id); persist(); if (sheet.open && sheet.querySelector('#res-form')) sheetResources(); if (ui.route === 'work' && current() === cur) { refreshWS(); surfaceNewNotes(); } }, reduceMotion.matches ? 300 : 1800); break; }
        case 'import': { const text = String(f.get('content')); const data = E.validateImported(text); ui.importText = text; const t = task(); openSheet('检查带回的内容', `<p class="t-sub tertiary">来自你的 Agent，用途「${esc(data.purpose)}」，将放在「${esc(t ? t.title : a.tasks[0].title)}」下${data.requestId ? '，对应一次已记录的导出' : ''}</p><h3 class="t-title3">${esc(data.title)}</h3><div class="prose quoteblock">${md(data.body)}</div><p class="t-sub tertiary">导入后是一份独立的“待检查”作品，不会覆盖已有内容，也不会自动运行任何测试。</p>`, `${btn('返回修改', 'agent', 'quiet')}${btn('导入为待检查作品', 'confirm-import', 'primary')}`, 'wide'); break; }
        case 'dispute': { const key = form.dataset.key; a.disputes = [...(a.disputes || []), { key, text: String(f.get('text')).trim(), createdAt: new Date().toISOString() }]; E.log(a, 'feedback_disputed', '你对一条反馈提出了不同看法。', { key }); ui.disputeOpen = null; persist(); render(); notify('已记下你的看法'); break; }
      }
    } catch (err) { notify(err.message || '请检查输入'); }
  });
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); const v = commit(); notify(storageError || (v ? '已存为新版本' : '已保存')); updateSave(); }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && (e.target.id === 'chat-input' || e.target.id === 'lab-q')) { e.preventDefault(); e.target.form.requestSubmit(); }
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'z' && ui.lastUndo && !/^(INPUT|TEXTAREA)$/.test(e.target.tagName)) { e.preventDefault(); const u = ui.lastUndo; ui.lastUndo = null; u(); toastEl.classList.remove('visible'); notify('已撤销'); }
    if (e.key === 'Escape' && ui.inspectorOpen && narrow() && !sheet.open) { ui.inspectorOpen = false; refreshWS(['toolbar', 'inspector']); document.querySelector('[data-action="toggle-inspector"]')?.focus(); }
    if (e.key === 'Escape' && popoverOpen) { popoverOpen = false; refreshWS(['toolbar']); document.querySelector('.title-btn')?.focus(); }
    if (e.altKey && /^Arrow/.test(e.key) && e.target.classList && e.target.classList.contains('task-title') && e.target.closest('.lanes')) {
      e.preventDefault();
      const a = current(); const id = e.target.dataset.id; const t = a.tasks.find(x => x.id === id); if (!t) return;
      const order = ['first', 'next', 'later']; const lane = a.tasks.filter(x => x.priority === t.priority); const li = lane.indexOf(t);
      let to = null; let msg = '已调整顺序';
      if (e.key === 'ArrowUp' && order.indexOf(t.priority) > 0) { to = { priority: order[order.indexOf(t.priority) - 1] }; msg = '「' + t.title + '」改为' + PRI[to.priority]; }
      if (e.key === 'ArrowDown' && order.indexOf(t.priority) < 2) { to = { priority: order[order.indexOf(t.priority) + 1] }; msg = '「' + t.title + '」改为' + PRI[to.priority]; }
      if (e.key === 'ArrowLeft' && li > 0) to = { priority: t.priority, beforeId: lane[li - 1].id };
      if (e.key === 'ArrowRight' && li < lane.length - 1) to = { priority: t.priority, beforeId: lane[li + 2] ? lane[li + 2].id : null };
      if (!to) { notify('已经到头了'); return; }
      moveWithUndo(a, id, to, msg); document.querySelector(`.task-title[data-id="${id}"]`)?.focus();
      const moved = a.tasks.find(x => x.id === id); const laneNow = a.tasks.filter(x => x.priority === moved.priority);
      announce('「' + moved.title + '」现在在' + PRI[moved.priority] + '第 ' + (laneNow.indexOf(moved) + 1) + ' 位，共 ' + laneNow.length + ' 项');
    }
  });
  sheet.addEventListener('cancel', e => { e.preventDefault(); closeSheet(); });
  sheet.addEventListener('click', e => { if (e.target === sheet) { const r = sheet.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) closeSheet(); } });
  // Drag between priority groups: dropping on a card inserts before it; dropping on a group appends to it.
  document.addEventListener('dragstart', e => { const card = e.target.closest('.lanes [data-task-id]'); if (!card) return; dragId = card.dataset.taskId; card.classList.add('dragging'); document.querySelector('.lanes')?.classList.add('is-dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragId); });
  document.addEventListener('dragover', e => { const lane = e.target.closest('.lane'); if (!lane || !dragId) return; e.preventDefault(); document.querySelectorAll('.drop-before, .lane.drop').forEach(x => x.classList.remove('drop-before', 'drop')); const card = e.target.closest('[data-task-id]'); if (card && card.dataset.taskId !== dragId) card.classList.add('drop-before'); else lane.classList.add('drop'); });
  document.addEventListener('drop', e => { const lane = e.target.closest('.lane'); if (!lane || !dragId) return; e.preventDefault(); const a = current(); const card = e.target.closest('[data-task-id]'); const t = a.tasks.find(x => x.id === dragId); const pr = lane.dataset.lane; const id = dragId; dragId = null; document.querySelectorAll('.dragging, .drop-before, .lane.drop').forEach(x => x.classList.remove('dragging', 'drop-before', 'drop')); if (card && card.dataset.taskId === id) return; moveWithUndo(a, id, { priority: pr, beforeId: card ? card.dataset.taskId : null }, t.priority !== pr ? '「' + t.title + '」移到' + PRI[pr] : '已调整顺序'); });
  document.addEventListener('dragend', () => { dragId = null; document.querySelector('.lanes')?.classList.remove('is-dragging'); document.querySelectorAll('.dragging, .drop-before, .lane.drop').forEach(x => x.classList.remove('dragging', 'drop-before', 'drop')); });
  document.addEventListener('focusout', e => {
    if (popoverOpen && e.target.closest && e.target.closest('.title-wrap') && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('.title-wrap'))) { setTimeout(() => { if (popoverOpen && !document.activeElement.closest('.title-wrap')) { popoverOpen = false; refreshWS(['toolbar']); } }, 0); }
    if (e.target.id !== 'editor-body' && e.target.id !== 'editor-title') return;
    setTimeout(() => {
      const a = current(); const x = artifact();
      if (!a || !x) return;
      if (document.activeElement && (document.activeElement.id === 'editor-body' || document.activeElement.id === 'editor-title')) return;
      commit(); updateSave();
      if (E.intentOf(x.purpose) !== 'commit') return;
      const before = (a.nudges || []).length; E.checkCommitment(a, x);
      if ((a.nudges || []).length > before) { persist(); refreshMargin(); refreshWS(['shelf', 'toolbar']); }
    }, 0);
  });
  window.addEventListener('beforeunload', commit);
  window.addEventListener('scroll', () => document.documentElement.classList.toggle('scrolled', window.scrollY > 4), { passive: true });
  window.addEventListener('resize', () => document.querySelectorAll('.segmented').forEach(layoutSegmented));

  if (L) {
    let scheduled = false;
    L.attach(state, changed => {
      liveStatus();
      if (changed && !scheduled) { scheduled = true; queueMicrotask(() => { scheduled = false; commit(); if (ui.route === 'review') render(); else if (ui.route === 'work') refreshWS(); else render(); liveStatus(); }); }
    });
    L.refresh(current());
    setInterval(() => { if (!document.hidden) L.store.poll(); }, 1500);
  }
  ui.route = routeNow();
  if ((ui.route === 'work' || ui.route === 'review') && !current()) { ui.route = ''; history.replaceState(null, '', '#/'); }
  seedKnown();
  render();
})();
