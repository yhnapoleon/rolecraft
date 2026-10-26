/** Normal-view explanation of one recorded decision. No inference, re-scoring or new calls. */
import type { ChainUnit, PreviewRecognition } from './chain';
import type { RecognitionRecord } from './badge';
import type { Language } from '../results-native/localization';
import { escapeMoment as esc } from './signature';
import 'number-flow';
import './judgment-chain.css';

const labels = ['supported', 'contradicted', 'insufficient'] as const;
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
export function leadingProbability(p?: Record<string, number> | null) {
  if (!p) return null;
  const entries = labels.filter((k) => finite(p[k]) && p[k] >= 0 && p[k] <= 1);
  if (!entries.length) return null;
  const value = Math.max(...entries.map((k) => p[k]));
  return { labels: entries.filter((k) => p[k] === value), value };
}
const number = (value: number) =>
  `<span class="jc-number" data-value="${value}">${value.toFixed(3)}</span>`;

export function judgmentChainHtml(
  unit: ChainUnit,
  preview: Pick<PreviewRecognition, 'defer_cost'>,
  language: Language,
) {
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const names: Record<string, string> = {
    supported: t('支持', 'Supported'),
    contradicted: t('矛盾', 'Contradicted'),
    insufficient: t('依据不足', 'Insufficient evidence'),
  };
  const b = unit.branches;
  const nodes: string[] = [];
  const node = (key: string, title: string, method: string, content: string, tone = '') => {
    nodes.push(
      `<li class="jc-step" data-step="${key}" data-tone="${esc(tone)}" style="--jc-order:${nodes.length}"><span class="jc-dot" aria-hidden="true">${String(nodes.length + 1).padStart(2, '0')}</span><h5>${title}</h5><small>${method}</small>${content}</li>`,
    );
  };
  const verdict = (p?: Record<string, number> | null) => {
    const top = leadingProbability(p);
    return top
      ? `<p class="jc-verdict">${top.labels.map((k) => names[k]).join(t('／', ' / '))} ${number(top.value)}</p>`
      : '';
  };
  const tone = (p?: Record<string, number> | null) => {
    const top = leadingProbability(p);
    return top?.labels.length === 1 ? top.labels[0] : '';
  };
  const top = unit.top ?? [];
  const methods: Record<string, string> = {
    bm25: 'BM25',
    dense: 'e5',
    rrf: t('RRF 融合', 'RRF fusion'),
  };
  const hits = top.filter((hit) => typeof hit.quote === 'string' && hit.quote);
  if (hits.length || unit.evidence)
    node(
      'retrieval',
      t('找可用的依据', 'Find relevant evidence'),
      methods[unit.retrieval_method ?? ''] ?? t('检索方法未记录', 'Retrieval method not recorded'),
      hits.length
        ? `<blockquote class="jc-candidate">${esc(String(hits[0].quote))}</blockquote><details class="jc-hits"><summary>${t(`${hits.length} 段候选原文`, `${hits.length} candidate ${hits.length === 1 ? 'passage' : 'passages'}`)}</summary>${hits
            .map(
              (hit) =>
                `<blockquote>${esc(String(hit.quote))}</blockquote><p class="jc-source-scores">${[
                  ['BM25', hit.bm25],
                  [t('向量相似度', 'Dense similarity'), hit.dense],
                  [t('原文匹配分', 'Pair score'), b?.pairs?.[String(hit.evidence_id ?? '')]],
                ]
                  .filter(([, n]) => finite(n))
                  .map(([label, n]) => `${label} ${number(n as number)}`)
                  .join(' · ')}</p>`,
            )
            .join('')}</details>`
        : `<blockquote>${esc(unit.evidence ?? '')}</blockquote>`,
    );
  if (leadingProbability(b?.encoder))
    node(
      'encoder',
      t('读懂两句话的关系', 'Read the relationship'),
      'XLM-R',
      verdict(b?.encoder),
      tone(b?.encoder),
    );
  if (leadingProbability(b?.stack))
    node(
      'stack',
      t('让多个模型复核', 'Cross-check with multiple models'),
      t('堆叠集成', 'Stacked ensemble'),
      verdict(b?.stack),
      tone(b?.stack),
    );
  if (leadingProbability(b?.rule))
    node(
      'rule',
      t('核对数字与限制', 'Check numbers and limits'),
      t('规则核对', 'Rule check'),
      verdict(b?.rule) +
        (finite(b?.rule_window)
          ? `<p>${t(`核对窗口：${b.rule_window} 段`, `Check window: ${b.rule_window} passages`)}</p>`
          : ''),
      tone(b?.rule),
    );
  else if (b && Object.hasOwn(b, 'rule') && b.rule === null)
    node(
      'rule',
      t('核对数字与限制', 'Check numbers and limits'),
      t('规则未介入', 'Rule did not intervene'),
      `<p>${t('未找到可比的数字。', 'No comparable numbers were found.')}</p>`,
    );
  if (leadingProbability(unit.probabilities))
    node(
      'fusion',
      t('合在一起看', 'Bring the evidence together'),
      finite(b?.alpha) && leadingProbability(b?.rule)
        ? `${t('模型权重', 'Model weight')} α = ${b.alpha}`
        : t('本次最终分布', 'Recorded final distribution'),
      `<dl class="jc-distribution">${labels
        .filter((k) => finite(unit.probabilities?.[k]))
        .map(
          (k) =>
            `<div data-tone="${k}"><dt>${names[k]}</dt><dd>${number((unit.probabilities as Record<string, number>)[k])}</dd></div>`,
        )
        .join('')}</dl>`,
      unit.label,
    );
  const expected = unit.expected_cost,
    defer = preview.defer_cost;
  const costs =
    finite(expected) && finite(defer)
      ? `<p class="jc-cost" aria-label="${t(`自动判定代价 ${expected}，暂缓代价 ${defer}`, `Automatic judgement cost ${expected}; deferral cost ${defer}`)}">${number(expected)} <span aria-hidden="true">${expected < defer ? '&lt;' : expected === defer ? '=' : '&gt;'}</span><span class="sr-only">${expected < defer ? t('低于', 'less than') : expected === defer ? t('等于', 'equal to') : t('高于', 'greater than')}</span> ${number(defer)}</p><p>${t('自动判定代价 / 暂缓代价', 'Automatic judgement cost / deferral cost')}</p>`
      : `<p>${t('本次代价记录不完整。', 'The cost record is incomplete.')}</p>`;
  const decision =
    unit.decision === 'defer'
      ? t('先暂缓，请人核验', 'Defer for a human check')
      : unit.decision === 'decide'
        ? t('可以给出判断', 'Make a judgement')
        : t('未记录决策', 'Decision not recorded');
  node(
    'decision',
    decision,
    t('代价敏感决策 · C6', 'Cost-sensitive decision · C6'),
    costs,
    unit.decision === 'defer' ? 'insufficient' : unit.label,
  );
  const model = leadingProbability(b?.stack) ?? leadingProbability(b?.encoder),
    rule = leadingProbability(b?.rule);
  const disagreement = model && rule && model.labels.join() !== rule.labels.join();
  const modelName = leadingProbability(b?.stack) ? t('堆叠模型', 'stacked model') : 'XLM-R';
  const explanation = disagreement
    ? t(
        `${modelName}倾向${model.labels.map((k) => names[k]).join('／')}（${model.value.toFixed(3)}），规则倾向${rule.labels.map((k) => names[k]).join('／')}（${rule.value.toFixed(3)}）。`,
        `The ${modelName} favours ${model.labels.map((k) => names[k].toLowerCase()).join(' / ')} (${model.value.toFixed(3)}); the rule favours ${rule.labels.map((k) => names[k].toLowerCase()).join(' / ')} (${rule.value.toFixed(3)}).`,
      ) +
      (finite(b?.alpha)
        ? t(
            `按记录的 α=${b.alpha} 融合后，关系倾向${names[unit.label] ?? unit.label}。`,
            ` With the recorded α=${b.alpha}, the fused relation favours ${names[unit.label]?.toLowerCase() ?? unit.label}.`,
          )
        : '')
    : '';
  const notes = [
    !leadingProbability(b?.stack)
      ? t('本句未经堆叠复核。', 'This sentence was not checked by a stacked ensemble.')
      : '',
    !b ? t('此记录未附各分支数值。', 'Branch scores were not attached to this record.') : '',
  ].filter(Boolean);
  return `<rc-judgment-chain class="judgment-chain" role="region" aria-label="${t('这句是怎样判断的', 'How this sentence was judged')}"><header><h4>${t('这句是怎样判断的', 'How this sentence was judged')}</h4><span>${t('本次识别记录', 'This recognition record')}</span></header>${explanation ? `<p class="jc-explanation">${esc(explanation)}</p>` : ''}<ol class="jc-track" style="--jc-count:${nodes.length}">${nodes.join('')}</ol>${notes.map((n) => `<p class="jc-note">${n}</p>`).join('')}</rc-judgment-chain>`;
}
export function renderJudgmentChain(
  doc: Document,
  unit: ChainUnit,
  preview: Pick<PreviewRecognition, 'defer_cost'>,
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
      const cited = top?.find(hit => hit.evidence_id === unit.evidence_ids?.[0]);
      return {
        ...unit, top,
        evidence: unit.evidence ?? (typeof cited?.quote === 'string' ? cited.quote : undefined),
        ...(typeof retrieval?.outputs?.method === 'string' ? {retrieval_method: retrieval.outputs.method} : {}),
      };
    }),
  };
}

// The custom element upgrades both string-template and DOM-rendered hosts identically.
if (typeof customElements !== 'undefined' && !customElements.get('rc-judgment-chain')) {
  customElements.define(
    'rc-judgment-chain',
    class extends HTMLElement {
      observer?: IntersectionObserver;
      connectedCallback() {
        if (this.dataset.played) return;
        const show = () => {
          this.dataset.played = 'true';
          const reduced = this.ownerDocument.defaultView?.matchMedia(
            '(prefers-reduced-motion: reduce)',
          ).matches;
          if (!reduced) this.classList.add('jc-enter');
          for (const span of this.querySelectorAll<HTMLElement>('.jc-number')) {
            const value = Number(span.dataset.value);
            const flow = this.ownerDocument.createElement('number-flow') as HTMLElement & {
              update?: (v: number) => void;
              format: Intl.NumberFormatOptions;
              transformTiming: { duration: number };
              spinTiming: { duration: number };
            };
            if (!flow.update) continue;
            flow.setAttribute('aria-hidden', 'true');
            flow.format = { minimumFractionDigits: 3, maximumFractionDigits: 3 };
            flow.transformTiming = flow.spinTiming = { duration: 520 };
            flow.update(reduced ? value : 0);
            const spoken = this.ownerDocument.createElement('span');
            spoken.className = 'sr-only';
            spoken.textContent = value.toFixed(3);
            span.replaceChildren(spoken, flow);
            if (!reduced) requestAnimationFrame(() => flow.update?.(value));
          }
          this.observer?.disconnect();
        };
        if (typeof IntersectionObserver === 'undefined') show();
        else {
          this.observer = new IntersectionObserver((entries) => {
            if (entries.some((e) => e.isIntersecting)) show();
          });
          this.observer.observe(this);
        }
      }
      disconnectedCallback() {
        this.observer?.disconnect();
      }
    },
  );
}
