# RoleCraft

**RoleCraft 是面向 AI 产品经理的工作模拟与证据反馈项目。** 用户在有业务目标、约束和信息差的空间中，自主组织工作，与经理、业务负责人、技术负责人协作，使用自己的 Agent，形成作品、试错并依据结果调整判断。当前核心任务是企业知识助手试点决策。

当前实现包含 [工作台 v4](apps/web/README.md)、FastAPI 后端、独立 worker 和命令行演示。工作台、第一批后端接口、Agent UI 第一／二阶段、调查工作纸与资料／作品动效已通过 PR #1–#5 合入 `main`，整合基线为 `2e1e4ff`。尚未公开部署这一组合版；独立离线 DEMO 不代表现行连接版能力。本文按已合并源码及既有验收记录说明现状，环境重新安装后仍需现场验证。

## 已确认的产品原则

- 首版聚焦 AI 产品经理、知识助手试点任务及三个同事角色；工程师岗位、工程代码执行和案例面试仍为后续扩展。
- 用户决定问题、事项和优先级；阅读、对话、写作、测试、求助与修订可以交错，允许犯错或暂时没有方向，不强制固定能力顺序。
- 过程允许多种作品。最终决定需要覆盖用户范围、知识范围、容量、更新政策、兜底方式、工作项、验收测试、成功指标与退出条件；这些业务语义不限定唯一表单或创作顺序。
- 三位同事应依据各自职责、诉求、可见信息和权限回应。当前已实现权限视图与单回合对话，持续记忆、主动协作仍需补齐。
- 自带外部 Agent 是通用协作入口。当前使用任务包与手动回传；回传、采用、执行、验证和业务批准分别记录，不因接入 Agent 自动开放任意代码运行。
- 评价目标是依据作品用途、当时可知信息、实际行动及修订提供可追问反馈。固定六维 rubric 是当前案例基线，不规定工作步骤，也不穷尽个人能力；Agent 产物或一次失误不能直接证明用户独立能力。

这些原则承接 2026-10-04 的开放工作定义及 10-05 的前端／手动 Agent 实施确认。详细工程约束进入[技术设计](docs/design/career-training-technical-design.md)，新增工作进入[实施计划](docs/plans/career-training-implementation-plan.md)。

## 当前保存与能力边界

| 内容 | 当前实现 | 尚未实现 |
|---|---|---|
| 事项与开放作品 | 浏览器保存任务、优先级、Markdown／测试作品／调查、草稿、版本、引用与个人判断 | 服务端开放作品模型、跨设备同步及全过程评价 |
| 对话 | 后端保存问题、回复、时间及事项／作品／附件关联 ID，可凭会话凭据恢复 | 关联 ID 不进入模型提示词；跨回合记忆、附件对象读取和真实主动提醒 |
| 正式交付 | 后端保存固定六字段交付稿的多个版本，并固定提交及配置快照；所选作品可合入依据文本 | 提交后关联修订；当前提交后只读 |
| 外部 Agent | 导出选定上下文，手动带回、预览、检查、采用；受控测试与调查模块调用真实 API | MCP／直连、内置生成 Agent、持续自动同步、临时任意代码画布 |
| 反馈与 Judge | 后端 `rules-v3` 检查与待复核反馈；前端规则观察；实验性 shadow 关系判断 | 完整情境化语义 Judge；开放作品与修订轨迹的可靠评价；SFT／GRPO |

浏览器工作区以域名和端口隔离，保存了本地作品及会话凭据。服务端恢复需要 session ID 和 token；没有用户账号、服务端练习列表或自动跨设备同步。测试、保存、采用与提交分别表示不同状态，不能相互代替。

## 已实现

- **场景引擎**：一个主场景、两个可玩变体，包含角色权限、政策更新、扩容和资源延期规则。
- **可靠状态保存**：PostgreSQL / SQLite、事件与快照、乐观锁、幂等请求、历史回放。
- **角色对话**：经理（后端称主管）、业务负责人、技术负责人具有独立授权材料视图；有界工具循环、DeepSeek / OpenAI 兼容适配器。10/3 后端报告留有 DeepSeek 实调证据；默认本机路径使用不访问外部模型的 `local` 模式。
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

依赖以 `uv.lock` 和 `apps/web/package-lock.json` 为准。Python 项目要求 3.11 及以上，现有验收使用 3.12；前端要求 Node.js 22.12 及以上和 npm。默认本机演示不需要 API key、GPU 或 Docker。

首次获取仓库并安装自身环境：

```sh
git clone https://github.com/yhnapoleon/rolecraft.git
cd rolecraft
uv sync --locked --python 3.12
mkdir -p runs/local
```

无前端的后端演示：

```sh
uv run --locked career-lab demo --database-url sqlite:///runs/local/demo.db --output runs/local/demo.json
```

演示会执行材料、角色回合、政策／索引变化、配置、提交、反馈和重开回放。其数据库与输出是本机运行资料，不进入 Git。

体验当前工作台请按[前端启动说明](apps/web/README.md#启动)建立独立环境与新数据库。默认本机入口为前端 `http://127.0.0.1:18560/`、API／Swagger `http://127.0.0.1:18562/docs`；API 和 worker 必须共用同一数据库。不要从其他 worktree 复制虚拟环境、密钥或数据库，旧浏览器记录也不会因换目录自动迁移。

## PostgreSQL 与真实模型

以下命令使用 PowerShell。两个终端都要设置相同的数据库环境变量。

```powershell
docker compose up -d --wait
$env:CAREER_LAB_DATABASE_URL='postgresql+psycopg://career_lab:local-development-only@127.0.0.1:55439/career_lab'
uv run career-lab serve --host 127.0.0.1 --port 18562 --provider deepseek
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

密钥文件由使用者在本地配置，已加入 `.gitignore`。仓库不分发 API 密钥。DeepSeek 历史实调记录见[10/3 后端报告](docs/reports/final-results.md)，不代表当前机器已经配置；OpenAI 适配器尚无真实请求验收记录。角色对话不能直接批准资源或修改权威状态，启用角色模型也不会自动启用生成式知识助手。

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
| `POST /sessions/{id}/tests`、`GET /sessions/{id}/tests` | 运行并恢复知识助手测试，保留配置及来源版本 |
| `POST /sessions/{id}/artifacts`、`GET /sessions/{id}/artifacts` | 保存和恢复六字段交付稿的多个版本 |
| `POST /sessions/{id}/submissions`、`GET /sessions/{id}/submissions` | 固定和恢复提交快照；提交后只读 |
| `POST /sessions/{id}/feedback` | 创建反馈任务 |
| `GET /sessions/{id}/feedback/{submission_id}` | 获取保存的反馈 |
| `GET /sessions/{id}/timeline` | 历史回放，含对话原文、时间与上下文 ID |
| `GET /sessions/{id}/evidence/{sub}/{criterion}/{eid}` | 查看固定时点的评审依据 |
| `POST /sessions/{id}/relation-checks` | 实验性关系判断，仅作人工复核辅助 |

创建会话时可选 `pm_pilot`、`pm_pilot_urgent`、`pm_pilot_capacity15`。动作／审批请求携带 `request_id` 与 `expected_version`；测试、交付稿、提交和对话各有自己的幂等及版本契约，创建会话目前不支持幂等键。完整 19 个 HTTP 操作与请求结构见 [API 源码](src/career_lab/api/app.py)及运行服务的 Swagger。

主场景初始容量30人、开发资源3人日、第7天上线；第3次计数动作触发政策更新（当前包括阅读、角色回合、测试、配置、交付稿保存和审批等，暂停／恢复除外），住宿报销上限由500变为400。源文档更新不会自动刷新旧索引。50人实时同步方案需要分别申请扩容及额外资源/延期，也可以选择稳定知识的小范围试点。

现有固定六维 rubric 是这个版本 PM 案例的评价基线，不规定用户工作顺序，也不穷尽 AIPM 能力。后续情境化 Judge 将按作品用途、当时信息、行为和修订证据选择适用依据；未观察到的表现不自动判为能力不足。九项业务交付语义继续保留，现有六字段成果加试点配置的接口边界见前端 README。

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
uv run --locked career-lab serve --host 127.0.0.1 --port 18562 --database-url sqlite:///runs/local/rolecraft.db --provider local
```

更多说明：[复现手册](docs/data/experiments-v2-runbook.md) · [场景矩阵](docs/data/scenario-matrix-v2.md) · [标注规范](docs/data/annotation-guide-v2.md)。

## 测试与验证

```powershell
uv run --locked pytest tests apps/web/tests/test_existing_backend.py -q
# 启动Docker数据库后，可额外启用真实PostgreSQL测试：
$env:CAREER_LAB_TEST_PG='postgresql+psycopg://career_lab:local-development-only@127.0.0.1:55439/career_lab'
uv run pytest -q
```

既有记录分为两个阶段：10/3 受控 v2 报告记录 81 项测试通过（含 PostgreSQL）及独立解压复现；10/5 PR #5 整合记录为后端与接口契约 184 项通过、1 项 PostgreSQL 未配置而跳过，前端 94 项 Vitest（含 6 项真实 HTTP/worker）及 72 项状态回归通过。详见[025 整合验证](apps/web/README.md#025-整合验证)。这些是对应版本与环境的历史验收，不代表本次新环境安装已验证。既有 AnyIO/Starlette 弃用警告仍须按运行结果报告。

测试临时目录为 `.pytest_cache/tmp`；不要存放人工文件，并行测试需另设 `--basetemp` 和缓存目录。

## 项目结构

```text
apps/web/         本地连接版前端与独立 DEMO 入口
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

- [实施进度](docs/reports/implementation-progress.md)
- [技术设计](docs/design/career-training-technical-design.md)
- [后端实施计划](docs/plans/career-training-implementation-plan.md)
- [场景与实验计划](docs/plans/scenario-experiments-plan.md)
- [用户试用方案](docs/user-study/protocol.md)

后续缺口包括事项与开放作品服务端保存、三角色持续上下文、提交后关联修订、外部 Agent 直连接口、情境化 Judge 的契约与人工校准，以及真人双标、证据选择、真实用户试用和 SFT／GRPO 实验。工作台 v4、结构化 Agent 回传、调查与动效已有实现；新增工作按[接口需求](docs/design/frontend-interface-requirements.md)和[实施计划](docs/plans/career-training-implementation-plan.md)确定范围。

实施报告中的“前端排除”“尚未建立 Git 仓库”等只对应报告当时的轮次。已有原子分类和固定提交反馈仍可复用，其实验指标不能直接证明开放工作评价可靠或用户已经学会。

### 同学的目标架构提议

分支 `chore/ignore-presentation-files` 保存了[2026-10-04 目标架构稿](https://github.com/yhnapoleon/rolecraft/blob/chore/ignore-presentation-files/docs/superpowers/specs/2026-10-04-rolecraft-target-architecture-design.md)。其中 A 是可执行职业环境，B 是平台参考 Agent 的运行与能力路线；Jev 结构化判断、技能记忆和离线自动优化属于该分支提出的扩展。该稿尚未合入 main，也尚未确认为本轮实施基线；其“目标架构定稿”等自述不替代本仓库已确认原则和当前授权。讨论采用前需核对新增范围、接口、验证与资源，不自动采纳或合并。

本仓库包含项目源码、场景、配置、复现脚本和报告；本地密钥、数据库、环境、原始数据、个人标注记录与课程原始资料不上传。
