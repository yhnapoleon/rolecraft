# 回复：识别层补强请求（10-26 的 5 项 + 第四类口径）

日期：2026-10-27　读者：产品与前端组员　对应请求：《给 YH：识别层补强请求（5 项）与需要你判断的问题》　代码：PR `claude/rc12-recognition-requests`（基于 main `32c09134`）

## 0. 一句话答复

| # | 做 / 不做 | 状态 | 要点 |
|---|---|---|---|
| 1 检索方法 | 做 | 本 PR 已做 | 每句一个 `retrieval: {"method", "fallback"}`，预览顶层也给一份；不碰冻结契约 |
| 2 DTW 对齐路径 | 做 | 本 PR 已做 | `strategy.path = [{"i", "j", "cost"}, ...]`，只挂最近的参考；冻结视图不用另改 |
| 3 同事回复核查 F06 | 做（修根因） | 本 PR 已做，上不上短标看第 3 节的数字 | 根因不是模型，是候选整篇喂、数值规则跨候选比数、模型弃权把规则平均掉。三处都改了 |
| 4 同事知道学员进度 | 做，选 A | 本 PR 已挂钩子，等你们的 `colleague_brief` | `learner_state["aipm"]`；你们的函数一到就自动生效 |
| 5 逐句标注存服务端 | 可以 | 你们写 | 不要放进写事务里；和模型细看同一个后台作业；存的时候带 `recognizer` 与 `fallback` |
| 6 第四类 | 能申报 | 口径见第 6 节 | 行为事件流 → 符号序列 → HMM / DTW，加范围外检测；放在三类之后作「也覆盖」 |

## 1. 检索方法（C2）

- `relation.Judgement` 多了 `retrieval` 字段：`{"method": "rrf" | "dense" | "bm25" | null, "fallback": bool}`。`method` 是实际跑的方法；`fallback=true` 表示要的是 rrf 或 dense 但没加载到 e5，实际走了 BM25。没有候选时 `method` 为 null。
- 逐句预览（`POST …/submission-rule-check/recognition` 的 `recognition.units[*]`）每句都带这个字段，顶层 `recognition.retrieval` 再给一份（一次预览里所有句子的方法相同）。
- 不需要重导出契约：`Judgement` 是识别包内部结构，预览响应是自由 JSON，和 #73 加 `branches` 同一条路。
- 文案建议：`rrf` → 「语义检索 + 关键词检索融合」；`bm25` 且 `fallback` → 「关键词检索（语义模型未加载）」。

## 2. 逐点 DTW 对齐路径（C5）

- `GET /behavior` 的 `strategy` 多了 `path`，只给最近那条参考；`top3` 仍只有距离。
- 每一步是 `{"i": 本局第几步, "j": 参考第几步, "cost": 0 | 0.5 | 1}`，下标从 0 起，`i` 对应 `sequence` 的行号，`j` 对应 `strategy.reference.sequence` 的位置。路径从 (0, 0) 单调走到两端末尾。
- 插入、删除不用单独标：`i` 重复表示「你多做了」（本局一步对参考多步），`j` 重复表示「参考多做了」。`cost` 0.5 是同类动作不同对象（比如读了另一份材料），1 是不同动作；前端可按它把差别大的对齐画醒目。
- 冻结行为窗口（#73）不用另改：任务视图本来就是在冻结的历史上重跑 `analyze()`，`path` 随之算出。`path` 不进 `record.outputs`，需要时按 `steps` 和 `reference` 重算。

## 3. 同事回复核查（C10，F06 根因与修法）

### 3.1 根因（三处，都在调用方和规则，不在模型本身）

1. **整篇材料当一条候选**。`roles.after_reply` 把同事能看到的每份资料整篇喂给 `check_reply`；C1 的 `max_tokens` 是 160，只看每份资料开头的一百多个 token。同事引用的原文不在开头，模型就没见过，判「证据不足」。这是 10-26 给评审路径修的「候选是整篇材料没切句」，C10 这条路当时没一起修。
2. **数值规则在整篇文本上收集所有数字**。同事说「可审批上限 60 人」，经理委托里有「预留容量 30 人」且有「预留 / 容量」这类限额词，规则按 `exceeds_limit` 判矛盾 0.9；融合里规则占 0.6，模型拉不回来。演示包里那句「可审批上限 60 人」被标矛盾就是这个。
3. **模型弃权把规则的支持平均掉**。C1 对同事的转述句几乎一律给 0.98「证据不足」（E13 已经量出它在真实回答上基本失效）；规则找到原文里同一个数字只给 0.72 + 0.2 × 词面重合，0.4 / 0.6 加权后两边差不到 0.02，候选切成句子后词面重合变小，就从「支持」翻成「证据不足」。

### 3.2 改法

- `check_reply` 先把可见资料切成单元（句子、列表项，去掉标题），超过 80 个单元按与回复的相关度保留；每句附 C6 代价决策 `decision` / `expected_cost`，`evidence_units` 给出命中的原文单元和它在资料里的位置，`evidence_ids` 仍是资料 id，格式不变。识别器 id 升为 `reply-check-v2`。
- 调用方把每份资料的 `observed / valid_from / valid_until` 一起传入，规则能分辨「替换旧数字的通知」和「被替换的旧数字」（F04 在回复里同样成立）。
- 规则：断言本身在说上限（含上限 / 最多 / 容量等词）而某条候选原文给出同一上限时，另一条候选的较小数字不再构成矛盾（上限 60 与预留 30 是两回事）；断言没有限额词（「邀请 50 人」）而超过限额时，照旧判矛盾，不管别处有没有重复它的数字；更新的候选（`valid_from` 更大）永远赢。
- 同事回复路径开 `figure_first`：规则在原文单元里找到同一数字、而模型只是弃权时，规则的支持成立，不被平均掉；模型判矛盾时照常融合。评审路径不开这个开关，E10 量过的融合不变。

### 3.3 演示包回放（24 条同事回复、270 句，其中 177 句带出处或数字）

脚本 `scripts/recognition/replay_reply_check.py`，用真实权重（C1 + 堆叠 + e5）对 8 局演示会话里存下来的同事回复重跑。「录制时」是产品当时存下来的标签，「整篇」是旧候选形状 + 新规则，「单元」是现在的行为。

带出处或数字的 177 句：

| | 支持 | 矛盾 | 证据不足 |
|---|---|---|---|
| 录制时（产品存下的） | 46 | 20 | 111 |
| 整篇候选 + 新规则 | 61 | 4 | 112 |
| 单元候选 + 新规则 + figure_first（现在） | 63 | 7 | 107 |

现在仍判「矛盾」的 7 句里，C6 代价决策为「决定」的只有 1 句，其余都是「弃权」（defer），按第 3.4 节的门槛不会挂短标。判「证据不足」的 107 句是当前的主要短板：这些句子引用了规则或记录但没有可比的数字（「按审批规则，人工兜底要选 human」），规则没有可比项、C1 对转述句又一律弃权，就落在证据不足。这一类要靠换模型（E15）才能改善，当前模型下不能把「证据不足」当成「这句话没依据」。

全部 270 句：

| | 支持 | 矛盾 | 证据不足 |
|---|---|---|---|
| 录制时 | 51 | 25 | 194 |
| 整篇候选 + 新规则 | 61 | 4 | 205 |
| 现在 | 84 | 12 | 174 |

重跑用的可见资料是场景的公开材料（按回复时点取版本），没有同事的私有笔记，所以「录制时」一行和另外两行的输入不完全相同；两行重跑之间的输入相同。逐句结果在 `experiments/recognition/results/e16_reply_replay_demo.json`。

### 3.4 「待核实」短标上不上

- 可以上，但门槛要窄：只挂在 **`label == "contradicted"` 且 `decision == "decide"`** 的句子上（演示包 270 句里只有 1 句），文案用「待核实」，永远不写「矛盾」两个字。**不要**把 `insufficient` 当成「没依据」来挂标，见 3.3 的 107 句；它在当前模型下主要表示「模型读不出转述」。纯说明性的句子（「这两件事要分开看」）本来就没有依据可核，不该挂。
- 「依据」方向反过来用更稳：`label == "supported"` 的句子可以点开看 `evidence_units` 里命中的原文（现在给到句子级和位置），这是 C10 在正常界面里最可靠的一面。
- 以上是把 C1 换成 E15 的 mDeBERTa 之前能做到的程度；换模型要让 `encoder_relation.py` 支持序列分类结构并重新登记，约半天到一天，不建议在截止前碰。

## 4. 同事知道学员的进度和批改（ROLES 的 learner_state）

- 选 A。`behavior.learner_state()` 现在会调 `career_lab.aipm.colleague_brief(view, auth, language)`（也接受放在 `aipm.progress` 里），返回非空 dict 就放进 `learner_state["aipm"]`；函数不存在、返回 None、抛异常都静默跳过。你们的函数合进去即生效，合并顺序无所谓。
- 同事提示里加了一句：aipm 一项只用于决定从哪一处问起，不复述批改结论，不据此给答案。`cooperative-help-v3` 不用升；请在返回值里自带 `"revision": "aipm-brief-v1"` 之类的版本串，随 `learner_state` 进记录就可追溯。
- 不会挤掉资料：`learner_state` 在资料选源之后另加，不走 `max_chars` 预算。300 字封顶够用。
- 坑：`role_help_review` 会拒收带内部资料 ID 的回复，简报里用资料标题，不要用 SD-120 这种 ID，否则同事照着念就被拦。
- 整段只在 `CAREER_LAB_RECOGNIZERS` 开着时生效，CI 的快照测试不受影响。

## 5. 逐句标注存到服务端

- 可以。`draft_recognition` 就是前端已经在调的那条 C2 + C1 + C6 路，按 `support.input_hash` 缓存，同一版 PRD 前端核对过之后批改时再调基本零成本。不算新增识别调用点。
- 并发不用加锁，`EncoderRelation` 的推理本来就在一把全局锁里串行。要避免的是把这 1.6 秒放进 `review.create()` 的写事务，建议和 JUDGE 的模型细看放同一个后台作业，`model_status` 转 done 时一起写 `sentence_labels`。
- 识别层关闭存 null 可以；开着时请同时存 `recognizer`（`recognition.recognizer`）和 `fallback`，否则换了模型回看对不上。
- `SectionReview.sentence_labels` 的类型在你们的 `aipm/types.py`，不在冻结契约里，你们自己改。

## 6. 课程第四类「智能感知 / 意义建构」

能申报，按 [handover-deliverables-20261021.md](handover-deliverables-20261021.md) 第 1 节的口径：学员行为事件流转成符号序列，HMM 推阶段、DTW 对参考轨迹对齐（现在还能画出对齐线），加上问题流的范围外检测；整条识别链按 ISSM 的 sense-making 流水线组织，证据带版本和生效时点的上下文判断。写在前三类之后作「也覆盖」，不当主打。

## 7. 本 PR 改了什么、怎么验

- `recognition/relation.py`：`Judgement.retrieval`；规则的「冲突数字」处理；`judge(figure_first=)`。
- `recognition/reply.py`：候选切单元、C6 决策、`evidence_units`、`reply-check-v2`。
- `recognition/roles.py`：C10 调用带时效；提示句补 aipm。
- `recognition/behavior.py`：`dtw_path`、`strategy.path`、`learner_state["aipm"]` 钩子。
- `recognition/judge.py`、`api/recognition_signal.py`：透传 `retrieval`。
- `scripts/recognition/replay_reply_check.py`：演示包回放。
- 测试：`tests/unit/test_recognition_requests_1026.py`（12 个），加原有识别层单元 / 回归 / 集成测试。
