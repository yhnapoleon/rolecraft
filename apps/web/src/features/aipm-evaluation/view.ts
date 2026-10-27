/** Evaluation desk markup. Every interpolated value passes `esc`; one screen per tab. */
import type { AipmDesign, MonitoringPlan } from '../../aipm/types';
import { stageName, type StageKey } from '../answer-chain/copy';
import { answerChain, type ChainInput, type ChainView } from '../answer-chain/model';
import { answerChainHtml, chevron } from '../answer-chain/view';
import {
  type BatchView,
  buckets,
  type CaseDraft,
  draftReady,
  type EvaluationCase,
  type EvaluationContent,
  esc,
  type Language,
  latestAssessments,
  MAX_CASES,
  modeLabel,
  monitoringGaps,
  pausedMessage,
  ROUTES,
  type Recovery,
  type Route,
  rowsByRoute,
  summaryLines,
  text,
} from './model';

export type Tab = 'cases' | 'run' | 'monitoring';
export type DeskState = {
  language: Language;
  readOnly: boolean;
  tab: Tab;
  content: EvaluationContent | null;
  design: AipmDesign | null;
  drafts: CaseDraft[];
  view: BatchView | null;
  monitoring: MonitoringPlan[];
  running: boolean;
  busy: boolean;
  notice: { kind: 'status' | 'error'; message: string } | null;
  judging: Record<string, string>;
  /** Saved test results by test id: the answer and its chain input. */
  runs: Record<string, { answer: string; chain: ChainInput }>;
};

const ANSWER_PREVIEW = 140;
const runOf = (state: DeskState, row: EvaluationCase) =>
  row.run_ref ? state.runs?.[row.run_ref.object_id] : undefined;
const chainOf = (state: DeskState, row: EvaluationCase) => {
  const run = runOf(state, row);
  return run ? answerChain(run.chain, state.language) : null;
};
/** Where a run ended up on the chain: the amber step when it carried a problem through. */
const endedAt = (view: ChainView): StageKey =>
  (view.stages.find((s) => s.state === 'warn') ?? view.stages[view.stopAt]).key;

/** The answer (140 characters, the rest on request) and the compact answer chain. */
function runBlock(state: DeskState, row: EvaluationCase) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const run = runOf(state, row);
  const view = chainOf(state, row);
  if (!run || !view || !row.run_ref) return '';
  const answer = run.answer.trim();
  const long = [...answer].length > ANSWER_PREVIEW;
  const short = long ? `${[...answer].slice(0, ANSWER_PREVIEW).join('').trimEnd()}…` : answer;
  const text_ = answer
    ? `<p class="aipm-eval__answer-short">${esc(short)}</p>${long ? `<details class="aipm-eval__answer-full"><summary>${esc(t('展开全文', 'Show the full answer'))}</summary><p>${esc(answer)}</p></details>` : ''}`
    : '';
  return `<div class="aipm-eval__answer">${text_}${answerChainHtml(view, row.run_ref.object_id, {
    language: state.language,
    compact: true,
    handover: !state.readOnly,
  })}</div>`;
}

const routeLabel = (state: DeskState, route: Route) =>
  state.content?.routes.find((r) => r.id === route)?.label ?? route;

function tabs(state: DeskState) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const items: [Tab, string][] = [
    ['cases', t('出题与预期', 'Cases and expectations')],
    ['run', t('运行与判定', 'Run and judge')],
    ['monitoring', t('监控与回退', 'Monitoring and rollback')],
  ];
  return `<div class="aipm-eval__tabs" role="tablist">${items
    .map(
      ([id, label]) =>
        `<button type="button" role="tab" class="aipm-eval__tab" data-eval-tab="${id}" aria-selected="${state.tab === id}">${esc(label)}</button>`,
    )
    .join('')}</div>`;
}

function notice(state: DeskState) {
  if (!state.notice) return '';
  return `<p class="aipm-eval__notice" data-kind="${state.notice.kind}" role="${state.notice.kind === 'error' ? 'alert' : 'status'}">${esc(state.notice.message)}</p>`;
}

function caseTypeOptions(state: DeskState, draft: CaseDraft) {
  const types = state.content?.routes.find((r) => r.id === draft.route)?.case_types ?? [];
  return types
    .map(
      (type) =>
        `<option value="${esc(type.id)}"${type.id === draft.caseType ? ' selected' : ''}>${esc(type.label)}</option>`,
    )
    .join('');
}

function draftCard(state: DeskState, draft: CaseDraft) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const type = state.content?.routes
    .find((r) => r.id === draft.route)
    ?.case_types.find((c) => c.id === draft.caseType);
  const regression =
    state.content?.regression.case_type === draft.caseType &&
    state.content.regression.query === draft.query;
  const hint = regression ? state.content?.regression.expected_hint : type?.expected_hint;
  const disabled = state.readOnly || state.view ? ' disabled' : '';
  const toggle =
    draft.route === 'agent_confirmation'
      ? `<label class="aipm-eval__check"><input type="checkbox" data-eval-draft="${esc(draft.key)}" data-field="answerOnly"${draft.answerOnly ? ' checked' : ''}${disabled}> ${esc(t('只运行其中的检索回答子步骤', 'Run only its retrieval-answer substep'))}</label>`
      : '';
  return `<li class="aipm-eval__draft" data-draft="${esc(draft.key)}" data-ready="${draftReady(draft)}">
  <div class="aipm-eval__draft-head">
    <span class="aipm-eval__select"><select data-eval-draft="${esc(draft.key)}" data-field="caseType" aria-label="${esc(t('测试类型', 'Case type'))}"${disabled}>${caseTypeOptions(state, draft)}</select>${chevron()}</span>
    ${regression ? `<span class="aipm-eval__tag">${esc(state.content?.regression.label)}</span>` : ''}
    <button type="button" class="aipm-eval__link" data-eval-action="remove-draft" data-key="${esc(draft.key)}"${disabled}>${esc(t('移除', 'Remove'))}</button>
  </div>
  <label class="aipm-eval__field"><span>${esc(t('提问', 'Question'))}</span>
    <input type="text" data-eval-draft="${esc(draft.key)}" data-field="query" value="${esc(draft.query)}" placeholder="${esc(type?.query_hint)}"${disabled}></label>
  <label class="aipm-eval__field"><span>${esc(t('你期望的回答', 'Your expected answer'))}</span>
    <textarea rows="2" data-eval-draft="${esc(draft.key)}" data-field="expected" placeholder="${esc(hint)}"${disabled}>${esc(draft.expected)}</textarea></label>
  ${toggle}
</li>`;
}

export function readyLine(state: DeskState) {
  const ready = state.drafts.filter(draftReady).length;
  return text(
    state.language,
    `${ready} 题已写好预期 · 上限 ${MAX_CASES} 题`,
    `${ready} with expectations · up to ${MAX_CASES}`,
  );
}

function casesScreen(state: DeskState) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const content = state.content;
  if (!state.design?.rows?.some((row) => row.need_ref)) {
    return `<div class="aipm-eval__empty"><p>${esc(t('还没有保存过需求分拣。先在「需求与方案」里把需求分到四类，再回来出题。', 'No saved triage yet. Sort needs into the four routes in Needs and design, then come back to write cases.'))}</p></div>`;
  }
  const groups = rowsByRoute(state.design)
    .filter((group) => group.rows.length)
    .map((group) => {
      const route = content?.routes.find((r) => r.id === group.route);
      const rows = group.rows
        .map((row) => {
          const drafts = state.drafts.filter((d) => d.rowId === row.id);
          return `<div class="aipm-eval__row">
  <div class="aipm-eval__row-head"><span class="aipm-eval__need">${esc(row.user_request)}</span>
    <button type="button" class="aipm-eval__link" data-eval-action="add-draft" data-row="${esc(row.id)}"${state.readOnly || state.view || state.drafts.length >= MAX_CASES ? ' disabled' : ''}>${esc(t('加一题', 'Add a case'))}</button></div>
  ${drafts.length ? `<ol class="aipm-eval__drafts">${drafts.map((d) => draftCard(state, d)).join('')}</ol>` : ''}
</div>`;
        })
        .join('');
      return `<section class="aipm-eval__group" data-route="${group.route}">
  <h4>${esc(route?.label ?? group.route)}</h4>
  <p class="aipm-eval__boundary">${esc(route?.boundary)}</p>
  ${rows}
</section>`;
    })
    .join('');
  const ready = state.drafts.filter(draftReady).length;
  const regressionAdded = state.drafts.some(
    (d) => d.caseType === content?.regression.case_type && d.query === content?.regression.query,
  );
  const regression =
    content && !regressionAdded && !state.view
      ? `<button type="button" class="aipm-eval__link" data-eval-action="add-regression"${state.readOnly ? ' disabled' : ''}>${esc(t(`加入${content.regression.label}`, `Add the ${content.regression.label.toLowerCase()}`))}</button>`
      : '';
  const foot = state.view
    ? `<p class="aipm-eval__muted">${esc(t('这些题已建成评测批次。要改预期，请新建一份测试计划；旧成绩不会被改写。', 'These cases are in a batch. To change an expectation, start a new plan; earlier results are not rewritten.'))}</p>`
    : `<div class="aipm-eval__foot"><span class="aipm-eval__muted" data-eval-ready>${esc(readyLine(state))}</span>${regression}
  <button type="button" class="btn primary" data-eval-action="save-plan"${state.readOnly || state.busy || !ready ? ' disabled' : ''}>${esc(t('保存预期并建立批次', 'Save expectations and create batch'))}</button></div>`;
  return `${groups}${foot}`;
}

function statusLabel(language: Language, row: EvaluationCase, recovery?: Recovery) {
  const t = (zh: string, en: string) => text(language, zh, en);
  switch (row.status ?? 'pending') {
    case 'completed':
      return t('已运行', 'Ran');
    case 'execution_failed':
      return t('运行失败', 'Run failed');
    case 'unsupported':
      return t('计划用例 · 未支持运行', 'Plan only · not runnable');
    case 'cancelled':
      return t('已取消', 'Cancelled');
    default:
      if (!row.original_command) return t('待运行', 'Waiting');
      if (recovery === 'send_again')
        return t('服务端没有收到这道题', 'The server did not receive this case');
      if (recovery === 'reprepare')
        return t('条件已变，需重新准备', 'Conditions changed; prepare it again');
      return t('结果待确认', 'Outcome not confirmed');
  }
}

function caseQuery(state: DeskState, row: EvaluationCase) {
  const draft = state.drafts.find((d) => d.rowId === row.triage_row_id && d.query);
  const command = row.original_command as { payload?: { query?: string } } | null | undefined;
  return command?.payload?.query ?? draft?.query ?? row.id.slice(0, 8);
}

function caseLine(state: DeskState, row: EvaluationCase, extra = '') {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const open = row.run_ref
    ? `<button type="button" class="aipm-eval__link" data-eval-action="open-run" data-case="${esc(row.id)}">${esc(t('看运行结果', 'View run'))}</button>`
    : '';
  const recovery =
    row.status === 'pending' && row.original_command ? state.view?.recovery?.[row.id] : undefined;
  const disabled = state.readOnly || state.busy || state.running ? ' disabled' : '';
  // Explicit only: the same saved original, or a new request after conditions moved.
  const act =
    recovery === 'send_again'
      ? `<button type="button" class="btn" data-eval-action="send-again" data-case="${esc(row.id)}"${disabled}>${esc(t('重新发送', 'Send again'))}</button>`
      : recovery === 'reprepare'
        ? `<button type="button" class="btn" data-eval-action="reprepare" data-case="${esc(row.id)}"${disabled}>${esc(t('重新准备', 'Prepare again'))}</button>`
        : '';
  const abandoned = row.abandoned?.length
    ? `<span>${esc(t(`已放弃 ${row.abandoned.length} 条旧请求，不计入统计`, `${row.abandoned.length} abandoned request${row.abandoned.length > 1 ? 's' : ''}, not counted`))}</span>`
    : '';
  return `<li class="aipm-eval__case" data-status="${esc(row.status ?? 'pending')}">
  <div class="aipm-eval__case-head"><span class="aipm-eval__q">${esc(caseQuery(state, row))}</span><span class="aipm-eval__state">${esc(statusLabel(state.language, row, recovery))}</span></div>
  ${runBlock(state, row)}
  <div class="aipm-eval__meta"><span>${esc(routeLabel(state, row.route))}</span>${abandoned}${open}${act}</div>${extra}
</li>`;
}

function judgeForm(state: DeskState, row: EvaluationCase) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const disabled = state.readOnly || state.busy ? ' disabled' : '';
  const reason = state.judging[row.id] ?? '';
  const button = (result: string, label: string) =>
    `<button type="button" class="btn" data-eval-action="judge" data-case="${esc(row.id)}" data-result="${result}"${disabled || !reason.trim() ? ' disabled' : ''}>${esc(label)}</button>`;
  return `<div class="aipm-eval__judge">
  <textarea rows="2" data-eval-judge="${esc(row.id)}" placeholder="${esc(t('对照你的预期写一句理由', 'One line of reasoning against your expectation'))}"${disabled}>${esc(reason)}</textarea>
  <div class="aipm-eval__judge-actions">${button('satisfied', t('满足预期', 'Meets expectation'))}${button('not_satisfied', t('不满足', 'Does not meet'))}${button('unknown', t('无法判断', 'Can’t tell'))}</div>
</div>`;
}

function summaryBlock(state: DeskState, view: BatchView) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const lines = summaryLines(state.language, view.summary.all)
    .map(
      (line) =>
        `<div class="aipm-eval__stat" data-stat="${line.id}"><dt>${esc(line.label)}</dt><dd>${esc(line.value)}</dd><p>${esc(line.note)}</p></div>`,
    )
    .join('');
  const byRoute = ROUTES.filter((route) => view.summary[route]?.total)
    .map((route) => {
      const c = view.summary[route];
      return `<li><span>${esc(routeLabel(state, route))}</span><span>${esc(
        t(
          `${c.total} 题 · 运行 ${c.completed}/${c.runnable} · 判定 ${c.assessed}/${c.completed} · 满足 ${c.satisfied}/${c.assessed} · 未支持 ${c.unsupported}`,
          `${c.total} cases · ran ${c.completed}/${c.runnable} · judged ${c.assessed}/${c.completed} · satisfied ${c.satisfied}/${c.assessed} · plan-only ${c.unsupported}`,
        ),
      )}</span></li>`;
    })
    .join('');
  return `<dl class="aipm-eval__stats">${lines}</dl><ul class="aipm-eval__routes">${byRoute}</ul>${unmetBlock(state, view)}
<p class="aipm-eval__muted">${esc(t('本期由你本人判定，不做自动语义评分。', 'You judge every result in this release; there is no automatic semantic scoring.'))}</p>`;
}

/** Cases judged "does not meet", grouped by where they stopped on the answer chain. */
export function unmetByStage(state: DeskState, view: BatchView) {
  const latest = latestAssessments(view.assessments);
  const counts = new Map<StageKey, number>();
  for (const row of view.batch.cases) {
    if (latest.get(row.id)?.result !== 'not_satisfied') continue;
    const chain = chainOf(state, row);
    if (!chain || chain.tone === 'unknown') continue;
    const key = endedAt(chain);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function unmetBlock(state: DeskState, view: BatchView) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const groups = unmetByStage(state, view);
  if (!groups.length) return '';
  return `<p class="aipm-eval__unmet"><span>${esc(t('不满足的题停在哪一环', 'Where the unmet cases stopped'))}</span><span>${esc(
    groups.map(([key, n]) => `${stageName(key, state.language)} ${n}`).join(' · '),
  )}</span></p>`;
}

function runScreen(state: DeskState) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const view = state.view;
  if (!view) {
    return `<div class="aipm-eval__empty"><p>${esc(t('还没有评测批次。先在「出题与预期」里写好预期并保存。', 'No batch yet. Save cases with expectations first.'))}</p></div>`;
  }
  const b = buckets(view);
  const remaining = b.waiting.length;
  const paused = pausedMessage(
    state.language,
    view.batch.pause_reason,
    state.content as EvaluationContent,
  );
  const runLabel = state.running
    ? t('停止发起新题', 'Stop starting new cases')
    : t(`逐题运行剩余 ${remaining} 题`, `Run the remaining ${remaining} one by one`);
  const disabled = state.readOnly || (!state.running && !remaining) ? ' disabled' : '';
  const latest = latestAssessments(view.assessments);
  const list = (
    title: string,
    rows: EvaluationCase[],
    render: (row: EvaluationCase) => string,
    note = '',
  ) =>
    rows.length
      ? `<section class="aipm-eval__bucket"><h4>${esc(title)} <span>${rows.length}</span></h4>${note ? `<p class="aipm-eval__muted">${esc(note)}</p>` : ''}<ol>${rows.map(render).join('')}</ol></section>`
      : '';
  return `<div class="aipm-eval__runbar">
  <div><p class="aipm-eval__mode">${esc(modeLabel(state.language, view.batch.execution_mode))}</p>
  <p class="aipm-eval__muted">${esc(state.content?.run.explain)}</p></div>
  <button type="button" class="btn primary" data-eval-action="${state.running ? 'stop' : 'run'}"${disabled}>${esc(runLabel)}</button>
</div>
${paused ? `<p class="aipm-eval__notice" data-kind="status">${esc(paused)}${view.batch.pause_reason === 'user_paused' || view.batch.pause_reason === 'conditions_changed' ? ` <button type="button" class="aipm-eval__link" data-eval-action="resume"${state.readOnly ? ' disabled' : ''}>${esc(t('核对后继续', 'Checked; continue'))}</button>` : ''}</p>` : ''}
${list(t('待判定', 'To judge'), b.awaitingJudgement, (row) => caseLine(state, row, judgeForm(state, row)), t('运行完成只说明有结果，满足与否由你对照预期判断。', 'A finished run only means there is a result; you judge it against your expectation.'))}
${list(t('待运行', 'Waiting to run'), b.waiting, (row) => caseLine(state, row))}
${list(t('已判定', 'Judged'), b.judged, (row) => caseLine(state, row, `<p class="aipm-eval__verdict" data-result="${esc(latest.get(row.id)?.result)}">${esc(verdict(state.language, latest.get(row.id)?.result))} · ${esc(latest.get(row.id)?.reason)}</p>`))}
${list(t('运行失败', 'Run failed'), b.failed, (row) => caseLine(state, row), t('没有产生结果，不是质量判断。', 'No result was produced; this is not a quality judgement.'))}
${list(t('计划用例 · 未支持运行', 'Plan only · not runnable'), b.unsupported, (row) => caseLine(state, row), t('当前产品没有对应执行器，不进入运行通过率。', 'No executor exists for these; they stay out of the run rate.'))}
${list(t('已取消', 'Cancelled'), b.cancelled, (row) => caseLine(state, row))}
${summaryBlock(state, view)}`;
}

function verdict(language: Language, result?: string) {
  const t = (zh: string, en: string) => text(language, zh, en);
  if (result === 'satisfied') return t('满足预期', 'Meets expectation');
  if (result === 'not_satisfied') return t('不满足', 'Does not meet');
  if (result === 'unsupported') return t('未支持', 'Not supported');
  return t('无法判断', 'Can’t tell');
}

export const monitoringComplete = (state: DeskState) =>
  state.monitoring.length > 0 && state.monitoring.every((p) => !monitoringGaps(p).length);
export const monitoringLine = (state: DeskState) =>
  monitoringComplete(state)
    ? text(state.language, '每项都已填写。', 'Every field is filled.')
    : text(
        state.language,
        '每条计划的八项都填写后才能保存。',
        'Fill all eight fields of each plan to save.',
      );

function monitoringScreen(state: DeskState) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const content = state.content;
  if (!content) return '';
  const disabled = state.readOnly || !state.view ? ' disabled' : '';
  const plans = state.monitoring
    .map((plan, index) => {
      const gaps = monitoringGaps(plan);
      const fields = content.monitoring.fields
        .map(
          (field) =>
            `<label class="aipm-eval__field"><span>${esc(field.label)}</span><input type="text" data-eval-monitor="${index}" data-field="${esc(field.id)}" value="${esc(plan[field.id])}" placeholder="${esc(field.hint)}"${disabled}></label>`,
        )
        .join('');
      return `<li class="aipm-eval__plan" data-complete="${!gaps.length}"><div class="aipm-eval__plan-grid">${fields}</div>
<button type="button" class="aipm-eval__link" data-eval-action="remove-monitor" data-index="${index}"${disabled}>${esc(t('移除这条', 'Remove'))}</button></li>`;
    })
    .join('');
  const starters = content.monitoring.starter_metrics
    .map(
      (m, index) =>
        `<button type="button" class="aipm-eval__chip" data-eval-action="add-monitor" data-starter="${index}" data-source="${m.source}"${disabled}>${esc(m.metric)}${m.source === 'to_collect' ? ` · ${esc(t('待采集', 'to collect'))}` : ''}</button>`,
    )
    .join('');
  const complete = monitoringComplete(state);
  return `<p class="aipm-eval__muted">${esc(content.monitoring.intro)}</p>
${state.view ? '' : `<p class="aipm-eval__notice" data-kind="status">${esc(t('观察计划跟着评测批次保存。先建立批次。', 'The plan is saved with an evaluation batch. Create one first.'))}</p>`}
<div class="aipm-eval__chips">${starters}<button type="button" class="aipm-eval__chip" data-eval-action="add-monitor"${disabled}>${esc(t('自定义', 'Custom'))}</button></div>
${plans ? `<ol class="aipm-eval__plans">${plans}</ol>` : ''}
<p class="aipm-eval__muted">${esc(content.monitoring.rollback_note)}</p>
<div class="aipm-eval__foot"><span class="aipm-eval__muted" data-eval-complete>${esc(monitoringLine(state))}</span>
<button type="button" class="btn primary" data-eval-action="save-monitoring"${disabled || !complete || state.busy ? ' disabled' : ''}>${esc(t('保存观察计划', 'Save observation plan'))}</button></div>`;
}

export function renderDesk(state: DeskState) {
  const t = (zh: string, en: string) => text(state.language, zh, en);
  const body =
    state.tab === 'cases'
      ? casesScreen(state)
      : state.tab === 'run'
        ? runScreen(state)
        : monitoringScreen(state);
  return `<section class="aipm-eval" lang="${state.language}" aria-busy="${state.busy}">
<header class="aipm-eval__head"><h3>${esc(state.content?.title ?? t('评测、监控与回退', 'Evaluation, monitoring and rollback'))}</h3>
<p class="aipm-eval__muted">${esc(state.content?.intro)}</p></header>
${tabs(state)}${notice(state)}
<div class="aipm-eval__body" role="tabpanel">${body}</div>
</section>`;
}
