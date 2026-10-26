# 交接：演示录制组提的八件事，核对结果与改动

日期：2026-10-26　读者：录制演示、接前端的组员　上一份：[进入视频和报告阶段](handover-deliverables-20261021.md)

分支 `claude/rc10-demo-feedback`（基于 main @ c20fa82）。合入后**重启 serve 和三个 worker**；`src/career_lab/models/` 下没有改动，C1 回传登记不用重做。

## 0. 一句话结论

| 你们提的 | 核对结果 | 处理 |
|---|---|---|
| 逐句模型建议大多在长度检查时弃权（英 10/10、中 8/9） | 属实。根因不是长度上限，而是送进模型的候选是**整篇材料**（brief 258 token、demand 498、trial_details 5134，上限 160）。按句切分的逻辑只切带 span 的候选，整篇引用的材料 span 为空，没切 | 整篇材料也切成句子单元（每个单元是材料里一段精确原文，带 span）。切完后同一批作品句的「句子 + 候选」最长 110 token，不再弃权 |
| 「政策已更新：…400 元」建议说矛盾 0.89，产品链说支持 0.50 | **产品链对，建议错。** 新政策原文就是 400，规则分支读到同数同单位给支持；「逐句模型建议」只有 XLM-R 一个分支，把这句和新政策判成了矛盾（本机复现：单模型对 policy-v2 的 pair 概率 C=0.70）。产品链里 XLM-R 也判矛盾，被规则按 α=0.4 拉回到支持 0.51 | 不改判定。关系记录现在带各分支分数（见第 3 节），透镜里能直接看到是哪一支把它拉回来的 |
| 行为摘要前后对不上（冻结 3 步 vs 实时 20 步） | 属实，根因就是你们查到的：`job_view` 没挂公共历史，`behavior._events` 拿到空列表，只剩对话轮次 | 口径定为**整局截至交付点的全部可见动作**（含交付那一步）。`job_view` 现在在同一事务内按任务自己的授权读完历史、冻结在视图里；行为记录保存每一步的 `seq / symbol / event_id` 和窗口 `window{from_seq,to_seq}`，可逐步对照实时接口 |
| e5 版本记录是 unhashed | 属实 | 未登记的 e5 目录加载时现算树哈希作版本号；本机已 `registry add`，revision `2933a10907b4` |
| Mac 版编码器登记 `registry-mac/encoder-24978a76…` 行不行 | **可以，这正是设计**：登记项钉住 torch 等四个包的已装版本，所以 id 按机器不同。要对得上的只有 `model_revision`（`hf-encoder-v3:1a620086ac00…`），请在你们的 registration.json 里核对这一项 | 写进了演示交接第 4 节 |
| 命中原句偶尔不准（「80 人」） | 命中句按字符二元组重合选，整篇材料里带数字的句子会输给词多的句子 | 先按作品句里的数量（80 人）匹配，再按重合度。材料切成句子后这个问题本身也少了 |
| 矛盾句引用了旧测试记录而不是新政策（F04） | 属实。两边都判矛盾时取的是模型的证据，模型证据按检索顺序排，旧记录排在前 | 两边一致时规则比对到的那条（新政策）排第一，模型证据按 pair 分数降序跟在后面。另外规则多读一类单元：**会话中才生效的限额**（`valid_from_seq > 0`，演示局里就是政策 v2，`valid_from 13`）只要和作品句同一计量单位，不论检索排第几都进规则比对。原因：作品重复旧数字时，复述旧数字的老回答会把新政策挤出 top-5（本机复现「住宿上限 500 元」时 policy-v2 排第 19）；只放宽给会话中生效的限额，是因为按相似度放宽会把餐费上限 100 元也拉进来，给「400 元」那句判出假矛盾（已复现并排除） |
| 可选：参考轨迹 ID / 版本 / 序列 | 已加 | `strategy.reference = {id: "behavior-v1@<revision>#<index>", index, strategy, sequence}` |
| 可选：融合各分支分数 | 已加 | 每个作品句的 `branches`：`encoder`（XLM-R 单独）、`stack`（堆叠）、`pairs`（逐候选 pair 分）、`rule`（规则分布，没法比时为 null）、`rule_window`、`alpha` |

## 1. 行为分析：口径与数据

- **口径**：交付时的行为分析 = 该局从开始到交付命令所在快照点的全部**学员可见**事件（material_read、test_assistant、config_applied、request/decision、index_refreshed、submitted、revision_opened、场景里程碑）加上三位同事的对话轮次。交付那一步本身计入（`steps[-1].symbol == "submit"`）。
- **实现**：`storage/v2_jobs.py::job_view` → `_with_frozen_history`。任务视图离开事务后还要用，所以历史在事务内读完（用 `public_history_reader`，和实时 `GET /behavior` 同一个读取器、同一套 `reference_allowed` 权限检查，上限是任务快照的 `business_seq`），然后以静态 `public_history(page, auth)` 挂回视图。所有 v2 任务（反馈、同事回合）都经过这里；同事 prompt 的 `learner_state` 因此也能看到阶段和已读材料了。
- **可对照的数据**：行为记录 `outputs` 新增 `window {from_seq, to_seq, events, turns}`、`steps [{seq, symbol, event_id}]`、`reference`；`GET /behavior` 的 `sequence[]` 每行也带 `event_id`，`window` 同形。回归测试 `tests/regression/test_recognition_behavior_window.py`：冻结 `steps` == 实时 `sequence` 过滤到 `to_seq` 的部分。
- **「回看工作过程」**：参考轨迹在 `strategy.reference.sequence`，学员轨迹在 `sequence[]`，`alignment{missing, extra, swapped}` 不变。

## 2. 逐句模型建议的长度预算

- 不动 `max_tokens=160`（训练时就是 160，`truncation="only_second"`），也不截断。改的是候选：`recognition/units.py::candidate_units` 对 span 为空、整篇引用的候选（材料、测试记录）也按句切，单元 ≤160 字符、ref 带精确 span；候选总数仍按与作品的检索分数封顶 80。模型建议那条链用的是同一个包（`relation_input` → `sentence_input` → top-5），所以切分自然传到它。
- 复现数据（pm_pilot 中文演示作品 9 句、英文 10 句，本机 XLM-R 分词）：整篇材料时 top-5 里只要有一篇 >120 token 就弃权；切成单元后每对最长 110 token（中文）、110（英文），`0/9`、`0/10` 弃权。
- 顺带：`title` 以前靠材料正文的 Markdown 标题，切句后由 `title_of(ref)` 从场景包取材料标题，`tests/regression/test_recognition_signal.py` 里那条 `title` 断言仍过。

## 3. 关系判定里新增的字段

每个作品句（`recognition.relation.outputs.units[]`、预演/句子路由 `units[]`、冻结反馈里同）多了 `branches`：

```json
{"encoder": {"supported": 0.07, "contradicted": 0.86, "insufficient": 0.07},
 "stack":   {"supported": 0.01, "contradicted": 0.98, "insufficient": 0.01},
 "pairs":   {"e-…policy-v2": 0.74, "e-…test": 0.97},
 "rule":    {"supported": 0.90, "contradicted": 0.05, "insufficient": 0.05},
 "rule_window": 6,
 "alpha": 0.4}
```

`rule` 为 `null` 表示规则没找到可比的数字（这时没有融合，`reason` 是 `pair_aggregate`）。没有模型时只有 `{"rule": …, "rule_window": n}`。最终 `probabilities = alpha·stack + (1−alpha)·rule`。

证据顺序：两边同判时 `evidence_ids[0]` 是规则比对到的候选；只有模型判定时按 pair 分数降序。

## 4. 两件事请你们那边确认

1. 跑 worker 的那台机器也要设 `CAREER_LAB_RECOGNIZERS`（没权重也设，指到任意目录即规则回退）；不设的话评审包不会切单元，模型建议照旧弃权。
2. Mac 登记的 `registration.json` 里 `model_revision` 应等于 `hf-encoder-v3:1a620086ac0067bc33cc8ff30e971baa6de8470e86f3789033a3d42e5bb6b87a`；是这个就对，`encoder-…` 的 id 不必一致。

## 5. 顺手修的和没修的

- main 在 Windows 上起不来：四处 `import fcntl`（`runtime/model_audit.py`、`engineer/review_store.py`、`engineer/session_store.py`、`reference_agent/journal.py`）。加了 `runtime/file_lock.py`（POSIX 用 flock，Windows 用 msvcrt），`os.O_NOFOLLOW` 改成 `getattr(os, "O_NOFOLLOW", 0)`。行为不变。
- 没修、Windows 上本来就失败的测试（Mac 上应当是绿的，CI 也是 Linux）：`tests/unit/test_return_v3_package.py::test_pkg_05`、`tests/integration/test_relation_units_export.py::test_exp_07`（导出清单路径分隔符）、engineer 私有目录权限检查（`st_mode & 0o077`、`os.getuid`）相关的一批。这些与本次改动无关，在不含本次改动的 main 上同样失败。
- 已知局限，没在这次动：XLM-R 单模型对「政策已更新…400 元」这类句子仍会判矛盾（E1 里它就是 0.656 / 0.608 的水平），产品靠规则分支拉回；报告里讲法仍按机制速查第 10 节。
