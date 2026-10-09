import { T, when, locale, isChinese } from './i18n';
import { icon, agentMark, assistantMark } from './art.js';
import { materialTitle } from './vocab.js';

const esc = (v) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
const action = (name, label, attrs = '', style = 'quiet') =>
  `<button type="button" class="btn small ${style}" data-action="${name}" ${attrs}>${label}</button>`;

export function caseState(work, item, attempt, pending, busy) {
  const runs = attempt.tests
    .filter((r) => r.workId === work.id && r.caseId === item.id)
    .slice()
    .reverse();
  const current = runs.find((r) => r.caseRevision === item.revision);
  const waiting =
    pending?.kind === 'test' &&
    pending.localRun?.workId === work.id &&
    pending.localRun?.caseId === item.id;
  const changed =
    current &&
    (current.configVersion !== attempt.configVersion ||
      current.policyVersion !== attempt.world.policyVersion ||
      (attempt.config.update !== 'realtime' &&
        current.indexVersion != null &&
        current.indexVersion !== attempt.world.indexVersion));
  return {
    runs,
    current,
    waiting,
    changed,
    tone: waiting || changed || (runs.length && !current) ? 'attention' : '',
    label: waiting
      ? busy
        ? T('正在运行', 'Running')
        : T('结果待确认', 'Awaiting confirmation')
      : !current && runs.length
        ? T('内容已改，待重测', 'Edited · run again')
        : changed
          ? T('条件已变', 'Conditions changed')
          : current
            ? T('已有结果', 'Result available')
            : T('未运行', 'Not run'),
  };
}

const refTitle = (ref, materials = []) =>
  materialTitle(
    materials.find((m) => m.id === ref.id) || { title: T('参考资料', 'Reference document') },
  );

export function testSetPreview(work, materials = []) {
  return `<article class="test-preview"><header><span class="test-eyebrow">${icon('flask', 'i-sm')}${T('可执行测试计划', 'Runnable test plan')}</span><h3>${esc(work.title)}</h3><p>${T('先检查问题，再带回工作台。导入不会运行测试。', 'Review the questions, then bring them into your workspace. Importing does not run tests.')}</p></header>
    <ol>${work.cases.map((c, i) => `<li><span class="test-number">${String(i + 1).padStart(2, '0')}</span><div><h4>${esc(c.question)}</h4><p>${esc(c.intent)}</p>${c.expectation ? `<p class="test-preview-expect"><span>${T('预期', 'Expected')}</span>${esc(c.expectation)}</p>` : ''}${(c.refs || []).length ? `<div class="test-sources">${c.refs.map((r) => `<span class="stamp">${icon('doc', 'i-xs')}${esc(refTitle(r, materials))} · v${r.version}</span>`).join('')}</div>` : ''}</div></li>`).join('')}</ol>
    <footer>${T(work.cases.length + ' 个问题 · 预期由你检查', work.cases.length + ' questions · expectations for you to review')}</footer></article>`;
}

export function testSetView({
  work,
  attempt,
  session,
  busy,
  canRun,
  editable,
  opened,
  selectedRuns,
  modes,
  errors,
  md,
  strip,
  evidence,
}) {
  const states = work.cases.map((c) => caseState(work, c, attempt, session?.pending, busy));
  const done = states.filter((s) => s.current).length;
  const locked = attempt.backend?.status !== 'active';
  const openId =
    opened === undefined
      ? work.cases.find(
          (c) =>
            session?.pending?.localRun?.workId === work.id &&
            session.pending.localRun.caseId === c.id,
        )?.id || null
      : opened;
  return `<div class="obj-pad test-set-work" data-test-set="${esc(work.id)}">
    <article class="paper test-set-paper">
      ${strip}
      <header class="test-set-head"><div class="test-set-kicker"><span class="test-eyebrow">${icon('flask', 'i-sm')}${T('测试计划', 'Test plan')}</span><span class="test-count">${T(work.cases.length + ' 个问题', work.cases.length + ' questions')}</span></div>
        <label class="sr-only" for="editor-title">${T('标题', 'Title')}</label><input id="editor-title" class="editor-title" data-edit="title" value="${esc(work.title)}" maxlength="160" ${editable ? '' : 'readonly'}>
        <div class="editor-meta"><span>${work.source === 'user' ? T('你写的', 'By you') : T('来自你的 Agent', 'From your agent')}</span><span data-revision>v${work.revision}</span><span class="save" data-save></span></div>
        <p class="test-set-intro">${T('把想确认的事，变成可以亲手验证的问题。', 'Turn what you want to know into questions you can test.')}</p>
      </header>
      <div class="test-set-status"><div class="test-progress" aria-hidden="true">${work.cases.map((c, i) => `<span class="${states[i].current ? 'recorded' : ''}"></span>`).join('')}</div><span class="test-count-results">${T(done + ' / ' + work.cases.length + ' 问题有结果', done + ' / ' + work.cases.length + ' questions have results')}</span><span class="test-review-note">${T('结果由你核对', 'Results for you to review')}</span></div>
      ${!work.requestId ? `<div class="test-context-note">${icon('info', 'i-sm')}<span>${T('这份回传没有关联任务包，采用前请核对它使用的资料与情境。', 'This return has no linked task package. Check its sources and context before adopting it.')}</span></div>` : ''}
      ${!work.adopted ? `<div class="test-context-note">${icon('eye', 'i-sm')}<span>${T('先检查并采用这份计划，再运行其中的问题。', 'Review and adopt this plan before running its questions.')}</span></div>` : !session?.world.configs.pilot ? `<div class="test-context-note">${icon('gear', 'i-sm')}<span>${T('先设置知识助手的试点范围，再开始测试。', 'Set up the assistant’s pilot scope before testing.')}</span>${action('config', T('试点设置', 'Pilot settings'))}</div>` : locked ? `<div class="test-context-note">${icon('lock', 'i-sm')}<span>${T('这次练习只读，已保存的测试仍可查看。', 'This practice is read-only. Saved results remain available.')}</span></div>` : ''}
      <div class="test-sheet-caption"><span>${T('问题与验证目的', 'Question and intent')}</span><span>${T('逐条运行 · 保留每次结果', 'Run individually · keep every result')}</span></div>
      <ol class="test-cases">${work.cases
        .map((c, i) => {
          const s = states[i],
            open = c.id === openId,
            runId = selectedRuns[c.id];
          if (errors[c.id] && !s.waiting) {
            s.label = T('本次未完成', 'Run incomplete');
            s.tone = 'attention';
          }
          const run = s.runs.find((r) => r.id === runId) || s.runs[0];
          const mode = modes[c.id] || (run ? 'result' : 'plan');
          const pendingHere = s.waiting;
          const runAllowed =
            work.adopted &&
            canRun &&
            c.question.trim() &&
            c.question.length <= 4000 &&
            !pendingHere;
          return `<li class="test-case ${open ? 'is-open' : ''} ${pendingHere ? 'is-running' : ''}" data-case-row="${esc(c.id)}">
          <div class="test-case-top"><span class="test-number">${String(i + 1).padStart(2, '0')}</span><button type="button" class="test-case-toggle" data-action="test-toggle" data-id="${esc(c.id)}" aria-expanded="${open}" aria-controls="case-panel-${esc(c.id)}"><span class="test-case-question">${esc(c.question || T('写一个测试问题', 'Write a test question'))}</span><span class="test-case-intent">${esc(c.intent || T('这个问题想验证什么？', 'What should this question verify?'))}</span></button><div class="test-case-controls"><span class="test-state ${s.tone}" role="status">${pendingHere && busy ? '<span class="test-spinner" aria-hidden="true"></span>' : ''}${s.label}</span>${action('test-run', icon(s.runs.length ? 'refresh' : 'play', 'i-xs') + (s.runs.length ? T('重测', 'Run again') : T('运行', 'Run')), `data-id="${esc(c.id)}" ${runAllowed ? '' : 'disabled'}`, 'test-run-btn')}<button type="button" class="btn icon quiet small test-chevron" data-action="test-toggle" data-id="${esc(c.id)}" aria-label="${esc(open ? T('收起问题', 'Collapse question') : T('展开问题', 'Expand question'))}" aria-expanded="${open}">${icon('down', 'i-xs')}</button></div></div>
          <div class="test-case-panel" id="case-panel-${esc(c.id)}" ${open ? '' : 'hidden'}>
            ${run ? `<div class="test-view-switch segmented" role="group" aria-label="${esc(T('问题视图', 'Question view'))}"><span class="thumb"></span><button type="button" data-action="test-mode" data-id="${esc(c.id)}" data-mode="result" aria-pressed="${mode === 'result'}">${T('运行结果', 'Results')}</button><button type="button" data-action="test-mode" data-id="${esc(c.id)}" data-mode="plan" aria-pressed="${mode === 'plan'}">${T('问题与预期', 'Question & expectation')}</button></div>` : ''}
            <div class="test-spec" ${run && mode === 'result' ? 'hidden' : ''}><div class="test-case-fields"><label class="test-field">${T('问知识助手', 'Ask the knowledge assistant')}<textarea id="case-question-${esc(c.id)}" rows="2" data-case-field="question" data-case-id="${esc(c.id)}" maxlength="4000" ${editable ? '' : 'readonly'} placeholder="${esc(T('像员工那样提问…', 'Ask as an employee would…'))}">${esc(c.question)}</textarea></label>
              <div class="test-field-pair"><label class="test-field">${T('想验证什么', 'What to verify')}<textarea id="case-intent-${esc(c.id)}" rows="2" data-case-field="intent" data-case-id="${esc(c.id)}" maxlength="2000" ${editable ? '' : 'readonly'}>${esc(c.intent)}</textarea></label><label class="test-field">${T('预期表现', 'Expected behavior')}<span class="test-field-hint">${T('待验证', 'To be verified')}</span><textarea id="case-expectation-${esc(c.id)}" rows="2" data-case-field="expectation" data-case-id="${esc(c.id)}" maxlength="2000" ${editable ? '' : 'readonly'} placeholder="${esc(T('可以留空', 'Optional'))}">${esc(c.expectation || '')}</textarea></label></div>
            </div>
            ${(c.refs || []).length ? `<div class="test-sources"><span>${T('计划参考', 'Plan references')}</span>${c.refs.map((r) => `<button type="button" class="chip" data-action="test-ref" data-id="${esc(r.id)}" data-version="${r.version}">${icon('doc', 'i-xs')}${esc(refTitle(r, attempt.backend?.materials || []))}<span class="ver">v${r.version}</span></button>`).join('')}</div>` : ''}
            </div>
            ${errors[c.id] ? `<div class="test-inline-error" role="alert">${icon('warn', 'i-sm')}<span>${esc(errors[c.id])}</span></div>` : ''}
            ${pendingHere && !busy ? `<div class="test-context-note">${icon('sync', 'i-sm')}<span>${T('结果还未确认。恢复原请求会保留这次运行，不会另外发起测试。', 'The result is unconfirmed. Resume the original request to recover this run.')}</span>${action('live-retry', T('恢复原请求', 'Resume request'), '', 'primary')}</div>` : ''}
            ${run && mode === 'result' ? testRunView({ run, runs: s.runs, item: c, work, session, md }) : !run ? `<div class="test-run-empty">${icon('flask', 'i-sm')}<p>${T('运行后，回答和引用会留在这里。', 'The answer and its sources will appear here after a run.')}</p></div>` : ''}
            <div class="test-case-foot"><span>v${c.revision} · ${T('每次重测另存结果', 'Every rerun keeps a new result')}</span>${editable ? action('test-remove', T('移除问题', 'Remove question'), `data-id="${esc(c.id)}"`, 'quiet test-remove') : ''}</div>
          </div>
        </li>`;
        })
        .join('')}</ol>
      <footer class="test-set-footer">${editable && work.cases.length < 20 ? action('test-add', icon('plus', 'i-sm') + T('补一个问题', 'Add a question'), '', 'quiet') : ''}<span class="spacer"></span>${action('test-export', icon('download', 'i-xs') + T('导出计划', 'Export plan'))}</footer>
      ${evidence}
    </article>
    <div class="action-bar">${action('agent', agentMark('xs') + T('交给我的 Agent', 'Hand to my agent'))}${action('obj', icon('flask', 'i-sm') + T('自由提问', 'Ask freely'), 'data-type="bench"')}<span class="spacer"></span>${action('request-review', icon('eye', 'i-sm') + T('请求评审', 'Request a review'))}</div>
  </div>`;
}

export function testRunView({ run, runs, item, work, session, md }) {
  const old = run.caseRevision !== item.revision;
  const cited = work.evidence?.some((e) => e.type === 'test' && e.id === run.id);
  const note = session?.testNotes[run.id]?.diagnosis || '';
  return `<section class="test-result" aria-label="${esc(T('实际测试结果', 'Actual test result'))}">
    <header class="test-result-head"><span>${assistantMark('xs')}<b>${T('实际回答', 'Actual answer')}</b></span><label class="test-history"><span class="sr-only">${T('选择一次运行', 'Select a run')}</span><select data-case-history="${esc(item.id)}" aria-label="${esc(T('选择一次运行', 'Select a run'))}">${runs.map((r, i) => `<option value="${esc(r.id)}" ${r.id === run.id ? 'selected' : ''}>${i === 0 ? T('最近一次', 'Latest run') : T('第 ' + (runs.length - i) + ' 次', 'Run ' + (runs.length - i))} · ${T('问题 v', 'Question v')}${r.caseRevision}</option>`).join('')}</select>${icon('down', 'i-xs')}</label></header>
    ${old ? `<p class="test-history-warning">${icon('history', 'i-xs')}${T('这是较早问题版本的结果，当前内容尚未被这次运行验证。', 'This result belongs to an earlier question. It does not verify your current edits.')}</p>` : ''}
    <div class="test-answer prose"${isChinese(run.answer) ? ' lang="zh-CN"' : ''}>${md(run.answer)}${locale() === 'en' && isChinese(run.answer) ? '<p class="msg-local">Chinese source</p>' : ''}</div>
    <div class="test-run-facts"><span>${T('配置 v', 'Config v')}${run.configVersion}</span><span>${T('政策源 v', 'Policy v')}${run.policyVersion ?? '—'}</span><span>${T('使用版本 v', 'Used version v')}${run.indexVersion ?? '—'}</span>${run.createdAt ? `<time>${esc(when(run.createdAt))}</time>` : ''}${run.stale ? `<span class="warn">${icon('stale', 'i-xs')}${T('引用了旧版本', 'Cites an older version')}</span>` : ''}${run.fallback ? `<span>${T('兜底回答', 'Fallback response')}</span>` : ''}</div>
    <div class="test-result-actions">${run.citations.length ? action('run-source', icon('doc', 'i-xs') + T('查看来源', 'View sources'), `data-run="${esc(run.id)}"`) : `<span class="meta">${T('没有返回引用', 'No sources returned')}</span>`}${action('test-cite', icon(cited ? 'check' : 'quote', 'i-xs') + (cited ? T('已作为依据', 'Added as evidence') : T('作为这份计划的依据', 'Use as plan evidence')), `data-id="${esc(run.id)}" ${cited || session?.world.status !== 'active' || !work.adopted ? 'disabled' : ''}`)}<span class="spacer"></span></div>
    <label class="test-observation"><span>${T('你的观察', 'Your observation')}<small>${T('由你判断是否符合预期', 'You decide whether it meets expectations')}</small></span><textarea id="run-note-${esc(run.id)}" data-test-note="${esc(run.id)}" rows="2" maxlength="2000" placeholder="${esc(T('记录发现、疑问，或下一步要验证的事…', 'Record a finding, a question, or what to check next…'))}" ${session?.world.status === 'active' ? '' : 'readonly'}>${esc(note)}</textarea></label>
  </section>`;
}
