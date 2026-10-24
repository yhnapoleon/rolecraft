/** Copy for the system profile page: header, pipeline and the recogniser register.
 * Both languages carry the same keys (checked by tsc and copy.test.ts). Figures are
 * never written here: `{name}` placeholders are filled from the published results. */
import { copyText, type CopyTable, type Language } from '../results-native/localization';

const zh = {
  title: '系统剖面',
  docTitle: '系统剖面 · Practice',
  lead: '给评审看：系统从学员的工作里识别什么、怎样识别，以及哪些实验支撑这些做法。',
  navLabel: '本页内容',
  navPipeline: '一句话走完全链',
  navRegister: '七个识别器',
  navStory: '实验故事线',
  loading: '正在读取…',

  pipeTitle: '一句话走完全链',
  pipeLead: '本次练习作品里的一句，依次经过识别层的每一站。',
  pipeLeadExample:
    '本次练习还没有作品逐句识别记录，交付后才有。下面这句来自演示包里一局已录制的练习，数字是那一局真实的识别输出。',
  exampleTag: '示例',
  sentenceOf: '第 {i} / {n} 句',
  pick: '换一句',
  pickOption: '第 {i} 句 · {label}：{quote}',
  play: '播放',
  replay: '重播',
  keysHint: '用方向键逐站查看。',
  stationsLabel: '识别流水线的六站',
  fallbackNote: '规则回退：关系模型的权重没有加载，这句由数字与限额一致性规则判定。',

  st_sense: '感知',
  st_prep: '预处理',
  st_repr: '表示',
  st_recog: '识别',
  st_decide: '决策',
  st_gen: '三个生成器',

  sense_short: '读入交付的作品',
  sense_detail:
    '交付时读入作品全文。测试提问、同事对话和学员一路操作留下的事件，也从这一层进入识别。',
  sense_detail_counts:
    '交付时读入作品全文。同一局里，这一层还读到 {tests} 次测试提问、{replies} 条同事回复，以及学员一路操作留下的事件。',
  prep_short: '切句：第 {i} / {n} 句',
  prep_detail:
    '作品切成 {n} 句，这是第 {i} 句；资料切成 {m} 个证据单元。每句只和检索出的候选单元配对，不和全部资料硬比。',
  prep_detail_nounits:
    '作品切成 {n} 句，这是第 {i} 句；资料切成证据单元，每句只和检索出的候选单元配对。',
  repr_short: '检索到：{quote}',
  repr_short_none: '没有检索记录',
  repr_detail: 'BM25 看字面重合，e5 向量看语义，两路名次用 RRF 融合。这句排在最前的候选：',
  repr_scores: 'BM25 {bm25} · e5 {dense}',
  recog_short: '判为{label}',
  recog_detail:
    'XLM-R 交叉编码器逐对读「句子—候选」，与 TF-IDF + 逻辑回归堆叠；资料里有可比的数字或限额时，再与规则按 α = 0.4 融合。',
  recog_rule: '这句规则参与了融合：{rule}。',
  recog_pairs: '这句没有可比的数字，由句对概率聚合得出。',
  rule_same: '数字与资料一致（{qty}）',
  rule_exceeds: '数字超出资料里的上限（{claim}，上限 {limit}）',
  rule_different: '数字与资料不同（写的是 {claim}，资料是 {stated}）',
  decide_short_decide: '直接判定',
  decide_short_defer: '送人工核验',
  decide_detail_decide:
    '直接判定的期望代价是 {cost}，低于送人工的 {defer}，所以识别器自己给出「{label}」。',
  decide_detail_defer:
    '直接判定的期望代价是 {cost}，高于送人工的 {defer}，所以这句标「待核验」，不计入扣分。',
  decide_costs: '代价：误扣分 3 · 错放 1 · 送人工 0.5。概率先在 dev 上做温度缩放校准。',
  gen_short_agree: '评审与识别器一致',
  gen_short_conservative: '仲裁：取更保守的{final}',
  gen_short_undecided: '仲裁：保留评审的标签',
  gen_short_none: '摘要进入评审输入',
  gen_summary: '进入评审输入的识别摘要：第 {i} 句 · {label} · 证据 {k} 条 · {decision}。',
  gen_agree: '评分项「{criterion}」：评审给「{judge}」，与识别器一致。',
  gen_conservative:
    '评分项「{criterion}」：评审给「{judge}」，识别器给「{rec}」，两者不一致，在规则界内取更保守的「{final}」。',
  gen_undecided:
    '评分项「{criterion}」：评审给「{judge}」，没有可比的标签；识别器给「{rec}」，保留评审的标签。',
  gen_none: '本次没有仲裁记录。',
  gen_peers: '另外两个生成器：同事拿到提问意图与回复依据核查；知识助手拿到范围检测、检索与漂移。',
  gen_peers_counts:
    '本局里，同事一侧有意图识别 {intent} 次、依据核查 {reply} 条；知识助手一侧有范围检测 {scope} 次、漂移 {drift} 次。',
  generator_judge: '评审',
  generator_roles: '同事',
  generator_assistant: '知识助手',

  lab_supported: '有依据',
  lab_contradicted: '与资料矛盾',
  lab_insufficient: '证据不足',
  dec_decide: '直接判定',
  dec_defer: '送人工',
  verdict_MET: '满足',
  verdict_PARTIAL: '部分满足',
  verdict_NOT_MET: '未满足',
  verdict_INSUFFICIENT: '证据不足',
  unit_pday: '{v} 人日',
  unit_person: '{v} 人',
  unit_cny: '{v} 元',
  unit_hour: '{v} 小时',
  unit_day: '{v} 天',
  unit_pct: '{v}%',
  unit_day_index: '第 {v} 天',

  regTitle: '七个识别器',
  regLead: '每个识别器只认一件事。指标都取自已发布的实验结果，写明测试集和语言。',
  covTitle: '课程要求的四类技术',
  cov_supervised: '监督／无监督学习',
  cov_supervised_items: '监督：关系判定、回复依据核查、提问意图。无监督：范围检测、行为识别。',
  cov_mldl: '机器学习／深度学习',
  cov_mldl_items: '深度学习：XLM-R 交叉编码器、e5 向量。机器学习：TF-IDF + 逻辑回归、DTW、HMM。',
  cov_hybrid: '集成／混合',
  cov_hybrid_items: '堆叠集成、与规则的晚期融合、RRF 检索融合、代价决策与评审仲裁。',
  cov_sensing: '智能感知',
  cov_sensing_items: '学员的操作事件流转成符号序列，供行为识别使用。',
  f_what: '识别什么',
  f_method: '方法',
  f_used: '用在',
  f_metric: '关键指标',

  c1_name: '关系判定',
  c1_what: '作品里的每一句话，和资料是支持、矛盾，还是证据不足。',
  c1_method: 'XLM-R 交叉编码器',
  c1_chain: '产品判定链：与 TF-IDF + 逻辑回归堆叠，再与数字限额规则晚期融合（α = 0.4）',
  c1_used: '评审输入、交付前预演',
  c1_step_xlmr: 'XLM-R 单独',
  c1_step_stack: '堆叠',
  c1_step_chain: '堆叠 + 规则（产品）',
  c1_m: '产品判定链 macro-F1|中 {zh} · 英 {en}',
  c1_set: 'relation-v3 test，断言级',

  c2_name: '证据检索',
  c2_what: '为每句话、每个提问，找出最相关的资料段落。',
  c2_method: 'BM25 + e5 向量，RRF 融合',
  c2_used: '评审的候选证据、同事选资料、知识助手回答',
  c2_m1: '句子找到金标证据 Recall@5（RRF）|中 {zh} · 英 {en}',
  c2_set1: 'relation-v3 test',
  c2_m2: '改写过的提问 Recall@5|e5 中 {dzh} · 英 {den}，RRF 中 {rzh} · 英 {ren}',
  c2_set2: '知识助手提问 test',

  c4_name: '范围与漂移检测',
  c4_what: '知识助手收到的提问在不在知识库范围内；政策更新后，回答里的数字有没有变。',
  c4_method: 'e5 向量 + 马氏距离单类，只用域内数据拟合；漂移看向量距离和数字变化',
  c4_used: '知识助手：域外问题转人工、标出漂移',
  c4_m1: '域外提问 AUROC|中 {zh} · 英 {en}',
  c4_set1: '知识助手提问 test',
  c4_m2: '公开数据 MASSIVE 上的 AUROC|中 {zh} · 英 {en}',
  c4_set2: 'E13',

  c5_name: '行为识别',
  c5_what:
    '学员这一局的操作顺序最像哪种策略、处在哪个阶段、有没有异常，比如政策更新后没复测就交付。',
  c5_method: 'DTW 1-NN 对照参考轨迹；HMM 推断阶段，用似然判异常',
  c5_used: '同事（当前阶段）、复盘里的「你的行为模式」',
  c5_m1: '步骤被扰动 50% 时认出策略的准确率（DTW）|{v}',
  c5_m2: '异常检测 AUROC（HMM 似然）|{v}',
  c5_set: '脚本策略轨迹 test，{n} 条，中英合计',

  c10_name: '同事回复依据核查',
  c10_what: '同事回复里的每句话有没有资料依据，有没有说出学员不该看到的私密信息。',
  c10_method: '检索取前 3 个单元，关系判定逐句判；私密资料再判一遍查泄露',
  c10_used: '同事回复下的核查署名',
  c10_m1: '三分类 macro-F1|{v}',
  c10_set1: '合成回复 test，中英',
  c10_m2: '真实大模型回答（RAGTruth）上的三分类 macro-F1|{v}，基本失效，见 E13 与 E15',

  c11_name: '提问意图',
  c11_what: '学员问同事的问题属于哪一类：问限制、问资源、问流程、求批准，或其他。',
  c11_method: 'TF-IDF 字符 2–4 gram + 逻辑回归',
  c11_used: '同事按意图组织回复',
  c11_m1: '准确率|中 {zh} · 英 {en}',
  c11_set: 'intent-v1 test',
  c11_m2: '没有模型时退回的关键词规则|中 {zh} · 英 {en}',

  c6_name: '代价决策与评审仲裁',
  c6_what: '哪些判定由识别器直接给出、哪些送人工；识别器和评审意见不一致时取哪一个。',
  c6_method: '校准后的概率按代价矩阵取期望代价最小；不一致时在规则界内取更保守的',
  c6_used: '评审：待核验排队、仲裁',
  c6_m1: '送人工 {r} 时的误扣分率|{before} → {after}',
  c6_set1: 'relation-v3 test，产品判定链',
  c6_m2: '评审与识别器的冲突率|{v}（按评审给出可比标签的 {k} 条计，共 {n} 条仲裁）',
  c6_set2: 'E8',

  cat_c1: '监督 · 深度学习',
  cat_chain: '集成 · 混合',
  cat_c2: '混合',
  cat_c4: '无监督',
  cat_c5: '机器学习 · 无监督',
  cat_c5_extra: '可加：智能感知',
  cat_c6: '统计决策 · 混合',
  cat_c10: '监督',
  cat_c11: '监督 · 经典机器学习',
  catLabel: '课程类别',
} as const;

export type Key = keyof typeof zh;

const en: Record<Key, string> = {
  title: 'System profile',
  docTitle: 'System profile · Practice',
  lead: 'For reviewers: what the system recognises in a learner’s work, how it does it, and the experiments behind each choice.',
  navLabel: 'On this page',
  navPipeline: 'One sentence, end to end',
  navRegister: 'Seven recognisers',
  navStory: 'The experiments',
  loading: 'Loading…',

  pipeTitle: 'One sentence, end to end',
  pipeLead: 'A sentence from this practice’s work, through each stage of the recognition layer.',
  pipeLeadExample:
    'This practice has no sentence-level records yet; they appear after a submission. The sentence below comes from a recorded run in the demo pack, and the numbers are that run’s actual recognition output.',
  exampleTag: 'Example',
  sentenceOf: 'Sentence {i} of {n}',
  pick: 'Pick another sentence',
  pickOption: 'Sentence {i} · {label}: {quote}',
  play: 'Play',
  replay: 'Replay',
  keysHint: 'Step through the stages with the arrow keys.',
  stationsLabel: 'The six stages of the recognition pipeline',
  fallbackNote:
    'Rule fallback: the relation model’s weights were not loaded, so the number-and-limit rule judged this sentence.',

  st_sense: 'Sense',
  st_prep: 'Pre-process',
  st_repr: 'Represent',
  st_recog: 'Recognise',
  st_decide: 'Decide',
  st_gen: 'Three generators',

  sense_short: 'Reads the submitted work',
  sense_detail:
    'At submission the whole work is read in. Test questions, colleague turns and the trail of the learner’s actions enter recognition here too.',
  sense_detail_counts:
    'At submission the whole work is read in. In the same practice this stage also took in {tests} test questions, {replies} colleague replies and the trail of the learner’s actions.',
  prep_short: 'Split: sentence {i} of {n}',
  prep_detail:
    'The work is split into {n} sentences; this is sentence {i}. The materials are cut into {m} evidence units. Each sentence is paired only with the candidates retrieval finds, not with every unit.',
  prep_detail_nounits:
    'The work is split into {n} sentences; this is sentence {i}. The materials are cut into evidence units, and each sentence is paired only with the candidates retrieval finds.',
  repr_short: 'Retrieved: {quote}',
  repr_short_none: 'No retrieval record',
  repr_detail:
    'BM25 scores word overlap, e5 vectors score meaning, and RRF fuses the two rankings. The top candidates for this sentence:',
  repr_scores: 'BM25 {bm25} · e5 {dense}',
  recog_short: 'Judged {label}',
  recog_detail:
    'An XLM-R cross-encoder reads each sentence–candidate pair and is stacked with TF-IDF + logistic regression; when the materials hold a comparable number or limit, a rule is fused in at α = 0.4.',
  recog_rule: 'The rule took part here: {rule}.',
  recog_pairs:
    'No comparable number here, so the label comes from the aggregated pair probabilities.',
  rule_same: 'the number matches the materials ({qty})',
  rule_exceeds: 'the number exceeds the stated limit ({claim}, limit {limit})',
  rule_different:
    'the number differs from the materials ({claim} written, {stated} in the materials)',
  decide_short_decide: 'Decides itself',
  decide_short_defer: 'Sends to a person',
  decide_detail_decide:
    'Deciding costs {cost} in expectation, below the {defer} of sending it to a person, so the recogniser gives “{label}” itself.',
  decide_detail_defer:
    'Deciding would cost {cost} in expectation, above the {defer} of sending it to a person, so the sentence is marked for review and never deducted.',
  decide_costs:
    'Costs: wrong deduction 3 · wrong pass 1 · to a person 0.5. Probabilities are temperature-calibrated on dev first.',
  gen_short_agree: 'Reviewer agrees',
  gen_short_conservative: 'Arbiter: the more cautious {final}',
  gen_short_undecided: 'Arbiter keeps the reviewer’s label',
  gen_short_none: 'Summary goes to the reviewer',
  gen_summary:
    'What enters the reviewer’s input: sentence {i} · {label} · {k} evidence units · {decision}.',
  gen_agree: 'Criterion “{criterion}”: the reviewer gave “{judge}”, the same as the recogniser.',
  gen_conservative:
    'Criterion “{criterion}”: the reviewer gave “{judge}” and the recogniser “{rec}”. They disagree, so the more cautious “{final}” within the rule bounds stands.',
  gen_undecided:
    'Criterion “{criterion}”: the reviewer gave “{judge}”, which is not a comparable label; the recogniser gave “{rec}”, and the reviewer’s label stands.',
  gen_none: 'No arbitration record in this practice.',
  gen_peers:
    'The other two generators: colleagues get question intent and reply grounding checks; the knowledge assistant gets scope, retrieval and drift.',
  gen_peers_counts:
    'In this practice colleagues got {intent} intent readings and {reply} grounding checks; the assistant got {scope} scope checks and {drift} drift checks.',
  generator_judge: 'Reviewer',
  generator_roles: 'Colleagues',
  generator_assistant: 'Knowledge assistant',

  lab_supported: 'supported',
  lab_contradicted: 'contradicts the materials',
  lab_insufficient: 'insufficient evidence',
  dec_decide: 'decided',
  dec_defer: 'to a person',
  verdict_MET: 'Met',
  verdict_PARTIAL: 'Partially met',
  verdict_NOT_MET: 'Not met',
  verdict_INSUFFICIENT: 'Insufficient evidence',
  unit_pday: '{v} person-days',
  unit_person: '{v} people',
  unit_cny: 'CNY {v}',
  unit_hour: '{v} hours',
  unit_day: '{v} days',
  unit_pct: '{v}%',
  unit_day_index: 'day {v}',

  regTitle: 'Seven recognisers',
  regLead:
    'Each recogniser recognises one thing. Every figure comes from the published results, with its test set and language.',
  covTitle: 'The four technique families in the course brief',
  cov_supervised: 'Supervised / unsupervised learning',
  cov_supervised_items:
    'Supervised: relation, reply grounding, question intent. Unsupervised: scope detection, behaviour.',
  cov_mldl: 'Machine learning / deep learning',
  cov_mldl_items:
    'Deep learning: the XLM-R cross-encoder, e5 vectors. Machine learning: TF-IDF + logistic regression, DTW, HMM.',
  cov_hybrid: 'Ensemble / hybrid',
  cov_hybrid_items:
    'Stacking, late fusion with a rule, RRF retrieval fusion, cost decision and arbitration.',
  cov_sensing: 'Intelligent sensing',
  cov_sensing_items:
    'The learner’s action events become a symbol sequence for behaviour recognition.',
  f_what: 'Recognises',
  f_method: 'Method',
  f_used: 'Feeds',
  f_metric: 'Key figures',

  c1_name: 'Relation',
  c1_what:
    'Whether each sentence of the work is supported by the materials, contradicts them, or lacks evidence.',
  c1_method: 'XLM-R cross-encoder',
  c1_chain:
    'Product chain: stacked with TF-IDF + logistic regression, then late-fused with the number-and-limit rule (α = 0.4)',
  c1_used: 'Reviewer input, pre-submission check',
  c1_step_xlmr: 'XLM-R alone',
  c1_step_stack: 'Stack',
  c1_step_chain: 'Stack + rule (product)',
  c1_m: 'Product chain macro-F1|zh {zh} · en {en}',
  c1_set: 'relation-v3 test, claim level',

  c2_name: 'Evidence retrieval',
  c2_what: 'Finds the most relevant material passages for each sentence and each question.',
  c2_method: 'BM25 + e5 vectors, fused by RRF',
  c2_used: 'Reviewer candidates, colleagues’ sources, assistant answers',
  c2_m1: 'Sentence → gold evidence, Recall@5 (RRF)|zh {zh} · en {en}',
  c2_set1: 'relation-v3 test',
  c2_m2: 'Paraphrased questions, Recall@5|e5 zh {dzh} · en {den}, RRF zh {rzh} · en {ren}',
  c2_set2: 'assistant questions test',

  c4_name: 'Scope and drift',
  c4_what:
    'Whether a question to the assistant is inside the knowledge base, and whether numbers in its answers changed after a policy update.',
  c4_method:
    'e5 vectors + one-class Mahalanobis distance, fitted on in-scope data only; drift compares vector distance and numbers',
  c4_used: 'Assistant: hands out-of-scope questions to a person, flags drift',
  c4_m1: 'Out-of-scope AUROC|zh {zh} · en {en}',
  c4_set1: 'assistant questions test',
  c4_m2: 'AUROC on public MASSIVE|zh {zh} · en {en}',
  c4_set2: 'E13',

  c5_name: 'Behaviour',
  c5_what:
    'Which strategy the learner’s sequence of actions resembles, which phase they are in, and whether anything is off, such as submitting without retesting after a policy update.',
  c5_method:
    'DTW 1-NN against reference trajectories; an HMM for phases, its likelihood for anomalies',
  c5_used: 'Colleagues (current phase), “Your pattern” in the review',
  c5_m1: 'Strategy accuracy with 50% of steps perturbed (DTW)|{v}',
  c5_m2: 'Anomaly AUROC (HMM likelihood)|{v}',
  c5_set: 'scripted-strategy trajectories test, {n} runs, both languages',

  c10_name: 'Reply grounding',
  c10_what:
    'Whether each sentence of a colleague’s reply is grounded in the materials, and whether it leaks something the learner should not see.',
  c10_method:
    'Top-3 units from retrieval, judged sentence by sentence; the private facts are checked the same way for leaks',
  c10_used: 'The signature under each colleague reply',
  c10_m1: 'Three-way macro-F1|{v}',
  c10_set1: 'synthetic replies test, zh and en',
  c10_m2:
    'Three-way macro-F1 on real LLM answers (RAGTruth)|{v}, close to failing; see E13 and E15',

  c11_name: 'Question intent',
  c11_what:
    'Which kind of question the learner asks a colleague: a limit, resources, process, approval, or other.',
  c11_method: 'TF-IDF character 2–4-grams + logistic regression',
  c11_used: 'Colleagues shape their reply to the intent',
  c11_m1: 'Accuracy|zh {zh} · en {en}',
  c11_set: 'intent-v1 test',
  c11_m2: 'Keyword rule used when no model is loaded|zh {zh} · en {en}',

  c6_name: 'Cost decision and arbitration',
  c6_what:
    'Which judgements the recogniser makes itself and which go to a person, and whose label stands when the recogniser and the reviewer disagree.',
  c6_method:
    'Calibrated probabilities, then the lowest expected cost under a cost matrix; on disagreement, the more cautious label within the rule bounds',
  c6_used: 'Reviewer: review queue, arbitration',
  c6_m1: 'Wrong-deduction rate when {r} go to a person|{before} → {after}',
  c6_set1: 'relation-v3 test, product chain',
  c6_m2:
    'Reviewer–recogniser conflict rate|{v}, over the {k} of {n} arbitrations where the reviewer gave a comparable label',
  c6_set2: 'E8',

  cat_c1: 'Supervised · deep learning',
  cat_chain: 'Ensemble · hybrid',
  cat_c2: 'Hybrid',
  cat_c4: 'Unsupervised',
  cat_c5: 'Machine learning · unsupervised',
  cat_c5_extra: 'also: intelligent sensing',
  cat_c6: 'Statistical decision · hybrid',
  cat_c10: 'Supervised',
  cat_c11: 'Supervised · classical ML',
  catLabel: 'Course family',
};

export const COPY: CopyTable<Key> = { zh, en };

export const tr = (language: Language, key: Key, values: Record<string, string | number> = {}) =>
  copyText(COPY, language, key, values);
