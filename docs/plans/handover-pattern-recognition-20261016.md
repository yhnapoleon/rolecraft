# 交接：模式识别组件实施（2026-10-16 → 下一个会话）

写给接手实现的 Agent 或组员。目标：到 2026-10-31，把 RoleCraft 做成**理想条件下能端到端演示的模式识别系统**。稳定性、可验证性、安全性不在范围内；不跑回归门禁，不做契约重导出，不走封存 test 仪式。共同开发者，直接在 `main` 上开分支改。

## 1. 先读什么

按顺序，总共约 40 分钟：

1. [选型文档](pattern-recognition-selection-20261016.md) —— 补哪些识别器、各自怎么接、顺序、砍法。**这是唯一的执行依据。**
2. 本文第 3–6 节 —— 环境、现状、第一步、坑。
3. [v3 设计文档](../superpowers/specs/2026-10-16-rolecraft-pattern-recognition-redesign.md)的 **0A 节**（远端已有什么）、**3.3 节**（断言生成矩阵）、**12 节**（M1–M7 细节，对应选型里的 C4–C9）、**13 节**（课件方法对照，写报告时用）。其余节是旧前提，跳过。
4. 远端的 [docs/HANDOVER.md](../HANDOVER.md) 的"起服务""启动工作台""没有负责方产物时怎样演示模型建议"三节；[docs/data/return-v3/README.md](../data/return-v3/README.md)（模型回传格式，第 2、5、6 节）；[docs/data/expansion-v3-w07.md](../data/expansion-v3-w07.md) 的"研究授权与真实会话导出"（导出作品句的命令）。

## 2. 项目一句话

RoleCraft：AI 产品经理的工作模拟。学员读材料、问三位 LLM 同事、配置并测试一个知识助手、申请资源、提交方案，系统给带证据的反馈。远端 `main`（Jeffrey、Kairui，10-07 至 10-15 的 685 个提交）已建好 React 工作台、后端、Agent 接入、规则评价（14 项 rubric，带规则界）、逐句"模型建议"界面、模型槽与回传接收端。**缺的是模型本身和识别器**。我们补：

| 代号 | 识别器 | 接入点 |
|---|---|---|
| C1 | 关系判定（XLM-R，逐对支持/矛盾/无关，中英） | SUPPORT 槽，反馈页逐句建议（界面已有） |
| C2 | 证据句级切块 + top-k 检索 | `src/career_lab/evidence/v2/assembler.py` 候选构造处；`models/v3/consumer.py` 逐句推理前 |
| C3 | 经典基线与集成 | 只进报告；线性回传登记为融合分量 |
| C4 | 范围外问题检测（马氏距离） | `src/career_lab/assistant/service.py` 约第 100 行 `fallback = ...` |
| C5 | 行为轨迹识别（DTW + kNN、HMM、异常） | 新接口 `GET /sessions/{id}/behavior` + 新前端页 `apps/web/src/features/behavior-native/` |
| C6 | 代价敏感拒识 | `consumer.py` 聚合后 |
| C10 | 同事回复依据核查（复用 C1） | 角色回合落库后 |
| JUDGE | LLM 语义评审（非识别器，端到端必需） | 配置 JUDGE 槽为 DeepSeek |

课程四项要求的对应见选型文档第 3 节。

## 3. 环境与现状

- 本地目录 `D:\HuaweiMoveData\Users\13736\Desktop\AIS\5002GPJ`，分支 `main` = `origin/main` 319c2a9（10-16 已同步；旧本地提交在 `backup/local-main-20261016`）。每次开工先 `git fetch` 看远端有没有新 PR。
- Python 3.12，`uv sync --locked` 已做；编码器环境另建：`$env:UV_PROJECT_ENVIRONMENT='.venv-encoder'; uv sync --locked --extra encoder`（torch 2.8.0 CPU、transformers 4.57.1）。前端 `apps/web` 还没 `npm ci`（Node 22 可用）。
- 远端代码基线：`pytest tests/unit tests/contracts` 1490 通过；Windows 上另有 95 失败 + 6 错误，**全是平台差异**（文件锁、`os.fchmod`、符号链接、GBK 解码、路径分隔符），不是逻辑错误。不要去修它们。
- 密钥：项目根 `ds.txt`（DeepSeek）、`openai.txt`，已在 `.gitignore`。
- 未跟踪目录：`data/`、`docs/superpowers/`、`docs/reports/expansion-progress.md`、`pre/`、`proposal_presentaion/`，都别提交。

## 4. 第一步做什么（波次 0，1 天）

目的：确认反馈页能显示逐句模型建议，以及 JUDGE 槽能用。远端命令是 `sh` 写的，Windows 下用 PowerShell 等价写法：

```powershell
cd D:\HuaweiMoveData\Users\13736\Desktop\AIS\5002GPJ
$env:PYTHONUTF8='1'
mkdir runs\local\dev -Force
# 双语场景目录
uv run --locked python -c "import sys; from pathlib import Path; from scripts.regression.published import write_catalog; write_catalog(Path(sys.argv[1]))" runs/local/dev/catalog.json
# 凭据密钥（服务要求有，内容随便）
$env:CAREER_LAB_SCENARIO_CATALOG="$PWD\runs\local\dev\catalog.json"
$env:CAREER_LAB_SCENARIO_ARCHIVE="$PWD\runs\local\dev\archive"
$env:CAREER_LAB_CREDENTIAL_KEY_ID='local-dev-v1'
$env:CAREER_LAB_CREDENTIAL_KEY='local-development-key-at-least-32-bytes-long-0000'
# 合成线性回传（远端自带的机制演示）：按 HANDOVER "没有负责方产物时怎样演示模型建议" 用 scripts.regression.model_flows.build("linear", out) 生成环境变量，然后在 API 与 worker 两个终端都设上
# 终端 1
uv run --locked career-lab serve --host 127.0.0.1 --port 18562 --database-url sqlite:///runs/local/dev/rolecraft.db --provider local
# 终端 2
uv run --locked career-lab worker --database-url sqlite:///runs/local/dev/rolecraft.db --provider local
# 终端 3
cd apps\web; npm ci; npm run build; $env:ROLECRAFT_API_TARGET='http://127.0.0.1:18562'; npm run preview -- --port 18560
```

打开 http://127.0.0.1:18560/ ，新建练习，写一份含"有据可查"或"豁免"字样的作品并提交，反馈页应出现逐句建议和"合成机制演示"标识。然后把 JUDGE 槽指向 DeepSeek（`CAREER_LAB_JUDGE_PROVIDER` 等变量，见 `src/career_lab/runtime/model_slots.py` 开头的说明和 W08 "模型槽配置"），再提交一次，语义评分项应从"待核验"变成有标签。

这一步如果卡在 Windows 平台问题上（`fcntl`、文件锁），改用 WSL 或组里的 Mac 起服务；训练和数据生成不受影响。

## 5. 随后的顺序

见选型文档第 5 节的波次表。要点：

- **数据先行**（波次 1，3 天）：脚本运行器走 HTTP API 跑 8 种策略 × 40 条会话（这批同时是 C5 的轨迹和 C1 的真实作品句来源）；`datasets.v3 export --live --relation-units` 导出作品句；DeepSeek 按生成矩阵写中英各 2,000 条断言，第二遍盲判复核；C4 的查询集中英各 300。
- **C1 在 Colab T4 训练**，导出必须在本机 `.venv-encoder`（CPU、torch 2.8.0）下跑 `docs/data/return-v3/reference/export_hf_return.py export` 与 `predict`，再 `registry_cli register --scope external_candidate`。
- C2、C4 可与数据并行；C5 建模在数据出来后；C10 和界面署名、识别实验室页在波次 3。
- 实验全部分语言报告。test 只在冻结后跑一次。

## 6. 坑（都是 10-16 实测过的）

1. **Windows 写文件**：任何会被 hash 校验的文件（`SHA256SUMS`、JSON 清单、回传包）一律 `open(..., encoding="utf-8", newline="\n")`。`write_text` 默认写 `\r\n`，远端自检脚本会把每个文件报成 `file_missing`。
2. **`PYTHONUTF8=1`** 常开，否则远端代码里没写 `encoding` 的 `read_text` 在中文 Windows 上按 GBK 解码报错。
3. **工作区换行**：`.gitattributes` 是 `eol=lf`，但旧 checkout 残留过 26 个 CRLF 文件导致 hash 保护测试失败；已用 `git rm -r --cached . && git reset --hard` 重写。换目录重新 clone 不会有这个问题。
4. **Hugging Face 下载**：直连 huggingface.co 下 400 MB 权重会中途断；用 `curl -sL -C - --retry 3` 从 `https://hf-mirror.com/<repo>/resolve/main/<file>` 逐文件下到本地目录，再 `from_pretrained(本地目录)`，并设 `HF_HUB_OFFLINE=1`。先用 `https://huggingface.co/api/models/<repo>` 查文件列表。
5. **transformers 在这台机器**：任何 import 之前设 `USE_TF=0`、`HF_HUB_DISABLE_SYMLINKS=1`。
6. **CPU 吞吐**（Ultra 7 155H，序列长 64，batch 16）：BERT-base 级模型冻结底部 8 层每秒 3.6 条；XLM-R base 前向成本同 BERT-base（多出的参数在词表，冻结）。一万句对一轮约 45 分钟。所以训练去 Colab。
7. **远端 `reference_agent` 和 `RunJournal` 用了 `fcntl`**，Windows 跑不了。C5 的轨迹用自己写的 HTTP 脚本运行器生成。
8. **改 `src/career_lab/models/**` 下任何文件后，已登记的模型要重新 `register` 一次**（注册身份锁了这个目录的源码 hash）。两条命令，不是问题，但别忘。
9. **远端契约指纹**：改 `contracts/`、`api/app.py` 等指纹内文件会让 `tests/contracts` 的导出一致性测试失败。按本期标准忽略，PR 说明里写一句"演示版，契约未重导出"。

## 7. 待组内确认（默认值已写进选型文档）

- 编码器底座 XLM-R base（双语要求）；若 Colab 不可用则本机冻结底层训，时间翻倍。
- C10 做到什么程度：默认做"依据核查"，泄露检测有余量再做。
- 代价矩阵默认 误扣分 3 / 错误放行 1 / 送人工 0.5。
- 组员实玩与 Agent 实玩各几条轨迹：默认每人 3 条、Claude Code 经 MCP 3 条。

## 8. 本会话留下的其他东西

- 课件清单：三门课（PSUPR、PRMLS、ISSM）的逐日方法清单已压缩进 v3 文档第 13.1 节；写报告的"课程对应"章节直接用 13.5 节的表。
- 实测数据：v3 文档附录 A（中文 NLI 零样本 10 条、CPU 吞吐表）。
- 本地 `docs/superpowers/` 下 10-04、10-06 的两份旧规范已被远端实现超过，只作历史参考。
