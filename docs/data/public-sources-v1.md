# 公开数据 v1：真实数据与基于真实数据的合成数据

日期：2026-10-20　对应：10-06《数据收集与标注计划》第 3.3 节「公开辅助来源」和 WP-D1、WP-D8（负责方本地文档 `docs/superpowers/plans/2026-10-06-rolecraft-data-plan.md`，未入库）；10-06 的开源来源调研；合成协议同 [识别层设计](../plans/pattern-recognition-design-20261016.md) 第 7 节的 `relation-v3`

## 0. 一句话

10-06 定的公开来源这次正式取齐了，分三个发布目录：**真实文本加真实标签**（`public-real-v1`）、**真实 PM 材料**（`public-materials-v1`，未经模型改写）、**以真实材料为证据、由 DeepSeek 写断言的合成数据**（`public-synth-v1`）。关系类记录和 relation-v3 同形，C1 和堆叠的评测代码不用改就能读。

## 1. 三个发布目录

| 目录 | 内容 | 条数 | 标签从哪来 | 等级 |
|---|---|---|---|---|
| `data/releases/public-real-v1/` | ContractNLI、VitaminC、CFEVER 三份关系数据 | 50,515 | 原数据集自带的人工标注 | G1 |
| `data/releases/public-materials-v1/` | 证据单元、KEP 签核清单、TheAgentCompany PM 任务、Jira 轨迹、tau-bench 轨迹 | 见 1.2 | 清单是作者自己打的勾；轨迹是最终状态或环境奖励 | G1 / 无标签 |
| `data/releases/public-synth-v1/` | 以 438 个真实证据单元为金标、按 v3 生成矩阵写的中英断言 | 3,839 条断言、14,865 个句对 | 生成规格 + DeepSeek 盲判一致才保留 | G2v |

每个目录都有 `manifest.json`（来源、固定版本、许可哈希、条数）、`data_card.md`、`SHA256SUMS`，许可原文在 `LICENSES/`。

### 1.1 public-real-v1（真实文本、真实标签）

| 文件 | 语言 | train / dev / test | 怎么转的 |
|---|---|---|---|
| `relation-contractnli.jsonl` | en | 7,191 / 1,037 / 2,091 | 607 份保密协议 × 17 条假设，全量，沿用官方划分。蕴含 / 矛盾 / 未提及 → SUPPORTED / CONTRADICTED / INSUFFICIENT；标注片段是金标单元（最多 4 个），同一合同里最像的 3 个非证据片段做难负例 |
| `relation-vitaminc.jsonl` | en | 8,003 / 2,003 / 4,000 | 只取 `revision_type = real`（证据来自维基百科真实改版，同一断言换一版证据标签翻转）；按 `case_id` 整组抽样；每条一个候选 |
| `relation-cfever.jsonl` | zh | 19,950 / 3,611 / 2,629 | 官方 test 无标签，所以官方 dev（三类各 1,000）当 test，官方 train 按断言块 85/15 拆成 train/dev。繁转简（OpenCC t2s）、去掉分词空格、还原维基转换标记（`-LSB-`、`-{zh-cn:…}-`），原文留在 `unit_sources`。丢了 822 条（证据页或邻近页不在维基库里） |

这三份对 RoleCraft 都是**域外**数据（合同、维基百科），用来检验关系识别器能不能迁移到真实文本，不混进产品训练集。

### 1.2 public-materials-v1（真实 PM 材料）

| 文件 | 条数 | 内容 |
|---|---|---|
| `units.jsonl` | 13,319 | 证据单元，每条带定位、固定版本和许可。site-policy 2,031（含 84 句被后来的提交改写过的旧句）、KEP 7,360、Jira 3,689（含 1,596 个按变更日志回放出来的旧修复版本状态）、TheAgentCompany 140、tau-bench 政策 99 |
| `criterion-kep.jsonl` | 5,948 | 686 份 KEP 的 Release Signoff Checklist 每一项，带作者自己的勾选状态（勾 2,876 / 未勾 3,072） |
| `tasks-tac.jsonl` | 28 | TheAgentCompany 全部 `pm-*` 任务的说明和评分点 |
| `trajectory-jira.jsonl` | 400 | Jira issue 的字段变更序列（状态、修复版本、优先级、指派、链接），带最终状态和解决用时 |
| `trajectory-taubench.jsonl` | 1,980 | tau-bench 历史 Agent 运行（gpt-4o、claude-3.5-sonnet，航空 / 零售），带环境奖励（成功 1,183 / 失败 797） |

「旧版本」是真的：比如 Marketplace 开发者协议在 2024-06-13 把终止通知期从 45 天改成 30 天；ZOOKEEPER-3376 的修复版本从 3.7.0 推到 3.8.0。由结构化字段渲染成句子的（KEP 的 `kep.yaml`、Jira 字段）在 `transformations` 里注明。

### 1.3 public-synth-v1（基于真实数据的合成）

协议和 relation-v3 一致（生成矩阵、文风、盲判提示词直接复用 [`synth_relation.py`](../../scripts/recognition/synth_relation.py)），只是把 pm_pilot 材料换成了上面的真实单元：

1. **选金标单元**：含数字、义务、审批、版本的句子，按文档轮流取，KEP 130（其中目标 / 非目标 30）、Jira 130（其中修复版本历史 40）、site-policy 118（其中 8 句真实改写，改动涉及数字或情态词）、tau-bench 40、TheAgentCompany 20。
2. **难负例**：同一文档里 TF-IDF 最像的 5 个单元做池，写到断言自身数字的跳过。
3. **中文**：金标、旧版本和负例由 DeepSeek 翻译（温度 0），数字和原文不完全一致的译文丢弃（2,117 留 2,104）。
4. **生成与复核**：每个合法格子写一句，四种文风轮换；盲判只看（断言，金标单元），与规格一致才保留。英文 2,064 留 1,939，中文 1,978 留 1,900，丢弃的 203 条在 `rejected.jsonl`。
5. **划分**：按（语言，来源文档）60/20/20，train 2,230 / dev 803 / test 806。

生成后发现 32 条记录的候选里有同一单元出现两次（tau-bench 零售政策本身有重复句），已去重并在 manifest 的 `post_fix` 里记下；脚本也已改成组装时跳过重复单元。

标签分布：英文 SUPPORTED 917 / CONTRADICTED 640 / INSUFFICIENT 382，中文 879 / 662 / 359。旧版本断言 73 条（英 43、中 30）。DeepSeek 用量 1,151 次调用，约 66.5 万输入 + 31.8 万输出 token。生成和复核同厂家，这一条和 relation-v3 一样要在报告里写明。

## 2. 来源登记

原始文件在 `data/raw/public/<来源>/`（ContractNLI 沿用 10-02 下载的 `data/raw/contractnli/`），每个来源一份 `source.json`，记 URL、固定版本、取数日期、许可和许可文件的 SHA-256。`data/raw/` 和 `data/releases/` 都在 `.gitignore` 里，不进仓库。

| 来源 | 取了什么 | 固定版本 | 许可 | 进了哪里 |
|---|---|---|---|---|
| ContractNLI | 官方 zip 全量 | 10-02 下载，zip 哈希见 `source.json` | CC BY 4.0 | real |
| VitaminC（`tals/vitaminc`） | train / dev / test | HF `be6febb761b0` | CC BY-SA 3.0（衍生数据须沿用） | real |
| CFEVER（`IKMLab-team/cfever`） | train / dev / test + 24 个维基页文件 | HF `1f8fa4bd2908` | Apache-2.0 | real |
| github/site-policy | 全历史克隆，20 份职场相关政策 | `b9578b546d25`（2026-05-29） | CC0-1.0 | materials、synth |
| kubernetes/enhancements | 686 份 KEP | `5b503a75369b`（2026-10-17） | Apache-2.0 | materials、synth |
| TheAgentCompany | 28 个 `pm-*` 任务 | `98b68ef82a47` | MIT | materials、synth |
| Public Jira Dataset（Zenodo 15719919） | 5.8 GB 转储的前 100 MB 里，修复版本或截止日期被改过至少两次的前 400 个 issue（Apache 150、Red Hat 150、Atlassian 98、Mojang 2） | 2025-06-23 版，md5 `02f85309…` | CC BY 4.0 | materials、synth |
| tau-bench | 政策文档 + 4 份历史轨迹 | `59a200c6d575` | MIT | materials、synth |

Public Jira Dataset 是 zip 里套一个 gzip 压缩的 mongodump，Zenodo 只有约 0.7 MB/s，整包要两个多小时，所以 `jira_stream.py` 用 HTTP 分段边下边解压边解析，够数就停。选取规则写在 `source.json` 里，同样的规则重跑得到同样的 400 条。

## 3. 和 10-06 计划的对照

| 计划里的来源 | 这次 | 说明 |
|---|---|---|
| GitHub site-policy | 做了 | 计划要「再取 3 到 5 个有改版历史的政策」，实际取了 20 份 |
| KEP Release Signoff Checklist | 做了 | 计划 5 到 10 份清单，实际全部 686 份 |
| TheAgentCompany 任务定义 | 做了 | 28 个 PM 任务全取 |
| TheAgentCompany experiments（运行轨迹） | 没取 | 仓库未声明许可，计划本来就只作本地格式参考 |
| Public Jira Dataset | 做了 | 替代直接抓 Apache Jira；计划 10 到 20 条，实际 400 条 |
| tau-bench historical_trajectories | 做了 | 1,980 条，非 PM 场景，单列 |
| ContractNLI | 全量 | 10-02 只导了 5 份合同 85 条试点 |
| VitaminC、CFEVER | 做了 | 10-06 调研表里的「标签相同、可直接用」两份 |
| CHEF | 没取 | 仓库没写许可 |
| OCNLI | 没取 | CC BY-NC，而且是句对推理，不是断言—证据 |
| AMI 会议语料 | 没取 | 调研时提过，计划正式表没列；音频和转写体量大，收益不明 |

10-06 手写的 `data/external-samples/` 草稿原样没动。计划 4.4 节说要移进 `_superseded/`，这次没移，等组内确认没人还在引用再说。计划里的两遍标注（`gpt6-astra`）已经被 10-16 的协议取代（DeepSeek 生成 + 盲判），合成部分照新协议做。

## 4. 怎么重跑

在仓库根目录：

```bash
.venv/Scripts/python.exe -m scripts.public.fetch                       # 下载，约 1.4 GB
uv run --no-project --with pymongo python -m scripts.public.jira_stream --limit 400 --per-collection 150
uv run --no-project --with scikit-learn --with opencc-python-reimplemented python -m scripts.public.build_real
uv run --no-project --with pyyaml python -m scripts.public.build_materials
.venv/Scripts/python.exe -m scripts.public.synth_grounded --out data/releases/public-synth-v1
```

前四步是确定的：版本固定，同一份原始数据重跑出来的文件哈希不变（已核对）。第五步调 DeepSeek（密钥读 `ds.txt`），每次结果不同；`--smoke 8` 只跑 8 个单元、不写文件。`uv run --with` 用的是临时环境，不动项目的依赖。

## 5. 已知限制

- ContractNLI 的片段是条款，常常很长，也不是最小充分集合。
- VitaminC、CFEVER 是 FEVER 式标注，证据不完整：标成 UNRELATED 的负例句可能和断言部分相关。
- CFEVER 的话题以台湾维基百科为主；NOT ENOUGH INFO 的候选句取自相邻断言引用的页面，test 里这一类少了约三分之一；官方 train 和 dev 共用 40 个证据页（test 的 444 页里），按官方划分原样保留。
- VitaminC 记录带 BIG-bench canary 字符串，不能进任何预训练语料。
- KEP 清单「没打勾」常常只是作者没更新，不一定是没达标。
- Jira 子集是按「计划顺延」特征挑的，刻意偏向延期的 issue；个人字段已被数据集作者匿名化。
- 合成部分的生成、翻译和复核都是 DeepSeek，同源偏差和 relation-v3 一样。

## 6. 格式冒烟

用产品里的 C1 加载器（`runs/local/recognizers/c1-xlmr-cpu`）对每份 test 各抽一小批跑了一遍，三份真实数据和合成数据都原样读入。抽样太小，下面的数字只说明「能跑」，不是实验结论：

| 文件 | 抽样 | 准确率 | macro-F1 | 预测分布 |
|---|---|---|---|---|
| relation-contractnli | 60（三类各 20） | 0.350 | 0.237 | 47 条判成 INSUFFICIENT |
| relation-vitaminc | 60 | 0.367 | 0.286 | 41 条判成 INSUFFICIENT |
| relation-cfever | 60 | 0.367 | 0.296 | 44 条判成 INSUFFICIENT |
| public-synth（中英混合） | 90（三类各 30） | 0.700 | 0.683 | SUPPORTED 29 / CONTRADICTED 18 / INSUFFICIENT 43 |

信号是：只在 pm_pilot 合成数据上训练的 C1，碰到「DeepSeek 写的断言 + 真实证据」还能保持 0.7 左右（和它在 relation-v3 test 上差不多），碰到人写的真实断言就大多退回「证据不足」。也就是说短板更可能在断言的写法和标注口径，而不只是证据文本是不是真实的。样本太小，要写进报告得在完整 test 上正式跑一次迁移实验（C1、LR、堆叠各一行，按来源分开报）。
