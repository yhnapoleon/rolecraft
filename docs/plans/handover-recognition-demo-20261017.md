# 模式识别层与演示会话包：交接（2026-10-17）

写给三类人：合并 PR 的组员、要跑演示的人、接着做的人（包括下一个 Claude 会话）。这里只放入口和要紧的事实；逐项细节、命令和踩过的坑在[进度文档](progress-pattern-recognition-20261016.md)，设计依据在[完整设计](pattern-recognition-design-20261016.md)。

## 1. 现在是什么状态

- 识别层（C1 关系判定、C2 检索、C4 范围、C5 行为、C6 拒识与仲裁、C10 回复核查、C11 意图）已经占住三个 LLM 入口（评审 JUDGE、同事 ROLES、知识助手 ASSISTANT）的输入装配，每一页都有识别署名；四个模型槽都接 DeepSeek。
- 第二个领域 `it_ticket_pilot`（IT 工单助手）中英都能玩；实验 E1、E3–E10 全部跑完，识别实验室页有图。
- `demo/` 里有 8 局录好的练习，任何部署一条命令导入，用继续码打开，**不调用任何模型**。
- 报告、slides、视频还没开始。全部代码在 5 个 PR 里，**10-19 已全部合入 main**（`18ecf41`）。
- 10-19 起进入交付物阶段：架构图在 [`docs/figures/`](../figures/)，README 改成以识别为中心的英文版，旧中文 README 的内容见 git 历史（`18ecf41:README.md`）。

## 2. 合并 PR（已完成，留作记录）

| PR | 内容 | 依赖 |
|---|---|---|
| [#58](https://github.com/yhnapoleon/rolecraft/pull/58) | 后端识别层 `src/career_lab/recognition/`，三个入口装配，`GET /recognition`、`/behavior`，预演附逐句识别 | — |
| [#59](https://github.com/yhnapoleon/rolecraft/pull/59) | 前端：署名组件、复盘页汇总、行为页、识别实验室 `#/lab`、预演逐句标色、IT 场景入口 | 运行时要 #58 的接口 |
| [#60](https://github.com/yhnapoleon/rolecraft/pull/60) | 实验脚本与结果（`experiments/recognition/`） | — |
| [#61](https://github.com/yhnapoleon/rolecraft/pull/61) | 第二领域 `it_ticket_pilot`（场景内容、构建脚本、生成的包） | 叠在 #58 上 |
| [#62](https://github.com/yhnapoleon/rolecraft/pull/62) | 演示会话包 `demo/`、IT 英文版、漂移数值规则、预演性能、进度文档与本文件 | 叠在 #61 上 |

顺序：**#58 → #61 → #62**，#59、#60 随时。都是演示版：碰了契约文件（`RecognitionRecord`、几个结果对象加可选 `recognition` 字段）但**没有重导出契约**，远端契约回归和部分单测可能会红；`PROMPT_VERSION` 没改（发布包钉死）。

## 3. 只想演示

照 [`demo/README.md`](../../demo/README.md)：设三个环境变量 → `demo_pack import` 打印 8 个继续码 → 起服务和前端 → 首页「有继续码？」输入。那份 README 里有演示路线（每一页看哪个署名）。

三条提醒：

1. 主演示用**中文**局。英文局的语义评分项大多停在「待核验」（E8 也是这个趋势）。
2. 「交付前」那几局用来看预演：工作板点「交付」→ 勾版本 → 选「缩小范围推进」。**不要点「提交选中的版本」**。
3. 识别器权重不在仓库里。没权重的机器上，已存的识别记录照常显示，但行为页和预演会退回规则版（灰色「规则回退」）。要完整效果，在有权重的机器上演示，或按第 4 节拷权重。

## 4. 要跑完整产品（实时对话、实时评审）

需要：

- `.venv-encoder`（CPU 版 torch 2.8.0、transformers 4.57.1、hmmlearn 0.3.3；用 `uv pip` 装进去，没进 `uv.lock`）。
- 识别器权重目录 `runs/local/recognizers/`（约 1.5 GB：`c1-xlmr-cpu` 1.1 GB、`retrieval-e5` 470 MB，其余几 MB），整个目录拷过去即可，`manifest.json` 里是相对路径。
- DeepSeek key 文件（仓库根目录 `ds.txt`，已在 `.gitignore`）。

环境变量（本机写在 `runs/local/dev/env.ps1`，`runs/` 不入库，组员照下面设）：

```powershell
$env:CAREER_LAB_SCENARIO_CATALOG = "demo/catalog.json"          # 仓库相对路径，从仓库根目录启动
$env:CAREER_LAB_CREDENTIAL_KEY_ID = "local-dev-v1"
$env:CAREER_LAB_CREDENTIAL_KEY = "<至少 32 字节>"
$env:CAREER_LAB_RECOGNIZERS = "<拷来的>\recognizers"             # 不设 = 三个入口都不经过识别层（回到原行为）；设了但缺某个权重 = 该识别器规则回退
$env:CAREER_LAB_RELATION_ENCODER = "<拷来的>\recognizers\c1-xlmr-cpu"
foreach ($s in 'JUDGE','ROLES','ASSISTANT') {
  Set-Item "Env:CAREER_LAB_${s}_PROVIDER" 'deepseek'
  Set-Item "Env:CAREER_LAB_${s}_KEY_FILE" "<仓库>\ds.txt"
}
# 可选：反馈页「逐句模型建议」用的 C1 编码器回传登记（本机在 runs/local/c1-return/），
# 需要 CAREER_LAB_MODEL_REGISTRY / _REGISTRATION / _JOURNAL，见 env.ps1。
```

然后 `career-lab serve` 一个、`career-lab worker` 三个（都用 `.venv-encoder` 里的），前端 `apps/web` 下 `npm run build` 和 `npm run preview -- --port 18560`（设 `ROLECRAFT_API_TARGET`）。本机一键脚本是 `runs/local/dev/start.ps1`。改了 `src/` 下任何 `.py` 都要重启服务。

## 5. 识别层在哪里

| 识别器 | 做什么 | 在哪个入口出场 | 代码 |
|---|---|---|---|
| C1 关系判定 | 作品句 vs 材料句：支持 / 矛盾 / 证据不足（XLM-R pair_aggregate，冻结 10 层，本机 CPU 训练）+ 数值限额规则晚期融合 α=0.4 | 评审输入、SUPPORT 核验、预演、C10 | `recognition/relation.py`、`encoder_relation.py` |
| C2 检索 | 材料切单元，e5 / BM25 / RRF 排序 | 评审候选（≤80 单元）、助手打分、同事选源 | `recognition/units.py`、`retrieval.py` |
| C4 范围 | 马氏距离判问题在不在知识库范围；每个场景、每种语言单独拟合 | 助手测试卡 | `recognition/scope.py` |
| 漂移 | 同一问题索引刷新前后的答案差异（向量距离 + 数字变化） | 助手测试卡 | `recognition/scope.py::drift` |
| C5 行为 | 操作序列：DTW 最近策略、HMM 阶段、异常规则 | 复盘页「你的行为模式」、评审输入 | `recognition/behavior.py` |
| C6 拒识与仲裁 | 期望代价决定送人工；评审标签与 C1 不一致取保守 | 反馈页、预演 | `recognition/decision.py`、`judge.py` |
| C10 回复核查 | 同事回复逐句有没有依据、有没有泄露 | 同事回复气泡下 | `recognition/reply.py` |
| C11 意图 | 学员提问意图五类 | 同事回复气泡下、同事 prompt 的 `learner_state` | `recognition/intent.py` |

## 6. 实验结果（test，中 / 英）

| 编号 | 结论 |
|---|---|
| E1 | C1 macro-F1 0.656 / 0.608；**LR 特征叠加 C1 的堆叠最好，0.713 / 0.633**；纯词面经典模型大多 0.11–0.30 |
| E3 | 改写问题 Recall@5：e5 0.82 / 0.79，RRF 0.65 / 0.57，BM25 0.49 / 0.36 |
| E4 | 送人工 20% 时误扣分率 6.3% → 0.8%（总错误率不降，代价矩阵就是冲着误扣分）；ECE 0.009 → 0.006 |
| E5 | C4 AUROC 0.977 / 0.953 |
| E6 | 策略识别 1.0（脚本可分）；步骤扰动 0.5 时 DTW 0.71；异常 AUROC HMM 0.90 |
| E7 | 意图 LR 准确率 0.946 / 0.824 |
| E8 | 评审输入有 / 无识别摘要：待核验 57.4% / 61.1%，给出标签 42.6% / 38.9%，两组标签一致 0.675，R2.support 仲裁冲突率 23.5%——方向一致、幅度小 |
| E9 | C4 用 pm_pilot 拟合搬到 IT：AUROC 0.60 / 0.50；只用 IT 知识库拟合：0.986 / 0.949；C1 跨到 IT 0.592 / 0.631 |
| E10 | 晚期融合 0.630 vs C1 0.625（合计） |
| E2 | 没跑（要 Colab） |

数据都是 DeepSeek 生成、DeepSeek 复核，报告里要写明同源局限；数据集在 `data/releases/`，不入库。

## 7. 已知问题

- **C1 准确率只有 0.6 出头**，会误判：录好的演示局里，技术负责人说对的「可审批上限 60 人」被 C10 标成矛盾；故意写的过度表述「人工兜底已经落实」没被抓到。讲的时候说「识别器给出可核查的信号，不是裁决」。
  注意和[进度文档](progress-pattern-recognition-20261016.md)第 5 节区分：那里记的是**另一局**，DeepSeek 技术负责人把可审批上限说成现有容量（「上限是 60 人」），C10 判矛盾是对的。录好的演示包里是本条这种误判，视频里不能拿演示包这一局讲「识别层抓 LLM 的错」。
- **预演慢**：首算约 23 秒，再算约 8 秒（8 秒是规则核查本身，没识别器也要 8.7 秒）。前端给了 60 秒。
- **同事回复偶尔被拦**：LLM 安全复核（`role_help_unverified`）不放行时，气泡显示失败，重问一次即可。
- **SQLite 并发**：多局并行或实验和服务同时跑会报 `database is locked`。单人演示不会碰到。

## 8. 下一步

1. 合 PR → 组员拉代码 → 各自导入演示包、按路线彩排一遍。
2. S10 报告、slides、视频、架构图（第 5、6 节可以直接用）。
3. 性能（用户定为最后做）：产品端换成 E1 的堆叠模型（现成的 +5.7 / +2.5）；Colab 训更好的 C1（进度文档第 7 节有步骤）；预演提速。
4. 明确不做：人机判别（没有 Agent 轨迹）、工程师路径接 C1、E2。报告里写进「下一步」。

## 9. 文件索引

| 文件 | 用途 |
|---|---|
| [`progress-pattern-recognition-20261016.md`](progress-pattern-recognition-20261016.md) | 逐项进度、命令、验收记录、和设计的出入、坑 |
| [`pattern-recognition-design-20261016.md`](pattern-recognition-design-20261016.md) | 完整设计（唯一执行依据） |
| [`demo/README.md`](../../demo/README.md) | 演示包导入与演示路线 |
| `scripts/recognition/` | `demo_pack`、`demo_play`、`build_it_scenario`、`fit_it_scope`、`smoke`、数据合成与策略轨迹 |
| `experiments/recognition/` | 每个实验一个脚本，结果在 `results/`，`publish_lab` 复制给实验室页 |
