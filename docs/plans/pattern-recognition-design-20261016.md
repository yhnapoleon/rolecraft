# RoleCraft 模式识别层：完整设计

日期：2026-10-16　基于：`origin/main` 319c2a9　前置文档：[选型](pattern-recognition-selection-20261016.md)、[定位调研](pattern-recognition-positioning-research-20261016.md)、[交接](handover-pattern-recognition-20261016.md)。本文取代选型文档第 4 节和交接文档第 5 节，成为唯一执行依据；与前两份冲突时以本文为准。

写给实现的 coding agent 和组员。每个模块给出：目的、接入点（文件与函数，10-16 读源码核实）、输入输出契约、算法、数据、验收标准。没有时间锚点，只有依赖顺序。

## 0. 目的与原则

目标：让模式识别成为 RoleCraft 技术栈的主体。操作化为三条：

1. **识别器占住每一个 LLM 调用的输入装配环节。** 三个 LLM 入口（JUDGE 评分、ROLES 同事、ASSISTANT 知识助手）的输入都由识别器决定或标注；LLM 是执行器，识别层是感知与决策依据。不绕过 LLM。
2. **每个识别输出都带名字和分数，在学员每一步出场。** 任一页面至少一个「识别署名」；复盘页有会话级汇总；识别实验室页给评审看中间结果。
3. **架构与叙事以识别层为中心。** 代码树上有 `recognition` 包；架构图按 ISSM sense-making 流水线 B 画，识别器是中间五个框。

约束沿用交接文档：演示版，不管稳定性、可验证性、安全性；不跑回归门禁；碰契约指纹文件在 PR 说明里写「演示版，契约未重导出」；改 `models/**` 后已登记模型重新 `register`。

## 1. 总体架构

```
工作台（React）
  │  署名组件 RecognitionBadge · 会话汇总行 · 行为页 · 识别实验室页
  ▼
API / worker（FastAPI, jobs）
  │  三个 LLM 入口的输入装配
  │   JUDGE   ← N1 识别摘要 + C2 候选 + C1/C6 结果；support_check = C1
  │   ROLES   ← N3 C2 选源 + C11 意图 + C5 阶段；回合后 C10 核查
  │   ASSISTANT ← C2 检索 + C4 范围 + 版本检查 + 漂移异常
  ▼
识别层  src/career_lab/recognition/
  units      C2  单元化与检索（BM25 / e5 / RRF）
  relation   C1  关系判定（XLM-R pair_aggregate，复用 models/v3 加载器）
  decision   C6  代价敏感拒识 + 仲裁器 + 提升图排队
  scope      C4  范围外检测（马氏距离）+ 版本漂移统计异常
  intent     C11 提问意图识别
  behavior   C5  行为轨迹（DTW+kNN / HMM / 异常 / 人机判别）
  reply      C10 同事回复依据核查与泄露检查（复用 C1）
  provenance N5  RecognitionRecord 统一记录与会话级汇总
  registry       识别器登记与加载（权重目录、hash、离线回退）
  ▼
数据与实验  data/releases/*，experiments/recognition/*（C3 基线、消融、跨领域、有无识别摘要对照）
```

ISSM 流水线 B 的对应：原始数据（会话事件、作品文本、材料）→ 特征（单元、向量、符号序列）→ 识别实体（断言句、意图、阶段）→ 语义关系（C1 支持/矛盾/无关，C4 域内/域外）→ 上下文关系（版本有效性、代价决策 C6、仲裁、轨迹对齐 C5）→ 知识（评分项、反馈、复盘）。

## 2. 识别层公共契约

### 2.1 包与接口

新建 `src/career_lab/recognition/`，不在契约指纹内（指纹只锁 `contracts/`、`api/app.py` 等，以远端 `tests/contracts` 的清单为准）。`models/v3/consumer.py` 在指纹内且在注册身份锁定的目录里，所以 C1 推理仍留在 `models/v3`，识别层只调用它。

```python
# recognition/base.py
class Recognizer(Protocol):
    id: str                      # "xlm-r-pair-v1" / "scope-mahalanobis-v1" / ...
    revision: str                # 权重 hash 前 12 位，或 "rule-fallback"
    def recognize(self, inputs: dict, *, work_language: str) -> RecognitionRecord: ...

@dataclass(frozen=True)
class RecognitionRecord:          # contracts/v2/recognition.py，新契约文件
    recognizer_id: str
    revision: str
    task: Literal["relation","retrieval","scope","drift","intent","behavior","reply_check","decision","arbiter"]
    input_hash: str               # digest(inputs 的公开投影)
    label: str | None             # 主标签
    score: float | None           # 主分数（概率、距离、代价，含义由 task 定）
    threshold: float | None       # 本次判定用的阈值
    outputs: dict[str, JsonValue] # 任务专有字段，见各模块
    citations: tuple[EvidenceRefV2, ...]
    as_of: VersionPoint
    duration_ms: int
    fallback: bool                # True = 权重不可用，用规则回退得到的结果
```

所有识别器都有**规则回退**（`fallback=True`）：没权重时产品照常跑，界面署名显示「规则回退」。这保证远端同事和 CI 在没有模型目录时不受影响。

### 2.2 登记与加载

```
CAREER_LAB_RECOGNIZERS=<dir>      # 识别器根目录；未设则全部规则回退
<dir>/manifest.json               # [{"id","task","path","sha256","revision","languages":["zh","en"]}]
<dir>/scope-mahalanobis-v1/{mean.npy, precision.npy, threshold.json, embedder.json}
<dir>/intent-tfidf-lr-v1/{vectorizer.joblib, model.joblib}
<dir>/behavior-v1/{references.json, hmm.joblib, iforest.joblib, executor_rf.joblib}
<dir>/retrieval-e5/{config.json, model.safetensors, tokenizer.json, ...}   # multilingual-e5-small 本地目录
```

C1 不走这个目录，继续走远端 `CAREER_LAB_MODEL_REGISTRATIONS` 和 `registry_cli register --scope external_candidate`（编码器回传 v3 格式不变）。`recognition/registry.py::load_all()` 在 worker 启动时读 manifest，校验 sha256，失败则该识别器回退，stderr 打印每个识别器的状态（仿照 worker 打印四个槽）。

向量模型统一用 `intfloat/multilingual-e5-small`（118M，MIT），C2、C4 共用一个 `Embedder`，CPU 下一句约 8 ms；权重按交接文档坑 4 从 hf-mirror 下到本地。

### 2.3 Provenance 与会话级汇总（N5）

- `RecognitionRecord` 以可选字段挂在三种结果对象上：`FeedbackV2.recognition: tuple[RecognitionRecord,...]`、测试结果（`assistant/v2` 的 test 结果 data 字典加 `recognition` 键）、`RoleReply.recognition`。都是可选字段，旧数据不受影响。
- 新路由 `GET /sessions/{session_id}/recognition`：返回本会话全部记录（按 as_of 排序）和计数 `{"scope":6,"relation_units":24,"intent":9,"reply_check":9,"behavior":1,"arbiter":2}`。实现：遍历 `v2_transactions` 里带 `recognition` 的对象，不另建表。
- 前端 `features/recognition-native/badge.ts`：一个通用组件 `renderBadge(record, language)` 渲染「识别器名 · 标签 分数/阈值 · 回退标识」，每个页面只传记录不写文案；文案表在 `badge-copy.ts`，中英各一份。

## 3. 三个 LLM 入口的输入装配

### 3.1 JUDGE（N1、N2）

接入点【已核实】：`api/registered_models.py::RegisteredFeedback.evaluate` 先调 `engine.evaluate`（里面的 `FeedbackEngine` 对每个 `EvidencePackageV2` 调 `AdvisoryJudge.evaluate`），再追加 `model_advice`。Judge 的 prompt 输入由 `evidence/v2/assembler.py::model_input` 严格白名单投影。

改法：

1. **顺序反过来**：`RegisteredFeedback.evaluate` 先对 `R2.support` 包跑 C2 + C1 + C6（得到逐句结果），再把结果写进**每个**包的 `rule_context["recognition"]`，然后才调 `engine.evaluate`。这样 Judge 评任何一项时都能看到识别摘要。
2. **候选证据换成单元**：`assembler.py` 第 255 行与 336 行构造 `CandidateEvidenceV2` 处，材料不再整篇进候选，改为调用 `recognition.units.split_material` 得到单元；每个单元一个 `CandidateEvidenceV2`，`ref` 带 `char_span`（`EvidenceRefV2` 已有 span 字段，用于作品句，这里复用）。配置、登记册、测试记录按 `units.transcribe_state` 转成单句。候选上限 80；超出按 C2 对作品全文的检索分截断。
3. **识别摘要进 prompt**：`model_input` 加白名单字段 `recognition`：

```json
"recognition": {
  "relation_units": [{"index":3,"quote":"安排 50 人","label":"contradicted","confidence":0.91,"evidence_ids":["e-…"],"decision":"decide"}],
  "counts": {"supported":14,"contradicted":2,"insufficient":5,"deferred":3},
  "recognizer": "xlm-r-pair-v1@a1b2c3",
  "scope_tests": [{"query":"火星天气","scope":"out","score":4.1}],
  "behavior": {"strategy_nearest":"规范B","phase_sequence":["探索","测试","决策"],"anomalies":["政策更新后未测试即提交"]}
}
```

   只放标签、置信、句索引、证据 id，不放原文以外的任何内部 id（白名单原则不变）。长度上限 8 KB，超出按置信从低到高丢 `relation_units` 行（低置信的信息量小）。

4. **Judge system prompt 改为 v2**（`rubrics/v4/judge.py` 第 71 行附近；`scenarios/v2/release.py` 的 `PROMPT_VERSION` 改为 `grounded-feedback-bilingual-v2`，契约指纹内，演示版）。新增一段：「输入含识别器对作品逐句的关系判定（标签、置信、证据 id）。先读识别结果；标签在规则界内时以识别结果为主要依据；只有识别结果缺失、置信低于 0.6 或与规则事实冲突时才自行判断，并在 explanation 开头写明 `[识别一致]`、`[识别缺失]` 或 `[与识别不一致：原因]`。引用识别器标出的 evidence_ids。」

5. **`support_check` 换成 C1**：`AdvisoryJudge(model, support_check=...)` 的默认 `EvidenceSupportVerifier` 是 LLM 核验；新建 `recognition/relation.py::RecognizerSupportVerifier`，接口与 `EvidenceSupportVerifier` 相同（`check(claim, citations) -> {"supported": bool, "detail": ...}`，以远端类签名为准），内部对 Judge 引用的每条证据跑 C1；无权重时退回原 LLM 核验。`api/evaluation_runtime.py` 第 301 行处按 `CAREER_LAB_RECOGNIZERS` 是否可用选择。

6. **仲裁器**（C6 的一部分）：Judge 返回后，对 `R2.support` 比较 Judge 标签与 C1 聚合标签（`units.aggregate` 的结果映射到 MET/PARTIAL/NOT_MET：全部支持→MET，存在矛盾→NOT_MET，其余→PARTIAL）。不一致时：取规则界内更保守的一个作为最终 `FeedbackItem.label`，`explanation` 前加「仲裁：识别器 X / 评审 Y，取保守」，写一条 `task="arbiter"` 的 RecognitionRecord。一致时记 `agreement=true`。冲突率进报告。

验收：提交一份含「安排 50 人」的作品，反馈页 R2.support 的解释以 `[识别一致]` 开头；`GET .../recognition` 里有 relation、retrieval、decision、arbiter 四种记录；关掉 `CAREER_LAB_RECOGNIZERS` 后一切退回 v1 行为（除 prompt 版本号）。

### 3.2 ROLES（N3、C10 接入）

接入点【已核实】：`runtime/context_v2.py::ContextSnapshot.select_sources(auth, max_chars)` 按渠道排序（附件、共享、记忆、后到的通知、初始材料）再按字符预算截断，**没有相关性排序**；`build_prompt` 把选中的源序列化。`runtime/roles_v2.py::generate_plan` 调它，`RoleRuntime.generate` 在 `generate_plan` 返回后写 `role_reply` 对象。

改法：

1. `select_sources` 保留附件、共享、记忆优先和「后到的通知优先于它更新的初始材料」两条规则，但 `rest` 组内部改为按 C2 检索分（问题文本对源文本）降序；检索分为 0 的源仍保留但排最后。实现：`ContextSnapshot` 新增可选属性 `ranker: Callable[[str, Sequence[Source]], dict[ref_key, float]] | None`，由 `FixedRoleSnapshotPort.capture` 注入；为 None 时行为与今天完全相同。
2. `build_prompt` 在 `sources` 之前加一个 `learner_state` 条目（不是源，是上下文），内容来自 C11 和 C5：

```json
{"intent": {"label":"ask_limit","confidence":0.87},
 "phase": "探索", "materials_read": ["brief","faq"], "materials_unread": ["technical","policy"],
 "tests_run": 0, "requests_pending": [], "recognizer": "intent-tfidf-lr-v1 / behavior-v1"}
```

   角色 system prompt（`context_v2.py` 第 48 行起的通用文案）加一句：「`learner_state` 是系统识别出的学员当前状态，只用于决定回答的详略与提醒（例如学员未读技术材料时提醒去读），不得据此泄露学员不可见的事实。」

3. C10：`RoleRuntime.generate` 在 `generate_plan` 返回、`object_write("role_reply", ...)` 之前，调 `recognition/reply.py::check_reply(reply.text, snapshot, auth)`，结果写入 `reply.recognition`（`RoleReply` 契约加可选字段）。不阻断、不改文本；现有 LLM `reply_verifier`（立场一致性）照常。

验收：问技术负责人「最多能上多少人」，回复气泡下出现「意图 ask_limit 0.87 · 依据核查 2/2 句有依据」；`learner_state` 出现在 `role_context` 私有审计对象里。

### 3.3 ASSISTANT（C2、C4 接入）

接入点【已核实】：`assistant/v2/service.py::Assistant.run`。`candidates` 来自 `chunks(material, fragments, size)`（已按配置 `chunk_size` 分块），打分是 `meaningful_tokens` 的覆盖率 ≥ `tuning.min_score`，随后依次判 `prohibited_topic`、`no_retrieval_hit`、`outside_scope`、`manual_verification_required`、`stale_source_guard`。`api/app.py` 里 import 的 v1 `TrainingService` 不是产品测试走的路径，交接文档指的 v1 第 100 行作废。

改法：

1. 打分改为 C2：`score = retrieve(query, candidates, method=cfg_method)` 的归一化分（BM25 归一到 [0,1] 或 e5 余弦），`min_score` 语义保留。方法由场景包 `runtime/recognition.json` 指定，默认 RRF。
2. 在 `scored` 计算之后、`prohibited` 判断之前插入 C4：`scope = scope_detector.recognize({"query": query, "domain_units": in_domain_units(cfg)})`；`in_domain_units` 由 `cfg.scope_filter` 与 `cfg.domains` 决定（scope_filter 开时政策单元不进域内集合，这正是场景要教的）。新回退码 `outside_scope_ood`（`localized_text` 中英各加一条文案），优先级在 `no_retrieval_hit` 之前：域外就不看检索。
3. 漂移异常：同一会话同一问题（`digest(query)` 相同）在 `index_refreshed` 事件前后都测过时，算两次答案向量的余弦距离 `drift`，与本包域内「改写对」距离分布的均值 + 2σ 比较，超出记 `drift_anomaly=true`。这是对现有 `stale`（规则判）的统计对照，只标注不改状态。
4. 测试结果 data 加 `recognition: [scope_record, retrieval_record, drift_record?]`。

验收：问「火星天气」得 `outside_scope_ood`，卡片显示「范围 马氏 4.1 / 阈 2.8 · 域外 → 转人工」；问「住宿报销上限」在 scope_filter 开关两种配置下判定不同；索引刷新前后问同一问题出现漂移标注。

## 4. 各识别器设计

### 4.1 C2 单元化与检索 `recognition/units.py`、`recognition/retrieval.py`

**单元**：

```python
@dataclass(frozen=True)
class Unit:
    unit_id: str          # digest(material_id, version, char_span)
    material_id: str; version: int
    char_span: tuple[int,int]
    text: str
    kind: Literal["heading","item","sentence","state"]   # state = 结构化状态转写
    domain: str | None
    valid_from_seq: int; valid_until_seq: int | None
```

切分规则：Markdown 标题一行一单元（kind=heading，不做候选，只给上下文）；列表项一项一单元；段落按句号、问号、感叹号、分号切句，中英同一正则（复用 `models/v3/units.py::split_sentences` 的分段逻辑，不改它）；少于 4 个非空字符的并入前一单元；超过 160 字符的按逗号再切。`transcribe_state(snapshot)` 把当前配置、资源登记册、审批记录、测试记录各转成单句，模板中英各一套，例如「提交时配置：试点人数 20 人，更新策略 daily，范围过滤 开」。

**检索**：`retrieve(query, units, k=5, method="rrf") -> list[Hit(unit, score, rank, method)]`。BM25 复用 `assistant/retrieval.py::tokens`（中文二元组 + 拉丁词），英文加简单词干（去 s/ed/ing）；e5 用 `Embedder` 余弦，query 前缀 `query: `，单元前缀 `passage: `；RRF k=60。单元向量按 `(material_id, version)` 缓存到 `CAREER_LAB_MODEL_JOURNAL` 下的 `embeddings/`。

**评测**：金标来自 C1 数据的 `gold_unit_ids`；指标 Recall@1/3/5、MRR，分语言；三种方法一张表，选定方法写进场景包 `runtime/recognition.json`。

### 4.2 C1 关系判定（训练工程 `experiments/recognition/relation/`，推理在 `models/v3`）

与选型文档一致：`FacebookAI/xlm-roberta-base`，`pair_aggregate`，512 token，mean pooling，冻结底部 8 层，lr 2e-5，batch 16，3 轮，dev joint 早停；Colab T4 训练，本机 `.venv-encoder` 导出与 `predict`，`registry_cli register --scope external_candidate`。

本文新增两点：

- **逐句输出要带概率**：`models/v3/consumer.py::_public_unit` 加 `probabilities: {"supported":p,"contradicted":p,"insufficient":p}` 与 `confidence = max(p)`；前端 `AdviceUnit` 加同名可选字段。C6 和仲裁器都靠它。改了 `models/**`，已登记模型重新 register。
- **逐句候选用 C2**：`consumer.py::_relation_advice` 对每句先 `retrieve(sentence, candidates, k=5)` 再送编码器；`MAX_UNITS` 保持 24。pm_pilot 约 60 单元时每句 5 对，24 句 120 对，CPU 约 15 秒。

对照组（报告）：线性适配（冻结全部只训头）vs 冻结底 8 层 vs 全量；C3 的五个经典基线与集成同表；分语言 Macro-F1、逐类 P/R、混淆矩阵、证据 F1、joint。

### 4.3 C6 代价敏感决策 `recognition/decision.py`

代价矩阵（组内可改，放 `recognition/costs.json`）：误判为矛盾（误扣分）3，误判为支持（错误放行）1，送人工 0.5，正确 0。

```python
def decide(probs: dict[str,float], costs) -> Decision:
    # 期望代价：对每个候选判定 d，E[cost(d)] = Σ_y p(y)·cost(d,y)；defer 代价固定 0.5
    # 取最小；并列取 defer
    return Decision(action="decide"|"defer", label=argmin, expected_cost=..., defer_cost=0.5)
```

校准：dev 上温度缩放，`temperature.json` 随 C1 登记目录放；报告 ECE 前后。

应用：逐句决策写进 `relation_units[i].decision`；`defer` 的句子在反馈页仍显示「待核验」，但解释改为「期望代价 1.8 高于送人工 0.5」；聚合标签只用 `decide` 的句子。**提升图排队**：待核验列表按期望代价降序，页面顶部一行「人工先看前 20% 可覆盖约 x% 真错误」，x 来自 dev 上的提升曲线，随登记目录放 `lift.json`。

仲裁器见 3.1 第 6 条。

### 4.4 C4 范围外检测与漂移 `recognition/scope.py`

- 向量：e5-small，L2 归一。
- 域内分布：每个场景包、每种语言、每种 scope_filter 取值各拟合一组 `(mean, precision)`：样本 = 域内单元向量 + 约 100 条域内改写问题向量；协方差用 Ledoit-Wolf 收缩。马氏距离为分数；阈值在 dev 上取 TPR 95%。
- 输出：`label ∈ {"in","out"}`，`score`（距离），`threshold`，`outputs={"nearest_unit_id", "fit_key": "pm_pilot/zh/scope_on"}`。
- 对照组（报告）：K-Means 簇中心距离、余弦均值 ± kσ、朴素贝叶斯域内似然、自编码器重建误差、one-class SVM、Isolation Forest；AUROC、TPR95 时 FPR、近域子集单独报告、PCA 二维投影图。
- 漂移：见 3.3 第 3 条。
- 回退：无权重时 `label` 由 `no_retrieval_hit` 推出，`fallback=True`。

### 4.5 C11 意图识别 `recognition/intent.py`

五类：`ask_limit`（问限制/约束）、`ask_resource`（问资源/人力/天数）、`ask_process`（问流程/怎么做）、`seek_approval`（求批准/申请）、`other`。模型：TF-IDF 字符 2–4 gram + 逻辑回归，中英各一个或合一个（先试合一个）。数据：DeepSeek 按类别和四种文风各生成，中英各 600，第二遍盲判一致才留；加组员实玩的问题作测试。回退：关键词规则。输出进 N3 的 `learner_state`，并细化 C5 符号 `ask:<role>:<intent>`。

### 4.6 C5 行为轨迹 `recognition/behavior.py`

**符号表**（从 v2 事件与命令映射，远端 `scenarios/v2/engine.py` 与 `delegations/catalog.py` 的名字【已核实】）：

| 来源 | 符号 |
|---|---|
| `material_read`（按 material_id 的 domain） | `read:brief` `read:technical` `read:business` `read:faq` `read:policy` `read:approval` |
| `turns.create` + C11 | `ask:supervisor:<intent>` `ask:tech_lead:<intent>` `ask:business_lead:<intent>` |
| `config_applied` / `initial_plan_applied` | `configure` |
| `test_assistant` + C4 + 命中域 | `test:normal` `test:policy` `test:oos` |
| `business_requested`（按 kind） | `request:capacity` `request:resources` |
| `business_decided` / `resource_grant_committed` | `approved:*` / `denied:*` |
| `index_refreshed` | `refresh_index` |
| 业务事件（政策更新） | `event:policy_updated` |
| `submissions.create` | `submit` |
| `revision_opened` | `revise` |

序列属性：`executor ∈ {human, own_agent, reference_agent}`（委托记录），`language`，`scenario_id`。

**模型**：

- 策略识别：序列编辑距离与 DTW（符号替换代价：同类前缀 0.5，异类 1）+ 1-NN，参考库 = 8 种脚本策略各 40 条；对照 n-gram（1–3）频率 + 随机森林、小 LSTM。
- 阶段推断：`hmmlearn.CategoricalHMM`，状态数 3–5 按 BIC；发射分布人工命名为「探索 / 测试 / 决策 / 调整」；在线推断 `phase_now(sequence)` = 最后一步的后验最大状态（给 N3 用）。
- 异常：规则四条（政策更新后未测即提交、未读技术材料即申请资源、申请当批准直接配 50 人、重复提交同一配置）给标签；分数 = 合理轨迹上训的 HMM 对数似然（按长度归一）；对照 Isolation Forest（n-gram 特征）、到策略簇中心的 DTW 距离。
- 人机判别（A'）：n-gram + 时间间隔统计（Agent 的步间隔近似常数）+ 随机森林；数据 = 组员实玩 + Claude Code 经 MCP 实玩 + 参考 Agent。
- 无监督发现：DTW 距离矩阵 + Ward 层次聚类，轮廓系数选簇数，与策略标签算 ARI。

**接口** `GET /sessions/{session_id}/behavior`：

```json
{"sequence":[{"seq":12,"symbol":"read:technical","at":"…","phase":"探索"}],
 "strategy":{"nearest":"规范B","distance":4.0,"top3":[…]},
 "alignment":{"missing":["test:policy"],"extra":["submit"],"swapped":[["request:capacity","read:technical"]]},
 "phases":[{"name":"探索","from_seq":1,"to_seq":9},…],
 "anomalies":[{"rule":"policy_update_untested_submit","score":0.82,"at_seq":31}],
 "executor":{"predicted":"own_agent","confidence":0.93,"declared":"own_agent"},
 "recognizer":"behavior-v1@…"}
```

**前端** `apps/web/src/features/behavior-native/`：时间线色块（阶段）、参考路径对齐图（缺/多/反序三种标记）、异常列表、人机判别一行。放在复盘页（results-native）下方，入口按钮「你的行为模式」。

### 4.7 C10 同事回复核查 `recognition/reply.py`

```python
def check_reply(text, snapshot, auth) -> RecognitionRecord:
    sentences = split_sentences(text)                        # 复用 models/v3/units
    visible = units_of(snapshot.select_sources(auth, 10**9)[0])   # 该角色可见的全部源，单元化
    private = units_of(snapshot.private_facts 中 learner 不可见者)
    for s in sentences:
        hits = retrieve(s, visible, k=3); label = relation(s, hits)   # C1
        leak = any(relation(s, retrieve(s, private, k=3)) == "supported")
    outputs = {"sentences":[{"quote","label","confidence","evidence_ids","leak"}],
               "grounded": n_supported, "ungrounded": n_other, "leaks": n_leak}
```

泄露检查的候选只在服务端用，`evidence_ids` 对泄露句不返回（不能把私有事实 id 交给学员）；只返回 `leak: true` 和句子。回退：无 C1 权重时只做检索命中率（有命中即「可能有依据」），`fallback=True`。

### 4.8 C3 经典基线与集成（只进报告，`experiments/recognition/baselines/`）

同一份 C1 数据，`rolecraft-linear-text-v1` 的 TF-IDF 字符 n-gram 特征；NB（拉普拉斯）、kNN（k 网格）、决策树（增益率、剪枝）、SVM（RBF）、LR、字符 MLP；bagging（LR）、AdaBoost（树）、随机森林（OOB、置换重要性）、LR + 编码器堆叠、概率融合 alpha 网格。线性回传按远端 `linear-return.md` 导出并登记为融合分量（远端机制已有）。偏差—方差说明。

## 5. 界面：署名、汇总、实验室

| 页面 | 识别署名内容 | 数据来源 |
|---|---|---|
| 测试结果卡 | 「范围检测 scope-mahalanobis-v1 · 马氏 1.3 / 阈 2.8 · 域内」「检索 rrf · top-1 0.71」「漂移 0.42 · 异常」 | 测试结果 `recognition` |
| 回复气泡下 | 「意图 ask_limit 0.87」「依据核查 2/3 句有依据 · 无泄露」 | `RoleReply.recognition` |
| 写作区预演卡 | 每句 top-1 证据与关系标签实时标色（调用现有预演接口，候选换单元） | 预演反馈 |
| 反馈页每项 | 「判定来源：识别器 xlm-r-pair-v1 0.91 / 评审一致」或「仲裁：取保守」；逐句建议保留；待核验按期望代价排序 + 提升图一行 | `FeedbackV2.recognition` + `model_advice` |
| 复盘页顶部 | 「本次会话：范围检测 6 次 · 关系判定 24 句 · 意图识别 9 次 · 依据核查 9 条 · 轨迹识别 1 条 · 仲裁 2 项」 | `GET …/recognition` |
| 行为页 | 见 4.6 | `GET …/behavior` |
| 识别实验室 `features/recognition-lab/` | 选一条断言看全链：检索 top-5 与分数 → 逐对关系概率 → 代价决策 → Judge 输入里的识别摘要 → Judge 输出与仲裁；下方图表：C3 总表、C1 分语言混淆矩阵、C4 ROC 与 PCA 投影、C5 混淆矩阵与 HMM 状态发射图、跨领域泛化表、有无识别摘要对照 | 静态 JSON（实验产物复制到 `apps/web/public/lab/`）+ 会话实时记录 |

署名文案中英各一份；「规则回退」状态显示灰色标签并写「权重未加载」。

## 6. 训练场景

### 6.1 档 A：换领域变体（IT 工单助手）

同一结构 `index_scope_resource_dependency`，新场景 id `it_ticket_pilot`，中英各一份。内容在 `scenarios/v2/content_it.py` / `content_it_en.py`，由 `seed.py::build_seed` 生成包。对应关系：

| pm_pilot | it_ticket_pilot |
|---|---|
| 知识助手答政策/FAQ | 工单助手答报修流程 / SLA / 权限申请 |
| 差旅政策 v1→v2（住宿 500→400） | SLA 政策 v1→v2（P2 响应 4 小时→2 小时） |
| 技术材料「最多 30 人」 | 技术材料「并发工单上限 30」 |
| 三角色 supervisor / tech_lead / business_lead | 同三角色，business_lead 换成 service_desk_lead（id 不变，名字和材料变） |
| 探针 13 条 | 同数目，按新材料重写 |

需参数化的写死处【已核实】：`scenarios/v2/evaluation_facts.py` 的 `policy_travel`、住宿报销匹配器、`policy` 材料名 → 改为从包 `rules["policy_material_id"]` 与 `rules["policy_probe_patterns"]` 读取；`engineer/capture.py` 要求的 `failures`、`trial_details` 材料照样提供。前端 `workbench-live.ts` 的场景 id 映射加一项。安装与目录按现有 `installed/current.json` 与 `write_catalog` 机制。

用途：C1、C4 在 pm_pilot 训、在 it_ticket_pilot 测的跨领域表；C5 第二个场景的轨迹；演示时可选。

### 6.2 A'：执行者维度

零改动。数据来自组员实玩、Claude Code 经 MCP 实玩、参考 Agent（Windows 上跑不了 `reference_agent`，用 Mac 或 WSL 跑）。进 C5 的人机判别与「人 vs Agent」对比报告。

### 6.3 B1：工程师路径接 C1

`engineer/` 的 `review` 产出 `claim_consistency` 时，把工程师「声称报告」逐句对探针结果（转写成单元）跑 C1，`E3.change_consistency` 的解释引用识别结果；记录进 `RecognitionRecord(task="relation")`。

### 6.4 不做

案例面试模式、事故响应、数据标注 QA、招聘：写进报告「下一步」，不实现。

## 7. 数据

全部放 `data/releases/<name>/`，每个目录有 `manifest.json`（记录、hash、生成规格、复核规格、模型版本）、`data_card.md`、`SHA256SUMS`（`utf-8` + `\n`）。

| 数据 | 内容 | 规模 | 生成 | 复核 | 分区 |
|---|---|---|---|---|---|
| `relation-v3` | 断言、候选单元（1 金标 + 3 难负例）、三分类标签、现象、文风、语言、`unit_hash` | 中英各 2,000 断言、8,000 句对；加真实作品句 | 真实句：脚本运行器 40 条会话 + `datasets.v3 export --live --relation-units`；合成：DeepSeek 按 v3 第 3.3 节矩阵 | 第二遍盲判（只给句对），一致保留；程序核对数值与版本 | 按事实根 60/20/20，test 冻结前不碰 |
| `assistant-queries-v1` | 问题、域内/域外、近域/远域、答案单元、语言、scope_filter 取值 | 中英各 300（域内直述、域内改写、域外各 100） | DeepSeek 按清单 | 程序核对域内问题有答案单元 | 按问题模板 |
| `intent-v1` | 问题、意图、语言、文风 | 中英各 600 | DeepSeek 按五类四文风 | 第二遍盲判 | 60/20/20 |
| `trajectories-v1` | 符号序列、执行者、策略标签、异常标签、场景、语言 | 8 策略 × 40 = 320 合成；真实约 15 | HTTP 脚本运行器（不用 `reference_agent`）跑真实后端，随机化顺序、问题、数值 | 标签来自策略，无需复核 | 合成按策略分层 80/20；真实只测 |
| `paraphrases-v1` | C4 拟合用的域内改写问题 | 每包每语言 100 | DeepSeek | 程序核对 | 全部训练 |

脚本运行器 `scripts/recognition/run_strategies.py`：参数 `--strategy --count --scenario --language --api http://127.0.0.1:18562`；八种策略各一个函数，每步调 HTTP 接口（新建会话、读材料、问角色、配置、测试、申请、提交），记录 request_id 以便事后从 `v2_transactions` 导出；同一批会话同时是 C1 真实句和 C5 轨迹的来源。

## 8. 实验与报告

实验代码在 `experiments/recognition/`，每个实验一个脚本，输出 `results/<exp>.json` 与图；实验室页从这里取静态文件。

| 编号 | 实验 | 产出 |
|---|---|---|
| E1 | C1 分语言主结果 + C3 基线与集成同表 | 总表、混淆矩阵 |
| E2 | 线性适配 vs 冻结底层 vs 全量；学习曲线；特征选择三法 | 曲线 |
| E3 | C2 三种检索方法 Recall@k、MRR | 表 |
| E4 | C6 误差—拒识曲线、固定拒识率下误扣分率、ECE 前后、提升图 | 图 |
| E5 | C4 AUROC、TPR95 时 FPR、近域子集、六种对照、PCA 投影 | 图表 |
| E6 | C5 策略识别准确率与混淆矩阵、BIC 曲线与发射分布、异常 AUROC、ARI、人机判别准确率、真实轨迹单独报告 | 图表 |
| E7 | C11 准确率与混淆矩阵 | 表 |
| E8 | **有无识别摘要的 Judge 对照**：同一批提交两种输入，标签一致性、引用命中率、待核验比例、与 C1 的冲突率 | 表（报告核心） |
| E9 | 跨领域泛化：pm_pilot 训 → it_ticket_pilot 测（C1、C4） | 表 |
| E10 | 早期 vs 晚期融合（结构化事实拼进编码器输入 vs 决策级） | 表 |

报告系统设计章按 PSUPR 五段与 ISSM 流水线 B 两条线写；课程四项对应按 v3 第 13.5 节表。

## 9. 实施顺序（按依赖，不按时间）

```
S0  环境与基线
    起三进程（交接文档第 4 节，助手走 v2）；JUDGE 槽接 DeepSeek；e5-small 与 XLM-R 权重下到本地；.venv-encoder 建好
    验收：反馈页出现合成逐句建议；语义评分项有标签
S1  识别层骨架（不依赖数据）
    recognition/{base,registry,provenance}；RecognitionRecord 契约；三种结果对象的可选字段；GET /recognition；前端 badge 组件与复盘页汇总行
    验收：全部规则回退状态下，每个页面能显示灰色「规则回退」署名
S2  C2 单元化与检索（不依赖数据）
    units、retrieval、Embedder、向量缓存；assembler 候选换单元；assistant v2 打分换 C2；consumer 逐句 top-5
    验收：Judge 包候选 ≤ 80 单元；助手测试卡显示检索署名
S3  数据生产（依赖 S0 起的服务）
    脚本运行器 → 40 条会话 → relation 真实句 + trajectories；DeepSeek 合成 relation / queries / intent / paraphrases；两遍复核；分区
S4  轻量识别器（依赖 S3 对应数据）
    C4 scope + 漂移（queries + paraphrases）；C11 intent；C5 建模（trajectories）；各自登记进 CAREER_LAB_RECOGNIZERS
S5  LLM 入口装配（依赖 S1、S2，C4/C11/C5 有则用、无则回退）
    N1 识别摘要 + model_input 白名单 + Judge prompt v2 + support_check 替换；N3 选源与 learner_state；C10 回复核查；assistant C4 门
    验收：3.1–3.3 的验收条目
S6  C1 训练与登记（依赖 S3 relation 数据）
    Colab 训练 → 本机导出 → register；consumer 加概率；C6 决策与温度缩放；仲裁器；提升图排队
    验收：反馈页 R2.support 解释以 [识别一致] 或 [仲裁] 开头
S7  行为页与实验室页（依赖 S4 C5、S1 骨架）
    GET /behavior；behavior-native；recognition-lab
S8  场景（可与 S3–S7 并行）
    it_ticket_pilot 中英；evaluation_facts 参数化；B1 工程师路径接 C1
S9  实验 E1–E10；冻结；test 各跑一次；错误分析
S10 报告、slides、视频、架构图
```

并行性：S1、S2、S8 互不依赖；S3 与 S1/S2 并行；S4 的三个识别器互不依赖；S5 在 S1、S2 后即可开始（识别器缺就回退），不必等 S6。砍法顺序：E10 → 漂移异常 → C5 的 LSTM 与 Isolation Forest 对照 → C10 泄露检查 → it_ticket_pilot 第二语言 → C3 集成部分。S1、S2、S5、C1、C4、C5 策略识别、C11、署名组件、E8 不砍。

## 10. 与远端的协作与约束

- **契约改动清单（演示版，不重导出）**：`contracts/v2/recognition.py` 新增；`FeedbackV2`、`RoleReply` 各加可选 `recognition` 字段；`model_input` 加 `recognition` 白名单字段；`PROMPT_VERSION` 升 v2；`v2_routes.py` 加 `/recognition`、`/behavior` 两个 GET。
- **`models/**` 改动**：`consumer.py` 加概率输出与逐句 top-5；改后已登记模型重新 register。
- **PR 切分**：S1 一个 PR；S2 一个；S5 按入口拆三个；C4/C11/C5 各一个；场景一个；前端页面各一个。每个 PR 说明里写「演示版，契约未重导出」。
- **Windows 坑**沿用交接文档第 6 节；`reference_agent` 与 `RunJournal` 用 `fcntl`，参考 Agent 轨迹在 Mac/WSL 跑。
- **不改**：规则界、14 项评分项定义、`affects_score=false` 的逐句建议语义（分数仍由 Judge 在规则界内给，识别器是它的输入与核验）。

## 11. 已定的可调项

下面这些都已按本文默认值定下，直接实施，不需要确认。它们都是数据或文案，改动不触碰代码结构，事后要改就改对应文件：

| 项 | 默认值 | 改在哪里 |
|---|---|---|
| 代价矩阵 | 误扣分 3 / 错误放行 1 / 送人工 0.5 | `recognition/costs.json` |
| 意图五类 | `ask_limit` `ask_resource` `ask_process` `seek_approval` `other` | `intent-v1` 生成规格与 `badge-copy.ts` |
| HMM 阶段命名 | 探索 / 测试 / 决策 / 调整 | `behavior-v1/references.json` 的 `phase_names` |
| 档 A 领域 | `it_ticket_pilot` | `scenarios/v2/content_it*.py` |
| Judge 采信识别结果的置信阈值 | 0.6 | `rubrics/v4/judge.py` 的 prompt 常量 |
| 前端两页与 badge 组件 | 由实现本设计的 coding agent 做，与后端同一批 PR | — |
