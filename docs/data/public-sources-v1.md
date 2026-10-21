# 公开数据 v1：真实数据与基于真实数据的合成数据

日期：2026-10-20　对应：10-06《数据收集与标注计划》第 3.3 节「公开辅助来源」和 WP-D1、WP-D8（[`docs/superpowers/plans/2026-10-06-rolecraft-data-plan.md`](../superpowers/plans/2026-10-06-rolecraft-data-plan.md)，10-21 入库）；10-06 的开源来源调研；合成协议同 [识别层设计](../plans/pattern-recognition-design-20261016.md) 第 7 节的 `relation-v3`

## 0. 一句话

10-06 定的公开来源这次正式取齐了，分三个发布目录：**真实文本加真实标签**（`public-real-v1`）、**真实 PM 材料**（`public-materials-v1`，未经模型改写）、**以真实材料为证据、由 DeepSeek 写断言的合成数据**（`public-synth-v1`）。关系类记录和 relation-v3 同形，C1 和堆叠的评测代码不用改就能读。

同日第二批（第 7 节）：给原来只有合成数据的识别器（C10 回复核查、C4 范围、C2 检索、C5 行为、C11 意图）各补一份数据，真实优先，找不到标签对得上的真实数据就以真实材料为底合成。第 6 节是用这些数据跑的关系链路迁移实验（E11），第 8 节是拿三份真实数据混训的 E12，第 9 节是各识别器在第二批数据上的正式实验（E13）。

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

10-06 手写的 `data/external-samples/` 草稿已于 10-21 按计划 4.4 节归档（本地目录，不入库）：两份合成会话、场景链和三份外部样例移进 `_superseded/`，因为它们已经被引擎导出数据和本文的公开数据取代；`info-action` 样例按计划移进 `_reference/`，只作格式参考。两个目录各有一份 README，写明每个文件被什么取代，以及合成会话和引擎不一致的六处。仓库里没有代码引用这些文件。计划里的两遍标注（`gpt6-astra`）已经被 10-16 的协议取代（DeepSeek 生成 + 盲判），合成部分照新协议做。

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

## 6. E11：关系链路迁移到真实文本

`experiments/recognition/relation/transfer_public.py`，结果在 `experiments/recognition/results/e11_transfer_public.json`。所有模型都只在 relation-v3（pm_pilot 材料 + DeepSeek 断言）上拟合过，这里不重训，直接在各份数据的**完整 test** 上评。claim 级 macro-F1：

| test 集 | 条数 | 词法 LR | C1 | C1 + 规则 | 堆叠 | 堆叠 + 规则（产品） |
|---|---|---|---|---|---|---|
| relation-v3（域内参照） | 1,324 | 0.600 | 0.625 | 0.630 | **0.663** | 0.658 |
| public-synth（DeepSeek 断言 + 真实证据） | 806 | 0.621 | 0.655 | 0.661 | **0.695** | 0.687 |
| ContractNLI（人写断言，en） | 2,091 | 0.339 | 0.311 | 0.311 | **0.377** | 0.377 |
| VitaminC（人写断言，en） | 4,000 | 0.371 | 0.316 | 0.359 | 0.383 | **0.385** |
| CFEVER（人写断言，zh） | 2,629 | 0.272 | 0.343 | **0.375** | 0.322 | 0.340 |

域内那一行和产品登记的数字一致（堆叠 + 规则：中文 0.698、英文 0.635），说明评测链路没走样。

读法：

- **证据换成真实文本，问题不大。** public-synth 的证据全是真实句子，断言仍是 DeepSeek 按同一套矩阵写的，堆叠 0.695，和域内持平。
- **断言换成人写的，就掉到接近随机**（三分类随机约 0.33）。差距集中在 CONTRADICTED：产品链路在 ContractNLI / VitaminC / CFEVER 上这一类的 F1 只有 0.16 / 0.09 / 0.11，模型大多退回 INSUFFICIENT 或 SUPPORTED。人写的矛盾（换个限定、换个时间、改一处事实）和生成矩阵里的矛盾（否定、数字超限、旧值）不是一回事。
- 规则只在有数字和限额可比时介入（ContractNLI 0%、VitaminC 55%、CFEVER 17%），所以 ContractNLI 上「加规则」没有变化。
- 这是报告「局限与讨论」该写的一条：识别器学到的是生成数据的断言写法。三份真实数据都带 train 划分，第 8 节（E12）拿它们和 relation-v3 混训，看域内掉多少、真实数据涨多少。

## 7. 第二批：给只有合成数据的识别器补数据（10-20 晚）

原则：真实优先；标签对不上、或者缺中文的部分，以第 1 节的真实材料为底合成，协议同上（生成计划 + 盲判一致才保留，G2v）。

### 7.1 按识别器

| 识别器 | 真实数据 | 合成数据（以真实材料为底） | 产品能否直接读 |
|---|---|---|---|
| C10 同事回复核查 | `public-reply-v1`：RAGTruth，17,790 条真实大模型回答（6 个模型）、2,965 份源文档，131,160 句。句子按人工逐词标注分成 grounded / conflict / baseless，test 里是 17,375 / 587 / 968 | `public-reply-synth-v1`：603 条中英同事回复、2,724 句（grounded 1,504 / conflict 462 / baseless 455 / leak 303），一半回复带「泄露内部备注」 | `check_reply(reply, visible, private)` 能直接跑，句子和金标逐句对齐（需设 `CAREER_LAB_RELATION_ENCODER`，否则走规则兜底） |
| C4 范围检测 | `public-scope-v1`：CLINC150（英，150 个意图 22,500 条 + 范围外 1,200 条，范围外检测的标准基准）；MASSIVE 1.1 中英平行各 16,521 条，办公类场景算范围内、闲聊和常识问答算远域、其余助手任务算近域 | 和 C2 共用 `public-queries-synth-v1` | 字段同 `assistant-queries-v1` |
| C2 检索 | `public-retrieval-v1`：PrivacyQA，35 份隐私政策、1,750 个真人问题，专家标了相关句和能不能答 | `public-queries-synth-v1`：2,658 个中英知识库问题（in_direct 898 / in_paraphrase 885 / out_near 574 / out_far 301），知识库是 155 个真实材料片段 | 字段同 `assistant-queries-v1` |
| C5 行为轨迹 | `public-sequence-v1`：tau-bench 1,980 条 Agent 运行（按环境奖励分成功 / 失败）、Jira 400 条变更序列（按最终处理结果） | 不需要（已有 `trajectories-v1`） | `sequence` 字段同 `trajectories-v1`，但符号表是各来源自己的 |
| C11 意图 | 没有：五个类别是我们自己定的，没有标签对得上的公开数据 | `public-intent-synth-v1`：1,354 句中英提问，五类、四种文风同 intent-v1，但话题换成真实材料 | 字段同 `intent-v1` |

格式冒烟（只说明能跑，不是实验结论）：产品的 C11 在 intent-v1 test 上中文 0.946 / 英文 0.824，在 `public-intent-synth-v1` test 上 0.867 / 0.852（这里是准确率；正式结果见第 9 节）。

### 7.2 新增来源登记

| 来源 | 固定版本 | 许可 | 进了哪里 |
|---|---|---|---|
| RAGTruth | `c103204b9ce2` | MIT | public-reply-v1 |
| CLINC150（`clinc/oos-eval`） | `828f8093932c` | CC BY 3.0 | public-scope-v1 |
| MASSIVE 1.1（S3 tar 包 + HF 卡 `ff6bd8e4b27c`） | 1.1 | CC BY 4.0 | public-scope-v1 |
| PrivacyQA（`PrivacyQA_EMNLP`） | `5178ff3eaf61` | MIT | public-retrieval-v1 |

tau-bench、Jira、site-policy、KEP、TheAgentCompany 沿用第 2 节已下载的版本。

### 7.3 怎么重跑

```bash
.venv/Scripts/python.exe -m scripts.public.fetch ragtruth clinc150 massive privacyqa
.venv/Scripts/python.exe -m scripts.public.build_tasks                    # 真实部分，确定可复现
.venv/Scripts/python.exe -m scripts.public.synth_tasks reply queries intent  # 合成部分，调 DeepSeek
```

`build_tasks` 依赖 `public-materials-v1`（tau-bench、Jira 轨迹），`synth_tasks` 依赖 `public-synth-v1/units.jsonl`（中英对照的真实单元）。这一批合成用了 2,192 次 DeepSeek 调用，约 89.7 万输入 + 21.3 万输出 token。

### 7.4 已知限制

- RAGTruth 只有英文，而且没有「泄露」这一类；中文和泄露只能靠合成补。RAGTruth 的回答是通用问答、新闻摘要、餐厅介绍，不是同事口吻。
- MASSIVE 的范围内 / 近域 / 远域是我们按场景划的（写在 manifest 里），`domain` 保留了原场景，可以重划。CLINC150 的范围外问题没有区分近域和远域。
- PrivacyQA 的 test 用「六位标注员任一人认为相关」，所以 test 里能答的比例（366 / 400）比 train 高；同时给了多数票版本 `relevant_majority_unit_ids`。
- 合成的知识库问题只复核了「能不能答」，近域和远域按生成计划，没有复核。
- 合成的回复里，计划写得很明确，盲判一致率很高（616 条丢 13 条），这说明标签和计划一致，不说明句子难。
- tau-bench 和 Jira 的符号表和产品的 C5 不同，只能检验 DTW / HMM / n-gram 这些方法，不能直接套产品的参考库。

## 8. E12：用三份真实数据混训关系链路（10-21）

`experiments/recognition/relation/mix_public.py`，结果在 `experiments/recognition/results/e12_mix_public.json`。按 `fit_stack.py` 的配方重拟合词法 LR（train 句对）和堆叠的元学习器（dev 句对），只是把 ContractNLI、VitaminC、CFEVER 的 train / dev 加进去；**C1 不重训**（本机 CPU 训一遍要几个小时），仍用 relation-v3 上训的那个。CFEVER 的 dev 抽 1,000 条断言，其余全量。四组：

- **v3 单独**：只用 relation-v3，就是产品的堆叠，数字和 E11 逐位一致；
- **全混**：relation-v3 + 三份真实数据，共 127,913 个 train 句对、4,833 条 dev 断言；
- **加权混**：同上，词法 LR 里每份真实数据的总权重压到和 relation-v3 一样；
- **留一来源**：拿掉其中一份（train 和 dev 都拿掉），只看它的 test，相当于一个没见过的真实来源。

混合 dev 上规则融合权重的网格几乎是平的（规则在真实断言上很少能介入），按「平手取最小」选出 α = 0，所以每组都同时按产品的 α = 0.4 报了一遍；两种读法最多差 0.04，下表用 α = 0.4。

产品链路（堆叠 + 规则）的 claim 级 macro-F1：

| test 集 | v3 单独 | 全混 | 加权混 | 留一来源（这一份没参与） |
|---|---|---|---|---|
| relation-v3（域内） | **0.658** | 0.468 | 0.460 | – |
| ContractNLI | 0.377 | 0.499 | **0.558** | 0.350 |
| VitaminC | **0.385** | 0.367 | 0.375 | 0.338 |
| CFEVER | 0.340 | 0.364 | 0.359 | **0.418** |
| public-synth | **0.687** | 0.586 | 0.605 | – |

只看词法 LR（堆叠的底层学习器）：

| test 集 | v3 单独 | 全混 | 加权混 | 留一来源 |
|---|---|---|---|---|
| relation-v3 | **0.600** | 0.455 | 0.464 | – |
| ContractNLI | 0.339 | 0.643 | **0.669** | 0.274 |
| VitaminC | 0.371 | 0.421 | **0.436** | 0.325 |
| CFEVER | 0.272 | **0.422** | 0.396 | 0.416 |
| public-synth | **0.621** | 0.574 | 0.606 | – |

读法：

- **域内代价大，真实数据收益小而且不均匀。** 混训后 relation-v3 从 0.658 掉到 0.46–0.47（中 0.698 → 0.476，英 0.635 → 0.463）；真实数据只有 ContractNLI 明显涨（+12 到 +18 个点），VitaminC 和 CFEVER 在 ±3 个点以内。
- **掉分出在混训本身，不是融合权重。** α 取 0 还是 0.4 差不多；只看词法 LR，域内也从 0.600 掉到 0.455。真实句对是 relation-v3 的 13 倍，即使按来源加权，LR 学到的主要是真实数据的模式。
- **对没见过的真实来源基本没用。** 留一来源的三份里，ContractNLI（0.350）和 VitaminC（0.338）比只用 relation-v3 还低，只有 CFEVER 涨到 0.418。所以 ContractNLI 那十几个点的提升来自它自己的 train，不是「学会了人写的断言」。
- **C1 拖了后腿。** 在真实数据上，混训后的词法 LR 单独反而比堆叠好（ContractNLI 0.643 对 0.499，CFEVER 0.422 对 0.364）：C1 只见过 relation-v3，在真实断言上给的概率没有用，而元学习器在混合 dev 上只能学一套权重，不能按来源区分。要在真实数据上真正提高，下一步是用混合数据重训 C1，而不是只换堆叠。
- 产品不换：仍用 `relation-stack-v1`。混训版按产品格式存在 `runs/local/recognizers/relation-stack-mix-v1/`（5.4 MB，未登记），需要时可以对照。

报告里可以这样用：E11 说明识别器学到的是生成数据的写法；E12 说明只在浅层（词法 LR、元学习器）补真实数据解决不了，代价是域内掉 20 个点，提升也不能迁移到没见过的来源。

## 9. E13：各识别器在公开数据上的正式实验（10-21）

`experiments/recognition/public_eval.py`，一个识别器一个子命令（`reply` / `scope` / `retrieval` / `sequence` / `intent`），结果在 `experiments/recognition/results/e13_<子命令>.json`。产品的识别器要么原样跑（C10、C2、C11 的迁移），要么在公开数据自己的 train 上按同一方法重拟合（C4、C5、C11 的域内），并和 E5 / E6 / E7 的基线放在一起比。

### 9.1 C10 同事回复核查

和 `check_reply` 同样的调用：每句先用 C2 在可见材料里取前 3 个单元，再由 C1 + 堆叠 + 规则判；有私密材料时同样判一遍，私密材料支持、可见材料不支持就算泄露。句子用数据里的金标切分（产品的切句器遇到「数字后的句号」不断句，合成回复里只有 73 % 的回复切法一致；RAGTruth 是用产品切句器切的，100 % 一致）。基线是不加载 C1 时的规则兜底。RAGTruth 按（任务类型，有没有问题）分层抽了 300 条 test 回复，有问题和没问题各半。

| 数据 | 链路 | 句子 | 三分类 macro-F1 | 「没有依据」P / R / F1 | AUROC | 回复级 F1 | 泄露 P / R / F1 |
|---|---|---|---|---|---|---|---|
| RAGTruth（英） | 产品 | 2,211（有问题 258） | 0.288 | 0.094 / 0.248 / 0.136 | 0.462 | 0.597 | – |
| RAGTruth（英） | 规则兜底 | 同上 | 0.120 | 0.126 / 0.973 / 0.223 | 0.540 | 0.667 | – |
| 合成回复（中英） | 产品 | 546（有问题 237） | **0.705** | 0.744 / 0.810 / **0.776** | **0.824** | 0.975 | 0.953 / 0.661 / 0.781 |
| 合成回复（中英） | 规则兜底 | 同上 | 0.269 | 0.505 / 0.932 / 0.655 | 0.616 | 0.996 | 0.965 / 0.887 / **0.924** |

AUROC 是拿 1 − P(supported) 给「没有依据」的句子排序。规则兜底把绝大多数句子判成「依据不足」（RAGTruth 90 %、合成 80 %），所以召回高、回复级 F1 好看，但没有区分度。

读法：

- **合成回复上产品链路是有效的**：三分类 0.705，中英相近（0.709 / 0.700）。矛盾句的召回只有 0.49，漏掉的 46 句里 24 句被判成「支持」、22 句「依据不足」。
- **真实大模型回答（RAGTruth）上基本失效**，和 E11 的结论一致：识别器学到的是生成数据的写法。产品链路挑出来的「没有依据」句子，精确率 0.094 比有问题句子的基础比例 0.117 还低，矛盾类几乎没抓到（F1 0.01），三类任务（问答、摘要、数据转文本）都一样。
- 原因能确认的只有一半：RAGTruth 里没问题的句子，和最像的那一句原文的词重合平均也只有 46 %（有问题的 35–38 %），一句回答常常要靠几句原文合起来才有依据，而 C1 是一句一句比的，所以大量没问题的句子被判「依据不足」。但有问题的句子重合更低，按重合度排序方向是对的（规则兜底 AUROC 0.540），C1 的概率却略微反了（0.462），这一点没有找到原因。
- **泄露检测规则兜底更好**（F1 0.924 对 0.781）：私密备注和泄露句的字面重合很高，规则直接判「支持」；C1 + 堆叠漏掉了三分之一的泄露句（召回 0.661），是私密那边没判成「支持」还是可见那边误判成「支持」，结果文件里没有分开记。
- 要在真实回答上用，需要的不是调阈值，而是让 C1 见过多句拼合的证据和人写 / 模型自然写出的错误，比如拿 RAGTruth 的 train（约 10 万句，其中有问题的约 1.1 万句）去训。这和第 8 节的混训是同一个方向。

### 9.2 C4 范围检测

方法和 E5 相同：e5-small 向量，用范围内训练问题拟合 Ledoit-Wolf 马氏距离，阈值取 dev 范围内的 95 % 分位。另加两个要用意图标签的基线：按意图分类的马氏距离（共享协方差）、逻辑回归的最大 softmax。test 上范围外的 AUROC：

| 数据 | 产品（单高斯马氏距离） | 分类马氏距离 | 最大 softmax | 最近邻余弦 | 其余基线最好的 |
|---|---|---|---|---|---|
| CLINC150（英，150 个意图） | 0.868 | 0.928 | **0.956** | 0.943 | 自编码器 0.801 |
| MASSIVE 中 | 0.961 | 0.963 | 0.906 | **0.965** | K-Means 0.955 |
| MASSIVE 英 | 0.940 | 0.944 | 0.905 | **0.951** | K-Means 0.947 |
| 合成知识库问题 中 | 0.770 | 0.769 | 0.667 | **0.870** | K-Means 0.728 |
| 合成知识库问题 英 | 0.832 | 0.833 | 0.664 | **0.900** | 高斯朴素贝叶斯 0.795 |

读法：

- **远域都容易，难在近域。** MASSIVE 的远域（闲聊、常识），距离类方法（两种马氏距离、最近邻余弦）都在 0.95 以上；合成问题的近域（同一份材料、没写答案），马氏距离只有中 0.677 / 英 0.769，最近邻余弦 0.814 / 0.858。
- **范围内是多个簇的时候，单个高斯不够。** CLINC150 有 150 个意图，产品方法 0.868，用上意图标签的两种方法到 0.93–0.96，和文献里的结论一致。产品自己的知识库（E5）上马氏距离和最近邻余弦打平（中 0.977 / 0.980，英 0.953 / 0.939），换到公开数据，最近邻余弦每一份都不比它差。
- 按 dev 阈值实际放行的范围外问题：CLINC150 上产品方法放过 55 %，最大 softmax 24 %；MASSIVE 中文 24 %，英文 33 %。这两份数据上范围内被误拒都在 4–6 %，和 95 % 的设定相符；合成问题的 dev 里范围内问题不到 200 条，阈值估得粗，产品方法误拒到中 9 % / 英 14 %。

### 9.3 C2 检索

产品的 `retrieval.search`，在问题所属文档的单元里排序，看第一个相关单元的名次。

| 数据 | 条数 | BM25 R@1 / R@5 / MRR | e5 稠密 | RRF（产品） |
|---|---|---|---|---|
| PrivacyQA test（任一标注员认为相关） | 366 | 0.251 / 0.593 / 0.412 | **0.393 / 0.770 / 0.562** | 0.380 / 0.738 / 0.536 |
| PrivacyQA test（多数票） | 272 | 0.132 / 0.338 / 0.248 | 0.235 / **0.540** / **0.378** | **0.246** / 0.474 / 0.359 |
| PrivacyQA train + dev（专家标注） | 925 | 0.136 / 0.386 / 0.258 | 0.203 / 0.462 / **0.333** | **0.205** / **0.468** / 0.332 |
| 合成问题，全知识库，中 | 918 | 0.752 / 0.898 / 0.817 | 0.780 / 0.930 / 0.846 | **0.805 / 0.956 / 0.872** |
| 合成问题，全知识库，英 | 865 | 0.797 / 0.947 / 0.860 | 0.760 / 0.939 / 0.839 | **0.816 / 0.969 / 0.883** |

- 真人提问加法律文本（PrivacyQA），稠密检索最好，RRF 被 BM25 拖低了一点；合成问题的措辞和材料更接近，RRF 最好。两种情况下 RRF 都不是最差，作为默认是稳的。
- 合成问题里，换了说法的问题比照抄原文的问题难：全知识库 RRF 的 MRR 中文 0.806 对 0.937，英文 0.833 对 0.932。只在问题自己的上下文（5–7 个单元）里找，三种方法 R@5 都在 0.97 以上。
- PrivacyQA 能不能答：拿检索第一名的稠密分数当分数，AUROC 0.787（BM25 分数 0.621）。只靠检索分数判断「政策里有没有答案」还不够，这也是产品要单独做 C4 的原因。

### 9.4 C5 行为序列

方法同 E6：DTW 1-NN（产品的替换代价）、编辑距离 1-NN、1–3 gram 随机森林，另加每类各拟合一个 HMM（比每步对数似然）、只看序列长度、全猜多数类。Jira 的序列截在第一个 `resolution:*` 或关单类状态之前，否则标签就在输入里（12 条截完是空的，丢掉）。

| 数据 | 任务 | DTW 1-NN | 编辑距离 1-NN | n-gram 随机森林 | 每类 HMM | 只看长度 | 多数类 |
|---|---|---|---|---|---|---|---|
| tau-bench（216 条 test） | 成功 / 失败，macro-F1 | 0.502 | 0.532 | 0.592 | **0.674** | 0.498 | 0.427 |
| 同上 | 失败的 AUROC | 0.593 | 0.596 | 0.640 | **0.681** | 0.526 | – |
| Jira（130 条 test） | 三类结局，macro-F1 | 0.262 | 0.292 | 0.207 | 0.294 | **0.380** | 0.100 |

- tau-bench 上有信号但不强：失败这一类的 F1 最高 0.49（HMM）。产品用的 DTW 1-NN 在这里是几种序列方法里最弱的，每类 HMM 最好。一个可能的解释（没有单独验证）：同一任务的成功和失败运行用的工具差不多，整条序列对齐后的距离拉不开，按每步转移概率打分的 HMM 更能抓到局部差别。
- Jira 上没有信号：关单之前的变更记录（修复版本改来改去、指派、链接）几乎不包含最后怎么处理的信息，各方法接近随机，只看长度反而最好。而且按项目划分，train 和 test 的结局比例差很多（未解决 train 113 / test 23）。这是负面结果，照实写。
- 和 E6 对照：E6 的轨迹是脚本策略生成的，策略之间差别大，DTW 1-NN、编辑距离、随机森林都是满分；真实轨迹的结局差别小得多。产品的 C5 用来认「学员用的是哪种策略」，这个任务本身比预测成败容易，E13 的数字不能直接拿来说产品 C5 不行，但能说明 DTW 参考库的做法对细粒度差别不敏感。

### 9.5 C11 意图

| 模型 | intent-v1 test 中 / 英（acc，macro-F1） | 合成 test 中 / 英（acc，macro-F1） |
|---|---|---|
| 产品（只在 intent-v1 上训） | 0.946, 0.942 / 0.824, 0.823 | 0.867, 0.861 / 0.852, 0.843 |
| 只在合成数据上重训（C=8） | 0.674, 0.673 / 0.681, 0.683 | 0.985, 0.985 / 0.972, 0.974 |
| intent-v1 + 合成混训（C=16） | 0.907, 0.900 / 0.857, 0.856 | 0.985, 0.985 / 0.979, 0.980 |
| 关键词规则 | 0.550, 0.543 / 0.496, 0.519 | 0.881, 0.878 / 0.838, 0.817 |

- 产品模型换到真实材料的话题上，中文 macro-F1 掉 8 个点（0.942 → 0.861），英文反而高 2 个点（0.823 → 0.843），后者和下面说的「合成句子更直白」一致。
- 混训后两份 test 都好：合成 test 到 0.98，英文 intent-v1 也从 0.82 升到 0.86；代价是中文 intent-v1 从 0.94 掉到 0.90。
- 关键词规则在合成数据上有 0.82–0.88，在 intent-v1 上只有 0.5 左右：合成句子写得比 pm_pilot 的问法直白，常带「上限」「审批」这类关键词，所以合成 test 比 intent-v1 test 容易，0.98 不能当作真实水平。
