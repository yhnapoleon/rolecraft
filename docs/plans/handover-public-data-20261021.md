# 交接：公开数据、E11–E13、数据清单

日期：2026-10-21（同日两轮：上午公开数据 + E11，下午 E12 混训 + E13 各识别器正式实验）　详细登记：[公开数据 v1](../data/public-sources-v1.md)（来源、条数、读法、限制、重跑命令、E11–E13 的完整表格都在那里，这里只记状态、入口和坑）　打包清单：[DATA_INVENTORY](../data/DATA_INVENTORY.md)

## 0. 先看这里

- 两轮都只加数据、实验脚本、结果和文档，没碰产品代码和契约。
- 全部改动在 **PR #66**（分支 `claude/rc9-public-data`），等用户手动合。下午这一轮是加在 #66 上的新提交，没开新 PR。
- **合并顺序：#65 → #63 → #66**（#64 和这条线无关，随时可合）。#66 的 CI 现在是红的，两个原因：
  - 7 条是 main 上本来就有的 import 排序问题，#65 修；
  - 1 条是 `experiments/recognition/relation/transfer_public.py` 引用了 `career_lab.recognition.stack`，这个模块只在 #63 里。main 上找不到它，ruff 就把它当成三方包，排序结论跟着变。

  #63 合进去之后重跑 #66 的 CI 即可，`transfer_public.py` 不用改。下午新加的 `mix_public.py`、`public_eval.py` 按 CI 的 stdin 口径过了 ruff format 和 ruff check。
- 本机工作区停在 `local/deliverables-20261019`（#63–#65 的本地合并，没推）。#66 的文件在工作区里都是**未跟踪的副本**，和 PR 分支逐字节相同：`scripts/public/`、`docs/data/public-sources-v1.md`、`docs/data/DATA_INVENTORY.md`、`docs/plans/handover-public-data-20261021.md`、`docs/superpowers/`、`experiments/recognition/relation/{transfer_public,mix_public}.py`、`experiments/recognition/public_eval.py`、`experiments/recognition/results/e1{1,2,3}_*.json`。合并后切到 main 拉取之前，先删掉这些副本，否则 git 会拒绝覆盖未跟踪文件。
- 数据和权重都不在仓库里，位置、大小和该不该打包见 [DATA_INVENTORY](../data/DATA_INVENTORY.md) 第 1 节。用户 10-21 定：清单写好，打包他自己来，Canvas 装不装得下不管。

## 1. 做了什么

### 1.1 上午：公开数据（10 个发布目录）

| 目录 | 给谁用 | 真实 / 合成 | 规模 | 脚本 |
|---|---|---|---|---|
| `public-real-v1` | C1 关系 | 真实：ContractNLI、VitaminC、CFEVER | 50,515 条 | `build_real.py` |
| `public-materials-v1` | 合成的底料，也含 KEP 签核清单、轨迹 | 真实：site-policy、KEP、Jira、TheAgentCompany、tau-bench | 13,319 个证据单元 | `build_materials.py`（Jira 先跑 `jira_stream.py`） |
| `public-synth-v1` | C1 关系 | 合成，证据是真实单元 | 3,839 条断言 | `synth_grounded.py` |
| `public-reply-v1` | C10 回复核查 | 真实：RAGTruth | 17,790 条回答、131,160 句 | `build_tasks.py reply` |
| `public-reply-synth-v1` | C10（中文、泄露类） | 合成 | 603 条回复、2,724 句 | `synth_tasks.py reply` |
| `public-scope-v1` | C4 范围 | 真实：CLINC150、MASSIVE 中英 | 23,700 + 33,042 条 | `build_tasks.py scope` |
| `public-retrieval-v1` | C2 检索 | 真实：PrivacyQA | 1,750 个问题、35 份政策 | `build_tasks.py retrieval` |
| `public-queries-synth-v1` | C2 / C4 | 合成，知识库是真实材料 | 2,658 个问题 | `synth_tasks.py queries` |
| `public-sequence-v1` | C5 行为 | 真实：tau-bench、Jira | 1,980 + 400 条序列 | `build_tasks.py sequence` |
| `public-intent-synth-v1` | C11 意图 | 合成（没有标签对得上的真实数据） | 1,354 句 | `synth_tasks.py intent` |

### 1.2 下午：用户要的四件事

1. **混训（E12）**：词法 LR 和堆叠加入三份真实数据重拟合，C1 不重训。登记文档第 8 节。
2. **各识别器正式实验（E13）**：C10、C4、C2、C5、C11 全做了。登记文档第 9 节。
3. **小收尾**：
   - `data/external-samples/` 按 10-06 数据计划 4.4 节归档：两份合成会话、场景链、三份外部样例进 `_superseded/`，`info-action` 进 `_reference/`，各写了 README（被什么取代、合成会话和引擎不一致的六处）。这个目录本来就没入库，只是本地移动。
   - `docs/superpowers/`（10-06 扩建规范、执行计划、数据计划，10-16 模式识别重设计 v3.2）入库，提交前扫过没有密钥。
4. **打包清单**：`docs/data/DATA_INVENTORY.md`（英文，可以直接放进交付包）。

### 1.3 晚上：根因溯源 → 复核 → 换底座（E14、E15，登记文档第 10 节）

- E14a `diagnose_public.py`：问题在句对分类——C1 只认出 ContractNLI 6.5 % 的金标支持条款、VitaminC 7.6 % 的矛盾修订；截断、聚合规则都不是主因。
- E14b `review_errors.py`：DeepSeek 盲判 390 条，错误桶里同意金标的比例和随机对照相当，绝大多数是模型真错。
- E15 `nli_relation.py`：句对分类器换成 mDeBERTa-v3 多语言 NLI（`runs/local/weights/mdeberta-v3-base-xnli-2mil7/`），混合微调后（`runs/local/recognizers/c1-mdeberta-mix/`，未登记）relation-v3 0.658 → 0.903、ContractNLI 0.377 → 0.806、VitaminC 0.385 → 0.792、CFEVER 0.340 → 0.641、public-synth 0.687 → 0.825；C10 合成回复 0.705 → 0.928，RAGTruth AUROC 0.462 → 0.735（按块读）。**产品还没换**：新模型只在实验脚本里用。

## 2. 结论速记

产品链路（堆叠 + 规则）的 macro-F1，详细表格在登记文档里：

- **E11（迁移，不重训）**：域内 0.658；DeepSeek 写的断言配真实证据 0.687；人写的断言 ContractNLI / VitaminC / CFEVER 只有 0.377 / 0.385 / 0.340，差距集中在 CONTRADICTED。
- **E12（混训浅层）**：ContractNLI 涨到 0.50–0.56，VitaminC、CFEVER 在 ±3 个点以内，域内掉到 0.46–0.47；留一来源时，没见过的来源三份里两份更差。只看词法 LR 域内也掉，所以是混训本身的代价，不是融合权重的问题。真实数据上混训 LR 单独比堆叠好，说明 C1 拖后腿。**产品不换**，混训版存在 `runs/local/recognizers/relation-stack-mix-v1/`（未登记）。
- **E13 C10**：合成回复上三分类 0.705、「没有依据」F1 0.776、AUROC 0.824；RAGTruth 真实回答上基本失效（0.288 / 0.136 / 0.462）。泄露检测规则兜底更好（F1 0.924 对 0.781）。
- **E13 C4**：远域都容易，近域难；产品的单高斯马氏距离在 CLINC150 上 0.868，最近邻余弦 0.943、最大 softmax 0.956；最近邻余弦在公开数据上每一份都不比马氏距离差。
- **E13 C2**：PrivacyQA（真人提问 + 法律文本）稠密最好（MRR 0.562），RRF 0.536，BM25 0.412；合成问题全知识库 RRF 最好（0.872 / 0.883）。
- **E13 C5**：tau-bench 成败每类 HMM 最好（macro-F1 0.674，AUROC 0.681），产品的 DTW 1-NN 最弱（0.502）；Jira 关单前的序列预测结局，各方法接近随机——负面结果。
- **E13 C11**：产品模型迁到真实话题中文掉 8 个点、英文涨 2 个点；混训后合成 test 0.98、英文 intent-v1 0.82 → 0.86、中文 intent-v1 0.94 → 0.90。合成句子更直白（关键词规则都有 0.82–0.88），0.98 不能当真实水平。

报告「局限与讨论」可以用的主线：识别器学到的是生成数据的写法（E11、E13 的 C10）；只在浅层补真实数据解决不了（E12）；检索和范围检测换到真实数据还站得住，但方法选择会变（C2 稠密、C4 最近邻）。

## 3. 怎么跑

在仓库根目录执行。各脚本用的环境不同：

| 用途 | 环境 |
|---|---|
| `fetch.py`、`build_tasks.py`、`synth_grounded.py`、`synth_tasks.py` | `.venv/Scripts/python.exe -m scripts.public.<名>` |
| `jira_stream.py` | `uv run --no-project --with pymongo python -m ...` |
| `build_real.py` | `uv run --no-project --with scikit-learn --with opencc-python-reimplemented python -m ...` |
| `build_materials.py` | `uv run --no-project --with pyyaml python -m ...` |
| `transfer_public.py`、`mix_public.py`、`public_eval.py`，以及任何要用 C1 的冒烟 | `.venv-encoder/Scripts/python.exe`，设 `USE_TF=0 HF_HUB_OFFLINE=1 HF_HUB_DISABLE_SYMLINKS=1 PYTHONUTF8=1` |

```bash
python -m experiments.recognition.relation.transfer_public --encoder runs/local/recognizers/c1-xlmr-cpu   # E11
python -m experiments.recognition.relation.mix_public --encoder runs/local/recognizers/c1-xlmr-cpu --save  # E12，约 2 小时
python -m experiments.recognition.public_eval intent|sequence|retrieval|scope|reply|all [--limit 300]   # E13
```

- E13 各子命令在本机的用时：intent 1 分钟、sequence 约 15 分钟（纯 Python 的 DTW）、retrieval 约 20 分钟、scope 约 15 分钟、reply 约 1 小时（C1 推理，`--limit` 是 RAGTruth 抽多少条回复）。
- `public_eval.py` 自己会把 `CAREER_LAB_RECOGNIZERS` 和 `CAREER_LAB_RELATION_ENCODER` 默认指到 `runs/local/recognizers/`；`reply` 没加载到 C1 会直接退出，不会静默走规则。
- C1 的句对概率缓存在 `runs/local/cache/c1-pairs/`：E11 的五份 test、E12 的 ContractNLI / VitaminC / CFEVER dev 都已缓存，E12 重跑只花 LR 拟合的时间（每组 15–20 分钟）。
- 合成脚本读 `ds.txt` 里的 DeepSeek 密钥；都有 `--smoke N`。下载和 `build_*` 是确定的（重跑哈希不变），合成部分每次结果不同。

## 4. 没做的（按需再做）

- **把 E15 的 NLI 模型接进产品**（已经做完的是实验，产品仍用 `c1-xlmr-cpu` + 堆叠）：`encoder_relation.py` 要支持 `AutoModelForSequenceClassification` 这种结构（前提 = 证据 + 有效期，假设 = 断言，标签顺序 蕴含 / 中立 / 矛盾），按 registry 登记；新模型单独已经比堆叠好，融合规则在混合微调后反而略降（0.903 → 0.882），接入时可以不再用堆叠和规则，或重新选 α。C10 的 `check_reply` 改按块读（前 3 个单元拼成一段）。改动要挂在 `CAREER_LAB_RECOGNIZERS` 开关下，CI 才不受影响。
- **C10 在真实回答上继续提高**：用 RAGTruth train（约 10 万句，按块组织）微调，本机 CPU 抽 1–2 万句约 2–3 小时。
- E15 没有做留一来源，也只训了 1 轮。
- **识别实验室页**没有加 E11–E13 的图（`experiments/recognition/publish_lab.py`）。
- `docs/reports/expansion-progress.md`（10-06 扩建工作的进度记录）也一直没入库，这次没动，要不要一起入库由用户定。
- C10 的泄露漏判没有拆开记是哪一边的判断出了错（见登记文档 9.1）。

## 5. 坑

- **Windows 路径太长**：在 scratchpad 里开 worktree 会检出失败（`scenarios/` 下的长路径）。建提交改用底层命令：临时 `GIT_INDEX_FILE` + `read-tree` + `hash-object -w` + `update-index` + `commit-tree`，不动工作区和暂存区。要一棵干净树复现 CI，就用稀疏检出，只检出 `pyproject.toml`、`experiments/`、`src/career_lab/`、`scripts/`。
- **Git Bash 改写路径**：`sparse-checkout set /pattern` 里以 `/` 开头的模式会被改成 `D:/Git/...`，要设 `MSYS_NO_PATHCONV=1`。
- **本机 lint 绿不代表 CI 绿**：ruff 判断包归属时会看子模块在不在。本机工作区合着没推的 PR，CI 只有 main。复现方法是在稀疏检出的 PR 分支里用 stdin 模式跑 ruff（CI 的 `scripts/regression/lint.py` 就是这么喂的）。
- **产品切句器遇到「数字后的句号」不断句**：`version 1.5.2. It was` 会并成一句。合成回复只有 73 % 和金标切法一致，E13 的 C10 因此改按金标句子判（第一次跑按产品切句对齐，跳过了 27 % 的回复，而且跳过的正好是带数字的，结果有偏；旧结果留在 `runs/local/logs/e13_reply.skip-misaligned.json`）。产品里这个行为没改。
- **混合 dev 上 α 会被选成 0**：规则在真实断言上很少介入，网格是平的，「平手取最小」就落到 0。E12 因此同时报了产品的 α = 0.4。以后在新数据上选 α 要先看网格。
- **Jira 序列要截在关单之前**：`public-sequence-v1/jira.jsonl` 的 `sequence` 里含 `resolution:*` 和关单状态，直接拿来预测结局等于把标签放进了输入。
- `python -I` 会忽略 `PYTHONIOENCODING`。要打印中文，脚本里先写 `sys.stdout.reconfigure(encoding="utf-8")`。
- heredoc 会吃反斜杠：带正则的代码一律用 Write / Edit 写。
- **Zenodo 约 0.7 MB/s**：Public Jira Dataset 不要整包下（5.8 GB），用 `jira_stream.py` 按 HTTP 分段边下边解析。
- **CFEVER 用 HF 版**：证据是字典格式；维基原文有分词空格和 `-LSB-`、`-{zh-cn:…}-` 这类标记，`build_real.py` 已经处理，剩 1 处嵌套标记没清。
- **MASSIVE** 直接从 tar 包里读中英两个文件，不要全解压（51 种语言，656 MB）。
- `ruff format` 会改正在后台运行的脚本的源文件。不影响已经加载的进程，但别在生成或实验跑着的时候改逻辑，否则结果和脚本对不上（这一轮 E12 就是停掉重跑的，旧日志在 `runs/local/logs/e12_mix_public.run1.log`）。
