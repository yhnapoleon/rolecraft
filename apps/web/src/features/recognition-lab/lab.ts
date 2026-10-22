/** Recognition lab (#/lab): one claim's full chain in this practice, plus experiment charts.
 *
 * The chain comes from GET /sessions/{id}/recognition; charts read static result files
 * that `experiments/recognition/publish_lab.py` copies to `public/lab/`.
 */
import { copyText, type CopyTable, type Language } from '../results-native/localization';
import type { RecognitionRecord } from '../recognition-native/badge';
import type { SessionRecognition } from '../recognition-native/client';
import { groupedBars, heatmap, lines, scatter } from './charts';
import './lab.css';

const zh = {
  title: '识别实验室',
  lead: '这一页给评审看识别层的中间结果：本次练习里一条断言从检索到仲裁的全链路，以及各识别器的离线实验。',
  archAlt: 'RoleCraft 架构：识别层位于学员工作台与三个生成器之间',
  archCaption: '感知 → 预处理 → 表示 → 识别 → 决策，三个生成器（评审、同事、知识助手）以识别结果为输入。',
  chain: '本次练习：一条断言的全链路',
  noSession: '先完成一次提交，这里会显示作品逐句的识别过程。',
  noRelation: '本次练习还没有作品句级识别记录（提交后出现）。',
  pick: '选择作品中的一句',
  s1: '① 证据检索：BM25 + e5 + RRF 为这句话找到的候选证据',
  s2: '② 关系判定：逐对概率与聚合',
  s3: '③ 代价决策：期望代价与送人工',
  s4: '④ 进入 Judge 输入的识别摘要',
  s5: '⑤ Judge 输出与仲裁（R2.support）',
  decide: '直接判定：{label}（期望代价 {cost}）',
  defer: '送人工核验：期望代价 {cost} 高于送人工 {defer}',
  arbiterAgree: '评审 {judge} 与识别器 {rec} 一致',
  arbiterConservative: '评审 {judge}、识别器 {rec} 不一致 → 取保守 {final}',
  arbiterUndecided: '评审未给出可比标签（{judge}），识别器 {rec}',
  noArbiter: '本次没有仲裁记录。',
  fallbackNote: '规则回退：关系判定用的是数值与限额一致性规则，关系模型权重未加载。',
  experiments: '离线实验',
  missing: '这项实验的结果还没有发布到实验室。',
  e5: 'E5 · 范围检测：马氏距离与六种对照方法的 AUROC（test）',
  e5pca: 'E5 · e5 向量的 PCA 投影（中文）：知识库单元、域内问题、域外问题',
  e6: 'E6 · 行为识别：步骤被随机扰动时的策略识别准确率',
  e6anom: 'E6 · 行为轨迹异常检测 AUROC',
  e7: 'E7 · 提问意图识别：准确率（test）',
  e7cm: 'E7 · TF-IDF+LR 意图混淆矩阵（test，中英合计）',
  e1: 'E1 · 关系判定（XLM-R 交叉编码器）：分语言 macro-F1 与 joint（test）',
  e1cm: 'E1 · XLM-R 关系判定混淆矩阵（test）',
  e1base: 'E1 · 经典模型、集成与 XLM-R 对比（test macro-F1）：LR 与 XLM-R 的堆叠集成最好',
  e1stack: 'E1-S · 产品里的关系判定链（test macro-F1）：XLM-R、堆叠集成，以及各自与数值限额规则的晚期融合',
  e1stackMeta: '产品使用：堆叠集成 + 数值限额规则，融合权重 α={alpha}（dev 五折外预测选出）',
  e3: 'E3 · 证据检索：Recall@5（test；直述问题三法都接近 1.0，差别在改写问题）',
  e4: 'E4 · 代价敏感拒识：误差—拒识曲线（test），期望代价高的断言先送人工',
  e4meta: 'ECE 温度缩放前 {before} → 后 {after} · 产品默认代价下送人工比例 {defer}',
  e8: 'E8 · Judge 输入里有无识别摘要（同一批提交）',
  e8meta: '{pairs} 对提交 · 两种条件的标签一致率 {agree} · 识别器与评审冲突率 {conflict}',
  e9: 'E9 · 跨领域：pm_pilot 上做的东西搬到 it_ticket_pilot（test）',
  e10: 'E10 · 晚期融合：XLM-R + 数值限额规则，macro-F1（test）',
  e10ph: 'E10 · 分现象准确率（test，中英合计）',
  e10meta: '融合权重 α={alpha}（dev 网格选出）· 规则有可比依据的比例 {active} · 早期融合未做（需重训编码器）',
  rejectRate: '送人工比例',
  errorRate: '剩余错误率',
  wrongDeduction: '误扣分率',
  labelled: '给出标签的比例',
  pending: '待核验比例',
  citations: '平均引用数',
  recOn: '有识别摘要',
  recOff: '无识别摘要',
  pmFit: '范围检测用 pm_pilot 拟合 · AUROC',
  itFit: '范围检测只用 IT 知识库拟合 · AUROC',
  itRecall: 'e5 检索改写问题 · Recall@5',
  itC1: '关系判定（pm_pilot 训练）· IT macro-F1',
  table: '表格视图',
  units: '知识库单元',
  inDomain: '域内问题',
  outDomain: '域外问题',
  noise: '扰动概率',
  gold: '真实',
  predicted: '预测',
  stats: 'HMM 状态数 {k}（BIC 选择）· 无监督聚类 ARI {ari}（k={kc}）',
} as const;
const en: Record<keyof typeof zh, string> = {
  title: 'Recognition lab',
  lead: 'For reviewers: the recognition layer’s intermediate results — one claim of this practice from retrieval to arbitration — and each recognizer’s offline experiments.',
  archAlt: 'RoleCraft architecture: a recognition layer between the learner workbench and three generators',
  archCaption: 'Sense → pre-process → represent → recognise → decide; the three generators (Judge, colleagues, knowledge assistant) take the recognition results as input.',
  chain: 'This practice: one claim, end to end',
  noSession: 'Submit once and this section shows how each sentence of the work was recognised.',
  noRelation: 'No sentence-level records in this practice yet (they appear after a submission).',
  pick: 'Choose a sentence of the work',
  s1: '① Evidence retrieval: candidates BM25 + e5 + RRF found for this sentence',
  s2: '② Relation: pair probabilities, aggregated',
  s3: '③ Cost decision: expected cost vs. sending to a person',
  s4: '④ The recognition summary that enters the Judge input',
  s5: '⑤ Judge output and arbitration (R2.support)',
  decide: 'Decide: {label} (expected cost {cost})',
  defer: 'Send to a person: expected cost {cost} exceeds the deferral cost {defer}',
  arbiterAgree: 'Reviewer {judge} agrees with recognizer {rec}',
  arbiterConservative: 'Reviewer {judge} vs recognizer {rec} → conservative {final}',
  arbiterUndecided: 'Reviewer gave no comparable label ({judge}); recognizer {rec}',
  noArbiter: 'No arbitration record in this practice.',
  fallbackNote: 'Rule fallback: relations came from the number-and-limit consistency rule; relation model weights not loaded.',
  experiments: 'Offline experiments',
  missing: 'This experiment’s results are not published to the lab yet.',
  e5: 'E5 · Scope detection: AUROC of Mahalanobis distance and six alternatives (test)',
  e5pca: 'E5 · PCA of e5 vectors (Chinese): KB units, in-domain and out-of-domain questions',
  e6: 'E6 · Behaviour recognition: strategy accuracy when steps are randomly perturbed',
  e6anom: 'E6 · Trajectory anomaly detection AUROC',
  e7: 'E7 · Question intent: accuracy (test)',
  e7cm: 'E7 · TF-IDF+LR intent confusion matrix (test, both languages)',
  e1: 'E1 · Relation (XLM-R cross-encoder): macro-F1 and joint by language (test)',
  e1cm: 'E1 · XLM-R relation confusion matrix (test)',
  e1base: 'E1 · Classical models, ensembles and XLM-R (test macro-F1): the LR + XLM-R stacked ensemble is best',
  e1stack: 'E1-S · The product’s relation chain (test macro-F1): XLM-R, the stacked ensemble, and each with late fusion of the number-and-limit rule',
  e1stackMeta: 'In the product: stacked ensemble + number-and-limit rule, fusion weight α={alpha} (chosen on out-of-fold dev predictions)',
  e3: 'E3 · Evidence retrieval: Recall@5 (test; all three are near 1.0 on direct questions, paraphrases separate them)',
  e4: 'E4 · Cost-sensitive reject option: error–reject curve (test); highest-cost claims go to a person first',
  e4meta: 'ECE before temperature scaling {before} → after {after} · deferral rate at the product costs {defer}',
  e8: 'E8 · Judge with and without the recognition summary in its input (same submissions)',
  e8meta: '{pairs} submission pairs · label agreement between conditions {agree} · recognizer–reviewer conflict rate {conflict}',
  e9: 'E9 · Cross-domain: what was built on pm_pilot, moved to it_ticket_pilot (test)',
  e10: 'E10 · Late fusion: XLM-R + the number-and-limit rule, macro-F1 (test)',
  e10ph: 'E10 · Accuracy by phenomenon (test, both languages)',
  e10meta: 'Fusion weight α={alpha} (dev grid) · share of claims where the rule had comparable evidence {active} · early fusion not run (needs retraining)',
  rejectRate: 'deferral rate',
  errorRate: 'remaining error rate',
  wrongDeduction: 'wrong-deduction rate',
  labelled: 'labelled share',
  pending: 'pending-review share',
  citations: 'mean citations',
  recOn: 'with summary',
  recOff: 'without summary',
  pmFit: 'Scope fitted on pm_pilot · AUROC',
  itFit: 'Scope fitted on IT KB only · AUROC',
  itRecall: 'e5 retrieval, paraphrases · Recall@5',
  itC1: 'Relation (trained on pm_pilot) · IT macro-F1',
  table: 'Table view',
  units: 'KB units',
  inDomain: 'in-domain questions',
  outDomain: 'out-of-domain questions',
  noise: 'perturbation probability',
  gold: 'gold',
  predicted: 'predicted',
  stats: 'HMM states {k} (by BIC) · unsupervised clustering ARI {ari} (k={kc})',
};
type Key = keyof typeof zh;
const COPY: CopyTable<Key> = { zh, en };

const esc = (v: string) =>
  v.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c);
const f2 = (v: unknown) => (typeof v === 'number' ? v.toFixed(2) : '–');

async function staticJson(name: string) {
  try {
    const response = await fetch(`/lab/${name}.json`, { cache: 'no-store' });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

type Unit = {
  index: number;
  quote: string;
  label: string;
  confidence: number;
  probabilities: Record<string, number>;
  evidence_ids: string[];
  reason: string;
  decision: string;
  expected_cost: number;
};

function chainHtml(data: SessionRecognition | null, l: Language, selected: number) {
  const t = (k: Key, v: Record<string, string | number> = {}) => copyText(COPY, l, k, v);
  if (!data) return `<p class="meta">${t('noSession')}</p>`;
  const records = data.records.map((r) => r.record);
  const relation = [...records]
    .reverse()
    .find((r) => r.task === 'relation' && Array.isArray(r.outputs?.units));
  if (!relation) return `<p class="meta">${t('noRelation')}</p>`;
  const units = (relation.outputs?.units ?? []) as Unit[];
  const unit = units.find((u) => u.index === selected) ?? units[0];
  const retrieval = [...records]
    .reverse()
    .find((r) => r.task === 'retrieval' && Array.isArray(r.outputs?.per_sentence_top));
  const top = ((retrieval?.outputs?.per_sentence_top ?? []) as { index: number; top: Record<string, unknown>[] }[])
    .find((row) => row.index === unit.index)?.top ?? [];
  const decision = [...records].reverse().find((r) => r.task === 'decision');
  const arbiter = [...records].reverse().find((r) => r.task === 'arbiter') as RecognitionRecord | undefined;
  const options = units
    .map((u) => `<option value="${u.index}"${u.index === unit.index ? ' selected' : ''}>[${u.index}] ${esc(u.quote.slice(0, 40))}</option>`)
    .join('');
  const probs = ['supported', 'contradicted', 'insufficient']
    .map((k) => {
      const p = unit.probabilities?.[k] ?? 0;
      return `<li><span>${k}</span><span class="rc-pbar"><i style="width:${Math.round(p * 100)}%" data-s="${k === 'supported' ? 3 : k === 'contradicted' ? 2 : 1}"></i></span><span>${f2(p)}</span></li>`;
    })
    .join('');
  const deferCost = Number((decision?.outputs?.costs as { defer?: number } | undefined)?.defer ?? 0.5);
  const decisionLine =
    unit.decision === 'defer'
      ? t('defer', { cost: f2(unit.expected_cost), defer: f2(deferCost) })
      : t('decide', { label: unit.label, cost: f2(unit.expected_cost) });
  const out = arbiter?.outputs ?? {};
  const arbiterLine = !arbiter
    ? t('noArbiter')
    : out.agreement
      ? t('arbiterAgree', { judge: String(out.judge_label), rec: String(out.recognizer_label) })
      : out.final && out.final !== out.judge_label
        ? t('arbiterConservative', { judge: String(out.judge_label), rec: String(out.recognizer_label), final: String(out.final) })
        : t('arbiterUndecided', { judge: String(out.judge_label), rec: String(out.recognizer_label) });
  const summaryRow = {
    index: unit.index,
    label: unit.label,
    confidence: unit.confidence,
    evidence_ids: unit.evidence_ids,
    decision: unit.decision,
  };
  return `<label class="rc-pick">${t('pick')} <select data-rc-unit>${options}</select></label>
    <blockquote class="rc-quote">${esc(unit.quote)}</blockquote>
    ${relation.fallback ? `<p class="meta">${t('fallbackNote')}</p>` : ''}
    <ol class="rc-chain">
      <li><h4>${t('s1')}</h4><ul class="rc-top">${top
        .map((h) => `<li><span class="rc-rank">#${h.rank}</span>${esc(String(h.quote ?? ''))}<span class="meta"> bm25 ${f2(h.bm25)} · e5 ${f2(h.dense)}</span></li>`)
        .join('')}</ul></li>
      <li><h4>${t('s2')}</h4><p>${esc(unit.label)} · ${f2(unit.confidence)} <span class="meta">${esc(unit.reason ?? '')} · ${esc(relation.recognizer_id)}@${esc(relation.revision.slice(0, 12))}</span></p><ul class="rc-probs">${probs}</ul></li>
      <li><h4>${t('s3')}</h4><p>${esc(decisionLine)}</p></li>
      <li><h4>${t('s4')}</h4><pre class="rc-json">${esc(JSON.stringify(summaryRow, null, 1))}</pre></li>
      <li><h4>${t('s5')}</h4><p>${esc(arbiterLine)}</p></li>
    </ol>`;
}

type PcaQuery = { kind: string; xy: [number, number]; text: string; score: number };

// biome-ignore lint/suspicious/noExplicitAny: experiment JSON from public/lab is read field by field
function experimentsHtml(results: Record<string, any>, l: Language) {
  const t = (k: Key, v: Record<string, string | number> = {}) => copyText(COPY, l, k, v);
  const section = (title: Key, body: string | null) =>
    `<section class="rc-exp"><h3>${t(title)}</h3>${body ?? `<p class="meta">${t('missing')}</p>`}</section>`;
  const parts: string[] = [];
  const e1 = results.e1_relation;
  parts.push(
    section(
      'e1',
      e1
        ? groupedBars(['macro-F1', 'joint', 'evidence F1'], ['zh', 'en'].map((lang) => ({
            name: lang,
            values: [e1.test[lang]?.macro_f1 ?? 0, e1.test[lang]?.joint ?? 0, e1.test[lang]?.evidence_f1 ?? 0],
          })), { tableCaption: t('table') })
        : null,
    ),
  );
  if (e1) parts.push(section('e1cm', heatmap(['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT'], e1.test.all.confusion, { tableCaption: t('table'), rowLabel: t('gold'), colLabel: t('predicted') })));
  const base = results.e1_baselines?.models as Record<string, { test: Record<string, { macro_f1: number }> }> | undefined;
  if (base) {
    const names = Object.keys(base);
    parts.push(
      section(
        'e1base',
        groupedBars(names, ['zh', 'en'].map((lang) => ({
          name: lang,
          values: names.map((n) => base[n].test[lang]?.macro_f1 ?? 0),
        })), { tableCaption: t('table') }),
      ),
    );
  }
  const stack = results.e1_stack?.test as Record<string, Record<string, { macro_f1: number }>> | undefined;
  if (stack) {
    const variants = Object.keys(stack);
    const label = (v: string) => v.replace('c1', 'XLM-R').replace('stack', 'stacked').replace('_rule_alpha', ' + rule α=');
    parts.push(
      section(
        'e1stack',
        groupedBars(variants.map(label), ['zh', 'en', 'all'].map((lang) => ({
          name: lang,
          values: variants.map((v) => stack[v][lang]?.macro_f1 ?? 0),
        })), { tableCaption: t('table') }) +
          `<p class="meta">${esc(t('e1stackMeta', { alpha: f2(results.e1_stack.fusion_alpha) }))}</p>`,
      ),
    );
  }
  const e3 = results.e3_retrieval;
  const methodNames: Record<string, string> = { bm25: 'BM25', dense: 'e5', rrf: 'RRF' };
  parts.push(
    section(
      'e3',
      e3
        ? (() => {
            const methods = Object.keys(e3.assistant['zh/in_paraphrase'] ?? {});
            const kinds = ['zh/in_paraphrase', 'en/in_paraphrase'];
            return groupedBars(methods.map((m) => methodNames[m] ?? m), kinds.map((k) => ({
              name: k,
              values: methods.map((m) => e3.assistant[k]?.[m]?.['recall@5'] ?? 0),
            })), { tableCaption: t('table') });
          })()
        : null,
    ),
  );
  const e4 = results.e4_decision?.test;
  parts.push(
    section(
      'e4',
      e4
        ? (() => {
            const rows = e4.error_reject as { reject_rate: number; error_rate: number; wrong_deduction_rate: number }[];
            return (
              lines(rows.map((r) => r.reject_rate), [
                { name: t('errorRate'), values: rows.map((r) => r.error_rate) },
                { name: t('wrongDeduction'), values: rows.map((r) => r.wrong_deduction_rate) },
              ], { xLabel: t('rejectRate'), tableCaption: t('table') }) +
              `<p class="meta">${esc(t('e4meta', { before: f2(e4.ece_t1), after: f2(e4.ece_fitted), defer: f2(e4.defer_rate) }))}</p>`
            );
          })()
        : null,
    ),
  );
  const e5 = results.e5_scope;
  parts.push(
    section(
      'e5',
      e5
        ? (() => {
            const methods = Object.keys(e5.baselines.zh ?? {});
            return groupedBars(methods, ['zh', 'en'].map((lang) => ({
              name: lang,
              values: methods.map((m) => e5.baselines[lang]?.[m]?.auroc ?? 0),
            })), { min: 0.5, tableCaption: t('table') });
          })()
        : null,
    ),
  );
  if (e5?.pca?.zh) {
    const pca = e5.pca.zh;
    parts.push(
      section(
        'e5pca',
        scatter(
          [
            { name: t('units'), points: pca.units.map((p: number[]) => ({ x: p[0], y: p[1] })) },
            {
              name: t('inDomain'),
              points: pca.queries.filter((q: PcaQuery) => q.kind.startsWith('in_')).map((q: PcaQuery) => ({ x: q.xy[0], y: q.xy[1], label: `${q.text} · ${f2(q.score)}` })),
            },
            {
              name: t('outDomain'),
              points: pca.queries.filter((q: PcaQuery) => q.kind.startsWith('out_')).map((q: PcaQuery) => ({ x: q.xy[0], y: q.xy[1], label: `${q.text} · ${f2(q.score)}` })),
            },
          ],
          { tableCaption: t('table') },
        ),
      ),
    );
  }
  const e6 = results.e6_behavior;
  parts.push(
    section(
      'e6',
      e6
        ? (() => {
            const rows = Object.entries(e6.strategy_robustness) as [string, { dtw_1nn: number; ngram_rf: number }][];
            const ps = rows.map(([p]) => Number(p));
            return (
              lines(ps, [
                { name: 'DTW 1-NN', values: rows.map(([, r]) => r.dtw_1nn) },
                { name: 'n-gram RF', values: rows.map(([, r]) => r.ngram_rf) },
              ], { xLabel: t('noise'), tableCaption: t('table') }) +
              `<p class="meta">${esc(t('stats', { k: e6.hmm.states, ari: f2(e6.clustering.ari_vs_strategy), kc: e6.clustering.k }))}</p>`
            );
          })()
        : null,
    ),
  );
  if (e6) {
    const methods = ['hmm_loglik', 'dtw_to_regular', 'isolation_forest'];
    parts.push(section('e6anom', groupedBars(methods, [{ name: 'AUROC', values: methods.map((m) => e6.anomaly[m]?.auroc ?? 0) }], { tableCaption: t('table') })));
  }
  const e7 = results.e7_intent;
  parts.push(
    section(
      'e7',
      e7
        ? (() => {
            const models = Object.keys(e7.models);
            return groupedBars(models, ['zh', 'en'].map((lang) => ({ name: lang, values: models.map((m) => e7.models[m][lang].accuracy) })), { tableCaption: t('table') });
          })()
        : null,
    ),
  );
  if (e7) parts.push(section('e7cm', heatmap(e7.labels, e7.models.tfidf_lr.all.confusion, { tableCaption: t('table'), rowLabel: t('gold'), colLabel: t('predicted') })));
  const e8 = results.e8_judge;
  parts.push(
    section(
      'e8',
      e8
        ? (() => {
            const cond = (c: 'on' | 'off') => e8.by_condition[c] ?? {};
            const metric = (c: 'on' | 'off') => [cond(c).labelled_rate ?? 0, cond(c).pending_rate ?? 0, cond(c).mean_citations ?? 0];
            return (
              groupedBars([t('labelled'), t('pending'), t('citations')], [
                { name: t('recOn'), values: metric('on') },
                { name: t('recOff'), values: metric('off') },
              ], { tableCaption: t('table') }) +
              `<p class="meta">${esc(t('e8meta', { pairs: e8.pairs, agree: f2(e8.agreement?.label_agreement), conflict: f2(e8.arbiter?.conflict_rate) }))}</p>`
            );
          })()
        : null,
    ),
  );
  const e9 = results.e9_cross_domain;
  parts.push(
    section(
      'e9',
      e9
        ? groupedBars([t('pmFit'), t('itFit'), t('itRecall'), t('itC1')], ['zh', 'en'].map((lang) => ({
            name: lang,
            values: [
              e9.scope?.[lang]?.pm_fit_on_it?.auroc ?? 0,
              e9.scope?.[lang]?.it_units_only_fit?.auroc ?? 0,
              e9.retrieval?.[`${lang}/in_paraphrase`]?.dense?.['recall@5'] ?? 0,
              e9.relation?.[lang]?.macro_f1 ?? 0,
            ],
          })), { tableCaption: t('table') })
        : null,
    ),
  );
  const e10 = results.e10_fusion;
  const fusionNames = ['c1', 'rule', 'late_fusion'];
  parts.push(
    section(
      'e10',
      e10
        ? groupedBars(['XLM-R', 'rule', 'late fusion'], ['zh', 'en', 'all'].map((lang) => ({
            name: lang,
            values: fusionNames.map((m) => e10[m]?.[lang] ?? 0),
          })), { tableCaption: t('table') }) +
          `<p class="meta">${esc(t('e10meta', { alpha: f2(e10.alpha), active: f2(e10.rule_active_rate?.test) }))}</p>`
        : null,
    ),
  );
  if (e10?.c1?.by_phenomenon) {
    const phenomena = Object.keys(e10.c1.by_phenomenon);
    parts.push(
      section(
        'e10ph',
        groupedBars(phenomena, fusionNames.map((m, i) => ({
          name: ['XLM-R', 'rule', 'late fusion'][i],
          values: phenomena.map((p) => e10[m]?.by_phenomenon?.[p] ?? 0),
        })), { tableCaption: t('table') }),
      ),
    );
  }
  return parts.join('');
}

export async function mountLab(
  root: HTMLElement,
  options: { language: Language; session: (() => Promise<SessionRecognition>) | null },
) {
  const l = options.language;
  const t = (k: Key) => copyText(COPY, l, k);
  root.innerHTML = `<header class="rc-lab-head"><h1 class="title-xl">${t('title')}</h1><p class="meta">${t('lead')}</p></header>
    <figure class="rc-lab-arch"><img src="/lab/architecture.png" alt="${t('archAlt')}" loading="lazy"><figcaption class="meta">${t('archCaption')}</figcaption></figure>
    <section class="rc-lab-chain"><h2>${t('chain')}</h2><div data-rc-chain><p class="meta">…</p></div></section>
    <section class="rc-lab-exps"><h2>${t('experiments')}</h2><div data-rc-exps><p class="meta">…</p></div></section>`;
  const names = ['e1_relation', 'e1_baselines', 'e1_stack', 'e3_retrieval', 'e4_decision', 'e5_scope', 'e6_behavior', 'e7_intent', 'e8_judge', 'e9_cross_domain', 'e10_fusion'];
  const loaded = await Promise.all(names.map((n) => staticJson(n)));
  const results = Object.fromEntries(names.map((n, i) => [n, loaded[i]]));
  const exps = root.querySelector<HTMLElement>('[data-rc-exps]');
  if (exps) exps.innerHTML = experimentsHtml(results, l);
  let data: SessionRecognition | null = null;
  try {
    data = options.session ? await options.session() : null;
  } catch {
    data = null;
  }
  const chain = root.querySelector<HTMLElement>('[data-rc-chain]');
  const draw = (selected: number) => {
    if (!chain) return;
    chain.innerHTML = chainHtml(data, l, selected);
    chain.querySelector<HTMLSelectElement>('[data-rc-unit]')?.addEventListener('change', (event) => {
      draw(Number((event.target as HTMLSelectElement).value));
    });
  };
  draw(-1);
}
