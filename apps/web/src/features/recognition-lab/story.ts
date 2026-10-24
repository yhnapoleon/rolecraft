/** The experiment story (bottom of #/lab): E1–E10 on our own data, then the real-data line
 * E11 → E14 → E15 with E12 and E13 as side branches. Every figure in the copy is filled
 * from a published result field (figures.ts); every chart has a name and a table view. */
import type { Language } from '../results-native/localization';
import { groupedBars, heatmap, lines, scatter } from './charts';
import type { Results } from './data';
import { type Figure, f2, f3, fill, fraction, pct, ref, value } from './figures';
import { STORY_COPY, st, type StoryKey } from './story-copy';
import { esc, rich } from './html';

type Ctx = { r: Results; l: Language; width: number };
type Chart = (ctx: Ctx) => string | null;
export interface Entry {
  id: string;
  tag?: 'mainline' | 'branch';
  offline?: boolean;
  figures: Record<string, Figure>;
  charts: Chart[];
}

const E1S = 'stack_rule_alpha0.4';
const REAL = ['relation-v3', 'public-synth', 'contractnli', 'vitaminc', 'cfever'] as const;
const REAL_NAMES: Record<string, [string, string]> = {
  'relation-v3': ['relation-v3（自建）', 'relation-v3 (ours)'],
  'public-synth': ['public-synth', 'public-synth'],
  contractnli: ['ContractNLI', 'ContractNLI'],
  vitaminc: ['VitaminC', 'VitaminC'],
  cfever: ['CFEVER', 'CFEVER'],
};
const realName = (l: Language, key: string) => (REAL_NAMES[key] ?? [key, key])[l === 'zh' ? 0 : 1];
const MODEL_NAMES: Record<string, [string, string]> = {
  naive_bayes: ['朴素贝叶斯', 'naive Bayes'],
  knn_k3: ['kNN（k=3）', 'kNN (k=3)'],
  decision_tree_d8: ['决策树', 'decision tree'],
  svm_rbf: ['SVM（RBF）', 'SVM (RBF)'],
  logistic_regression: ['逻辑回归', 'logistic regression'],
  mlp: ['MLP', 'MLP'],
  bagging_lr: ['Bagging（LR）', 'bagging (LR)'],
  adaboost_trees: ['AdaBoost', 'AdaBoost'],
  random_forest: ['随机森林', 'random forest'],
  lr_tfidf_plus_features: ['LR + 人工特征', 'LR + features'],
  stack_lr_encoder: ['堆叠 LR + XLM-R', 'stack LR + XLM-R'],
  'fusion_alpha0.6': ['概率融合 α=0.6', 'probability fusion α=0.6'],
  encoder_c1: ['XLM-R', 'XLM-R'],
};
const PHENOMENA: Record<string, [string, string]> = {
  negation: ['否定', 'negation'],
  unfounded_inference: ['无据推断', 'unfounded inference'],
  paraphrase: ['换说法', 'paraphrase'],
  direct: ['直述', 'direct'],
  numeric_compare: ['数值比较', 'numeric comparison'],
  number_format: ['数字格式', 'number format'],
  slot_mismatch: ['槽位错配', 'slot mismatch'],
  request_as_approval: ['申请当批准', 'request as approval'],
  old_version: ['引用旧版本', 'old version'],
};
const SCOPE_METHODS: Record<string, [string, string]> = {
  mahalanobis: ['马氏距离（产品）', 'Mahalanobis (product)'],
  max_cosine: ['最近邻余弦', 'nearest-neighbour cosine'],
  kmeans_centroid: ['K-Means 中心距离', 'K-Means centroid'],
  gaussian_nb: ['高斯朴素贝叶斯', 'Gaussian naive Bayes'],
  autoencoder: ['自编码器', 'autoencoder'],
  one_class_svm: ['单类 SVM', 'one-class SVM'],
  isolation_forest: ['Isolation Forest', 'isolation forest'],
};
const RELATION_ROWS = {
  zh: ['支持', '矛盾', '证据不足'],
  en: ['supported', 'contradicted', 'insufficient'],
};
const RELATION_COLS = { zh: ['支持', '矛盾', '不足'], en: ['sup.', 'contra.', 'insuff.'] };
const INTENTS: Record<string, [string, string]> = {
  ask_limit: ['问限制', 'limit'],
  ask_resource: ['问资源', 'resources'],
  ask_process: ['问流程', 'process'],
  seek_approval: ['求批准', 'approval'],
  other: ['其他', 'other'],
};
const name2 = (table: Record<string, [string, string]>, l: Language, key: string) =>
  (table[key] ?? [key, key])[l === 'zh' ? 0 : 1];

const has = (r: Results, ...files: string[]) => files.every((f) => r[f] != null);
const opts = (ctx: Ctx, key: StoryKey, extra = {}) => ({
  label: st(ctx.l, key),
  tableCaption: st(ctx.l, 'table'),
  width: ctx.width,
  ...extra,
});
const LANGS = ['zh', 'en'] as const;
const langSeries = (ctx: Ctx, values: (lang: 'zh' | 'en') => number[]) =>
  LANGS.map((lang) => ({ name: st(ctx.l, lang), values: values(lang) }));

export const ENTRIES: { chapter: 1 | 2; entry: Entry }[] = [
  {
    chapter: 1,
    entry: {
      id: 'e1',
      figures: {
        stack_zh: f3(ref('e1_baselines', 'models', 'stack_lr_encoder', 'test', 'zh', 'macro_f1')),
        stack_en: f3(ref('e1_baselines', 'models', 'stack_lr_encoder', 'test', 'en', 'macro_f1')),
        c1_zh: f3(ref('e1_baselines', 'models', 'encoder_c1', 'test', 'zh', 'macro_f1')),
        c1_en: f3(ref('e1_baselines', 'models', 'encoder_c1', 'test', 'en', 'macro_f1')),
        lr_zh: f3(
          ref('e1_baselines', 'models', 'lr_tfidf_plus_features', 'test', 'zh', 'macro_f1'),
        ),
        lr_en: f3(
          ref('e1_baselines', 'models', 'lr_tfidf_plus_features', 'test', 'en', 'macro_f1'),
        ),
      },
      charts: [
        (ctx) => {
          if (!has(ctx.r, 'e1_baselines')) return null;
          const models = Object.keys((ctx.r.e1_baselines as { models: object }).models);
          return groupedBars(
            models.map((m) => name2(MODEL_NAMES, ctx.l, m)),
            langSeries(ctx, (lang) =>
              models.map((m) =>
                value(ctx.r, 'e1_baselines', 'models', m, 'test', lang, 'macro_f1'),
              ),
            ),
            opts(ctx, 'e1_chart', { digits: 3 }),
          );
        },
        (ctx) => {
          const matrix = (
            ctx.r.e1_relation as { test?: { all?: { confusion?: number[][] } } } | null
          )?.test?.all?.confusion;
          return matrix
            ? heatmap(RELATION_ROWS[ctx.l], matrix, {
                ...opts(ctx, 'e1_cm'),
                columns: RELATION_COLS[ctx.l],
                rowLabel: ctx.l === 'zh' ? '真实' : 'gold',
                colLabel: ctx.l === 'zh' ? '预测' : 'predicted',
              })
            : null;
        },
      ],
    },
  },
  {
    chapter: 1,
    entry: {
      id: 'e10',
      figures: {
        rule_all: f3(ref('e10_fusion', 'rule', 'all')),
        c1_old: f3(ref('e10_fusion', 'c1', 'by_phenomenon', 'old_version')),
        rule_old: f3(ref('e10_fusion', 'rule', 'by_phenomenon', 'old_version')),
        c1_all: f3(ref('e1_stack', 'test', 'c1', 'all', 'macro_f1')),
        c1r_all: f3(ref('e1_stack', 'test', 'c1_rule_alpha0.4', 'all', 'macro_f1')),
        st_all: f3(ref('e1_stack', 'test', 'stack', 'all', 'macro_f1')),
        str_all: f3(ref('e1_stack', 'test', E1S, 'all', 'macro_f1')),
      },
      charts: [
        (ctx) => {
          if (!has(ctx.r, 'e1_stack')) return null;
          const variants = ['c1', 'c1_rule_alpha0.4', 'stack', E1S];
          const names =
            ctx.l === 'zh'
              ? ['XLM-R', 'XLM-R + 规则', '堆叠', '堆叠 + 规则（产品）']
              : ['XLM-R', 'XLM-R + rule', 'stack', 'stack + rule (product)'];
          return groupedBars(
            names,
            (['zh', 'en', 'all'] as const).map((lang) => ({
              name: st(ctx.l, lang),
              values: variants.map((v) => value(ctx.r, 'e1_stack', 'test', v, lang, 'macro_f1')),
            })),
            opts(ctx, 'e10_chart', { digits: 3 }),
          );
        },
        (ctx) => {
          const e10 = ctx.r.e10_fusion as { c1?: { by_phenomenon?: object } } | null;
          if (!e10?.c1?.by_phenomenon) return null;
          const phenomena = Object.keys(e10.c1.by_phenomenon);
          const names =
            ctx.l === 'zh' ? ['XLM-R', '规则', '晚期融合'] : ['XLM-R', 'rule', 'late fusion'];
          return groupedBars(
            phenomena.map((p) => name2(PHENOMENA, ctx.l, p)),
            ['c1', 'rule', 'late_fusion'].map((m, i) => ({
              name: names[i],
              values: phenomena.map((p) => value(ctx.r, 'e10_fusion', m, 'by_phenomenon', p)),
            })),
            opts(ctx, 'e10_ph'),
          );
        },
      ],
    },
  },
  {
    chapter: 1,
    entry: {
      id: 'e4',
      figures: {
        ece0: f3(ref('e4_decision', 'test', 'ece_t1')),
        ece1: f3(ref('e4_decision', 'test', 'ece_fitted')),
        wd0: pct(ref('e1_stack', 'test', E1S, 'error_reject', 0, 'wrong_deduction_rate')),
        wd20: pct(ref('e1_stack', 'test', E1S, 'error_reject', 2, 'wrong_deduction_rate')),
      },
      charts: [
        (ctx) => {
          const rows = (
            ctx.r.e4_decision as { test?: { error_reject?: Record<string, number>[] } } | null
          )?.test?.error_reject;
          if (!rows) return null;
          return lines(
            rows.map((row) => row.reject_rate),
            [
              { name: st(ctx.l, 'errorRate'), values: rows.map((row) => row.error_rate) },
              {
                name: st(ctx.l, 'wrongDeduction'),
                values: rows.map((row) => row.wrong_deduction_rate),
              },
            ],
            { ...opts(ctx, 'e4_chart'), xLabel: st(ctx.l, 'rejectRate') },
          );
        },
      ],
    },
  },
  {
    chapter: 1,
    entry: {
      id: 'e3',
      figures: {
        rel_zh: f3(ref('e3_retrieval', 'relation', 'zh', 'rrf', 'recall@5')),
        rel_en: f3(ref('e3_retrieval', 'relation', 'en', 'rrf', 'recall@5')),
        d_zh: f2(ref('e3_retrieval', 'assistant', 'zh/in_paraphrase', 'dense', 'recall@5')),
        d_en: f2(ref('e3_retrieval', 'assistant', 'en/in_paraphrase', 'dense', 'recall@5')),
        r_zh: f2(ref('e3_retrieval', 'assistant', 'zh/in_paraphrase', 'rrf', 'recall@5')),
        r_en: f2(ref('e3_retrieval', 'assistant', 'en/in_paraphrase', 'rrf', 'recall@5')),
        b_zh: f2(ref('e3_retrieval', 'assistant', 'zh/in_paraphrase', 'bm25', 'recall@5')),
        b_en: f2(ref('e3_retrieval', 'assistant', 'en/in_paraphrase', 'bm25', 'recall@5')),
      },
      charts: [
        (ctx) =>
          has(ctx.r, 'e3_retrieval')
            ? groupedBars(
                ['BM25', 'e5', 'RRF'],
                langSeries(ctx, (lang) =>
                  ['bm25', 'dense', 'rrf'].map((m) =>
                    value(
                      ctx.r,
                      'e3_retrieval',
                      'assistant',
                      `${lang}/in_paraphrase`,
                      m,
                      'recall@5',
                    ),
                  ),
                ),
                opts(ctx, 'e3_chart'),
              )
            : null,
      ],
    },
  },
  {
    chapter: 1,
    entry: {
      id: 'e5',
      figures: {
        m_zh: f3(ref('e5_scope', 'baselines', 'zh', 'mahalanobis', 'auroc')),
        m_en: f3(ref('e5_scope', 'baselines', 'en', 'mahalanobis', 'auroc')),
        c_zh: f3(ref('e5_scope', 'baselines', 'zh', 'max_cosine', 'auroc')),
        c_en: f3(ref('e5_scope', 'baselines', 'en', 'max_cosine', 'auroc')),
      },
      charts: [
        (ctx) => {
          const base = (ctx.r.e5_scope as { baselines?: { zh?: object } } | null)?.baselines?.zh;
          if (!base) return null;
          const methods = ['mahalanobis', ...Object.keys(base).filter((m) => m !== 'mahalanobis')];
          return groupedBars(
            methods.map((m) => name2(SCOPE_METHODS, ctx.l, m)),
            langSeries(ctx, (lang) =>
              methods.map((m) => value(ctx.r, 'e5_scope', 'baselines', lang, m, 'auroc')),
            ),
            opts(ctx, 'e5_chart', { min: 0.5, digits: 3 }),
          );
        },
        (ctx) => {
          type Q = { kind: string; xy: [number, number]; text: string; score: number };
          const pca = (
            ctx.r.e5_scope as { pca?: { zh?: { units: number[][]; queries: Q[] } } } | null
          )?.pca?.zh;
          if (!pca) return null;
          const point = (q: Q) => ({
            x: q.xy[0],
            y: q.xy[1],
            label: `${q.text} · ${q.score.toFixed(2)}`,
          });
          return scatter(
            [
              { name: st(ctx.l, 'units'), points: pca.units.map((p) => ({ x: p[0], y: p[1] })) },
              {
                name: st(ctx.l, 'inDomain'),
                points: pca.queries.filter((q) => q.kind.startsWith('in_')).map(point),
              },
              {
                name: st(ctx.l, 'outDomain'),
                points: pca.queries.filter((q) => q.kind.startsWith('out_')).map(point),
              },
            ],
            opts(ctx, 'e5_pca'),
          );
        },
      ],
    },
  },
  {
    chapter: 1,
    entry: {
      id: 'e6',
      figures: {
        ntrain: { refs: [ref('e6_behavior', 'n_train')], show: ([x]) => String(x) },
        ntest: { refs: [ref('e6_behavior', 'n_test')], show: ([x]) => String(x) },
        d0: f2(ref('e6_behavior', 'strategy_robustness', '0.0', 'dtw_1nn')),
        d50: f2(ref('e6_behavior', 'strategy_robustness', '0.5', 'dtw_1nn')),
        rf50: f2(ref('e6_behavior', 'strategy_robustness', '0.5', 'ngram_rf')),
        hmm: f2(ref('e6_behavior', 'anomaly', 'hmm_loglik', 'auroc')),
        dtwa: f2(ref('e6_behavior', 'anomaly', 'dtw_to_regular', 'auroc')),
        iso: f2(ref('e6_behavior', 'anomaly', 'isolation_forest', 'auroc')),
      },
      charts: [
        (ctx) => {
          const rows = (
            ctx.r.e6_behavior as {
              strategy_robustness?: Record<string, Record<string, number>>;
            } | null
          )?.strategy_robustness;
          if (!rows) return null;
          const ps = Object.keys(rows);
          return lines(
            ps.map(Number),
            [
              { name: 'DTW 1-NN', values: ps.map((p) => rows[p].dtw_1nn) },
              {
                name: ctx.l === 'zh' ? 'n-gram 随机森林' : 'n-gram random forest',
                values: ps.map((p) => rows[p].ngram_rf),
              },
            ],
            { ...opts(ctx, 'e6_chart'), xLabel: st(ctx.l, 'noise') },
          );
        },
        (ctx) =>
          has(ctx.r, 'e6_behavior')
            ? groupedBars(
                ctx.l === 'zh'
                  ? ['HMM 似然', 'DTW 距离', 'Isolation Forest']
                  : ['HMM likelihood', 'DTW distance', 'Isolation Forest'],
                [
                  {
                    name: 'AUROC',
                    values: ['hmm_loglik', 'dtw_to_regular', 'isolation_forest'].map((m) =>
                      value(ctx.r, 'e6_behavior', 'anomaly', m, 'auroc'),
                    ),
                  },
                ],
                opts(ctx, 'e6_anom'),
              )
            : null,
      ],
    },
  },
  {
    chapter: 1,
    entry: {
      id: 'e7',
      figures: {
        lr_zh: f3(ref('e7_intent', 'models', 'tfidf_lr', 'zh', 'accuracy')),
        lr_en: f3(ref('e7_intent', 'models', 'tfidf_lr', 'en', 'accuracy')),
        svm_zh: f3(ref('e7_intent', 'models', 'tfidf_svm', 'zh', 'accuracy')),
        svm_en: f3(ref('e7_intent', 'models', 'tfidf_svm', 'en', 'accuracy')),
        kw_zh: f3(ref('e7_intent', 'models', 'keyword_rule', 'zh', 'accuracy')),
        kw_en: f3(ref('e7_intent', 'models', 'keyword_rule', 'en', 'accuracy')),
      },
      charts: [
        (ctx) => {
          if (!has(ctx.r, 'e7_intent')) return null;
          const models = ['tfidf_lr', 'tfidf_svm', 'tfidf_nb', 'keyword_rule'];
          const names =
            ctx.l === 'zh'
              ? ['逻辑回归（产品）', '线性 SVM', '朴素贝叶斯', '关键词规则']
              : ['logistic regression (product)', 'linear SVM', 'naive Bayes', 'keyword rule'];
          return groupedBars(
            names,
            langSeries(ctx, (lang) =>
              models.map((m) => value(ctx.r, 'e7_intent', 'models', m, lang, 'accuracy')),
            ),
            opts(ctx, 'e7_chart', { digits: 3 }),
          );
        },
        (ctx) => {
          const e7 = ctx.r.e7_intent as {
            labels?: string[];
            models?: { tfidf_lr?: { all?: { confusion?: number[][] } } };
          } | null;
          const matrix = e7?.models?.tfidf_lr?.all?.confusion;
          return e7?.labels && matrix
            ? heatmap(
                e7.labels.map((k) => name2(INTENTS, ctx.l, k)),
                matrix,
                {
                  ...opts(ctx, 'e7_cm'),
                  rowLabel: ctx.l === 'zh' ? '真实' : 'gold',
                  colLabel: ctx.l === 'zh' ? '预测' : 'predicted',
                },
              )
            : null;
        },
      ],
    },
  },
  {
    chapter: 1,
    entry: {
      id: 'e8',
      figures: {
        pairs: { refs: [ref('e8_judge', 'pairs')], show: ([x]) => String(x) },
        on: pct(ref('e8_judge', 'by_condition', 'on', 'labelled_rate')),
        off: pct(ref('e8_judge', 'by_condition', 'off', 'labelled_rate')),
        agree: f2(ref('e8_judge', 'agreement', 'label_agreement')),
        conflict: f2(ref('e8_judge', 'arbiter', 'conflict_rate')),
      },
      charts: [
        (ctx) =>
          has(ctx.r, 'e8_judge')
            ? groupedBars(
                [st(ctx.l, 'labelled'), st(ctx.l, 'pending')],
                (['on', 'off'] as const).map((c) => ({
                  name: st(ctx.l, c === 'on' ? 'recOn' : 'recOff'),
                  values: ['labelled_rate', 'pending_rate'].map((m) =>
                    value(ctx.r, 'e8_judge', 'by_condition', c, m),
                  ),
                })),
                opts(ctx, 'e8_chart'),
              )
            : null,
      ],
    },
  },
  {
    chapter: 1,
    entry: {
      id: 'e9',
      figures: {
        pm_zh: f3(ref('e9_cross_domain', 'scope', 'zh', 'pm_fit_on_it', 'auroc')),
        pm_en: f3(ref('e9_cross_domain', 'scope', 'en', 'pm_fit_on_it', 'auroc')),
        it_zh: f3(ref('e9_cross_domain', 'scope', 'zh', 'it_units_only_fit', 'auroc')),
        it_en: f3(ref('e9_cross_domain', 'scope', 'en', 'it_units_only_fit', 'auroc')),
        r_zh: f2(ref('e9_cross_domain', 'retrieval', 'zh/in_paraphrase', 'dense', 'recall@5')),
        r_en: f2(ref('e9_cross_domain', 'retrieval', 'en/in_paraphrase', 'dense', 'recall@5')),
        c1_zh: f3(ref('e9_cross_domain', 'relation', 'zh', 'macro_f1')),
        c1_en: f3(ref('e9_cross_domain', 'relation', 'en', 'macro_f1')),
      },
      charts: [
        (ctx) =>
          has(ctx.r, 'e9_cross_domain')
            ? groupedBars(
                [st(ctx.l, 'pmFit'), st(ctx.l, 'itFit'), st(ctx.l, 'itRecall'), st(ctx.l, 'itC1')],
                langSeries(ctx, (lang) => [
                  value(ctx.r, 'e9_cross_domain', 'scope', lang, 'pm_fit_on_it', 'auroc'),
                  value(ctx.r, 'e9_cross_domain', 'scope', lang, 'it_units_only_fit', 'auroc'),
                  value(
                    ctx.r,
                    'e9_cross_domain',
                    'retrieval',
                    `${lang}/in_paraphrase`,
                    'dense',
                    'recall@5',
                  ),
                  value(ctx.r, 'e9_cross_domain', 'relation', lang, 'macro_f1'),
                ]),
                opts(ctx, 'e9_chart', { digits: 3 }),
              )
            : null,
      ],
    },
  },
  {
    chapter: 2,
    entry: {
      id: 'e11',
      tag: 'mainline',
      figures: {
        v3: f3(
          ref('e11_transfer_public', 'sources', 'relation-v3', 'stack_rule', 'all', 'macro_f1'),
        ),
        synth: f3(
          ref('e11_transfer_public', 'sources', 'public-synth', 'stack_rule', 'all', 'macro_f1'),
        ),
        cnli: f3(
          ref('e11_transfer_public', 'sources', 'contractnli', 'stack_rule', 'all', 'macro_f1'),
        ),
        vit: f3(ref('e11_transfer_public', 'sources', 'vitaminc', 'stack_rule', 'all', 'macro_f1')),
        cf: f3(ref('e11_transfer_public', 'sources', 'cfever', 'stack_rule', 'all', 'macro_f1')),
        cnli_c: f2(
          ref(
            'e11_transfer_public',
            'sources',
            'contractnli',
            'stack_rule',
            'per_class',
            'CONTRADICTED',
            'f1',
          ),
        ),
        vit_c: f2(
          ref(
            'e11_transfer_public',
            'sources',
            'vitaminc',
            'stack_rule',
            'per_class',
            'CONTRADICTED',
            'f1',
          ),
        ),
        cf_c: f2(
          ref(
            'e11_transfer_public',
            'sources',
            'cfever',
            'stack_rule',
            'per_class',
            'CONTRADICTED',
            'f1',
          ),
        ),
      },
      charts: [
        (ctx) =>
          has(ctx.r, 'e11_transfer_public')
            ? groupedBars(
                REAL.map((s) => realName(ctx.l, s)),
                [
                  {
                    name: st(ctx.l, 'macroF1'),
                    values: REAL.map((s) =>
                      value(
                        ctx.r,
                        'e11_transfer_public',
                        'sources',
                        s,
                        'stack_rule',
                        'all',
                        'macro_f1',
                      ),
                    ),
                  },
                  {
                    name: st(ctx.l, 'contraF1'),
                    values: REAL.map((s) =>
                      value(
                        ctx.r,
                        'e11_transfer_public',
                        'sources',
                        s,
                        'stack_rule',
                        'per_class',
                        'CONTRADICTED',
                        'f1',
                      ),
                    ),
                  },
                ],
                opts(ctx, 'e11_chart', { digits: 3 }),
              )
            : null,
      ],
    },
  },
  {
    chapter: 2,
    entry: {
      id: 'e12',
      tag: 'branch',
      figures: {
        v3: f3(
          ref(
            'e12_mix_public',
            'variants',
            'v3',
            'test',
            'relation-v3',
            'stack_rule_product_alpha',
            'all',
            'macro_f1',
          ),
        ),
        v3_mix: f3(
          ref(
            'e12_mix_public',
            'variants',
            'mix',
            'test',
            'relation-v3',
            'stack_rule_product_alpha',
            'all',
            'macro_f1',
          ),
        ),
        v3_bal: f3(
          ref(
            'e12_mix_public',
            'variants',
            'mix_balanced',
            'test',
            'relation-v3',
            'stack_rule_product_alpha',
            'all',
            'macro_f1',
          ),
        ),
        cnli_mix: f3(
          ref(
            'e12_mix_public',
            'variants',
            'mix',
            'test',
            'contractnli',
            'stack_rule_product_alpha',
            'all',
            'macro_f1',
          ),
        ),
        cnli_bal: f3(
          ref(
            'e12_mix_public',
            'variants',
            'mix_balanced',
            'test',
            'contractnli',
            'stack_rule_product_alpha',
            'all',
            'macro_f1',
          ),
        ),
        cnli_loso: f3(
          ref(
            'e12_mix_public',
            'variants',
            'loso_contractnli',
            'test',
            'contractnli',
            'stack_rule_product_alpha',
            'all',
            'macro_f1',
          ),
        ),
        vit_loso: f3(
          ref(
            'e12_mix_public',
            'variants',
            'loso_vitaminc',
            'test',
            'vitaminc',
            'stack_rule_product_alpha',
            'all',
            'macro_f1',
          ),
        ),
      },
      charts: [
        (ctx) => {
          if (!has(ctx.r, 'e12_mix_public')) return null;
          const sets = ['relation-v3', 'contractnli', 'vitaminc', 'cfever'];
          const cell = (variant: string, set: string) =>
            value(
              ctx.r,
              'e12_mix_public',
              'variants',
              variant,
              'test',
              set,
              'stack_rule_product_alpha',
              'all',
              'macro_f1',
            );
          return groupedBars(
            sets.map((s) => realName(ctx.l, s)),
            [
              { name: st(ctx.l, 'v3Only'), values: sets.map((s) => cell('v3', s)) },
              { name: st(ctx.l, 'mixAll'), values: sets.map((s) => cell('mix', s)) },
              { name: st(ctx.l, 'mixBalanced'), values: sets.map((s) => cell('mix_balanced', s)) },
              {
                name: st(ctx.l, 'loso'),
                values: sets.map((s) => (s === 'relation-v3' ? Number.NaN : cell(`loso_${s}`, s))),
              },
            ],
            opts(ctx, 'e12_chart', { digits: 3 }),
          );
        },
      ],
    },
  },
  {
    chapter: 2,
    entry: {
      id: 'e14',
      tag: 'mainline',
      figures: {
        cnli_s: f3(
          ref(
            'e14_diagnose_public',
            'sources',
            'contractnli',
            'pair_c1_evidence',
            'recall',
            'SUPPORTS',
          ),
        ),
        cnli_c: f3(
          ref(
            'e14_diagnose_public',
            'sources',
            'contractnli',
            'pair_c1_evidence',
            'recall',
            'CONTRADICTS',
          ),
        ),
        vit_c: f3(
          ref(
            'e14_diagnose_public',
            'sources',
            'vitaminc',
            'pair_c1_evidence',
            'recall',
            'CONTRADICTS',
          ),
        ),
        t_c: pct(
          ref(
            'e14_diagnose_public',
            'sources',
            'contractnli',
            'truncation',
            'gold_pairs_over_limit',
          ),
        ),
        t_v: pct(
          ref('e14_diagnose_public', 'sources', 'vitaminc', 'truncation', 'gold_pairs_over_limit'),
        ),
        t_f: pct(
          ref('e14_diagnose_public', 'sources', 'cfever', 'truncation', 'gold_pairs_over_limit'),
        ),
        v3_cue: pct(
          ref('e14_diagnose_public', 'sources', 'relation-v3', 'contradiction_cues', 'any_cue'),
        ),
        vit_cue: pct(
          ref('e14_diagnose_public', 'sources', 'vitaminc', 'contradiction_cues', 'any_cue'),
        ),
        cf_cue: pct(
          ref('e14_diagnose_public', 'sources', 'cfever', 'contradiction_cues', 'any_cue'),
        ),
        cnli_b: reviewBuckets('contractnli'),
        vit_b: reviewBuckets('vitaminc'),
        cf_b: reviewBuckets('cfever'),
        cnli_k: fraction(
          [ref('e14_review_errors', 'groups', 'contractnli|control', 'agrees_gold')],
          [ref('e14_review_errors', 'groups', 'contractnli|control', 'n')],
        ),
        vit_k: fraction(
          [ref('e14_review_errors', 'groups', 'vitaminc|control', 'agrees_gold')],
          [ref('e14_review_errors', 'groups', 'vitaminc|control', 'n')],
        ),
        cf_k: fraction(
          [ref('e14_review_errors', 'groups', 'cfever|control', 'agrees_gold')],
          [ref('e14_review_errors', 'groups', 'cfever|control', 'n')],
        ),
      },
      charts: [
        (ctx) => {
          if (!has(ctx.r, 'e14_diagnose_public')) return null;
          const sets = ['relation-v3', 'contractnli', 'vitaminc', 'cfever'];
          return groupedBars(
            sets.map((s) => realName(ctx.l, s)),
            [
              {
                name: st(ctx.l, 'supportPairs'),
                values: sets.map((s) =>
                  value(
                    ctx.r,
                    'e14_diagnose_public',
                    'sources',
                    s,
                    'pair_c1_evidence',
                    'recall',
                    'SUPPORTS',
                  ),
                ),
              },
              {
                name: st(ctx.l, 'contraPairs'),
                values: sets.map((s) =>
                  value(
                    ctx.r,
                    'e14_diagnose_public',
                    'sources',
                    s,
                    'pair_c1_evidence',
                    'recall',
                    'CONTRADICTS',
                  ),
                ),
              },
            ],
            opts(ctx, 'e14_chart', { digits: 3 }),
          );
        },
        (ctx) => {
          const groups = (
            ctx.r.e14_review_errors as {
              groups?: Record<string, { n: number; agrees_gold: number }>;
            } | null
          )?.groups;
          if (!groups) return null;
          const sets = ['contractnli', 'vitaminc', 'cfever'];
          const share = (set: string, control: boolean) => {
            const rows = Object.entries(groups).filter(
              ([k]) => k.startsWith(`${set}|`) && k.endsWith('|control') === control,
            );
            const n = rows.reduce((a, [, g]) => a + g.n, 0);
            return n ? rows.reduce((a, [, g]) => a + g.agrees_gold, 0) / n : Number.NaN;
          };
          return groupedBars(
            sets.map((s) => realName(ctx.l, s)),
            [
              { name: st(ctx.l, 'control'), values: sets.map((s) => share(s, true)) },
              { name: st(ctx.l, 'buckets'), values: sets.map((s) => share(s, false)) },
            ],
            opts(ctx, 'e14_review'),
          );
        },
      ],
    },
  },
  {
    chapter: 2,
    entry: {
      id: 'e15',
      tag: 'mainline',
      offline: true,
      figures: {
        vit_e11: f3(
          ref('e11_transfer_public', 'sources', 'vitaminc', 'stack_rule', 'all', 'macro_f1'),
        ),
        vit_zs: f3(ref('e15_nli_zs', 'sources', 'vitaminc', 'nli', 'all', 'macro_f1')),
        v3_mix: f3(ref('e15_nli_mix', 'sources', 'relation-v3', 'nli', 'all', 'macro_f1')),
        cnli_mix: f3(ref('e15_nli_mix', 'sources', 'contractnli', 'nli', 'all', 'macro_f1')),
        vit_mix: f3(ref('e15_nli_mix', 'sources', 'vitaminc', 'nli', 'all', 'macro_f1')),
        cf_mix: f3(ref('e15_nli_mix', 'sources', 'cfever', 'nli', 'all', 'macro_f1')),
        syn_mix: f3(ref('e15_nli_mix', 'sources', 'public-synth', 'nli', 'all', 'macro_f1')),
        syn0: f3(ref('e13_reply', 'datasets', 'synth', 'product', 'three_class', 'macro_f1')),
        syn1: f3(ref('e15_reply_mix', 'datasets', 'synth', 'chunk', 'three_class', 'macro_f1')),
        rag0: f3(ref('e13_reply', 'datasets', 'ragtruth', 'product', 'not_grounded', 'auroc')),
        rag1: f3(ref('e15_reply_mix', 'datasets', 'ragtruth', 'chunk', 'not_grounded', 'auroc')),
      },
      charts: [
        (ctx) =>
          has(ctx.r, 'e11_transfer_public', 'e15_nli_zs', 'e15_nli_mix')
            ? groupedBars(
                REAL.map((s) => realName(ctx.l, s)),
                [
                  {
                    name: st(ctx.l, 'productChain'),
                    values: REAL.map((s) =>
                      value(
                        ctx.r,
                        'e11_transfer_public',
                        'sources',
                        s,
                        'stack_rule',
                        'all',
                        'macro_f1',
                      ),
                    ),
                  },
                  {
                    name: st(ctx.l, 'nliZs'),
                    values: REAL.map((s) =>
                      value(ctx.r, 'e15_nli_zs', 'sources', s, 'nli', 'all', 'macro_f1'),
                    ),
                  },
                  {
                    name: st(ctx.l, 'nliMix'),
                    values: REAL.map((s) =>
                      value(ctx.r, 'e15_nli_mix', 'sources', s, 'nli', 'all', 'macro_f1'),
                    ),
                  },
                ],
                opts(ctx, 'e15_chart', { digits: 3 }),
              )
            : null,
        (ctx) =>
          has(ctx.r, 'e13_reply', 'e15_reply_zs', 'e15_reply_mix')
            ? groupedBars(
                [st(ctx.l, 'ragAuroc'), st(ctx.l, 'synthF1')],
                [
                  {
                    name: st(ctx.l, 'productReply'),
                    values: [
                      value(
                        ctx.r,
                        'e13_reply',
                        'datasets',
                        'ragtruth',
                        'product',
                        'not_grounded',
                        'auroc',
                      ),
                      value(
                        ctx.r,
                        'e13_reply',
                        'datasets',
                        'synth',
                        'product',
                        'three_class',
                        'macro_f1',
                      ),
                    ],
                  },
                  {
                    name: st(ctx.l, 'nliZs'),
                    values: [
                      value(
                        ctx.r,
                        'e15_reply_zs',
                        'datasets',
                        'ragtruth',
                        'chunk',
                        'not_grounded',
                        'auroc',
                      ),
                      value(
                        ctx.r,
                        'e15_reply_zs',
                        'datasets',
                        'synth',
                        'chunk',
                        'three_class',
                        'macro_f1',
                      ),
                    ],
                  },
                  {
                    name: st(ctx.l, 'nliMix'),
                    values: [
                      value(
                        ctx.r,
                        'e15_reply_mix',
                        'datasets',
                        'ragtruth',
                        'chunk',
                        'not_grounded',
                        'auroc',
                      ),
                      value(
                        ctx.r,
                        'e15_reply_mix',
                        'datasets',
                        'synth',
                        'chunk',
                        'three_class',
                        'macro_f1',
                      ),
                    ],
                  },
                ],
                opts(ctx, 'e15_reply', { digits: 3 }),
              )
            : null,
      ],
    },
  },
  {
    chapter: 2,
    entry: {
      id: 'e13',
      tag: 'branch',
      figures: {
        mz: f3(ref('e13_scope', 'massive/zh', 'methods', 'mahalanobis', 'all_out', 'auroc')),
        me: f3(ref('e13_scope', 'massive/en', 'methods', 'mahalanobis', 'all_out', 'auroc')),
        clinc: f3(ref('e13_scope', 'clinc150/en', 'methods', 'mahalanobis', 'all_out', 'auroc')),
        clinc_sm: f3(ref('e13_scope', 'clinc150/en', 'methods', 'max_softmax', 'all_out', 'auroc')),
        pq_d: f3(ref('e13_retrieval', 'privacyqa', 'test_any', 'dense', 'recall@5')),
        pq_r: f3(ref('e13_retrieval', 'privacyqa', 'test_any', 'rrf', 'recall@5')),
        tau_hmm: f3(ref('e13_sequence', 'tau-bench', 'methods', 'hmm_per_class', 'macro_f1')),
        tau_dtw: f3(ref('e13_sequence', 'tau-bench', 'methods', 'dtw_1nn', 'macro_f1')),
        jira_len: f3(ref('e13_sequence', 'jira', 'methods', 'length_only', 'macro_f1')),
        rag: f3(ref('e13_reply', 'datasets', 'ragtruth', 'product', 'three_class', 'macro_f1')),
      },
      charts: [
        (ctx) => {
          if (!has(ctx.r, 'e13_scope')) return null;
          const sets: [string, StoryKey | null][] = [
            ['clinc150/en', null],
            ['massive/zh', 'massiveZh'],
            ['massive/en', 'massiveEn'],
            ['queries-synth/zh', 'synthZh'],
            ['queries-synth/en', 'synthEn'],
          ];
          return groupedBars(
            sets.map(([, label]) => (label ? st(ctx.l, label) : 'CLINC150')),
            (['mahalanobis', 'max_cosine', 'max_softmax'] as const).map((m) => ({
              name: st(
                ctx.l,
                m === 'mahalanobis'
                  ? 'mahalanobis'
                  : m === 'max_cosine'
                    ? 'maxCosine'
                    : 'maxSoftmax',
              ),
              values: sets.map(([k]) =>
                value(ctx.r, 'e13_scope', k, 'methods', m, 'all_out', 'auroc'),
              ),
            })),
            opts(ctx, 'e13_chart', { min: 0.5, digits: 3 }),
          );
        },
      ],
    },
  },
];

/** The reviewer sides with gold in the three error buckets of one real set (sum of counts). */
function reviewBuckets(set: string): Figure {
  const buckets: Record<string, string[]> = {
    contractnli: [
      'SUPPORTED->INSUFFICIENT:missed_gold_pair',
      'INSUFFICIENT->SUPPORTED:spurious_support_non_evidence',
      'SUPPORTED->CONTRADICTED:support_read_as_contradiction',
    ],
    vitaminc: [
      'CONTRADICTED->SUPPORTED:contradiction_read_as_support',
      'SUPPORTED->INSUFFICIENT:missed_gold_pair',
      'CONTRADICTED->INSUFFICIENT:missed_gold_pair',
    ],
    cfever: [
      'CONTRADICTED->INSUFFICIENT:missed_gold_pair',
      'SUPPORTED->INSUFFICIENT:missed_gold_pair',
      'CONTRADICTED->SUPPORTED:contradiction_read_as_support',
    ],
  };
  const keys = buckets[set].map((b) => `${set}|${b}`);
  return fraction(
    keys.map((k) => ref('e14_review_errors', 'groups', k, 'agrees_gold')),
    keys.map((k) => ref('e14_review_errors', 'groups', k, 'n')),
  );
}

function entryHtml(e: Entry, ctx: Ctx) {
  const t = (k: StoryKey, v: Record<string, string> = {}) => esc(st(ctx.l, k, v));
  const values = fill(ctx.r, e.figures);
  const key = (part: string) => `${e.id}_${part}` as StoryKey;
  const tag = e.tag ? `<span class="rc-story-tag" data-tag="${e.tag}">${t(e.tag)}</span>` : '';
  const offline = e.offline
    ? `<span class="rc-story-tag" data-tag="offline">${t('offline')}</span>`
    : '';
  const head = `<header class="rc-story-head"><span class="rc-story-id">${e.id.toUpperCase()}</span><h4>${t(key('title'))}</h4>${tag}${offline}</header>`;
  if (!values)
    return `<article class="rc-story-entry" id="rc-${e.id}">${head}<p class="meta">${t('missing')}</p></article>`;
  const steps = (['q', 'how', 'found', 'use'] as const)
    .map(
      (step) =>
        `<div class="rc-step" data-step="${step}"><dt>${t(step)}</dt><dd>${rich(STORY_COPY[ctx.l][key(step)], values)}</dd></div>`,
    )
    .join('');
  const charts = e.charts
    .map((chart) => chart(ctx))
    .filter((html): html is string => !!html)
    .join('');
  return `<article class="rc-story-entry" id="rc-${e.id}" data-tag="${e.tag ?? ''}">${head}<div class="rc-story-body"><dl class="rc-steps">${steps}</dl><div class="rc-story-charts">${charts}</div></div></article>`;
}

export function storyHtml(results: Results, language: Language, width: number) {
  const ctx: Ctx = { r: results, l: language, width };
  const t = (k: StoryKey) => esc(st(language, k));
  const chapter = (n: 1 | 2) =>
    ENTRIES.filter((x) => x.chapter === n)
      .map((x) => entryHtml(x.entry, ctx))
      .join('');
  return `<section class="rc-chapter" data-chapter="1" aria-labelledby="rc-ch1"><header class="rc-chapter-head"><h3 class="rc-chapter-title" id="rc-ch1">${t('ch1Title')} <span class="rc-range">${t('ch1Range')}</span></h3><p class="meta">${t('ch1Lead')}</p></header>${chapter(1)}</section>
    <section class="rc-chapter" data-chapter="2" aria-labelledby="rc-ch2"><header class="rc-chapter-head"><h3 class="rc-chapter-title" id="rc-ch2">${t('ch2Title')} <span class="rc-range">${t('ch2Range')}</span></h3><p class="meta">${t('ch2Lead')}</p></header>${chapter(2)}</section>`;
}
