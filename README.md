# RoleCraft

**RoleCraft 是一个面向 AI 产品经理的职业任务模拟与证据反馈后端。** 用户在模拟企业中阅读材料、咨询不同角色、配置和测试知识助手、申请资源并提交方案；系统保存每一步状态，提供可追溯的规则反馈和实验性关系判断。

本项目用于 ISY5002 课程实践，覆盖监督学习、ML/DL 与 Hybrid/Ensemble 三类技术。目前提供 API 和命令行演示，前端与 SFT/GRPO 后训练尚未实现。

## 已实现

- **场景引擎**：一个主场景、两个可玩变体，包含角色权限、政策更新、扩容和资源延期规则。
- **可靠状态保存**：PostgreSQL / SQLite、事件与快照、乐观锁、幂等请求、历史回放。
- **角色对话**：有界工具循环、授权材料读取、DeepSeek / OpenAI 兼容适配器；DeepSeek 已真实联调。
- **知识助手**：BM25 检索、独立的源文档/索引版本、配置测试、结构化成果与固定版本提交。
- **反馈链路**：确定性约束检查、证据链接、分数区间、待核验状态和补练建议。
- **后台任务**：独立 worker、持久化 jobs、租约、心跳与有限重试。
- **实验管线**：受控数据生成、标注工作包、监督训练、概率融合、独立评测、实验冻结及辅助判断 API。

```mermaid
flowchart LR
    U[用户 / API客户端] --> API[FastAPI]
    API --> W[场景状态与事件]
    API --> J[后台任务 / Worker]
    J --> L[角色模型与授权工具]
    W --> DB[(PostgreSQL / SQLite)]
    W --> E[提交快照与证据包]
    E --> F[规则反馈与历史回放]
    D[受控数据] --> T[训练与独立评测]
    T --> R[冻结模型与实验记录]
    R --> S[需要人工复核的辅助判断]
    E --> S
```

## 快速开始

已验证环境：Python **3.12.13**，Windows；依赖版本锁定在 `uv.lock`。安装前准备 Git 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。默认演示不需要 API key、GPU 或 Docker。

```powershell
git clone https://github.com/yhnapoleon/rolecraft.git
cd rolecraft
uv sync --locked --python 3.12
uv run career-lab demo --output runs/demo.json
```

演示会完成读取材料、角色回合、政策更新、旧索引测试、调整方案、提交、反馈和数据库重开回放。详细输出保存在 `runs/demo.json`。

启动 API：

```powershell
uv run career-lab serve --port 8502
```

另开终端，在同一项目目录启动 worker：

```powershell
uv run career-lab worker
```

打开 [Swagger API 文档](http://127.0.0.1:8502/docs)。两个进程默认共用项目目录中的 `career_lab.db`；角色对话和反馈任务需要 worker 执行。

## PostgreSQL 与真实模型

以下命令使用 PowerShell。两个终端都要设置相同的数据库环境变量。

```powershell
docker compose up -d --wait
$env:CAREER_LAB_DATABASE_URL='postgresql+psycopg://career_lab:local-development-only@127.0.0.1:55439/career_lab'
uv run career-lab serve --port 8502 --provider deepseek
```

另一个终端：

```powershell
$env:CAREER_LAB_DATABASE_URL='postgresql+psycopg://career_lab:local-development-only@127.0.0.1:55439/career_lab'
uv run career-lab worker --provider deepseek
```

Compose 使用本机端口 **55439**，其中的账号密码仅用于本地开发。`docker compose stop` 停止数据库并保留数据卷。

| 配置 | 用途 |
|---|---|
| `--provider local` | 默认本地提取式角色回复 |
| `--provider deepseek` | 默认读取项目根目录的 `ds.txt` |
| `--provider openai` | 默认读取项目根目录的 `openai.txt` |
| `CAREER_LAB_KEY_FILE` | 自定义密钥文件路径 |
| `CAREER_LAB_BASE_URL` | 自定义兼容接口地址 |
| `CAREER_LAB_MODEL` | 自定义模型名称 |
| `CAREER_LAB_DATABASE_URL` | API 与 worker 共用的数据库 |
| `CAREER_LAB_STUDY` | 已冻结并完成评价的辅助模型实验目录 |

密钥文件由使用者在本地创建，已加入 `.gitignore`。仓库不包含 API 密钥。DeepSeek 已实调；OpenAI 适配器已实现，尚未进行真实 OpenAI 请求验证。模型对话不能直接批准资源或修改权威状态。

## API 使用流程

1. `POST /sessions` 创建会话，保存返回的 `session_id` 与 `token`。
2. 后续请求添加 `Authorization: Bearer <token>`。
3. 读取材料、执行操作、发起角色对话、测试助手并提交成果。
4. 通过 worker 生成反馈，读取证据和历史过程。

| 接口（会话内） | 作用 |
|---|---|
| `GET /sessions/{id}` | 当前状态 |
| `GET /sessions/{id}/materials` | 当前或历史可见材料 |
| `POST /sessions/{id}/actions` | 配置试点、申请资源、刷新索引、暂停/恢复 |
| `POST /sessions/{id}/approvals/resolve` | 按场景规则处理已提交的扩容或延期申请 |
| `POST /sessions/{id}/turns` | 创建角色对话任务 |
| `GET /sessions/{id}/jobs/{job_id}` | 查询任务状态 |
| `POST /sessions/{id}/tests` | 运行知识助手测试并保存版本 |
| `POST /sessions/{id}/artifacts` | 保存结构化成果 |
| `POST /sessions/{id}/submissions` | 固定提交快照 |
| `POST /sessions/{id}/feedback` | 创建反馈任务 |
| `GET /sessions/{id}/feedback/{submission_id}` | 获取保存的反馈 |
| `GET /sessions/{id}/timeline` | 历史回放 |
| `POST /sessions/{id}/relation-checks` | 实验性关系判断，仅作人工复核辅助 |

创建会话时可选 `pm_pilot`、`pm_pilot_urgent`、`pm_pilot_capacity15`。业务动作使用 `request_id` 和 `expected_version`，防止重复写入及覆盖并发更新。完整请求结构和证据接口见 Swagger。

主场景初始容量30人、开发资源3人日、第7天上线；第3次有效业务操作触发政策更新，住宿报销上限由500变为400。源文档更新不会自动刷新旧索引。50人实时同步方案需要分别申请扩容及额外资源/延期，也可以选择稳定知识的小范围试点。

## 数据与课程实验

最新受控实验 **v2** 包含 **1,152条中文 G0 样本**，来自6类能力、24个作者定义的逻辑结构；train/dev/test 为 **576/288/288**。每个事实根包含支持、矛盾、缺失及两种表达，使用8条候选材料。改写及其正反例固定在同一分区。

课程三项技术对应：

| 类别 | 实现 |
|---|---|
| 监督学习 | 有标签的结论—证据关系三分类 |
| ML / DL | TF-IDF＋逻辑回归、字符特征＋MLP |
| Hybrid / Ensemble | 概率融合、有限规则＋分类模型 |

v2固定实验结果如下；完整指标、检索实验和稳健性实验见[结果报告](docs/reports/controlled-v2-results.md)。

| 候选 | dev Macro-F1 | test Macro-F1 |
|---|---:|---:|
| 线性模型 | 0.5455 | 0.4275 |
| MLP | 0.3692 | 0.3587 |
| 概率融合 | 0.5455 | 0.4275 |
| 有限规则＋模型 | 0.7076 | 0.6496 |

融合权重在dev上选为0，没有带来增益。混合模型在test上的误扣分率为33.3%，未达到预设自动评分门槛。学习模型目前引用全部候选材料，证据选择质量仍需改进。

这些是**程序可验证的受控合成结果**。24个逻辑模板不代表24个独立真实业务场景；人工双标、真实用户试用及完整语义评价尚未完成。辅助接口固定返回 `mode=shadow`、`review_required=true`、`affects_score=false`，不改动正式评分。

### 复现 v2

在全新输出目录依次运行：

```powershell
uv run python scripts/prepare_experiments.py pilot
uv run python scripts/prepare_experiments.py annotations
uv run python scripts/prepare_experiments.py release
uv run career-lab train-baselines --manifest data/releases/controlled-v2/manifest.json --output runs/models/controlled-v2
uv run python scripts/run_controlled_experiments.py dev
uv run python scripts/run_controlled_experiments.py freeze
uv run python scripts/run_controlled_experiments.py test
uv run python scripts/report_controlled_experiments.py
```

生成器拒绝覆盖已有数据或模型目录。`annotations` 读取两份本地标注表，空表会如实返回 `pending`；不会自动生成真人标注。冻结后源码、模型或结果漂移会被拒绝，test不用于继续调参。每个新版本需使用独立目录；已看过的test不能继续作为新的未见选型集。

训练模型、合成数据和原始实验缓存通过命令重建，未纳入Git。此前90条中文pilot和85项ContractNLI导入记录保留在报告中；公开数据获取脚本为 `scripts/import_public_pilot.py`，来源和许可证见[来源记录](docs/reports/task-07-public-source.json)。

辅助接口启用方法：

```powershell
$env:CAREER_LAB_STUDY='runs/controlled-v2'
uv run career-lab serve --port 8502
```

更多说明：[复现手册](docs/data/experiments-v2-runbook.md) · [场景矩阵](docs/data/scenario-matrix-v2.md) · [标注规范](docs/data/annotation-guide-v2.md)。

## 测试与验证

```powershell
uv run pytest -q
# 启动Docker数据库后，可额外启用真实PostgreSQL测试：
$env:CAREER_LAB_TEST_PG='postgresql+psycopg://career_lab:local-development-only@127.0.0.1:55439/career_lab'
uv run pytest -q
```

截至2026-10-03，已验证 **81项测试通过**（含真实PostgreSQL）。不配置PostgreSQL时为80通过、1项跳过。独立解压环境的16条安装/数据/训练/评价命令也已通过，主要实验指标复现一致。当前有一条上游AnyIO/Starlette弃用警告。

测试临时目录为 `.pytest_cache/tmp`；不要存放人工文件，并行测试需另设 `--basetemp` 和缓存目录。

## 项目结构

```text
src/career_lab/
  contracts/     场景、动作、证据与评价协议
  scenarios/     场景加载、状态转换和权限投影
  storage/       事务、事件、快照与对象存储
  runtime/       角色回合、模型适配器与工具路由
  jobs/          后台任务、租约和worker
  assistant/     检索、测试与提交服务
  evidence/      固定时点证据组装与输入隔离
  rubrics/       规则反馈、分数区间和补练
  datasets/      受控数据、公开数据导入与标注
  models/        CPU监督模型与融合
  evals/         独立grader、指标与可恢复runner
  experiments/   对照实验、来源校验与冻结
  registry/      模型产物与报告身份校验
  api/           FastAPI接口
scenarios/       可运行场景、材料、rubric及hash清单
configs/         模型与评价配置
scripts/         数据、实验、报告和交付复现入口
tests/           单元、集成和端到端测试
docs/            设计、计划、规范及验证报告
```

## 进度与后续

- [最终目标技术框架 v2：A/B 并重、主动信息获取、技能记忆、自动优化与 Jev](docs/superpowers/specs/2026-10-04-rolecraft-target-architecture-design.md)（目标设计，非已实现能力清单）
- [实施进度](docs/reports/implementation-progress.md)
- [技术设计](docs/design/career-training-technical-design.md)
- [后端实施计划](docs/plans/career-training-implementation-plan.md)
- [场景与实验计划](docs/plans/scenario-experiments-plan.md)
- [用户试用方案](docs/user-study/protocol.md)

后续工作包括真人双标与裁决、证据选择和语义评价改进、真实用户试用及课程展示材料。前端、SFT、GRPO仍未实施。部分历史文档记录了当时“尚未建立Git仓库”的状态，该描述仅对应历史实施阶段。

本仓库包含项目源码、场景、配置、复现脚本和报告；本地密钥、数据库、环境、原始数据、个人标注记录与课程原始资料不上传。
