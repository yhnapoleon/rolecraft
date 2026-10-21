# 交接：公开数据（真实 + 基于真实的合成）与 E11

日期：2026-10-21　详细登记：[公开数据 v1](../data/public-sources-v1.md)（来源、条数、读法、限制、重跑命令都在那里，这里只记状态、入口和坑）

## 0. 先看这里

- 这一轮只做了数据和一组迁移实验，没碰产品代码和契约。
- 全部改动在 **PR #66**（分支 `claude/rc9-public-data`），等用户手动合。
- **合并顺序：#65 → #63 → #66。** #66 的 CI 现在是红的，两个原因：
  - 7 条是 main 上本来就有的 import 排序问题，#65 修；
  - 1 条是 `experiments/recognition/relation/transfer_public.py` 引用了 `career_lab.recognition.stack`，这个模块只在 #63 里。main 上找不到它，ruff 就把它当成三方包，排序结论跟着变。

  #63 合进去之后重跑 #66 的 CI 即可，`transfer_public.py` 不用改。
- 本机工作区停在 `local/deliverables-20261019`（#63–#65 的本地合并，没推）。这一轮新增的文件在工作区里是**未跟踪的副本**，和 PR 分支逐字节相同：
  - `scripts/public/`
  - `docs/data/public-sources-v1.md`
  - `docs/plans/handover-public-data-20261021.md`
  - `experiments/recognition/relation/transfer_public.py`
  - `experiments/recognition/results/e11_transfer_public.json`

  合并后切到 main 拉取之前，先删掉这些副本，否则 git 会拒绝覆盖未跟踪文件。
- 数据不在仓库里：原始文件在 `data/raw/public/`（约 1.6 GB）和 `data/raw/contractnli/`，发布目录是 `data/releases/public-*`（约 300 MB），都在 `.gitignore` 里。随 ZIP 怎么交还没定。

## 1. 做了什么

两批，共 10 个发布目录。真实部分用原数据集自己的标签（G1）；合成部分由 DeepSeek 按计划生成，盲判一致才保留（G2v），并且都以真实材料为底。

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

字段都沿用现有数据集：关系类同 relation-v3，范围 / 检索同 `assistant-queries-v1`，意图同 `intent-v1`，序列同 `trajectories-v1`。

## 2. E11 的结论

`transfer_public.py`：只在 relation-v3 上拟合过的链路，不重训，在各份完整 test 上评。产品链路（堆叠 + 规则）的 macro-F1：

- 域内参照（relation-v3）：0.658，和产品登记数字一致。
- DeepSeek 写断言 + 真实证据（public-synth）：0.687。
- 人写断言：ContractNLI 0.377、VitaminC 0.385、CFEVER 0.340。

证据换成真实文本没问题；断言换成人写的，就掉到接近随机，差距集中在 CONTRADICTED。完整五行表和读法见登记文档第 6 节，原始结果在 `experiments/recognition/results/e11_transfer_public.json`。

## 3. 怎么跑

在仓库根目录执行。各脚本用的环境不同：

| 用途 | 环境 |
|---|---|
| `fetch.py`、`build_tasks.py`、`synth_grounded.py`、`synth_tasks.py` | `.venv/Scripts/python.exe -m scripts.public.<名>` |
| `jira_stream.py` | `uv run --no-project --with pymongo python -m ...` |
| `build_real.py` | `uv run --no-project --with scikit-learn --with opencc-python-reimplemented python -m ...` |
| `build_materials.py` | `uv run --no-project --with pyyaml python -m ...` |
| `transfer_public.py`，以及任何要用 C1 的冒烟 | `.venv-encoder/Scripts/python.exe`，设 `USE_TF=0 HF_HUB_OFFLINE=1 HF_HUB_DISABLE_SYMLINKS=1` |

- `uv run --with` 用的是临时环境，不动项目依赖。
- 合成脚本读 `ds.txt` 里的 DeepSeek 密钥；都有 `--smoke N`，只跑几个单元、不写文件。
- 下载和 `build_*` 是确定的：版本固定，重跑出来的文件哈希不变（已核对）。合成部分每次结果不同。
- 产品识别器的环境变量：
  - `CAREER_LAB_RECOGNIZERS=<仓库>/runs/local/recognizers`：意图、范围、行为、堆叠的权重。
  - `CAREER_LAB_RELATION_ENCODER=<仓库>/runs/local/recognizers/c1-xlmr-cpu`：C1。不设的话，`check_reply` 和 `relation.judge` 会静默走规则兜底（输出里 `fallback: true`）。
- E11 的 C1 句对概率缓存在 `runs/local/cache/c1-pairs/<revision>-public-<来源>-<条数>.npy`，重跑只要几分钟。第一次跑完整 test 在本机 CPU 上约一个半小时。

## 4. 没做的（按需再做）

- **混训**：三份真实数据都带 train 划分，可以和 relation-v3 一起拟合 LR / 堆叠（或重训 C1），再跑 E11，看域内掉多少、真实数据涨多少。
- **各识别器在新数据上的正式实验**：这一轮只做了格式冒烟，没出正式数字：
  - C10：RAGTruth 抽了几条、合成回复抽了 2 条；
  - C11：在 intent-v1 test 上中文 0.946 / 英文 0.824，在 `public-intent-synth-v1` test 上 0.867 / 0.852；
  - C4（CLINC150、MASSIVE）、C2（PrivacyQA）、C5（tau-bench、Jira）都还没跑。
- 10-06 的 `data/external-samples/` 草稿没移进 `_superseded/`。
- `docs/superpowers/`（含 10-06 的数据计划）仍未入库。登记文档引用它时注明了「本地，未入库」。

## 5. 坑

- **Windows 路径太长**：在 scratchpad 里开 worktree 会检出失败（`scenarios/` 下的长路径）。建提交改用底层命令：临时 `GIT_INDEX_FILE` + `read-tree` + `hash-object -w` + `update-index` + `commit-tree`，不动工作区和暂存区。要一棵干净树复现 CI，就用稀疏检出，只检出 `pyproject.toml`、`experiments/`、`src/career_lab/`、`scripts/`。
- **Git Bash 改写路径**：`sparse-checkout set /pattern` 里以 `/` 开头的模式会被改成 `D:/Git/...`，要设 `MSYS_NO_PATHCONV=1`。
- **本机 lint 绿不代表 CI 绿**：ruff 判断包归属时会看子模块在不在。本机工作区合着没推的 PR，CI 只有 main。复现方法是在稀疏检出的 PR 分支里用 stdin 模式跑 ruff（CI 的 `scripts/regression/lint.py` 就是这么喂的）。
- `python -I` 会忽略 `PYTHONIOENCODING`。要打印中文，脚本里先写 `sys.stdout.reconfigure(encoding="utf-8")`。
- heredoc 会吃反斜杠：带正则的代码一律用 Write / Edit 写。这一轮在 `build_real.py` 里踩过一次，写进了空字节。
- **Zenodo 约 0.7 MB/s**：Public Jira Dataset 不要整包下（5.8 GB），用 `jira_stream.py` 按 HTTP 分段边下边解析，够数就停（只读前 100 MB）。
- **CFEVER 用 HF 版**：证据是字典格式；维基原文是分词后带空格的，还有 `-LSB-`、`-{zh-cn:…}-` 这类标记。`build_real.py` 已经处理，剩 1 处嵌套标记没清。
- **MASSIVE** 直接从 tar 包里读中英两个文件，不要全解压（51 种语言，656 MB）。
- `ruff format` 会改正在后台运行的生成脚本的源文件。这不影响已经加载的进程，但别在生成过程中改提示词，否则数据和脚本对不上。
