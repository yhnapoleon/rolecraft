# RoleCraft 数据收集与标注计划

版本：1.0　日期：2026-10-06　配套：[扩建规范 v2.2](../specs/2026-10-06-rolecraft-expansion-spec.md) 第 10 节、[扩建执行计划](2026-10-06-rolecraft-expansion-plan.md)

## 0. 定位

数据工作单独成计划，原因有三：它的产出是所有实验的输入，必须尽早开始；它有自己的流水线（导出、标注、校验、发布），与功能开发的节奏不同；用户 2026-10-06 的指示把标注方式从人工双标改为模型分批标注并确认，这一变化需要完整写清楚。

本计划的工作包编号为 WP-D0 到 WP-D8，在执行计划的泳道 L2 中排期；代码归属 `src/career_lab/datasets/`、`src/career_lab/labeling/`（新建）和 `scripts/` 下与数据有关的脚本。

关于标注模型：用户指定使用 `gpt6-astra`。本文没有核实该模型的接口、价格、上下文长度和中文表现；流水线按模型无关的方式设计，模型名是配置项 `labeling.model`，运行时记录响应返回的实际模型标识。接入方式（API 密钥还是 Agent 按批次执行）见第 6.1 节和规范 16 节的 U10。

陈述标记沿用规范：【已核实】、【设计】、【估计】。

## 1. 目标与原则

1. 四类数据全部从真实运行导出，草稿不入库；草稿只作为格式参考，并保留其来源说明。
2. 标签等级：程序可核验的为 G0；语义类由模型两遍独立标注并确认，为 G2v；人工复核改为可选抽检。任何地方不得把模型标签表述为人工标签。
3. 每条记录可以溯源：环境运行的记录回溯到会话、事件序号、执行者和代码提交号；外部来源的记录回溯到 URL、修订版本、取数日期、许可和所做的变换。
4. 按结构分区；标注提示词只能在训练和开发分区上调整；测试分区的记录由冻结后的提示词版本一次性标注。
5. 演示级：数量以够做对照实验为准，不追求覆盖所有角落；流水线必须能重跑，数字允许小幅波动。
6. 标注模型的输入只来自 `model_input`，不含 gold、路径夹具、探针预期和关键事实清单。

## 2. 数据家族与记录形状

规范 10.1 节定义了四类；本计划加上第五类“技能与优化记录”，由技能记忆和自动优化模块产出，格式简单，这里一并规定。

### 2.1 关系与证据

```yaml
record_id: rel-<会话前缀>-<序号>
schema_version: 2
task_type: relation
claim:
  text: 国内出差住宿报销上限为每人每晚 400 元
  source: {kind: assistant_answer, object_id: <测试记录>, seq: 20}   # assistant_answer / artifact_claim / role_statement / external_document
as_of_seq: 20
candidate_evidence:                 # 目标 8 条；不足 8 条时如实记录条数
  - {id: e1, kind: document, object_id: policy_travel, version: 2, observed_at_seq: 14, valid_from_seq: 4, valid_to_seq: null, text: ...}
  - {id: e2, kind: test_result, object_id: ..., version: 1, observed_at_seq: 20, text: ...}
label: SUPPORTED
label_tier: G0                      # G0 / G2 / G2v
acceptable_evidence_sets: [[e1, e2]]
missing_requirement: null
labeling: {method: rule:version_match, model: null, prompt_version: null, passes: []}
```

G0 规则：断言中含数值、版本或“是否存在某记录”，且账本或状态里有对应事实时，由程序判定并给出最小充分集合。其他断言进入模型标注队列。

### 2.2 原子评价项

```yaml
record_id: crit-<提交前缀>-<评分项>
schema_version: 2
task_type: criterion
criterion_id: R4.staleness_test
rubric_version: 2
submission: {session_id: ..., submission_id: ..., as_of_seq: 25, artifact_id: ..., config_version: 2}
subject_spans: [...]                # 被评价对象的相关段落
candidate_evidence: [...]           # 按评分项的 evidence_types 选取
rule_bound: {floor: PARTIAL, ceiling: MET, decided: false}
label: MET
label_tier: G2v
evidence_ids: [e3, e5]
reason_code: ...
labeling: {method: model:two_pass, model: ..., prompt_version: crit-v3, passes: [A, B], agreement: true}
pair_of: crit-<分支提交>-R4.staleness_test   # 同一评分项在父会话与分支上的成对记录
```

规则已定标（`decided: true`）的为 G0，不送模型；其余送模型，模型输出必须落在规则界内。

### 2.3 过程轨迹

```yaml
record_id: traj-<会话 id>
schema_version: 2
run: {session_id, branch_of, scenario: {id, version, structure_id}, executor_summary: {human: 20, delegate_agent: 7}, runtime_bundle: ..., seed}
steps: [{seq, actor_id, executor, tool, args, result_ref, events, state_digest}]
outcome: {submitted: true, decision: defer_with_conditions, rule_decided_weight: 0.45, labels_summary: {...}}
diagnoses:                          # 6.7 节检测器，G0
  - {issue_type: ignored_visible_change, earliest_step: 18, evidence_refs: [...], affected_criteria: [R5.impact], proposed_intervention: {fork_at: 18, replace: read_material(policy_travel)}}
narrative_annotations:              # 可选，模型生成，G2v
  - {kind: strength, text: ..., steps: [11]}
label_tier: G0                      # 以诊断为准；叙述性标注单独标 G2v
```

### 2.4 信息动作

```yaml
record_id: dp-<会话 id>-<seq>
schema_version: 2
as_of_seq: 8
belief_state: {...}                 # 参考 Agent 的信念状态快照；真人会话没有
candidate_actions:
  - {id: a1, tool: read_material, args: {material_id: technical}, outcome_type: resolves_key_unknown, resolved_fact_ids: [capacity, dev_days], state_changed: false, rejected: false}
  - {id: a2, tool: submit_plan, args: {}, outcome_type: premature, rejected: false, rule_violations: [R4.functional_tests]}
chosen: a1
chosen_by: {kind: reference_agent, label: active-v1}
label_tier: G0                      # 环境推导；含角色对话候选时该候选单独标 G2
```

### 2.5 技能与优化记录

```yaml
# 技能候选
record_id: skill-<id>-v<版本>
origin: {trajectory_refs: [...], distilled_by: {model, prompt_version}}
validation: {structures: [...], success_delta: ..., invalidation_tests: [...]}
status: candidate                   # candidate / validated / active / deprecated
# 优化候选
record_id: cand-<id>
parent: cand-<id>
diff: {...}
hypothesis: ...
evaluation: {structures: [...], success_rate: ..., cost: ..., dominated: false}
```

## 3. 来源与产量目标

### 3.1 环境运行（主来源）

这是数据的主体，也是算力的主要去处。由参考 Agent 运行器（执行计划 WP-12）按 suite 清单批量运行：

| 维度 | 取值 |
|---|---|
| 结构 | S1 `pm_pilot` v2；S2 双重变更；S3 批准有效期；S4 信息分散；S5 不可行识别；S6 受限知识域（见执行计划 WP-15） |
| 策略 | 固定清单（不调用模型）；普通工具循环；主动获取 |
| 种子 | 每组至少 5 个 |
| 预算 | 统一的步数和 token 上限 |
| 分支 | 每条成功主轨迹派生 1 到 2 条干预分支：忽略变更、过早提交、未经批准的假设 |
| 故障注入 | 一部分运行注入模型超时、工具错误、材料暂时不可用 |

产量目标【估计】，用于判断流水线是否跑够，不是硬性指标：

| 数据 | 目标 | 推算 |
|---|---|---|
| 主轨迹 | 90 | 6 结构 × 3 策略 × 5 种子 |
| 分支轨迹 | 90 到 180 | 每条主轨迹 1 到 2 条 |
| 真人与委托 Agent 会话 | 15 到 30 | 试用加演示 |
| 步骤 | 约 5,000 | 每条轨迹 20 到 30 步 |
| 信息动作决策点 | 约 5,000，候选约 30,000 | 每步一个决策点，每个 5 到 8 个候选，环境推导 G0 |
| 原子评价项 | 约 3,000 | 约 200 次提交 × 14 条；规则定标约四成为 G0，其余送模型 |
| 关系与证据 | 2,000 到 3,000 | 每会话 10 到 15 条断言 |
| 诊断标注 | 与轨迹数相同 | 检测器自动产生 |

### 3.2 受控合成

受控实验 v2 的 1,152 条 G0 关系项继续使用：训练与开发分区用于训练基线和校准标注模型，测试分区只作回归。新结构的程序化关系项（如需要）用现有生成器按同一协议生成为 v3，与 v2 分目录。

### 3.3 公开辅助来源

用于补充真实材料和扩展情境，单独放在 `public_aux` 桶，与环境运行的数据分开统计。

| 来源 | 内容 | 许可 | 用途 | 是否可发布 |
|---|---|---|---|---|
| GitHub site-policy（多版本政策文本） | 真实政策改版，可构造带版本的关系项 | CC0-1.0 | 关系与证据 | 是 |
| Kubernetes KEP 的 Release Signoff Checklist | 真实评分标准与作者自评 | Apache-2.0 | 原子评价项 | 是 |
| TheAgentCompany 任务定义（task.md、checkpoints.md） | PM 任务与评分点 | MIT | 原子评价项、情境 | 是 |
| TheAgentCompany experiments（运行轨迹） | Agent 轨迹与得分 | 未声明 | 过程轨迹的格式参考 | 否；只留本地，不入数据集 |
| Public Jira Dataset（含 Apache Jira） | 真人过程记录 | CC BY 4.0 | 过程轨迹 | 是；替代直接抓取 Apache Jira |
| tau-bench historical_trajectories | 按政策办事的客服轨迹 | MIT | 过程轨迹（非 PM，单列） | 是 |

扩充时每个来源都要记录 URL、修订版本（提交号或取数日期）、许可文件的 hash、所做的变换（翻译、断言撰写、截断）。

### 3.4 真人与委托 Agent 会话

来自同伴试用（执行计划 WP-19）和演示录制。参与者同意后匿名编号；轨迹按 `human_session` 桶导出；执行者字段区分人和委托 Agent。

### 3.5 业务合成

预留 `business_synth` 桶和同样的记录格式；是否接入由规范 U7 决定，本期不排工作。

## 4. 外部样例的根因分析、修复与溯源

### 4.1 校验结果【已核实】

2026-10-06 用现有 pydantic 契约逐条校验 `data/external-samples/`：

| 文件 | 条数 | 试用的契约 | 通过 | 首批错误 |
|---|---|---|---|---|
| `open-source-pm-samples.jsonl` | 18 | `EvidencePackage` | 0 | 缺 `as_of_seq`；`candidate_evidence[*]` 含被禁止的 `source_text`、`locator`；顶层含 `label`、`acceptable_evidence_sets`、`label_tier`、`source`、`language`、`note` |
| 同上 | 18 | `GoldAnnotation` | 0 | 缺 `annotation_version`；含被禁止的 `claim`、`candidate_evidence`、`criterion`、`source`、`note` |
| `judge-criterion-samples.jsonl` | 9 | `EvidencePackage` | 0 | 缺 `claim`、`as_of_seq`、`candidate_evidence`、`completeness`；含被禁止的 `source`、`criterion_id`、`criterion_zh`、`source_state`、`submission`、`evidence` |
| `process-trajectory-samples.jsonl` | 4 | 无对应 v1 契约 | — | 三种来源的步骤结构不同：Jira 是字段变更，TheAgentCompany 是动作与观察，tau-bench 是对话轮次 |
| `info-action-synthetic-samples.jsonl` | 12 | 无对应 v1 契约 | — | 标签由假设的成本表算出，不是环境反馈 |
| `showcase-synthetic-session.json`、`synthetic-scenario-chain.json` | 2 | 无对应契约 | — | 手工推演；与引擎行为不符（见 4.2 的 R5） |

### 4.2 根因分类

| 编号 | 根因 | 影响的文件 | 性质 |
|---|---|---|---|
| R1 | 一条记录同时装了模型输入和 gold。仓库刻意把 `EvidencePackage`（输入）和 `GoldAnnotation`（真值）分成两个对象，并用 `extra="forbid"` 阻止 gold 混入输入 | 关系样例、评价项样例 | 设计差异，不是 bug |
| R2 | 溯源字段（`source_text`、`locator`、`source`、`language`）在 v1 契约里没有位置，而 v1 禁止未知字段 | 关系样例、评价项样例 | v1 契约缺少溯源字段 |
| R3 | 评价项、轨迹、信息动作在 v1 里没有对应契约；评价项样例的被评价对象是一段自由文本，而 v1 的 `claim` 是“评分项描述加成果理由”的拼接 | 评价项、轨迹、信息动作 | 契约缺失 |
| R4 | `as_of_seq` 的语义是会话事件序号；外部文档没有事件序列，只有版本号与日期 | 关系样例 | 时间模型不匹配 |
| R5 | 合成会话靠手工推演，没有在引擎上运行：触发时点写错（政策更新在第 4 步就触发，因为所有动作都计数）；系统反馈覆盖率写 0.2，实测为 0；测试的 `label` 和成果的 `name` 字段不存在；角色回复包含账本之外的事实；助手对范围外问题的行为与真实相反；早期草稿在配置之前测试 | 两份合成会话 | 生成过程缺少执行验证 |
| R6 | 草稿是对着设计文档的文字写的，不是对着 pydantic 类写的；仓库没有导出 JSON Schema，也没有校验命令 | 全部 | 流程缺陷 |
| R7 | 许可缺口：TheAgentCompany experiments 仓库未声明许可；Apache Jira 页面未标注开放许可 | 轨迹、评价项 | 合规 |
| R8 | 标签来源：外部样例的标签、译文、证据选择都由模型给出，但文件里只用 `label_tier: G2` 一笔带过，没有记录模型、提示词和日期 | 外部样例 | 溯源缺失 |

### 4.3 修复决定

| 根因 | 决定 | 落点 |
|---|---|---|
| R1 | 导入时拆分：输入部分进 `EvidencePackageV2`，标签部分进 `GoldAnnotationV2`；两者用 `record_id` 关联 | WP-D1 导入器；契约 v2（执行计划 WP-01） |
| R2 | v2 契约为证据条目增加可选的 `source_text`、`locator`；记录级增加 `source`、`transformations`、`language`。v1 契约不改 | WP-01 |
| R3 | v2 新增 `CriterionItem`（被评价对象可以是 `{kind: external_document, text}`）、`Trajectory`（步骤带 `step_kind` 与 `raw` 透传）、`DecisionPoint` | WP-01 |
| R4 | v2 证据条目用 `valid_from` / `valid_to` 表达版本有效期；外部文档记录 `time_model: versioned_document`，`as_of_seq` 置 0 并以 `document_revision` 代替 | WP-01、WP-D1 |
| R5 | 两份合成会话由真实运行导出替代；原文件移入 `data/external-samples/_superseded/`，附 `README.md` 列出每处与引擎的不一致 | WP-D1、WP-D2 |
| R6 | 从 pydantic 导出 JSON Schema 到 `schemas/`；新增 `career-lab data validate <文件或目录>`；测试中加入对 `data/external-samples/` 和 `data/releases/` 全量校验 | WP-01、WP-D1 |
| R7 | `publishable: false` 的记录不进入发布目录；Jira 条目改从 Public Jira Dataset 取；TheAgentCompany 的运行记录只保留本地格式参考 | WP-D1、WP-D8 |
| R8 | 外部样例全部重新过一遍第 6 节的标注流水线，得到带模型、提示词版本和日期的 G2v 标签；原有标签保留在 `labeling.legacy` 中 | WP-D6 |

### 4.4 逐文件处置

| 文件 | 处置 | 结果位置 |
|---|---|---|
| `open-source-pm-samples.jsonl/.md` | 导入为 18 条关系项；候选证据从 4 条补到 8 条（从同一来源文档再取干扰句，记录为 `transformations: [padded_distractors]`）；重新标注 | `data/releases/public-aux-v1/relation/` |
| `judge-criterion-samples.jsonl/.md` | 导入为 9 条评价项；`source_state` 原样保留，`label` 由声明的映射表产生并记录 `mapping_version`；来自 experiments 仓库的 3 条标 `publishable: false` | `data/releases/public-aux-v1/criterion/`；不可发布的留在 `data/local-only/` |
| `process-trajectory-samples.jsonl/.md` | 导入为 4 条轨迹，`step_kind` 分别为 `field_change`、`agent_action`、`dialogue_turn`；诊断标注重新由模型两遍生成并标 G2v；Jira 条目换源后重取 | 同上 |
| `info-action-synthetic-samples.jsonl/.md` | 不导入为数据；保留为提示词与格式参考，标 `label_tier: synthetic_assumed`；由 WP-12 的环境推导标签替代 | `data/external-samples/_reference/` |
| `showcase-*.json/.md`、`synthetic-scenario-chain.json/.md` | 不导入；移入 `_superseded/` 并写差异说明；用 `career-lab export` 对真实运行导出同一流程的四类数据 | `data/external-samples/_superseded/`；`data/releases/env-v1/` |

### 4.5 溯源要求

每条外部记录带：

```yaml
source:
  name: GitHub Username Policy
  url: https://github.com/github/site-policy/...
  revision: 21a781fa4f          # 提交号或取数日期
  retrieved_at: 2026-10-06
  license: CC0-1.0
  license_hash: <许可文件的 sha256>
  locator: Policies/github-company-policies/...#L12   # 原文位置
publishable: true
transformations:
  - {kind: translation, by: {model: ..., prompt_version: ...}, note: 中文译文未经人工核对}
  - {kind: claim_authoring, by: {model: ...}}
  - {kind: padded_distractors, from: same_document}
labeling:
  legacy: {label: CONTRADICTED, tier: G2, note: 2026-10-06 草稿中的标签}
  current: {label: ..., tier: G2v, model: ..., prompt_version: ..., passes: [...]}
```

环境运行的记录带 `provenance: {session_id, branch_of, seq_range, executor_summary, export_command, code_revision, scenario_hash}`。

### 4.6 防止再发

- `schemas/` 目录由 `career-lab schema export` 生成，CI 测试断言它与 pydantic 定义一致。
- 任何写数据文件的 Agent，交付前必须运行 `career-lab data validate`；执行计划 6.5 节把这条列为交接检查项。
- 合成会话只能由 `career-lab export` 从真实运行产生；禁止手工编写“运行记录”。

## 5. 导出流水线

【设计】`career-lab export --database-url <数据库> --session <会话 id> [--branch <分支 id>] --output <目录>` 从一个会话导出四类切面。实现放在 `src/career_lab/datasets/export.py`。

### 5.1 关系与证据的提取

| 断言来源 | 提取规则 | G0 判定 |
|---|---|---|
| 助手回答 | 测试记录中含数值、版本、日期或“不能／需要”类陈述的句子 | 与账本对照：数值相等且版本有效为 SUPPORTED；数值不等或版本过期为 CONTRADICTED；账本无对应为送模型 |
| 成果里的 `claims` | 每条 `claims[*].text` | 若 `evidence_refs` 指向配置、事件、测试记录且可程序核对，按核对结果定标；否则送模型 |
| 角色陈述 | 回合结果中与 `disclosed_fact_ids` 对应的句子 | 由包含性检查定标；不通过的送模型 |
| 外部文档 | 导入器提供 | 送模型 |

候选证据的构造：目标 8 条，包含正确集合、同一会话内的干扰项（旧版本、无关材料、无关测试记录）；证据顺序随机并记录种子；每条带 `kind`、`version`、`observed_at_seq`、`valid_from_seq`、`valid_to_seq`。

### 5.2 原子评价项的提取

每次提交乘以 rubric 的全部评分项。证据按评分项的 `evidence_types` 选取；`rule_bound` 来自规则 v3。`decided: true` 的记为 G0；其余送模型。父会话与分支在同一评分项上的记录互相填写 `pair_of`。

### 5.3 过程轨迹的提取

步骤表来自事件与对象；诊断来自检测器（规范 6.7 节）；叙述性标注可选，由模型两遍生成。

### 5.4 信息动作的提取

参考 Agent 运行器在每步记录决策日志（候选动作、信念状态、选择）。导出时对每个候选在状态副本上执行一次，得到 `outcome_type`（规范 8.3 节）。真人会话没有候选日志，只记录实际选择；可以事后枚举合法候选并同样推导标签，`chosen_by` 记为人。

### 5.5 泄露过滤

导出的 `model_input` 不含路径夹具、探针预期、关键事实清单、未来事件、不可披露的私有事实。导出器用一个黑名单测试：把这些内容的特征字符串与导出文件逐条比对，命中即失败。

## 6. 模型标注流水线

【设计】实现放在 `src/career_lab/labeling/`，命令前缀 `career-lab label`。

### 6.1 接入方式

两种方式都支持，由配置 `labeling.transport` 选择：

| 方式 | 做法 | 适用 |
|---|---|---|
| `api` | 通过现有的 OpenAI 兼容适配器调用，`base_url`、`model`、密钥文件由配置给出；并发与重试有上限 | 有 API 密钥时 |
| `agent_batch` | 流水线只负责切批、校验和汇总；每个批次是一个输入文件和一个待写的输出文件；由一个 Agent（例如在 GPT 订阅下运行的 Codex）读取输入、按提示词逐条标注、写出输出；校验器拒绝不合格的输出并要求重写该批 | 只有订阅、没有 API 密钥时 |

两种方式的输出格式相同，校验器相同。`agent_batch` 方式下，Agent 使用的提示词必须是仓库里的版本化文件，不得自行改写。

### 6.2 批次格式

```text
labeling/<任务>/<数据集版本>/
  manifest.json                 # 任务、提示词版本、模型、批次列表、分区
  batches/b0001.inputs.jsonl    # 每行一个 model_input，不含 gold
  batches/b0001.A.jsonl         # 第一遍输出
  batches/b0001.B.jsonl         # 第二遍输出
  batches/b0001.C.jsonl         # 裁决输出，仅对分歧条目
  batches/b0001.report.json     # 校验结果、一致率、用量、耗时
```

输出行的固定形状：

```json
{"item_id": "...", "label": "...", "evidence_ids": ["e1"], "reason_code": "...", "explanation": "...",
 "model": "<响应返回的模型标识>", "prompt_version": "rel-v1", "pass": "A", "created_at": "..."}
```

### 6.3 两遍标注与裁决

| 遍 | 输入 | 要求 |
|---|---|---|
| A | `model_input`，证据按原顺序 | 提示词版本 `*-v1-a` |
| B | 同一 `model_input`，证据顺序打乱、编号重排，提示词措辞不同（`*-v1-b`），独立上下文，看不到 A 的输出 | 结果映射回原编号后比较 |
| C | 仅对 A、B 不一致的条目：给出两遍的标签和理由，要求独立判断并说明采纳哪一方或都不采纳 | 提示词版本 `*-v1-c` |

一致（标签相同且引用集合在可接受集合意义上等价）即为 G2v；经 C 裁决的记 G2v 并标 `adjudicated: true`；C 仍无效的记 `unlabeled`。每批报告分歧率，按任务和类别统计。

### 6.4 校验器

每条输出都要通过：JSON 可解析；`label` 在该任务的标签空间内；`evidence_ids` 是候选证据的子集；评价项的 `label` 在 `rule_bound` 以内；`explanation` 不超过规定长度；输出中不出现候选证据以外的材料名或数值（防止模型把外部知识当证据）。不通过的条目退回重标，重标次数有上限。

### 6.5 校准

在大规模标注之前，先用同一流水线标注受控实验 v2 的开发分区（288 条 G0 关系项）和环境运行中规则已定标的评价项子集，得到标注模型相对程序真值的准确率、逐类精确率与召回率、kappa。准确率低于 0.9 时先修提示词再放量；修改只允许看训练与开发分区。校准结果随数据集发布，是 G2v 可靠性的唯一量化依据。

### 6.6 分区约束

提示词的调整、少样本示例的选择、裁决规则的修改都只能使用训练与开发分区。测试分区由冻结后的提示词版本一次性标注，标注日志写入冻结记录。

### 6.7 成本与记录

每批记录模型标识、提示词版本、条数、重试次数、用量（API 方式有 token 数；Agent 方式记录批次数与墙钟时间）、校验失败数。汇总进数据卡。

### 6.8 可选的人工抽检

规范 U6。若做：两名成员各独立标注 30 条关系项和 30 条评价项，与 G2v 比较并报告一致率。经两人独立标注并裁决的条目可以标为 G1 并单独报告，但本计划的任何步骤不依赖它。

### 6.9 可选的跨模型核对

仓库已有 DeepSeek 密钥。对分歧集合可以再请一个不同提供商的模型给第三意见，记录为 `cross_model_opinion`，不改变等级规则。

## 7. 分区与泄漏控制

- 分区键是 `structure_id`。S1 到 S4 为训练与开发；S5、S6 为测试（取决于规范 U5）；分配写在 `scenarios/registry.yaml`。
- 同一结构的数值变体、改写、分支、从中导出的全部记录和整理出的技能都在同一分区。
- 受控实验 v2 的测试分区只作回归；不再作为任何选择的依据。
- 公开辅助桶单独划分：按来源文档分组，同一文档的记录不跨分区。
- 泄漏检查脚本：按 `lineage` 校验无跨分区；按文本近重复（归一化后 shingle 相似度）报告疑似泄漏并列出。

## 8. 发布格式与数据卡

目录：

```text
data/releases/env-v1/
  manifest.json          # 数据集版本、代码提交号、场景 hash、分区、条数、标签等级分布、标注模型校准结果
  data_card.md
  LICENSES/
  relation/{train,dev,test}.jsonl
  criterion/{train,dev,test}.jsonl
  trajectory/{train,dev,test}.jsonl
  decision/{train,dev,test}.jsonl
  skills/ candidates/    # 第五类
  lineage.jsonl
  labeling/              # 第 6 节的批次目录
data/releases/public-aux-v1/   # 同样布局，只含 publishable: true 的记录
data/local-only/               # 不可发布的记录
```

数据卡必须写明：来源与桶的构成；标签等级分布及含义（G2v 不是人工标签）；标注模型、提示词版本、校准结果、分歧率；分区规则；已知限制（合成环境、单一产品情境、模型标注）；许可。

公共字段的完整清单：`schema_version`、`record_id`、`task_type`、`label_tier`、`bucket`、`lineage{root_scenario_id, structure_id, derivation_id, session_id, branch_of}`、`split`、`provenance`、`source`（外部）、`transformations`（外部）、`publishable`、`language`、`labeling{method, model, prompt_version, passes, agreement, adjudicated}`。

## 9. 工作包

### WP-D0 标注模型接入冒烟

**目标**：确定 `gpt6-astra` 的接入方式并跑通 20 条。

**依赖**：无。**步骤**：按规范 U10 确认是否有 API 密钥；用 20 条受控 v2 开发项分别尝试 `api` 或 `agent_batch`；记录实际模型标识、延迟、每条用量。

**验收**：`docs/reports/expansion/labeling-smoke.json` 存在，含 20 条的输出、校验结果和与 G0 的一致数；进度记录写明选定的接入方式。

### WP-D1 外部样例根因修复、导入与溯源

**目标**：完成第 4 节的全部处置。

**依赖**：契约 v2（执行计划 WP-01）。**步骤**：实现 `scripts/import_external_samples.py` 与 `career-lab data validate`；导出 `schemas/`；逐文件处置；写 `_superseded/README.md` 的差异说明；把 4.1 节的失败案例写成回归测试（旧文件在新导入器下全部通过）。

**验收**：`uv run career-lab data validate data/external-samples data/releases` 通过；导入条数 18、9、4 与原文件一致，其中 `publishable: false` 的条数单独列出；`_superseded/README.md` 列出至少 4.2 节 R5 的六处不一致；测试通过。

### WP-D2 导出命令

**目标**：第 5 节的四类切面由一条命令产生。

**依赖**：WP-01、执行计划 WP-04（执行者、成果类型）、WP-05（规则界）。**步骤**：实现 `export.py`；在 `runs/synthetic-flow` 的数据库副本和一条新运行上各导出一次；实现泄露过滤测试。

**验收**：导出文件全部通过 `data validate`；用路径 B 会话与“忽略变更”分支导出，得到同一评分项上的 `pair_of` 成对记录并给出条数；泄露过滤测试通过。

### WP-D3 标注流水线

**目标**：第 6 节的切批、两遍、裁决、校验、汇总可用。

**依赖**：WP-D0。**步骤**：实现 `labeling/`；提示词文件 `prompts/labeling/{rel,crit,traj}-v1-{a,b,c}.md`；校验器；批次报告；两种接入方式各跑一个小批。

**验收**：离线测试用脚本化模型覆盖：越界标签被拒、无效引用被拒、A 与 B 不一致触发 C、C 无效记为 `unlabeled`；真实小批（每任务 30 条）报告存在；校准步骤（6.5 节）在受控 v2 开发分区上完成并给出准确率与 kappa。

### WP-D4 规模化环境运行

**目标**：按 3.1 节的 suite 跑出数据主体。

**依赖**：执行计划 WP-12、WP-13、WP-15。**步骤**：编写 suite 清单；分批运行并导出；每批运行后跑泄露检查；故障注入子集单独标记。

**验收**：产量表的每一行给出实际数字；RunManifest 与轨迹一一对应；分支与父会话的 `pair_of` 关系完整；运行失败的会话数单独列出。

### WP-D5 分区、泄漏检查与发布脚本

**目标**：第 7、8 节。

**依赖**：WP-D2。**步骤**：`scenarios/registry.yaml` 的分区；泄漏检查脚本；`career-lab data release --bucket env --version v1`；数据卡模板。

**验收**：泄漏检查通过并输出报告；发布目录结构与第 8 节一致；`manifest.json` 含标签等级分布与校准结果字段（可先为空，由 WP-D6 填入）。

### WP-D6 全量标注

**目标**：对 WP-D2、WP-D4 导出的语义类条目和 WP-D1 导入的外部条目完成两遍标注。

**依赖**：WP-D3、WP-D4。**步骤**：先训练与开发分区；冻结提示词版本；再测试分区；汇总分歧率；填入数据卡。

**验收**：每个任务的 G2v 条数、`unlabeled` 条数、分歧率、裁决比例写入数据卡；测试分区的标注日志记录了冻结的提示词版本；没有任何一条测试分区的记录被用于提示词修改（用日志时间戳核对）。

### WP-D7 可选人工抽检

**目标**：第 6.8 节。**依赖**：WP-D6。**负责人**：成员。**验收**：若执行，报告两人与 G2v 的一致率和两人之间的 kappa；若不执行，数据卡写明未执行。

### WP-D8 公开来源扩充

**目标**：按 3.3 节扩充公开辅助桶。

**依赖**：WP-D1。**步骤**：site-policy 再取 3 到 5 个有改版历史的政策；KEP 再取 5 到 10 份清单；Public Jira Dataset 取 10 到 20 条有计划顺延特征的 issue；每条记录按 4.5 节写溯源；送 WP-D6 标注。

**验收**：新增条数按来源列出；每条有 `source` 与 `transformations`；许可文件进入 `LICENSES/`；`publishable` 标记正确。

## 10. 数据与实验的对应

| 实验 | 使用的数据 |
|---|---|
| E1 监督模型 | 受控 v2 关系项（G0）；环境关系项（G0 与 G2v）；公开辅助关系项单独报告 |
| E2 混合评价 | 环境评价项：规则定标的 G0 部分检验规则，G2v 部分检验 Judge |
| E3 Jev | 关系项的 G0 子集与 G2v 子集 |
| E4 主动获取 | WP-D4 的运行记录与决策点 |
| E5 技能迁移 | 训练与开发结构的轨迹用于整理；未见结构的运行用于评测 |
| E6 自动优化 | 开发结构的失败轨迹与反馈 |
| E7 过程诊断 | 轨迹的诊断标注与分支验证记录 |
| E8 结构泛化 | `scenarios/registry.yaml` 与各结构的运行结果 |
| E9 SFT | 评价项与关系项的训练分区（G0 与 G2v，分别统计） |
| E10 组合消融 | 同 E4 的 suite，切换模块 |
| E11 真人试用 | `human_session` 桶 |

## 11. 待裁定

| 编号 | 事项 | 默认值 |
|---|---|---|
| D1 | 批次大小 | 每批 50 条 |
| D2 | 校准门槛 | 相对 G0 的准确率 0.9 |
| D3 | 候选证据条数 | 8 条；外部来源不足时如实记录 |
| D4 | 叙述性轨迹标注是否生成 | 生成，但只用于工作台展示，不进入实验 |
| D5 | 分歧率超过多少时暂停放量 | 30% |

与规范 16 节相关的事项：U6（人工抽检）、U7（业务合成）、U8（外部样例入库）、U10（接入方式）。
