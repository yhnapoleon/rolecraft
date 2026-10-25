# 工程师回归报告样例

这里的四个 JSON 是两次真实签字复核读回的记录：`GET /engineer/reviews/{review_id}` 返回的 `review` 对象（前端类型 `EngineerReviewRecord`）。其中 `report` 是公开回归报告 `EngineerPublicReport`，`evaluation` 是评价结论 `EngineerRuleEvaluation`。样例页 `#/engineer-report` 和回归报告组件 `src/features/engineer-report/` 读的就是它们。

情境是同一张工程委托：政策更新后索引还停在旧版，「住宿报销上限是多少？」照旧答出旧额度、没有过期提醒（目标探针 F01）。工程师用两种修法各签一次，中英各一份，业务事实相同。

| 文件 | 样例页标签 | 修法 | 目标 | 公开 4 条 | 隐藏 9 条 | 隐藏对比（新增失败 · 修好 · 仍未通过 · 未核实） | E1–E5 |
|---|---|---|---|---|---|---|---|
| `sample-root-cause.{zh,en}.json` | 根因修法 | `freshness_guard: warn` | F01 修好 | 全部通过 | 通过 9 · 未通过 0 · 出错 0 | 0 · 2 · 0 · 0 | 满足 · 满足 · 满足 · 满足 · 等待模型核验 |
| `sample-overreach.{zh,en}.json` | 改得太宽 | `freshness_guard: warn` 加 `min_score: 0.2` | F01 修好 | 全部通过 | 通过 8 · 未通过 1 · 出错 0 | 1 · 2 · 0 · 0 | 满足 · 未满足（新增失败，隐藏 1 条）· 满足 · 满足 · 等待模型核验（还有 1 条隐藏失败没有解释） |

两份的 `status` 都是 `verified`，自报与重跑一致（`claim_check: matched`）。

## 生成条件

- 2026-10-24，191 集成分支 `claude/191-eng-integration` 提交 `7832651`，脚本 `scripts.engineer_review_samples`：每种语言一个新库、一局新练习，从工程师卡直接开委托（系统先完成试点上线），以本人身份签两份草稿，再经接口读回。复核与试跑固定用规则版检索，不调用模型；数据库、工程师目录和私有复核库放在临时目录，用完即删。
- 除公开报告和评价结论外，记录里还有 `review_id`、`signed_at`、`signed_by`、`draft_id`、`ticket_id`、`impact_note`、`retrieval`。逐份核过：不含令牌和本机路径。`signed_by.id`（`human:` 加会话号）与引用里的 `session_id` 来自脚本的一次性库，单独拿到没有任何权限。`impact_note` 是脚本写好的示意说明，代替学员自己写的影响说明，不含个人信息，报告组件不显示它。以上都按接口原样保留。

## 怎样重跑

在 191 集成分支 worktree 的根目录（已 `uv sync --locked`）：

```sh
unset PYTHONPATH
.venv/bin/python -m scripts.engineer_review_samples --output runs/local/engineer-review-samples   # 输出目录不能已存在
```

脚本每写一份打印一行摘要（E1、E2、隐藏修好与新增失败数）。把四份按下表复制到本目录：

| 生成的文件 | 本目录文件名 |
|---|---|
| `zh-root-cause.json` | `sample-root-cause.zh.json` |
| `en-root-cause.json` | `sample-root-cause.en.json` |
| `zh-demo-overreach.json` | `sample-overreach.zh.json` |
| `en-demo-overreach.json` | `sample-overreach.en.json` |

复制前逐份检查没有令牌和本机路径（例如 `grep -E '"token"|/Users/|runs/|Bearer' *.json` 应无输出）。重跑后时间、哈希和会话号会变；测试里按样例写的断言（`src/features/engineer-report/*.test.ts` 中的 ER-03、ER-05、ER-20、ER-38 至 ER-42）若受影响要同步。
