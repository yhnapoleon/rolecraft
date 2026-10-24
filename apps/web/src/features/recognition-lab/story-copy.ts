/** Copy for the experiment story: what we asked → how → what we found → what the product
 * does with it. Every figure is a `{name}` placeholder filled from the published results
 * (see story.ts); the two languages carry the same keys. */
import { copyText, type CopyTable, type Language } from '../results-native/localization';

const zh = {
  storyTitle: '实验故事线',
  storyLead: '每个实验按四步读：问了什么、怎么做、发现了什么、所以产品里怎么用。',
  ch1Title: '在自建数据上选方法',
  ch1Range: 'E1–E10',
  ch1Lead:
    '数据来自 pm_pilot 场景：资料是场景材料，断言由 DeepSeek 生成，行为轨迹由脚本策略在真实后端上跑出。',
  ch2Title: '换到真实数据',
  ch2Range: 'E11 → E14 → E15',
  ch2Lead: '自建数据上的分数，换到人写的文本还站得住吗？这条线找到了答案、原因和改法。',
  q: '问了什么',
  how: '怎么做',
  found: '发现了什么',
  use: '所以产品里',
  mainline: '主线',
  branch: '旁支',
  offline: '离线评测，产品未换',
  table: '表格视图',
  missing: '这项实验的结果还没有发布到页面。',
  zh: '中文',
  en: '英文',
  all: '中英合计',
  macroF1: 'macro-F1',

  e1_title: '关系判定选哪个模型',
  e1_q: '哪种模型最会判断一句话和资料的关系：支持、矛盾，还是证据不足？',
  e1_how:
    '在 relation-v3 上比 7 种经典模型、3 种集成（bagging、AdaBoost、随机森林）、XLM-R 交叉编码器，以及 TF-IDF + 逻辑回归与 XLM-R 的堆叠；断言级 macro-F1，分语言。',
  e1_found:
    '堆叠最好：中 {stack_zh} / 英 {stack_en}。XLM-R 单独 {c1_zh} / {c1_en}；最好的经典模型（TF-IDF + 人工特征的逻辑回归）{lr_zh} / {lr_en}。',
  e1_use: '关系判定用堆叠。',
  e1_chart: 'E1 · 各模型 macro-F1（relation-v3 test，中文与英文）',
  e1_cm: 'E1 · XLM-R 关系判定混淆矩阵（relation-v3 test，中英合计）',

  e10_title: '数字和限额，交给规则',
  e10_q: '数字和限额类的句子模型常判错，规则能补上吗？',
  e10_how:
    '规则在资料里找到可比的数字时，和模型概率按 α 加权（晚期融合）；α 在 dev 上用五折外预测选，几乎打平时取最小。早期融合要重训编码器，没有做。',
  e10_found:
    '规则单独只有 {rule_all}，但「引用旧版本」这类现象模型全错、规则全对（XLM-R {c1_old}，规则 {rule_old}）。加规则后，XLM-R {c1_all} → {c1r_all}；堆叠 {st_all} → {str_all}，整体持平。',
  e10_use:
    '产品判定链 = 堆叠 + 规则（α = 0.4）：dev 上几乎不损失，换来规则在它能比对的数字上说了算，结果可以解释。',
  e10_chart: 'E1-S · 产品判定链各环节 macro-F1（relation-v3 test）',
  e10_ph: 'E10 · 分现象准确率：XLM-R、规则与晚期融合（relation-v3 test，中英合计）',

  e4_title: '没把握时送人工',
  e4_q: '识别器没把握时，该不该自己下结论？',
  e4_how:
    '在 dev 上做温度缩放校准，再按代价矩阵（误扣分 3、错放 1、送人工 0.5）取期望代价最小，画误差—拒识曲线。',
  e4_found: '校准后 ECE {ece0} → {ece1}。产品判定链送人工 20% 时，误扣分率从 {wd0} 降到 {wd20}。',
  e4_use: '期望代价高于送人工的句子标「待核验」，不计入扣分；待核验按期望代价排队。',
  e4_chart: 'E4 · XLM-R 的误差—拒识曲线：期望代价最高的先送人工（relation-v3 test）',
  rejectRate: '送人工比例',
  errorRate: '剩余错误率',
  wrongDeduction: '误扣分率',

  e3_title: '找证据：字面、语义，还是两路融合',
  e3_q: '一句话或一个提问，怎样找到对应的资料段落？',
  e3_how:
    'BM25、e5 向量、RRF 融合，在两种金标上比：句子 → 金标证据单元；知识助手提问 → 来源单元，分直述和改写两种。',
  e3_found:
    '句子找证据三种方法都很高（RRF 中 {rel_zh} / 英 {rel_en}），直述提问也都接近满分；差别在改写过的提问：e5 {d_zh} / {d_en}，RRF {r_zh} / {r_en}，BM25 {b_zh} / {b_en}。',
  e3_use: '作品逐句找证据用 RRF；知识助手的提问检索用 e5 向量。',
  e3_chart: 'E3 · 改写过的提问 Recall@5（知识助手提问 test）',

  e5_title: '问题是不是超出了知识库',
  e5_q: '知识助手怎么知道一个问题超出了知识库？',
  e5_how:
    '只用域内的知识库单元和改写问题，拟合 e5 向量的马氏距离（Ledoit-Wolf 收缩协方差），阈值取 dev 上域内 95% 分位；和六种方法对照。',
  e5_found: 'AUROC 中 {m_zh} / 英 {m_en}，和最近邻余弦（{c_zh} / {c_en}）相当，高于其余五种。',
  e5_use: '范围检测用马氏距离：只要域内数据和一个阈值，结果能解释成「离知识库有多远」。',
  e5_chart: 'E5 · 域外检测 AUROC：马氏距离与六种对照（知识助手提问 test）',
  e5_pca: 'E5 · e5 向量的二维投影（中文）：知识库单元、域内问题、域外问题',
  units: '知识库单元',
  inDomain: '域内问题',
  outDomain: '域外问题',

  e6_title: '从操作序列认出策略',
  e6_q: '能不能从学员的操作序列认出策略、阶段和异常？',
  e6_how:
    '8 种脚本策略在真实后端上跑出轨迹（训练 {ntrain} 条、测试 {ntest} 条）。DTW 1-NN、编辑距离 1-NN、n-gram 随机森林认策略；HMM 认阶段（状态数按 BIC 选）；异常比 HMM 似然、到参考轨迹的 DTW 距离和 Isolation Forest。',
  e6_found:
    '不扰动时 DTW 和随机森林都是 {d0}；步骤被随机扰动 50% 时 DTW {d50}、随机森林 {rf50}。异常 AUROC：HMM {hmm}、DTW 距离 {dtwa}、Isolation Forest {iso}。',
  e6_use: '行为识别用 DTW 认策略，用 HMM 认阶段和异常。',
  e6_chart: 'E6 · 步骤被随机扰动时的策略准确率（脚本轨迹 test）',
  e6_anom: 'E6 · 轨迹异常检测 AUROC（脚本轨迹 test）',
  noise: '扰动概率',

  e7_title: '学员在问什么',
  e7_q: '同事怎么知道学员在问什么？',
  e7_how:
    'TF-IDF 字符 2–4 gram + 逻辑回归，一个模型管中英；对照朴素贝叶斯、线性 SVM 和关键词规则。',
  e7_found:
    '逻辑回归准确率中 {lr_zh} / 英 {lr_en}，线性 SVM（{svm_zh} / {svm_en}）接近，关键词规则只有 {kw_zh} / {kw_en}。',
  e7_use: '提问意图用逻辑回归；没加载模型时退回关键词规则。',
  e7_chart: 'E7 · 提问意图准确率（intent-v1 test）',
  e7_cm: 'E7 · 逻辑回归意图混淆矩阵（intent-v1 test，中英合计）',

  e8_title: '识别摘要进了评审输入之后',
  e8_q: '把识别摘要放进评审输入，评审会不一样吗？',
  e8_how: '同样 {pairs} 对脚本提交，识别层开、关各跑一次 DeepSeek 评审，逐项比。',
  e8_found:
    '给出标签的比例 {on} 对 {off}，两种条件的标签一致率 {agree}；在「判断的证据支持」一项上，评审与识别器的冲突率 {conflict}。',
  e8_use: '识别摘要进入评审输入；两者冲突时按仲裁规则取保守。',
  e8_chart: 'E8 · 评审输入里有无识别摘要（同一批提交）',
  labelled: '给出标签的比例',
  pending: '待核验比例',
  recOn: '有识别摘要',
  recOff: '无识别摘要',

  e9_title: '换一个场景还能用吗',
  e9_q: '换一个场景（IT 工单助手），这些识别器还能用吗？',
  e9_how:
    'pm_pilot 上做的检索、范围检测、关系判定，直接用在 it_ticket_pilot 的 test 上；范围检测另试只用 IT 知识库单元重新拟合。',
  e9_found:
    '范围检测离不开本场景：pm 的拟合直接搬过去 AUROC 只有 {pm_zh} / {pm_en}，只用 IT 知识库单元重拟合就回到 {it_zh} / {it_en}。检索不用训练，改写问题 e5 Recall@5 {r_zh} / {r_en}；关系判定 macro-F1 {c1_zh} / {c1_en}。',
  e9_use: '每个场景包带自己的范围拟合；检索与关系判定跨场景复用。',
  e9_chart: 'E9 · pm_pilot 上做的识别器用在 it_ticket_pilot（test）',
  pmFit: '范围检测 · pm 拟合 · AUROC',
  itFit: '范围检测 · 只用 IT 单元 · AUROC',
  itRecall: 'e5 检索改写问题 · Recall@5',
  itC1: '关系判定 · macro-F1',

  e11_title: '换成人写的断言',
  e11_q: '在人写的断言上，产品判定链还站得住吗？',
  e11_how:
    '不重训，直接评五份 test：自建的 relation-v3；DeepSeek 断言配真实证据（public-synth）；人写断言 ContractNLI（合同，英文）、VitaminC（维基，英文）、CFEVER（维基，中文）。',
  e11_found:
    '证据换成真实文本问题不大（public-synth {synth}，自建 {v3}）；断言换成人写的，掉到 {cnli} / {vit} / {cf}，接近三分类随机。差距集中在矛盾类，F1 只有 {cnli_c} / {vit_c} / {cf_c}。',
  e11_use: '识别器学到的是生成数据里断言的写法。产品先不改，查原因（E14）。',
  e11_chart: 'E11 · 产品判定链直接用在五份 test 上',
  contraF1: '矛盾类 F1',

  e12_title: '只在浅层补真实数据',
  e12_q: '只在浅层（词法逻辑回归、堆叠的元学习器）补真实数据，能补回来吗？',
  e12_how:
    '把三份真实数据的 train / dev 加进去，重拟合词法逻辑回归和元学习器，XLM-R 不重训；四组：只用自建、全混、按来源加权混、留一来源。',
  e12_found:
    'ContractNLI 升到 {cnli_mix} / {cnli_bal}（全混 / 加权混），自建数据却从 {v3} 掉到 {v3_mix} / {v3_bal}；VitaminC、CFEVER 变化不大。留一来源时，ContractNLI {cnli_loso}、VitaminC {vit_loso} 比只用自建还低。',
  e12_use: '产品不换。XLM-R 的句对概率在人写断言上没用，元学习器救不回来，问题在更深一层。',
  e12_chart: 'E12 · 混训后的产品判定链 macro-F1（α = 0.4）',
  v3Only: '只用自建',
  mixAll: '全混',
  mixBalanced: '加权混',
  loso: '留一来源',

  e14_title: '错在哪一步',
  e14_q: '错在哪一步？是模型错了，还是标签错了？',
  e14_how:
    '一是读 E11 的句对缓存，看 XLM-R 对金标证据那一对认没认出，再看截断和矛盾线索；二是每份真实数据取三个最大错误桶各 30 条、随机对照 40 条，让 DeepSeek 看同样的候选、不看标签重判。',
  e14_found:
    '句对这一步就认不出：ContractNLI 支持对只认出 {cnli_s}、矛盾对 {cnli_c}；VitaminC 矛盾对 {vit_c}。截断不是主因（金标句对超长：ContractNLI {t_c}，VitaminC {t_v}，CFEVER {t_f}）。自建数据的矛盾 {v3_cue} 带数字或否定线索，VitaminC、CFEVER 只有 {vit_cue} / {cf_cue}。复核里错误桶站金标的比例（{cnli_b}、{vit_b}、{cf_b}）和随机对照（{cnli_k}、{vit_k}、{cf_k}）相当，绝大多数是模型真错。',
  e14_use:
    '问题在句对分类器本身：它把「矛盾」学成了「数字和否定」。下一步换一个学过推理关系的句对模型。',
  e14_chart: 'E14 · XLM-R 对金标证据句对的认出率（各 test）',
  e14_review: 'E14 · DeepSeek 盲判复核：同意金标的比例',
  supportPairs: '支持对认出',
  contraPairs: '矛盾对认出',
  control: '随机对照',
  buckets: '错误桶',

  e15_title: '换一个学过推理的句对模型',
  e15_q: '换一个已经学过「蕴含、中立、矛盾」的句对模型会怎样？',
  e15_how:
    '句对分类器换成多语言 NLI 交叉编码器 mDeBERTa-v3（在 XNLI 等多语言推理数据上训过，含中文）。先零样本直接用，再用 relation-v3 全部 train 加三份真实 train 的抽样混合微调 1 轮。',
  e15_found:
    '零样本五份全涨（VitaminC {vit_e11} → {vit_zs}）。混合微调后自建 {v3_mix}、ContractNLI {cnli_mix}、VitaminC {vit_mix}、CFEVER {cf_mix}、public-synth {syn_mix}，不再是 E12 那样「真实涨、自建掉」。用到回复核查、三个单元拼成一段读：合成回复 {syn0} → {syn1}，RAGTruth AUROC {rag0} → {rag1}。',
  e15_use:
    '这是离线评测的升级版句对分类器，产品里仍是堆叠 + 规则，还没换。限制：只训 1 轮，没做留一来源；ContractNLI 只有 17 条固定假设，{cnli_mix} 是「没见过的合同」，不是新断言；底座的训练数据含 FEVER，和 VitaminC、CFEVER 同属维基体裁。',
  e15_chart: 'E15 · 三种句对分类器在五份 test 上的 macro-F1',
  e15_reply: 'E15 · 回复核查：产品与 NLI（三个单元拼成一段读）',
  productChain: '产品判定链（E11）',
  nliZs: 'NLI 零样本',
  nliMix: 'NLI 混合微调',
  ragAuroc: 'RAGTruth AUROC',
  synthF1: '合成回复 macro-F1',
  productReply: '产品',

  e13_title: '其他识别器换到公开数据',
  e13_q: '其他识别器换到公开数据上表现如何？',
  e13_how:
    '范围检测、检索、行为、意图、回复核查各找真实数据或基于真实材料的数据（CLINC150、MASSIVE、PrivacyQA、tau-bench、Jira、RAGTruth 等）；能重拟合的，按同一方法在公开 train 上重拟合。',
  e13_found:
    '范围检测：MASSIVE 中 {mz} / 英 {me}；CLINC150 只有 {clinc}，用上意图标签的最大 softmax 到 {clinc_sm}，最近邻余弦在每一份上都不比马氏距离差。检索：PrivacyQA 上 e5 Recall@5 {pq_d}、RRF {pq_r}。行为：tau-bench 成败识别每类 HMM {tau_hmm}，产品的 DTW {tau_dtw}；Jira 关单前的序列预测不了结局，只看长度反而最好（{jira_len}）。回复核查：RAGTruth 三分类只有 {rag}（见 E15）。',
  e13_use:
    '检索和范围检测换到真实数据仍站得住，但最好的方法会变（检索用 e5、范围用最近邻余弦）；产品暂不换，记作后续。',
  e13_chart: 'E13 · 公开数据上的域外检测 AUROC',
  mahalanobis: '马氏距离（产品）',
  maxCosine: '最近邻余弦',
  maxSoftmax: '最大 softmax',
  massiveZh: 'MASSIVE 中文',
  massiveEn: 'MASSIVE 英文',
  synthZh: '合成提问 中文',
  synthEn: '合成提问 英文',
} as const;

export type StoryKey = keyof typeof zh;

const en: Record<StoryKey, string> = {
  storyTitle: 'The experiments',
  storyLead:
    'Each experiment reads in four steps: what we asked, how, what we found, and what the product does with it.',
  ch1Title: 'Choosing methods on our own data',
  ch1Range: 'E1–E10',
  ch1Lead:
    'Data from the pm_pilot scenario: its own materials, claims generated by DeepSeek, and trajectories from scripted strategies run against the real backend.',
  ch2Title: 'Moving to real data',
  ch2Range: 'E11 → E14 → E15',
  ch2Lead:
    'Do the scores on our own data hold on text people wrote? This line found the answer, the cause and a fix.',
  q: 'What we asked',
  how: 'How',
  found: 'What we found',
  use: 'So the product',
  mainline: 'Main line',
  branch: 'Side branch',
  offline: 'Offline evaluation; the product has not switched',
  table: 'Table view',
  missing: 'This experiment’s results are not published to the page yet.',
  zh: 'Chinese',
  en: 'English',
  all: 'Both languages',
  macroF1: 'macro-F1',

  e1_title: 'Which model judges relations',
  e1_q: 'Which model best judges how a sentence relates to the materials: supported, contradicted or insufficient?',
  e1_how:
    'On relation-v3 we compared 7 classical models, 3 ensembles (bagging, AdaBoost, random forest), an XLM-R cross-encoder, and a stack of TF-IDF + logistic regression with XLM-R; claim-level macro-F1 by language.',
  e1_found:
    'The stack is best: zh {stack_zh} / en {stack_en}. XLM-R alone reaches {c1_zh} / {c1_en}; the best classical model (logistic regression on TF-IDF plus hand-made features) {lr_zh} / {lr_en}.',
  e1_use: 'judges relations with the stack.',
  e1_chart: 'E1 · macro-F1 per model (relation-v3 test, Chinese and English)',
  e1_cm: 'E1 · XLM-R relation confusion matrix (relation-v3 test, both languages)',

  e10_title: 'Leave numbers and limits to a rule',
  e10_q: 'Models often misjudge sentences about numbers and limits. Can a rule help?',
  e10_how:
    'When the rule finds a comparable number in the materials, its verdict is weighted with the model’s probabilities by α (late fusion); α is chosen on out-of-fold dev predictions, smallest among near-ties. Early fusion would need retraining the encoder and was not run.',
  e10_found:
    'The rule alone reaches only {rule_all}, yet on phenomena such as citing an old version the model is always wrong and the rule always right (XLM-R {c1_old}, rule {rule_old}). With the rule, XLM-R goes {c1_all} → {c1r_all} and the stack {st_all} → {str_all}: level overall.',
  e10_use:
    'uses stack + rule (α = 0.4): almost no cost on dev, and the rule has the final say on the numbers it can compare, so the result can be explained.',
  e10_chart: 'E1-S · macro-F1 along the product chain (relation-v3 test)',
  e10_ph:
    'E10 · Accuracy by phenomenon: XLM-R, the rule and late fusion (relation-v3 test, both languages)',

  e4_title: 'Unsure? Send it to a person',
  e4_q: 'When the recogniser is unsure, should it decide anyway?',
  e4_how:
    'Temperature scaling on dev, then the lowest expected cost under a cost matrix (wrong deduction 3, wrong pass 1, to a person 0.5), traced as an error–reject curve.',
  e4_found:
    'Calibration takes ECE from {ece0} to {ece1}. With 20% sent to a person, the product chain’s wrong-deduction rate falls from {wd0} to {wd20}.',
  e4_use:
    'marks sentences whose expected cost exceeds a person’s as “for review”, never deducts for them, and queues them by expected cost.',
  e4_chart:
    'E4 · XLM-R error–reject curve: highest expected cost goes to a person first (relation-v3 test)',
  rejectRate: 'share sent to a person',
  errorRate: 'remaining error rate',
  wrongDeduction: 'wrong-deduction rate',

  e3_title: 'Finding evidence: words, meaning, or both',
  e3_q: 'How do we find the material passage behind a sentence or a question?',
  e3_how:
    'BM25, e5 vectors and RRF fusion against two gold sets: sentence → gold evidence unit, and assistant question → source unit, asked directly or paraphrased.',
  e3_found:
    'All three find evidence for sentences well (RRF zh {rel_zh} / en {rel_en}) and are near perfect on direct questions; paraphrased questions separate them: e5 {d_zh} / {d_en}, RRF {r_zh} / {r_en}, BM25 {b_zh} / {b_en}.',
  e3_use:
    'retrieves evidence for each sentence with RRF and answers assistant questions with e5 vectors.',
  e3_chart: 'E3 · Paraphrased questions, Recall@5 (assistant questions test)',

  e5_title: 'Is the question outside the knowledge base?',
  e5_q: 'How does the knowledge assistant know a question is outside its knowledge base?',
  e5_how:
    'A Mahalanobis distance on e5 vectors (Ledoit-Wolf shrunk covariance) fitted only on in-scope units and paraphrased questions, with the threshold at the 95% in-scope quantile on dev; six alternatives alongside.',
  e5_found:
    'AUROC zh {m_zh} / en {m_en}, on a par with nearest-neighbour cosine ({c_zh} / {c_en}) and above the other five.',
  e5_use:
    'detects scope with the Mahalanobis distance: in-scope data and one threshold are enough, and the score reads as “how far from the knowledge base”.',
  e5_chart:
    'E5 · Out-of-scope AUROC: Mahalanobis distance and six alternatives (assistant questions test)',
  e5_pca:
    'E5 · 2-D projection of e5 vectors (Chinese): KB units, in-scope and out-of-scope questions',
  units: 'KB units',
  inDomain: 'in-scope questions',
  outDomain: 'out-of-scope questions',

  e6_title: 'Recognising strategy from actions',
  e6_q: 'Can we recognise a learner’s strategy, phase and anomalies from their sequence of actions?',
  e6_how:
    'Eight scripted strategies run against the real backend ({ntrain} training and {ntest} test runs). DTW 1-NN, edit-distance 1-NN and an n-gram random forest recognise the strategy; an HMM (states chosen by BIC) the phase; anomalies compare HMM likelihood, DTW distance to the references, and Isolation Forest.',
  e6_found:
    'Unperturbed, DTW and the random forest both score {d0}; with 50% of steps randomly perturbed, DTW {d50} and the random forest {rf50}. Anomaly AUROC: HMM {hmm}, DTW distance {dtwa}, Isolation Forest {iso}.',
  e6_use: 'recognises strategy with DTW and phases and anomalies with the HMM.',
  e6_chart: 'E6 · Strategy accuracy as steps are randomly perturbed (scripted trajectories test)',
  e6_anom: 'E6 · Trajectory anomaly AUROC (scripted trajectories test)',
  noise: 'perturbation probability',

  e7_title: 'What is the learner asking?',
  e7_q: 'How do colleagues know what the learner is asking?',
  e7_how:
    'TF-IDF character 2–4-grams + logistic regression, one model for both languages; naive Bayes, a linear SVM and the keyword rule alongside.',
  e7_found:
    'Logistic regression reaches zh {lr_zh} / en {lr_en} accuracy, the linear SVM is close ({svm_zh} / {svm_en}), and the keyword rule only {kw_zh} / {kw_en}.',
  e7_use:
    'recognises intent with logistic regression and falls back to the keyword rule when no model is loaded.',
  e7_chart: 'E7 · Question-intent accuracy (intent-v1 test)',
  e7_cm: 'E7 · Logistic-regression intent confusion matrix (intent-v1 test, both languages)',

  e8_title: 'With the recognition summary in the reviewer’s input',
  e8_q: 'Does the reviewer behave differently with the recognition summary in its input?',
  e8_how:
    'The same {pairs} scripted submission pairs, judged by the DeepSeek reviewer once with the recognition layer on and once off, compared item by item.',
  e8_found:
    'Share of items given a label: {on} vs {off}; label agreement between the conditions {agree}; on “Evidence supporting judgments” the reviewer and the recogniser conflict in {conflict} of decided cases.',
  e8_use:
    'puts the recognition summary in the reviewer’s input and arbitrates conflicts toward the more cautious label.',
  e8_chart: 'E8 · The reviewer with and without the recognition summary (same submissions)',
  labelled: 'labelled share',
  pending: 'pending-review share',
  recOn: 'with summary',
  recOff: 'without summary',

  e9_title: 'Does it carry to another scenario?',
  e9_q: 'Do these recognisers still work in another scenario (an IT ticket assistant)?',
  e9_how:
    'Retrieval, scope detection and relation built on pm_pilot, applied to the it_ticket_pilot test; scope detection is also refitted on the IT knowledge-base units alone.',
  e9_found:
    'Scope detection belongs to its scenario: the pm fit carried over reaches only {pm_zh} / {pm_en} AUROC, and refitting on the IT units alone restores {it_zh} / {it_en}. Retrieval needs no training (paraphrases, e5 Recall@5 {r_zh} / {r_en}); relation macro-F1 is {c1_zh} / {c1_en}.',
  e9_use:
    'ships its own scope fit in each scenario pack and reuses retrieval and relation across scenarios.',
  e9_chart: 'E9 · Recognisers built on pm_pilot, used on it_ticket_pilot (test)',
  pmFit: 'Scope · pm fit · AUROC',
  itFit: 'Scope · IT units only · AUROC',
  itRecall: 'e5 retrieval, paraphrases · Recall@5',
  itC1: 'Relation · macro-F1',

  e11_title: 'Claims written by people',
  e11_q: 'Does the product chain hold on claims written by people?',
  e11_how:
    'No retraining; five test sets as they are: our relation-v3; DeepSeek claims against real evidence (public-synth); human claims from ContractNLI (contracts, English), VitaminC (Wikipedia, English) and CFEVER (Wikipedia, Chinese).',
  e11_found:
    'Real evidence text is not the problem (public-synth {synth}, ours {v3}); human claims drop it to {cnli} / {vit} / {cf}, close to three-way chance. The gap sits in contradictions, with F1 of only {cnli_c} / {vit_c} / {cf_c}.',
  e11_use:
    'stays as it is for now: the recognisers learned how generated claims are written, so the next step is finding where it breaks (E14).',
  e11_chart: 'E11 · The product chain applied to five test sets',
  contraF1: 'contradiction F1',

  e12_title: 'Adding real data to the shallow layers only',
  e12_q:
    'Can real data added only to the shallow layers (the lexical logistic regression and the stack’s meta-learner) win it back?',
  e12_how:
    'The three real sets’ train / dev splits are added and the lexical logistic regression and meta-learner refitted, with XLM-R unchanged; four variants: ours only, all mixed, mixed with per-source weights, and leave one source out.',
  e12_found:
    'ContractNLI rises to {cnli_mix} / {cnli_bal} (mixed / weighted) while our own data falls from {v3} to {v3_mix} / {v3_bal}; VitaminC and CFEVER barely move. Left out, ContractNLI ({cnli_loso}) and VitaminC ({vit_loso}) score below the ours-only model.',
  e12_use:
    'does not switch. XLM-R’s pair probabilities are no use on human claims and the meta-learner cannot rescue them: the problem lies deeper.',
  e12_chart: 'E12 · Product-chain macro-F1 after mixed training (α = 0.4)',
  v3Only: 'ours only',
  mixAll: 'all mixed',
  mixBalanced: 'weighted mix',
  loso: 'source left out',

  e14_title: 'Where does it break?',
  e14_q: 'Which step fails? Is the model wrong, or the label?',
  e14_how:
    'First, read the E11 pair cache: did XLM-R recognise the gold-evidence pair, and do truncation or contradiction cues explain it? Second, per real set, 30 claims from each of the three largest error buckets and 40 random controls re-judged by DeepSeek with the same candidates and no labels.',
  e14_found:
    'The pair step already fails: on ContractNLI XLM-R recognises only {cnli_s} of supporting pairs and {cnli_c} of contradicting ones; on VitaminC {vit_c} of contradicting pairs. Truncation is not the cause (gold pairs over length: ContractNLI {t_c}, VitaminC {t_v}, CFEVER {t_f}). Of our own contradictions {v3_cue} carry a number or negation cue, against {vit_cue} / {cf_cue} in VitaminC and CFEVER. In review, the reviewer sides with the gold label in error buckets ({cnli_b}, {vit_b}, {cf_b}) about as often as in the random controls ({cnli_k}, {vit_k}, {cf_k}): almost all are real model errors.',
  e14_use:
    'needs a different pair classifier: XLM-R learned “contradiction” as “numbers and negation”. Next, a pair model that has learned inference.',
  e14_chart: 'E14 · XLM-R recognition rate on gold-evidence pairs (each test set)',
  e14_review: 'E14 · DeepSeek blind review: share agreeing with the gold label',
  supportPairs: 'supporting pairs recognised',
  contraPairs: 'contradicting pairs recognised',
  control: 'random control',
  buckets: 'error buckets',

  e15_title: 'A pair model that has learned inference',
  e15_q: 'What if the pair classifier already knows entailment, neutral and contradiction?',
  e15_how:
    'The pair classifier becomes a multilingual NLI cross-encoder, mDeBERTa-v3 (trained on XNLI and other multilingual inference data, Chinese included): first zero-shot, then fine-tuned for one epoch on all of relation-v3 train plus samples of the three real train sets.',
  e15_found:
    'Zero-shot lifts all five (VitaminC {vit_e11} → {vit_zs}). After mixed fine-tuning: ours {v3_mix}, ContractNLI {cnli_mix}, VitaminC {vit_mix}, CFEVER {cf_mix}, public-synth {syn_mix}; no longer E12’s “real up, ours down”. In reply grounding, reading three units as one passage: synthetic replies {syn0} → {syn1}, RAGTruth AUROC {rag0} → {rag1}.',
  e15_use:
    'still runs stack + rule: this upgraded pair classifier is an offline evaluation and has not been switched in. Limits: one epoch, no leave-one-source-out; ContractNLI has only 17 fixed hypotheses, so {cnli_mix} means unseen contracts, not new claims; the base model’s training data includes FEVER, the same Wikipedia genre as VitaminC and CFEVER.',
  e15_chart: 'E15 · macro-F1 of three pair classifiers on five test sets',
  e15_reply: 'E15 · Reply grounding: the product vs NLI reading three units as one passage',
  productChain: 'product chain (E11)',
  nliZs: 'NLI zero-shot',
  nliMix: 'NLI mixed fine-tune',
  ragAuroc: 'RAGTruth AUROC',
  synthF1: 'synthetic replies macro-F1',
  productReply: 'product',

  e13_title: 'The other recognisers on public data',
  e13_q: 'How do the other recognisers do on public data?',
  e13_how:
    'Scope, retrieval, behaviour, intent and reply grounding each get real data or data built on real materials (CLINC150, MASSIVE, PrivacyQA, tau-bench, Jira, RAGTruth and others); methods that can be refitted are refitted on the public train split.',
  e13_found:
    'Scope: MASSIVE zh {mz} / en {me}; CLINC150 only {clinc}, where max softmax with intent labels reaches {clinc_sm}, and nearest-neighbour cosine is never below Mahalanobis on any set. Retrieval: on PrivacyQA e5 Recall@5 {pq_d}, RRF {pq_r}. Behaviour: tau-bench success / failure by per-class HMM {tau_hmm}, the product’s DTW {tau_dtw}; Jira outcomes cannot be predicted before closing, and sequence length alone does best ({jira_len}). Reply grounding: RAGTruth three-way only {rag} (see E15).',
  e13_use:
    'keeps its methods for now: retrieval and scope hold on real data, but the best method changes (e5 for retrieval, nearest-neighbour cosine for scope), noted as follow-up.',
  e13_chart: 'E13 · Out-of-scope AUROC on public data',
  mahalanobis: 'Mahalanobis (product)',
  maxCosine: 'nearest-neighbour cosine',
  maxSoftmax: 'max softmax',
  massiveZh: 'MASSIVE Chinese',
  massiveEn: 'MASSIVE English',
  synthZh: 'synthetic questions zh',
  synthEn: 'synthetic questions en',
};

export const STORY_COPY: CopyTable<StoryKey> = { zh, en };

export const st = (
  language: Language,
  key: StoryKey,
  values: Record<string, string | number> = {},
) => copyText(STORY_COPY, language, key, values);
