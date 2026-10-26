/** Recorded technical details; probability tables use neutral ink regardless of the winning class. */
import type { ChainUnit, PreviewRecognition } from './chain';
import type { RecognitionRecord } from './badge';
import type { Language } from '../results-native/localization';
import { escapeCheck as esc } from './record-inspector';
import { checkPresentation, leadingProbability, relationLabels } from './check-presentation';
import './judgment-chain.css';
export { leadingProbability } from './check-presentation';
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const number = (n: number) =>
  `<span class="jc-number" data-value="${n}" title="${n}">${n.toFixed(3)}</span>`;
export function judgmentChainHtml(
  unit: ChainUnit,
  preview: PreviewRecognition,
  language: Language,
) {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const p = checkPresentation(unit, preview, language),
    b = unit.branches;
  const names: Record<string, string> = {
    supported: t('支持', 'Supported'),
    contradicted: t('矛盾', 'Contradicted'),
    insufficient: t('依据不足', 'Insufficient evidence'),
  };
  const rows: [string, string, Record<string, number> | null | undefined][] = [
    ['encoder', 'XLM-R', p.ruleOnly ? null : b?.encoder],
    ['stack', t('堆叠集成', 'Stacked ensemble'), p.ruleOnly ? null : b?.stack],
    ['rule', t('数字规则', 'Number rule'), b?.rule],
    ['fusion', t('最终分布', 'Final distribution'), unit.probabilities],
  ];
  const alpha = finite(b?.alpha) && b.alpha >= 0 && b.alpha <= 1 ? b.alpha : null;
  const model = p.ruleOnly ? null : p.model,
    rule = p.rule;
  const routes =
    model || rule
      ? `<div class="jc-routes" data-paths="${model && rule ? 2 : 1}"><div class="jc-route-inputs">${model ? `<div class="jc-route"><b>${t('内容理解', 'Meaning check')}</b><small>${leadingProbability(b?.encoder) ? 'XLM-R' : ''}${leadingProbability(b?.stack) ? t(' → 堆叠集成', ' → Stacking') : ''}${rule && alpha !== null ? ` · ${Number((alpha * 100).toFixed(1))}% (α = ${alpha})` : ''}</small></div>` : ''}${rule ? `<div class="jc-route"><b>${t('数字与限制', 'Numbers and limits')}</b><small>${t('规则核对', 'Rule check')}${model && alpha !== null ? ` · ${Number(((1 - alpha) * 100).toFixed(1))}%` : ''}${finite(b?.rule_window) ? t(` · 窗口 ${b.rule_window} 段`, ` · window: ${b.rule_window} passages`) : ''}</small></div>` : ''}</div><span class="jc-merge" aria-hidden="true"><i></i><i></i></span><div class="jc-route-final"><b>${model && rule ? t('合并后的倾向', 'Result after fusion') : t('本次最终分布', 'Recorded final distribution')}</b><small>${
          leadingProbability(unit.probabilities)
            ?.labels.map((k) => names[k])
            .join(' / ') ?? t('分布未完整记录', 'Distribution incomplete')
        }</small></div></div>`
      : '';
  const hits = (unit.top ?? []).filter((h) => typeof h.quote === 'string');
  const candidates = `<details class="jc-hits"><summary>${t('取回候选原文', 'Retrieved passages')} · ${hits.length}</summary><p>${esc(unit.retrieval_method && ['rrf', 'bm25', 'dense'].includes(unit.retrieval_method) ? { rrf: 'RRF', bm25: 'BM25', dense: 'e5' }[unit.retrieval_method] : t('检索方法未记录', 'Retrieval method not recorded'))}</p>${unit.evidence ? `<p>${t('本次选中的原文', 'Passage selected for this check')}</p><blockquote>${esc(unit.evidence)}</blockquote>` : `<p>${t('选中的原文未记录', 'The selected passage was not saved')}</p>`}${hits
    .map(
      (h) =>
        `<blockquote>${esc(h.quote)}</blockquote><p>${[
          ['BM25', h.bm25],
          [t('向量相似度', 'Dense similarity'), h.dense],
          [
            t('原文匹配分', 'Pair score'),
            typeof h.evidence_id === 'string' ? b?.pairs?.[h.evidence_id] : undefined,
          ],
        ]
          .filter(([, n]) => finite(n))
          .map(([s, n]) => `${s} ${number(n as number)}`)
          .join(' · ')}</p>`,
    )
    .join('')}</details>`;
  const table = `<table class="jc-table"><caption>${t('本次记录的分布', 'Recorded distributions')}</caption><thead><tr><th>${t('检查', 'Check')}</th>${relationLabels.map((k) => `<th>${names[k]}</th>`).join('')}</tr></thead><tbody>${rows
    .filter(([, , v]) => v != null)
    .map(
      ([key, name, v]) =>
        `<tr data-step="${key}"><th scope="row">${name}</th>${relationLabels.map((k) => `<td data-label="${names[k]}">${finite(v?.[k]) ? number(v?.[k] as number) : '—'}</td>`).join('')}</tr>`,
    )
    .join('')}</tbody></table>`;
  const expected = unit.expected_cost,
    defer = preview.defer_cost,
    complete = finite(expected) && finite(defer);
  const costs = complete
    ? `<div class="jc-cost-row"><div><small>${t('自动判定的预期代价', 'Expected cost of deciding')}</small><strong>${number(expected)}</strong></div><span aria-label="${expected > defer ? t('高于', 'greater than') : expected < defer ? t('低于', 'less than') : t('等于', 'equal to')}">${expected > defer ? '&gt;' : expected < defer ? '&lt;' : '='}</span><div><small>${t('暂缓核验的代价', 'Cost of deferring')}</small><strong>${number(defer)}</strong></div></div>`
    : `<p>${t('代价记录不完整', 'Cost details are incomplete')}</p>`;
  const mismatch =
    complete &&
    ((unit.decision === 'defer' && expected < defer) ||
      (unit.decision === 'decide' && expected > defer));
  return `<section class="judgment-chain"><p class="jc-explanation">${p.relation} · ${p.status}</p>${routes}${table}${!leadingProbability(b?.stack) ? `<p>${t('未记录堆叠结果', 'No stacking result was recorded')}</p>` : ''}${b?.rule === null ? `<p>${t('这次没有可比较的数字', 'No comparable numbers were found')}</p>` : ''}${p.agreement === 'incomplete' ? `<p>${t('分支记录不完整，原始读数保留如下。', 'Branch details are incomplete; recorded values are retained.')}</p>` : ''}${candidates}<section class="jc-decision" data-step="decision">${costs}<p><b>${unit.decision === 'defer' ? t('记录决定：暂缓', 'Recorded decision: defer') : unit.decision === 'decide' ? t('记录决定：判定', 'Recorded decision: decide') : t('最终决定未记录', 'No final decision was recorded')}</b>${mismatch ? ` · ${t('代价记录需核对', 'Cost details need checking')}` : ''}</p></section><p class="jc-note">${t('代价是决策尺度，不是金额或正确率。这张图解释检查过程，不证明判断一定正确。', 'Cost is a decision measure, not money or accuracy. This view explains the check; it does not establish that the result is correct.')}</p></section>`;
}
export function renderJudgmentChain(
  doc: Document,
  unit: ChainUnit,
  preview: PreviewRecognition,
  language: Language,
) {
  const host = doc.createElement('div');
  host.innerHTML = judgmentChainHtml(unit, preview, language);
  return host;
}

/** Join only the records on this feedback, by the sentence's explicit index. */
export function recordedSentencePreview(records: RecognitionRecord[]): PreviewRecognition | null {
  const relation = records.find((r) => r.task === 'relation' && Array.isArray(r.outputs?.units));
  if (!relation) return null;
  const retrieval = records.find(
    (r) => r.task === 'retrieval' && Array.isArray(r.outputs?.per_sentence_top),
  );
  const rows = (retrieval?.outputs?.per_sentence_top ?? []) as {
    index: number;
    top?: Record<string, unknown>[];
  }[];
  const decision = records.find((r) => r.task === 'decision');
  const defer = (decision?.outputs?.costs as { defer?: number })?.defer;
  return {
    recognizer: `${relation.recognizer_id}@${relation.revision}`,
    fallback: relation.fallback,
    origin: 'delivery',
    defer_cost: defer,
    units: ((relation.outputs?.units ?? []) as ChainUnit[]).map((unit) => {
      const top = rows.find((row) => row.index === unit.index)?.top ?? unit.top;
      const cited = top?.find(
        (hit) =>
          typeof hit.evidence_id === 'string' && unit.evidence_ids?.includes(hit.evidence_id),
      );
      return {
        ...unit,
        top,
        evidence: unit.evidence ?? (typeof cited?.quote === 'string' ? cited.quote : undefined),
        ...(typeof retrieval?.outputs?.method === 'string'
          ? { retrieval_method: retrieval.outputs.method }
          : {}),
      };
    }),
  };
}
