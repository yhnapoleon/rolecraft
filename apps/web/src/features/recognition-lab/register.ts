/** The recogniser register (middle of #/lab): what each recogniser recognises, how, its
 * course family, what it feeds, and one or two figures from the published results. */
import type { Language } from '../results-native/localization';
import { COPY, type Key } from './copy';
import type { Results } from './data';
import { type Figure, f2, f3, fill, int, pct, pct0, ref } from './figures';
import { esc, rich } from './html';

interface Metric {
  text: Key;
  set: Key;
  figures: Record<string, Figure>;
  setFigures?: Record<string, Figure>;
}
export interface Row {
  id: string;
  name: Key;
  what: Key;
  method: Key;
  chain?: Key;
  cats: Key[];
  extraCat?: Key;
  used: Key;
  primary?: boolean;
  steps?: { label: Key; zh: Figure; en: Figure }[];
  metrics: Metric[];
  /** Every figure of the row, for checks. */
  figures: Record<string, Figure>;
}

function row(r: Omit<Row, 'figures'>): Row {
  const figures: Record<string, Figure> = {};
  r.metrics.forEach((m, i) => {
    for (const [k, f] of Object.entries({ ...m.figures, ...m.setFigures }))
      figures[`${i}.${k}`] = f;
  });
  r.steps?.forEach((s, i) => {
    figures[`step${i}.zh`] = s.zh;
    figures[`step${i}.en`] = s.en;
  });
  return { ...r, figures };
}

const E1S = 'stack_rule_alpha0.4';
const stack = (variant: string, lang: string) =>
  f3(ref('e1_stack', 'test', variant, lang, 'macro_f1'));

export const REGISTER: Row[] = [
  row({
    id: 'c1',
    primary: true,
    name: 'c1_name',
    what: 'c1_what',
    method: 'c1_method',
    chain: 'c1_chain',
    cats: ['cat_c1', 'cat_chain'],
    used: 'c1_used',
    steps: [
      { label: 'c1_step_xlmr', zh: stack('c1', 'zh'), en: stack('c1', 'en') },
      { label: 'c1_step_stack', zh: stack('stack', 'zh'), en: stack('stack', 'en') },
      { label: 'c1_step_chain', zh: stack(E1S, 'zh'), en: stack(E1S, 'en') },
    ],
    metrics: [
      { text: 'c1_m', set: 'c1_set', figures: { zh: stack(E1S, 'zh'), en: stack(E1S, 'en') } },
    ],
  }),
  row({
    id: 'c2',
    name: 'c2_name',
    what: 'c2_what',
    method: 'c2_method',
    cats: ['cat_c2'],
    used: 'c2_used',
    metrics: [
      {
        text: 'c2_m1',
        set: 'c2_set1',
        figures: {
          zh: f3(ref('e3_retrieval', 'relation', 'zh', 'rrf', 'recall@5')),
          en: f3(ref('e3_retrieval', 'relation', 'en', 'rrf', 'recall@5')),
        },
      },
      {
        text: 'c2_m2',
        set: 'c2_set2',
        figures: {
          dzh: f2(ref('e3_retrieval', 'assistant', 'zh/in_paraphrase', 'dense', 'recall@5')),
          den: f2(ref('e3_retrieval', 'assistant', 'en/in_paraphrase', 'dense', 'recall@5')),
          rzh: f2(ref('e3_retrieval', 'assistant', 'zh/in_paraphrase', 'rrf', 'recall@5')),
          ren: f2(ref('e3_retrieval', 'assistant', 'en/in_paraphrase', 'rrf', 'recall@5')),
        },
      },
    ],
  }),
  row({
    id: 'c4',
    name: 'c4_name',
    what: 'c4_what',
    method: 'c4_method',
    cats: ['cat_c4'],
    used: 'c4_used',
    metrics: [
      {
        text: 'c4_m1',
        set: 'c4_set1',
        figures: {
          zh: f3(ref('e5_scope', 'baselines', 'zh', 'mahalanobis', 'auroc')),
          en: f3(ref('e5_scope', 'baselines', 'en', 'mahalanobis', 'auroc')),
        },
      },
      {
        text: 'c4_m2',
        set: 'c4_set2',
        figures: {
          zh: f3(ref('e13_scope', 'massive/zh', 'methods', 'mahalanobis', 'all_out', 'auroc')),
          en: f3(ref('e13_scope', 'massive/en', 'methods', 'mahalanobis', 'all_out', 'auroc')),
        },
      },
    ],
  }),
  row({
    id: 'c5',
    name: 'c5_name',
    what: 'c5_what',
    method: 'c5_method',
    cats: ['cat_c5'],
    extraCat: 'cat_c5_extra',
    used: 'c5_used',
    metrics: [
      {
        text: 'c5_m1',
        set: 'c5_set',
        figures: { v: f2(ref('e6_behavior', 'strategy_robustness', '0.5', 'dtw_1nn')) },
        setFigures: { n: int(ref('e6_behavior', 'n_test')) },
      },
      {
        text: 'c5_m2',
        set: 'c5_set',
        figures: { v: f2(ref('e6_behavior', 'anomaly', 'hmm_loglik', 'auroc')) },
        setFigures: { n: int(ref('e6_behavior', 'n_test')) },
      },
    ],
  }),
  row({
    id: 'c10',
    name: 'c10_name',
    what: 'c10_what',
    method: 'c10_method',
    cats: ['cat_c10'],
    used: 'c10_used',
    metrics: [
      {
        text: 'c10_m1',
        set: 'c10_set1',
        figures: {
          v: f3(ref('e13_reply', 'datasets', 'synth', 'product', 'three_class', 'macro_f1')),
        },
      },
      {
        text: 'c10_m2',
        set: 'c10_set1',
        figures: {
          v: f3(ref('e13_reply', 'datasets', 'ragtruth', 'product', 'three_class', 'macro_f1')),
        },
      },
    ],
  }),
  row({
    id: 'c11',
    name: 'c11_name',
    what: 'c11_what',
    method: 'c11_method',
    cats: ['cat_c11'],
    used: 'c11_used',
    metrics: [
      {
        text: 'c11_m1',
        set: 'c11_set',
        figures: {
          zh: f3(ref('e7_intent', 'models', 'tfidf_lr', 'zh', 'accuracy')),
          en: f3(ref('e7_intent', 'models', 'tfidf_lr', 'en', 'accuracy')),
        },
      },
      {
        text: 'c11_m2',
        set: 'c11_set',
        figures: {
          zh: f3(ref('e7_intent', 'models', 'keyword_rule', 'zh', 'accuracy')),
          en: f3(ref('e7_intent', 'models', 'keyword_rule', 'en', 'accuracy')),
        },
      },
    ],
  }),
  row({
    id: 'c6',
    name: 'c6_name',
    what: 'c6_what',
    method: 'c6_method',
    cats: ['cat_c6'],
    used: 'c6_used',
    metrics: [
      {
        text: 'c6_m1',
        set: 'c6_set1',
        figures: {
          r: pct0(ref('e1_stack', 'test', E1S, 'error_reject', 2, 'reject_rate')),
          before: pct(ref('e1_stack', 'test', E1S, 'error_reject', 0, 'wrong_deduction_rate')),
          after: pct(ref('e1_stack', 'test', E1S, 'error_reject', 2, 'wrong_deduction_rate')),
        },
      },
      {
        text: 'c6_m2',
        set: 'c6_set2',
        figures: {
          v: f2(ref('e8_judge', 'arbiter', 'conflict_rate')),
          k: int(ref('e8_judge', 'arbiter', 'judge_decided')),
          n: int(ref('e8_judge', 'arbiter', 'records')),
        },
      },
    ],
  }),
];

export function registerHtml(results: Results, language: Language) {
  const t = (k: Key) => esc(COPY[language][k]);
  const families = (
    [
      ['cov_supervised', 'cov_supervised_items'],
      ['cov_mldl', 'cov_mldl_items'],
      ['cov_hybrid', 'cov_hybrid_items'],
      ['cov_sensing', 'cov_sensing_items'],
    ] as const
  )
    .map(([head, items]) => `<div><dt>${t(head)}</dt><dd>${t(items)}</dd></div>`)
    .join('');
  const rows = REGISTER.map((r) => {
    const cats = [
      ...r.cats.map((c) => `<span class="rc-family">${t(c)}</span>`),
      r.extraCat ? `<span class="rc-family" data-extra>${t(r.extraCat)}</span>` : '',
    ].join('');
    const metrics = r.metrics
      .map((m) => {
        const values = fill(results, m.figures);
        const setValues = fill(results, m.setFigures ?? {}) ?? {};
        if (!values) return '';
        const [label, figures] = COPY[language][m.text].split('|');
        return `<li><span class="rc-metric-label">${rich(label, values)}</span><span class="rc-metric-text">${rich(figures ?? '', values)}</span><span class="rc-metric-set">${esc(COPY[language][m.set].replace(/\{(\w+)\}/g, (_, n: string) => setValues[n] ?? ''))}</span></li>`;
      })
      .filter(Boolean)
      .join('');
    const steps = r.steps
      ? `<ol class="rc-chainsteps" aria-label="${t('c1_chain')}">${r.steps
          .map((s, i) => {
            const v = fill(results, { zh: s.zh, en: s.en });
            const cls = i === (r.steps?.length ?? 0) - 1 ? 'rc-lab-num' : 'rc-num-soft';
            return `<li><span class="rc-chainstep-name">${t(s.label)}</span><span class="rc-chainstep-val">${v ? `<b class="${cls}">${esc(v.zh)}</b> / <b class="${cls}">${esc(v.en)}</b>` : '–'}</span></li>`;
          })
          .join('')}</ol>`
      : '';
    return `<li class="rc-rec"${r.primary ? ' data-primary' : ''} id="rc-${r.id}">
      <div class="rc-rec-name"><h3 class="rc-rec-title">${t(r.name)}</h3><p class="rc-families" aria-label="${t('catLabel')}">${cats}</p></div>
      <div class="rc-rec-body"><p class="rc-rec-what">${t(r.what)}</p>
        <dl class="rc-rec-facts"><div><dt>${t('f_method')}</dt><dd>${t(r.method)}${r.chain ? `<br><span class="rc-rec-chain">${t(r.chain)}</span>` : ''}</dd></div><div><dt>${t('f_used')}</dt><dd>${t(r.used)}</dd></div></dl>
        ${steps}</div>
      <div class="rc-rec-metrics"><h4 class="sr-only">${t('f_metric')}</h4><ul>${metrics}</ul></div>
    </li>`;
  }).join('');
  return `<div class="rc-families-index"><p class="rc-index-title" id="rc-families-title">${t('covTitle')}</p><dl aria-labelledby="rc-families-title">${families}</dl></div><ol class="rc-register">${rows}</ol>`;
}
