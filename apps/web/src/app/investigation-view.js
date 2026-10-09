import { T, when, isChinese, locale } from './i18n';
import { icon, assistantMark, agentMark } from './art.js';
import { materialTitle } from './vocab.js';

const esc = (v) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
const button = (label, action, attrs = '', cls = 'quiet') =>
  `<button type="button" class="btn small ${cls}" data-action="${action}" ${attrs}>${label}</button>`;
const version = (value) => (value == null ? T('未知', 'Unknown') : 'v' + esc(value));
const detailsOpen = (state, key, initial = false) =>
  (state?.open?.[key] ?? initial) ? ' open' : '';
const language = (text) => (isChinese(text) ? ' lang="zh-CN"' : '');
const sourceLanguage = (text) =>
  locale() === 'en' && isChinese(text) ? '<small class="msg-local">Chinese source</small>' : '';
export const investigationSourceKey = (sessionId, block) =>
  [sessionId, block.testId, block.material?.id, block.material?.version].join('|');
const blockTitle = (b) =>
  ({
    note: b.title || T('调查思路', 'Investigation notes'),
    test_compare: T('测试记录对照', 'Compare test records'),
    source_check: T('回答与资料版本', 'Answer and source versions'),
    retest: T('下一步验证', 'Check the next step'),
  })[b.type];
const glyph = (type) =>
  ({ note: 'note', test_compare: 'flask', source_check: 'layers', retest: 'refresh' })[type];

export function investigationPreview(work) {
  return `<article class="investigation-preview"><span class="inv-eyebrow">${icon('layers', 'i-sm')}${T('可组合的调查视图', 'Composable investigation')}</span><h3>${esc(work.title)}</h3><p>${esc(work.question)}</p><ol>${work.blocks.map((b, i) => `<li><span class="inv-number">${String(i + 1).padStart(2, '0')}</span>${icon(glyph(b.type), 'i-sm')}<div><b>${esc(blockTitle(b))}</b><p>${b.type === 'note' ? esc(b.text) : b.type === 'test_compare' ? T(b.testIds.length + ' 次真实测试', b.testIds.length + ' actual test runs') : b.type === 'source_check' ? T('核对实际引用与所选资料版本', 'Check the actual citation against the selected source version') : esc(b.label || T('由你决定是否重测', 'You decide whether to rerun'))}</p></div></li>`).join('')}</ol><footer>${T('模块和顺序由 Agent 提出；证据由工作台核对，操作由你发起。', 'The agent proposes modules and their order. The workspace verifies evidence; you initiate actions.')}</footer></article>`;
}

function runFacts(run) {
  const citations = run.citations || [];
  return `<div class="inv-facts"><span>${T('配置 ', 'Config ')}${version(run.configVersion)}</span><span>${T('当时政策源 ', 'Policy at run ')}${version(run.policyVersion)}</span><span>${T('当时索引 ', 'Index at run ')}${version(run.indexVersion)}</span>${citations.map((c) => `<span>${esc(materialTitle({ id: c.id, title: c.title }))} · ${version(c.version)}</span>`).join('')}${!citations.length ? `<span>${T('未记录引用', 'No citation recorded')}</span>` : ''}${run.fallback ? `<span>${T('兜底回答', 'Fallback')}</span>` : ''}${run.stale ? `<span class="warn">${T('当时引用已过期', 'Citation was stale at the time')}</span>` : ''}</div>`;
}
function runPanel(run, label, md, canCite, key, viewState) {
  if (!run)
    return `<section class="inv-pane"><h4>${esc(label)}</h4><p class="inv-missing">${T('这条真实运行记录暂未取得。', 'This actual run is not available yet.')}</p></section>`;
  const answer = String(run.answer || '');
  const plain = answer.replace(/^#{1,6}\s+/gm, '').trim();
  const excerpt = plain.length > 180 ? plain.slice(0, 180) + '…' : plain;
  const answerKey = key + ':answer:' + run.id;
  return `<section class="inv-pane inv-run-pane"><header><span class="inv-pane-label">${esc(label)}</span><time>${run.createdAt ? esc(when(run.createdAt)) : T('时间未记录', 'Time not recorded')}</time></header><p class="inv-question"${language(run.question)}>${esc(run.question)}</p><details class="inv-answer-details" data-key="${esc(answerKey)}"${detailsOpen(viewState, answerKey)}><summary>${icon('chev', 'i-xs')}<span class="inv-when-closed">${T('展开完整回答', 'Read full answer')}</span><span class="inv-when-open">${T('收起完整回答', 'Collapse answer')}</span></summary><div class="prose inv-answer"${language(answer)}>${md(answer)}${sourceLanguage(answer)}</div></details><p class="inv-answer-excerpt"${language(answer)}>${esc(excerpt) || T('未记录回答正文。', 'No answer text recorded.')}</p>${runFacts(run)}<div class="inv-pane-actions">${button(icon('doc', 'i-xs') + T('查看引用', 'View citations'), 'run-source', `data-run="${esc(run.id)}"`)}${button(icon('quote', 'i-xs') + T('引用结果', 'Cite result'), 'investigation-cite', `data-id="${esc(run.id)}" ${canCite ? '' : 'disabled'}`)}</div></section>`;
}
function materialPane(material, label, sourceVersion, md, waiting, key, viewState) {
  return `<section class="inv-pane inv-original"><header><span class="inv-pane-label">${esc(label)}</span><span class="stamp">${version(sourceVersion)}</span></header>${material ? `<h4>${esc(materialTitle(material))}</h4><details data-key="${esc(key)}"${detailsOpen(viewState, key)}><summary>${icon('chev', 'i-xs')}${T('阅读原文', 'Read original')}</summary><div class="prose inv-material"${language(material.content)}>${md(material.content, { dropTitle: true })}${sourceLanguage(material.content)}</div></details>` : `<p class="inv-missing">${icon(waiting ? 'sync' : 'info', 'i-sm')}${waiting ? T('正在读取这个版本…', 'Loading this exact version…') : T('这个版本的正文暂未取得。不会用其他版本替代。', 'This version is unavailable. Another version is not substituted.')}</p>`}</section>`;
}
function evidenceOverview(work, attempt, cache) {
  const sources = work.blocks.filter((b) => b.type === 'source_check');
  if (!sources.length) return '';
  return `<section class="inv-evidence-overview" aria-label="${T('证据版本关系', 'Evidence versions')}"><div class="inv-overview-label">${icon('layers', 'i-sm')}${T('证据与版本', 'Evidence & versions')}</div>${sources
    .map((block) => {
      const run = attempt.tests.find((r) => r.id === block.testId);
      const cited = run?.citations?.find((c) => c.id === block.material.id);
      const current = attempt.backend?.materials?.find((m) => m.id === block.material.id);
      const state = cache[investigationSourceKey(attempt.id, block)];
      const material = state?.selected || current || { id: block.material.id };
      const differs = cited?.version != null && cited.version !== block.material.version;
      return `<div class="inv-version-row"><b>${esc(materialTitle(material))}</b><dl><div><dt>${T('回答引用', 'Answer cites')}</dt><dd>${version(cited?.version)}</dd></div><div class="${differs ? 'inv-version-changed' : ''}"><dt>${T('本次核对', 'Comparing')}</dt><dd>${version(block.material.version)}</dd></div><div><dt>${T('当前资料', 'Current source')}</dt><dd>${version(current?.version)}</dd></div></dl></div>`;
    })
    .join('')}</section>`;
}
function reviewPanel(work, mutable) {
  const review = work.review || { focus: 'uncertain', note: '' };
  const options = [
    ['uncertain', T('还不能确定', 'Not yet sure')],
    ['index', T('重点核对索引', 'Check the index')],
    ['source', T('重点核对资料', 'Check the source')],
    ['other', T('其他判断', 'Another interpretation')],
  ];
  return `<section class="inv-review"><header class="inv-block-head">${icon('note', 'i-sm')}<h3>${T('我的调查判断', 'My investigation judgment')}</h3></header><div class="inv-review-controls"><label>${T('当前判断', 'Current focus')}<select id="investigation-review-focus" data-investigation-review="focus" ${mutable ? '' : 'disabled'}>${options.map(([value, label]) => `<option value="${value}" ${review.focus === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label><span>${T('可以暂留疑问，也可以保留不同看法。', 'Questions and different interpretations can stay open.')}</span></div><label class="sr-only" for="investigation-review-note">${T('判断与依据', 'Judgment and evidence')}</label><textarea id="investigation-review-note" data-investigation-review="note" rows="3" maxlength="4000" placeholder="${esc(T('记下你的判断、依据，或还缺什么证据…', 'Record your judgment, evidence, or what is still missing…'))}" ${mutable ? '' : 'readonly'}>${esc(review.note)}</textarea><div class="inv-review-footer"><span>${T('写下判断，不代表验证已通过。', 'Recording a judgment does not mark a check as passed.')}</span>${button(T('保存判断', 'Save judgment'), 'investigation-review-save', mutable ? '' : 'disabled', 'primary')}</div></section>`;
}

export function investigationView({
  work,
  attempt,
  session,
  mutable,
  readOnly,
  canRun,
  busy,
  cache = {},
  errors = {},
  controls = '',
  strip = '',
  md,
  diffHtml,
  viewState = {},
}) {
  const pending = session?.pending,
    canCite = mutable && work.adopted;
  const origin = work.ruleOrigin
    ? T('规则起始视图', 'Rule-based starting view')
    : work.source === 'user'
      ? T('你的调查记录', 'Your investigation')
      : T('外部 Agent 组合', 'Composed by your agent');
  return `<div class="obj-pad investigation-work"><article class="paper investigation-paper">${strip}${controls}<header class="investigation-head"><div class="inv-kicker"><span class="inv-eyebrow">${icon('layers', 'i-sm')}${T('调查工作纸', 'Investigation workpaper')}</span><span class="inv-origin">${work.ruleOrigin || work.source === 'user' ? '' : agentMark('xs')}${origin}</span></div><label class="sr-only" for="editor-title">${T('标题', 'Title')}</label><input id="editor-title" class="editor-title" data-edit="title" value="${esc(work.title)}" maxlength="160" ${mutable ? '' : 'readonly'}><div class="editor-meta"><span data-revision>v${work.revision}</span><span>${T(work.blocks.length + ' 个模块', work.blocks.length + ' modules')}</span><span data-save></span></div><label class="inv-purpose">${T('要弄清什么', 'What are we trying to understand?')}<textarea id="investigation-question" data-investigation-question rows="1" maxlength="1000" ${mutable ? '' : 'readonly'}>${esc(work.question)}</textarea></label></header>
    ${readOnly || !work.adopted ? `<p class="inv-adoption-note">${icon('eye', 'i-sm')}${readOnly ? T('当前练习只读，可查看已保存证据。', 'This practice is read-only. Saved evidence is available to review.') : T('先检查并采用；读取证据不会运行测试。', 'Review and adopt before running tests. Reading evidence does not run them.')}</p>` : ''}
    ${evidenceOverview(work, attempt, cache)}
    <div class="investigation-blocks">${work.blocks
      .map((block, index) => {
        const key = investigationSourceKey(attempt.id, block),
          state = cache[key],
          run = attempt.tests.find((r) => r.id === block.testId);
        const waiting =
          pending?.localRun?.investigationId === work.id && pending.localRun.blockId === block.id;
        const outcomes = attempt.tests
          .filter((r) => r.investigationId === work.id && r.blockId === block.id)
          .slice()
          .reverse();
        let content = '';
        if (block.type === 'note')
          content = `<div class="inv-note prose">${md(block.text)}</div><span class="inv-note-origin">${work.ruleOrigin ? T('规则整理，供你核对', 'Rule-based, for your review') : work.source === 'user' ? T('你的工作笔记', 'Your working notes') : T('Agent 的分析，供你核对', 'Agent analysis, for your review')}</span>`;
        if (block.type === 'test_compare')
          content = `<div class="inv-grid inv-run-grid">${block.testIds
            .map((id, i) =>
              runPanel(
                attempt.tests.find((r) => r.id === id),
                T('测试 ' + (i + 1), 'Test ' + (i + 1)),
                md,
                canCite,
                block.id,
                viewState,
              ),
            )
            .join('')}</div>`;
        if (block.type === 'source_check') {
          const cited = run?.citations?.find((c) => c.id === block.material.id);
          const latest = attempt.backend?.materials?.find((m) => m.id === block.material.id);
          const before = state?.citation?.material,
            after = state?.selected;
          const mode = viewState.modes?.[block.id] === 'original' ? 'original' : 'diff';
          const available =
            typeof before?.content === 'string' && typeof after?.content === 'string';
          const identical = available && before.content === after.content;
          const answerKey = block.id + ':source-answer';
          const waitingSource = !state || state.loading;
          content = `${run ? `<details class="inv-source-answer" data-key="${esc(answerKey)}"${detailsOpen(viewState, answerKey)}><summary>${assistantMark('xs')}${T('查看这次实际回答', 'Read the actual answer')}<span class="inv-inline-fact">${T('引用 ', 'Cites ')}${version(cited?.version)}</span></summary><div class="prose inv-source-answer-text"${language(run.answer)}>${md(run.answer, { dropTitle: true })}${sourceLanguage(run.answer)}</div><div class="inv-pane-actions">${button(T('查看引用', 'View citations'), 'run-source', `data-run="${esc(run.id)}"`)}${button(T('引用结果', 'Cite result'), 'investigation-cite', `data-id="${esc(run.id)}" ${canCite ? '' : 'disabled'}`)}</div></details>` : `<p class="inv-missing">${T('原回答暂未取得，无法确认实际引用。', 'The original answer is unavailable; its citation cannot be confirmed.')}</p>`}<div class="inv-comparison-toolbar"><p>${T('实际引用 ', 'Actually cited ')}<b>${version(cited?.version)}</b><span aria-hidden="true"> → </span>${T('本次核对 ', 'Comparing ')}<b>${version(block.material.version)}</b></p><div class="inv-mode" role="group" aria-label="${T('资料查看方式', 'Source view')}">${['diff', 'original'].map((m) => button(m === 'diff' ? T('差异', 'Changes') : T('原文', 'Originals'), 'investigation-mode', `id="investigation-mode-${esc(block.id)}-${m}" data-id="${esc(block.id)}" data-mode="${m}" aria-pressed="${mode === m}"`, mode === m ? 'inv-mode-active' : 'quiet')).join('')}</div></div>${mode === 'diff' ? `<div class="inv-diff-surface">${available && diffHtml ? `${identical ? `<p class="inv-missing">${T('这两个版本的正文一致。', 'The text of these two versions is identical.')}</p>` : `<p class="inv-diff-legend"><span class="inv-diff-before">${T('原有内容', 'Previous text')}</span><span class="inv-diff-after">${T('变更内容', 'Changed text')}</span></p>`}<div class="prose inv-material"${language(after.content)}>${diffHtml(before.content, after.content)}${sourceLanguage(after.content)}</div>` : `<p class="inv-missing">${icon(waitingSource ? 'sync' : 'info', 'i-sm')}${waitingSource ? T('正在读取两个版本，取得原文后显示差异…', 'Loading both versions to compare their text…') : T('还没有取得可比较的两份正文，请查看原文或重新读取。', 'Both source texts are needed to compare changes. View originals or load again.')}</p>`}</div>` : `<div class="inv-grid">${materialPane(before, T('回答实际引用', 'Actually cited'), cited?.version, md, waitingSource, block.id + ':cited-original', viewState)}${materialPane(after, T('本次核对版本', 'Selected version'), block.material.version, md, waitingSource, block.id + ':selected-original', viewState)}</div>`}${latest && latest.version !== block.material.version ? `<p class="inv-version-note">${icon('stale', 'i-xs')}${T('当前资料已到 v' + latest.version + '，这里保留你选择的 v' + block.material.version + '。', 'The current source is v' + latest.version + '. This view keeps your selected v' + block.material.version + '.')}</p>` : ''}${state?.error ? `<p class="inv-load-error" role="status">${esc(state.error)}</p>` : ''}${state && !state.loading && !available ? button(T('重新读取', 'Try loading again'), 'investigation-load', `data-id="${esc(block.id)}"`) : ''}`;
        }
        if (block.type === 'retest') {
          const historyKey = block.id + ':run-history';
          const policyVersion = Number.isFinite(attempt.world?.policyVersion)
            ? attempt.world.policyVersion
            : undefined;
          const indexVersion = Number.isFinite(attempt.world?.indexVersion)
            ? attempt.world.indexVersion
            : undefined;
          const indexBehind =
            policyVersion != null && indexVersion != null && indexVersion < policyVersion;
          const canRefresh = indexBehind && (run?.citations || []).some((c) => c.id === 'policy');
          content = `<div class="inv-retest-lead"><p class="inv-retest-question">${icon('flask', 'i-sm')}${esc(run?.question || T('原测试暂不可用', 'Original test unavailable'))}</p><p class="inv-retest-note">${T('沿用问题，使用当前试点设置；不会自动刷新索引。', 'Same question, current pilot settings. The index is not refreshed automatically.')}</p><p class="inv-current-index ${indexBehind ? 'warn' : ''}">${icon(indexBehind ? 'stale' : 'layers', 'i-xs')}<span>${T('当前政策源 ', 'Current policy ')}${version(policyVersion)} / ${T('索引 ', 'index ')}${version(indexVersion)}${indexBehind ? T('，索引落后', ', index behind') : ''}</span></p></div><div class="inv-action-row">${button(icon('refresh', 'i-sm') + esc(block.label || T('按当前设置重测', 'Rerun with current settings')), 'investigation-retest', `data-id="${esc(block.id)}" ${canRun && work.adopted && run && !waiting ? '' : 'disabled'}`, 'primary')}${canRefresh ? button(icon('sync', 'i-sm') + T('刷新索引', 'Refresh index'), 'investigation-refresh-index', `data-id="${esc(block.id)}" ${canRun && work.adopted && run && !waiting ? '' : 'disabled'}`) : ''}${button(icon('gear', 'i-sm') + T('查看设置', 'View settings'), 'config')}${waiting ? `<span class="inv-run-state" role="status">${busy ? T('正在运行…', 'Running…') : T('结果待确认', 'Awaiting confirmation')}</span>` : ''}</div>${errors[block.id] || (waiting && !busy) ? `<div class="inv-recovery" role="alert"><p>${icon('info', 'i-sm')}${errors[block.id] ? esc(errors[block.id]) : T('这次请求尚未确认结果。', 'This request has no confirmed result yet.')}</p>${waiting && !busy ? button(T('恢复原请求', 'Resume request'), 'live-retry', '', 'primary') : ''}</div>` : ''}${
            outcomes.length
              ? `<div class="inv-result-label"><span>${T('原记录与最新重测', 'Original & latest rerun')}</span><span>${T('共 ' + outcomes.length + ' 次重测', '' + outcomes.length + ' rerun(s)')}</span></div><div class="inv-grid inv-run-grid">${runPanel(run, T('作为起点的运行', 'Original run'), md, canCite, block.id + ':baseline', viewState)}${runPanel(outcomes[0], T('最新重测', 'Latest rerun'), md, canCite, block.id + ':latest', viewState)}</div>${
                  outcomes.length > 1
                    ? `<details class="inv-run-history" data-key="${esc(historyKey)}"${detailsOpen(viewState, historyKey)}><summary>${icon('chev', 'i-xs')}${T('更早的 ' + (outcomes.length - 1) + ' 次重测', '' + (outcomes.length - 1) + ' earlier rerun(s)')}<span>${T('全部记录保留', 'All records retained')}</span></summary><div class="inv-history-list">${outcomes
                        .slice(1)
                        .map((r, i) =>
                          runPanel(
                            r,
                            T(
                              '重测 ' + (outcomes.length - i - 1),
                              'Rerun ' + (outcomes.length - i - 1),
                            ),
                            md,
                            canCite,
                            block.id + ':history',
                            viewState,
                          ),
                        )
                        .join('')}</div></details>`
                    : ''
                }`
              : ''
          }`;
        }
        return `<section class="investigation-block inv-block-${esc(block.type)}" data-investigation-block="${esc(block.id)}"><header class="inv-block-head"><span class="inv-number">${String(index + 1).padStart(2, '0')}</span><h3>${esc(blockTitle(block))}</h3><span class="spacer"></span>${mutable ? `<div class="inv-order"><button type="button" class="btn icon quiet small" data-action="investigation-move" data-id="${esc(block.id)}" data-dir="-1" aria-label="${esc(T('模块 ' + (index + 1) + ' 上移', 'Move module ' + (index + 1) + ' up'))}" title="${esc(T('上移', 'Move up'))}" ${index === 0 ? 'disabled' : ''}>${icon('back', 'i-xs')}</button><button type="button" class="btn icon quiet small" data-action="investigation-move" data-id="${esc(block.id)}" data-dir="1" aria-label="${esc(T('模块 ' + (index + 1) + ' 下移', 'Move module ' + (index + 1) + ' down'))}" title="${esc(T('下移', 'Move down'))}" ${index === work.blocks.length - 1 ? 'disabled' : ''}>${icon('chev', 'i-xs')}</button></div>` : ''}</header>${content}</section>`;
      })
      .join('')}${reviewPanel(work, mutable)}</div>
    <footer class="investigation-foot"><span>${T('证据来自真实记录；结论由你核对。', 'Evidence comes from actual records. You review the conclusions.')}</span>${button(agentMark('xs') + T('交给我的 Agent 重组', 'Let my agent reorganize'), 'agent')}</footer></article></div>`;
}
