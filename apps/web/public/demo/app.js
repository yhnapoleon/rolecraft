/* ISY5002 前端原型 · 应用逻辑（纯前端，本地模拟状态）
   - 状态保存在本浏览器 localStorage，不写后端。
   - 角色回答和检索由有限规则模拟；不调用模型。问题、预期、诊断和修订由用户撰写。 */
(function () {
  const D = window.DEMO;
  const KEY = 'isy5002_proto_v1';
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) =>
    String(s ?? '').replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );
  const uid = (p) => p + '_' + Math.random().toString(36).slice(2, 7).toUpperCase();

  /* ---------------- 状态 ---------------- */
  function freshState() {
    return {
      step: 0,
      schema: 2,
      practice: {
        suite: [],
        editor: { text: '', expected: '', basis: '' },
        messages: {},
        diagnoses: {},
        revisionReason: '',
      },
      drafts: {},
      nextAttemptNo: 2,
      introSeen: false,
      selectedQuery: 'DEMO_Q1',
      scenario: {
        role: 'pm',
        desc: '',
        useAuth: false,
        match: null,
        followup: null,
        confirmed: false,
        version: null,
      },
      wb: { nav: 'mat:DEMO_M01', planHidden: true },
      seen: {},
      threads: {},
      config: {
        scope: 'all',
        updateNotice: false,
        fallback: 'guess',
        capacity: 30,
        version: 1,
        savedAt: 'Day 0, 09:30',
      },
      configHistory: [],
      tests: [],
      events: [],
      world: { m05: 'v1', indexM05: 'v1', indexSnapshot: 'Day 0, 00:00', clock: 0 },
      plan: Object.fromEntries(D.FIELDS.map((f) => [f.id, { text: '', evidence: [] }])),
      attempts: [],
      currentAttempt: null,
      attemptNo: 1,
      variant: null,
      drill: null,
      demo: { failNextEval: false, faultNextTest: false, faultUsed: false, bizTimeoutUsed: false },
      cfgDraft: null,
      notifOpen: false,
    };
  }
  let S = load() || freshState();
  S.drafts ||= {};
  S.nextAttemptNo ||= Math.max(S.attemptNo + 1, ...S.attempts.map((a) => a.attemptNo + 1));
  S.selectedQuery ||= 'DEMO_Q1';
  const WORK_KEYS = [
    'scenario',
    'wb',
    'seen',
    'threads',
    'config',
    'configHistory',
    'tests',
    'events',
    'world',
    'plan',
    'attemptNo',
    'variant',
    'drill',
    'demo',
    'cfgDraft',
    'revisedFrom',
    'seenFeedback',
    'selectedQuery',
    'sampleUndo',
    'practice',
  ];
  const clone = (x) => JSON.parse(JSON.stringify(x));
  function ensurePractice() {
    S.practice ||= {
      suite: [],
      editor: { text: '', expected: '', basis: '' },
      messages: {},
      diagnoses: {},
      revisionReason: '',
    };
    return S.practice;
  }
  function locked() {
    return S.attempts.some((a) => a.attemptNo === S.attemptNo);
  }
  function canEdit() {
    if (locked()) {
      toast('这是已提交的记录，请先修订为新版本。');
      return false;
    }
    return true;
  }
  const TOPICS = {
    leave: '年假',
    expense: '设备报销',
    password: '密码重置',
    vpn: 'VPN',
    laptop: '电脑更换',
    salary: '薪资请求',
    refund: '客户退款',
    notice: '日期提示',
    index: '索引更新',
    capacity: '平台容量',
    realtime: '实时同步',
    raise: '扩容',
    effort: '开发工时',
    fallback: '兜底',
    changing: '政策更新',
    stable: '稳定知识',
    who: '试点人群',
    deadline: '时间安排',
    goal: '试点目标',
  };
  function testEvidence(r) {
    return {
      key: 'test:' + r.id,
      kind: 'test',
      ref: r.id,
      configVersion: r.configVersion,
      label: r.text,
      attemptNo: S.attemptNo,
      snapshot: { ...clone(r), diagnosis: clone(ensurePractice().diagnoses[r.id] || {}) },
    };
  }
  function workSnapshot() {
    ensurePractice();
    return clone(
      Object.fromEntries(WORK_KEYS.filter((k) => S[k] !== undefined).map((k) => [k, S[k]])),
    );
  }
  function archiveDraft() {
    S.drafts[S.attemptNo] = workSnapshot();
  }
  let saveOK = true;
  let saveTimer = null;
  function load() {
    try {
      const j = localStorage.getItem(KEY);
      return j ? JSON.parse(j) : null;
    } catch {
      return null;
    }
  }
  function persist() {
    archiveDraft();
    try {
      localStorage.setItem(KEY, JSON.stringify(S));
      saveOK = true;
    } catch {
      saveOK = false;
    }
    const el = $('#savestate');
    if (el) {
      el.className = 'savestate' + (saveOK ? '' : ' failed');
      el.querySelector('span:last-child').textContent = !saveOK
        ? '保存失败，请保留页面'
        : S.cfgDraft
          ? '草稿已保存 · 配置未应用'
          : '已保存到本浏览器';
    }
    const draft = $('.draft-toggle');
    if (draft) {
      draft.querySelector('span').textContent =
        D.FIELDS.filter((f) => S.plan[f.id].text.trim()).length + '/9';
      draft.querySelector('small').textContent =
        D.FIELDS.filter((f) => S.plan[f.id].evidence.length).length + ' 项附来源';
    }
    return saveOK;
  }
  window.addEventListener('pagehide', persist);

  function tick(n = 1) {
    S.world.clock += n;
  }
  function clockLabel() {
    const m = 9 * 60 + 30 + S.world.clock * 20;
    const day = Math.floor(m / (24 * 60));
    const hh = Math.floor((m % (24 * 60)) / 60);
    const mm = m % 60;
    return `Day ${day}, ${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  }

  /* ---------------- 通知与事件 ---------------- */
  function toast(msg, cls = '') {
    const box = $('#toasts');
    while (box.children.length >= 3) box.firstChild.remove();
    const t = document.createElement('div');
    t.className = 'toast ' + cls;
    t.textContent = msg;
    $('#toasts').appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }
  function triggerEvent(id) {
    if (S.events.some((e) => e.id === id)) return;
    const defs = {
      DEMO_E1: {
        title: 'Mei published the revised expenses chapter (M05 v2)',
        body: 'HR policy handbook — expenses chapter is now v2. The assistant index was last rebuilt on Day 0 and will pick up the change at the next nightly rebuild. Compare the material versions and re-run your tests before deciding your update policy.',
        kind: '资料更新',
      },
      DEMO_E2: {
        title: 'Priya: the leadership demo moved earlier, to Wednesday',
        body: 'Ops leadership review moved from Friday to Wednesday. Priya asks whether your plan still holds. Check which of your decisions depend on the timeline. Earlier decisions are judged on what you knew at the time.',
        kind: '演示提前',
      },
    };
    const d = defs[id];
    S.events.push({ id, ...d, ts: clockLabel(), read: false, acked: false });
    if (id === 'DEMO_E1') {
      S.world.m05 = 'v2';
    }
    toast('局面变化：' + d.title, 'amber');
    persist();
  }
  function unreadCount() {
    return S.events.filter((e) => !e.read).length;
  }

  /* ---------------- 证据 ---------------- */
  function evidenceLabel(ev) {
    if (ev.kind === 'para') return `${ev.para} ${ev.version}`;
    if (ev.kind === 'ans') {
      const c = D.COLLEAGUES.find((c) => c.id === ev.colleague);
      return `${c.initials} · ${ev.qid.replace(/^q_[a-z]+_/, '')}`;
    }
    if (ev.kind === 'test') return `${ev.ref} · cfg v${ev.configVersion}`;
    return ev.ref;
  }
  function addEvidence(fieldId, ev) {
    if (S.attempts.some((a) => a.attemptNo === S.attemptNo)) {
      toast('此尝试已提交，请先修订为新版本');
      return;
    }
    const f = S.plan[fieldId];
    if (f.evidence.some((e) => e.key === ev.key)) {
      toast('这条依据已经在该字段里');
      return;
    }
    f.evidence.push(clone(ev));
    persist();
    renderPlan();
    toast(`已引用到「${D.FIELDS.find((x) => x.id === fieldId).label}」`);
  }
  function citeMenu(ev) {
    return `<div class="cite-menu"><button class="btn sm quiet" data-action="cite-open" aria-haspopup="menu">引用到方案 ▾</button>
      <div class="cite-pop" hidden role="menu"><div class="h">加入哪个字段</div>${D.FIELDS.map((f) => `<button role="menuitem" data-action="cite" data-field="${f.id}" data-ev='${esc(JSON.stringify(ev))}'>${esc(f.label)}</button>`).join('')}</div></div>`;
  }

  /* ---------------- 模拟：查询 ---------------- */
  function materialVersion(mid, v) {
    return D.MATERIALS.find((m) => m.id === mid).versions.find((x) => x.v === v);
  }
  function inScope(q, cfg) {
    if (q.kind === 'oos') return false;
    const sc = D.SCOPES.find((s) => s.id === cfg.scope);
    if (sc.docs.includes(q.source)) return true;
    if (sc.stableParas && sc.stableParas.includes(q.para)) return true;
    return false;
  }
  function runQuery(q) {
    const cfg = S.config;
    const rec = {
      id: 'DEMO_T' + S.attemptNo + '_R' + (S.tests.length + 1),
      qid: q.id,
      text: q.text,
      kind: q.kind,
      configVersion: cfg.version,
      cfg: { ...cfg },
      ts: clockLabel(),
      indexSnapshot: S.world.indexSnapshot,
      passages: [],
      flags: [],
    };
    if (!inScope(q, cfg)) {
      rec.scope = 'out';
      if (cfg.fallback === 'guess') {
        const fake = {
          DEMO_Q3:
            'Enterprise customers can request a refund within 30 days of invoice; partial refunds are prorated.',
          DEMO_Q5: 'Salary bands are set by grade; your manager is likely in band M2.',
          DEMO_Q2:
            'Staff may claim home-office equipment costs with receipts through the expense portal.',
          DEMO_Q4: 'Contact the service desk to reset your password.',
          DEMO_Q1: 'Annual leave depends on grade; typically two to three weeks.',
        }[q.id];
        rec.answer = fake;
        rec.answerKind = 'guess';
        rec.flags.push(
          'No retrieved passage: the assistant answered from nothing. Treat as a wrong answer to diagnose, not a platform fault.',
        );
      } else if (cfg.fallback === 'refuse') {
        rec.answer =
          "This question is outside the assistant's approved sources for this pilot. Please contact HR or IT directly.";
        rec.answerKind = 'refuse';
      } else {
        rec.answer =
          'Simulated hand-off to the HR shared mailbox. No message was actually sent. Scenario response target: one working day.';
        rec.answerKind = 'handoff';
      }
    } else {
      rec.scope = 'in';
      const idxV = q.source === 'DEMO_M05' ? S.world.indexM05 : 'v1';
      const mv = materialVersion(q.source, idxV);
      const para = mv.paras.find((p) => p.id === q.para);
      rec.passages.push({ pid: q.para, version: idxV, text: para.text });
      const templ = {
        DEMO_Q1:
          'New employees receive 14 days of annual leave per year, pro-rated in the first year.',
        DEMO_Q4:
          'Use the self-service portal; a reset link goes to your recovery phone within about 5 minutes.',
      };
      if (q.id === 'DEMO_Q2')
        rec.answer =
          idxV === 'v1'
            ? 'You can claim up to SGD 300 per calendar year for approved home-office equipment, with receipts.'
            : 'You can claim up to SGD 500 per calendar year for approved home-office equipment, with receipts. Claims above SGD 300 need Finance sign-off.';
      else rec.answer = templ[q.id];
      rec.answerKind = 'answer';
      rec.sourceNow = q.source === 'DEMO_M05' ? S.world.m05 : 'v1';
      rec.stale = q.source === 'DEMO_M05' && S.world.m05 !== S.world.indexM05 && q.para === 'M05§1';
      if (rec.stale)
        rec.flags.push(
          `Retrieved passage is from M05 ${idxV}; the source is now ${S.world.m05}. The assistant quotes the old text until the next rebuild (up to 24 h).`,
        );
      if (cfg.updateNotice)
        rec.notice = `Answer based on index snapshot ${S.world.indexSnapshot}. Policies changed after that date may not be reflected.`;
    }
    return rec;
  }

  /* ---------------- 模拟：评价 ---------------- */
  function nums(t) {
    return (t.match(/\d+/g) || []).map(Number);
  }
  function has(t, ...ws) {
    const l = t.toLowerCase();
    return ws.some((w) => l.includes(w));
  }
  function evaluate(att) {
    const P = att.snapshot.plan,
      tests = att.snapshot.tests || [];
    return Object.fromEntries(
      D.FIELDS.map((f) => {
        const p = P[f.id],
          t = p.text.trim(),
          ev = p.evidence || [];
        const r = {
          rule: { ok: null, text: 'This prototype does not automatically verify this field.' },
          relation: {
            label: 'NOT_CHECKED',
            text: 'A citation records a source, not proof that it supports your claim. Semantic review has not run.',
          },
          judge: {
            label: 'INSUFFICIENT',
            text: 'Not judged. Requires a reviewer to compare the statement with its evidence.',
          },
          pending:
            'Semantic evaluation is not connected. Reviewer and review time are not assigned.',
          next: 'Compare each claim with the exact source and test version.',
        };
        if (!t) {
          r.rule = { ok: false, text: 'Field is empty.' };
          r.judge = { label: 'NOT_MET', text: 'Requirement not addressed.' };
          r.pending = null;
        } else if (!ev.length) {
          r.relation = { label: 'INSUFFICIENT', text: 'No evidence attached.' };
          r.pending = 'No attached evidence. Awaiting review; not an automatic deduction.';
        }
        if (f.id === 'capacity' && t) {
          const n = t.match(
            /(?:capacity[:\s]*|pilot[:\s]*|wave\s*1[:\s]*)?(\d+)\s*(?:named\s+|concurrent\s+)?users?/i,
          );
          if (
            n &&
            !has(
              t,
              'conditional',
              'approval',
              'pending',
              'subject to',
              'after',
              'if ',
              'later',
              'not ',
              'no more',
              '批准',
              '如果',
            )
          ) {
            const v = Number(n[1]);
            r.rule = {
              ok: v <= 30,
              text: `The first explicit user count is ${v}; the fixed platform limit is 30. Conditional and later-wave claims still require review.`,
            };
            if (v > 30 && !has(t, 'conditional', 'approval', 'pending', 'subject to')) {
              r.judge = {
                label: 'NOT_MET',
                text: 'An unconditional user count exceeds the fixed platform capacity.',
              };
              r.relation = {
                label: 'CONTRADICTED',
                text: 'The stated number exceeds M03§1 v1: 30 users.',
              };
              r.pending = null;
              r.next =
                'Narrow the unconditional pilot population or state and verify the required approval.';
            }
          }
        }
        if (f.id === 'tests' && t) {
          const cited = ev
            .filter((e) => e.kind === 'test')
            .map((e) => e.snapshot || tests.find((x) => x.id === e.ref))
            .filter(Boolean);
          r.rule = {
            ok: null,
            text: `${cited.length} cited run(s) resolve. Record existence does not establish that a test passed; compare your expectation, diagnosis and actual output.`,
          };
        }
        if (
          f.id === 'update' &&
          ev.length &&
          ev.every((e) => e.kind === 'para' && e.para === 'M05§1')
        ) {
          r.relation = {
            label: 'INSUFFICIENT',
            text: 'M05§1 describes the expense cap, not index rebuild timing or your update policy.',
          };
          r.judge = {
            label: 'INSUFFICIENT',
            text: 'This evidence does not establish the update-policy claim.',
          };
        }
        return [f.id, r];
      }),
    );
  }

  /* v3: role entry, routes, independent attempts, accessible overlays */
  const ROUTES = ['hall', 'scenario', 'brief', 'workbench', 'review', 'feedback', 'tasks'];
  let modalOrigin = null,
    entryTransition = null,
    entryPending = false,
    entryToken = 0;
  function writeRoute(replace = false) {
    const path =
      S.step === 0
        ? '#hall'
        : `#pm/${ROUTES[S.step]}?attempt=${S.attemptNo}&nav=${encodeURIComponent(S.wb.nav)}${S.step === 5 && S.currentAttempt ? '&submission=' + S.currentAttempt : ''}`;
    if (location.hash !== path) history[replace ? 'replaceState' : 'pushState']({}, '', path);
  }
  function readRoute(initial = false) {
    const raw = location.hash.slice(1),
      [path, query] = raw.split('?'),
      params = new URLSearchParams(query || '');
    const n = ROUTES.indexOf(path?.replace('pm/', ''));
    const no = Number(params.get('attempt'));
    if (!initial) archiveDraft();
    if (no && S.drafts[no]) restoreWork(S.drafts[no]);
    S.step = n < 0 ? 0 : n;
    if (S.step > 2 && !S.scenario.confirmed) S.step = 1;
    if (
      params.get('nav') &&
      /^(mat:DEMO_M0[1-6]|col:DEMO_C_(MGR|TECH|BIZ)|test|cfg)$/.test(params.get('nav'))
    )
      S.wb.nav = params.get('nav');
    S.currentAttempt =
      S.attempts.find((a) => a.id === params.get('submission') && a.attemptNo === S.attemptNo)
        ?.id ||
      S.attempts.find((a) => a.attemptNo === S.attemptNo)?.id ||
      null;
    S.notifOpen = false;
    persist();
    if (!initial) {
      closeModal();
      render();
    }
    if (initial) writeRoute(true);
  }
  window.addEventListener('popstate', () => {
    finishEntry();
    readRoute();
  });
  function focusMain() {
    const e = $('#view h1') || $('#view h2');
    if (e) {
      e.tabIndex = -1;
      e.focus({ preventScroll: true });
    }
  }
  function showModal(title, html, cls = '') {
    closeModal();
    modalOrigin = document.activeElement;
    const bg = document.createElement('div');
    bg.className = 'modal-bg ' + cls;
    bg.innerHTML = `<section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="mh"><b id="modal-title">${esc(title)}</b><button class="btn sm" data-action="close-modal">关闭</button></div><div class="mb">${html}</div></section>`;
    document.body.appendChild(bg);
    document.body.classList.add('overlay-open');
    $('#app').inert = true;
    $('.demo-panel').inert = true;
    bg.querySelector('button').focus();
  }
  function closeModal() {
    clearTimeout(voiceTimer);
    if (activeUtterance) {
      activeUtterance.onerror = null;
      activeUtterance.onend = null;
      activeUtterance.onstart = null;
    }
    window.speechSynthesis?.cancel();
    const bg = $('.modal-bg');
    if (!bg) return;
    bg.remove();
    document.body.classList.remove('overlay-open');
    $('#app').inert = false;
    $('.demo-panel').inert = false;
    if (modalOrigin?.isConnected) modalOrigin.focus({ preventScroll: true });
    else focusMain();
    modalOrigin = null;
  }
  function showSample(k) {
    const sp = D.SAMPLE_PLANS[k];
    showModal(
      '示例预览 · 非参考答案',
      `<p class="note amber">填入将替换九字段并清空旧引用，防止示例与旧证据错配。可以撤销恢复。示例中的测试声明也必须重新验证。</p>${D.FIELDS.map((f) => `<section class="sample-field"><h3>${f.label}</h3><p>${esc(sp[f.id])}</p></section>`).join('')}<button class="btn primary" data-action="sample-apply" data-k="${k}">确认替换九字段</button>`,
    );
  }
  function finishEntry() {
    entryToken++;
    const transition = entryTransition;
    entryTransition = null;
    entryPending = false;
    transition?.skipTransition();
    document.documentElement.classList.remove('role-entry');
    document.querySelectorAll('[data-entry-motion]').forEach((el) => {
      el.getAnimations().forEach((animation) => animation.cancel());
      delete el.dataset.entryMotion;
    });
  }
  function enterPM(custom = false, keyboard = false) {
    if (entryPending) return;
    finishEntry();
    if (!custom && !S.scenario.confirmed) {
      S.scenario.confirmed = true;
      S.scenario.version = D.SCENARIO.version;
      S.scenario.desc ||= D.INTAKE_EXAMPLES[0].text;
    }
    const token = entryToken;
    const navigate = () => {
      if (token === entryToken) go(custom ? 1 : 2);
    };
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const limited =
      navigator.connection?.saveData ||
      (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 2);
    // The destination is the live workspace. No timer, overlay, or extra route.
    if (reduced || limited || keyboard) {
      navigate();
      return;
    }
    if (document.startViewTransition) {
      entryPending = true;
      document.documentElement.classList.add('role-entry');
      const transition = document.startViewTransition(() => {
        navigate();
        if (token === entryToken) entryPending = false;
      });
      entryTransition = transition;
      // Resizing or a second navigation may legitimately skip snapshot animation.
      transition.ready.catch(() => {});
      transition.finished
        .catch(() => {})
        .finally(() => {
          if (entryTransition !== transition) return;
          entryTransition = null;
          entryPending = false;
          document.documentElement.classList.remove('role-entry');
        });
    } else {
      navigate();
      // Same short arrival in browsers without View Transitions; never blocks input.
      const view = $('#view');
      if (!view?.animate) return;
      view.dataset.entryMotion = '';
      const animation = view.animate(
        [
          { opacity: 0, transform: 'translateY(10px)' },
          { opacity: 1, transform: 'translateY(0)' },
        ],
        { duration: 340, easing: 'cubic-bezier(.22,1,.36,1)' },
      );
      animation.finished.catch(() => {}).finally(() => delete view.dataset.entryMotion);
    }
  }
  function renderHall(v) {
    const active = S.scenario.confirmed;
    const written = D.FIELDS.filter((f) => S.plan[f.id].text.trim()).length;
    v.innerHTML = `<div class="hall"><header class="hall-nav"><a href="#hall" class="hall-brand">PRACTICE<span> / AI WORK LAB</span></a><div class="hall-utility"><span class="hall-status">无需注册 · 本浏览器保存</span>${active ? '<button class="hall-history" data-action="go" data-step="6">我的练习 ↗</button>' : ''}</div></header>
      <section class="hall-hero"><img class="hall-image" src="assets/studio-entry.png" alt="" fetchpriority="high"><div class="hall-image-shade"></div><div class="hall-copy"><p class="eyebrow">AI 职业任务训练场</p><h1>进入角色。<br>交出<span>你的判断。</span></h1><p class="hall-lede">自由对话调查，亲手测试 AI 助手。<br>改配置、重测，用证据修订你的决定。</p></div><aside class="hall-brief"><span class="hall-brief-label">你的第一个项目 · 虚构情境</span><h2>Northwind<br><span>知识助手试点</span></h2><p>经理希望一周内开放第一批试点。<br>你来决定怎样做，以及何时该暂停。</p><div class="hall-team"><span class="mini-avatar pn">PN</span><span class="mini-avatar dk">DK</span><span class="mini-avatar ml">ML</span><span>与你一起工作的三位同事</span></div></aside></section>
      <section class="career-section" aria-labelledby="career-title"><div class="section-caption"><h2 id="career-title">选择你的职业</h2><span>从调查，到可执行的交付</span></div><div class="career-grid"><article class="career-card live"><div class="career-meta"><span class="career-number">PRODUCT</span><span class="available">可体验</span></div><h3>AI 产品经理</h3><p>自由问同事，自己写测试，改配置后重跑。<br>用运行证据交付决定，再根据反馈修订。</p><div class="career-detail"><span>主任务与两个模拟变体</span><span>约 ${D.SCENARIO.expectedMinutes} 分钟</span>${active ? `<span>当前交付稿 ${written}/9</span>` : ''}</div><div class="career-actions"><button class="career-enter" data-action="enter-pm">${active ? '继续 AI 产品经理工作台' : '进入 AI 产品经理工作台'}<span aria-hidden="true">↗</span></button><button class="career-context" data-action="enter-pm" data-intake="true">${active ? '查看或调整练习情境' : '先描述自己的业务情境'} →</button></div></article><article class="career-card soon"><div class="career-meta"><span class="career-number">ENGINEERING</span><span class="coming">后续路径</span></div><h3>AI 应用工程师</h3><p>面向构建与调试的职业路径。<br>Coding Agent 实操后置，当前尚未开放。</p><button disabled>尚未开放</button></article></div></section>
      <section class="hall-practice"><div><p class="eyebrow">这次，由你亲手完成</p><h2>从一句问题，<br>到一份经得起验证的决定。</h2><p>你练习产品判断。三个不同的角色，陪你完成同一个任务。</p></div><ol><li><b>01</b><div><strong>问 AI 同事</strong><p>自由文字提问 / 语音演示，追问目标、政策与限制。</p><span>同事提供信息 · 有限情境模拟</span></div></li><li><b>02</b><div><strong>亲自测试知识助手</strong><p>自写问题和预期，检查引用，修改配置并比较同题结果。</p><span>助手是被测试的应用 · 规则模拟运行</span></div></li><li><b>03</b><div><strong>提交，获得证据反馈，再修订</strong><p>留下自己的决定、测试集和版本，进入新局面独立判断。</p><span>反馈核对实际记录 · 非真实模型评分</span></div></li></ol></section><footer class="hall-footer"><p><b>前端演示 · 未审核 D2</b> 同事、检索和反馈均为有限模拟；语音演示不录音。工程师与案例面试后置。</p></footer></div>`;
  }
  function restoreWork(d) {
    for (const k of WORK_KEYS) {
      if (d[k] !== undefined) S[k] = clone(d[k]);
      else delete S[k];
    }
  }
  function resumeDraft(no) {
    archiveDraft();
    const d = S.drafts[no];
    if (!d) return;
    restoreWork(d);
    S.currentAttempt = null;
    persist();
    go(3);
  }
  function taskGuide() {
    const n = S.wb.nav,
      written = D.FIELDS.filter((f) => S.plan[f.id].text.trim()).length;
    const stage = n.startsWith('col:')
      ? 'talk'
      : n === 'test'
        ? 'test'
        : n === 'cfg'
          ? 'config'
          : 'sources';
    return `<div class="journey-bar"><div class="journey-mission"><span class="mission-dot"></span><b>${S.variant === 'DEMO_V2' ? '新增 35 人的请求，重新作出试点决定' : S.variant === 'DEMO_V1' ? '政策中途更新，重新作出试点决定' : '你的任务：一周内，提出有依据的知识助手试点决定'}</b><span>${S.revisedFrom ? '修订练习' : S.variant ? '独立变体' : '首次练习'} · ${S.attemptNo}</span></div><nav class="journey-steps" aria-label="实操步骤">${[
      ['talk', '01', '问同事', 'col:DEMO_C_TECH'],
      ['test', '02', '自己测试', 'test'],
      ['config', '03', '调整与重测', 'cfg'],
    ]
      .map(
        ([k, i, t, n]) =>
          `<button class="${stage === k ? 'current' : ''}" data-action="nav" data-nav="${n}"><small>${i}</small>${t}</button>`,
      )
      .join(
        '',
      )}<button data-action="go" data-step="4"><small>04</small>交付与反馈 <em>${written}/9</em></button><button class="journey-source ${stage === 'sources' ? 'current' : ''}" data-action="nav" data-nav="mat:DEMO_M01">原始材料</button></nav>${locked() ? `<div class="snapshot-banner">当前是已提交作品，原始记录保留。<button data-action="revise" data-id="${S.attempts.find((a) => a.attemptNo === S.attemptNo).id}">创建修订，继续实操 ↗</button></div>` : ''}</div>`;
  }

  function stepEnabled(n) {
    if (n <= 2) return true;
    if (!S.scenario.confirmed) return false;
    if (n === 5) return S.attempts.length > 0;
    return true;
  }
  function go(n) {
    if (!stepEnabled(n)) return;
    closeModal();
    if (n === 5) {
      const att =
        S.attempts.find((a) => a.id === S.currentAttempt && a.attemptNo === S.attemptNo) ||
        S.attempts.find((a) => a.attemptNo === S.attemptNo) ||
        S.attempts.at(-1);
      if (att) {
        if (att.attemptNo !== S.attemptNo) {
          archiveDraft();
          restoreWork(att.snapshot);
        }
        S.currentAttempt = att.id;
      }
    }
    S.step = n;
    S.notifOpen = false;
    if (n === 4) ensureEventBeforeReview();
    persist();
    writeRoute();
    render();
    focusMain();
  }

  function ensureEventBeforeReview() {
    if (!S.variant && !S.events.some((e) => e.id === 'DEMO_E2')) triggerEvent('DEMO_E2');
  }

  const MATERIAL_NAMES = [
    '经理的委托',
    '助手产品说明',
    '平台与容量',
    '本周工程资源',
    '人事政策手册',
    'IT 服务 FAQ',
  ];
  const FIELD_NAMES = {
    users: '用户范围',
    knowledge: '知识范围',
    capacity: '试点容量',
    update: '更新机制',
    fallback: '兜底方式',
    work: '执行安排',
    tests: '验收测试',
    metrics: '成功指标',
    exit: '退出条件',
  };
  function render() {
    const app = $('#app');
    document.body.dataset.screen = S.step === 0 ? 'hall' : 'workspace';
    app.className = S.step === 0 ? 'app is-hall' : 'app studio';
    app.scrollTop = 0; // The hall scroll position must not shift the workspace shell.
    if (S.step === 0) {
      app.innerHTML = '<div class="role-field" aria-hidden="true"></div><main id="view"></main>';
      renderHall($('#view'));
      renderNotif();
      return;
    }
    const names = {
      1: '练习情境',
      2: '项目委托',
      3:
        S.wb.nav === 'test'
          ? '助手实验室'
          : S.wb.nav === 'cfg'
            ? '助手配置'
            : S.wb.nav.startsWith('col:')
              ? '团队沟通'
              : '项目资料',
      4: '交付审阅',
      5: '反馈与复盘',
      6: '练习档案',
    };
    app.innerHTML = `<aside class="studio-rail" aria-label="项目导航"><button class="studio-logo" data-action="go" data-step="0" aria-label="返回职业大厅">P<span>PRACTICE<small>WORKSPACE</small></span></button><div class="project-id"><span class="project-monogram">N</span><span>Northwind<small>知识助手试点</small></span><span class="project-dot"></span></div><nav class="rail-main"><button class="rail-link ${S.step === 2 ? 'selected' : ''}" data-action="go" data-step="2"><span class="rail-glyph">◈</span>项目委托</button><button class="rail-link ${S.step === 3 ? 'selected' : ''}" data-action="go" data-step="3"><span class="rail-glyph">↗</span>调查工作区</button><div id="wbnav"></div><div class="rail-divider"></div>${[
      [4, '交付审阅', '▤'],
      [5, '反馈与复盘', '↺'],
      [6, '练习档案', '▦'],
    ]
      .map(
        ([n, t, g]) =>
          `<button class="rail-link ${S.step === n ? 'selected' : ''}" data-action="go" data-step="${n}" ${stepEnabled(n) ? '' : 'disabled'}><span class="rail-glyph">${g}</span>${t}</button>`,
      )
      .join(
        '',
      )}</nav><div class="rail-footer"><span class="your-avatar">YOU</span><span>你的岗位<small>AI 产品经理</small></span><button data-action="go" data-step="1" aria-label="更换练习情境" class="rail-context">情境</button></div></aside>
    <header class="studio-top"><div class="studio-breadcrumb"><button class="mobile-menu btn" data-action="project-menu" aria-label="打开项目导航">☰</button><span>Northwind</span><i>/</i><strong>${names[S.step]}</strong><span class="workspace-version">练习 ${S.attemptNo}</span></div><div class="studio-status"><div role="status" class="savestate ${saveOK ? '' : 'failed'}" id="savestate"><span class="dot"></span><span>${!saveOK ? '保存失败，请保留页面' : S.cfgDraft ? '草稿已保存 · 配置未应用' : '已保存到本浏览器'}</span></div><button class="iconbtn" data-action="notif" aria-label="通知">动态${unreadCount() ? `<span class="badge">${unreadCount()}</span>` : ''}</button></div></header>
    <div class="studio-boundary"><span><i></i>DEMO · 同事、助手与反馈均为模拟 · 未审核 D2</span><span class="boundary-actions"><button data-action="go" data-step="2">实操任务入口 ↗</button><button data-action="practice-info">模拟边界</button></span></div><main class="view" id="view"></main>`;
    ({
      1: renderIntake,
      2: renderBrief,
      3: renderWorkbench,
      4: renderReview,
      5: renderFeedback,
      6: renderTasks,
    })[S.step]($('#view'));
    renderNav();
    renderNotif();
  }

  function renderIntake(v) {
    const sc = S.scenario;
    v.innerHTML = `<div class="page">
      <p class="kicker">练习设置 / 业务情境</p>
      <h1>为这次练习选择情境</h1>
      <p class="lede">你已进入 AI 产品经理工作台。可以直接使用演示任务，也可以描述业务来匹配受支持情境；不会生成任意公司的完整流程。</p>
      <section class="card stack" style="margin-top:18px">
        <div class="note">已选择 AI 产品经理 · 一个主任务与两个模拟变体。<button class="btn quiet" data-action="go" data-step="0">返回职业大厅</button></div>
        </div>
        <div>
          <h3>你想练习的业务</h3>
          <p class="small muted">用自然语言写，或选一个示例。描述用于匹配模板和必要追问，不会直接改变场景事实或评价依据。</p>
          <textarea id="desc" rows="3" placeholder="例如：I want to practise opening an internal policy Q&A assistant for staff, as a pilot, within a week.">${esc(sc.desc)}</textarea>
          <div class="examples" style="margin-top:8px">${D.INTAKE_EXAMPLES.map((e) => `<button class="chip-ex" data-action="example" data-id="${e.id}">${esc(e.text)}</button>`).join('')}</div>
        </div>
        <div>
          <label class="row" style="gap:10px"><input type="checkbox" id="useauth" ${sc.useAuth ? 'checked' : ''}> 附加已授权的背景文本（演示用内置示例，不上传真实资料）</label>
          ${sc.useAuth ? `<div class="note small" style="margin-top:8px">${esc(D.AUTHORISED_TEXT_SAMPLE)}<br><span class="muted">演示假设：背景文本只影响模板匹配和追问，不写入评价依据，本次会话结束不保留。</span></div>` : ''}
        </div>
        <div class="row" style="justify-content:space-between">
          <span class="small muted">语言：导航中文；任务材料、同事回答与正式提交为英文（v0.8 首轮英文评测）。</span>
          <button class="btn primary" data-action="match">匹配场景</button>
        </div>
      </section>
      ${sc.match ? renderMatch(sc) : ''}
    </div>`;
  }
  function renderMatch(sc) {
    const m = sc.match;
    if (m.status === 'none')
      return `<section class="card" style="margin-top:16px;border-color:var(--amber)">
      <h3>这个情境暂时不能构造</h3>
      <p class="muted">你的描述看起来不是 AI 产品经理的知识助手类任务。当前只有一个演示模板 · 未审核 D2，不会凭描述生成新公司或新系统。你的输入已保留。</p>
      <div class="row"><button class="btn" data-action="example" data-id="ex1">改用示例：内部政策问答助手试点</button><button class="btn quiet" data-action="clear-match">保留输入，稍后再试</button></div>
    </section>`;
    if (m.status === 'empty')
      return `<section class="card" style="margin-top:16px"><h3>先写一句你想练什么</h3><p class="muted">没有描述也可以直接用示例进入。</p><div class="examples">${D.INTAKE_EXAMPLES.slice(
        0,
        2,
      )
        .map(
          (e) =>
            `<button class="chip-ex" data-action="example" data-id="${e.id}">${esc(e.text)}</button>`,
        )
        .join('')}</div></section>`;
    return `<section class="matchcard" style="margin-top:16px" aria-live="polite">
      <header><div><b>匹配到模板</b> <span class="pill mono">${D.SCENARIO.id}</span> <span class="muted small">${esc(D.SCENARIO.title)}</span></div><span class="pill">演示模板 · 未审核 D2</span></header>
      <div class="body">
        <div><b>从你的描述采用了</b><ul>${m.adopted.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>
        <div><b>没有建模的部分</b><ul>${m.notModeled.length ? m.notModeled.map((x) => `<li>${esc(x)}</li>`).join('') : '<li class="muted">无</li>'}</ul></div>
        <div><b>材料与评价的来源</b><ul><li>虚构公司 Northwind Retail Ops 的 6 份材料，带版本</li><li>三位模拟同事，各自只知道自己范围内的事</li><li>评价依据不对你显示；反馈会指向你能看到的记录</li></ul></div>
        <div><b>一个必要的追问</b><p class="small muted">只问会改变任务的信息。</p>
          <div class="radio"><label><input type="radio" name="fu" value="staff" ${sc.followup === 'staff' ? 'checked' : ''}> 试点对象是内部员工</label><label><input type="radio" name="fu" value="external" ${sc.followup === 'external' ? 'checked' : ''}> 试点对象是外部客户</label></div>
          ${sc.followup === 'external' ? '<p class="field-err">外部客户场景不在当前模板内。可以继续，但任务会按内部员工试点进行。</p>' : ''}
        </div>
      </div>
      <div class="foot"><span class="small muted">确认后本次练习固定为 ${esc(D.SCENARIO.version)}；之后修改描述不会改变已开始的练习。</span><button class="btn primary" data-action="confirm-scenario" ${sc.followup ? '' : 'disabled'}>确认并进入任务简报</button></div>
    </section>`;
  }
  function doMatch() {
    const desc = $('#desc').value.trim();
    S.scenario.desc = desc;
    if (!desc) {
      S.scenario.match = { status: 'empty' };
      persist();
      render();
      return;
    }
    const l = desc.toLowerCase();
    const ok = has(
      l,
      'assistant',
      'knowledge',
      'policy',
      'q&a',
      'faq',
      'pilot',
      '助手',
      '知识',
      '问答',
      '试点',
      'hr',
      'staff',
      'internal',
    );
    if (!ok) {
      S.scenario.match = { status: 'none' };
      persist();
      render();
      return;
    }
    const adopted = [],
      notModeled = [];
    if (has(l, 'policy', 'hr', '政策'))
      adopted.push("Staff policy questions as the assistant's domain");
    if (has(l, 'pilot', 'small group', 'first', '试点'))
      adopted.push('A pilot with a limited first group');
    if (has(l, 'week', '一周', 'days')) adopted.push('A one-week timeline');
    if (has(l, 'email', '邮件')) adopted.push('Current baseline: questions answered by email');
    if (!adopted.length) adopted.push('An internal knowledge-assistant pilot for staff');
    if (has(l, 'pharmacy', 'bank', 'hospital', 'school', '药店', '银行'))
      notModeled.push(
        'Your specific industry; the template uses a fictional retail operations company',
      );
    if (has(l, 'customer', '客户'))
      notModeled.push('External customers; the template covers internal staff only');
    if (has(l, 'mobile', 'app', 'voice'))
      notModeled.push('Channel details; the assistant is a web tool in this template');
    S.scenario.match = { status: 'ok', adopted, notModeled };
    persist();
    render();
    setTimeout(() => $('.matchcard')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  }

  /* ---- 页 2 ---- */
  function renderBrief(v) {
    const answers = Object.values(S.threads)
        .flat()
        .filter((x) => x.type === 'a').length,
      technical = (S.threads.DEMO_C_TECH || []).some(
        (x) =>
          x.type === 'a' && ['q_tech_capacity', 'q_tech_effort', 'q_tech_index'].includes(x.qid),
      ),
      runs = S.tests.filter((x) => !x.fault).length,
      written = D.FIELDS.filter((f) => S.plan[f.id].text.trim()).length;
    v.innerHTML = `<div class="mission-page"><div class="mission-mast"><p class="eyebrow">YOUR ASSIGNMENT / INTERNAL TOOLS</p><span class="mission-status"><i></i>${written || answers || runs ? '进行中' : '等待你接手'} · ${S.variant ? '独立变体 · 无解题提示' : '主任务'}</span></div><div class="mission-layout"><section class="mission-story"><p class="role-intro">你是 Northwind 的 AI 产品经理。</p><h1>${S.variant === 'DEMO_V2' ? '业务提出了<br><span>新的试点人群。</span>' : S.variant === 'DEMO_V1' ? '政策变了，<br><span>试点怎样继续？</span>' : '一周内，<br><span>开放知识助手试点。</span>'}</h1><p class="mission-deck">哪些人可以先用？哪些问题值得信任？<br>你的任务，是用调查和实际测试给出上线判断。</p><div class="commission"><div class="commission-by"><span class="avatar pn">PN</span><div><b>Priya Nair <small>发给你</small></b><span>Internal Tools 负责人 · Day 0, 09:12</span></div></div><blockquote>${S.variant === 'DEMO_V2' ? '“Sales wants to add 35 people before the demo. Please revisit your decision.”' : S.variant === 'DEMO_V1' ? '“HR has reissued the expense policy on day 3. Please review the pilot.”' : '“I want a first group of staff using it within one week. Please own the plan.”'}</blockquote><p>自己确定还需要哪些信息，通过调查和测试，交出有依据的试点决定。</p><button class="text-link" data-action="nav-go" data-nav="mat:DEMO_M01">阅读完整委托与原文来源 ↗</button></div><div class="mission-action"><button class="btn primary" data-action="nav-go" data-nav="${technical ? 'test' : 'col:DEMO_C_MGR'}">${technical ? '继续测试自己的问题' : '和同事聊聊 · 文字 / 语音演示'} <span>↗</span></button><button class="btn quiet" data-action="nav-go" data-nav="test">直接设计测试 ↗</button></div><p class="microcopy">助手先检索材料，再生成回答；原文与索引可能不同步。调查顺序由你决定。</p></section><aside class="mission-dossier"><div class="dossier-top"><span class="eyebrow">THE DELIVERABLE</span><span>↗</span></div><div class="dossier-visual" aria-hidden="true"><img src="assets/studio-entry.png" alt=""></div><h2>一份可以执行的<br>试点决定。</h2><p>把范围、运行方式和验证依据讲清楚。九个字段帮助你组织决定，不替你作答。</p><div class="deliverable-lines"><div><b>开放边界</b><span>用户 · 知识 · 容量</span></div><div><b>运行安排</b><span>更新 · 兜底 · 工作项</span></div><div><b>验证与退出</b><span>测试 · 指标 · 退出条件</span></div></div><div class="mission-evidence"><span>你的工作已留下</span><div><b>${answers}</b> 段回答 <b>${runs}</b> 次测试 <b>${written}/9</b> 字段</div></div><button class="text-link" data-action="go" data-step="4">打开交付审阅 →</button><div class="dossier-foot">约 ${D.SCENARIO.expectedMinutes} 分钟 · 可随时暂停<br>本浏览器自动保存 · 方案用英文；提问与诊断可用中文</div></aside></div>${S.variant ? `<div class="mission-variant"><b>当前变体：${esc(D.SCENARIO.variants.find((x) => x.id === S.variant).title)}</b><p>${esc(D.SCENARIO.variants.find((x) => x.id === S.variant).desc)}</p></div>` : ''}<section class="mission-routes"><div><p class="eyebrow">PRACTICE CONTEXT</p><h3>换一种局面，再做判断</h3><p>主任务与两种变体均为模拟素材，未审核。</p></div><div class="route-list"><button data-action="restart" ${!S.variant ? 'disabled' : ''}><span>主任务</span><b>知识助手试点</b><i>↗</i></button>${D.SCENARIO.variants.map((x) => `<button data-action="variant" data-id="${x.id}" ${S.variant === x.id ? 'disabled' : ''}><span>变体</span><b>${x.id === 'DEMO_V1' ? '政策中途更新' : '试点人群扩大'}</b><i>↗</i></button>`).join('')}</div></section></div>`;
  }

  function renderWorkbench(v) {
    v.innerHTML = `${taskGuide()}<label class="mobile-nav">切换工作内容<select id="wb-select">${D.MATERIALS.map((m, i) => `<option value="mat:${m.id}" ${S.wb.nav === 'mat:' + m.id ? 'selected' : ''}>资料 · ${MATERIAL_NAMES[i]}</option>`).join('')}${D.COLLEAGUES.map((c) => `<option value="col:${c.id}" ${S.wb.nav === 'col:' + c.id ? 'selected' : ''}>同事 · ${c.name}</option>`).join('')}<option value="test" ${S.wb.nav === 'test' ? 'selected' : ''}>助手实验室</option><option value="cfg" ${S.wb.nav === 'cfg' ? 'selected' : ''}>助手配置</option></select></label><div class="wb ${S.wb.planHidden ? 'plan-hidden' : ''}"><section class="wb-main" id="wbmain"></section><aside class="wb-plan" aria-label="交付稿"><div class="plan-head"><div><span class="eyebrow">DECISION DRAFT</span><button data-action="toggle-plan" aria-label="收起交付稿">×</button></div><h3>你的试点决定</h3><p>引用留在决定旁边。正式提交英文；未确认的内容可写 Unknown。</p></div><div class="plan-body" id="planbody"></div></aside></div>`;
    renderMain();
    renderPlan();
  }

  function renderNav() {
    const nav = S.step === 3 ? S.wb.nav : '',
      el = $('#wbnav');
    if (!el) return;
    const item = (key, label) =>
      `<button class="navitem ${nav === key ? 'active' : ''}" data-action="nav" data-nav="${key}" ${nav === key ? 'aria-current="page"' : ''}>${label}</button>`;
    el.innerHTML = `<div class="rail-section"><h4>调查对象 <span>AI 同事 · 模拟</span></h4>${D.COLLEAGUES.map((c) => item('col:' + c.id, `<span class="mini-avatar ${c.initials.toLowerCase()}">${c.initials}</span><span>${c.name.split(' ')[0]}<small>${c.id === 'DEMO_C_TECH' ? '技术与资源' : c.id === 'DEMO_C_MGR' ? '目标与人群' : '业务与政策'}</small></span>`)).join('')}</div><div class="rail-section"><h4>被测试的应用 <span>模拟</span></h4>${item('test', '<span class="rail-glyph">⌘</span>助手实验室')}${item('cfg', '<span class="rail-glyph">≋</span>配置与重测 <span class="v">v' + S.config.version + '</span>')}</div><details class="rail-materials" ${nav.startsWith('mat:') ? 'open' : ''}><summary>原始材料 · 6 份</summary>${D.MATERIALS.map((m, i) => item('mat:' + m.id, `<span>${MATERIAL_NAMES[i]}</span><span class="v">${m.id === 'DEMO_M05' ? S.world.m05 : 'v1'}</span>`)).join('')}</details>`;
  }

  function renderMain() {
    const [kind, id] = S.wb.nav.split(':');
    const el = $('#wbmain');
    el.dataset.mode = kind;
    if (kind === 'mat') el.innerHTML = renderMaterial(id);
    else if (kind === 'col') el.innerHTML = renderColleague(id);
    else if (kind === 'test') el.innerHTML = renderTests();
    else {
      el.innerHTML = renderConfig();
      if (locked()) {
        el.querySelectorAll('input').forEach((x) => (x.disabled = true));
        el.querySelectorAll(
          '[data-action=cfg-save],[data-action=cfg-reset],[data-action=cfg-retest]',
        ).forEach((x) => (x.disabled = true));
        el.insertAdjacentHTML(
          'afterbegin',
          '<p class="note">已提交的配置快照。需要修改时，请从反馈页创建修订。</p>',
        );
      }
    }
  }
  function renderMaterial(mid) {
    const m = D.MATERIALS.find((x) => x.id === mid);
    const cur = mid === 'DEMO_M05' ? S.world.m05 : 'v1';
    const view = (S.wb.matView && S.wb.matView[mid]) || cur;
    if (!S.seen[mid]) S.seen[mid] = [];
    if (!S.seen[mid].includes(view)) {
      S.seen[mid].push(view);
      persist();
    }
    const ver = m.versions.find((x) => x.v === view);
    const prev = m.versions.find((x) => x.v === 'v1');
    return `<div class="panel-head"><div><p class="kicker">材料 · ${esc(m.kind)} · ${esc(m.owner)}</p><h2>${esc(m.title)}</h2><p>逐段阅读；需要时把某段引用进方案，引用会带上版本号。</p></div></div>
      ${S.variant ? '<p class="small muted">独立变体：自行决定调查、测试与交付安排。</p>' : ''}<article class="doc"><div class="doc-head"><span class="mono muted">${m.id} · ${esc(mid === 'DEMO_M05' && view === 'v2' ? S.events.find((e) => e.id === 'DEMO_E1')?.ts || ver.date : ver.date)}</span>
        ${
          m.versions.length > 1
            ? `<div class="vtabs" role="tablist">${m.versions
                .filter((x) => x.v === 'v1' || cur === 'v2')
                .map(
                  (x) =>
                    `<button role="tab" class="${view === x.v ? 'on' : ''}" data-action="matview" data-mid="${mid}" data-v="${x.v}">${x.v}${x.v === cur ? ' · current' : ''}</button>`,
                )
                .join('')}</div>`
            : '<span class="pill mono">v1 · current</span>'
        }</div>
        ${view === 'v2' ? `<div class="note amber" style="margin:10px 18px 0">v2 published ${esc(S.events.find((e) => e.id === 'DEMO_E1')?.ts || 'at the recorded event time')}. Changed passages are highlighted. The assistant index currently holds ${esc(S.world.indexM05)}.</div>` : ''}
        ${ver.paras
          .map((p) => {
            const changed = view === 'v2' && prev.paras.find((q) => q.id === p.id)?.text !== p.text;
            return `<div class="para ${changed ? 'changed' : ''}"><span class="pid">${p.id}</span><div class="txt">${esc(p.text)}</div><div class="act">${citeMenu({ key: `para:${mid}:${view}:${p.id}`, kind: 'para', material: mid, version: view, para: p.id, ref: p.id, snapshot: { text: p.text, date: mid === 'DEMO_M05' && view === 'v2' ? S.events.find((e) => e.id === 'DEMO_E1')?.ts || ver.date : ver.date } })}</div></div>`;
          })
          .join('')}
      </article><div class="context-next" ${S.variant ? 'hidden' : ''}><span>读完之后</span><p>${mid === 'DEMO_M01' ? '向技术负责人确认容量和开发限制，别急着承诺上线。' : mid === 'DEMO_M05' ? '在实验室检查助手引用的是哪个政策版本。' : '把关键段落引用进交付稿，或向同事追问未确定的内容。'}</p><button class="text-link" data-action="nav" data-nav="${mid === 'DEMO_M01' ? 'col:DEMO_C_TECH' : 'test'}">${mid === 'DEMO_M01' ? '与 Daniel 沟通' : '去助手实验室'} →</button></div>`;
  }
  function renderColleague(cid) {
    const c = D.COLLEAGUES.find((x) => x.id === cid),
      th = S.threads[cid] || [],
      pr = ensurePractice();
    return `<div class="dialogue-workspace"><section class="free-conversation"><header class="conversation-head"><span class="avatar ${c.initials.toLowerCase()}">${c.initials}</span><div><p class="kicker">AI 同事 · 有限情境模拟</p><h2>${esc(c.name)}</h2><p>${esc(c.role)}</p></div><button class="btn sm" data-action="voice-open" data-target="chat" data-cid="${cid}" ${locked() ? 'disabled' : ''}>◉ 语音演示</button></header><div class="colleague-switch">${D.COLLEAGUES.map((x) => `<button data-action="nav" data-nav="col:${x.id}" class="${x.id === cid ? 'active' : ''}">${x.name.split(' ')[0]} <small>${x.id === 'DEMO_C_MGR' ? '目标' : x.id === 'DEMO_C_TECH' ? '技术' : '业务'}</small></button>`).join('')}</div><div class="thread" aria-live="polite">${th.length ? th.map((x) => renderMsg(c, x)).join('') : `<div class="conversation-empty"><p class="eyebrow">你来决定先确认什么</p><h3>从一个真正想问的问题开始。</h3><p>你的问题会留在对话里。回答附来源，未知事项会明确说明。</p></div>`}</div><div class="free-composer"><label for="colleague-question">问 ${esc(c.name.split(' ')[0])}</label><div class="composer-input"><textarea id="colleague-question" data-chat="${cid}" rows="2" maxlength="2000" placeholder="写下你想确认的问题，或继续追问……" ${locked() ? 'disabled' : ''}>${esc(pr.messages[cid] || '')}</textarea><button class="btn primary" data-action="ask-free" data-cid="${cid}" ${locked() ? 'disabled' : ''}>发送 ↗</button></div><div class="composer-foot"><span>文字输入 · ⌘ / Ctrl + Enter 发送 · 不调用真实模型</span><button class="text-link" data-action="voice-open" data-target="chat" data-cid="${cid}" ${locked() ? 'disabled' : ''}>文字 / 语音演示</button></div></div></section><aside class="investigation-note"><p class="eyebrow">此刻的工作</p><h3>把信息缺口<br>变成调查问题。</h3><p>同事提供他知道的事实；是否足以支持决定，由你判断。</p><details><summary>${c.name.split(' ')[0]} 负责什么</summary><p>${esc(c.knows)}</p><p>${esc(c.unknown)}</p></details><div class="next-work"><span>准备验证自己的设想？</span><button class="btn primary" data-action="nav" data-nav="test">自己设计一条测试 →</button><button class="text-link" data-action="nav" data-nav="mat:DEMO_M01">打开原始材料 ↗</button></div></aside></div>`;
  }

  function renderMsg(c, x) {
    if (x.type === 'q')
      return `<div class="msg me"><div class="bubble">${esc(x.text)}<div class="meta">你 · ${esc(x.ts)}</div></div></div>`;
    if (x.type === 'fault' || x.type === 'fault_done')
      return `<div class="sysfault"><b>连接中断</b><div>${esc(x.text)}<p>问题仍在记录中，可重新输入发送。</p></div></div>`;
    const old = c.questions.find((q) => q.id === x.qid),
      sources = x.sources || [old?.cite].filter(Boolean);
    const ev = {
      key: 'ans:' + x.id,
      kind: 'ans',
      colleague: c.id,
      qid: x.qid || 'free',
      ref: x.id,
      snapshot: { ...x, question: x.question || old?.text, colleague: c.id },
    };
    return `<div class="msg"><span class="avatar ${c.initials.toLowerCase()}">${c.initials}</span><div class="bubble">${esc(x.text)}<button class="reply-audio" data-action="reply-speak" data-cid="${c.id}" data-id="${x.id}">▷ 朗读 / 文字</button><div class="meta"><span class="src">${esc(c.name)} · ${esc(x.ts)} · 模拟回答${x.topic && TOPICS[x.topic] ? ' · 按「' + esc(TOPICS[x.topic]) + '」回应' : ''}</span>${x.uncovered ? '' : citeMenu(ev)}</div>${
      sources.length
        ? `<div class="reply-sources">${sources
            .map((pid) => {
              const m = D.MATERIALS.find((m) =>
                m.versions.some((v) => v.paras.some((p) => p.id === pid)),
              );
              const version = x.version || 'v1';
              const para = m?.versions
                .find((v) => v.v === version)
                ?.paras.find((p) => p.id === pid);
              return para
                ? `<button class="text-link" data-action="open-ev" data-ev='${esc(JSON.stringify({ kind: 'para', material: m.id, version, para: pid, snapshot: { text: para.text } }))}'>${pid} ${version} ↗</button>`
                : '';
            })
            .join('')}</div>`
        : x.fact
          ? '<small class="muted">来源：该角色在本场景中的陈述，未经独立验证。</small>'
          : ''
    }${x.refer ? `<button class="text-link" data-action="nav" data-nav="col:${x.refer}">向 ${esc(D.COLLEAGUES.find((c) => c.id === x.refer).name)} 追问 →</button>` : ''}</div></div>`;
  }

  function askFree(cid) {
    if (!canEdit()) return;
    const p = ensurePractice(),
      text = (p.messages[cid] || '').trim();
    if (!text) {
      toast('先写下你想问的问题。');
      $('#colleague-question')?.focus();
      return;
    }
    const th = (S.threads[cid] ||= []),
      reply = PracticeEngine.colleague(cid, text, th, S.world, S.variant, D);
    tick();
    th.push({ type: 'q', text, ts: clockLabel(), qid: 'free' });
    th.push({
      id: uid('DEMO_MSG'),
      type: 'a',
      qid: 'free',
      question: text,
      ts: clockLabel(),
      ...reply,
    });
    p.messages[cid] = '';
    persist();
    renderMain();
    $('#colleague-question')?.focus({ preventScroll: true });
    const thread = $('.thread');
    if (thread) thread.scrollTop = thread.scrollHeight;
  }
  function ask(cid, qid) {
    const c = D.COLLEAGUES.find((x) => x.id === cid);
    const q = c.questions.find((x) => x.id === qid);
    const th = (S.threads[cid] = S.threads[cid] || []);
    th.filter((x) => x.type === 'fault' && x.qid === qid).forEach((x) => (x.resolved = true));
    tick();
    th.push({ type: 'q', qid, text: q.text, ts: clockLabel() });
    if (q.timeoutOnce && !S.demo.bizTimeoutUsed) {
      S.demo.bizTimeoutUsed = true;
      th.push({
        type: 'fault',
        qid,
        text: 'Colleague service timed out after 20 s (request DEMO_REQ_7F3A). Your question was not lost.',
      });
    } else
      th.push({
        id: uid('DEMO_MSG'),
        type: 'a',
        qid,
        text:
          S.variant === 'DEMO_V2' && qid === 'q_mgr_who'
            ? q.answer +
              ' Sales has also asked to add 35 people. No extra capacity has been approved; address who waits.'
            : q.answer,
        ts: clockLabel(),
      });
    persist();
    renderNav();
    renderMain();
    const t = $('.thread');
    if (t) t.scrollTop = t.scrollHeight;
  }
  function renderTests() {
    const p = ensurePractice(),
      e = p.editor,
      cfg = S.config,
      last = S.tests.find((r) => r.id === p.focusRun) || S.tests.at(-1);
    return `<div class="lab-heading"><div><p class="kicker">被测试的应用 · Northwind Assistant · 模拟</p><h2>先写预期，再让结果说话。</h2></div><button class="btn" data-action="nav" data-nav="cfg">调整配置 v${cfg.version} ↗</button></div><div class="experiment-grid"><section class="test-author"><div class="author-heading"><h3>${e.id ? '修订测试' : '你来设计测试'}</h3><button class="text-link" data-action="voice-open" data-target="test" ${locked() ? 'disabled' : ''}>◉ 语音演示</button></div><label for="test-question">问题</label><textarea id="test-question" data-test-input="text" rows="2" maxlength="2000" ${locked() ? 'disabled' : ''} placeholder="你想用什么问题检验助手？">${esc(e.text)}</textarea><label for="test-expected">你预期它怎样回答？</label><textarea id="test-expected" data-test-input="expected" rows="2" maxlength="3000" ${locked() ? 'disabled' : ''} placeholder="写下预期行为，运行后比较">${esc(e.expected)}</textarea><label for="test-basis">预期的依据</label><textarea id="test-basis" data-test-input="basis" rows="2" maxlength="3000" ${locked() ? 'disabled' : ''} placeholder="依据哪条材料、对话，或什么假设？">${esc(e.basis)}</textarea><div class="test-actions"><button class="btn primary" data-action="test-save-run" ${locked() ? 'disabled' : ''}>保存并运行 ↗</button><button class="btn" data-action="test-save" ${locked() ? 'disabled' : ''}>仅保存</button>${e.id ? '<button class="text-link" data-action="test-new">另写一条</button>' : ''}</div><details class="question-help"><summary>查看有限模拟的覆盖范围</summary><p>年假、设备报销、密码、VPN、电脑更换、薪资和退款请求；一次一个主题，常见中英文问法，金额按 SGD。未建模条件保留为未覆盖，不虚构结果。</p></details><section class="test-library"><div class="author-heading"><h3>我的测试集 <small>${p.suite.length}</small></h3>${p.suite.length ? `<button class="text-link" data-action="suite-run" ${locked() ? 'disabled' : ''}>全部重跑</button>` : ''}</div>${p.suite.map((t) => `<div class="suite-row"><div><b>${esc(t.text)}</b><small>测试 v${t.version} · ${S.tests.filter((r) => r.testId === t.id).length} 次运行</small></div><div class="row"><button class="btn sm" data-action="test-edit" data-id="${t.id}" ${locked() ? 'disabled' : ''}>编辑</button><button class="btn sm" data-action="test-run" data-id="${t.id}" ${locked() ? 'disabled' : ''}>重跑</button></div></div>`).join('') || '<p class="muted">你的第一条测试会保存在这里。</p>'}</section></section><section class="experiment-result" id="runs"><div class="result-heading"><span class="live-dot"></span><b>运行现场</b><span>${S.tests.length} 次记录 · 配置 v${cfg.version}</span></div>${
      last
        ? `${renderDiff(last)}${renderRun(last)}<details class="run-history"><summary>全部运行记录 · ${S.tests.length} 次</summary>${S.tests
            .slice()
            .reverse()
            .map(
              (r) =>
                `<button data-action="focus-run" data-id="${r.id}"><b>${esc(r.id)}</b><span>v${r.configVersion} · ${esc(r.text)}</span></button>`,
            )
            .join('')}</details>`
        : '<div class="result-empty"><div class="assistant-mark">N</div><h3>等你的第一个问题。</h3><p>这里将显示助手回答、检索片段与版本。<br>然后由你写下诊断。</p><div class="result-sequence"><span>你的预期</span><i>→</i><span>实际回答</span><i>→</i><span>你的判断</span></div></div>'
    }<div class="result-next"><button class="btn" data-action="nav" data-nav="cfg">调整配置，再验证</button><button class="text-link" data-action="go" data-step="4">把证据写进试点决定 →</button></div></section></div>`;
  }

  function renderRun(r) {
    const p = ensurePractice(),
      diag = p.diagnoses[r.id] || { text: '', difference: '' };
    return `<article class="run authored-run" id="run-${r.id}"><div class="run-title"><span>${esc(r.id)} · 配置 v${r.configVersion}</span><span>${esc(r.ts)}</span></div><h3>${esc(r.text)}</h3>${r.expected ? `<div class="expected-note"><b>你在运行前的预期</b><p>${esc(r.expected)}</p><small>依据：${esc(r.basis)}</small></div>` : ''}${r.fault ? `<div class="sysfault"><b>运行中断</b><div>模拟服务超时，没有生成回答。问题和预期已保存；这条故障不代表助手表现。<button class="btn sm" data-action="practice-rerun" data-id="${r.id}">重试同一测试</button></div></div>` : `<div class="answer-by"><span class="assistant-mark">N</span>Northwind Assistant <small>${r.covered === false ? '此输入未覆盖' : '模拟输出' + (TOPICS[r.topic] ? ' · ' + TOPICS[r.topic] : '')}</small></div><div class="a">${esc(r.answer)}${r.notice ? `<div class="index-notice">${esc(r.notice)}</div>` : ''}</div><details class="run-evidence" open><summary>检查运行依据</summary><div class="run-facts"><span>配置 <b>v${r.configVersion}</b></span><span>索引快照 <b>${esc(r.indexSnapshot)}</b></span>${r.sourceNow ? `<span>源文档版本 <b>${esc(r.sourceNow)}</b></span>` : ''}</div>${r.passages?.length ? r.passages.map((p) => `<div class="passage"><span class="pid">${esc(p.pid)} · 索引 ${esc(p.version)}</span>${esc(p.text)}</div>`).join('') : '<p class="small muted">本次没有检索片段。</p>'}<details><summary>当时的配置</summary><p class="small">${esc(D.SCOPES.find((s) => s.id === r.cfg?.scope)?.label || '旧版记录')} · ${esc(D.FALLBACKS.find((f) => f.id === r.cfg?.fallback)?.label || '')} · 日期提示 ${r.cfg?.updateNotice ? '开启' : '关闭'}</p></details></details>`}<div class="run-diagnosis"><label for="diagnosis-${r.id}">你的诊断</label><textarea id="diagnosis-${r.id}" data-diagnosis="${r.id}" data-part="text" rows="2" maxlength="5000" ${locked() ? 'disabled' : ''} placeholder="实际结果与预期有什么差别？你的依据是什么？">${esc(diag.text)}</textarea>${S.tests.some((x) => x.id !== r.id && x.qid === r.qid && x.configVersion < r.configVersion) ? `<label for="difference-${r.id}">改动带来了什么？还有什么风险？</label><textarea id="difference-${r.id}" data-diagnosis="${r.id}" data-part="difference" rows="2" maxlength="5000" ${locked() ? 'disabled' : ''}>${esc(diag.difference)}</textarea>` : ''}</div><div class="composer-foot"><button class="btn sm" data-action="practice-rerun" data-id="${r.id}" ${locked() ? 'disabled' : ''}>用当前配置重测原问题</button>${citeMenu(testEvidence(r))}</div></article>`;
  }

  function renderDiff(focus) {
    const y = focus || S.tests.at(-1);
    if (!y) return '';
    const x = S.tests
      .filter(
        (r) =>
          r.qid === y.qid && !r.fault && r.covered !== false && r.configVersion < y.configVersion,
      )
      .at(-1);
    if (!x || y.fault || y.covered === false) return '';
    const changes = [
      x.cfg?.scope !== y.cfg?.scope ? '知识范围' : null,
      x.cfg?.fallback !== y.cfg?.fallback ? '兜底方式' : null,
      x.cfg?.updateNotice !== y.cfg?.updateNotice ? '日期提示' : null,
      x.cfg?.capacity !== y.cfg?.capacity ? '试点人数' : null,
    ].filter(Boolean);
    return `<section class="comparison"><div class="author-heading"><h3>同题 · 改动前后</h3><span>${changes.join('、') || '配置版本'}已变更</span></div><div class="diff">${[x, y].map((r, i) => `<div class="col"><h4>${i ? '本次' : '上次'} · v${r.configVersion} · ${esc(r.id)}</h4><p>${esc(r.answer)}</p><small>${r.passages?.map((p) => p.pid + ' ' + p.version).join(', ') || '无检索片段'} · 提示${r.notice ? '开启' : '关闭'}</small></div>`).join('')}</div><p class="observed-change">${x.answer === y.answer ? '观察：回答文字没有变化。' : '观察：回答内容已变化。'}${x.answerKind !== y.answerKind ? '响应路径也已改变。' : ''} 是否符合你的预期？</p></section>`;
  }

  function saveTest(andRun = false) {
    if (!canEdit()) return;
    const p = ensurePractice(),
      e = p.editor;
    if (!e.text.trim() || !e.expected.trim() || !e.basis.trim()) {
      toast('请写下问题、预期和依据，再保存测试。');
      return;
    }
    const old = p.suite.find((t) => t.id === e.id);
    const t = {
      id: old?.id || uid('TEST'),
      version: (old?.version || 0) + 1,
      text: e.text.trim(),
      expected: e.expected.trim(),
      basis: e.basis.trim(),
    };
    if (old) {
      t.history = [...(old.history || []), clone({ ...old, history: undefined })];
      p.suite[p.suite.indexOf(old)] = t;
    } else p.suite.push(t);
    p.editor = { text: '', expected: '', basis: '' };
    persist();
    if (andRun) runTest(t);
    else {
      renderMain();
      toast('测试已保存。');
    }
  }
  function executeTest(t) {
    tick();
    const id = 'DEMO_T' + S.attemptNo + '_R' + (S.tests.length + 1);
    const rec = {
      id,
      qid: t.id + ':v' + t.version,
      testId: t.id,
      testVersion: t.version,
      text: t.text,
      expected: t.expected,
      basis: t.basis,
      configVersion: S.config.version,
      cfg: clone(S.config),
      ts: clockLabel(),
      indexSnapshot: S.world.indexSnapshot,
    };
    if (S.demo.faultNextTest) {
      S.demo.faultNextTest = false;
      Object.assign(rec, { fault: true, passages: [], flags: [] });
    } else Object.assign(rec, PracticeEngine.run(t, S.config, S.world, D));
    S.tests.push(rec);
    ensurePractice().focusRun = rec.id;
    // A recorded world event occurs after the first completed supported test, not before its output.
    if (
      !S.variant &&
      !rec.fault &&
      rec.covered !== false &&
      !S.events.some((e) => e.id === 'DEMO_E1')
    )
      triggerEvent('DEMO_E1');
    return rec;
  }
  function runTest(t) {
    if (!canEdit() || !t) return;
    executeTest(t);
    persist();
    renderNav();
    renderMain();
    toast('运行已保存，查看本次结果与版本依据。');
    if (innerWidth <= 900) $('#runs')?.scrollIntoView({ block: 'start', behavior: 'instant' });
  }
  function rerunOriginal(id) {
    const r = S.tests.find((r) => r.id === id);
    if (!r) return;
    runTest({
      id: r.testId || r.qid,
      version: r.testVersion || 1,
      text: r.text,
      expected: r.expected || '',
      basis: r.basis || '',
    });
  }
  function processFeedback(att) {
    const w = att.snapshot,
      p = w.practice || {},
      diagnoses = p.diagnoses || {},
      runs = w.tests || [];
    return `<section class="process-feedback"><div class="author-heading"><h2>${att.revisedFrom ? (att.variant ? '变体修订记录' : '修订后的记录') : att.variant ? '独立变体记录' : '首次提交记录'}</h2><span>${(p.suite || []).length} 条自写测试 · ${runs.length} 次运行</span></div><p>以下只核对已保存的操作与来源。你的诊断和方案是否成立，仍需语义复核。</p>${p.revisionReason ? `<div class="expected-note"><b>你的修订理由</b><p>${esc(p.revisionReason)}</p></div>` : ''}${
      !runs.length
        ? '<p>没有运行证据，暂时无法核对你的试点判断。</p>'
        : runs
            .filter((r) => r.notice && r.stale && !r.fault)
            .map(
              (r) =>
                `<div class="evidence-feedback"><b>回看 ${esc(r.id)} 的日期提示</b><p>这次已显示索引日期，回答仍使用 ${esc(r.passages[0]?.pid)} ${esc(r.passages[0]?.version)}；当时源文档为 ${esc(r.sourceNow)}。它是否支持你在更新政策中的决定？</p><button class="btn sm" data-action="open-ev" data-ev='${esc(JSON.stringify(testEvidence(r)))}'>打开这次运行</button></div>`,
            )
            .join('')
    }${runs.filter((r) => !r.fault && r.covered !== false && !(diagnoses[r.id]?.text || '').trim()).length ? '<p class="note">有运行尚未写诊断。修订时说明实际结果、预期差异及依据。</p>' : ''}${runs.some((r) => r.covered === false) ? '<p class="note">包含模拟器未覆盖的输入：已保留为待真实服务验证，不能算作通过或失败。</p>' : ''}<details><summary>回看测试、诊断与修订证据</summary>${runs.map((r) => `<div class="process-row"><b>${esc(r.id)} · ${esc(r.text)}</b><p>预期：${esc(r.expected || '旧记录未写预期')}</p><p>诊断：${esc(diagnoses[r.id]?.text || '尚未填写')}</p>${diagnoses[r.id]?.difference ? `<p>改动解释：${esc(diagnoses[r.id].difference)}</p>` : ''}<button class="text-link" data-action="open-ev" data-ev='${esc(JSON.stringify(testEvidence(r)))}'>查看原始记录 ↗</button></div>`).join('')}</details><p class="small muted">${att.revisedFrom ? '这是看过反馈后的修订，不能据此认定已能独立迁移。' : att.variant ? '这是新局面中的自主表现，单独保存，不与看过反馈后的修订合并。' : '首次作品已冻结，后续修订不会覆盖。'}</p></section>`;
  }
  function run(qid) {
    const q = D.QUERIES.find((x) => x.id === qid);
    S.selectedQuery = qid;
    tick();
    if (S.demo.faultNextTest || (S.tests.length === 2 && !S.demo.faultUsed)) {
      S.demo.faultNextTest = false;
      S.demo.faultUsed = true;
      S.tests.push({
        id: 'DEMO_T' + S.attemptNo + '_R' + (S.tests.length + 1),
        qid,
        text: q.text,
        kind: q.kind,
        fault: true,
        reqId: 'DEMO_REQ_' + Math.random().toString(16).slice(2, 6).toUpperCase(),
        ts: clockLabel(),
        configVersion: S.config.version,
      });
      persist();
      renderNav();
      renderMain();
      return;
    }
    S.tests.push(runQuery(q));
    if (S.tests.filter((r) => !r.fault).length === 1 && !S.events.some((e) => e.id === 'DEMO_E1'))
      triggerEvent('DEMO_E1');
    persist();
    renderNav();
    renderMain();
    render();
    S.step === 3 && renderAll();
  }
  function renderAll() {
    render();
  }
  function renderConfig() {
    const d = S.cfgDraft || { ...S.config };
    const dirty =
      JSON.stringify({ ...d, version: 0, savedAt: 0 }) !==
      JSON.stringify({ ...S.config, version: 0, savedAt: 0 });
    return `<div class="panel-head"><div><p class="kicker">ASSISTANT BEHAVIOR</p><h2>定义助手怎样回答。</h2><p>这些是你在试点里可以改的设置。保存后形成新的配置版本；回到测试台重跑同一条查询，看行为是否改变。配置不会改变平台容量或开发资源。</p></div></div>
      <div class="lab-tabs"><button data-action="nav" data-nav="test">运行与诊断</button><span class="active">助手行为配置</span></div><div class="cfg">
        <div class="grp"><div class="lbl">Knowledge scope<span>Which sources the assistant may answer from</span></div><div class="seg">${D.SCOPES.map((s) => `<label><input type="radio" name="scope" value="${s.id}" ${d.scope === s.id ? 'checked' : ''}>${esc(s.label)}</label>`).join('')}</div></div>
        <div class="grp"><div class="lbl">Index-date notice<span>Show the index snapshot date on every reply (M02§4)</span></div><div><label class="switch"><input type="checkbox" class="raw" name="notice" value="on" ${d.updateNotice ? 'checked' : ''}><span class="track"></span><span>${d.updateNotice ? 'On' : 'Off (default)'}</span></label></div></div>
        <div class="grp"><div class="lbl">Fallback<span>What happens on out-of-scope or low-confidence questions</span></div><div class="seg">${D.FALLBACKS.map((f) => `<label><input type="radio" name="fallback" value="${f.id}" ${d.fallback === f.id ? 'checked' : ''}>${esc(f.label)}</label>`).join('')}</div></div>
        <div class="grp"><div class="lbl">Named users<span>Requested pilot size. The platform limit is not changed here.</span></div><div><input type="number" id="cap" aria-label="试点人数" min="1" max="500" value="${d.capacity}" style="width:120px">${!S.variant && d.capacity > 30 ? '<div class="field-err">Requested more than the 30-user platform limit (M03§1). You can save it, but the plan will be checked against the limit.</div>' : ''}</div></div>
        <div class="foot"><span class="ver">current: config v${S.config.version} · saved ${esc(S.config.savedAt)}${dirty ? ' · unsaved changes' : ''}</span><div class="row"><button class="btn" data-action="cfg-reset" ${dirty ? '' : 'disabled'}>放弃修改</button><button class="btn primary" data-action="cfg-save" ${dirty ? '' : 'disabled'}>保存为 v${S.config.version + 1}</button>${S.tests.length ? `<button class="btn primary" data-action="cfg-retest" ${dirty ? '' : 'disabled'}>保存并重测上一题 →</button>` : ''}</div></div>
      </div>
      ${S.configHistory.length ? `<h3 style="margin:18px 0 8px">配置历史</h3><table class="tbl"><tr><th>版本</th><th>范围</th><th>提醒</th><th>兜底</th><th>人数</th><th>保存于</th></tr>${[...S.configHistory, S.config].map((c) => `<tr><td class="mono">v${c.version}</td><td>${esc(D.SCOPES.find((s) => s.id === c.scope).label)}</td><td>${c.updateNotice ? 'on' : 'off'}</td><td>${esc(D.FALLBACKS.find((f) => f.id === c.fallback).label)}</td><td>${c.capacity}</td><td class="mono">${esc(c.savedAt)}</td></tr>`).join('')}</table>` : ''}`;
  }
  function readCfgDraft() {
    const g = (n) => document.querySelector(`input[name=${n}]:checked`)?.value;
    S.cfgDraft = {
      ...S.config,
      scope: g('scope'),
      updateNotice: !!document.querySelector('input[name=notice]')?.checked,
      fallback: g('fallback'),
      capacity: Number($('#cap').value || '0'),
    };
  }
  function renderPlan() {
    const body = $('#planbody');
    if (!body) return;
    const submitted = S.attempts.find((a) => a.attemptNo === S.attemptNo);
    body.innerHTML =
      (submitted
        ? `<div class="note">已提交快照 · 草稿已锁定。<button class="btn" data-action="revise" data-id="${submitted.id}">修订为新版本</button></div>`
        : '') +
      D.FIELDS.map((f) => {
        const p = S.plan[f.id];
        return `<div class="pf ${p.text ? '' : 'empty'}"><label for="pf_${f.id}">${esc(FIELD_NAMES[f.id] || f.label)}<small>${esc(f.label)}</small><span class="hint">${p.evidence.length ? p.evidence.length + ' 条依据' : ''}</span></label><textarea ${submitted ? 'disabled' : ''} id="pf_${f.id}" data-field="${f.id}" placeholder="${esc(f.hint)}">${esc(p.text)}</textarea><div class="chips">${p.evidence.map((e) => `<span class="chip ${e.kind} ${e.kind === 'para' && e.material === 'DEMO_M05' && e.version === 'v1' && S.world.m05 === 'v2' ? 'stale' : ''}" title="${esc(e.label || e.ref)}"><button class="chip-open" data-action="open-ev" data-ev='${esc(JSON.stringify(e))}'>${esc(evidenceLabel(e))}</button><button ${submitted ? 'disabled' : ''} class="x" data-action="chip-rm" data-field="${f.id}" data-key="${esc(e.key)}" aria-label="移除引用">×</button></span>`).join('')}</div></div>`;
      }).join('') +
      `<div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn primary sm" data-action="go" data-step="4">审阅并提交</button></div>`;
  }

  /* ---- 页 4 ---- */
  function validation() {
    const items = [];
    const empty = D.FIELDS.filter((f) => !S.plan[f.id].text.trim());
    items.push(
      empty.length
        ? {
            s: 'bad',
            t: `${empty.length} 个字段为空：${empty.map((f) => f.label).join('、')}。可以写“Unknown: …”并说明确认办法。`,
          }
        : { s: 'ok', t: '九个字段都有内容。' },
    );
    const cited = D.FIELDS.filter((f) => S.plan[f.id].evidence.length).length;
    items.push(
      cited
        ? { s: 'warn', t: `${cited} 个字段附了依据。引用是否支持决定，仍需对照原文判断。` }
        : { s: 'warn', t: '没有任何字段附依据。反馈将无法核对你的陈述。' },
    );
    const testCited = S.plan.tests.evidence.some((e) => e.kind === 'test');
    items.push(
      testCited
        ? { s: 'ok', t: 'Acceptance tests 引用了实际测试记录。' }
        : S.tests.length
          ? {
              s: 'warn',
              t: `已运行 ${S.tests.length} 次测试但方案未引用；请把对应记录引用到 Acceptance tests，才能核对方案中的测试陈述。`,
            }
          : { s: 'bad', t: '还没有运行过任何测试。' },
    );
    const unread = S.events.filter((e) => !e.acked);
    items.push(
      unread.length
        ? {
            s: 'bad',
            t: `${unread.length} 条局面变化尚未确认看过：${unread.map((e) => e.kind).join('、')}。提交前请确认。`,
          }
        : { s: 'ok', t: '已发生的变化都已确认看过。' },
    );
    const cap = Math.max(-1, ...nums(S.plan.capacity.text).filter((x) => x <= 500));
    if (!S.variant && cap > 30)
      items.push({
        s: 'warn',
        t: `文中出现 ${cap} 人；平台容量为 30。若这是有条件的后续安排，请保留批准条件，交由复核。`,
      });
    const staleChips = D.FIELDS.flatMap((f) =>
      S.plan[f.id].evidence.filter(
        (e) =>
          e.kind === 'para' &&
          e.material === 'DEMO_M05' &&
          e.version === 'v1' &&
          S.world.m05 === 'v2',
      ),
    );
    if (staleChips.length)
      items.push({
        s: 'warn',
        t: `${staleChips.length} 条引用指向 M05 v1，该材料已有 v2。引用仍会打开当时的版本；是否更新由你判断。`,
      });
    if (D.FIELDS.some((f) => /[\u3400-\u9fff]/.test(S.plan[f.id].text)))
      items.push({
        s: 'bad',
        t: '演示假设：正式提交仅支持英文；检测到中文，草稿已保留，未调用中文评分。',
      });
    return items;
  }
  function renderReview(v) {
    const items = validation();
    const blocking = submissionBlocks();
    const cur = S.attempts.find((a) => a.attemptNo === S.attemptNo) || null;
    const submittedThis = cur && cur.attemptNo === S.attemptNo;
    v.innerHTML = `<div class="page wide review-page">
      <p class="kicker">DECISION REVIEW / 练习 ${S.attemptNo}</p>
      <h1>把你的判断，交代清楚。</h1>
      <p class="lede">提交会生成不可修改的快照，包含九字段、依据、当时的配置版本和已发生的变化。业务上不合理的方案也可以提交并得到反馈。</p>
      <section class="process-review"><h3>随方案保存的过程作品</h3><p>${ensurePractice().suite.length} 条测试 · ${S.tests.length} 次运行 · ${Object.values(ensurePractice().diagnoses).filter((x) => x.text?.trim()).length} 条诊断 · 配置 v${S.config.version}</p>${S.revisedFrom ? `<label for="revision-reason">这次为什么修改？</label><textarea id="revision-reason" rows="3" ${submittedThis ? 'disabled' : ''} placeholder="哪些证据改变了你的判断？改了什么，仍有哪些限制？">${esc(ensurePractice().revisionReason)}</textarea>` : ''}</section><div class="review-grid" style="margin-top:16px">
        <section class="card">
          ${D.FIELDS.map((f) => {
            const p = S.plan[f.id];
            return `<div class="rv-field"><div class="lbl">${esc(f.label)}<span class="st muted">${p.evidence.length ? p.evidence.length + ' 条依据' : '无依据'}</span></div><div><textarea class="decision-input" aria-label="${esc(FIELD_NAMES[f.id])}" data-field="${f.id}" rows="3" ${submittedThis ? 'disabled' : ''} placeholder="${esc(f.hint)}">${esc(p.text)}</textarea><div class="chips">${p.evidence.map((e) => `<button class="chip ${e.kind}" data-action="open-ev" data-ev='${esc(JSON.stringify(e))}' title="打开当时的记录">${esc(evidenceLabel(e))}</button>`).join('')}</div></div></div>`;
          }).join('')}
        </section>
        <aside class="sticky stack">
          <section class="card"><h3>提交前检查</h3><ul class="checklist" id="review-checklist" style="margin-top:8px">${items.map((i) => `<li><span class="${i.s}">${i.s === 'ok' ? '✓' : i.s === 'bad' ? '✕' : '!'}</span><span>${esc(i.t)}</span></li>`).join('')}</ul></section>
          <section class="card"><h3>已发生的变化</h3>${S.events.length ? S.events.map((e) => `<div class="notif ${e.acked ? '' : 'unread'}" style="margin-top:8px"><b>${esc(e.title)}</b><div class="when">${esc(e.ts)} · ${esc(e.kind)}</div>${e.acked ? '<div class="small muted">已确认看过</div>' : `<button class="btn sm" style="margin-top:6px" data-action="ack" data-id="${e.id}">我已看过这条变化</button>`}</div>`).join('') : '<p class="muted small">没有变化。</p>'}</section>
          <section class="card">
            ${
              submittedThis
                ? `<p><b>已提交</b> · ${esc(cur.id)} · ${esc(cur.submittedAt)}</p><p class="small muted">重复点击不会再生成一份。</p><button class="btn primary" data-action="go" data-step="5">查看反馈</button>`
                : `<p class="small muted">提交后编辑不会覆盖这份快照；若要修改，会另存为新版本。</p><button class="btn primary" data-action="submit" ${blocking.length ? 'disabled' : ''} style="width:100%">提交这份试点方案</button>${blocking.length ? '<p class="field-err">请补齐必填内容（修订含理由）、使用本次支持语言并确认变化；草稿已保留。</p>' : ''}<button class="btn quiet" data-action="go" data-step="3" style="margin-top:6px">返回工作台修改</button>`
            }
          </section>
        </aside>
      </div></div>`;
  }
  function submissionBlocks() {
    const blocks = D.FIELDS.filter((f) => !S.plan[f.id].text.trim()).map((f) => f.id);
    if (D.FIELDS.some((f) => /[\u3400-\u9fff]/.test(S.plan[f.id].text))) blocks.push('language');
    if (S.events.some((e) => !e.acked)) blocks.push('events');
    if (S.revisedFrom && !ensurePractice().revisionReason.trim()) blocks.push('revision reason');
    return blocks;
  }
  function submit() {
    if (submissionBlocks().length) {
      toast('请先处理提交前检查；草稿已保留。', 'red');
      go(4);
      return;
    }
    const existing = S.attempts.find((a) => a.attemptNo === S.attemptNo);
    if (existing) {
      S.currentAttempt = existing.id;
      go(5);
      return;
    }
    tick();
    const att = {
      id: 'DEMO_A' + (S.attempts.length + 1),
      attemptNo: S.attemptNo,
      variant: S.variant,
      submittedAt: clockLabel(),
      scenarioVersion: S.scenario.version,
      configVersion: S.config.version,
      seenFeedback: S.seenFeedback || false,
      revisedFrom: S.revisedFrom || null,
      snapshot: JSON.parse(JSON.stringify({ ...workSnapshot() })),
      status: 'submitted',
      feedback: null,
    };
    S.attempts.push(att);
    S.currentAttempt = att.id;
    if (S.demo.failNextEval) {
      S.demo.failNextEval = false;
      att.status = 'eval_failed';
      toast('提交已保存。评价服务暂时失败，可以重试。', 'red');
    } else {
      att.feedback = evaluate(att);
      att.status = 'evaluated';
      toast('已提交 ' + att.id + '，反馈已生成（模拟）');
    }
    persist();
    go(5);
  }

  /* ---- 页 5 ---- */
  function renderFeedback(v) {
    const att = S.attempts.find((a) => a.id === S.currentAttempt) || S.attempts.at(-1);
    if (!att) {
      v.innerHTML = '<div class="page"><h1>还没有提交</h1></div>';
      return;
    }
    if (att.status === 'eval_failed') {
      v.innerHTML = `<div class="page"><h1>作品已保存，反馈暂未生成。</h1><p>模拟评价服务中断；提交、测试与配置快照均已保留。</p><button class="btn primary" data-action="retry-eval" data-id="${att.id}">重试反馈</button></div>`;
      return;
    }
    const w = att.snapshot,
      p = w.practice || {},
      runs = w.tests || [],
      diagnoses = p.diagnoses || {};
    const findings = operationFindings(w),
      src = S.attempts.find((a) => a.id === att.revisedFrom);
    const evButton = (r) =>
      `<button class="text-link" data-action="open-ev" data-ev='${esc(JSON.stringify({ kind: 'test', ref: r.id, attemptNo: att.attemptNo, snapshot: { ...r, diagnosis: diagnoses[r.id] || {} } }))}'>查看 ${esc(r.id)} 原始证据 ↗</button>`;
    v.innerHTML = `<div class="page wide feedback-page"><div class="feedback-mast"><div><p class="kicker">证据反馈 · 有限规则核对 · ${att.id}</p><h1>${src ? '看看这次修订改变了什么。' : '让这次运行，推动下一次判断。'}</h1><p>反馈只针对已保存操作和版本事实，不冒充真实模型评分。</p></div><button class="btn primary" data-action="revise" data-id="${att.id}">保留这份，开始修订 →</button></div><div class="feedback-stats"><span><b>${(p.suite || []).length}</b> 自写测试</span><span><b>${runs.length}</b> 次运行</span><span><b>v${w.config.version}</b> 最终配置</span><span><b>${Object.values(diagnoses).filter((x) => x.text?.trim()).length}</b> 条自主诊断</span></div>${src ? `<section class="revision-summary"><p class="eyebrow">修订记录 · 不代表独立迁移</p><h2>${src.id} → ${att.id}</h2><p>配置 v${src.snapshot.config.version} → v${w.config.version}；新增 ${Math.max(0, runs.length - (src.snapshot.tests || []).length)} 次运行。</p><blockquote>${esc(p.revisionReason || '未记录修订理由')}</blockquote></section>` : ''}<div class="feedback-findings">${findings.map((f, i) => `<article class="feedback-finding ${f.kind}"><div class="finding-index">${String(i + 1).padStart(2, '0')}</div><div><p class="eyebrow">${f.kind === 'observed' ? '已记录的变化' : f.kind === 'gap' ? '尚缺的证据' : '需要你重新判断'}</p><h2>${esc(f.title)}</h2><p>${esc(f.fact)}</p>${f.r ? `<div class="feedback-proof"><div><small>你运行前写的预期</small><p>${esc(f.r.expected || '旧记录未填写')}</p></div><div><small>实际输出 · ${f.r.id} · v${f.r.configVersion}</small><p>${esc(f.r.answer || '未生成回答')}</p></div></div>${diagnoses[f.r.id]?.text ? `<blockquote><small>你写的诊断</small><p>${esc(diagnoses[f.r.id].text)}</p></blockquote>` : ''}${f.field ? `<details><summary>与你的「${FIELD_NAMES[f.field]}」一起看</summary><blockquote>${esc(w.plan[f.field].text || '未填写')}</blockquote></details>` : ''}${evButton(f.r)}` : ''}<p class="finding-question">${esc(f.question)}</p></div></article>`).join('')}</div><section class="feedback-scope"><h3>九字段作品已冻结，逐项对照来源</h3><p>上面的反馈核对操作事实；下面保留你的完整原话与引用。自由陈述的语义正确性尚未由真实模型或人工评定。</p>${D.FIELDS.map((f) => `<details><summary>${FIELD_NAMES[f.id]} <small>${w.plan[f.id].evidence.length} 条依据</small></summary><p>${esc(w.plan[f.id].text)}</p><div class="chips">${w.plan[f.id].evidence.map((e) => `<button class="chip" data-action="open-ev" data-ev='${esc(JSON.stringify(e))}'>${esc(evidenceLabel(e))}</button>`).join('')}</div>${att.feedback?.[f.id]?.rule.ok === false ? `<p class="field-err">${esc(att.feedback[f.id].rule.text)}</p>` : ''}</details>`).join('')}</section><div class="feedback-finish"><div><p class="eyebrow">${src ? '下一段练习' : '同一任务，再做一次'}</p><h2>${src ? '换一种局面，独立判断。' : '修改配置、重测，再修订决定。'}</h2><p>${src ? '新变体单独记录，不把看过反馈后的进步当成迁移成功。' : '修订会复制本次作品，保留测试、引用与运行，不覆盖这份提交。'}</p></div><div class="row">${src ? D.SCENARIO.variants.map((x) => `<button class="btn" data-action="variant" data-id="${x.id}">${x.id === 'DEMO_V1' ? '政策更新' : '人群扩大'} · 独立变体 →</button>`).join('') : `<button class="btn primary" data-action="revise" data-id="${att.id}">开始修订 →</button>`}</div></div></div>`;
  }
  function operationFindings(w) {
    const runs = w.tests || [],
      p = w.practice || {},
      d = p.diagnoses || {},
      out = [];
    const latest = Object.values(
      runs.reduce((a, r) => {
        a[r.qid] = r;
        return a;
      }, {}),
    );
    for (const r of latest) {
      if (r.fault) {
        out.push({
          kind: 'gap',
          title: '这条运行中断，不能当作助手答错',
          fact: `${r.id} 保存了平台故障，没有生成回答。`,
          r,
          field: 'tests',
          question: '保留故障记录，用同题重试后再作判断。',
        });
        continue;
      }
      if (r.covered === false) {
        out.push({
          kind: 'gap',
          title: '这个问题超出模拟器覆盖范围',
          fact: `${r.id} 没有可验证的回答，不计为通过或失败。`,
          r,
          field: 'tests',
          question: '是否需要补一条可执行测试？未覆盖条件应怎样留在试点限制中？',
        });
        continue;
      }
      const prev = runs
        .filter(
          (x) =>
            x.qid === r.qid && x.configVersion < r.configVersion && !x.fault && x.covered !== false,
        )
        .at(-1);
      if (prev && !r.stale)
        out.push({
          kind: 'observed',
          title: prev.answer === r.answer ? '配置变了，回答没有变' : '同题重测的响应已改变',
          fact: `${prev.id} / v${prev.configVersion} → ${r.id} / v${r.configVersion}。${prev.answerKind !== r.answerKind ? '响应路径：' + routeName(prev.answerKind) + ' → ' + routeName(r.answerKind) + '。' : '响应路径仍为' + routeName(r.answerKind) + '。'}${prev.notice !== r.notice ? '日期提示也有变化。' : ''}`,
          r,
          field: r.answerKind === 'handoff' ? 'fallback' : 'update',
          question: '对照你自己的预期：改变解决了什么，又留下什么代价？',
        });
      if (r.stale)
        out.push({
          kind: 'challenge',
          title: r.notice ? '日期提示出现了，检索仍是旧版' : '这次回答引用的版本与源文档不同',
          fact: `${prev ? '同题由 v' + prev.configVersion + ' 重测到 v' + r.configVersion + '。' : ''}${r.id} 检索 ${r.passages?.[0]?.version}，运行时源文档为 ${r.sourceNow}。${r.notice ? '开启提示没有重建索引。' : ''}`,
          r,
          field: 'update',
          question: '这条证据是否足以支持你写的更新政策？你会如何处理这类问题？',
        });
      if (r.answerKind === 'guess')
        out.push({
          kind: 'challenge',
          title: '没有检索依据，助手仍给出了答复',
          fact: `${r.id} 使用“继续回答”兜底，没有引用知识片段。`,
          r,
          field: 'fallback',
          question: '这种回答可以进入试点吗？用配置改动与新运行验证你的选择。',
        });
      if (!(d[r.id]?.text || '').trim())
        out.push({
          kind: 'gap',
          title: '这条结果还缺少你的解释',
          fact: `${r.id} 已保存预期和实际输出，但没有自主诊断。`,
          r,
          field: 'tests',
          question: '哪里符合预期，哪里不同？引用哪个版本，才能说明你的判断？',
        });
      else if (!r.stale && !prev && r.answerKind !== 'guess')
        out.push({
          kind: 'observed',
          title: '预期、输出和你的诊断已连在一起',
          fact: `${r.id} 已记录${routeName(r.answerKind)}与自主诊断；记录完整不等于判断正确。`,
          r,
          field: 'tests',
          question: '还能设计一个不同问法或边界条件，检验这个判断吗？',
        });
    }
    if (!runs.length)
      out.push({
        kind: 'gap',
        title: '决定尚没有运行证据',
        fact: '这份提交没有记录助手运行。',
        question: '自行设计问题、预期与依据，运行后再判断试点是否可用。',
      });
    const cited = (w.plan.tests?.evidence || []).filter((x) => x.kind === 'test').length;
    if (runs.length && !cited)
      out.push({
        kind: 'gap',
        title: '运行已保存，还没有进入验收依据',
        fact: `本次有 ${runs.length} 次运行，验收测试字段没有引用任何运行。`,
        question: '选取与你的决定相关的记录引用到字段，解释它为什么支持该决定。',
      });
    if (
      cited &&
      latest.some(
        (r) =>
          !r.fault &&
          r.covered !== false &&
          !(w.plan.tests.evidence || []).some((e) => e.kind === 'test' && e.ref === r.id),
      )
    )
      out.push({
        kind: 'gap',
        title: '部分最新运行尚未引用到验收测试',
        fact: '过程记录已经保存；验收字段仍有未关联的最新运行。',
        question: '检查方案里提到的结果是否指向正确运行与配置版本，再决定需要补充哪些引用。',
      });
    if (w.config.capacity > 30)
      out.push({
        kind: 'challenge',
        title: '配置请求超过现有平台容量',
        fact: `最终配置请求 ${w.config.capacity} 人；本场景登记容量仍为 30 人，保存配置不会扩容。`,
        question: '区分现在开放的人数与获批后的安排，并说明资源不到位时怎样处理。',
      });
    return out;
  }
  function routeName(k) {
    return (
      {
        answer: '按检索片段回答',
        handoff: '人工转介',
        refuse: '拒绝回答',
        guess: '无依据继续回答',
        uncovered: '未覆盖',
      }[k] || '已记录响应'
    );
  }
  function renderDrill(f, r) {
    const drills = {
      capacity: {
        q: 'Daniel 的运维说明写着 30 人上限，且本周不可能扩容。下面哪种写法与事实一致？',
        opts: [
          { t: '“Pilot: 80 users on the Ops floor.”', ok: false, why: '超过上限且没有条件。' },
          {
            t: '“Wave 1: 30 users; wave 2 conditional on cost approval for a larger instance.”',
            ok: true,
            why: '无条件部分不超过 30，超出部分写清条件。',
          },
          {
            t: '“Capacity: to be decided by engineering.”',
            ok: false,
            why: '把已知事实写成未知。',
          },
        ],
      },
      work: {
        q: '本周只有 3 人天。下面哪种工作项写法能被证据支持？',
        opts: [
          { t: '“Build real-time sync (5 days).”', ok: false, why: '超出可用工时且无条件。' },
          {
            t: '“Scope + notice + hand-off (under 1 day). Real-time sync only if leadership approves 2 extra days.”',
            ok: true,
            why: '可用工时内的动作明确，超出部分有条件。',
          },
          { t: '“Ask Daniel to find time.”', ok: false, why: '没有动作、工时或条件。' },
        ],
      },
      tests: {
        q: '哪种验收测试写法能让读者核对？',
        opts: [
          { t: '“Tests passed.”', ok: false, why: '没有查询、没有记录。' },
          {
            t: '“Ran DEMO_R2 (changed policy) under cfg v2: excluded and handed off; DEMO_R3 (out of scope): handed off.”',
            ok: true,
            why: '引用记录，说明覆盖的风险。',
          },
          { t: '“Will test before launch.”', ok: false, why: '承诺不是证据。' },
        ],
      },
      fallback: {
        q: 'Mei 说“不要让它猜”。哪种兜底与此一致？',
        opts: [
          { t: 'Answer anyway with a disclaimer.', ok: false, why: '仍然在猜。' },
          {
            t: 'Hand off to the HR shared mailbox with the original question.',
            ok: true,
            why: '有去处，有人答。',
          },
          { t: 'Log the question and do nothing.', ok: false, why: '用户得不到回答。' },
        ],
      },
      update: {
        q: '索引每晚重建，最长滞后 24 小时。哪种更新政策讲清了这一点？',
        opts: [
          { t: '“Content is always up to date.”', ok: false, why: '与事实矛盾。' },
          {
            t: '“Nightly index; each reply shows the snapshot date; changed chapters excluded for 24 h.”',
            ok: true,
            why: '说明机制、披露方式和处理。',
          },
          { t: '“HR will update as needed.”', ok: false, why: '没有说明滞后如何被看见。' },
        ],
      },
    };
    const d = drills[f.id] || {
      q: `围绕「${f.label}」：哪种写法能被你看到的材料支持？`,
      opts: [
        { t: '写具体、可观察的内容并引用来源。', ok: true, why: '可核对。' },
        { t: '写笼统的目标。', ok: false, why: '无法核对。' },
        { t: '留空。', ok: false, why: '未回答。' },
      ],
    };
    const st = S.drill && S.drill.field === f.id ? S.drill : null;
    return `<div class="drill"><p class="muted small" style="margin:0 0 4px">短补练 · 只针对已判定的最弱项 · ${esc(f.label)} <span class="pill mono">demo rule</span></p><h3 style="margin-bottom:10px">${esc(d.q)}</h3>${d.opts.map((o, i) => `<button class="opt ${st ? (o.ok ? 'right' : st.pick === i ? 'wrong' : '') : ''}" data-action="drill" data-field="${f.id}" data-i="${i}" ${st ? 'disabled' : ''}>${esc(o.t)}${st ? `<div class="small muted">${esc(o.why)}</div>` : ''}</button>`).join('')}${st ? `<p class="small muted" style="margin-top:6px">补练完成。这只说明你理解了这一项的依据，不代表岗位能力提升。</p>` : ''}</div>`;
  }

  /* ---- 页 6 ---- */
  function renderTasks(v) {
    v.innerHTML = `<div class="page archive-page">
      <p class="kicker">YOUR WORK / 练习档案</p><h1>你的练习记录</h1><p class="lede">这台浏览器里的草稿与提交快照。旧尝试保持原样；修订另存一份，清理站点数据会丢失记录。</p>
      <section style="margin-top:16px">
        <div class="attempt"><div><div class="t">attempt ${S.attemptNo} · ${esc(D.SCENARIO.title)}${S.variant ? ' · ' + esc(D.SCENARIO.variants.find((x) => x.id === S.variant).title) : ''}</div><div class="m">${esc(S.scenario.version || '未确认场景')} · ${S.attempts.some((a) => a.attemptNo === S.attemptNo) ? '已提交' : '进行中'} · ${S.tests.length} tests · ${
          Object.values(S.threads)
            .flat()
            .filter((x) => x.type === 'a').length
        } answers · config v${S.config.version}</div></div><div class="row">${S.scenario.confirmed ? `<button class="btn primary" data-action="go" data-step="3">${S.attempts.some((a) => a.attemptNo === S.attemptNo) ? '回看工作台' : '继续'}</button>` : `<button class="btn primary" data-action="go" data-step="1">开始</button>`}</div></div>
        ${Object.values(S.drafts)
          .filter(
            (d) =>
              d.attemptNo !== S.attemptNo && !S.attempts.some((a) => a.attemptNo === d.attemptNo),
          )
          .reverse()
          .map(
            (d) =>
              `<div class="attempt"><div><div class="t">attempt ${d.attemptNo} · 已保存草稿 ${d.variant ? esc(d.variant) : ''}</div><div class="m">${D.FIELDS.filter((f) => d.plan[f.id].text.trim()).length}/9 字段 · config v${d.config.version}</div></div><button class="btn" data-action="resume-draft" data-no="${d.attemptNo}">恢复这份草稿</button></div>`,
          )
          .join('')}
        ${S.attempts
          .slice()
          .reverse()
          .map(
            (a) =>
              `<div class="attempt"><div><div class="t">${esc(a.id)} · attempt ${a.attemptNo}${a.variant ? ' · ' + esc(D.SCENARIO.variants.find((x) => x.id === a.variant).title) : ''}${a.seenFeedback ? ' · 修订版，已看过反馈' : ''}</div><div class="m">submitted ${esc(a.submittedAt)} · ${a.status === 'evaluated' ? '已生成操作证据反馈 · 未作语义评分' : a.status === 'eval_failed' ? '评价失败，可重试' : '已提交'} · cfg v${a.configVersion}${a.revisedFrom ? ' · revised from ' + esc(a.revisedFrom) : ''}</div></div><div class="row"><button class="btn" data-action="open-attempt" data-id="${a.id}">看快照与反馈</button></div></div>`,
          )
          .join('')}
      </section>
      <section class="card" style="margin-top:20px"><h3>重新开始</h3><p class="small muted">开始一次新的尝试会保留所有旧尝试；工作台内容会清空。</p><button class="btn" data-action="restart">开始新的尝试</button> <button class="btn danger" data-action="reset-all" style="margin-left:8px">清除本浏览器的全部演示状态</button></section>
    </div>`;
  }

  /* ---- 通知抽屉与模态 ---- */
  function renderNotif() {
    let d = $('#drawer');
    if (d) d.remove();
    if (!S.notifOpen) return;
    d = document.createElement('div');
    d.id = 'drawer';
    d.className = 'drawer';
    d.innerHTML = `<div class="row" style="justify-content:space-between"><h3>通知</h3><button class="btn sm" data-action="notif">关闭</button></div>
      ${
        S.events.length
          ? S.events
              .slice()
              .reverse()
              .map(
                (e) =>
                  `<div class="notif ${e.read ? '' : 'unread'}"><b>${esc(e.title)}</b><div class="when">${esc(e.ts)} · ${esc(e.kind)}</div><p class="small" style="margin:6px 0">${esc(e.body)}</p>${e.id === 'DEMO_E1' ? `<button class="btn sm" data-action="nav-go" data-nav="mat:DEMO_M05">查看 M05 v2</button> ` : ''}${e.acked ? '<span class="small muted">已确认看过</span>' : `<button class="btn sm" data-action="ack" data-id="${e.id}">我已看过</button>`}</div>`,
              )
              .join('')
          : '<p class="muted small">还没有通知。局面变化会出现在这里，也会在审阅前要求你确认。</p>'
      }
      <p class="small muted" style="margin-top:12px">通知只告诉你发生了什么，不指出受影响的字段，也不给答案。</p>`;
    document.body.appendChild(d);
    d.querySelector('button')?.focus();
    S.events.forEach((e) => (e.read = true));
    persist();
    const b = $('[data-action=notif] .badge');
    if (b) b.remove();
  }
  function openEvidence(e) {
    let html = '';
    const active =
      S.step === 5 ? S.attempts.find((a) => a.id === S.currentAttempt)?.snapshot : null;
    if (e.kind === 'para') {
      const m = D.MATERIALS.find((x) => x.id === e.material),
        v = m?.versions.find((x) => x.v === e.version),
        p = v?.paras.find((x) => x.id === e.para);
      html = `<p class="mono muted">${esc(e.para)} · ${esc(e.version)} · ${esc(e.snapshot?.date || v?.date)}</p><p>${esc(e.snapshot?.text || p?.text || '原始记录不可用')}</p>`;
    } else if (e.kind === 'ans') {
      const candidates = (active?.threads || S.threads)[e.colleague] || [];
      const msg = e.snapshot || candidates.find((x) => x.id === e.ref && x.type === 'a');
      html = msg
        ? `<p class="mono">${esc(e.colleague)} · ${esc(msg.id || e.ref)} · ${esc(msg.ts)}</p><p><b>问题：</b>${esc(msg.question || D.COLLEAGUES.find((c) => c.id === e.colleague)?.questions.find((q) => q.id === e.qid)?.text)}</p><p><b>当时的回答：</b>${esc(msg.text)}</p><p class="note">引用只保存该条回答，不代表已验证支持你的方案。</p>`
        : '<p class="note amber">旧引用缺少唯一消息快照，无法可靠定位。请重新引用实际回答；不以模板答案代替。</p>';
    } else {
      const r = e.snapshot || (active?.tests || S.tests).find((x) => x.id === e.ref);
      html = r
        ? `<p class="mono">${esc(r.id)} · ${esc(r.ts)} · cfg v${r.configVersion} · ${esc(r.indexSnapshot || '')}</p><p><b>Query：</b>${esc(r.text)}</p>${r.fault ? '<p class="note amber">平台故障：没有可评价回答。</p>' : `<p>${esc(r.answer)}</p>${r.notice ? `<p class="note">${esc(r.notice)}</p>` : ''}${r.sourceNow ? `<p>运行时源文档：${esc(r.sourceNow)}</p>` : ''}${r.expected ? `<p>运行前预期：${esc(r.expected)}</p><p>预期依据：${esc(r.basis)}</p>` : ''}${r.diagnosis?.text ? `<p>引用时的诊断：${esc(r.diagnosis.text)}</p>` : ''}${(r.flags || []).map((t) => `<p class="note ${r.stale ? 'amber' : 'red'}">${esc(t)}</p>`).join('')}${(r.passages || []).map((p) => `<p class="passage">${esc(p.pid)} ${esc(p.version)} · ${esc(p.text)}</p>`).join('')}`}`
        : '<p>原始记录不可用，不能视为有效证据。</p>';
    }
    showModal('引用的原始记录', html);
  }

  function openAttempt(id) {
    const a = S.attempts.find((x) => x.id === id);
    if (!a) return;
    archiveDraft();
    restoreWork(a.snapshot);
    S.currentAttempt = id;
    persist();
    go(5);
  }

  let voiceContext = null,
    voiceTimer = null,
    activeUtterance = null;
  function openVoice(target, cid) {
    const pr = ensurePractice();
    voiceContext = { target, cid, ready: false };
    const text = target === 'chat' ? pr.messages[cid] || '' : pr.editor.text || '';
    showModal(
      '语音演示 · 不启用麦克风',
      `<div class="voice-demo"><div class="voice-orb" aria-hidden="true">◉</div><h2>用你的话，体验一次语音往返。</h2><p>本轮用你输入的文字演示“转写 → 确认 → 发送”。没有录音、语音识别或音频上传。</p><label for="voice-transcript">你想说的话 / 可编辑转写</label><textarea id="voice-transcript" rows="3" placeholder="写下你自己的问题，不会替你生成问题。">${esc(text || pr.voiceDraft || '')}</textarea><div id="voice-status" role="status">演示模式 · 麦克风未开启</div><div class="voice-actions"><button class="btn" data-action="voice-preview">演示转写过程</button><button class="btn primary" data-action="voice-send" disabled>${target === 'chat' ? '确认转写并发送' : '确认转写，填入测试问题'}</button></div><button class="text-link" data-action="close-modal">继续用文字输入 →</button></div>`,
      'voice-modal',
    );
  }
  function speakReply(cid, id) {
    const r = (S.threads[cid] || []).find((x) => x.id === id);
    if (!r) return;
    const synth = window.speechSynthesis,
      voice = synth
        ?.getVoices()
        .find(
          (v) => v.localService && v.lang.startsWith(/[\u3400-\u9fff]/.test(r.text) ? 'zh' : 'en'),
        );
    showModal(
      '同事回复 · 朗读与文字',
      `<div class="voice-demo"><div class="voice-orb" aria-hidden="true">▷</div><h2>${voice ? '正在准备本机朗读' : '本机语音暂不可用'}</h2><p>${voice ? '朗读这段已生成的模拟回复；未调用麦克风。' : '已降级为文字回复。没有启动录音或外部语音服务。'}</p><blockquote>${esc(r.text)}</blockquote><button class="btn primary" data-action="close-modal">${voice ? '停止朗读，继续对话' : '返回文字对话'}</button>${voice ? '<button class="text-link" data-action="voice-text">改用文字回复</button>' : ''}</div>`,
      'voice-modal',
    );
    if (voice) {
      const u = new SpeechSynthesisUtterance(r.text);
      u.voice = voice;
      u.lang = voice.lang;
      u.onstart = () => {
        const h = $('.voice-demo h2');
        if (h) h.textContent = '正在使用本机语音朗读';
      };
      u.onend = () => {
        const h = $('.voice-demo h2');
        if (h) h.textContent = '朗读已结束，继续你的调查';
      };
      u.onerror = (e) => {
        if (['canceled', 'interrupted'].includes(e.error)) return;
        const h = $('.voice-demo h2');
        if (h) h.textContent = '朗读不可用，请阅读下方回复';
      };
      synth.cancel();
      activeUtterance = u;
      synth.speak(u);
    }
  }
  /* ---------------- 事件委托 ---------------- */
  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-action]');
    if (!ev.target.closest('.cite-menu'))
      document.querySelectorAll('.cite-pop').forEach((p) => (p.hidden = true));
    if (!b) return;
    const a = b.dataset.action;
    if (a !== 'enter-pm') finishEntry();
    if (a === 'voice-open') {
      if (canEdit()) openVoice(b.dataset.target, b.dataset.cid);
      return;
    }
    if (a === 'voice-text') {
      if (activeUtterance) activeUtterance.onerror = null;
      window.speechSynthesis?.cancel();
      $('.voice-demo h2').textContent = '已切换为文字回复';
      $('.voice-demo>p').textContent = '朗读已停止。可以继续阅读原回复，文字对话不受影响。';
      b.remove();
      return;
    }
    if (a === 'reply-speak') {
      speakReply(b.dataset.cid, b.dataset.id);
      return;
    }
    if (a === 'voice-preview') {
      const t = $('#voice-transcript').value.trim();
      if (!t) {
        toast('先写下你想说的话。');
        return;
      }
      ensurePractice().voiceDraft = t;
      persist();
      $('#voice-status').textContent = '正在演示转写…（文字输入，无录音）';
      $('.voice-orb').classList.add('active');
      b.disabled = true;
      voiceTimer = setTimeout(() => {
        if (!$('#voice-status')) return;
        voiceContext.ready = true;
        $('#voice-status').textContent = '演示转写已就绪。请检查并确认自己的问题。';
        $('.voice-orb').classList.remove('active');
        $('[data-action=voice-send]').disabled = false;
        b.disabled = false;
      }, 650);
      return;
    }
    if (a === 'voice-send') {
      if (!voiceContext?.ready || !canEdit()) return;
      const t = $('#voice-transcript').value.trim();
      if (!t) {
        toast('转写不能为空。');
        return;
      }
      const ctx = voiceContext;
      const pr = ensurePractice();
      pr.voiceDraft = t;
      closeModal();
      if (ctx.target === 'chat') {
        pr.messages[ctx.cid] = t;
        askFree(ctx.cid);
      } else {
        pr.editor.text = t;
        persist();
        renderMain();
        $('#test-expected')?.focus();
      }
      return;
    }
    if (a === 'focus-run') {
      ensurePractice().focusRun = b.dataset.id;
      persist();
      renderMain();
      return;
    }
    if (a === 'cfg-retest') {
      if (!canEdit()) return;
      readCfgDraft();
      if (
        !Number.isInteger(S.cfgDraft.capacity) ||
        S.cfgDraft.capacity < 1 ||
        S.cfgDraft.capacity > 500
      ) {
        toast('人数需为 1–500 的整数');
        return;
      }
      const last = S.tests.at(-1);
      S.configHistory.push({ ...S.config });
      tick();
      S.config = { ...S.cfgDraft, version: S.config.version + 1, savedAt: clockLabel() };
      S.cfgDraft = null;
      S.wb.nav = 'test';
      persist();
      writeRoute();
      render();
      if (last) rerunOriginal(last.id);
      return;
    }
    const editActions = [
      'ask-free',
      'question-hint',
      'test-save',
      'test-save-run',
      'test-new',
      'test-edit',
      'test-run',
      'suite-run',
      'practice-rerun',
      'cfg-save',
      'cfg-retest',
      'cfg-reset',
      'voice-open',
      'voice-send',
      'ask',
      'run',
      'rerun',
      'demo-rebuild',
    ];
    if (editActions.includes(a) && !canEdit()) return;
    if (a === 'ask-free') {
      askFree(b.dataset.cid);
      return;
    }
    if (a === 'question-hint') {
      ensurePractice().messages[b.dataset.cid] = b.dataset.text;
      persist();
      renderMain();
      $('#colleague-question').focus();
      return;
    }
    if (a === 'test-save' || a === 'test-save-run') {
      saveTest(a === 'test-save-run');
      return;
    }
    if (a === 'test-new') {
      ensurePractice().editor = { text: '', expected: '', basis: '' };
      persist();
      renderMain();
      return;
    }
    if (a === 'test-edit') {
      ensurePractice().editor = clone(ensurePractice().suite.find((t) => t.id === b.dataset.id));
      persist();
      renderMain();
      $('#test-question').focus();
      return;
    }
    if (a === 'test-run') {
      runTest(ensurePractice().suite.find((t) => t.id === b.dataset.id));
      return;
    }
    if (a === 'practice-rerun') {
      rerunOriginal(b.dataset.id);
      return;
    }
    if (a === 'suite-run') {
      ensurePractice().suite.forEach(executeTest);
      persist();
      renderNav();
      renderMain();
      toast('测试集运行已保存。');
      return;
    }
    if (a.startsWith('demo-')) $('.demo-panel details').open = false;
    if (a === 'finding') {
      ev.preventDefault();
      document.getElementById('finding-' + b.dataset.field)?.scrollIntoView({
        behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
        block: 'start',
      });
    } else if (a === 'project-menu') {
      showModal(
        '项目导航',
        `<div class="project-menu-items"><details><summary>原始材料 · 6 份</summary>${D.MATERIALS.map((m, i) => `<button class="btn" data-action="nav" data-nav="mat:${m.id}">${MATERIAL_NAMES[i]}</button>`).join('')}</details>${[
          [2, '项目委托'],
          [3, '调查工作区'],
          [4, '交付审阅'],
          [5, '反馈与复盘'],
          [6, '练习档案'],
          [1, '练习情境'],
          [0, '职业大厅'],
        ]
          .map(
            ([n, t]) =>
              `<button class="btn" data-action="go" data-step="${n}" ${stepEnabled(n) ? '' : 'disabled'}>${t}</button>`,
          )
          .join('')}</div>`,
      );
    } else if (a === 'practice-info') {
      showModal(
        '练习说明与模拟边界',
        '<p>你扮演 AI 产品经理，调查限制、验证知识助手，再提交带证据的九字段试点方案。</p><p>同事负责提供局部信息；知识助手是被配置和测试的对象；反馈层负责核对规则与证据，不能混为一个全知 AI。</p><p>同事回答、检索和反馈均为前端模拟，未接入真实服务；材料未审核 D2。英文提交、背景保存及修订规则都是可逆演示假设。未安排真实评阅人，不承诺复核时限。</p><p>本浏览器自动保存，清理站点数据会丢失进度；工程师和面试仍后置。</p>',
      );
    } else if (a === 'enter-pm') enterPM(b.dataset.intake === 'true', ev.detail === 0);
    else if (a === 'resume-draft') resumeDraft(+b.dataset.no);
    else if (a === 'toggle-plan') {
      const y = $('#wbmain')?.scrollTop || 0;
      S.wb.planHidden = !S.wb.planHidden;
      persist();
      render();
      $('#wbmain').scrollTop = y;
      if (!S.wb.planHidden && innerWidth <= 600) {
        $('.wb-plan').scrollIntoView({ block: 'start' });
        $('#planbody textarea:not([disabled])')?.focus({ preventScroll: true });
      }
    } else if (a === 'go') go(+b.dataset.step);
    else if (a === 'role') {
      S.scenario.role = b.dataset.role;
      persist();
      render();
    } else if (a === 'example') {
      const e = D.INTAKE_EXAMPLES.find((x) => x.id === b.dataset.id);
      S.scenario.desc = e.text;
      S.scenario.match = null;
      persist();
      render();
      $('#desc').focus();
    } else if (a === 'match') doMatch();
    else if (a === 'clear-match') {
      S.scenario.match = null;
      persist();
      render();
    } else if (a === 'confirm-scenario') {
      S.scenario.confirmed = true;
      S.scenario.version = D.SCENARIO.version;
      persist();
      go(2);
    } else if (a === 'nav') {
      closeModal();
      S.wb.nav = b.dataset.nav;
      S.step = 3;
      persist();
      writeRoute();
      render();
      $('#wbmain').scrollTop = 0;
    } else if (a === 'nav-go') {
      closeModal();
      S.wb.nav = b.dataset.nav;
      S.notifOpen = false;
      S.step = 3;
      persist();
      writeRoute();
      render();
    } else if (a === 'matview') {
      S.wb.matView = S.wb.matView || {};
      S.wb.matView[b.dataset.mid] = b.dataset.v;
      persist();
      renderNav();
      renderMain();
    } else if (a === 'cite-open') {
      const pop = b.nextElementSibling;
      showModal('引用到哪个字段', `<div class="cite-choices">${pop.innerHTML}</div>`);
    } else if (a === 'cite') {
      const field = b.dataset.field,
        evidence = JSON.parse(b.dataset.ev);
      closeModal();
      S.wb.planHidden = true;
      addEvidence(field, evidence);
      render();
      if (innerWidth <= 600) {
        $('#pf_' + field)?.scrollIntoView({ block: 'center' });
        $('#pf_' + field)?.focus({ preventScroll: true });
      }
    } else if (a === 'chip-rm') {
      if (S.attempts.some((a) => a.attemptNo === S.attemptNo)) return;
      const f = S.plan[b.dataset.field];
      f.evidence = f.evidence.filter((e) => e.key !== b.dataset.key);
      persist();
      renderPlan();
    } else if (a === 'ask') ask(b.dataset.cid, b.dataset.qid);
    else if (a === 'run') run($('#qsel').value);
    else if (a === 'rerun') run(b.dataset.qid);
    else if (a === 'cfg-save') {
      readCfgDraft();
      if (
        !Number.isInteger(S.cfgDraft.capacity) ||
        S.cfgDraft.capacity < 1 ||
        S.cfgDraft.capacity > 500
      ) {
        toast('人数需为 1–500 的整数', 'red');
        return;
      }
      S.configHistory.push({ ...S.config });
      tick();
      S.config = { ...S.cfgDraft, version: S.config.version + 1, savedAt: clockLabel() };
      S.cfgDraft = null;
      persist();
      renderNav();
      renderMain();
      toast(`已保存配置 v${S.config.version}。回到测试台重跑同一条查询看差异。`);
    } else if (a === 'cfg-reset') {
      if (confirm('放弃未应用的配置修改？已保存配置不受影响。')) {
        S.cfgDraft = null;
        persist();
        renderMain();
      }
    } else if (a === 'sample') {
      const m = $('#samplemenu');
      m.hidden = !m.hidden;
    } else if (a === 'sample-fill') {
      showSample(b.dataset.k);
    } else if (a === 'sample-apply') {
      if (S.attempts.some((a) => a.attemptNo === S.attemptNo)) return;
      S.sampleUndo = clone(S.plan);
      const sp = D.SAMPLE_PLANS[b.dataset.k];
      D.FIELDS.forEach((f) => {
        S.plan[f.id] = { text: sp[f.id], evidence: [] };
      });
      closeModal();
      persist();
      renderPlan();
      toast('已替换九字段并清空旧引用；可撤销。');
    } else if (a === 'sample-undo') {
      if (!S.attempts.some((a) => a.attemptNo === S.attemptNo) && S.sampleUndo) {
        S.plan = clone(S.sampleUndo);
        delete S.sampleUndo;
        persist();
        renderPlan();
        toast('已恢复填入示例前的方案和依据');
      }
    } else if (a === 'ack') {
      const e = S.events.find((x) => x.id === b.dataset.id);
      e.acked = true;
      e.read = true;
      persist();
      render();
    } else if (a === 'notif') {
      S.notifOpen = !S.notifOpen;
      persist();
      renderNotif();
    } else if (a === 'submit') submit();
    else if (a === 'retry-eval') {
      const at = S.attempts.find((x) => x.id === b.dataset.id);
      at.feedback = evaluate(at);
      at.status = 'evaluated';
      persist();
      render();
      toast('评价已完成（模拟）');
    } else if (a === 'open-ev') openEvidence(JSON.parse(b.dataset.ev));
    else if (a === 'close-modal') closeModal();
    else if (a === 'drill') {
      S.drill = { field: b.dataset.field, pick: +b.dataset.i };
      persist();
      render();
    } else if (a === 'variant') {
      startAttempt(b.dataset.id, null);
    } else if (a === 'revise') {
      const src = S.attempts.find((x) => x.id === b.dataset.id);
      startAttempt(src.variant, src.id, JSON.parse(JSON.stringify(src.snapshot.plan)));
    } else if (a === 'open-attempt') openAttempt(b.dataset.id);
    else if (a === 'restart') startAttempt(null, null);
    else if (a === 'reset-all') {
      if (confirm('清除本浏览器里的全部演示状态？旧尝试也会删除。')) {
        localStorage.removeItem(KEY);
        S = freshState();
        persist();
        writeRoute(true);
        render();
      }
    } else if (a === 'demo-fault') {
      S.demo.faultNextTest = true;
      toast('下一次查询将模拟平台超时');
    } else if (a === 'demo-fail-eval') {
      S.demo.failNextEval = true;
      toast('下一次提交将模拟评价失败');
    } else if (a === 'demo-rebuild') {
      S.world.indexM05 = S.world.m05;
      S.world.indexSnapshot = clockLabel() + ' (rebuild)';
      persist();
      toast('已模拟夜间索引重建');
      if (S.step === 3) renderMain();
    }
  });
  document.addEventListener('input', (ev) => {
    const t = ev.target;
    if (t.id === 'voice-transcript') {
      ensurePractice().voiceDraft = t.value;
      persist();
      return;
    }
    if (t.dataset.chat) {
      if (!locked()) {
        ensurePractice().messages[t.dataset.chat] = t.value;
        persist();
      }
      return;
    }
    if (t.dataset.testInput) {
      if (!locked()) {
        ensurePractice().editor[t.dataset.testInput] = t.value;
        persist();
      }
      return;
    }
    if (t.dataset.diagnosis) {
      if (!locked()) {
        const p = ensurePractice();
        p.diagnoses[t.dataset.diagnosis] ||= { text: '', difference: '' };
        p.diagnoses[t.dataset.diagnosis][t.dataset.part] = t.value;
        persist();
      }
      return;
    }
    if (t.id === 'revision-reason') {
      if (!locked()) {
        ensurePractice().revisionReason = t.value;
        persist();
        const b = $('[data-action=submit]');
        if (b) {
          b.disabled = !!submissionBlocks().length;
          const msg = b.nextElementSibling;
          if (msg?.classList.contains('field-err')) msg.hidden = !b.disabled;
        }
      }
      return;
    }
    if (t.dataset.field) {
      if (locked()) return;
      S.plan[t.dataset.field].text = t.value;
      t.closest('.pf')?.classList.toggle('empty', !t.value);
      persist();
      const submitButton = $('[data-action=submit]');
      if (submitButton) {
        submitButton.disabled = !!submissionBlocks().length;
        const check = $('#review-checklist');
        if (check)
          check.innerHTML = validation()
            .map(
              (i) =>
                `<li><span class="${i.s}">${i.s === 'ok' ? '✓' : i.s === 'bad' ? '✕' : '!'}</span><span>${esc(i.t)}</span></li>`,
            )
            .join('');
        const msg = submitButton.nextElementSibling;
        if (msg?.classList.contains('field-err')) msg.hidden = !submitButton.disabled;
      }
    } else if (t.id === 'cap') {
      if (locked()) return;
      readCfgDraft();
      persist();
    } else if (t.id === 'desc') {
      S.scenario.desc = t.value;
      persist();
    }
  });
  document.addEventListener('change', (ev) => {
    const t = ev.target;
    if (t.id === 'wb-select') {
      S.wb.nav = t.value;
      persist();
      writeRoute();
      render();
    } else if (t.id === 'qsel') {
      S.selectedQuery = t.value;
      persist();
    } else if (t.id === 'useauth') {
      S.scenario.useAuth = t.checked;
      persist();
      render();
    } else if (t.name === 'fu') {
      S.scenario.followup = t.value;
      persist();
      render();
    } else if (['scope', 'notice', 'fallback'].includes(t.name) || t.id === 'cap') {
      if (locked()) {
        renderMain();
        return;
      }
      readCfgDraft();
      persist();
      renderMain();
    }
  });
  document.addEventListener(
    'pointerdown',
    () => {
      if (entryTransition) finishEntry();
    },
    { passive: true },
  );
  document.addEventListener(
    'wheel',
    () => {
      if (entryTransition) finishEntry();
    },
    { passive: true },
  );
  document.addEventListener('keydown', (ev) => {
    if (entryTransition) finishEntry();
    if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter' && ev.target.id === 'colleague-question') {
      ev.preventDefault();
      askFree(ev.target.dataset.chat);
      return;
    }
    const modal = $('.modal-bg');
    if (modal && ev.key === 'Tab') {
      const els = [
        ...modal.querySelectorAll(
          'button:not([disabled]),[href],input,select,textarea,[tabindex="0"]',
        ),
      ].filter((e) => e.getClientRects().length);
      const first = els[0],
        last = els[els.length - 1];
      if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
      }
    }
    if (ev.key === 'Escape') {
      closeModal();
      if (S.notifOpen) {
        S.notifOpen = false;
        renderNotif();
        $('[data-action="notif"]')?.focus();
      }
    }
  });

  function startAttempt(variant, revisedFrom, planCopy) {
    archiveDraft();
    const scenario = clone(S.scenario);
    const src = revisedFrom ? S.attempts.find((a) => a.id === revisedFrom) : null;
    const base = src ? { ...S.drafts[src.attemptNo], ...src.snapshot } : freshState();
    for (const k of WORK_KEYS) {
      if (base[k] !== undefined) S[k] = clone(base[k]);
      else delete S[k];
    }
    S.scenario = scenario;
    S.attemptNo = S.nextAttemptNo++;
    S.variant = variant || null;
    S.revisedFrom = revisedFrom || null;
    S.seenFeedback = !!src;
    S.demo.failNextEval = false;
    S.demo.faultNextTest = false;
    S.plan = planCopy || freshState().plan;
    S.cfgDraft = null;
    S.sampleUndo = null;
    S.drill = null;
    S.currentAttempt = null;
    ensurePractice().revisionReason = '';
    S.wb = { nav: src ? 'test' : 'col:DEMO_C_MGR', planHidden: true };
    if (!src) {
      S.world.clock = variant === 'DEMO_V1' ? 216 : 0;
      S.world.indexSnapshot = variant === 'DEMO_V1' ? 'Day 3, 00:00' : 'Day 0, 00:00';
      if (variant === 'DEMO_V2')
        S.events.push({
          id: 'DEMO_E3',
          title: 'Sales requests 35 additional pilot users',
          body: 'Sales asks to add 35 people. Capacity has not changed. Decide who waits and what approval would be required.',
          kind: '新增人群请求',
          ts: clockLabel(),
          read: false,
          acked: false,
        });
    }
    if (!src && variant === 'DEMO_V1') triggerEvent('DEMO_E1');
    persist();
    toast(`已创建 attempt ${S.attemptNo}；原草稿与提交均保留`);
    go(src ? 3 : 2);
  }

  /* 演示控制面板 */
  const dp = document.createElement('div');
  dp.className = 'demo-panel';
  dp.innerHTML = `<details><summary>演示控制（不属于产品）</summary><div class="body"><button class="btn sm" data-action="demo-fault">下次查询模拟平台超时</button><button class="btn sm" data-action="demo-fail-eval">下次提交模拟评价失败</button><button class="btn sm" data-action="demo-rebuild">模拟夜间索引重建</button><span class="small muted">状态存于本浏览器 localStorage。</span></div></details>`;
  document.body.appendChild(dp);

  if (S.schema !== 2) {
    S.attempts.forEach((a) => {
      if (a.feedback) {
        a.legacyFeedback = a.feedback;
        a.feedback = evaluate(a);
      }
    });
    S.schema = 2;
    Object.values(S.threads)
      .flat()
      .forEach((x) => {
        if (x.type === 'a') x.id ||= uid('DEMO_MSG');
      });
  }
  readRoute(true);
  render();
})();
